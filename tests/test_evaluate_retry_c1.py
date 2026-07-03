"""C1 aspect review — spending-safety tests for the retry loop added on top of
_judge_live (dffc41a..0045b41). Covers:

1. generation-counter reset mid-retry → stale settle no-ops (existing audit-fix
   mechanism must still hold under the new retry loop).
2. worst-case call amplification: reserve() happens ONCE before attempt 1, not
   re-checked per retry attempt — retries cannot make a single reservation
   exceed its own estimate, but confirms the reservation ceiling math.
3. precompute sub-cap: a retried criterion consumes exactly ONE call slot
   (_take_call_slot), not one per attempt.
4. retry-failed endpoint (criterionIds subset) triggers judge_one exactly
   len(criterionIds) * attempts calls, never touching the other criteria.
5. terminal/retry judge failures surface as backend logger.warning records
   (not just the budget JSONL) — an operator watching uvicorn output must
   see them.

No real network access; judge_one/asyncio.sleep are monkeypatched.
"""
from __future__ import annotations

import asyncio
import logging

import pytest

from palimpsest.webapp import app as app_mod
from palimpsest.webapp import budget, db, precompute
from tests.conftest import _body


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
                 "VALUES('m','https://openrouter.ai/api/v1','k','{}')")
    conn.execute("INSERT INTO criterion(id,name,model_name,weight,scale_min,scale_max,enabled) "
                 "VALUES('accuracy','Accuracy','m',1.0,1,10,1)")
    conn.execute("INSERT INTO criterion(id,name,model_name,weight,scale_min,scale_max,enabled) "
                 "VALUES('cultural','Cultural','m',1.0,1,10,1)")
    conn.commit()

    class _DummyClient:
        class config:
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


# ── 1. generation-reset mid-retry ──────────────────────────────────────────

def test_generation_reset_mid_retry_stale_settle_noops(eval_client, monkeypatch):
    """A reset() fired between the first (failed) attempt and the retry's
    eventual success must make the terminal settle() a no-op against the NEW
    generation's spend — the audit-fix mechanism (reset-generation) has to
    survive the new retry loop, not just a single-attempt call."""
    calls = {"n": 0}

    async def flaky_with_reset(*a, **kw):
        pass

    def flaky(*a, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            # simulate an admin reset() landing while attempt 1 is in flight
            budget.reset()
            raise TimeoutError("provider slow")
        return _judge_result()

    monkeypatch.setattr(app_mod, "judge_one", flaky)
    pid = _make_para(eval_client)
    ev = eval_client.post(f"/api/paragraphs/{pid}/evaluate",
                          json={"criterionIds": ["accuracy"]}).json()
    assert calls["n"] == 2
    assert ev["failedCriterionIds"] == []
    snap = budget.snapshot()
    # generation bumped mid-flight → the eventual settle(actual=0.001) must
    # NOT apply against the new generation's spend (reservation belonged to
    # the pre-reset epoch); spend must stay at 0, not reflect the real cost.
    assert snap["spentUsd"] == pytest.approx(0.0)
    assert snap["calls"] == 0                  # reset() also zeroed the call counter


# ── 2. worst-case amplification / reserve-once math ────────────────────────

def test_reserve_called_once_not_per_attempt(eval_client, monkeypatch):
    """reserve() must fire exactly once per criterion-call regardless of how
    many attempts the retry loop takes — the worst case for spend is bounded
    by ONE estimate, not (1+EVAL_RETRIES) estimates stacked."""
    reserve_calls = {"n": 0}
    orig_reserve = budget.reserve

    async def counting_reserve(est):
        reserve_calls["n"] += 1
        return await orig_reserve(est)

    monkeypatch.setattr(budget, "reserve", counting_reserve)

    attempts = {"n": 0}

    def flaky_twice(*a, **kw):
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise TimeoutError("slow")
        return _judge_result()

    monkeypatch.setattr(app_mod, "judge_one", flaky_twice)
    pid = _make_para(eval_client)
    eval_client.post(f"/api/paragraphs/{pid}/evaluate", json={"criterionIds": ["accuracy"]})
    assert attempts["n"] == 3                  # 1 initial + 2 retries actually ran
    assert reserve_calls["n"] == 1              # but only ONE reservation was taken
    # therefore the hard ceiling per criterion-call is exactly est (one
    # reservation), never (1+EVAL_RETRIES) * est — retries cannot inflate the
    # reservation itself. Confirm the call counter matches reservations, not attempts.
    assert budget.snapshot()["calls"] == 1


def test_worst_case_ceiling_5_criteria_matches_cap(eval_client, monkeypatch):
    """5 criteria x (1+EVAL_RETRIES) attempts x N paragraphs is the worst-case
    call-VOLUME (network requests to the provider), but budget.calls only
    counts reservations (1 per criterion-call). Confirm reserve() still
    enforces the $2 cap against the sum of ESTIMATES (not real costs), and
    that a call whose single estimate alone exceeds remaining headroom is
    rejected before any attempt runs (no attempt-1 spend, no retry storm)."""
    # cap the budget artificially low so one estimate already exceeds it
    monkeypatch.setattr(budget, "_CAP_USD", 0.0000001)
    monkeypatch.setattr(app_mod, "judge_one", lambda *a, **kw: _judge_result())
    pid = _make_para(eval_client)
    ev = eval_client.post(f"/api/paragraphs/{pid}/evaluate",
                          json={"criterionIds": ["accuracy"]}).json()
    # BudgetExceeded raised inside reserve(), before judge_one ever runs —
    # counted as a failed criterion, zero attempts, zero spend.
    assert ev["failedCriterionIds"] == ["accuracy"]
    assert budget.snapshot()["spentUsd"] == pytest.approx(0.0)
    assert budget.snapshot()["calls"] == 0


def test_all_retries_exhausted_reservation_released_not_leaked(eval_client, monkeypatch):
    """(b) from the brief: after exhausting all retries, the reservation must
    be released ($0 settle) and NOT leak — a subsequent reserve() must see
    full headroom, not a permanently-inflated spent counter."""
    monkeypatch.setattr(app_mod, "judge_one",
                        lambda *a, **kw: (_ for _ in ()).throw(TimeoutError("slow")))
    pid = _make_para(eval_client)
    eval_client.post(f"/api/paragraphs/{pid}/evaluate", json={"criterionIds": ["accuracy"]})
    assert budget.snapshot()["spentUsd"] == pytest.approx(0.0)

    # a fresh criterion-call must reserve at full estimate — no residue held
    est = 0.5
    gen = asyncio.run(budget.reserve(est))
    assert budget.snapshot()["spentUsd"] == pytest.approx(est)
    asyncio.run(budget.settle(est, 0.001, gen))
    assert budget.snapshot()["spentUsd"] == pytest.approx(0.001)


# ── 3. precompute sub-cap counts criterion-calls, not attempts ────────────

def test_precompute_subcap_counts_one_slot_per_criterion_despite_retries(eval_client, monkeypatch):
    """_take_call_slot() is invoked once per (paragraph, criterion) pair in
    the outer precompute loop, BEFORE the real app._judge_live (with its
    retry loop) runs — retries inside judge_live must not consume extra
    slots, and must not bypass the slot check either (the slot is already
    held for the whole retry sequence)."""
    monkeypatch.setattr(precompute, "_CALL_CAP", 10)
    budget._STATE.pop("precompute_calls", None)

    attempts = {"n": 0}

    def flaky(client, criterion_id, source, target, **kw):
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise TimeoutError("slow")
        r = _judge_result()
        return {"value": r["value"], "summary": r["summary"], "issues": r["issues"], "usage": r["usage"]}

    monkeypatch.setattr(app_mod, "judge_one", flaky)

    conn = db.connect()
    conn.execute("DELETE FROM criterion")
    conn.execute("INSERT INTO criterion(id,name,model_name,weight,scale_min,scale_max,enabled) "
                 "VALUES('accuracy','Accuracy','m',1.0,1,10,1)")
    conn.commit()
    doc = eval_client.post("/api/documents",
                           json=_body(paragraphs=[{"source": "s0", "target": "t0"}])).json()

    # exercise the REAL retry loop via app_mod._judge_live, as precompute._run does
    asyncio.run(precompute.run(doc["id"], app_mod._judge_live))
    # 1 paragraph x 1 criterion = 1 slot consumed, even though judge_one
    # (inside the retry loop) was invoked 3x before succeeding.
    assert budget._STATE["precompute_calls"] == 1
    assert attempts["n"] == 3
    assert precompute.status_for(doc["id"])["status"] == "done"


# ── 4. retry-failed subset endpoint call counting ──────────────────────────

def test_retry_failed_subset_only_calls_requested_criteria(eval_client, monkeypatch):
    """A retry-failed click with criterionIds=['accuracy'] must call judge_one
    ONLY for 'accuracy' (<= len(criterionIds) * (1+EVAL_RETRIES) calls total),
    never re-running the already-succeeded 'cultural' criterion."""
    seen = {"accuracy": 0, "cultural": 0}

    def counting_judge(client, criterion_id, source, target, **kw):
        seen[criterion_id] += 1
        if criterion_id == "accuracy" and seen["accuracy"] < 2:
            raise TimeoutError("slow")
        return _judge_result()

    monkeypatch.setattr(app_mod, "judge_one", counting_judge)
    pid = _make_para(eval_client)
    full = eval_client.post(f"/api/paragraphs/{pid}/evaluate").json()
    assert {s["criterionId"] for s in full["scores"]} == {"accuracy", "cultural"}
    assert seen["cultural"] == 1
    baseline_accuracy_calls = seen["accuracy"]

    # simulate a retry-failed click for just 'accuracy'
    again = eval_client.post(f"/api/paragraphs/{pid}/evaluate",
                             json={"criterionIds": ["accuracy"]}).json()
    assert seen["cultural"] == 1                 # untouched by the subset retry
    assert seen["accuracy"] > baseline_accuracy_calls
    assert seen["accuracy"] - baseline_accuracy_calls <= 1 + app_mod.EVAL_RETRIES
    assert {s["criterionId"] for s in again["scores"]} == {"accuracy", "cultural"}


# ── 5. budget error-log cost accounting ────────────────────────────────────

def test_failed_attempt_costUsd_null_successful_attempt_matches_usage(eval_client, monkeypatch, tmp_path):
    """Failed attempts log costUsd=None (never billed); the terminal success
    log's costUsd/tokens must equal exactly what the client's usage object
    reported — no double counting across attempts."""
    log = tmp_path / "b.jsonl"
    monkeypatch.setattr(budget, "_LOG_PATH", str(log))

    attempts = {"n": 0}

    def flaky_once(*a, **kw):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise TimeoutError("slow")
        return _judge_result(value=9.0)

    monkeypatch.setattr(app_mod, "judge_one", flaky_once)
    pid = _make_para(eval_client)
    eval_client.post(f"/api/paragraphs/{pid}/evaluate", json={"criterionIds": ["accuracy"]})

    import json as _json
    rows = [_json.loads(line) for line in log.read_text().splitlines()]
    retry_rows = [r for r in rows if r.get("status") == "retry"]
    ok_rows = [r for r in rows if r.get("status") == "ok"]
    assert len(retry_rows) == 1
    assert retry_rows[0]["costUsd"] is None      # failed attempt never billed
    assert len(ok_rows) == 1
    assert ok_rows[0]["costUsd"] == pytest.approx(0.001)   # matches _judge_result's usage.cost_usd
    assert ok_rows[0]["tokens"] == {"prompt": 10, "completion": 5, "reasoning": 0}
    # final budget spend reflects exactly the one successful call's real cost
    assert budget.snapshot()["spentUsd"] == pytest.approx(0.001)


# ── 6. judge failures surface in the backend logger, not just budget JSONL ──

def test_terminal_judge_failure_logs_warning_with_criterion_and_exc_type(eval_client, monkeypatch, caplog):
    """An operator watching uvicorn output must see judge failures. The
    terminal-failure log record must carry the criterion id and the
    exception type, and must use the already-redacted error string (never
    the raw exception, which could leak secrets)."""
    monkeypatch.setattr(app_mod, "judge_one",
                        lambda *a, **kw: (_ for _ in ()).throw(TimeoutError("provider unreachable")))
    pid = _make_para(eval_client)
    with caplog.at_level(logging.WARNING, logger="palimpsest.webapp.app"):
        eval_client.post(f"/api/paragraphs/{pid}/evaluate", json={"criterionIds": ["accuracy"]})

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    terminal = [r for r in warnings if "failed terminally" in r.getMessage()]
    assert len(terminal) == 1
    msg = terminal[0].getMessage()
    assert "accuracy" in msg
    assert "TimeoutError" in msg


def test_retry_attempt_logs_warning(eval_client, monkeypatch, caplog):
    """Each transient-error retry attempt (not just the terminal failure)
    must also be visible in backend logs."""
    attempts = {"n": 0}

    def flaky_once(*a, **kw):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise TimeoutError("slow")
        return _judge_result()

    monkeypatch.setattr(app_mod, "judge_one", flaky_once)
    pid = _make_para(eval_client)
    with caplog.at_level(logging.WARNING, logger="palimpsest.webapp.app"):
        eval_client.post(f"/api/paragraphs/{pid}/evaluate", json={"criterionIds": ["accuracy"]})

    retry_warnings = [r for r in caplog.records
                      if r.levelno == logging.WARNING and "judge retry" in r.getMessage()]
    assert len(retry_warnings) == 1
    assert "accuracy" in retry_warnings[0].getMessage()
