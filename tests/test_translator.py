"""Spec 2026-07-05-translator: translator-config CRUD, translate:true document
creation semantics, the background run_translation loop, and the concurrency
guards against evaluate/reset/delete."""
from __future__ import annotations

import asyncio
import json

import pytest

from palimpsest.webapp import app as app_mod
from palimpsest.webapp import budget, db, translate

from .conftest import _body


@pytest.fixture(autouse=True)
def _reset_translate_state():
    translate._status.clear()
    translate._translating.clear()
    yield
    translate._status.clear()
    translate._translating.clear()


def _translate_body(**over):
    base = {"title": "Draft", "sourceLang": "ru", "targetLang": "en", "precompute": False,
            "translate": True,
            "paragraphs": [{"source": f"src{i}", "target": ""} for i in range(3)]}
    base.update(over)
    return base


# ── GET/PUT /api/translator-config ──────────────────────────────────────────

def test_get_translator_config_default_empty(client):
    got = client.get("/api/translator-config").json()
    assert got == {"modelName": None, "prompt": "", "params": {}}


def test_put_translator_config_updates_and_get_reflects(client):
    db.connect().execute(
        "INSERT INTO model(name,base_url,api_key,params_json) VALUES(?,?,?,?)",
        ("openai/gpt-5.4-mini", "https://openrouter.ai/api/v1", "k", "{}"))
    db.connect().commit()
    r = client.put("/api/translator-config", json={
        "modelName": "openai/gpt-5.4-mini", "prompt": "Translate {source_lang}->{target_lang}",
        "params": {"max_tokens": 1024, "temperature": 0.2}})
    assert r.status_code == 200, r.text
    got = client.get("/api/translator-config").json()
    assert got["modelName"] == "openai/gpt-5.4-mini"
    assert got["params"] == {"max_tokens": 1024, "temperature": 0.2}


def test_put_translator_config_unknown_param_422(client):
    r = client.put("/api/translator-config", json={"modelName": None, "prompt": "",
                                                     "params": {"frobnicate": 1}})
    assert r.status_code == 422, r.text


def test_put_translator_config_secret_key_400(client):
    r = client.put("/api/translator-config", json={"modelName": None, "prompt": "",
                                                     "params": {"api_key": "x"}})
    assert r.status_code == 400, r.text


# ── POST /api/documents translate:true ──────────────────────────────────────

def test_create_translate_true_empty_targets_ok(client, monkeypatch):
    monkeypatch.setattr(translate, "launch", lambda *a, **kw: None)
    r = client.post("/api/documents", json=_translate_body())
    assert r.status_code == 201, r.text
    doc = r.json()
    for p in doc["paragraphs"]:
        assert p["target"] == ""
    rows = db.connect().execute(
        "SELECT seed_target FROM paragraph WHERE document_id=?", (doc["id"],)).fetchall()
    assert all(r["seed_target"] == "" for r in rows)


def test_create_without_translate_flag_empty_target_still_422(client):
    r = client.post("/api/documents", json=_body(paragraphs=[{"source": "s", "target": ""}]))
    assert r.status_code == 422
    assert r.json()["detail"] == "empty_cell:0"


def test_create_translate_true_mixed_targets_422(client, monkeypatch):
    monkeypatch.setattr(translate, "launch", lambda *a, **kw: None)
    body = _translate_body(paragraphs=[{"source": "s1", "target": ""},
                                        {"source": "s2", "target": "already translated"}])
    r = client.post("/api/documents", json=body)
    assert r.status_code == 422
    assert r.json()["detail"] == "mixed_targets"


def test_create_translate_true_forces_precompute_off_and_no_scores(client, monkeypatch):
    monkeypatch.setattr(translate, "launch", lambda *a, **kw: None)
    r = client.post("/api/documents", json=_translate_body(precompute=True))
    assert r.status_code == 201, r.text
    doc = r.json()
    assert doc["precompute"]["status"] == "skipped"
    assert doc["translation"]["status"] == "running"
    assert doc["translation"]["total"] == 3
    n_scores = db.connect().execute(
        "SELECT COUNT(*) c FROM score s JOIN paragraph p ON p.id=s.paragraph_id "
        "WHERE p.document_id=?", (doc["id"],)).fetchone()["c"]
    assert n_scores == 0


def test_create_translate_true_no_upload_revision_written_yet(client, monkeypatch):
    """translate:true leaves paragraphs without a target — no 'upload' revision
    is written at create time; translate.py writes the first one once real
    text lands (spec §2.1 point 1)."""
    monkeypatch.setattr(translate, "launch", lambda *a, **kw: None)
    doc = client.post("/api/documents", json=_translate_body()).json()
    pid = doc["paragraphs"][0]["id"]
    n = db.connect().execute("SELECT COUNT(*) c FROM target_revision WHERE paragraph_id=?", (pid,)).fetchone()["c"]
    assert n == 0


# ── run_translation background loop ─────────────────────────────────────────

class _FakeUsage:
    cost_usd = 0.0001
    prompt_tokens = 10
    completion_tokens = 5
    reasoning_tokens = 0


class _FakeResult:
    def __init__(self, content):
        self.content = content
        self.usage = _FakeUsage()


class _FakeClient:
    """Records every (system, user) call; config mimics LLMConfig enough for
    translate.py's budget math and app._client_for-style callers."""

    def __init__(self, model="fake/model", max_tokens=256, reply_prefix="EN"):
        self.calls: list[tuple[str, str]] = []
        self._reply_prefix = reply_prefix
        self.config = type("Cfg", (), {"model": model, "max_tokens": max_tokens})()

    def complete(self, system, user):
        self.calls.append((system, user))
        idx = len(self.calls)
        return _FakeResult(f"{self._reply_prefix}{idx}")


def _mk_translate_doc(client, monkeypatch, n=3):
    monkeypatch.setattr(translate, "launch", lambda *a, **kw: None)
    conn = db.connect()
    conn.execute("INSERT INTO model(name,base_url,api_key,params_json) VALUES(?,?,?,?)",
                 ("fake/model", "http://fake", "k", "{}"))
    conn.execute(
        "INSERT INTO translator_config(id,model_name,prompt,params_json) VALUES(1,?,?,?)",
        ("fake/model", "Translate {source_lang} into {target_lang}.", "{}"))
    conn.commit()
    return client.post("/api/documents", json=_translate_body(
        paragraphs=[{"source": f"src{i}", "target": ""} for i in range(n)])).json()


def test_run_translation_happy_path(client, monkeypatch):
    monkeypatch.setattr(budget, "_PRICES", {"fake/model": (1e-6, 1e-6)})
    budget.reset()
    doc = _mk_translate_doc(client, monkeypatch, n=3)
    fake = _FakeClient()

    def client_for(conn, name, params_override=None):
        return fake

    asyncio.run(translate.run_translation(doc["id"], client_for))
    status = translate.status_for(doc["id"])
    assert status["status"] == "done"
    assert status["done"] == 3

    got = client.get(f"/api/documents/{doc['id']}").json()
    targets = [p["target"] for p in got["paragraphs"]]
    assert targets == ["EN1", "EN2", "EN3"]
    for p in got["paragraphs"]:
        pid = p["id"]
        revs = db.connect().execute(
            "SELECT origin FROM target_revision WHERE paragraph_id=?", (pid,)).fetchall()
        assert [r["origin"] for r in revs] == ["translate"]


def test_run_translation_idempotent_resumes_only_empty(client, monkeypatch):
    monkeypatch.setattr(budget, "_PRICES", {"fake/model": (1e-6, 1e-6)})
    budget.reset()
    doc = _mk_translate_doc(client, monkeypatch, n=2)
    fake = _FakeClient()

    def client_for(conn, name, params_override=None):
        return fake

    asyncio.run(translate.run_translation(doc["id"], client_for))
    assert len(fake.calls) == 2

    # Re-run: both paragraphs already have a target → no new calls made.
    asyncio.run(translate.run_translation(doc["id"], client_for))
    assert len(fake.calls) == 2
    status = translate.status_for(doc["id"])
    assert status["status"] == "done" and status["done"] == 2


def test_run_translation_rolling_context(client, monkeypatch):
    monkeypatch.setattr(budget, "_PRICES", {"fake/model": (1e-6, 1e-6)})
    budget.reset()
    doc = _mk_translate_doc(client, monkeypatch, n=3)
    fake = _FakeClient()

    def client_for(conn, name, params_override=None):
        return fake

    asyncio.run(translate.run_translation(doc["id"], client_for))
    # 1st call has no prior context; 2nd includes EN1; 3rd includes EN1+EN2.
    assert "EN1" not in fake.calls[0][1]
    assert "EN1" in fake.calls[1][1]
    assert "EN1" in fake.calls[2][1] and "EN2" in fake.calls[2][1]


def test_run_translation_no_api_key(client, monkeypatch):
    doc = _mk_translate_doc(client, monkeypatch, n=1)
    # translator_config has no model_name in a fresh conftest DB → client_for
    # is never even reached; run_translation must still report the reason.
    asyncio.run(translate.run_translation(doc["id"], lambda *a, **kw: None))
    status = translate.status_for(doc["id"])
    assert status["status"] == "failed"
    assert status["error_reason"] == "no_api_key"


def test_run_translation_params_come_from_translator_config_not_registry(client, monkeypatch):
    """HIGH from review: _client_for's params_override must win over the
    model's own registry row (spec §3.1). Uses a model absent from
    model_matrix.MATRIX so capability-filtering doesn't strip temperature —
    the point here is override-vs-registry, not per-model capability gating."""
    conn = db.connect()
    conn.execute("INSERT INTO model(name,base_url,api_key,params_json) VALUES(?,?,?,?)",
                 ("custom/unlisted-model", "http://fake", "k",
                  json.dumps({"max_tokens": 999, "temperature": 0.9})))
    conn.execute(
        "INSERT INTO translator_config(id,model_name,prompt,params_json) VALUES(1,?,?,?)",
        ("custom/unlisted-model", "Translate {source_lang}->{target_lang}",
         json.dumps({"max_tokens": 111, "temperature": 0.1})))
    conn.commit()
    translator_params = json.loads(
        conn.execute("SELECT params_json FROM translator_config WHERE id=1").fetchone()["params_json"])
    built = app_mod._client_for(conn, "custom/unlisted-model", translator_params)
    assert built.config.max_tokens == 111
    assert built.config.temperature == 0.1


# ── POST /api/documents/{id}/translate ──────────────────────────────────────

def test_translate_endpoint_seed_document_403(client):
    conn = db.connect()
    doc_id = conn.execute(
        "INSERT INTO document(title,source_lang,target_lang,source_model,version,origin,created_at) "
        "VALUES('S','ru','en','m',0,'seed','now')").lastrowid
    conn.commit()
    r = client.post(f"/api/documents/{doc_id}/translate")
    assert r.status_code == 403


def test_translate_endpoint_no_config_is_409(client, monkeypatch):
    monkeypatch.setattr(translate, "launch", lambda *a, **kw: None)
    doc = client.post("/api/documents", json=_translate_body()).json()
    # the no-op'd auto-launch never actually ran
    translate._translating.discard((db.current_sid(), doc["id"]))
    r = client.post(f"/api/documents/{doc['id']}/translate")
    assert r.status_code == 409
    assert r.json()["detail"] == "no_api_key"


def test_translate_endpoint_budget_exhausted_409(client, monkeypatch):
    monkeypatch.setattr(translate, "launch", lambda *a, **kw: None)
    conn = db.connect()
    conn.execute("INSERT INTO model(name,base_url,api_key,params_json) VALUES(?,?,?,?)",
                 ("openai/gpt-5.4-mini", "https://openrouter.ai/api/v1", "k", "{}"))
    conn.execute(
        "INSERT INTO translator_config(id,model_name,prompt,params_json) VALUES(1,?,?,?)",
        ("openai/gpt-5.4-mini", "p", json.dumps({"max_tokens": 2048})))
    conn.commit()
    doc = client.post("/api/documents", json=_translate_body()).json()
    # the no-op'd auto-launch never actually ran
    translate._translating.discard((db.current_sid(), doc["id"]))

    budget._STATE["spent"] = budget._CAP_USD    # already at the cap
    try:
        r = client.post(f"/api/documents/{doc['id']}/translate")
        assert r.status_code == 409
        assert r.json()["detail"] == "budget_exhausted"
    finally:
        budget.reset()
    assert (db.current_sid(), doc["id"]) not in translate._translating


def test_translate_endpoint_starts_and_returns_total(client, monkeypatch):
    launched = {}
    monkeypatch.setattr(
        translate, "launch", lambda doc_id, cf, *a, **kw: launched.setdefault("doc_id", doc_id))
    conn = db.connect()
    conn.execute("INSERT INTO model(name,base_url,api_key,params_json) VALUES(?,?,?,?)",
                 ("openai/gpt-5.4-mini", "https://openrouter.ai/api/v1", "k", "{}"))
    conn.execute(
        "INSERT INTO translator_config(id,model_name,prompt,params_json) VALUES(1,?,?,?)",
        ("openai/gpt-5.4-mini", "p", json.dumps({"max_tokens": 256})))
    conn.commit()
    doc = client.post("/api/documents", json=_translate_body()).json()
    # the no-op'd auto-launch never actually ran
    translate._translating.discard((db.current_sid(), doc["id"]))
    r = client.post(f"/api/documents/{doc['id']}/translate")
    assert r.status_code == 202, r.text
    assert r.json() == {"status": "started", "total": 3}
    assert launched["doc_id"] == doc["id"]
    assert translate.status_for(doc["id"])["status"] == "running"


# ── concurrency guards ───────────────────────────────────────────────────

def test_evaluate_409_while_translating(client, monkeypatch):
    monkeypatch.setattr(translate, "launch", lambda *a, **kw: None)
    doc = client.post("/api/documents", json=_translate_body()).json()
    translate._translating.add((db.current_sid(), doc["id"]))
    pid = doc["paragraphs"][0]["id"]
    r = client.post(f"/api/paragraphs/{pid}/evaluate")
    assert r.status_code == 409
    assert r.json()["detail"] == "translation_in_progress"


def test_reset_409_while_translating(client, monkeypatch):
    monkeypatch.setattr(translate, "launch", lambda *a, **kw: None)
    doc = client.post("/api/documents", json=_translate_body()).json()
    translate._translating.add((db.current_sid(), doc["id"]))
    r = client.post(f"/api/documents/{doc['id']}/reset")
    assert r.status_code == 409


def test_delete_cancels_translate_task():
    """Mirrors test_precompute.py's DELETE-cancels-precompute test: a slow
    in-flight translate task must not keep making calls after DELETE returns."""
    from fastapi.testclient import TestClient
    import tempfile
    from palimpsest.webapp import db as db_mod

    with tempfile.TemporaryDirectory() as tmp:
        db_mod.DB_PATH = __import__("pathlib").Path(tmp) / "t.db"
        db_mod._conn = None
        db_mod.init_db(reset=True)
        c = TestClient(app_mod.app)
        doc = c.post("/api/documents", json=_translate_body(
            paragraphs=[{"source": f"s{i}", "target": ""} for i in range(5)])).json()

        counter = {"calls": 0}

        async def scenario():
            calls = counter

            class SlowClient:
                config = type("Cfg", (), {"model": "m", "max_tokens": 64})()

                def complete(self, system, user):
                    calls["calls"] += 1
                    import time
                    time.sleep(0.05)
                    return _FakeResult("EN")

            def client_for(conn, name, params_override=None):
                return SlowClient()

            key = (db_mod.current_sid(), doc["id"])
            translate._translating.add(key)
            task = asyncio.create_task(translate.run_translation(doc["id"], client_for))
            translate._tasks[key] = task
            await asyncio.sleep(0.02)

            r = c.delete(f"/api/documents/{doc['id']}")
            assert r.status_code == 204
            translate.cancel(doc["id"])

            calls_at_delete = calls["calls"]
            await asyncio.sleep(0.2)
            return calls_at_delete, calls["calls"]

        before, after = asyncio.run(scenario())
        assert after == before, "no further translate calls after DELETE returns"
