"""POST /api/paragraphs/{pid}/refine + GET/PUT /api/refiner-config.

Response/status-code contract is dictated by the already-shipped frontend
(api-client.ts refineParagraph / store.ts's refineParagraph action): success
returns the plain updated Paragraph dict (no envelope), scores/aggregate on
that response are the PRE-refine values (refine never touches `score`), and
409 is reserved EXCLUSIVELY for no_open_issues (the frontend silently
swallows a 409 — every other failure must use a different status so it still
surfaces an error banner).
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException


@pytest.fixture
def seeded(tmp_path, monkeypatch):
    from palimpsest.webapp import budget, db
    from palimpsest.webapp import seed as seedmod
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(db, "_conn", None)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    seedmod.seed()
    budget.reset()
    budget._CAP_USD = 2.0
    budget._CALL_CAP = 200
    budget._PRICES = {}
    yield db
    if db._conn is not None:
        db._conn.close()
        db._conn = None


def _install_fake_client(monkeypatch, content=None, *, cost=0.0003, raises=None, fail_times=0):
    """Mirrors test_test_endpoint.py's _install_fake_client, but 3-arg
    compatible with refine's `_client_for(conn, name, params)` call shape."""
    from palimpsest.llm.client import LLMResult, Usage
    from palimpsest.webapp import app

    calls = {"n": 0}

    class FakeClient:
        config = SimpleNamespace(max_tokens=1024, extra_body=None)

        def complete(self, system, user):
            calls["n"] += 1
            if raises is not None and calls["n"] <= fail_times:
                raise raises
            return LLMResult(content=content, usage=Usage(50, 20, 0, cost))

    monkeypatch.setattr(app, "_client_for", lambda conn, name, params=None: FakeClient())
    return calls


def _open_issue(conn, pid: int):
    return conn.execute(
        "SELECT id, criterion_id FROM issue WHERE paragraph_id=? AND status='open' LIMIT 1", (pid,)
    ).fetchone()


def _dismiss_all_issues(conn, pid: int):
    conn.execute("UPDATE issue SET status='archived' WHERE paragraph_id=?", (pid,))
    conn.commit()


# ─────────────────────────── refine: success ───────────────────────────

def test_refine_success_updates_target_accepts_issues_writes_revision(seeded, monkeypatch):
    from palimpsest.webapp.app import refine_paragraph

    conn = seeded.connect()
    pid = conn.execute("SELECT id FROM paragraph ORDER BY id LIMIT 1").fetchone()["id"]
    before = conn.execute("SELECT target FROM paragraph WHERE id=?", (pid,)).fetchone()["target"]
    open_before = [r["id"] for r in conn.execute(
        "SELECT id FROM issue WHERE paragraph_id=? AND status='open'", (pid,))]
    assert open_before, "seed paragraph must start with at least one open issue"
    n_revisions_before = conn.execute(
        "SELECT COUNT(*) c FROM target_revision WHERE paragraph_id=?", (pid,)).fetchone()["c"]

    revised_text = "A cleanly revised translation."
    _install_fake_client(monkeypatch, revised_text)

    out = asyncio.run(refine_paragraph(pid))

    assert out["target"] == revised_text
    assert out["target"] != before
    assert out["id"] == pid
    # scores/aggregate are the PRE-refine values (frontend re-evaluates itself)
    assert "scores" in out and "aggregate" in out

    row = conn.execute("SELECT target FROM paragraph WHERE id=?", (pid,)).fetchone()
    assert row["target"] == revised_text

    for iid in open_before:
        status = conn.execute("SELECT status FROM issue WHERE id=?", (iid,)).fetchone()["status"]
        assert status == "accepted"

    revs = conn.execute(
        "SELECT * FROM target_revision WHERE paragraph_id=? ORDER BY id DESC LIMIT 1", (pid,)).fetchone()
    assert revs["origin"] == "refine"
    assert revs["text"] == revised_text
    n_revisions_after = conn.execute(
        "SELECT COUNT(*) c FROM target_revision WHERE paragraph_id=?", (pid,)).fetchone()["c"]
    assert n_revisions_after == n_revisions_before + 1


def test_refine_strips_code_fence_and_wrapping_quotes(seeded, monkeypatch):
    from palimpsest.webapp.app import refine_paragraph

    conn = seeded.connect()
    pid = conn.execute("SELECT id FROM paragraph ORDER BY id LIMIT 1").fetchone()["id"]
    _install_fake_client(monkeypatch, '```\n"A quoted, fenced revision."\n```')

    out = asyncio.run(refine_paragraph(pid))
    assert out["target"] == "A quoted, fenced revision."


def test_refine_does_not_touch_score_rows(seeded, monkeypatch):
    """The frontend explicitly chains its own /evaluate after refine — refine
    itself must never write a `score` row (that would make the PRE-refine-
    values claim in the response a lie)."""
    from palimpsest.webapp.app import refine_paragraph

    conn = seeded.connect()
    pid = conn.execute("SELECT id FROM paragraph ORDER BY id LIMIT 1").fetchone()["id"]
    n_scores_before = conn.execute("SELECT COUNT(*) c FROM score WHERE paragraph_id=?", (pid,)).fetchone()["c"]
    _install_fake_client(monkeypatch, "Revised.")
    asyncio.run(refine_paragraph(pid))
    n_scores_after = conn.execute("SELECT COUNT(*) c FROM score WHERE paragraph_id=?", (pid,)).fetchone()["c"]
    assert n_scores_after == n_scores_before


def test_refine_leaves_other_paragraph_issues_untouched(seeded, monkeypatch):
    conn = seeded.connect()
    from palimpsest.webapp.app import refine_paragraph
    pids = [r["id"] for r in conn.execute("SELECT id FROM paragraph ORDER BY id LIMIT 2")]
    pid, other_pid = pids[0], pids[1]
    other_open_before = {r["id"] for r in conn.execute(
        "SELECT id FROM issue WHERE paragraph_id=? AND status='open'", (other_pid,))}
    _install_fake_client(monkeypatch, "Revised.")
    asyncio.run(refine_paragraph(pid))
    other_open_after = {r["id"] for r in conn.execute(
        "SELECT id FROM issue WHERE paragraph_id=? AND status='open'", (other_pid,))}
    assert other_open_after == other_open_before


# ─────────────────────────── refine: failures ───────────────────────────

def test_refine_no_open_issues_is_409(seeded):
    from palimpsest.webapp.app import refine_paragraph

    conn = seeded.connect()
    pid = conn.execute("SELECT id FROM paragraph ORDER BY id LIMIT 1").fetchone()["id"]
    _dismiss_all_issues(conn, pid)

    with pytest.raises(HTTPException) as ei:
        asyncio.run(refine_paragraph(pid))
    assert ei.value.status_code == 409


def test_refine_paragraph_not_found_is_404(seeded):
    from palimpsest.webapp.app import refine_paragraph
    with pytest.raises(HTTPException) as ei:
        asyncio.run(refine_paragraph(999999))
    assert ei.value.status_code == 404


def test_refine_no_open_issues_does_not_call_llm(seeded, monkeypatch):
    """409 is a precondition failure — nothing should be attempted/billed."""
    from palimpsest.webapp import app
    from palimpsest.webapp.app import refine_paragraph

    conn = seeded.connect()
    pid = conn.execute("SELECT id FROM paragraph ORDER BY id LIMIT 1").fetchone()["id"]
    _dismiss_all_issues(conn, pid)
    called = {"n": 0}
    monkeypatch.setattr(app, "_client_for", lambda *a, **kw: called.__setitem__("n", called["n"] + 1))
    with pytest.raises(HTTPException):
        asyncio.run(refine_paragraph(pid))
    assert called["n"] == 0


def test_refine_no_refiner_model_configured_is_503(seeded):
    from palimpsest.webapp.app import refine_paragraph

    conn = seeded.connect()
    pid = conn.execute("SELECT id FROM paragraph ORDER BY id LIMIT 1").fetchone()["id"]
    conn.execute("UPDATE refiner_config SET model_name=NULL WHERE id=1")
    conn.commit()

    with pytest.raises(HTTPException) as ei:
        asyncio.run(refine_paragraph(pid))
    assert ei.value.status_code == 503


def test_refine_no_api_key_is_503(seeded, monkeypatch):
    from palimpsest.webapp import app
    from palimpsest.webapp.app import refine_paragraph

    conn = seeded.connect()
    pid = conn.execute("SELECT id FROM paragraph ORDER BY id LIMIT 1").fetchone()["id"]
    monkeypatch.setattr(app, "_client_for", lambda *a, **kw: None)

    with pytest.raises(HTTPException) as ei:
        asyncio.run(refine_paragraph(pid))
    assert ei.value.status_code == 503


def test_refine_translation_in_progress_is_503(seeded):
    from palimpsest.webapp import translate
    from palimpsest.webapp.app import refine_paragraph

    conn = seeded.connect()
    pid = conn.execute("SELECT id FROM paragraph ORDER BY id LIMIT 1").fetchone()["id"]
    doc_id = conn.execute("SELECT document_id FROM paragraph WHERE id=?", (pid,)).fetchone()["document_id"]
    translate._translating.add(doc_id)
    try:
        with pytest.raises(HTTPException) as ei:
            asyncio.run(refine_paragraph(pid))
        assert ei.value.status_code == 503
    finally:
        translate._translating.discard(doc_id)


def test_refine_budget_exhausted_is_429(seeded, monkeypatch):
    from palimpsest.webapp import budget
    from palimpsest.webapp.app import refine_paragraph

    conn = seeded.connect()
    pid = conn.execute("SELECT id FROM paragraph ORDER BY id LIMIT 1").fetchone()["id"]
    _install_fake_client(monkeypatch, "Revised.")
    budget._CAP_USD = 0.0

    with pytest.raises(HTTPException) as ei:
        asyncio.run(refine_paragraph(pid))
    assert ei.value.status_code == 429


def test_refine_llm_call_fails_terminally_is_502(seeded, monkeypatch):
    """One transient retry, then a terminal failure → 502 (upstream failure),
    NOT 409 (which the frontend silently swallows) and NOT a 200 ok:false
    envelope (unlike /evaluate — refine's contract is Promise<Paragraph>,
    with no partial-failure field the frontend reads)."""
    from palimpsest.webapp.app import refine_paragraph

    conn = seeded.connect()
    pid = conn.execute("SELECT id FROM paragraph ORDER BY id LIMIT 1").fetchone()["id"]
    calls = _install_fake_client(monkeypatch, "unused", raises=TimeoutError("slow"), fail_times=99)

    with pytest.raises(HTTPException) as ei:
        asyncio.run(refine_paragraph(pid))
    assert ei.value.status_code == 502
    assert calls["n"] == 2, "exactly one retry (2 total attempts), not evaluate()'s 3"

    # nothing was mutated on a terminal failure
    row = conn.execute("SELECT status FROM issue WHERE paragraph_id=? AND status='open' LIMIT 1",
                        (pid,)).fetchone()
    assert row is not None, "issues must stay open — the call never succeeded"


def test_refine_transient_error_then_success(seeded, monkeypatch):
    from palimpsest.webapp.app import refine_paragraph

    conn = seeded.connect()
    pid = conn.execute("SELECT id FROM paragraph ORDER BY id LIMIT 1").fetchone()["id"]
    calls = _install_fake_client(monkeypatch, "Recovered after one retry.",
                                  raises=TimeoutError("slow"), fail_times=1)

    out = asyncio.run(refine_paragraph(pid))
    assert out["target"] == "Recovered after one retry."
    assert calls["n"] == 2


def test_refine_empty_output_is_502_and_rejected(seeded, monkeypatch):
    from palimpsest.webapp.app import refine_paragraph

    conn = seeded.connect()
    pid = conn.execute("SELECT id FROM paragraph ORDER BY id LIMIT 1").fetchone()["id"]
    before = conn.execute("SELECT target FROM paragraph WHERE id=?", (pid,)).fetchone()["target"]
    _install_fake_client(monkeypatch, "   \n  ")   # whitespace-only

    with pytest.raises(HTTPException) as ei:
        asyncio.run(refine_paragraph(pid))
    assert ei.value.status_code == 502

    after = conn.execute("SELECT target FROM paragraph WHERE id=?", (pid,)).fetchone()["target"]
    assert after == before, "empty/whitespace output must never be written as the new target"


# ─────────────────────────── refiner-config CRUD ───────────────────────────

def test_get_refiner_config_returns_seeded_default(seeded):
    from palimpsest.webapp.app import get_refiner_config
    from palimpsest.webapp.model_matrix import DEFAULT_CRITERION_MODEL

    out = get_refiner_config()
    assert out["modelName"] == DEFAULT_CRITERION_MODEL
    assert "expert translation editor" in out["prompt"]
    assert out["params"] == {"max_tokens": 2048, "temperature": 0.2}


def test_put_refiner_config_updates_and_get_reflects(seeded):
    from palimpsest.webapp.app import RefinerConfigBody, get_refiner_config, update_refiner_config

    body = RefinerConfigBody(modelName="qwen/qwen3.6-27b", prompt="Custom refiner prompt",
                              params={"max_tokens": 1024, "temperature": 0.1})
    out = update_refiner_config(body)
    assert out["modelName"] == "qwen/qwen3.6-27b"
    assert out["prompt"] == "Custom refiner prompt"
    assert out["params"] == {"max_tokens": 1024, "temperature": 0.1}

    got = get_refiner_config()
    assert got == out


def test_put_refiner_config_unknown_param_422(seeded):
    from fastapi import HTTPException as HTTPExc

    from palimpsest.webapp.app import RefinerConfigBody, update_refiner_config

    with pytest.raises(HTTPExc) as ei:
        update_refiner_config(RefinerConfigBody(modelName=None, prompt="", params={"frobnicate": 1}))
    assert ei.value.status_code == 422


def test_put_refiner_config_secret_key_400(seeded):
    from fastapi import HTTPException as HTTPExc

    from palimpsest.webapp.app import RefinerConfigBody, update_refiner_config

    with pytest.raises(HTTPExc) as ei:
        update_refiner_config(RefinerConfigBody(modelName=None, prompt="", params={"api_key": "x"}))
    assert ei.value.status_code == 400


def test_get_refiner_config_null_row_returns_default_shape(seeded):
    """Mirrors translator/grounding-config's null-row handling — never 500."""
    from palimpsest.webapp import db
    from palimpsest.webapp.app import get_refiner_config

    conn = db.connect()
    conn.execute("DELETE FROM refiner_config")
    conn.commit()
    assert get_refiner_config() == {"modelName": None, "prompt": "", "params": {}}
