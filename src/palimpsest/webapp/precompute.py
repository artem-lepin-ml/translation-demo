"""Background first-pass scoring for uploaded documents (spec §5.6).

One paid judge pass over the first PRECOMPUTE_PARAS paragraphs. Each paragraph
atomically writes kind='seed' (baseline scores + open issues) and kind='cache'
score copies (same values, no uplift). Budget-critical: every call goes through
budget.reserve()/settle() plus the global precompute sub-cap below.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone

from . import budget, db
from .aggregate import compute_aggregate

PRECOMPUTE_PARAS = 12
_CALL_CAP = int(os.environ.get("PALIMPSEST_PRECOMPUTE_CALLS", "80"))

# In-memory status per document; absent after restart (accepted risk, spec §5.6).
_status: dict[int, dict] = {}

# Strong references to in-flight precompute tasks, keyed by doc_id — required
# so DELETE can cancel a running task (asyncio.create_task's return value is
# otherwise the only reference, and it's discarded at the call site).
_tasks: dict[int, asyncio.Task] = {}


def status_for(doc_id: int) -> dict | None:
    return _status.get(doc_id)


def mark_skipped(doc_id: int) -> None:
    _status[doc_id] = {"status": "skipped", "done": 0, "planned": 0, "succeeded": 0}


def mark_started(doc_id: int, n_paragraphs: int) -> None:
    """Pre-set status so the 201 body already carries it; run() refines later."""
    _status[doc_id] = {"status": "running", "done": 0,
                        "planned": min(n_paragraphs, PRECOMPUTE_PARAS), "succeeded": 0}


def launch(doc_id: int, judge_live) -> None:
    t = asyncio.create_task(run(doc_id, judge_live))
    _tasks[doc_id] = t
    t.add_done_callback(lambda _: _tasks.pop(doc_id, None))


def cancel(doc_id: int) -> None:
    """Stop an in-flight precompute run for ``doc_id`` (called from DELETE).
    Cancels the task if still running and drops its status entry."""
    t = _tasks.get(doc_id)
    if t is not None:
        t.cancel()
    _status.pop(doc_id, None)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _take_call_slot() -> bool:
    """Sub-cap check-and-increment BEFORE the call, under budget's own lock
    (решение №10 — no second locking scheme)."""
    async with budget._lock:
        used = budget._STATE.get("precompute_calls", 0)
        if used >= _CALL_CAP:
            return False
        budget._STATE["precompute_calls"] = used + 1
        return True


def _already_scored(conn, pid: int) -> bool:
    return conn.execute("SELECT 1 FROM score WHERE paragraph_id=? LIMIT 1", (pid,)).fetchone() is not None


def _document_exists(conn, doc_id: int) -> bool:
    return conn.execute("SELECT 1 FROM document WHERE id=?", (doc_id,)).fetchone() is not None


def _write_paragraph(conn, doc_id: int, pid: int, enabled, results: dict) -> bool:
    """Paragraph-atomic write of seed + cache rows. Returns False if a live
    /evaluate slipped in during the LLM calls (TOCTOU re-check, решение №9),
    or if the document was deleted during the LLM calls (spend-after-delete
    guard — the DELETE route also cancels the task, but this closes the race
    window between "task already past the cancellation point" and "the write
    lock is acquired")."""
    values = {cid: r["value"] for cid, r in results.items()}
    aggregate, criteria_key = compute_aggregate(values, enabled)
    ts = _now()
    with db._lock:
        if not _document_exists(conn, doc_id):
            return False                       # document deleted mid-flight, discard write
        if _already_scored(conn, pid):
            return False                       # discard judged results, no write
        for cid, res in results.items():
            for kind in ("seed", "cache"):
                conn.execute(
                    "INSERT INTO score(paragraph_id,criterion_id,value,summary,aggregate,"
                    "criteria_key,kind,created_at) VALUES(?,?,?,?,?,?,?,?)",
                    (pid, cid, res["value"], res["summary"], aggregate, criteria_key, kind, ts))
            for it in res["issues"]:
                conn.execute(
                    "INSERT INTO issue(paragraph_id,criterion_id,target_fragment,source_fragment,"
                    "explanation,suggestion,severity,mqm_category,status,kind,created_at) "
                    "VALUES(?,?,?,?,?,?,?,?,'open','seed',?)",
                    (pid, cid, it["targetFragment"], it["sourceFragment"], it["explanation"],
                     it["suggestion"], it["severity"], it["mqmCategory"], ts))
        conn.commit()                          # единственный commit на границе абзаца (M3)
    return True


async def run(doc_id: int, judge_live) -> None:
    """Sequential precompute loop. ``judge_live`` is app._judge_live (passed in
    to avoid a circular import). Cancellation (DELETE → ``cancel()``) must
    propagate, not be swallowed as an ordinary failure; any other exception is
    logged and leaves the document's status as 'stopped' rather than crashing
    the fire-and-forget task silently."""
    try:
        await _run(doc_id, judge_live)
    except asyncio.CancelledError:
        raise                                  # propagate — do not touch _status further
    except Exception:
        logging.exception("precompute.run failed for doc_id=%s", doc_id)
        _status[doc_id] = {**_status.get(doc_id, {"done": 0, "planned": 0}), "status": "stopped"}


async def _run(doc_id: int, judge_live) -> None:
    conn = db.connect()
    d = conn.execute("SELECT * FROM document WHERE id=?", (doc_id,)).fetchone()
    if d is None:
        return
    paras = conn.execute(
        "SELECT * FROM paragraph WHERE document_id=? ORDER BY idx LIMIT ?",
        (doc_id, PRECOMPUTE_PARAS)).fetchall()
    enabled = conn.execute("SELECT * FROM criterion WHERE enabled=1").fetchall()
    _status[doc_id] = {"status": "running", "done": 0, "planned": len(paras), "succeeded": 0}
    for p in paras:
        if not _document_exists(conn, doc_id):
            _status.pop(doc_id, None)          # документ удалён во время прогрева
            return
        if _already_scored(conn, p["id"]):     # дешёвый пре-чек: не тратить деньги
            _status[doc_id]["done"] += 1
            _status[doc_id]["succeeded"] += 1
            continue
        results: dict[str, dict] = {}
        failed = False
        for c in enabled:
            if not await _take_call_slot():
                _status[doc_id]["status"] = "stopped"
                return
            try:
                results[c["id"]] = await judge_live(
                    conn, c, p["source"], p["target"],
                    d["source_lang"], d["target_lang"], endpoint="precompute")
            except Exception:
                logging.exception(
                    "precompute judge call failed doc_id=%s paragraph_id=%s criterion=%s",
                    doc_id, p["id"], c["id"])
                failed = True                  # BudgetExceeded/сеть → абзац не пишется
                break
        if not failed and _write_paragraph(conn, doc_id, p["id"], enabled, results):
            _status[doc_id]["succeeded"] += 1
        _status[doc_id]["done"] += 1
    _status[doc_id]["status"] = "done"
