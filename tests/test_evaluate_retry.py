"""Reliability of the per-criterion live judge: transient errors retry with
backoff, deterministic errors do not, and a partial-failure re-evaluate can
re-run only the failed criteria without wiping the ones that succeeded.

The LLM is never called for real — `judge.judge_one` is monkeypatched and the
per-attempt backoff sleep is stubbed to keep the suite fast.
"""
from __future__ import annotations

import asyncio
import json

import httpx
import openai
import pytest

from palimpsest.webapp import app as app_mod
from palimpsest.webapp import budget, db
from tests.conftest import _body


@pytest.fixture(autouse=True)
def _no_network_budget(monkeypatch):
    # deterministic pricing, no OpenRouter /models fetch; instant backoff
    monkeypatch.setattr(budget, "_PRICES", {"m": (1e-6, 1e-6)})

    async def _instant_sleep(*_a, **_k):
        return None

    monkeypatch.setattr(app_mod, "EVAL_BACKOFF", 0.0)
    monkeypatch.setattr(app_mod.asyncio, "sleep", _instant_sleep)
    budget.reset()


@pytest.fixture()
def eval_client(client, monkeypatch):
    """A client whose one criterion 'accuracy' points at a fake model 'm', with
    `_client_for` returning a dummy (no real key needed)."""
    conn = db.connect()
    conn.execute("INSERT INTO model(name,base_url,api_key,params_json) "
                 "VALUES('m','https://openrouter.ai/api/v1','k','{}')")
    conn.execute("INSERT INTO criterion(id,name,model_name,weight,scale_min,scale_max,enabled) "
                 "VALUES('accuracy','Accuracy','m',1.0,1,10,1)")
    conn.commit()

    class _DummyClient:
        class config:  # noqa: N801 — mimic LLMClient.config.max_tokens access
            max_tokens = 512

    monkeypatch.setattr(app_mod, "_client_for", lambda conn, name: _DummyClient())
    return client


def _make_para(cl) -> int:
    doc = cl.post("/api/documents", json=_body()).json()
    return doc["paragraphs"][0]["id"]


def _judge_result(value=8.0):
    return {"value": value, "summary": "ok", "issues": [],
            "usage": type("U", (), {"cost_usd": 0.001, "prompt_tokens": 10,
                                    "completion_tokens": 5, "reasoning_tokens": 0})()}


def test_transient_timeout_retries_then_succeeds(eval_client, monkeypatch):
    calls = {"n": 0}

    def flaky(*a, **kw):
        calls["n"] += 1
        if calls["n"] < 3:
            raise TimeoutError("provider slow")
        return _judge_result()

    monkeypatch.setattr(app_mod, "judge_one", flaky)
    pid = _make_para(eval_client)
    ev = eval_client.post(f"/api/paragraphs/{pid}/evaluate").json()
    assert calls["n"] == 3                 # 1 initial + 2 retries (EVAL_RETRIES default)
    assert ev["failedCriterionIds"] == []
    assert any(s["criterionId"] == "accuracy" for s in ev["scores"])


def test_transient_exhausts_retries_then_fails(eval_client, monkeypatch):
    calls = {"n": 0}

    def always_429(*a, **kw):
        calls["n"] += 1
        resp = httpx.Response(429, request=httpx.Request("POST", "http://or"))
        raise openai.RateLimitError("429 rate limited", response=resp, body=None)

    monkeypatch.setattr(app_mod, "judge_one", always_429)
    pid = _make_para(eval_client)
    ev = eval_client.post(f"/api/paragraphs/{pid}/evaluate").json()
    assert calls["n"] == 3                 # initial + 2 retries, then give up
    assert ev["failedCriterionIds"] == ["accuracy"]


def test_deterministic_error_not_retried(eval_client, monkeypatch):
    calls = {"n": 0}

    def bad_json(*a, **kw):
        calls["n"] += 1
        raise json.JSONDecodeError("bad", "doc", 0)

    monkeypatch.setattr(app_mod, "judge_one", bad_json)
    pid = _make_para(eval_client)
    ev = eval_client.post(f"/api/paragraphs/{pid}/evaluate").json()
    assert calls["n"] == 1                 # parse errors don't retry — a retry fails identically
    assert ev["failedCriterionIds"] == ["accuracy"]


def test_failed_call_releases_budget_reservation(eval_client, monkeypatch):
    monkeypatch.setattr(app_mod, "judge_one",
                        lambda *a, **kw: (_ for _ in ()).throw(TimeoutError()))
    pid = _make_para(eval_client)
    eval_client.post(f"/api/paragraphs/{pid}/evaluate")
    snap = budget.snapshot()
    assert snap["spentUsd"] == pytest.approx(0.0)   # error settled to 0.0, not held


def test_error_log_records_error_detail(eval_client, monkeypatch, tmp_path):
    log = tmp_path / "b.jsonl"
    monkeypatch.setattr(budget, "_LOG_PATH", str(log))
    monkeypatch.setattr(app_mod, "judge_one",
                        lambda *a, **kw: (_ for _ in ()).throw(TimeoutError("slow")))
    pid = _make_para(eval_client)
    eval_client.post(f"/api/paragraphs/{pid}/evaluate")
    rows = [json.loads(line) for line in log.read_text().splitlines()]
    terminal = [r for r in rows if r.get("status") == "error"]
    assert terminal and "TimeoutError" in terminal[-1]["error"]
    retries = [r for r in rows if r.get("status") == "retry"]
    assert len(retries) == 2                          # both retry attempts logged with detail
    assert all("TimeoutError" in r["error"] for r in retries)


def test_partial_reeval_keeps_prior_success(eval_client, monkeypatch):
    """cultural succeeds first; a later single-criterion re-eval of 'accuracy'
    must not drop cultural's score."""
    conn = db.connect()
    conn.execute("INSERT INTO criterion(id,name,model_name,weight,scale_min,scale_max,enabled) "
                 "VALUES('cultural','Cultural','m',1.0,1,10,1)")
    conn.commit()
    monkeypatch.setattr(app_mod, "judge_one", lambda *a, **kw: _judge_result(7.0))
    pid = _make_para(eval_client)
    full = eval_client.post(f"/api/paragraphs/{pid}/evaluate").json()
    assert {s["criterionId"] for s in full["scores"]} == {"accuracy", "cultural"}

    # re-run only accuracy
    again = eval_client.post(f"/api/paragraphs/{pid}/evaluate",
                             json={"criterionIds": ["accuracy"]}).json()
    assert {s["criterionId"] for s in again["scores"]} == {"accuracy", "cultural"}
    assert again["failedCriterionIds"] == []
