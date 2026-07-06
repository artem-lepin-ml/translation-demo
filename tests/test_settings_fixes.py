"""Spec 2026-07-05-settings-fixes: editable prompt persistence, params
whitelist + effectiveParams, apiKey clear (presence-check), precompute
error_reason, enabled=0 exclusion, and GET /api/health limits."""
from __future__ import annotations

import asyncio

from palimpsest.webapp import app as app_mod
from palimpsest.webapp import budget, db, precompute

from .conftest import _body


def _model_payload(**over):
    payload = {"baseUrl": "https://openrouter.ai/api/v1", "apiKey": "k", "params": {}}
    payload.update(over)
    return payload


# ── §2.3 editable evaluator prompt ──────────────────────────────────────────

def test_put_criterion_prompt_persists_and_get_reflects(client):
    conn = db.connect()
    conn.execute("INSERT INTO model(name,base_url,api_key,params_json) VALUES('m','http://x','k','{}')")
    conn.execute("INSERT INTO criterion(id,name,model_name,prompt,scale_min,scale_max,weight,color,enabled) "
                 "VALUES('accuracy','Accuracy','m','old prompt',1,10,0.3,'#888',1)")
    conn.commit()
    payload = {"id": "accuracy", "name": "Accuracy", "modelName": "m", "prompt": "NEW PROMPT TEXT",
               "scaleMin": 1, "scaleMax": 10, "weight": 0.3, "color": "#888", "enabled": True}
    r = client.put("/api/criteria/accuracy", json=payload)
    assert r.status_code == 200, r.text
    assert r.json()["prompt"] == "NEW PROMPT TEXT"
    got = client.get("/api/criteria").json()
    assert next(c for c in got if c["id"] == "accuracy")["prompt"] == "NEW PROMPT TEXT"


# ── §2.4 params whitelist + effectiveParams ─────────────────────────────────

def test_post_model_unknown_param_is_422(client):
    r = client.post("/api/models", json={"name": "x/y", **_model_payload(params={"frobnicate": 1})})
    assert r.status_code == 422, r.text
    assert "unknown param" in r.json()["detail"]


def test_post_model_enable_thinking_accepted(client):
    r = client.post("/api/models", json={"name": "x/y", **_model_payload(
        params={"enable_thinking": True, "max_tokens": 512})})
    assert r.status_code == 200, r.text
    assert r.json()["params"]["enable_thinking"] is True


def test_post_model_reasoning_bad_effort_is_422(client):
    r = client.post("/api/models", json={"name": "x/y", **_model_payload(
        params={"reasoning": {"effort": "extreme"}})})
    assert r.status_code == 422, r.text


def test_post_model_max_tokens_out_of_range_is_422(client):
    r = client.post("/api/models", json={"name": "x/y", **_model_payload(params={"max_tokens": 0})})
    assert r.status_code == 422, r.text
    r2 = client.post("/api/models", json={"name": "x/z", **_model_payload(params={"max_tokens": 999999})})
    assert r2.status_code == 422, r2.text


def test_get_models_includes_effective_params(client):
    client.post("/api/models", json={"name": "x/y", **_model_payload(params={"max_tokens": 555})})
    got = next(m for m in client.get("/api/models").json() if m["name"] == "x/y")
    assert "effectiveParams" in got
    assert got["effectiveParams"]["max_tokens"] == 555


# ── §2.5 apiKey clear (presence-check) ──────────────────────────────────────

def test_put_model_omitted_api_key_keeps_existing(client):
    client.post("/api/models", json={"name": "x/y", "baseUrl": "http://x", "apiKey": "secret-key",
                                      "params": {}})
    r = client.put("/api/models/x/y", json={"baseUrl": "http://x", "params": {}})  # apiKey omitted
    assert r.status_code == 200, r.text
    row = db.connect().execute("SELECT api_key FROM model WHERE name='x/y'").fetchone()
    assert row["api_key"] == "secret-key"


def test_put_model_empty_api_key_clears_it(client):
    client.post("/api/models", json={"name": "x/y", "baseUrl": "http://x", "apiKey": "secret-key",
                                      "params": {}})
    r = client.put("/api/models/x/y", json={"baseUrl": "http://x", "apiKey": "", "params": {}})
    assert r.status_code == 200, r.text
    row = db.connect().execute("SELECT api_key FROM model WHERE name='x/y'").fetchone()
    assert row["api_key"] == ""


# ── §2.6 precompute error_reason ────────────────────────────────────────────

def test_precompute_no_api_key_error_reason(client):
    conn = db.connect()
    conn.execute("INSERT INTO criterion(id,name,weight,scale_min,scale_max,enabled) "
                 "VALUES('accuracy','Accuracy',1.0,1,10,1)")
    conn.commit()

    async def failing_judge(conn, criterion, source, target, sl, tl, endpoint="precompute"):
        raise RuntimeError("no api key for model")

    doc = client.post("/api/documents", json=_body(paragraphs=[{"source": "s", "target": "t"}])).json()
    asyncio.run(precompute.run(doc["id"], failing_judge))
    status = precompute.status_for(doc["id"])
    assert status["error_reason"] == "no_api_key"
    got = client.get(f"/api/documents/{doc['id']}").json()
    assert got["precompute"]["errorReason"] == "no_api_key"


# ── enabled=0 exclusion ──────────────────────────────────────────────────

def test_disabled_criterion_excluded_from_evaluate(client, monkeypatch):
    monkeypatch.setattr(budget, "_PRICES", {"m": (1e-6, 1e-6)})
    budget.reset()
    conn = db.connect()
    conn.execute("INSERT INTO model(name,base_url,api_key,params_json) VALUES('m','http://x','k','{}')")
    conn.execute("INSERT INTO criterion(id,name,model_name,weight,scale_min,scale_max,enabled) "
                 "VALUES('accuracy','Accuracy','m',1.0,1,10,1)")
    conn.execute("INSERT INTO criterion(id,name,model_name,weight,scale_min,scale_max,enabled) "
                 "VALUES('disabled-crit','Disabled','m',1.0,1,10,0)")
    conn.commit()

    usage = type("U", (), {"cost_usd": 0.0, "prompt_tokens": 1, "completion_tokens": 1, "reasoning_tokens": 0})()

    def fake_judge_one(client_, criterion_id, source, target, **kw):
        return {"value": 8.0, "summary": "ok", "issues": [], "usage": usage}

    monkeypatch.setattr(app_mod, "judge_one", fake_judge_one)

    class _Dummy:
        class config:
            max_tokens = 512

    monkeypatch.setattr(app_mod, "_client_for", lambda conn, name, params_override=None: _Dummy())
    doc = client.post("/api/documents", json=_body()).json()
    pid = doc["paragraphs"][0]["id"]
    r = client.post(f"/api/paragraphs/{pid}/evaluate")
    assert r.status_code == 200, r.text
    assert {s["criterionId"] for s in r.json()["scores"]} == {"accuracy"}


# ── S3 §2.3 GET /api/health limits ─────────────────────────────────────────

def test_health_reports_limits(client):
    got = client.get("/api/health").json()
    assert got["limits"] == {"maxParagraphs": app_mod.MAX_PARAGRAPHS,
                              "maxParaChars": app_mod.MAX_PARA_CHARS}
