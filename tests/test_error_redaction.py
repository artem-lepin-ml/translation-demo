"""C-critical fix: exception text logged to budget_calls.jsonl must never carry
a live API key. openai.AuthenticationError echoes the bad key verbatim
("Incorrect API key provided: sk-..."), and that message used to be written
unredacted via `error=f"{type(exc).__name__}: {exc}"` at both the retry-status
and terminal-error log sites in `_judge_live`.
"""
from __future__ import annotations

import httpx
import openai
import pytest

from palimpsest.webapp import app as app_mod
from palimpsest.webapp import budget, db
from palimpsest.webapp.secrets_guard import redact_error
from tests.conftest import _body

# ── unit: the redaction helper itself ──────────────────────────────────────

def test_redact_error_masks_openai_style_key():
    text = redact_error("Incorrect API key provided: sk-real-secret-XYZ123456789.")
    assert "sk-real-secret-XYZ123456789" not in text


def test_redact_error_masks_bearer_token():
    text = redact_error("Authorization failed for Bearer abcdEFGH12345678ijklMNOP")
    assert "abcdEFGH12345678ijklMNOP" not in text


def test_redact_error_truncates_long_message():
    text = redact_error("x" * 5000)
    assert len(text) <= 320  # ~300 char cap + a little slack for a truncation marker


def test_redact_error_keeps_non_secret_text_readable():
    text = redact_error("request timed out after 20s")
    assert "timed out" in text


# ── integration: the secret never reaches the log file ────────────────────

@pytest.fixture(autouse=True)
def _no_network_budget(monkeypatch):
    monkeypatch.setattr(budget, "_PRICES", {"m": (1e-6, 1e-6)})

    async def _instant_sleep(*_a, **_k):
        return None

    monkeypatch.setattr(app_mod, "EVAL_BACKOFF", 0.0)
    monkeypatch.setattr(app_mod.asyncio, "sleep", _instant_sleep)
    budget.reset()


@pytest.fixture()
def eval_client(client, monkeypatch):
    conn = db.connect()
    conn.execute("INSERT INTO model(name,base_url,api_key,params_json) "
                 "VALUES('m','https://openrouter.ai/api/v1','sk-real-secret-XYZ123456789','{}')")
    conn.execute("INSERT INTO criterion(id,name,model_name,weight,scale_min,scale_max,enabled) "
                 "VALUES('accuracy','Accuracy','m',1.0,1,10,1)")
    conn.commit()

    class _DummyClient:
        class config:
            max_tokens = 512

    monkeypatch.setattr(app_mod, "_client_for", lambda conn, name: _DummyClient())
    return client


def _make_para(cl) -> int:
    doc = cl.post("/api/documents", json=_body()).json()
    return doc["paragraphs"][0]["id"]


SECRET = "sk-real-secret-XYZ123456789"


def test_auth_error_key_not_leaked_terminal_log(eval_client, monkeypatch, tmp_path):
    log = tmp_path / "budget_calls.jsonl"
    monkeypatch.setattr(budget, "_LOG_PATH", str(log))

    def bad_key(*a, **kw):
        resp = httpx.Response(401, request=httpx.Request("POST", "http://or"))
        raise openai.AuthenticationError(f"Incorrect API key provided: {SECRET}",
                                         response=resp, body=None)

    monkeypatch.setattr(app_mod, "judge_one", bad_key)
    pid = _make_para(eval_client)
    ev = eval_client.post(f"/api/paragraphs/{pid}/evaluate",
                          json={"criterionIds": ["accuracy"]}).json()
    assert ev["failedCriterionIds"] == ["accuracy"]

    log_text = log.read_text()
    assert SECRET not in log_text
    assert "AuthenticationError" in log_text


def test_transient_error_key_not_leaked_retry_log(eval_client, monkeypatch, tmp_path):
    log = tmp_path / "budget_calls.jsonl"
    monkeypatch.setattr(budget, "_LOG_PATH", str(log))

    calls = {"n": 0}

    def flaky_with_secret(*a, **kw):
        calls["n"] += 1
        raise TimeoutError(f"provider slow, last used key {SECRET}")

    monkeypatch.setattr(app_mod, "judge_one", flaky_with_secret)
    pid = _make_para(eval_client)
    eval_client.post(f"/api/paragraphs/{pid}/evaluate", json={"criterionIds": ["accuracy"]})

    log_text = log.read_text()
    assert SECRET not in log_text
    assert "TimeoutError" in log_text
