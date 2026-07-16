"""Background first-pass AI translation for a source-only uploaded document
(spec 2026-07-05-translator). Mirrors precompute.py's status-registry/
cancellation pattern; the actual LLM call is a plain ``LLMClient.complete``
(no judge JSON schema), with a rolling 2-paragraph context for continuity.
"""
from __future__ import annotations

import os

import asyncio
import json
import logging
import re
from datetime import datetime, timezone

from ..llm.client import LLMClient, is_transient_error
from . import budget, db

TRANSLATE_TIMEOUT = float(os.environ.get("PALIMPSEST_TRANSLATE_TIMEOUT", "20"))
RETRY_ONCE_BACKOFF = 1.0
CONTEXT_CHAR_BUDGET = 2000
ROLLING_CONTEXT_PARAS = 2

# In-memory status per (session_id, doc_id); absent after restart (same
# accepted risk as precompute.py — a restart resets 'running' to nothing, a
# fresh POST resumes idempotently since already-translated paragraphs are
# skipped). Rekeyed for session isolation (2026-07-16) — see db.current_sid().
_status: dict[tuple[str, int], dict] = {}

# Strong references to in-flight translate tasks, keyed by (session_id,
# doc_id) (mirrors precompute._tasks) — required so DELETE can cancel a
# running task.
_tasks: dict[tuple[str, int], asyncio.Task] = {}

# (session_id, doc_id) pairs with a translate run in flight — evaluate/reset
# 409 against these (mirrors app._evaluating).
_translating: set[tuple[str, int]] = set()

_LEADING_LABEL_RE = re.compile(r"^\s*(translation|translated text)\s*:\s*", re.IGNORECASE)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def status_for(doc_id: int) -> dict | None:
    return _status.get((db.current_sid(), doc_id))


def mark_started(doc_id: int, total: int) -> None:
    """Pre-set status so the caller's response already carries it — same
    reasoning as precompute.mark_started (the background task's own first
    write happens after this function returns, on the next event-loop tick)."""
    _status[(db.current_sid(), doc_id)] = {"status": "running", "done": 0, "total": total}


def is_translating(doc_id: int) -> bool:
    return (db.current_sid(), doc_id) in _translating


def _document_exists(conn, doc_id: int) -> bool:
    return conn.execute("SELECT 1 FROM document WHERE id=?", (doc_id,)).fetchone() is not None


def _classify_failure(exc: Exception) -> str:
    """error_reason for a failed/stalled translate run — mirrors
    precompute._classify_failure (no_api_key | budget_exhausted | all_failed)."""
    if isinstance(exc, budget.BudgetExceeded):
        return "budget_exhausted"
    if isinstance(exc, RuntimeError) and "no api key" in str(exc):
        return "no_api_key"
    return "all_failed"


def _strip_label(text: str) -> str:
    """Defend against a leading 'Translation:'-style label the model prepends
    despite the 'output only the translation' instruction."""
    return _LEADING_LABEL_RE.sub("", text.strip()).strip()


def launch(doc_id: int, client_for, terms_launch=None) -> None:
    key = (db.current_sid(), doc_id)
    t = asyncio.create_task(run_translation(doc_id, client_for, terms_launch))
    _tasks[key] = t
    t.add_done_callback(lambda _: _tasks.pop(key, None))


def cancel(doc_id: int) -> None:
    """Stop an in-flight translate run for ``doc_id`` in the CURRENT session
    (called from DELETE) — mirrors precompute.cancel. Session-scoped by
    construction (the key includes db.current_sid()), so a delete in one
    session can never cancel another session's live translate task for the
    same doc_id (session isolation, 2026-07-16)."""
    key = (db.current_sid(), doc_id)
    t = _tasks.get(key)
    if t is not None:
        t.cancel()
    _translating.discard(key)


async def _translate_one(client: LLMClient, system: str, user: str) -> str | None:
    """Budget reserve/settle + one retry on a transient error (spec §3.1).
    Returns None on any terminal failure (budget, no client, deterministic
    error) — the caller counts it as a failed paragraph and moves on."""
    prompt_tok = budget.count_tokens(system) + budget.count_tokens(user)
    est = budget.estimate(client.config.model, prompt_tok, client.config.max_tokens)
    gen = await budget.reserve(est)             # raises BudgetExceeded — propagates to the caller
    attempt = 0
    while True:
        try:
            res = await asyncio.wait_for(
                asyncio.to_thread(client.complete, system, user), TRANSLATE_TIMEOUT)
            break
        except Exception as exc:
            if is_transient_error(exc) and attempt < 1:
                await asyncio.sleep(RETRY_ONCE_BACKOFF)
                attempt += 1
                continue
            await budget.settle(est, 0.0, gen)
            logging.warning("translate call failed terminally: error=%s", exc)
            return None
    await budget.settle(est, res.usage.cost_usd, gen)
    budget.log_call({"model": client.config.model, "endpoint": "translate", "status": "ok",
                     "tokens": {"prompt": res.usage.prompt_tokens,
                                "completion": res.usage.completion_tokens,
                                "reasoning": res.usage.reasoning_tokens},
                     "costUsd": res.usage.cost_usd})
    return _strip_label(res.content or "")


async def run_translation(doc_id: int, client_for, terms_launch=None) -> None:
    """``client_for`` is ``app._client_for`` (injected to avoid a circular
    import, same pattern as precompute's ``judge_live``). ``terms_launch``
    (2026-07-11 EMNLP sprint, optional — existing callers/tests that pass
    only ``client_for`` keep working unchanged) is ``app._terms_launch_
    after_translate``, called once at the successful end of ``_run`` so the
    live terminology pipeline sees the FINAL translated targets."""
    try:
        await _run(doc_id, client_for, terms_launch)
    except asyncio.CancelledError:
        raise                                  # propagate — do not touch _status further
    except Exception:
        logging.exception("translate.run_translation failed for doc_id=%s", doc_id)
        key = (db.current_sid(), doc_id)
        _status[key] = {**_status.get(key, {"done": 0, "total": 0}),
                         "status": "failed", "error_reason": "all_failed"}
    finally:
        _translating.discard((db.current_sid(), doc_id))


async def _run(doc_id: int, client_for, terms_launch=None) -> None:
    conn = db.connect()
    sid = db.current_sid()
    key = (sid, doc_id)
    d = conn.execute("SELECT * FROM document WHERE id=?", (doc_id,)).fetchone()
    if d is None:
        return
    cfg = conn.execute("SELECT * FROM translator_config WHERE id=1").fetchone()
    if cfg is None or not cfg["model_name"]:
        _status[key] = {"status": "failed", "done": 0, "total": 0, "error_reason": "no_api_key"}
        return
    params = json.loads(cfg["params_json"] or "{}")
    client = client_for(conn, cfg["model_name"], params)
    if client is None:
        _status[key] = {"status": "failed", "done": 0, "total": 0, "error_reason": "no_api_key"}
        return
    system = (cfg["prompt"] or "").format(
        source_lang=d["source_lang"], target_lang=d["target_lang"])

    paras = conn.execute(
        "SELECT * FROM paragraph WHERE document_id=? ORDER BY idx", (doc_id,)).fetchall()
    total = len(paras)
    _status[key] = {"status": "running", "done": 0, "total": total}

    ctx: list[str] = []
    failed = 0
    for p in paras:
        if not _document_exists(conn, doc_id):
            return                              # document deleted mid-flight
        if p["target"]:
            # Already translated (idempotent re-POST resumes only empty
            # paragraphs) — feed it as rolling context and count it done.
            ctx = (ctx + [p["target"]])[-ROLLING_CONTEXT_PARAS:]
            _status[key]["done"] += 1
            continue

        ctx_block = "\n".join(ctx)[-CONTEXT_CHAR_BUDGET:]
        user = (f"Source ({d['source_lang']}):\n{p['source']}\n\n"
                f"Context — previous translation:\n{ctx_block}\n\n"
                f"Translate into {d['target_lang']}. Output ONLY the translation.")
        try:
            text = await _translate_one(client, system, user)
        except budget.BudgetExceeded:
            # Hard per-call guard tripped mid-run — stop immediately, don't
            # keep counting the untried remainder as "done".
            _status[key]["status"] = "failed"
            _status[key]["error_reason"] = "budget_exhausted"
            return
        if text is None:
            failed += 1
            _status[key]["done"] += 1
            continue

        ts = _now()
        with db.current_lock():
            if not _document_exists(conn, doc_id):
                return                          # deleted while the call was in flight
            conn.execute("UPDATE paragraph SET target=?, seed_target=? WHERE id=?",
                         (text, text, p["id"]))
            db.write_revision(conn, p["id"], text, "translate", ts)
            conn.commit()
            db.touch(sid)                       # background task never re-calls connect()/
                                                 # current_lock() from a fresh contextvar read,
                                                 # so the TTL sweep needs this explicit bump
        ctx = (ctx + [text])[-ROLLING_CONTEXT_PARAS:]
        _status[key]["done"] += 1

    if total and failed == total:
        _status[key]["status"] = "failed"
        _status[key].setdefault("error_reason", "all_failed")
    else:
        _status[key]["status"] = "done"
        if terms_launch is not None:
            terms_launch(doc_id, client_for)
