"""Palimpsest demo backend — FastAPI over SQLite (rev-4 contract §2/§3).

API-only: the React/TipTap frontend is served separately by Vite (which proxies
/api here). Run single-writer: ``uvicorn palimpsest.webapp.app:app --port 8000``.
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging
import os
import re
import sqlite3
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import docx
from fastapi import Body, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from ..llm.client import LLMClient, LLMConfig, is_transient_error
from ..terminology.grounding.label_first import DEFAULT_GROUNDING_JUDGE_SYSTEM_PROMPT
from ..terminology.verdict import _norm
from . import budget, db, export, precompute, terminology_live, translate
from .aggregate import compute_aggregate
from .judge import judge_one, looks_like_advice, scoring_system_prompt
from .migrate import migrate as _migrate_db
from .model_matrix import MATRIX, additive_reasoning_tokens
from .model_params import ModelParams, _is_openrouter
from .secrets_guard import is_secret_key, redact_error

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    # Bring an existing prod DB up to the current additive schema before the
    # app serves any request (spec 2026-07-05-score-history-best §2.4) — a
    # fresh dev/test DB (db.init_db) already has the full SCHEMA, so this is a
    # no-op there beyond the idempotent CREATE TABLE IF NOT EXISTS/backfill checks.
    _migrate_db(db.connect())
    yield


app = FastAPI(title="Glossa-MT demo", lifespan=_lifespan)


@app.exception_handler(sqlite3.IntegrityError)
def _integrity_error(request: Request, exc: sqlite3.IntegrityError) -> JSONResponse:
    # duplicate PK / FK violation on a config write → 409, not a 500
    return JSONResponse(status_code=409, content={"error": str(exc)})

EVAL_TIMEOUT = float(os.environ.get("PALIMPSEST_EVAL_TIMEOUT", "20"))
# A single judge call over a ~2k-char pair on gpt-5.4-mini normally returns in
# 3–15 s; the tail occasionally spikes past EVAL_TIMEOUT or hits a transient
# 429/5xx. Retry those a couple of times with backoff before surfacing a failed
# criterion — a plain re-evaluate must not dead-end on a transient blip.
EVAL_RETRIES = int(os.environ.get("PALIMPSEST_EVAL_RETRIES", "2"))
EVAL_BACKOFF = float(os.environ.get("PALIMPSEST_EVAL_BACKOFF", "0.5"))


MAX_PARAGRAPHS = 40
MAX_PARA_CHARS = 4000

# doc ids with an /evaluate in flight — reset 409s against these.
_evaluating: set[int] = set()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─────────────────────────── serialization ───────────────────────────

def _score_dict(r) -> dict:
    return {"criterionId": r["criterion_id"], "value": r["value"], "summary": r["summary"],
            "criteriaKey": r["criteria_key"]}


def _issue_dict(r) -> dict:
    return {
        "id": str(r["id"]), "paragraphId": r["paragraph_id"], "criterionId": r["criterion_id"],
        "targetFragment": r["target_fragment"], "sourceFragment": r["source_fragment"],
        "explanation": r["explanation"], "suggestion": r["suggestion"],
        "severity": r["severity"], "mqmCategory": r["mqm_category"], "status": r["status"],
    }


_VERDICT_ENUM = {"green", "yellow", "red"}


def _norm_verdict(value: str | None) -> str | None:
    """Whitelist DB verdict columns against the enum the frontend CSS covers.

    A value outside {green, yellow, red} would drive a `verdict-<value>` /
    `difficulty-<value>` CSS class that doesn't exist — silently dead styling
    instead of a visible error. Coerce anything unexpected to null (neutral).
    """
    return value if value in _VERDICT_ENUM else None


def _term_dict(r) -> dict:
    return {
        "id": str(r["id"]), "paragraphId": r["paragraph_id"],
        "sourceSurface": r["source_surface"], "sourceLemma": r["source_lemma"],
        "context": r["context"], "charStart": r["char_start"], "charEnd": r["char_end"],
        "difficulty": _norm_verdict(r["difficulty"]),
        "grounded": json.loads(r["grounded_json"]) if r["grounded_json"] else None,
        "candidates": json.loads(r["candidates_json"]) if r["candidates_json"] else [],
        "targetSurface": r["target_surface"], "pairAccuracy": _norm_verdict(r["pair_accuracy"]),
        "recommended": r["recommended"], "note": r["note"],
        "traceJson": json.loads(r["trace_json"]) if r["trace_json"] else {},
    }


def _criterion_dict(r) -> dict:
    return {
        "id": r["id"], "name": r["name"], "modelName": r["model_name"], "prompt": r["prompt"],
        "scaleMin": r["scale_min"], "scaleMax": r["scale_max"], "weight": r["weight"],
        "color": r["color"], "enabled": bool(r["enabled"]),
    }


def _grounding_config_dict(r) -> dict:
    if r is None:
        return {"modelName": None, "prompt": "", "params": {}}
    return {"modelName": r["model_name"], "prompt": r["prompt"] or "",
            "params": json.loads(r["params_json"] or "{}")}


def _model_public(r) -> dict:
    key = r["api_key"] or ""
    masked = (key[:4] + "…") if key else ""
    raw = json.loads(r["params_json"] or "{}")
    effective = ModelParams.for_model(r["name"], raw).model_dump(exclude_none=True)
    return {"name": r["name"], "baseUrl": r["base_url"], "apiKeyMasked": masked,
            "params": raw, "effectiveParams": effective}


def _enabled_criteria(conn) -> list:
    return conn.execute("SELECT * FROM criterion WHERE enabled=1").fetchall()


def _para_score_views(conn, pid: int):
    """Return (latest, prev, baseline) dicts by criterion + (aggregate, aggregateBaseline)."""
    rows = conn.execute(
        "SELECT * FROM score WHERE paragraph_id=? AND kind IN ('seed','live') "
        "ORDER BY created_at DESC, id DESC", (pid,)).fetchall()
    latest: dict = {}
    prev: dict = {}
    for r in rows:
        c = r["criterion_id"]
        if c not in latest:
            latest[c] = r
        elif c not in prev:
            prev[c] = r
    base_rows = conn.execute("SELECT * FROM score WHERE paragraph_id=? AND kind='seed'", (pid,)).fetchall()
    baseline = {r["criterion_id"]: r for r in base_rows}
    aggregate = rows[0]["aggregate"] if rows else None
    aggregate_base = base_rows[0]["aggregate"] if base_rows else None
    return latest, prev, baseline, aggregate, aggregate_base


def _best_revision(conn, pid: int) -> dict | None:
    """Highest-aggregate scored revision for a paragraph (spec
    2026-07-05-score-history-best §2.2): argmax(aggregate) over kind IN
    ('seed','live') rows with a non-null revision_id, tie-broken by newest.
    kind='cache' is excluded — it's a synthetic seed-uplift preview, never a
    real judged revision (§0.2a)."""
    row = conn.execute(
        "SELECT * FROM score WHERE paragraph_id=? AND kind IN ('seed','live') "
        "AND revision_id IS NOT NULL "
        "ORDER BY aggregate DESC, created_at DESC, id DESC LIMIT 1", (pid,)).fetchone()
    if row is None:
        return None
    current_rev = db.latest_revision_id(conn, pid)
    return {"aggregate": row["aggregate"], "revisionId": row["revision_id"],
            "createdAt": row["created_at"], "isCurrent": row["revision_id"] == current_rev}


def _para_issues(conn, pid: int) -> list:
    live_crits = {row["criterion_id"] for row in conn.execute(
        "SELECT DISTINCT criterion_id FROM score WHERE paragraph_id=? AND kind='live'", (pid,))}
    out = []
    for r in conn.execute("SELECT * FROM issue WHERE paragraph_id=? ORDER BY id", (pid,)):
        if r["status"] in ("accepted", "dismissed", "outdated"):
            out.append(r)                                      # history
        elif r["status"] == "open" and r["criterion_id"] in live_crits and r["kind"] == "live":
            out.append(r)                                      # live open set
        elif r["status"] == "open" and r["kind"] == "seed" and r["criterion_id"] not in live_crits:
            out.append(r)                                      # not yet re-evaluated → seed open set
        # superseded / archived → dropped, never reach the API
        # (a seed-open row whose criterion IS in live_crits is superseded by
        # definition — the live branch above owns that criterion once re-evaluated)
    return [_issue_dict(r) for r in out]


def _para_dict(conn, p) -> dict:
    pid = p["id"]
    latest, prev, baseline, agg, agg_base = _para_score_views(conn, pid)
    terms = conn.execute("SELECT * FROM term WHERE paragraph_id=? ORDER BY char_start", (pid,)).fetchall()
    return {
        "id": pid, "idx": p["idx"], "source": p["source"], "target": p["target"],
        "scores": [_score_dict(r) for r in latest.values()],
        "scoresPrev": [_score_dict(r) for r in prev.values()] or None,
        "scoresBaseline": [_score_dict(r) for r in baseline.values()] or None,
        "aggregate": agg, "aggregateBaseline": agg_base,
        "best": _best_revision(conn, pid),
        "issues": _para_issues(conn, pid),
        "terms": [_term_dict(r) for r in terms],
    }


def _doc_summary(conn, d) -> dict:
    n = conn.execute("SELECT COUNT(*) n FROM paragraph WHERE document_id=?", (d["id"],)).fetchone()["n"]
    return {"id": d["id"], "title": d["title"], "sourceLang": d["source_lang"],
            "targetLang": d["target_lang"], "nParagraphs": n, "origin": d["origin"],
            "termsStatus": d["terms_status"]}


def _status_public(status: dict | None) -> dict | None:
    """camelCase the in-memory precompute/translation status dict for the wire
    (internal dicts stay snake_case Python; every other multi-word wire field
    in this API is camelCase — see ``error_reason`` in both registries)."""
    if status is None:
        return None
    out = dict(status)
    if "error_reason" in out:
        out["errorReason"] = out.pop("error_reason")
    return out


def _doc_dict(conn, d) -> dict:
    paras = conn.execute("SELECT * FROM paragraph WHERE document_id=? ORDER BY idx", (d["id"],)).fetchall()
    para_dicts = [_para_dict(conn, p) for p in paras]
    aggs = [pd["aggregate"] for pd in para_dicts if pd["aggregate"] is not None]
    out = {**_doc_summary(conn, d), "sourceModel": d["source_model"], "version": d["version"],
           "aggregate": round(sum(aggs) / len(aggs), 2) if aggs else None, "paragraphs": para_dicts,
           "termsStatus": d["terms_status"]}
    if d["origin"] == "upload":
        out["precompute"] = _status_public(precompute.status_for(d["id"]))
        out["translation"] = _status_public(translate.status_for(d["id"]))
    return out


# ─────────────────────────── read ───────────────────────────

# In the production container DEMO_STATIC_DIR is set and "/" must serve index.html
# from the static mount (registered at the bottom); the JSON health probe moves aside.
if not os.environ.get("DEMO_STATIC_DIR"):
    @app.get("/")
    def index() -> dict:
        return {"service": "Glossa-MT demo", "status": "ok"}


@app.get("/api/health")
def health() -> dict:
    return {"service": "Glossa-MT demo", "status": "ok",
            "limits": {"maxParagraphs": MAX_PARAGRAPHS, "maxParaChars": MAX_PARA_CHARS}}


@app.get("/api/documents")
def list_documents() -> list:
    conn = db.connect()
    return [_doc_summary(conn, d) for d in conn.execute("SELECT * FROM document ORDER BY id")]


@app.get("/api/documents/{doc_id}")
def get_document(doc_id: int) -> dict:
    conn = db.connect()
    d = conn.execute("SELECT * FROM document WHERE id=?", (doc_id,)).fetchone()
    if not d:
        raise HTTPException(404, "document not found")
    return _doc_dict(conn, d)


class ParagraphPairBody(BaseModel):
    source: str
    target: str


class CreateDocumentBody(BaseModel):
    title: str
    sourceLang: str
    targetLang: str
    precompute: bool = True
    translate: bool = False
    paragraphs: list[ParagraphPairBody]


_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _sanitize_lang(value: str) -> str:
    """A language string is embedded verbatim in the judge SYSTEM prompt
    ('You are evaluating a translation from {X} into {Y}.') — strip control
    characters first, then collapse all whitespace runs (incl. \\n/\\t) to a
    single space, so it can't inject a line break or stray byte into that
    prompt."""
    return " ".join(_CONTROL_CHARS_RE.sub("", value).split())


MAX_BODY_BYTES = 1 * 1024 * 1024


async def _read_body_capped(request: Request) -> bytes:
    """Reject bodies over MAX_BODY_BYTES before pydantic ever parses them.

    Content-Length is checked first for a fast rejection without reading the
    stream; the actual byte count is checked too, since the header can be
    absent or wrong (e.g. chunked transfer-encoding).
    """
    content_length = request.headers.get("content-length")
    if content_length is not None and int(content_length) > MAX_BODY_BYTES:
        raise HTTPException(413, "body_too_large")
    body = await request.body()
    if len(body) > MAX_BODY_BYTES:
        raise HTTPException(413, "body_too_large")
    return body


def _terms_launch_after_translate(doc_id: int, client_for) -> None:
    """``translate.py``'s optional ``terms_launch`` callback, invoked once at
    the successful end of a translate run (see ``translate.py``'s ``_run``)
    so pairing sees the FINAL translated targets. Bundles
    ``_grounding_judge_live`` here so ``terminology_live``/``translate``
    don't need a second injected parameter threaded through translate.py's
    own launch chain (which only ever passes ``client_for`` around, mirroring
    precompute's ``judge_live``-only convention).
    ``terminology_live.try_start`` guards against a resumed ``POST
    .../translate`` re-triggering terms after they already ran once for this
    document."""
    conn = db.connect()
    if terminology_live.try_start(conn, doc_id):
        terminology_live.launch(doc_id, client_for, _grounding_judge_live)


# ─────────────────────── content-fingerprint clone cache ───────────────────────
# EMNLP demo-video follow-up: a translate:false upload whose (source, target)
# pairs match an existing terms_status='done' document byte-for-byte
# (whitespace-run normalized) instantly inherits its terms/scores/issues
# instead of spending LLM calls. See "Content clone cache" in
# docs/subsystems/webapp.md for the full design.

def _normalize_ws(text: str) -> str:
    """Collapse every whitespace run (including newlines/tabs) to a single
    space and strip the ends — the same "incidental formatting shouldn't
    matter" normalization ``_sanitize_lang`` applies to language names,
    reused here so the fingerprint matches across trivial paste differences
    (double spaces, CRLF, a trailing blank line)."""
    return " ".join((text or "").split())


def _content_fingerprint(pairs: list[tuple[str, str]]) -> str:
    """sha256 over the ordered ``(source, target)`` pairs, whitespace-run
    normalized. Title/langs are deliberately excluded — the clone cache
    matches on translation CONTENT only. Serializing as a JSON array (not a
    raw concatenation) keeps pair count and order load-bearing in the hash
    itself, so a different paragraph count or a reordering can never
    collide by construction."""
    normalized = [[_normalize_ws(s), _normalize_ws(t)] for s, t in pairs]
    payload = json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _find_clone_source(conn, new_doc_id: int, fingerprint: str) -> int | None:
    """First existing document (any origin — the seed document qualifies like
    any other) whose CURRENT paragraph content hashes to ``fingerprint``,
    oldest match wins. Fingerprints are never stored — recomputed on the fly
    per candidate on every call; the demo has few documents, so this is
    cheap and needs no schema change. Only a fully-processed source
    (``terms_status='done'``) is eligible — a document still
    none/running/failed has nothing worth cloning yet, and this also keeps
    the brand-new document (still 'none' at this point) from matching
    itself."""
    for row in conn.execute(
            "SELECT id FROM document WHERE id != ? AND terms_status='done' ORDER BY id",
            (new_doc_id,)):
        cand_id = row["id"]
        cand_rows = conn.execute(
            "SELECT source, target FROM paragraph WHERE document_id=? ORDER BY idx",
            (cand_id,)).fetchall()
        cand_pairs = [(r["source"], r["target"]) for r in cand_rows]
        if _content_fingerprint(cand_pairs) == fingerprint:
            return cand_id
    return None


def _clone_predictions(
        conn, source_doc_id: int, new_pids: list[int], new_revision_ids: list[int | None], ts: str) -> None:
    """Copy every term/score/issue row from ``source_doc_id`` onto the
    freshly-inserted paragraphs in ``new_pids``, index-aligned (caller
    already matched paragraph counts via the fingerprint, and holds
    ``db._lock`` inside the same not-yet-committed transaction as the
    paragraph inserts).

    ``term`` rows keep every column verbatim (difficulty/grounded_json/
    candidates_json/trace_json/target_surface/pair_accuracy/recommended/
    note) — only ``paragraph_id`` is remapped. ``score``/``issue`` rows keep
    kind/status/criterion_id verbatim too, INCLUDING each score row's own
    frozen ``aggregate``/``criteria_key`` columns — the same "computed once
    at write time, never recomputed" contract ``seed.py``/
    ``precompute._write_paragraph`` use (see ``aggregate.py``):
    ``_para_score_views`` reads ``score.aggregate`` straight off the row, so
    copying the column verbatim reproduces the source document's exact
    scores/deltas with no extra computation here. ``created_at`` is stamped
    to ``ts`` (the clone happens "now"); ``score.revision_id`` is remapped
    to the new paragraph's own (single, just-inserted) revision — every
    paragraph reaching this function came from a non-translate upload, so
    it always has exactly one. Source rows are read oldest-first and
    inserted in that same relative order, so the fresh autoincrement ids
    preserve the original recency ordering and ``_para_score_views``'s
    ``ORDER BY created_at DESC, id DESC`` "latest per criterion" tie-break
    reproduces the source document's latest/prev split exactly.
    """
    cand_rows = conn.execute(
        "SELECT id FROM paragraph WHERE document_id=? ORDER BY idx", (source_doc_id,)).fetchall()
    cand_pids = [r["id"] for r in cand_rows]
    for new_pid, new_revision_id, cand_pid in zip(new_pids, new_revision_ids, cand_pids, strict=True):
        for t in conn.execute("SELECT * FROM term WHERE paragraph_id=? ORDER BY id", (cand_pid,)):
            conn.execute(
                "INSERT INTO term(paragraph_id,source_surface,source_lemma,context,char_start,char_end,"
                "difficulty,grounded_json,candidates_json,target_surface,pair_accuracy,recommended,note,"
                "trace_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (new_pid, t["source_surface"], t["source_lemma"], t["context"], t["char_start"], t["char_end"],
                 t["difficulty"], t["grounded_json"], t["candidates_json"], t["target_surface"],
                 t["pair_accuracy"], t["recommended"], t["note"], t["trace_json"]))
        for s in conn.execute(
                "SELECT * FROM score WHERE paragraph_id=? ORDER BY created_at ASC, id ASC", (cand_pid,)):
            conn.execute(
                "INSERT INTO score(paragraph_id,criterion_id,value,summary,aggregate,criteria_key,kind,"
                "created_at,revision_id) VALUES(?,?,?,?,?,?,?,?,?)",
                (new_pid, s["criterion_id"], s["value"], s["summary"], s["aggregate"], s["criteria_key"],
                 s["kind"], ts, new_revision_id))
        for i in conn.execute("SELECT * FROM issue WHERE paragraph_id=? ORDER BY id", (cand_pid,)):
            conn.execute(
                "INSERT INTO issue(paragraph_id,criterion_id,target_fragment,source_fragment,explanation,"
                "suggestion,severity,mqm_category,status,kind,created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (new_pid, i["criterion_id"], i["target_fragment"], i["source_fragment"], i["explanation"],
                 i["suggestion"], i["severity"], i["mqm_category"], i["status"], i["kind"], ts))


@app.post("/api/documents", status_code=201)
async def create_document(request: Request) -> dict:
    raw = await _read_body_capped(request)
    try:
        body = CreateDocumentBody.model_validate_json(raw)
    except ValueError as exc:
        raise HTTPException(422, "invalid_body") from exc
    if not body.title.strip() or len(body.title) > 120:
        raise HTTPException(422, "title_required")
    src, tgt = _sanitize_lang(body.sourceLang), _sanitize_lang(body.targetLang)
    if not src or not tgt or len(src) > 40 or len(tgt) > 40:
        raise HTTPException(422, "lang_required")
    if src.lower() == tgt.lower():
        raise HTTPException(422, "same_language")
    if not body.paragraphs:
        raise HTTPException(422, "empty_paragraphs")
    if len(body.paragraphs) > MAX_PARAGRAPHS:
        raise HTTPException(422, "too_many_paragraphs")

    if body.translate:
        # source-only upload for AI translation (spec 2026-07-05-translator §2.2):
        # every target must be empty — a mix would mean the modal's "AI translate"
        # toggle disagreed with pasted-in text, which should never happen from the
        # real UI, but the contract makes it an explicit 422 rather than silently
        # discarding whichever targets happened to be non-empty.
        for i, pair in enumerate(body.paragraphs):
            if not pair.source.strip():
                raise HTTPException(422, f"empty_cell:{i}")
            if len(pair.source) > MAX_PARA_CHARS:
                raise HTTPException(422, f"paragraph_too_long:{i}")
        if any(pair.target.strip() for pair in body.paragraphs):
            raise HTTPException(422, "mixed_targets")
    else:
        for i, pair in enumerate(body.paragraphs):
            if not pair.source.strip() or not pair.target.strip():
                raise HTTPException(422, f"empty_cell:{i}")
            if len(pair.source) > MAX_PARA_CHARS or len(pair.target) > MAX_PARA_CHARS:
                raise HTTPException(422, f"paragraph_too_long:{i}")

    # translate:true forces precompute off SERVER-SIDE regardless of what the
    # body says (CRITICAL from spec review): precompute over 12 empty targets
    # would burn a paid judge pass and permanently record a garbage baseline
    # (_already_scored then skips those paragraphs forever).
    run_precompute = body.precompute and not body.translate

    conn = db.connect()
    with db._lock:
        ts = _now()
        doc_id = conn.execute(
            "INSERT INTO document(title,source_lang,target_lang,source_model,version,origin,created_at) "
            "VALUES(?,?,?,'user',0,'upload',?)",
            (body.title.strip(), src, tgt, ts)).lastrowid
        new_pids: list[int] = []
        new_revision_ids: list[int | None] = []
        stored_pairs: list[tuple[str, str]] = []
        for idx, pair in enumerate(body.paragraphs):
            source = pair.source.strip()
            target = "" if body.translate else pair.target.strip()
            pid = conn.execute(
                "INSERT INTO paragraph(document_id,idx,source,target,seed_target) VALUES(?,?,?,?,?)",
                (doc_id, idx, source, target, target)).lastrowid
            new_pids.append(pid)
            stored_pairs.append((source, target))
            if not body.translate:
                # translate:true leaves target empty — translate.py writes the
                # first real revision once each paragraph is actually translated.
                new_revision_ids.append(db.write_revision(conn, pid, target, "upload", ts))
            else:
                new_revision_ids.append(None)

        # Content-fingerprint clone cache — translate:true is exempt (targets
        # are still empty here, nothing meaningful to fingerprint yet; terms
        # for a translate:true doc only ever launch post-translation, see
        # _terms_launch_after_translate).
        cloned_from: int | None = None
        if not body.translate:
            fingerprint = _content_fingerprint(stored_pairs)
            cloned_from = _find_clone_source(conn, doc_id, fingerprint)
            if cloned_from is not None:
                _clone_predictions(conn, cloned_from, new_pids, new_revision_ids, ts)

        conn.commit()
        # Set in-memory precompute/translation status BEFORE building the
        # response so the 201 body already carries it (run() refines `planned`
        # once it re-counts the paragraphs, but the initial value here is
        # already correct — same min(N, PRECOMPUTE_PARAS) math).
        if cloned_from is not None:
            # Cloned scores already ARE the baseline — never spend a judge
            # pass on paragraphs whose scores were just cloned in.
            precompute.mark_skipped(doc_id)
        elif run_precompute:
            precompute.mark_started(doc_id, len(body.paragraphs))
        else:
            precompute.mark_skipped(doc_id)
        if body.translate:
            translate._translating.add(doc_id)
            translate.mark_started(doc_id, len(body.paragraphs))
        elif cloned_from is not None:
            conn.execute("UPDATE document SET terms_status='done' WHERE id=?", (doc_id,))
        else:
            # translate:true docs have no target yet — terms launch later, at
            # translate's successful end (see _terms_launch_after_translate).
            # A non-translate doc already has real targets, so terms can run
            # immediately; write 'running' inside this same lock/transaction
            # so the 201 body below already reflects it (same "set status
            # before building the response" rule precompute/translate follow).
            conn.execute("UPDATE document SET terms_status='running' WHERE id=?", (doc_id,))
        d = conn.execute("SELECT * FROM document WHERE id=?", (doc_id,)).fetchone()
        result = _doc_dict(conn, d)
    if cloned_from is not None:
        logger.info("document %d cloned from %d via content fingerprint", doc_id, cloned_from)
    if run_precompute and cloned_from is None:
        precompute.launch(doc_id, _judge_live)
    if body.translate:
        translate.launch(doc_id, _client_for, _terms_launch_after_translate)
    elif cloned_from is None:
        terminology_live.launch(doc_id, _client_for, _grounding_judge_live)
    return result


@app.delete("/api/documents/{doc_id}", status_code=204)
def delete_document_route(doc_id: int):
    conn = db.connect()
    if doc_id in _evaluating:
        return JSONResponse({"error": "evaluate_in_flight"}, status_code=409)
    with db._lock:
        d = conn.execute("SELECT * FROM document WHERE id=?", (doc_id,)).fetchone()
        if not d:
            raise HTTPException(404, "document not found")
        if d["origin"] == "seed":
            return JSONResponse({"error": "seed_document"}, status_code=409)
        conn.execute("DELETE FROM document WHERE id=?", (doc_id,))
        conn.commit()
    precompute.cancel(doc_id)
    translate.cancel(doc_id)


MAX_DOCX_BYTES = 5 * 1024 * 1024


@app.post("/api/documents/extract-text")
async def extract_text(file: UploadFile = File(...)) -> dict:
    name = (file.filename or "").lower()
    if name.endswith(".doc"):
        raise HTTPException(415, "unsupported_type:doc")   # UI: «Сохраните как .docx…» (спека §5.5)
    if not name.endswith(".docx"):
        raise HTTPException(415, "unsupported_type")
    data = await file.read()
    if len(data) > MAX_DOCX_BYTES:
        raise HTTPException(413, "file_too_large")
    try:
        document = docx.Document(io.BytesIO(data))
    except Exception as exc:                     # python-docx кидает разные типы на битом zip
        raise HTTPException(422, "unparseable_file") from exc
    paras = [p.text.strip() for p in document.paragraphs if p.text.strip()]
    return {"text": "\n\n".join(paras), "nParagraphs": len(paras)}


def _para_or_404(conn, pid: int):
    p = conn.execute("SELECT * FROM paragraph WHERE id=?", (pid,)).fetchone()
    if not p:
        raise HTTPException(404, "paragraph not found")
    return p


@app.patch("/api/paragraphs/{pid}")
def patch_paragraph(pid: int, target: str = Body(..., embed=True)) -> dict:
    conn = db.connect()
    with db._lock:
        p = _para_or_404(conn, pid)
        conn.execute("UPDATE paragraph SET target=? WHERE id=?", (target, pid))
        if target != p["target"]:
            # Only a real change gets a revision — a debounced no-op PATCH (the
            # frontend already debounces 600ms) must not spam the history.
            db.write_revision(conn, pid, target, "edit", _now())
        conn.commit()
        return _para_dict(conn, _para_or_404(conn, pid))


# ─────────────────────────── improvement loop ───────────────────────────

def _client_for(conn, model_name: str, params_override: dict | None = None) -> LLMClient | None:
    """Build a client for ``model_name``. By default the effective params come
    from that model's OWN registry row (``model.params_json``) — the shape
    every existing caller (``_judge_live``, the Test probe) relies on.

    ``params_override``, when given, REPLACES the registry row's params bag
    entirely (translator_config / grounding_config params, not the model's
    own defaults) — spec 2026-07-05-translator §3.1: without this, a caller
    that wants its own temperature/max_tokens silently got the registry row's
    instead (only used for cost estimation, never for the actual call)."""
    m = conn.execute("SELECT * FROM model WHERE name=?", (model_name,)).fetchone()
    if not m:
        return None
    api_key = m["api_key"] or ""
    if not api_key and _is_openrouter(m["base_url"]):
        api_key = os.environ.get("OPENROUTER_API_KEY", "")   # shared-key env-fallback (OR only)
    if not api_key:
        return None
    raw = params_override if params_override is not None else json.loads(m["params_json"] or "{}")
    mp = ModelParams.for_model(model_name, raw)
    cfg = LLMConfig(model=m["name"], base_url=m["base_url"], api_key=api_key,
                    temperature=mp.temperature, max_tokens=mp.max_tokens, seed=mp.seed,
                    extra_body=mp.to_extra_body(model_name, m["base_url"]) or None)
    return LLMClient(cfg)


async def _judge_live(conn, criterion, source: str, target: str,
                      source_lang: str, target_lang: str, endpoint: str = "evaluate"):
    client = _client_for(conn, criterion["model_name"])
    if client is None:
        raise RuntimeError("no api key for model")
    name = criterion["model_name"]
    system = scoring_system_prompt(criterion["id"], source_lang, target_lang)
    prompt_tok = (budget.count_tokens(system) + budget.count_tokens(source)
                  + budget.count_tokens(target))
    raw = json.loads(conn.execute("SELECT params_json FROM model WHERE name=?", (name,)
                                  ).fetchone()["params_json"] or "{}")
    rmt = additive_reasoning_tokens(name, raw)
    est = budget.estimate(name, prompt_tok, client.config.max_tokens, rmt)
    gen = await budget.reserve(est)                       # raises BudgetExceeded → caught as failure
    # One reservation covers every retry of THIS criterion: the worst case is a
    # single successful call, and a retry only fires after the prior attempt was
    # billed $0 (it errored). Settle once, on the terminal outcome.
    attempt = 0
    while True:
        try:
            res = await asyncio.wait_for(
                asyncio.to_thread(judge_one, client, criterion["id"], source, target,
                                  source_lang=source_lang, target_lang=target_lang), EVAL_TIMEOUT)
            break
        except Exception as exc:
            if is_transient_error(exc) and attempt < EVAL_RETRIES:
                err = redact_error(f"{type(exc).__name__}: {exc}")
                budget.log_call({"model": name, "endpoint": endpoint, "criterion": criterion["id"],
                                 "params": raw, "status": "retry", "attempt": attempt,
                                 "error": err, "costUsd": None})
                logger.warning("judge retry: criterion=%s model=%s attempt=%d error=%s",
                                criterion["id"], name, attempt, err)
                await asyncio.sleep(EVAL_BACKOFF * (2 ** attempt))
                attempt += 1
                continue
            # terminal error → no tokens were actually billed; release the
            # worst-case reservation instead of holding it forever (settle to 0.0,
            # not None — None means "keep the reservation", which is wrong here).
            await budget.settle(est, 0.0, gen)
            err = redact_error(f"{type(exc).__name__}: {exc}")
            budget.log_call({"model": name, "endpoint": endpoint, "criterion": criterion["id"],
                             "params": raw, "status": "error", "attempts": attempt + 1,
                             "error": err, "costUsd": None})
            logger.warning("judge failed terminally: criterion=%s model=%s attempts=%d error=%s",
                            criterion["id"], name, attempt + 1, err)
            raise
    await budget.settle(est, res["usage"].cost_usd, gen)
    budget.log_call({"model": name, "endpoint": endpoint, "criterion": criterion["id"],
                     "params": raw, "status": "ok", "tokens": {"prompt": res["usage"].prompt_tokens,
                     "completion": res["usage"].completion_tokens,
                     "reasoning": res["usage"].reasoning_tokens}, "costUsd": res["usage"].cost_usd})
    return res


class EvaluateBody(BaseModel):
    criterionIds: list[str] | None = None


@app.post("/api/paragraphs/{pid}/evaluate")
async def evaluate(pid: int, body: EvaluateBody = EvaluateBody()) -> dict:
    conn = db.connect()
    p = _para_or_404(conn, pid)
    doc_id = p["document_id"]
    if translate.is_translating(doc_id):
        return JSONResponse({"detail": "translation_in_progress"}, status_code=409)
    doc = conn.execute("SELECT * FROM document WHERE id=?", (doc_id,)).fetchone()
    enabled = _enabled_criteria(conn)
    target_ids = set(body.criterionIds) if body.criterionIds else {c["id"] for c in enabled}
    crits = [c for c in enabled if c["id"] in target_ids]

    _evaluating.add(doc_id)
    try:
        results = await asyncio.gather(
            *[_judge_live(conn, c, p["source"], p["target"],
                          doc["source_lang"], doc["target_lang"]) for c in crits],
            return_exceptions=True)
    finally:
        _evaluating.discard(doc_id)

    succeeded = {c["id"]: r for c, r in zip(crits, results) if not isinstance(r, Exception)}
    failed = [c["id"] for c, r in zip(crits, results) if isinstance(r, Exception)]

    if not succeeded:
        cached = _cache_response(conn, p, enabled, failed)
        if cached is not None:
            return cached
        # no cache and nothing succeeded → empty live result (all failed)

    with db._lock:
        # values for ALL enabled = latest, overridden by fresh successes
        latest, _, _, agg_prev, _ = _para_score_views(conn, pid)
        values = {cid: row["value"] for cid, row in latest.items()}
        for cid, res in succeeded.items():
            values[cid] = res["value"]
        aggregate, criteria_key = compute_aggregate(values, enabled)
        ts = _now()
        revision_id = db.latest_revision_id(conn, pid)
        for cid, res in succeeded.items():
            conn.execute("UPDATE issue SET status='superseded' WHERE paragraph_id=? AND criterion_id=? AND kind='live' AND status='open'",
                         (pid, cid))
            conn.execute(
                "INSERT INTO score(paragraph_id,criterion_id,value,summary,aggregate,criteria_key,kind,created_at,revision_id) "
                "VALUES(?,?,?,?,?,?,'live',?,?)",
                (pid, cid, res["value"], res["summary"], aggregate, criteria_key, ts, revision_id))
            for it in res["issues"]:
                dismissed_or_accepted = conn.execute(
                    "SELECT 1 FROM issue WHERE paragraph_id=? AND criterion_id=? AND target_fragment=? "
                    "AND status IN ('accepted','dismissed') LIMIT 1",
                    (pid, cid, it["targetFragment"])).fetchone()
                if dismissed_or_accepted:
                    continue  # reviewer already dismissed/accepted this exact fragment — don't resurrect it
                conn.execute(
                    "INSERT INTO issue(paragraph_id,criterion_id,target_fragment,source_fragment,explanation,"
                    "suggestion,severity,mqm_category,status,kind,created_at) VALUES(?,?,?,?,?,?,?,?,'open','live',?)",
                    (pid, cid, it["targetFragment"], it["sourceFragment"], it["explanation"],
                     it["suggestion"], it["severity"], it["mqmCategory"], ts))
        conn.execute("UPDATE document SET version=version+1 WHERE id=?", (doc_id,))
        conn.commit()
        ver = conn.execute("SELECT version FROM document WHERE id=?", (doc_id,)).fetchone()["version"]
        latest, prev, baseline, agg, agg_base = _para_score_views(conn, pid)
        return {
            "scores": [_score_dict(r) for r in latest.values()],
            "scoresPrev": [_score_dict(r) for r in prev.values()] or None,
            "scoresBaseline": [_score_dict(r) for r in baseline.values()] or None,
            "aggregate": agg, "aggregateBaseline": agg_base, "aggregatePrev": agg_prev,
            "issues": _para_issues(conn, pid), "failedCriterionIds": failed,
            "cached": False, "cachedAt": None, "docVersion": ver,
        }


def _cache_response(conn, p, enabled, failed) -> dict | None:
    """Read-only passthrough of pre-computed kind='cache' scores (rev-4 §3)."""
    pid = p["id"]
    cache = conn.execute("SELECT * FROM score WHERE paragraph_id=? AND kind='cache'", (pid,)).fetchall()
    if not cache:
        return None
    _, prev, baseline, agg_prev, agg_base = _para_score_views(conn, pid)
    ver = conn.execute("SELECT version FROM document WHERE id=?", (p["document_id"],)).fetchone()["version"]
    return {
        "scores": [_score_dict(r) for r in cache],
        "scoresPrev": [_score_dict(r) for r in prev.values()] or None,
        "scoresBaseline": [_score_dict(r) for r in baseline.values()] or None,
        "aggregate": cache[0]["aggregate"], "aggregateBaseline": agg_base, "aggregatePrev": agg_prev,
        # cache supplied a value for every criterion → nothing failed from the
        # consumer's view (the live judges that raised are an internal detail).
        "issues": _para_issues(conn, pid), "failedCriterionIds": [],
        "cached": True, "cachedAt": cache[0]["created_at"], "docVersion": ver,
    }


class ApplyEditBody(BaseModel):
    issueId: str


def _splice_suggestion(target: str, frag: str, suggestion: str) -> str | None:
    """Replace ``frag`` with ``suggestion``, collapsing a boundary word that the
    surrounding text already supplies. Judge suggestions sometimes repeat the
    word immediately before/after the fragment (fragment "drawn into …",
    suggestion "partly incorporated …" next to an existing "partly") which a
    literal splice would duplicate ("partly partly"). Returns None if not found.

    Matching is whitespace-tolerant: exact substring first; on a miss, the
    fragment's tokens are re-searched with flexible inter-token whitespace —
    earlier accepts in a batch can reflow spacing without changing the words.
    """
    idx = target.find(frag) if frag else -1
    frag_len = len(frag)
    if idx == -1 and frag.split():
        pattern = r"\s+".join(re.escape(tok) for tok in frag.split())
        m = re.search(pattern, target)
        if m:
            idx, frag_len = m.start(), m.end() - m.start()
    if idx == -1:
        return None
    before, after = target[:idx], target[idx + frag_len:]
    sug = suggestion
    bw, sw = re.search(r"(\S+)\s*$", before), re.match(r"(\S+)(\s+)", sug)
    if bw and sw and bw.group(1).lower() == sw.group(1).lower():
        sug = sug[sw.end():]                       # drop leading duplicate word
    aw, sw2 = re.match(r"\s*(\S+)", after), re.search(r"(\s+)(\S+)\s*$", sug)
    if aw and sw2 and aw.group(1).lower() == sw2.group(2).lower():
        sug = sug[: sw2.start()]                   # drop trailing duplicate word
    return before + sug + after


@app.post("/api/paragraphs/{pid}/apply-edit")
def apply_edit(pid: int, body: ApplyEditBody) -> dict:
    conn = db.connect()
    with db._lock:
        p = _para_or_404(conn, pid)
        try:
            iid = int(body.issueId)
        except (TypeError, ValueError):
            raise HTTPException(404, "issue not found")  # non-numeric id can't exist
        iss = conn.execute("SELECT * FROM issue WHERE id=? AND paragraph_id=?", (iid, pid)).fetchone()
        if not iss:
            raise HTTPException(404, "issue not found")
        if iss["status"] != "open":
            # Accept on an already-accepted/dismissed/outdated issue must be rejected,
            # never re-splice the (possibly already-rewritten) target a second time.
            raise HTTPException(422, {"error": "not_open"})
        suggestion = (iss["suggestion"] or "").strip()
        if not suggestion:
            # nothing to apply — never delete the flagged fragment
            raise HTTPException(422, {"error": "no_suggestion"})
        if looks_like_advice(suggestion):
            # second line of defense: a legacy/pre-guard row can carry a
            # non-empty advice suggestion that sanitize_issue never saw —
            # refuse the splice instead of grafting advice text into the translation
            raise HTTPException(422, {"error": "advice_suggestion"})
        new_target = _splice_suggestion(p["target"], iss["target_fragment"], iss["suggestion"])
        if new_target is None:
            raise HTTPException(422, {"error": "fragment_not_found"})

        # Transactional write: paragraph UPDATE + issue UPDATE + sibling-invalidation
        # loop commit or roll back together. `with conn` commits on success and rolls
        # back on any exception (default deferred isolation_level) — without it, a
        # mid-loop failure would silently leave a partial write that persists on the
        # next unrelated commit elsewhere in the app.
        with conn:
            conn.execute("UPDATE paragraph SET target=? WHERE id=?", (new_target, pid))
            conn.execute("UPDATE issue SET status='accepted' WHERE id=?", (iss["id"],))
            db.write_revision(conn, pid, new_target, "apply_edit", _now())

            # Invalidate any OTHER still-open issue in this paragraph whose fragment is
            # now unreachable in the rewritten target (overlapped by this edit). Uses the
            # same whitespace-tolerant matcher: a probe splice returning None == gone.
            # Only status='open' rows are touched; accepted/dismissed history is left as-is.
            siblings = conn.execute(
                "SELECT * FROM issue WHERE paragraph_id=? AND id!=? AND status='open'",
                (pid, iss["id"]),
            ).fetchall()
            invalidated = []
            for sib in siblings:
                frag = sib["target_fragment"]
                # Probe with a no-op suggestion: we only care whether the fragment locates.
                if not frag or _splice_suggestion(new_target, frag, frag) is None:
                    conn.execute("UPDATE issue SET status='outdated' WHERE id=?", (sib["id"],))
                    invalidated.append(sib["id"])

        new_iss = conn.execute("SELECT * FROM issue WHERE id=?", (iss["id"],)).fetchone()
        sibling_dicts = [
            _issue_dict(conn.execute("SELECT * FROM issue WHERE id=?", (sid,)).fetchone())
            for sid in invalidated
        ]
        return {"target": new_target, "issue": _issue_dict(new_iss), "siblingIssues": sibling_dicts}


class IssueStatusBody(BaseModel):
    status: str


@app.patch("/api/issues/{iid}")
def patch_issue_status(iid: int, body: IssueStatusBody) -> dict:
    if body.status not in ("open", "dismissed", "outdated"):
        # 'accepted' is only reachable via apply-edit (it also rewrites the target);
        # 'outdated' = the fragment was overlapped by an earlier accepted edit
        raise HTTPException(422, {"error": "invalid_status"})
    conn = db.connect()
    with db._lock:
        iss = conn.execute("SELECT * FROM issue WHERE id=?", (iid,)).fetchone()
        if not iss:
            raise HTTPException(404, "issue not found")
        if iss["status"] == "accepted":
            raise HTTPException(409, {"error": "already_accepted"})
        conn.execute("UPDATE issue SET status=? WHERE id=?", (body.status, iid))
        conn.commit()
        return _issue_dict(conn.execute("SELECT * FROM issue WHERE id=?", (iid,)).fetchone())


@app.post("/api/documents/{doc_id}/reset")
def reset_document(doc_id: int) -> dict:
    conn = db.connect()
    if doc_id in _evaluating:
        raise HTTPException(409, "evaluate in flight")
    if translate.is_translating(doc_id):
        raise HTTPException(409, "translation_in_progress")
    with db._lock:
        d = conn.execute("SELECT * FROM document WHERE id=?", (doc_id,)).fetchone()
        if not d:
            raise HTTPException(404, "document not found")
        ts = _now()
        pids = [r["id"] for r in conn.execute("SELECT id FROM paragraph WHERE document_id=?", (doc_id,))]
        for pid in pids:
            # Archive live results (never delete — predictions are irreproducible);
            # seed AND cache stay untouched as static reference data.
            conn.execute("UPDATE score SET kind='archived' WHERE paragraph_id=? AND kind='live'", (pid,))
            conn.execute("UPDATE issue SET status='archived' WHERE paragraph_id=? AND kind='live'", (pid,))
            conn.execute("UPDATE issue SET status='open' WHERE paragraph_id=? AND kind='seed'", (pid,))
            seed_target = conn.execute("SELECT seed_target FROM paragraph WHERE id=?", (pid,)).fetchone()["seed_target"]
            conn.execute("UPDATE paragraph SET target=seed_target WHERE id=?", (pid,))
            db.write_revision(conn, pid, seed_target or "", "seed", ts)
        conn.execute("UPDATE document SET version=version+1 WHERE id=?", (doc_id,))
        conn.commit()
        return _doc_dict(conn, conn.execute("SELECT * FROM document WHERE id=?", (doc_id,)).fetchone())


# ─────────────────────────── revision history ───────────────────────────

@app.get("/api/paragraphs/{pid}/revisions")
def list_revisions(pid: int) -> dict:
    conn = db.connect()
    _para_or_404(conn, pid)
    revs = conn.execute(
        "SELECT * FROM target_revision WHERE paragraph_id=? ORDER BY id DESC", (pid,)).fetchall()
    best = _best_revision(conn, pid)
    best_id = best["revisionId"] if best else None
    current_id = db.latest_revision_id(conn, pid)
    out = []
    for r in revs:
        agg_row = conn.execute(
            "SELECT MAX(aggregate) a FROM score WHERE paragraph_id=? AND revision_id=? "
            "AND kind IN ('seed','live')", (pid, r["id"])).fetchone()
        out.append({
            "id": r["id"], "origin": r["origin"], "createdAt": r["created_at"], "text": r["text"],
            "aggregate": agg_row["a"], "isBest": r["id"] == best_id, "isCurrent": r["id"] == current_id,
        })
    return {"revisions": out}


class RestoreBody(BaseModel):
    revisionId: int


@app.post("/api/paragraphs/{pid}/restore")
def restore_paragraph(pid: int, body: RestoreBody) -> dict:
    conn = db.connect()
    with db._lock:
        _para_or_404(conn, pid)
        rev = conn.execute("SELECT * FROM target_revision WHERE id=?", (body.revisionId,)).fetchone()
        if not rev:
            raise HTTPException(404, "revision not found")
        if rev["paragraph_id"] != pid:
            raise HTTPException(409, "revision belongs to another paragraph")
        conn.execute("UPDATE paragraph SET target=? WHERE id=?", (rev["text"], pid))
        db.write_revision(conn, pid, rev["text"], "restore", _now())
        conn.commit()
        return _para_dict(conn, _para_or_404(conn, pid))


# ─────────────────────────── translate ───────────────────────────

@app.post("/api/documents/{doc_id}/translate", status_code=202)
async def translate_document(doc_id: int) -> dict:
    conn = db.connect()
    d = conn.execute("SELECT * FROM document WHERE id=?", (doc_id,)).fetchone()
    if not d:
        raise HTTPException(404, "document not found")
    if d["origin"] == "seed":
        # never overwrite the curated pilot-slice seed document with an AI draft
        raise HTTPException(403, "seed_document")
    if translate.is_translating(doc_id):
        return JSONResponse({"detail": "translation_in_progress"}, status_code=409)

    cfg = conn.execute("SELECT * FROM translator_config WHERE id=1").fetchone()
    if cfg is None or not cfg["model_name"]:
        return JSONResponse({"detail": "no_api_key"}, status_code=409)
    raw = json.loads(cfg["params_json"] or "{}")
    mp = ModelParams.for_model(cfg["model_name"], raw)
    # Rough pre-check so a document with an obviously exhausted budget never
    # even starts the background task (spec §2.2 — reserve() inside the loop
    # remains the hard per-call guard regardless of this estimate).
    rough_est = budget.estimate(cfg["model_name"], 500, mp.max_tokens)
    snap = budget.snapshot()
    if snap["calls"] >= snap["callCap"] or snap["spentUsd"] + rough_est > snap["capUsd"]:
        return JSONResponse({"detail": "budget_exhausted"}, status_code=409)

    total = conn.execute("SELECT COUNT(*) n FROM paragraph WHERE document_id=?", (doc_id,)).fetchone()["n"]
    translate._translating.add(doc_id)
    translate.mark_started(doc_id, total)
    translate.launch(doc_id, _client_for)
    return {"status": "started", "total": total}


# ─────────────────────────── export ───────────────────────────

@app.get("/api/documents/{doc_id}/export")
def export_document(doc_id: int, format: str = "xlsx"):
    if format not in ("xlsx", "md"):
        raise HTTPException(422, "unknown format")
    conn = db.connect()
    d = conn.execute("SELECT * FROM document WHERE id=?", (doc_id,)).fetchone()
    if not d:
        raise HTTPException(404, "document not found")
    slug = export.slugify(d["title"])
    if format == "xlsx":
        content = export.build_xlsx(conn, d)
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        filename = f"{slug}-{doc_id}.xlsx"
    else:
        content = export.build_markdown(conn, d).encode("utf-8")
        media_type = "text/markdown; charset=utf-8"
        filename = f"{slug}-{doc_id}.md"
    return Response(content=content, media_type=media_type,
                     headers={"Content-Disposition": f'attachment; filename="{filename}"'})


# ─────────────────────────── budget ───────────────────────────

@app.get("/api/budget")
def get_budget() -> dict:
    return budget.snapshot()


@app.post("/api/budget/reset")
def reset_budget() -> dict:
    budget.reset()
    return budget.snapshot()


# ─────────────────────────── config: criteria ───────────────────────────

class CriterionBody(BaseModel):
    id: str
    name: str
    modelName: str
    prompt: str = ""
    scaleMin: float = 1
    scaleMax: float = 10
    weight: float = Field(1, ge=0, le=1)
    color: str = "#888"
    enabled: bool = True


@app.get("/api/criteria")
def list_criteria() -> list:
    conn = db.connect()
    return [_criterion_dict(r) for r in conn.execute("SELECT * FROM criterion ORDER BY id")]


@app.post("/api/criteria")
def create_criterion(c: CriterionBody) -> dict:
    if not c.name.strip():
        raise HTTPException(422, "name must not be empty")
    if not c.prompt.strip():
        raise HTTPException(422, "prompt must not be empty")
    conn = db.connect()
    with db._lock:
        conn.execute(
            "INSERT INTO criterion(id,name,model_name,prompt,scale_min,scale_max,weight,color,enabled) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (c.id, c.name, c.modelName, c.prompt, c.scaleMin,
             c.scaleMax, c.weight, c.color, int(c.enabled)))
        conn.commit()
        return _criterion_dict(conn.execute("SELECT * FROM criterion WHERE id=?", (c.id,)).fetchone())


@app.put("/api/criteria/{cid}")
def update_criterion(cid: str, c: CriterionBody) -> dict:
    conn = db.connect()
    with db._lock:
        if not conn.execute("SELECT 1 FROM criterion WHERE id=?", (cid,)).fetchone():
            raise HTTPException(404, "criterion not found")
        conn.execute(
            "UPDATE criterion SET name=?,model_name=?,prompt=?,scale_min=?,scale_max=?,weight=?,color=?,enabled=? "
            "WHERE id=?",
            (c.name, c.modelName, c.prompt, c.scaleMin, c.scaleMax,
             c.weight, c.color, int(c.enabled), cid))
        conn.commit()
        return _criterion_dict(conn.execute("SELECT * FROM criterion WHERE id=?", (cid,)).fetchone())


@app.delete("/api/criteria/{cid}", status_code=204)
def delete_criterion(cid: str) -> None:
    conn = db.connect()
    with db._lock:
        refs = conn.execute("SELECT 1 FROM score WHERE criterion_id=? UNION SELECT 1 FROM issue WHERE criterion_id=? LIMIT 1",
                            (cid, cid)).fetchone()
        if refs:
            raise HTTPException(409, "criterion has score/issue history; disable instead")
        conn.execute("DELETE FROM criterion WHERE id=?", (cid,))
        conn.commit()


# ─────────────────────────── config: models ───────────────────────────

def _guard_params(params: dict) -> None:
    bad = [k for k in params if is_secret_key(k)]
    if bad:
        raise HTTPException(400, f"params must not contain secret-like keys: {bad}")


_REASONING_EFFORTS = {"low", "medium", "high"}


def _validate_params_whitelist(params: dict) -> None:
    """Whitelist + type/range check for a model/grounding/translator params bag
    (spec 2026-07-05-settings-fixes §2.4). Before this, an unknown key was
    silently saved then silently dropped downstream by ``ModelParams`` (extra
    keys ignored) — now it's a 422 at write time, so Settings can't accumulate
    params that quietly do nothing."""
    for key, value in params.items():
        is_num = not isinstance(value, bool) and isinstance(value, (int, float))
        is_int = not isinstance(value, bool) and isinstance(value, int)
        if key == "max_tokens":
            if not (is_int and 1 <= value <= 32768):
                raise HTTPException(422, "max_tokens must be an int in 1..32768")
        elif key == "temperature":
            if not (is_num and 0 <= value <= 2):
                raise HTTPException(422, "temperature must be a number in 0..2")
        elif key == "top_p":
            if not (is_num and 0 <= value <= 1):
                raise HTTPException(422, "top_p must be a number in 0..1")
        elif key == "top_k":
            if not is_int:
                raise HTTPException(422, "top_k must be an int")
        elif key == "min_p":
            if not is_num:
                raise HTTPException(422, "min_p must be a number")
        elif key == "seed":
            if not is_int:
                raise HTTPException(422, "seed must be an int")
        elif key == "enable_thinking":
            if not isinstance(value, bool):
                raise HTTPException(422, "enable_thinking must be a bool")
        elif key == "reasoning":
            if not isinstance(value, dict) or not set(value) <= {"effort", "max_tokens"}:
                raise HTTPException(422, "reasoning must be an object with effort/max_tokens")
            effort = value.get("effort")
            if effort is not None and effort not in _REASONING_EFFORTS:
                raise HTTPException(422, "reasoning.effort must be low|medium|high")
            rmt = value.get("max_tokens")
            if rmt is not None and (isinstance(rmt, bool) or not isinstance(rmt, int) or rmt < 0):
                raise HTTPException(422, "reasoning.max_tokens must be a non-negative int")
        else:
            raise HTTPException(422, f"unknown param: {key}")


def _require_params_object(m: dict) -> dict:
    """``params`` must be a JSON object — a list/number/null/string silently
    corrupts the registry downstream (e.g. iterated character-by-character)."""
    params = m.get("params", {})
    if not isinstance(params, dict):
        raise HTTPException(422, "params must be a JSON object")
    return params


@app.get("/api/models")
def list_models() -> list:
    conn = db.connect()
    return [_model_public(r) for r in conn.execute("SELECT * FROM model ORDER BY name")]


@app.post("/api/models")
def create_model(m: dict = Body(...)) -> dict:
    params = _require_params_object(m)
    _guard_params(params)
    _validate_params_whitelist(params)
    conn = db.connect()
    with db._lock:
        conn.execute("INSERT INTO model(name,base_url,api_key,params_json) VALUES(?,?,?,?)",
                     (m["name"], m["baseUrl"], m.get("apiKey", ""), json.dumps(params)))
        conn.commit()
        return _model_public(conn.execute("SELECT * FROM model WHERE name=?", (m["name"],)).fetchone())


@app.put("/api/models/{name:path}")
def update_model(name: str, m: dict = Body(...)) -> dict:
    params = _require_params_object(m)
    _guard_params(params)
    _validate_params_whitelist(params)
    conn = db.connect()
    with db._lock:
        row = conn.execute("SELECT * FROM model WHERE name=?", (name,)).fetchone()
        if not row:
            raise HTTPException(404, "model not found")
        # Presence-check, not falsy-check: "apiKey" absent from the body → keep
        # the existing key; "apiKey" present (including "") → use it verbatim,
        # so {apiKey: ""} explicitly clears a previously-set key (spec
        # 2026-07-05-settings-fixes §2.5 — an empty string was previously
        # indistinguishable from an omitted field).
        api_key = m["apiKey"] if "apiKey" in m else row["api_key"]
        conn.execute("UPDATE model SET base_url=?,api_key=?,params_json=? WHERE name=?",
                     (m["baseUrl"], api_key, json.dumps(params), name))
        conn.commit()
        return _model_public(conn.execute("SELECT * FROM model WHERE name=?", (name,)).fetchone())


@app.delete("/api/models/{name:path}", status_code=204)
def delete_model(name: str) -> None:
    conn = db.connect()
    with db._lock:
        if conn.execute("SELECT 1 FROM criterion WHERE model_name=? LIMIT 1", (name,)).fetchone():
            raise HTTPException(409, "model referenced by a criterion")
        conn.execute("DELETE FROM model WHERE name=?", (name,))
        conn.commit()


# ─────────────────────────── config: grounding ───────────────────────────

class GroundingConfigBody(BaseModel):
    modelName: str | None = None
    prompt: str = ""
    params: dict = Field(default_factory=dict)


@app.get("/api/grounding-config")
def get_grounding_config() -> dict:
    conn = db.connect()
    row = conn.execute("SELECT * FROM grounding_config WHERE id=1").fetchone()
    return _grounding_config_dict(row)


@app.put("/api/grounding-config")
def update_grounding_config(gc: GroundingConfigBody) -> dict:
    if not isinstance(gc.params, dict):
        raise HTTPException(422, "params must be a JSON object")
    _guard_params(gc.params)
    _validate_params_whitelist(gc.params)
    conn = db.connect()
    with db._lock:
        conn.execute(
            "INSERT INTO grounding_config(id,model_name,prompt,params_json) VALUES(1,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET model_name=excluded.model_name, "
            "prompt=excluded.prompt, params_json=excluded.params_json",
            (gc.modelName, gc.prompt, json.dumps(gc.params)))
        conn.commit()
        return _grounding_config_dict(conn.execute("SELECT * FROM grounding_config WHERE id=1").fetchone())


# ─────────────────────────── config: translator ───────────────────────────

def _translator_config_dict(r) -> dict:
    if r is None:
        return {"modelName": None, "prompt": "", "params": {}}
    return {"modelName": r["model_name"], "prompt": r["prompt"] or "",
            "params": json.loads(r["params_json"] or "{}")}


class TranslatorConfigBody(BaseModel):
    modelName: str | None = None
    prompt: str = ""
    params: dict = Field(default_factory=dict)


@app.get("/api/translator-config")
def get_translator_config() -> dict:
    conn = db.connect()
    row = conn.execute("SELECT * FROM translator_config WHERE id=1").fetchone()
    return _translator_config_dict(row)


@app.put("/api/translator-config")
def update_translator_config(tc: TranslatorConfigBody) -> dict:
    if not isinstance(tc.params, dict):
        raise HTTPException(422, "params must be a JSON object")
    _guard_params(tc.params)
    _validate_params_whitelist(tc.params)
    conn = db.connect()
    with db._lock:
        conn.execute(
            "INSERT INTO translator_config(id,model_name,prompt,params_json) VALUES(1,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET model_name=excluded.model_name, "
            "prompt=excluded.prompt, params_json=excluded.params_json",
            (tc.modelName, tc.prompt, json.dumps(tc.params)))
        conn.commit()
        return _translator_config_dict(conn.execute("SELECT * FROM translator_config WHERE id=1").fetchone())


# ─────────────────────────── config: refiner ───────────────────────────

def _refiner_config_dict(r) -> dict:
    if r is None:
        return {"modelName": None, "prompt": "", "params": {}}
    return {"modelName": r["model_name"], "prompt": r["prompt"] or "",
            "params": json.loads(r["params_json"] or "{}")}


class RefinerConfigBody(BaseModel):
    modelName: str | None = None
    prompt: str = ""
    params: dict = Field(default_factory=dict)


@app.get("/api/refiner-config")
def get_refiner_config() -> dict:
    conn = db.connect()
    row = conn.execute("SELECT * FROM refiner_config WHERE id=1").fetchone()
    return _refiner_config_dict(row)


@app.put("/api/refiner-config")
def update_refiner_config(rc: RefinerConfigBody) -> dict:
    if not isinstance(rc.params, dict):
        raise HTTPException(422, "params must be a JSON object")
    _guard_params(rc.params)
    _validate_params_whitelist(rc.params)
    conn = db.connect()
    with db._lock:
        conn.execute(
            "INSERT INTO refiner_config(id,model_name,prompt,params_json) VALUES(1,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET model_name=excluded.model_name, "
            "prompt=excluded.prompt, params_json=excluded.params_json",
            (rc.modelName, rc.prompt, json.dumps(rc.params)))
        conn.commit()
        return _refiner_config_dict(conn.execute("SELECT * FROM refiner_config WHERE id=1").fetchone())


# ─────────────────────────── refine ───────────────────────────
# Paper: "a dedicated refiner LLM integrates aggregated corrections in a
# single pass" — one call over ALL of a paragraph's open findings, instead of
# one apply-edit splice per issue. Response/status-code contract below is
# dictated by the ALREADY-SHIPPED frontend caller (api-client.ts
# refineParagraph, store.ts's refineParagraph action) — read before changing
# this endpoint:
#   - success -> the plain updated Paragraph dict (_para_dict), no envelope;
#     scores/aggregate are deliberately the PRE-refine values (the frontend
#     chains a real /evaluate right after) — refine never touches `score`.
#   - failure -> a non-2xx status. `post()` (api-client.ts) throws on
#     `!res.ok`; there is no `{ok:false}` 200 path for this endpoint, unlike
#     /evaluate or /test.
#   - 409 is special-cased CLIENT-SIDE as "silent, no error banner" (the
#     Refine button is already gated on activeIssueCount>0, so a 409 here
#     only fires on a genuine race) — reserved EXCLUSIVELY for
#     no_open_issues; every other failure below uses a different code so it
#     still surfaces a banner instead of silently no-op'ing.

REFINE_TIMEOUT = float(os.environ.get("PALIMPSEST_REFINE_TIMEOUT", "60"))
_REFINER_FENCE_RE = re.compile(r"^\s*```[a-zA-Z]*\n?|\n?```\s*$")
_REFINER_WRAP_QUOTES = "\"'“”‘’"


def _strip_refiner_wrapping(text: str) -> str:
    """Defensive cleanup on the refiner's raw completion: strip an accidental
    ```-fence and one layer of wrapping quotes despite the 'output ONLY the
    revised translation' instruction (same posture as translate._strip_label
    for the translator role)."""
    out = _REFINER_FENCE_RE.sub("", text.strip()).strip()
    if len(out) >= 2 and out[0] in _REFINER_WRAP_QUOTES and out[-1] in _REFINER_WRAP_QUOTES:
        out = out[1:-1].strip()
    return out


def _open_findings(conn, pid: int) -> list[dict]:
    """Open issues across ALL criteria for this paragraph — the exact set
    `_para_issues` surfaces to the inspector (live-open/seed-open branches),
    filtered to status=='open' (that helper also returns accepted/dismissed/
    outdated history, which the refiner must not re-litigate)."""
    return [i for i in _para_issues(conn, pid) if i["status"] == "open"]


@app.post("/api/paragraphs/{pid}/refine")
async def refine_paragraph(pid: int) -> dict:
    conn = db.connect()
    p = _para_or_404(conn, pid)
    doc_id = p["document_id"]
    if translate.is_translating(doc_id):
        raise HTTPException(503, "translation_in_progress")
    findings = _open_findings(conn, pid)
    if not findings:
        raise HTTPException(409, {"detail": "no_open_issues",
                                   "message": "no open findings to refine — evaluate the paragraph first"})

    cfg = conn.execute("SELECT * FROM refiner_config WHERE id=1").fetchone()
    if cfg is None or not cfg["model_name"]:
        raise HTTPException(503, "no_api_key")
    raw = json.loads(cfg["params_json"] or "{}")
    client = _client_for(conn, cfg["model_name"], raw)
    if client is None:
        raise HTTPException(503, "no_api_key")

    lines = [
        f"{idx}. [{f['criterionId']}]\n"
        f"   source fragment: {f['sourceFragment']!r}\n"
        f"   problematic translation fragment: {f['targetFragment']!r}\n"
        f"   explanation: {f['explanation']}\n"
        f"   suggested correction: {f['suggestion'] or '(none — see explanation)'}"
        for idx, f in enumerate(findings, start=1)
    ]
    user = (f"[SOURCE]\n{p['source']}\n\n[CURRENT TRANSLATION]\n{p['target']}\n\n"
            f"[REVIEWER FINDINGS]\n" + "\n".join(lines))
    system = cfg["prompt"] or ""

    prompt_tok = budget.count_tokens(system) + budget.count_tokens(user)
    rmt = additive_reasoning_tokens(cfg["model_name"], raw)
    est = budget.estimate(cfg["model_name"], prompt_tok, client.config.max_tokens, rmt)
    try:
        gen = await budget.reserve(est)
    except budget.BudgetExceeded:
        raise HTTPException(429, "budget_exhausted") from None

    attempt = 0
    while True:
        try:
            res = await asyncio.wait_for(
                asyncio.to_thread(client.complete, system, user), REFINE_TIMEOUT)
            break
        except Exception as exc:
            if is_transient_error(exc) and attempt < 1:
                await asyncio.sleep(EVAL_BACKOFF)
                attempt += 1
                continue
            await budget.settle(est, 0.0, gen)
            err = redact_error(f"{type(exc).__name__}: {exc}")
            budget.log_call({"model": cfg["model_name"], "endpoint": "refine", "params": raw,
                             "status": "error", "attempts": attempt + 1, "error": err, "costUsd": None})
            logger.warning("refine failed terminally: paragraph=%s model=%s attempts=%d error=%s",
                            pid, cfg["model_name"], attempt + 1, err)
            raise HTTPException(502, {"detail": "refine_failed", "error": err}) from exc
    await budget.settle(est, res.usage.cost_usd, gen)
    budget.log_call({"model": cfg["model_name"], "endpoint": "refine", "params": raw, "status": "ok",
                     "tokens": {"prompt": res.usage.prompt_tokens, "completion": res.usage.completion_tokens,
                     "reasoning": res.usage.reasoning_tokens}, "costUsd": res.usage.cost_usd})

    revised = _strip_refiner_wrapping(res.content or "")
    if not revised:
        raise HTTPException(502, {"detail": "refine_failed", "error": "empty_output"})

    with db._lock:
        with conn:
            conn.execute("UPDATE paragraph SET target=? WHERE id=?", (revised, pid))
            for f in findings:
                conn.execute("UPDATE issue SET status='accepted' WHERE id=? AND status='open'",
                             (int(f["id"]),))
            db.write_revision(conn, pid, revised, "refine", _now())
        return _para_dict(conn, _para_or_404(conn, pid))


async def _grounding_judge_live(conn, prompt: str, endpoint: str = "grounding"):
    """Mirrors ``_judge_live``: budget reserve/settle, retry only on transient
    errors (malformed JSON is terminal — see label_first.py's error policy),
    max_tokens=512/temperature=0 per the grounding_config row, reasoning param
    omitted per-model via the existing model_matrix/ModelParams mechanism.

    ``prompt`` is the USER-only content (Role + output contract now live in
    ``DEFAULT_GROUNDING_JUDGE_SYSTEM_PROMPT``, sent as the system message below
    -- spec 2026-07-10-wiki-eval-experiment-v2.md Р7).

    Called for real by ``terminology_live.py``'s live disambiguation judge
    (2026-07-11 EMNLP sprint) — see that module for the sync/async bridge
    that lets its Judge callable (invoked deep inside the frozen, synchronous
    ``LabelFirstGrounding.ground()``) reach this async, budget-guarded call.
    """
    row = conn.execute("SELECT * FROM grounding_config WHERE id=1").fetchone()
    if row is None or not row["model_name"]:
        raise RuntimeError("grounding_config not set")
    name = row["model_name"]
    raw = json.loads(row["params_json"] or "{}")
    client = _client_for(conn, name, raw)
    if client is None:
        raise RuntimeError("no api key for model")
    prompt_tok = budget.count_tokens(prompt)
    rmt = additive_reasoning_tokens(name, raw)
    est = budget.estimate(name, prompt_tok, client.config.max_tokens, rmt)
    gen = await budget.reserve(est)
    attempt = 0
    while True:
        try:
            res = await asyncio.wait_for(
                asyncio.to_thread(client.complete, DEFAULT_GROUNDING_JUDGE_SYSTEM_PROMPT, prompt), EVAL_TIMEOUT)
            break
        except Exception as exc:
            if is_transient_error(exc) and attempt < EVAL_RETRIES:
                err = redact_error(f"{type(exc).__name__}: {exc}")
                budget.log_call({"model": name, "endpoint": endpoint, "status": "retry",
                                 "attempt": attempt, "error": err, "costUsd": None})
                logger.warning("grounding judge retry: model=%s attempt=%d error=%s", name, attempt, err)
                await asyncio.sleep(EVAL_BACKOFF * (2 ** attempt))
                attempt += 1
                continue
            await budget.settle(est, 0.0, gen)
            err = redact_error(f"{type(exc).__name__}: {exc}")
            budget.log_call({"model": name, "endpoint": endpoint, "status": "error",
                             "attempts": attempt + 1, "error": err, "costUsd": None})
            logger.warning("grounding judge failed terminally: model=%s attempts=%d error=%s",
                            name, attempt + 1, err)
            raise
    await budget.settle(est, res.usage.cost_usd, gen)
    budget.log_call({"model": name, "endpoint": endpoint, "status": "ok",
                     "tokens": {"prompt": res.usage.prompt_tokens, "completion": res.usage.completion_tokens,
                     "reasoning": res.usage.reasoning_tokens}, "costUsd": res.usage.cost_usd})
    try:
        data = json.loads(res.content)
    except json.JSONDecodeError as exc:
        # malformed JSON is terminal — the strategy's judge callable classifies
        # this the same as any other malformed response (yellow/judge_unavailable),
        # it must NOT be retried (label_first.py's documented error policy).
        budget.log_call({"model": name, "endpoint": endpoint, "status": "malformed_json",
                         "error": redact_error(str(exc)), "costUsd": res.usage.cost_usd})
        raise ValueError(f"malformed judge JSON: {exc}") from exc
    return data


# ─────────────────────────── config: models — Test probe ───────────────────────────

TEST_EXTRACT_PROMPT = (
    "You extract terminology. From the Russian paragraph, list every key term and "
    "named entity (people, places, peoples, institutions, domain terms). Respond with "
    "ONLY a JSON array of strings, no prose, no code fences."
)


def _stems(text: str) -> set[str]:
    """Morphology-tolerant word stems: prefix-4 of each word (short words kept
    whole). Lets Russian case variants match — 'династия'/'династии' → 'дина',
    'сутии'/'сутиев' → 'сути' — so the reference (genitive, as it appears in the
    source) scores against a model's nominative output."""
    return {w if len(w) <= 4 else w[:4]
            for w in re.findall(r"[а-яёa-z0-9]+", text.lower())}


def _test_reference(conn) -> tuple[list[str], str]:
    """(reference term list, idx=1 source) from seed term rows of paragraph idx=1.
    Slash-terms ('марту/амурру') split into separate references; order-preserving deduped."""
    p = conn.execute("SELECT * FROM paragraph WHERE idx=1 ORDER BY id LIMIT 1").fetchone()
    terms: list[str] = []
    if p:
        for r in conn.execute("SELECT source_surface FROM term WHERE paragraph_id=?", (p["id"],)):
            surface = r["source_surface"]
            for part in (surface.split("/") if "/" in surface else [surface]):
                n = _norm(part)
                if n:
                    terms.append(n)
    return list(dict.fromkeys(terms)), (p["source"] if p else "")


def _parse_term_list(raw: str) -> list[str]:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
    data = json.loads(text)
    if isinstance(data, dict):
        for v in data.values():
            if isinstance(v, list):
                data = v
                break
    if not isinstance(data, list):
        raise ValueError("not a JSON list")
    return [str(x) for x in data]


class TestBody(BaseModel):
    effort: str | None = None


@app.post("/api/models/{name:path}/test")
async def test_model(name: str, body: TestBody = TestBody()) -> dict:
    conn = db.connect()
    if not conn.execute("SELECT 1 FROM model WHERE name=?", (name,)).fetchone():
        raise HTTPException(404, "model not found")
    ref, ru = _test_reference(conn)
    empty = {"ok": False, "extracted": [], "reference": ref,
             "matched": 0, "total": len(ref), "share": 0.0,
             "tokens": {"prompt": 0, "completion": 0, "reasoning": 0},
             "costUsd": None, "latencyMs": 0}
    client = _client_for(conn, name)
    if client is None:
        return {**empty, "message": "no api key/env for model"}

    raw = json.loads(conn.execute("SELECT params_json FROM model WHERE name=?", (name,)
                                   ).fetchone()["params_json"] or "{}")
    spec = MATRIX.get(name)
    if body.effort and (spec.reasoning == "effort" if spec else True):
        client.config.extra_body = {**(client.config.extra_body or {}),
                                     "reasoning": {"effort": body.effort}}
    prompt_tok = budget.count_tokens(TEST_EXTRACT_PROMPT) + budget.count_tokens(ru)
    rmt = additive_reasoning_tokens(name, raw)
    est = budget.estimate(name, prompt_tok, client.config.max_tokens, rmt)
    try:
        gen = await budget.reserve(est)
    except budget.BudgetExceeded:
        return {**empty, "message": "budget"}

    t0 = time.perf_counter()
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(client.complete, TEST_EXTRACT_PROMPT, ru), EVAL_TIMEOUT)
    except Exception as e:                      # timeout / API error → 200 ok:false
        await budget.settle(est, None, gen)
        budget.log_call({"model": name, "endpoint": "test", "params": raw,
                          "status": "error", "costUsd": None})
        return {**empty, "message": f"{type(e).__name__}: {e}"}

    latency = int((time.perf_counter() - t0) * 1000)
    cost = result.usage.cost_usd
    await budget.settle(est, cost, gen)
    tokens = {"prompt": result.usage.prompt_tokens, "completion": result.usage.completion_tokens,
              "reasoning": result.usage.reasoning_tokens}
    budget.log_call({"model": name, "endpoint": "test", "params": raw, "status": "ok",
                      "tokens": tokens, "costUsd": cost, "latencyMs": latency})
    try:
        extracted = _parse_term_list(result.content)
    except (json.JSONDecodeError, ValueError):
        return {**empty, "tokens": tokens, "costUsd": cost, "latencyMs": latency,
                "message": "could not parse model output as a JSON list"}

    got_stems: set[str] = set()
    for s in extracted:
        got_stems |= _stems(s)
    matched = sum(1 for r in ref
                  if (rs := _stems(r)) and len(rs & got_stems) / len(rs) >= 0.6)
    total = len(ref)
    share = matched / total if total else 0.0
    return {"ok": share >= 0.5, "extracted": extracted, "reference": ref,
            "matched": matched, "total": total, "share": round(share, 3),
            "tokens": tokens, "costUsd": cost, "latencyMs": latency,
            "message": "ok" if share >= 0.5 else "share below 0.5"}


# ─────────────────────────── static frontend (production container) ───────────────────────────

_static_dir = os.environ.get("DEMO_STATIC_DIR")
if _static_dir:
    from fastapi.staticfiles import StaticFiles

    # Mounted last so every /api route above wins; html=True serves index.html at /.
    app.mount("/", StaticFiles(directory=_static_dir, html=True), name="static")
