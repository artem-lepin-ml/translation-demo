"""HTTP-level routing tests via FastAPI TestClient.

The unit tests call endpoint functions directly, so they never exercise the
router. Model names contain a slash (e.g. ``qwen/qwen3.6-27b``); ASGI decodes
``%2F`` to ``/`` before routing, so a single-segment ``{name}`` route 404s on
every model. These tests pin the ``{name:path}`` fix by driving the real router.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    from palimpsest.webapp import app as appmod, budget, db
    from palimpsest.webapp import seed as seedmod
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(db, "_conn", None)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    seedmod.seed()
    budget.reset()
    budget._CAP_USD = 2.0
    budget._CALL_CAP = 200
    budget._PRICES = {}
    with TestClient(appmod.app) as c:
        yield c, appmod
    if db._conn is not None:
        db._conn.close()
        db._conn = None


def test_put_model_slashed_name_routes(client):
    c, _ = client
    r = c.put("/api/models/qwen/qwen3.6-27b",
              json={"baseUrl": "https://openrouter.ai/api/v1", "apiKey": "",
                    "params": {"max_tokens": 512, "temperature": 0.5}})
    assert r.status_code == 200, r.text          # routes, not 404 Not Found
    assert r.json()["params"]["max_tokens"] == 512


def test_test_endpoint_slashed_name_routes(client, monkeypatch):
    c, appmod = client
    from palimpsest.llm.client import LLMResult, Usage

    class Fake:
        config = SimpleNamespace(max_tokens=1024, extra_body=None)

        def complete(self, system, user):
            return LLMResult('["сутии", "амореи"]', Usage(10, 5, 0, 0.0001))

    monkeypatch.setattr(appmod, "_client_for", lambda conn, name: Fake())
    r = c.post("/api/models/qwen/qwen3.6-27b/test", json={})
    assert r.status_code == 200, r.text
    body = r.json()
    assert "share" in body and body["costUsd"] == 0.0001


def test_delete_unused_model_slashed_name_routes(client):
    c, _ = client
    # google/gemma-3-27b-it is seeded but not referenced by any criterion/
    # config (only qwen/qwen3.6-27b, DEFAULT_CRITERION_MODEL, is) → 204
    # (proves the slashed-name route matched a real, existing row)
    r = c.delete("/api/models/google/gemma-3-27b-it")
    assert r.status_code == 204, r.text


def test_delete_referenced_model_returns_409_not_404(client):
    c, _ = client
    # qwen/qwen3.6-27b is the seeded criteria model (DEFAULT_CRITERION_MODEL) →
    # 409, NOT a routing 404 (proves the slashed-name route matched)
    r = c.delete("/api/models/qwen/qwen3.6-27b")
    assert r.status_code == 409, r.text


def _criterion_payload(**over):
    payload = {"id": "new-crit", "name": "New", "modelName": "qwen/qwen3.6-27b",
               "prompt": "", "scaleMin": 1, "scaleMax": 10, "weight": 0.5,
               "color": "#888", "enabled": True}
    payload.update(over)
    return payload


def test_put_criterion_weight_out_of_range_is_422(client):
    c, _ = client
    r = c.put("/api/criteria/accuracy", json=_criterion_payload(id="accuracy", weight=-5))
    assert r.status_code == 422, r.text


def test_put_criterion_weight_above_one_is_422(client):
    c, _ = client
    r = c.put("/api/criteria/accuracy", json=_criterion_payload(id="accuracy", weight=1.5))
    assert r.status_code == 422, r.text


def test_put_criterion_valid_weight_accepted(client):
    c, _ = client
    r = c.put("/api/criteria/accuracy", json=_criterion_payload(id="accuracy", weight=0.42))
    assert r.status_code == 200, r.text
    assert r.json()["weight"] == 0.42


def test_post_criterion_weight_out_of_range_is_422(client):
    c, _ = client
    r = c.post("/api/criteria", json=_criterion_payload(weight=-0.1))
    assert r.status_code == 422, r.text


def test_post_criterion_empty_name_is_422(client):
    c, _ = client
    r = c.post("/api/criteria", json=_criterion_payload(name="   ", prompt="Evaluate this."))
    assert r.status_code == 422, r.text


def test_post_criterion_empty_prompt_is_422(client):
    c, _ = client
    r = c.post("/api/criteria", json=_criterion_payload(name="New", prompt="   "))
    assert r.status_code == 422, r.text


def test_post_criterion_valid_name_and_prompt_accepted(client):
    c, _ = client
    r = c.post("/api/criteria", json=_criterion_payload(name="New", prompt="Evaluate this."))
    assert r.status_code == 200, r.text


def test_post_criterion_succeeds_with_no_authorization_header(client):
    """wave-4 Б5: admin-token gating is fully removed — mutating routes work
    for everyone, with no Authorization header at all."""
    c, _ = client
    assert "authorization" not in {h.lower() for h in c.headers}
    r = c.post("/api/criteria", json=_criterion_payload(id="no-auth-crit", name="NoAuth",
                                                          prompt="Evaluate this."))
    assert r.status_code == 200, r.text


def test_delete_criterion_with_history_returns_409_not_404(client):
    """wave-4 Б4: hard-delete of a criterion with score/issue history is
    blocked (disable instead) — the seeded 'accuracy' criterion has both
    seed scores and seed issues, so this exercises the guard on a criterion
    that still exists post-Б4 (cultural was dropped from CRITERIA)."""
    c, _ = client
    r = c.delete("/api/criteria/accuracy")
    assert r.status_code == 409, r.text


def _model_payload(**over):
    payload = {"baseUrl": "https://openrouter.ai/api/v1", "apiKey": "",
               "params": {"max_tokens": 512}}
    payload.update(over)
    return payload


def test_post_model_params_array_is_422(client):
    c, _ = client
    r = c.post("/api/models", json={"name": "new/model", **_model_payload(params=[1, 2, 3])})
    assert r.status_code == 422, r.text


def test_post_model_params_number_is_422(client):
    c, _ = client
    r = c.post("/api/models", json={"name": "new/model", **_model_payload(params=5)})
    assert r.status_code == 422, r.text


def test_post_model_params_null_is_422(client):
    c, _ = client
    r = c.post("/api/models", json={"name": "new/model", **_model_payload(params=None)})
    assert r.status_code == 422, r.text


def test_post_model_params_string_is_422(client):
    c, _ = client
    r = c.post("/api/models", json={"name": "new/model", **_model_payload(params="hello")})
    assert r.status_code == 422, r.text


def test_post_model_params_valid_dict_accepted(client):
    c, _ = client
    r = c.post("/api/models", json={"name": "new/model", **_model_payload()})
    assert r.status_code == 200, r.text
    assert r.json()["params"] == {"max_tokens": 512}


def test_put_model_params_array_is_422(client):
    c, _ = client
    r = c.put("/api/models/qwen/qwen3.6-27b", json=_model_payload(params=[1, 2, 3]))
    assert r.status_code == 422, r.text


def test_put_model_params_string_is_422(client):
    c, _ = client
    r = c.put("/api/models/qwen/qwen3.6-27b", json=_model_payload(params="hello"))
    assert r.status_code == 422, r.text


def test_put_model_params_valid_dict_accepted(client):
    c, _ = client
    r = c.put("/api/models/qwen/qwen3.6-27b", json=_model_payload(params={"temperature": 0.5}))
    assert r.status_code == 200, r.text
    assert r.json()["params"] == {"temperature": 0.5}


# ─────────────────────────── grounding_config ───────────────────────────

def test_get_grounding_config_returns_seeded_default(client):
    c, _ = client
    r = c.get("/api/grounding-config")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["modelName"]
    assert body["prompt"]
    assert body["params"] == {"max_tokens": 512, "temperature": 0}


def test_put_grounding_config_updates_and_get_reflects(client):
    c, _ = client
    r = c.put("/api/grounding-config",
              json={"modelName": "qwen/qwen3.6-27b", "prompt": "Custom judge prompt",
                    "params": {"max_tokens": 256, "temperature": 0}})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["modelName"] == "qwen/qwen3.6-27b"
    assert body["prompt"] == "Custom judge prompt"
    assert body["params"] == {"max_tokens": 256, "temperature": 0}

    r2 = c.get("/api/grounding-config")
    assert r2.status_code == 200, r2.text
    assert r2.json() == body


def test_put_grounding_config_params_array_is_422(client):
    c, _ = client
    r = c.put("/api/grounding-config",
              json={"modelName": "qwen/qwen3.6-27b", "prompt": "x", "params": [1, 2, 3]})
    assert r.status_code == 422, r.text


def test_put_grounding_config_params_string_is_422(client):
    c, _ = client
    r = c.put("/api/grounding-config",
              json={"modelName": "qwen/qwen3.6-27b", "prompt": "x", "params": "hello"})
    assert r.status_code == 422, r.text


def test_put_grounding_config_params_secret_key_is_400(client):
    c, _ = client
    r = c.put("/api/grounding-config",
              json={"modelName": "qwen/qwen3.6-27b", "prompt": "x", "params": {"api_key": "x"}})
    assert r.status_code == 400, r.text
