import json

import pytest


@pytest.fixture
def seeded(tmp_path, monkeypatch):
    from palimpsest.webapp import db, seed as seedmod
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(db, "_conn", None)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    seedmod.seed()
    yield db
    if db._conn is not None:
        db._conn.close(); db._conn = None


def test_client_for_env_fallback_on_empty_key(seeded, monkeypatch):
    from palimpsest.webapp import app, db
    conn = db.connect()
    conn.execute("UPDATE model SET api_key='' WHERE name='qwen/qwen3.6-27b'"); conn.commit()
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-live")
    client = app._client_for(conn, "qwen/qwen3.6-27b")
    assert client is not None and client.config.api_key == "sk-or-live"


def test_client_for_no_fallback_for_vllm(seeded, monkeypatch):
    from palimpsest.webapp import app, db
    conn = db.connect()
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-live")
    # vLLM row has empty key + non-OR base_url → NO fallback → None (never leak OR key off-OR)
    assert app._client_for(conn, "TranslateGemma-27B") is None


def test_client_for_drops_temperature_for_gemini_flash_lite(seeded):
    from palimpsest.webapp import app, db
    conn = db.connect()
    conn.execute("UPDATE model SET params_json=? WHERE name='google/gemini-3.1-flash-lite'",
                 (json.dumps({"temperature": 0.9, "max_tokens": 128}),)); conn.commit()
    client = app._client_for(conn, "google/gemini-3.1-flash-lite")
    assert client.config.temperature is None and client.config.max_tokens == 128


def setup_function():
    from palimpsest.webapp import budget
    budget.reset(); budget._CAP_USD = 2.0; budget._CALL_CAP = 200; budget._PRICES = {}


def _install_fake_client(monkeypatch, content, cost=0.0003):
    from types import SimpleNamespace
    from palimpsest.llm.client import LLMResult, Usage
    from palimpsest.webapp import app

    class FakeClient:
        config = SimpleNamespace(max_tokens=1024, extra_body=None)
        def complete(self, system, user):
            return LLMResult(content=content, usage=Usage(50, 20, 0, cost))
    monkeypatch.setattr(app, "_client_for", lambda conn, name: FakeClient())


def test_test_endpoint_unknown_model_404(seeded):
    import asyncio, pytest as _pt
    from fastapi import HTTPException
    from palimpsest.webapp.app import test_model, TestBody
    with _pt.raises(HTTPException) as ei:
        asyncio.run(test_model("no/such", TestBody()))
    assert ei.value.status_code == 404


def test_test_endpoint_happy_share_and_cost(seeded, monkeypatch):
    import asyncio
    import json as _json
    from palimpsest.webapp import app, db
    from palimpsest.webapp.app import test_model, TestBody
    conn = db.connect()
    ref, _ = app._test_reference(conn)
    _install_fake_client(monkeypatch, _json.dumps(sorted(ref)))
    out = asyncio.run(test_model("qwen/qwen3.6-27b", TestBody()))
    assert out["ok"] is True
    assert out["share"] == 1.0
    assert out["matched"] == out["total"]
    assert out["total"] > 0
    assert out["costUsd"] == 0.0003


def test_test_endpoint_parse_error_is_ok_false_200(seeded, monkeypatch):
    import asyncio
    from palimpsest.webapp.app import test_model, TestBody
    _install_fake_client(monkeypatch, "not json at all")
    out = asyncio.run(test_model("qwen/qwen3.6-27b", TestBody()))
    assert out["ok"] is False and "message" in out


def test_test_endpoint_budget_block_is_ok_false(seeded, monkeypatch):
    import asyncio
    from palimpsest.webapp import budget
    from palimpsest.webapp.app import test_model, TestBody
    budget._CAP_USD = 0.0
    _install_fake_client(monkeypatch, '["сутии"]')
    out = asyncio.run(test_model("qwen/qwen3.6-27b", TestBody()))
    assert out["ok"] is False and out["message"] == "budget"


def test_evaluate_uses_freshly_edited_model_params(seeded, monkeypatch):
    """S4: edit a criterion's model params, then /evaluate — the client built for
    the live call must reflect the edit, not a stale/cached config.

    Exercises the REAL app._client_for (DB read → ModelParams.for_model →
    LLMConfig), faking only the network-touching LLMClient.complete, so the
    edit->evaluate freshness path is genuinely proven, not just the fake.

    Params are edited straight in the DB (not via update_model/PUT) to isolate
    this test from the HTTP layer — see test_update_model_allows_max_tokens_param
    below for the PUT-path coverage of the guard itself.
    """
    import asyncio
    import json as _json

    from palimpsest.llm.client import LLMClient, LLMResult, Usage
    from palimpsest.webapp import budget, db
    from palimpsest.webapp.app import EvaluateBody, evaluate

    conn = db.connect()
    criterion = conn.execute("SELECT * FROM criterion WHERE enabled=1 LIMIT 1").fetchone()
    cid, model_name = criterion["id"], criterion["model_name"]
    para = conn.execute("SELECT * FROM paragraph WHERE document_id=(SELECT document_id FROM criterion "
                         "LIMIT 1) LIMIT 1").fetchone()
    pid = para["id"] if para else conn.execute("SELECT id FROM paragraph LIMIT 1").fetchone()["id"]

    conn.execute("UPDATE model SET api_key='sk-test', params_json=? WHERE name=?",
                 (_json.dumps({"max_tokens": 4242}), model_name))
    conn.commit()

    recorded: list[int] = []

    def _fake_complete(self, system, user):
        recorded.append(self.config.max_tokens)
        return LLMResult(content=_json.dumps(
            {"final_score": 4.0, "summary": "ok", "identified_issues": []}),
            usage=Usage(10, 10, 0, 0.0001))

    monkeypatch.setattr(LLMClient, "complete", _fake_complete)

    budget.reset(); budget._CAP_USD = 2.0; budget._CALL_CAP = 200; budget._PRICES = {}

    asyncio.run(evaluate(pid, EvaluateBody(criterionIds=[cid])))

    assert recorded == [4242], "evaluate must use the client built from the just-edited params"


def test_update_model_allows_max_tokens_param(seeded):
    """The secret-key guard must not false-positive on the substring "token"
    inside "max_tokens" (regression for the _guard_params bug — see
    palimpsest.webapp.secrets_guard.is_secret_key)."""
    from palimpsest.webapp import app

    result = app.update_model(
        "qwen/qwen3.6-27b",
        {"baseUrl": "https://openrouter.ai/api/v1", "apiKey": "",
         "params": {"max_tokens": 512, "temperature": 0.3}},
    )
    assert result["params"] == {"max_tokens": 512, "temperature": 0.3}


def test_update_model_still_blocks_real_secret_keys(seeded):
    from fastapi import HTTPException
    from palimpsest.webapp import app

    with pytest.raises(HTTPException) as ei:
        app.update_model(
            "qwen/qwen3.6-27b",
            {"baseUrl": "https://openrouter.ai/api/v1", "apiKey": "",
             "params": {"api_key": "x"}},
        )
    assert ei.value.status_code == 400


def test_stems_are_morphology_tolerant():
    """The Test share metric matches Russian case variants: the reference is
    genitive (as it appears in the source), models answer in nominative."""
    from palimpsest.webapp.app import _stems

    assert _stems("династии") == _stems("династия")   # genitive stem == nominative stem
    assert _stems("сутиев") == _stems("сутии")
    verkh = _stems("Верхней Месопотамии")
    assert verkh == _stems("Верхняя Месопотамия") and "месо" in verkh


def test_test_metric_credits_nominative_output(seeded, monkeypatch):
    """A model returning nominative forms still scores against genitive/oblique refs."""
    import asyncio

    from palimpsest.webapp.app import TestBody, test_model
    # Reference terms for paragraph idx=1 come from the real demo seed (Phase C
    # terminology); some appear in the source in genitive/prepositional case
    # ("Плодородного Полумесяца", "Среднем Тигре"). The fake model answers with
    # nominative forms of the same terms — stemming should still credit them.
    _install_fake_client(
        monkeypatch,
        '["Нижняя Месопотамия", "Плодородный полумесяц", "Верхняя Месопотамия", '
        '"Ассирия", "Ашшур", "Средний Тигр"]')
    out = asyncio.run(test_model("qwen/qwen3.6-27b", TestBody()))
    assert out["matched"] >= 5        # 6 nominative forms matched oblique-case references
