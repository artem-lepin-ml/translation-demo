"""Live terminology pipeline: NER -> Wikidata grounding -> disambiguation
judge -> target pairing, run automatically in the background for a
newly-created document (2026-07-11 EMNLP-sprint lane B2).

Mirrors ``precompute.py``'s/``translate.py``'s async launch/status pattern,
with one deliberate difference: ``document.terms_status`` is a persisted DB
column (see ``migrate.py``), not an in-memory dict. That does NOT make a
restart free of risk on its own (stability fix, 2026-07-16): a restart kills
the in-flight asyncio task without ever reaching ``_finish()``, and the
persisted column just keeps reporting the stale ``running`` value forever --
worse than precompute/translate's in-memory dicts, which merely forget the
status on restart rather than actively lying about it. The actual recovery
is a startup sweep in ``app.py``'s lifespan (``_reset_stuck_terms``, runs
right after ``migrate()``): no in-process terminology task can possibly
exist for any doc_id immediately after a fresh process start, so every
document still at 'running' at that point is unconditionally stale and gets
reset to 'none'.

Every grounding/pairing decision reuses the FROZEN terminology module
unmodified (``extract.py``, ``grounding/label_first.py``,
``pairing/link_locate.py``, ``pipeline.py``) -- this module is glue only
(LLM/DB wiring), per the project convention "reuse, never reimplement".
Grounding uses plain ``GroundingConfig()`` defaults (``search_mode`` stays
``"baseline"`` -- the pinned config, see ``grounding/candidates.py``).
Pairing uses ``LinkLocatePairing`` (P1, deterministic, no extra judge call)
-- the same strategy ``scripts/term_pipeline.py``'s ``cmd_run`` used to
build ``data/seed/terminology_out.json`` (loaded into the ``term`` table by
``scripts/load_terms.py``). Note: ``scripts/enrich_seed_terms.py`` is NOT
that reference despite its name -- it only enriches the older
``seed_paragraphs.jsonl`` mock structure with grounding (qid/resolved_by),
has no pairing logic at all, and never writes to the ``term`` table; the
real seed generator is ``term_pipeline.py``.

Difficulty is not computed here -- ``LabelFirstGrounding.ground()`` already
returns the correct green/yellow/red per its own frozen decision table
(module docstring of ``grounding/label_first.py``): exact_label -> green;
llm_disambiguation/judge_unavailable -> yellow; judge_rejected/
no_candidates/wikidata_unavailable -> red. This module only has to supply a
working ``judge`` callable so the live pipeline actually escalates to a real
LLM call instead of always degrading to judge_unavailable.

Async/sync bridge (the one non-obvious piece). ``pipeline.run()`` and the
G6 strategies it calls are entirely SYNCHRONOUS by design (``Judge =
Callable[[str], dict]``, no await) -- the same strategy code runs unmodified
in the sync CLI eval harness (``scripts/wiki_eval.py``) and here. But the
live disambiguation judge must go through ``app._grounding_judge_live``,
which is ASYNC (``budget.reserve()``/``settle()`` are asyncio-lock-based
coroutines) so it shares budget accounting with every other live LLM call.
The bridge: each paragraph's whole ``pipeline.run()`` call (grounding +
pairing, including WikidataClient's blocking ``urllib`` calls) runs inside
``asyncio.to_thread`` off the event loop; the plain-sync ``judge`` callable
it receives schedules the async ``grounding_judge_live`` coroutine back onto
the ORIGINAL event loop via ``asyncio.run_coroutine_threadsafe(...).result()``
-- the standard pattern for a worker thread calling back into loop-owned
async primitives.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone

from ..llm.client import is_transient_error
from ..terminology import pipeline
from ..terminology.base import GroundingConfig, TermMention
from ..terminology.extract import (
    NER_SYSTEM_PROMPT,
    mentions_from_surfaces,
    ner_user,
    parse_surfaces,
    validate_surfaces,
)
from ..terminology.grounding import LabelFirstGrounding
from ..terminology.pairing import LinkLocatePairing
from ..terminology.wikidata import WikidataClient
from . import budget, db
from .model_matrix import additive_reasoning_tokens
from .secrets_guard import redact_error

logger = logging.getLogger(__name__)

# First-N-paragraphs cap, mirrors precompute.PRECOMPUTE_PARAS; env-overridable
# like precompute's own call sub-cap (PALIMPSEST_PRECOMPUTE_CALLS).
TERMS_PARAS = int(os.environ.get("PALIMPSEST_TERMS_PARAS", "12"))

_NER_TIMEOUT = float(os.environ.get("PALIMPSEST_TERMS_TIMEOUT", "20"))
_NER_RETRIES = int(os.environ.get("PALIMPSEST_TERMS_RETRIES", "2"))
_NER_BACKOFF = float(os.environ.get("PALIMPSEST_TERMS_BACKOFF", "0.5"))

# Margin the NER leg's wait_for ceiling must clear above the actual SDK
# client timeout (LLMConfig.timeout, 30s default in llm/client.py) -- stability
# fix (2026-07-16): the env-overridable default above (20s) used to be
# SHORTER than the SDK timeout, so asyncio.wait_for fired first and abandoned
# a still-running SDK call (the retry loop then started a SECOND concurrent
# call against the same provider instead of actually giving up). See
# ``_effective_ner_timeout``, which enforces the ordering at call time against
# the REAL client instead of hardcoding a duplicate "30" here -- single
# source of truth stays ``LLMConfig.timeout``.
_TIMEOUT_MARGIN = 5.0

# Per-paragraph ceiling on the whole grounding+pairing pipeline call (NER is
# already extracted and timed separately above; this wraps the SEPARATE
# ``pipeline.run`` call -- WikidataClient network I/O, own 15s-timeout x
# 5-attempt retry loop per fetch, see wikidata.py -- plus zero or more
# disambiguation judge calls, each already individually bounded by
# app.py's EVAL_TIMEOUT/EVAL_RETRIES). Stability fix (2026-07-16): this leg
# previously had NO ceiling at all, so a hung/deadlocked worker thread (or a
# pathological paragraph with many ambiguous mentions) could block a
# paragraph -- and therefore the whole document's terms_status='running' --
# indefinitely. Deliberately generous (unlike the NER leg's SDK-aligned
# ceiling above): nothing here should legitimately take this long, this is
# defense-in-depth only, matching the "never stuck at running forever"
# invariant the app.py startup sweep also enforces at the document level.
_GROUNDING_TIMEOUT = float(os.environ.get("PALIMPSEST_TERMS_GROUNDING_TIMEOUT", "180"))

# Safety floor for the NER call's max_tokens: grounding_config's own params
# are tuned for the disambiguation judge's short {"qid":...,"reason":...}
# reply (webapp default 512, see migrate.py's GROUNDING_DEFAULT_PARAMS) --
# far too small for a dense paragraph's [{surface,lemma,category}, ...]
# array, which would silently truncate mid-JSON and turn every paragraph
# into a parse failure. There is no dedicated "NER config" row in this DB
# (the task reuses grounding_config's MODEL for both roles); this floor is
# applied only to the params bag used for the NER call, never mutating the
# grounding_config row itself or the disambiguation judge's own call.
_NER_MIN_MAX_TOKENS = 2048

# Strong references to in-flight terms tasks, keyed by doc_id (mirrors
# precompute._tasks/translate._tasks). Not currently wired to DELETE
# (app.py's DELETE route is outside this task's authorized edit scope --
# see the delta note in docs/superpowers/specs/2026-06-30-demo-contracts.md
# and the shipped report's "NOT done" list); kept so that wiring is a
# localized future change (``cancel()`` would just do what
# precompute.cancel()/translate.cancel() already do).
_tasks: dict[int, asyncio.Task] = {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _document_exists(conn, doc_id: int) -> bool:
    return conn.execute("SELECT 1 FROM document WHERE id=?", (doc_id,)).fetchone() is not None


def _has_terms(conn, paragraph_id: int) -> bool:
    return conn.execute(
        "SELECT 1 FROM term WHERE paragraph_id=? LIMIT 1", (paragraph_id,)).fetchone() is not None


def try_start(conn, doc_id: int) -> bool:
    """Atomically transition ``terms_status`` 'none' -> 'running'.

    Returns True iff THIS call performed the transition (the caller should
    launch the background run); False when terms already started/finished
    for this doc (idempotent no-op -- e.g. a resumed ``POST
    .../translate`` completing a second time must not re-launch terms).

    Callers that already hold ``db._lock`` (``create_document``, on a
    brand-new never-raced ``doc_id``) must NOT call this -- ``db._lock`` is
    a plain ``threading.Lock``, not reentrant; write the column directly
    instead (see ``app.py``'s ``create_document``).

    This function only handles the 'none' -> 'running' edge -- it has no
    opinion about a doc stuck at 'running' from a dead process. That
    recovery is a separate, startup-only sweep (``app._reset_stuck_terms``,
    called from the lifespan right after ``migrate()``), not this function.
    """
    with db._lock:
        row = conn.execute("SELECT terms_status FROM document WHERE id=?", (doc_id,)).fetchone()
        if row is None or row["terms_status"] != "none":
            return False
        conn.execute("UPDATE document SET terms_status='running' WHERE id=?", (doc_id,))
        conn.commit()
        return True


def _finish(conn, doc_id: int, status: str) -> None:
    with db._lock:
        if not _document_exists(conn, doc_id):
            return
        conn.execute("UPDATE document SET terms_status=? WHERE id=?", (status, doc_id))
        conn.commit()


def launch(doc_id: int, client_for, grounding_judge_live) -> None:
    t = asyncio.create_task(run(doc_id, client_for, grounding_judge_live))
    _tasks[doc_id] = t
    t.add_done_callback(lambda _: _tasks.pop(doc_id, None))


async def run(doc_id: int, client_for, grounding_judge_live) -> None:
    """``client_for`` is ``app._client_for``, ``grounding_judge_live`` is
    ``app._grounding_judge_live`` (both injected to avoid a circular
    import, same pattern as precompute's ``judge_live``/translate's
    ``client_for``). Any uncaught exception (a bug, not an expected
    per-paragraph failure -- those are already caught inside ``_run``)
    still leaves the document in a terminal 'failed' state rather than
    hanging at 'running' forever."""
    try:
        await _run(doc_id, client_for, grounding_judge_live)
    except asyncio.CancelledError:
        raise                                  # propagate — do not touch terms_status further
    except Exception:
        logging.exception("terminology_live.run failed for doc_id=%s", doc_id)
        _finish(db.connect(), doc_id, "failed")


def _effective_ner_timeout(client) -> float:
    """The ``asyncio.wait_for`` ceiling for the NER call, always kept above
    ``client.config.timeout`` (the actual SDK per-request wall clock the
    ``client.complete`` call underneath is bound by) -- otherwise wait_for
    fires first and abandons a still-running SDK call instead of the SDK's
    own timeout ever getting a chance to raise. Derived from the REAL client
    at call time rather than a hardcoded duplicate of ``LLMConfig.timeout``'s
    default, so this stays correct even if that default changes or a caller
    passes a client configured with a non-default timeout."""
    return max(_NER_TIMEOUT, client.config.timeout + _TIMEOUT_MARGIN)


async def _extract_mentions_live(conn, client_for, source: str) -> list[TermMention]:
    """One budget-guarded NER call against the grounding_config model (no
    dedicated NER-config DB surface exists -- the task reuses
    grounding_config's model for both NER and disambiguation). Mirrors
    ``app._grounding_judge_live``'s reserve/settle/retry/timeout shape, but
    is not that function: a different system prompt (frozen
    ``NER_SYSTEM_PROMPT``, byte-identical, never modified here) and a
    different parse step (``parse_surfaces``, not bare ``json.loads``), so
    it cannot share the same closure.

    Raises on a terminal failure (no config / no api key / exhausted
    retries / malformed reply) -- the caller (``_run``) catches this
    per-paragraph and continues, per this module's failure contract.
    """
    row = conn.execute("SELECT * FROM grounding_config WHERE id=1").fetchone()
    if row is None or not row["model_name"]:
        raise RuntimeError("grounding_config not set")
    name = row["model_name"]
    raw = json.loads(row["params_json"] or "{}")
    # Safety floor only for THIS call's params bag — never mutates the
    # grounding_config row or affects the disambiguation judge's own call.
    ner_params = {**raw, "max_tokens": max(int(raw.get("max_tokens") or 0), _NER_MIN_MAX_TOKENS)}
    client = client_for(conn, name, ner_params)
    if client is None:
        raise RuntimeError("no api key for model")

    user = ner_user(source)
    prompt_tok = budget.count_tokens(NER_SYSTEM_PROMPT) + budget.count_tokens(user)
    rmt = additive_reasoning_tokens(name, ner_params)
    est = budget.estimate(name, prompt_tok, client.config.max_tokens, rmt)
    gen = await budget.reserve(est)
    ner_timeout = _effective_ner_timeout(client)
    attempt = 0
    while True:
        try:
            res = await asyncio.wait_for(
                asyncio.to_thread(client.complete, NER_SYSTEM_PROMPT, user), ner_timeout)
            break
        except Exception as exc:
            if is_transient_error(exc) and attempt < _NER_RETRIES:
                err = redact_error(f"{type(exc).__name__}: {exc}")
                budget.log_call({"model": name, "endpoint": "terms_extract", "status": "retry",
                                 "attempt": attempt, "error": err, "costUsd": None})
                logger.warning("terms NER retry: model=%s attempt=%d error=%s", name, attempt, err)
                await asyncio.sleep(_NER_BACKOFF * (2 ** attempt))
                attempt += 1
                continue
            await budget.settle(est, 0.0, gen)
            err = redact_error(f"{type(exc).__name__}: {exc}")
            budget.log_call({"model": name, "endpoint": "terms_extract", "status": "error",
                             "attempts": attempt + 1, "error": err, "costUsd": None})
            logger.warning("terms NER failed terminally: model=%s attempts=%d error=%s",
                            name, attempt + 1, err)
            raise
    await budget.settle(est, res.usage.cost_usd, gen)
    budget.log_call({"model": name, "endpoint": "terms_extract", "status": "ok",
                     "tokens": {"prompt": res.usage.prompt_tokens,
                                "completion": res.usage.completion_tokens,
                                "reasoning": res.usage.reasoning_tokens},
                     "costUsd": res.usage.cost_usd})

    # parse_surfaces raises ExtractionParseError (a ValueError) on a reply it
    # cannot recover a JSON array from — terminal, propagates to the
    # per-paragraph catch in _run, exactly like a malformed judge reply is
    # terminal in label_first.py's own documented error policy.
    surfaces = parse_surfaces(res.content)
    valid, _dropped = validate_surfaces(source, surfaces)
    return mentions_from_surfaces(source, valid)


def _make_sync_judge(conn, grounding_judge_live, loop: asyncio.AbstractEventLoop):
    """Bridge ``LabelFirstGrounding``'s sync ``Judge`` protocol to the async,
    budget-guarded ``grounding_judge_live`` — see module docstring. Runs on
    the worker thread ``pipeline.run()`` executes in (via
    ``asyncio.to_thread``); schedules the coroutine back onto ``loop`` and
    blocks only THIS (worker) thread, never the event loop, until it
    completes. Any exception the coroutine raises propagates through
    ``.result()`` unchanged — ``LabelFirstGrounding.ground()`` already
    treats any judge exception as terminal ``resolved_by=judge_unavailable``
    (see its module docstring)."""
    def judge(prompt: str) -> dict:
        future = asyncio.run_coroutine_threadsafe(
            grounding_judge_live(conn, prompt, endpoint="terms_grounding"), loop)
        return future.result()
    return judge


def _write_paragraph_terms(conn, doc_id: int, paragraph_id: int, terms) -> None:
    """Paragraph-atomic write, one transaction. ``INSERT OR REPLACE`` on the
    ``term`` table's ``UNIQUE(paragraph_id, char_start, char_end)`` — same
    convention ``scripts/load_terms.py`` uses to seed the same table."""
    with db._lock:
        if not _document_exists(conn, doc_id):
            return                              # document deleted mid-flight, discard write
        for t in terms:
            conn.execute(
                "INSERT OR REPLACE INTO term(paragraph_id,source_surface,source_lemma,context,"
                "char_start,char_end,difficulty,grounded_json,candidates_json,target_surface,"
                "pair_accuracy,recommended,note,trace_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                t.db_tuple(paragraph_id),
            )
        conn.commit()


async def _run(doc_id: int, client_for, grounding_judge_live) -> None:
    conn = db.connect()
    d = conn.execute("SELECT * FROM document WHERE id=?", (doc_id,)).fetchone()
    if d is None:
        return
    paras = conn.execute(
        "SELECT * FROM paragraph WHERE document_id=? ORDER BY idx LIMIT ?",
        (doc_id, TERMS_PARAS)).fetchall()

    loop = asyncio.get_running_loop()
    # One WikidataClient instance for the whole document run — warm cache across
    # its paragraphs. Plain GroundingConfig() defaults: search_mode stays
    # "baseline" (pinned). LinkLocatePairing (P1) is deterministic — the same
    # pairing strategy term_pipeline.py used to build the seed's term rows.
    wd = WikidataClient()
    grounder = LabelFirstGrounding(wd, config=GroundingConfig())
    pairer = LinkLocatePairing(wd)
    sync_judge = _make_sync_judge(conn, grounding_judge_live, loop)
    judge_cache: dict = {}          # "one sense per discourse" cache, scoped to scope_id=doc_id

    n_succeeded = 0
    for p in paras:
        if not _document_exists(conn, doc_id):
            return                              # document deleted mid-flight
        if _has_terms(conn, p["id"]):            # idempotent resume / defensive re-entry guard
            n_succeeded += 1
            continue
        try:
            mentions = await _extract_mentions_live(conn, client_for, p["source"])
            terms = await asyncio.wait_for(
                asyncio.to_thread(
                    pipeline.run, p["source"], p["target"] or "", mentions,
                    grounder=grounder, pairer=pairer, judge=sync_judge,
                    scope_id=doc_id, judge_cache=judge_cache,
                ),
                _GROUNDING_TIMEOUT,
            )
        except Exception:
            # Covers a genuine pipeline error AND asyncio.TimeoutError from the
            # wait_for ceiling above — both are per-paragraph failures under
            # this module's failure contract (skip, keep going). Note: like
            # the NER leg, a fired wait_for does not actually stop the
            # abandoned worker thread (an inherent asyncio.to_thread
            # limitation) — it keeps running in the background and any
            # eventual sync_judge callback it makes is harmless (just a
            # wasted call), never touches `terms_status` again.
            logger.exception("terms pipeline failed doc_id=%s paragraph_id=%s", doc_id, p["id"])
            continue                             # per-paragraph failure: skip, keep going
        _write_paragraph_terms(conn, doc_id, p["id"], terms)
        n_succeeded += 1

    status = "failed" if paras and n_succeeded == 0 else "done"
    _finish(conn, doc_id, status)
