"""Fix 1 (2026-07-17): a custom criterion's user-entered prompt (POST
/api/criteria) is the DB row's ``prompt`` column. Before this fix,
judge.py::_scoring_prompt always read prompts/scoring/<id>.md from disk,
which never exists for a custom id — evaluating one was a deterministic
FileNotFoundError before any LLM call, so a custom criterion could never be
scored.

Design fact (confirmed by reading seed.py:84-89): the 3 built-in criteria
rows (accuracy/fluency/style) have their DB ``prompt`` column populated
verbatim from the SAME prompts/scoring/<id>.md files at seed time — so
DB-first-with-file-fallback is safe for them too, not just for custom rows.
"""
from __future__ import annotations

import pytest

from palimpsest.webapp import app as app_mod
from palimpsest.webapp import budget, db
from palimpsest.webapp import judge as judge_mod
from tests.conftest import _body


@pytest.fixture(autouse=True)
def _no_network_budget(monkeypatch):
    monkeypatch.setattr(budget, "_PRICES", {"m": (1e-6, 1e-6)})
    budget.reset()


@pytest.fixture()
def eval_client(client, monkeypatch):
    conn = db.connect()
    conn.execute("INSERT INTO model(name,base_url,api_key,params_json) "
                 "VALUES('m','https://openrouter.ai/api/v1','k','{}')")
    conn.commit()

    class _DummyClient:
        class config:
            max_tokens = 512

    monkeypatch.setattr(app_mod, "_client_for", lambda conn, name: _DummyClient())
    return client


def _make_para(cl, **over) -> int:
    doc = cl.post("/api/documents", json=_body(**over)).json()
    return doc["paragraphs"][0]["id"]


def _judge_result(value=8.0):
    return {"value": value, "summary": "ok", "issues": [],
            "usage": type("U", (), {"cost_usd": 0.001, "prompt_tokens": 10,
                                    "completion_tokens": 5, "reasoning_tokens": 0})()}


def _post_criterion(cl, **over):
    payload = {"id": "my-custom", "name": "My Custom", "modelName": "m",
               "prompt": "Score how well the translation preserves formality.",
               "scaleMin": 1, "scaleMax": 10, "weight": 1.0, "color": "#888", "enabled": True}
    payload.update(over)
    return cl.post("/api/criteria", json=payload)


# ── unit: _scoring_prompt / scoring_system_prompt DB-first semantics ───────

def test_scoring_prompt_raises_without_override_for_unknown_id():
    """Documents the OLD (still-correct-as-fallback) behavior: no matching
    prompts/scoring/<id>.md and no override -> FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        judge_mod._scoring_prompt("no-such-criterion-id")


def test_scoring_prompt_uses_override_for_unknown_id():
    """The fix: a non-empty DB-row prompt is used verbatim, no file lookup at
    all, even for an id that has no matching file on disk."""
    text = judge_mod._scoring_prompt("no-such-criterion-id", "Custom rubric body.")
    assert text == "Custom rubric body."


def test_scoring_system_prompt_embeds_custom_prompt_no_file_needed():
    system = judge_mod.scoring_system_prompt(
        "my-custom", "ru", "en", prompt="Score formality preservation.")
    assert "Score formality preservation." in system


# ── integration: POST /api/criteria -> /evaluate reaches the judge stub ────

def test_custom_criterion_prompt_reaches_judge_one(eval_client, monkeypatch):
    """The exact user-entered prompt text created via POST /api/criteria is
    what judge_one receives — not a FileNotFoundError from the (nonexistent)
    prompts/scoring/my-custom.md."""
    r = _post_criterion(eval_client)
    assert r.status_code == 200, r.text

    seen = {}

    def recording_judge(client, criterion_id, source, target, *, source_lang, target_lang, prompt=None):
        seen["prompt"] = prompt
        return _judge_result()

    monkeypatch.setattr(app_mod, "judge_one", recording_judge)
    pid = _make_para(eval_client)
    ev = eval_client.post(f"/api/paragraphs/{pid}/evaluate").json()

    assert ev["failedCriterionIds"] == []
    assert seen["prompt"] == "Score how well the translation preserves formality."


def test_criterion_empty_prompt_and_no_file_fails_per_criterion_not_500(eval_client):
    """A criterion row whose prompt is empty AND has no prompts/scoring/<id>.md
    file (only reachable by clearing the prompt after creation — POST itself
    rejects a blank prompt at 422) fails as a per-criterion failedCriterionIds
    entry, not a 500 crashing the whole /evaluate call."""
    r = _post_criterion(eval_client, id="blank-crit", prompt="placeholder")
    assert r.status_code == 200, r.text
    conn = db.connect()
    conn.execute("UPDATE criterion SET prompt='' WHERE id='blank-crit'")
    conn.commit()

    pid = _make_para(eval_client)
    r = eval_client.post(f"/api/paragraphs/{pid}/evaluate")
    assert r.status_code == 200
    assert r.json()["failedCriterionIds"] == ["blank-crit"]


def test_builtin_criterion_falls_back_to_file_when_db_prompt_empty(eval_client, monkeypatch):
    """A bare-metal INSERT (unlike seed.py) that leaves `prompt` empty for a
    BUILT-IN id still resolves via the prompts/scoring/<id>.md file — DB-first
    with file fallback, not DB-only."""
    conn = db.connect()
    conn.execute("INSERT INTO criterion(id,name,model_name,weight,scale_min,scale_max,enabled) "
                 "VALUES('accuracy','Accuracy','m',1.0,1,10,1)")
    conn.commit()

    monkeypatch.setattr(app_mod, "judge_one", lambda *a, **kw: _judge_result())
    pid = _make_para(eval_client)
    ev = eval_client.post(f"/api/paragraphs/{pid}/evaluate").json()
    assert ev["failedCriterionIds"] == []


# ── seed.py design fact: built-in rows' DB prompt matches the file ─────────

def test_seed_criteria_db_prompt_matches_scoring_file(tmp_path, monkeypatch):
    from palimpsest import paths
    from palimpsest.webapp import seed as seedmod

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "seedcheck.db")
    monkeypatch.setattr(db, "_conn", None)
    seedmod.seed()
    conn = db.connect()
    for cid in ("accuracy", "fluency", "style"):
        row = conn.execute("SELECT prompt FROM criterion WHERE id=?", (cid,)).fetchone()
        file_text = (paths.PROMPTS / "scoring" / f"{cid}.md").read_text(encoding="utf-8")
        assert row["prompt"] == file_text
    db._conn.close()
    db._conn = None
