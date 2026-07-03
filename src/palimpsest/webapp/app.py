"""Palimpsest demo backend — FastAPI over SQLite (rev-4 contract §2/§3).

API-only: the React/TipTap frontend is served separately by Vite (which proxies
/api here). Run single-writer: ``uvicorn palimpsest.webapp.app:app --port 8000``.
"""
from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import re
import sqlite3
import time
from datetime import datetime, timezone

import docx
from fastapi import Body, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ..llm.client import LLMClient, LLMConfig, is_transient_error
from ..terminology.verdict import _norm
from . import budget, db, precompute
from .aggregate import compute_aggregate
from .judge import judge_one, looks_like_advice, scoring_system_prompt
from .model_matrix import MATRIX, additive_reasoning_tokens
from .model_params import ModelParams, _is_openrouter
from .secrets_guard import is_secret_key, redact_error

logger = logging.getLogger(__name__)

app = FastAPI(title="Palimpsest demo")


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
    }


def _criterion_dict(r) -> dict:
    return {
        "id": r["id"], "name": r["name"], "modelName": r["model_name"], "prompt": r["prompt"],
        "scaleMin": r["scale_min"], "scaleMax": r["scale_max"], "weight": r["weight"],
        "color": r["color"], "enabled": bool(r["enabled"]),
    }


def _model_public(r) -> dict:
    key = r["api_key"] or ""
    masked = (key[:4] + "…") if key else ""
    return {"name": r["name"], "baseUrl": r["base_url"], "apiKeyMasked": masked,
            "params": json.loads(r["params_json"] or "{}")}


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
        "issues": _para_issues(conn, pid),
        "terms": [_term_dict(r) for r in terms],
    }


def _doc_summary(conn, d) -> dict:
    n = conn.execute("SELECT COUNT(*) n FROM paragraph WHERE document_id=?", (d["id"],)).fetchone()["n"]
    return {"id": d["id"], "title": d["title"], "sourceLang": d["source_lang"],
            "targetLang": d["target_lang"], "nParagraphs": n, "origin": d["origin"]}


def _doc_dict(conn, d) -> dict:
    paras = conn.execute("SELECT * FROM paragraph WHERE document_id=? ORDER BY idx", (d["id"],)).fetchall()
    para_dicts = [_para_dict(conn, p) for p in paras]
    aggs = [pd["aggregate"] for pd in para_dicts if pd["aggregate"] is not None]
    out = {**_doc_summary(conn, d), "sourceModel": d["source_model"], "version": d["version"],
           "aggregate": round(sum(aggs) / len(aggs), 2) if aggs else None, "paragraphs": para_dicts}
    if d["origin"] == "upload":
        out["precompute"] = precompute.status_for(d["id"])
    return out


# ─────────────────────────── read ───────────────────────────

# In the production container DEMO_STATIC_DIR is set and "/" must serve index.html
# from the static mount (registered at the bottom); the JSON health probe moves aside.
if not os.environ.get("DEMO_STATIC_DIR"):
    @app.get("/")
    def index() -> dict:
        return {"service": "Palimpsest demo", "status": "ok"}


@app.get("/api/health")
def health() -> dict:
    return {"service": "Palimpsest demo", "status": "ok"}


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
    for i, pair in enumerate(body.paragraphs):
        if not pair.source.strip() or not pair.target.strip():
            raise HTTPException(422, f"empty_cell:{i}")
        if len(pair.source) > MAX_PARA_CHARS or len(pair.target) > MAX_PARA_CHARS:
            raise HTTPException(422, f"paragraph_too_long:{i}")
    conn = db.connect()
    with db._lock:
        doc_id = conn.execute(
            "INSERT INTO document(title,source_lang,target_lang,source_model,version,origin,created_at) "
            "VALUES(?,?,?,'user',0,'upload',?)",
            (body.title.strip(), src, tgt, _now())).lastrowid
        for idx, pair in enumerate(body.paragraphs):
            conn.execute(
                "INSERT INTO paragraph(document_id,idx,source,target,seed_target) VALUES(?,?,?,?,?)",
                (doc_id, idx, pair.source.strip(), pair.target.strip(), pair.target.strip()))
        conn.commit()
        # Set in-memory precompute status BEFORE building the response so the
        # 201 body already carries the real status (run() refines `planned`
        # once it re-counts the paragraphs, but the initial value here is
        # already correct — same min(N, PRECOMPUTE_PARAS) math).
        if body.precompute:
            precompute.mark_started(doc_id, len(body.paragraphs))
        else:
            precompute.mark_skipped(doc_id)
        d = conn.execute("SELECT * FROM document WHERE id=?", (doc_id,)).fetchone()
        result = _doc_dict(conn, d)
    if body.precompute:
        precompute.launch(doc_id, _judge_live)
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
        _para_or_404(conn, pid)
        conn.execute("UPDATE paragraph SET target=? WHERE id=?", (target, pid))
        conn.commit()
        return _para_dict(conn, _para_or_404(conn, pid))


# ─────────────────────────── improvement loop ───────────────────────────

def _client_for(conn, model_name: str) -> LLMClient | None:
    m = conn.execute("SELECT * FROM model WHERE name=?", (model_name,)).fetchone()
    if not m:
        return None
    api_key = m["api_key"] or ""
    if not api_key and _is_openrouter(m["base_url"]):
        api_key = os.environ.get("OPENROUTER_API_KEY", "")   # shared-key env-fallback (OR only)
    if not api_key:
        return None
    raw = json.loads(m["params_json"] or "{}")
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
        for cid, res in succeeded.items():
            conn.execute("UPDATE issue SET status='superseded' WHERE paragraph_id=? AND criterion_id=? AND kind='live' AND status='open'",
                         (pid, cid))
            conn.execute(
                "INSERT INTO score(paragraph_id,criterion_id,value,summary,aggregate,criteria_key,kind,created_at) "
                "VALUES(?,?,?,?,?,?,'live',?)",
                (pid, cid, res["value"], res["summary"], aggregate, criteria_key, ts))
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
    with db._lock:
        d = conn.execute("SELECT * FROM document WHERE id=?", (doc_id,)).fetchone()
        if not d:
            raise HTTPException(404, "document not found")
        pids = [r["id"] for r in conn.execute("SELECT id FROM paragraph WHERE document_id=?", (doc_id,))]
        for pid in pids:
            # Archive live results (never delete — predictions are irreproducible);
            # seed AND cache stay untouched as static reference data.
            conn.execute("UPDATE score SET kind='archived' WHERE paragraph_id=? AND kind='live'", (pid,))
            conn.execute("UPDATE issue SET status='archived' WHERE paragraph_id=? AND kind='live'", (pid,))
            conn.execute("UPDATE issue SET status='open' WHERE paragraph_id=? AND kind='seed'", (pid,))
            conn.execute("UPDATE paragraph SET target=seed_target WHERE id=?", (pid,))
        conn.execute("UPDATE document SET version=version+1 WHERE id=?", (doc_id,))
        conn.commit()
        return _doc_dict(conn, conn.execute("SELECT * FROM document WHERE id=?", (doc_id,)).fetchone())


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
    conn = db.connect()
    with db._lock:
        row = conn.execute("SELECT * FROM model WHERE name=?", (name,)).fetchone()
        if not row:
            raise HTTPException(404, "model not found")
        api_key = m["apiKey"] if m.get("apiKey") else row["api_key"]  # omitted → keep existing
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


# ─────────────────────────── terminology (term-agent fills later) ───────────────────────────

@app.post("/api/paragraphs/{pid}/terms")
def post_terms(pid: int) -> list:
    conn = db.connect()
    _para_or_404(conn, pid)
    return [_term_dict(r) for r in conn.execute("SELECT * FROM term WHERE paragraph_id=? ORDER BY char_start", (pid,))]


# ─────────────────────────── static frontend (production container) ───────────────────────────

_static_dir = os.environ.get("DEMO_STATIC_DIR")
if _static_dir:
    from fastapi.staticfiles import StaticFiles

    # Mounted last so every /api route above wins; html=True serves index.html at /.
    app.mount("/", StaticFiles(directory=_static_dir, html=True), name="static")
