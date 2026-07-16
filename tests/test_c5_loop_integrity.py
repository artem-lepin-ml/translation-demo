"""C5 aspect review — improvement-loop integrity across the retry/free-text-lang
merge (dffc41a..0045b41). Covers gaps not already exercised by
test_evaluate_retry.py / test_evaluate_retry_c1.py / test_issue_dedup.py:

1. reset() 409s against an in-flight (possibly retrying) /evaluate, and the
   retry backoff sleep does not block DELETE's cancellation of precompute.
2. A full free-text-language (German -> French) cycle: evaluate, accept a
   suggestion, re-score — the judge receives the language preamble on EVERY
   call (initial evaluate, re-judge after accept), asserted on captured prompts.
3. No-key / bad-key classification is fail-fast, not retried — quantifies the
   latency a caller would see falling back to cache.

No real network access; judge_one/asyncio.sleep are monkeypatched.
"""
from __future__ import annotations

import asyncio
import time

import httpx
import openai
import pytest

from palimpsest.webapp import app as app_mod
from palimpsest.webapp import budget, db, precompute
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
    conn.execute("INSERT INTO criterion(id,name,model_name,weight,scale_min,scale_max,enabled) "
                 "VALUES('accuracy','Accuracy','m',1.0,1,10,1)")
    conn.commit()

    class _DummyClient:
        class config:
            max_tokens = 512

    monkeypatch.setattr(app_mod, "_client_for", lambda conn, name: _DummyClient())
    return client


def _make_para(cl, **over) -> int:
    doc = cl.post("/api/documents", json=_body(**over)).json()
    return doc["paragraphs"][0]["id"]


def _judge_result(value=8.0, issues=None):
    return {"value": value, "summary": "ok", "issues": issues or [],
            "usage": type("U", (), {"cost_usd": 0.001, "prompt_tokens": 10,
                                    "completion_tokens": 5, "reasoning_tokens": 0})()}


def _wire_issue(target_fragment, source_fragment, explanation, suggestion):
    """Issue dict in the app's expected wire shape (judge._issue_from output)."""
    return {"targetFragment": target_fragment, "sourceFragment": source_fragment,
            "explanation": explanation, "suggestion": suggestion,
            "severity": "minor", "mqmCategory": None}


# ── 1. reset 409 + delete cancellation not blocked by retry sleep ──────────

def test_reset_409s_against_in_flight_evaluate(eval_client, monkeypatch):
    """While /evaluate is mid-flight (retrying with a slow backoff sleep),
    POST /reset must 409, not silently wipe scores out from under the running
    judge call.

    Drives evaluate()/reset_document() directly as coroutines on ONE event
    loop (TestClient.post blocks its own worker thread/loop end-to-end, so
    polling app_mod._evaluating from an outer loop around a threaded
    TestClient call is inherently racy — see test_issue_dedup.py's pattern).

    IMPORTANT: app_mod.asyncio IS the global asyncio module (same object this
    test file imports), so patching app_mod.asyncio.sleep patches asyncio.sleep
    everywhere in this process, including any `await asyncio.sleep(...)` this
    test itself issues. Synchronization below uses an asyncio.Event instead of
    polling via asyncio.sleep, to avoid the patched sleep racing with itself."""
    from palimpsest.webapp.app import EvaluateBody, evaluate, reset_document

    orig_sleep = asyncio.sleep
    backoff_entered = asyncio.Event()

    async def real_sleep_once(dur):
        if not sleeps_done["done"]:
            sleeps_done["done"] = True
            backoff_entered.set()          # signal via Event, not via sleep, to dodge the patch
            await orig_sleep(0.05)

    sleeps_done = {"done": False}
    monkeypatch.setattr(app_mod, "EVAL_BACKOFF", 0.01)
    monkeypatch.setattr(app_mod.asyncio, "sleep", real_sleep_once)

    calls = {"n": 0}

    def flaky(*a, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise TimeoutError("slow")
        return _judge_result()

    monkeypatch.setattr(app_mod, "judge_one", flaky)
    pid = _make_para(eval_client)
    doc_id = db.connect().execute(
        "SELECT document_id FROM paragraph WHERE id=?", (pid,)).fetchone()["document_id"]

    results = {}

    eval_key = (db.current_sid(), doc_id)

    async def scenario():
        ev_task = asyncio.create_task(evaluate(pid, EvaluateBody()))
        await asyncio.wait_for(backoff_entered.wait(), timeout=2.0)
        assert eval_key in app_mod._evaluating, "evaluate() should still be in flight during its backoff sleep"
        try:
            reset_document(doc_id)
            results["reset_status"] = 200
        except Exception as exc:
            results["reset_status"] = getattr(exc, "status_code", None)
        results["ev"] = await ev_task

    asyncio.run(scenario())
    assert results["reset_status"] == 409
    assert eval_key not in app_mod._evaluating              # cleared after gather, no leak
    assert results["ev"]["failedCriterionIds"] == []       # evaluate itself still completed successfully


def test_delete_during_retrying_evaluate_precompute_cancel_not_blocked_by_backoff(
    eval_client, monkeypatch,
):
    """A slow transient failure + backoff sleep inside /evaluate must not
    prevent a concurrent DELETE from cancelling an in-flight precompute task
    for a DIFFERENT/second document — the retry sleep for one paragraph's
    judge call must not block the event loop."""
    monkeypatch.setattr(app_mod, "EVAL_BACKOFF", 0.05)
    # NOTE: deliberately leave app_mod.asyncio.sleep as the REAL asyncio.sleep
    # (no monkeypatch) — this test's whole point is that a real backoff sleep
    # doesn't block the event loop, so DELETE for another document lands promptly.

    calls = {"n": 0}

    def flaky(*a, **kw):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise TimeoutError("slow")
        return _judge_result()

    monkeypatch.setattr(app_mod, "judge_one", flaky)
    pid = _make_para(eval_client)

    # second, precompute-eligible document whose warm-up we will cancel
    # concurrently with the first document's retrying /evaluate.
    precompute_doc = eval_client.post("/api/documents", json=_body(
        paragraphs=[{"source": f"s{i}", "target": f"t{i}"} for i in range(5)])).json()

    pc_calls = {"n": 0}

    async def slow_precompute_judge(conn, criterion, source, target, sl, tl, endpoint="precompute"):
        pc_calls["n"] += 1
        await asyncio.sleep(0.05)
        return _judge_result()

    async def scenario():
        pc_task = asyncio.create_task(precompute.run(precompute_doc["id"], slow_precompute_judge))
        precompute._tasks[(db.current_sid(), precompute_doc["id"])] = pc_task
        await asyncio.sleep(0.01)

        ev_task = asyncio.create_task(
            asyncio.to_thread(eval_client.post, f"/api/paragraphs/{pid}/evaluate"))
        await asyncio.sleep(0.02)                     # let evaluate() enter its backoff sleep

        t0 = time.monotonic()
        del_resp = await asyncio.to_thread(
            eval_client.delete, f"/api/documents/{precompute_doc['id']}")
        del_latency = time.monotonic() - t0

        calls_at_delete = pc_calls["n"]
        await asyncio.sleep(0.15)
        ev = (await ev_task).json()
        return del_resp.status_code, del_latency, calls_at_delete, pc_calls["n"], ev

    status, del_latency, calls_at_delete, calls_after, ev = asyncio.run(scenario())
    assert status == 204
    # DELETE must return promptly even though a sibling document's /evaluate
    # is mid-backoff-sleep — the event loop is not blocked by that sleep.
    assert del_latency < 0.1, f"DELETE took {del_latency:.3f}s — retry backoff blocked the loop"
    assert calls_after == calls_at_delete, "precompute kept spending after DELETE cancelled it"
    assert ev["failedCriterionIds"] == []                # the unrelated evaluate still completed


# ── 2. free-text language (German -> French) full loop, prompts asserted ──

def test_free_text_language_full_loop_preamble_on_every_call(eval_client, monkeypatch):
    """Upload a German->French doc (mocked judge), evaluate, accept a
    suggestion (re-judge), and confirm every judge_one call — including the
    accept-triggered re-judge — receives the German/French language preamble."""
    prompts_seen: list[tuple[str, str]] = []

    def recording_judge(client, criterion_id, source, target, *, source_lang, target_lang):
        from palimpsest.webapp.judge import scoring_system_prompt
        system = scoring_system_prompt(criterion_id, source_lang, target_lang)
        prompts_seen.append((system, f"[SOURCE — {source_lang}] {source}"))
        if len(prompts_seen) == 1:
            issues = [_wire_issue("Un paragraphe.", "Ein Absatz.",
                                  "mistranslated nuance", "Un paragraphe corrigé.")]
            return _judge_result(value=6.0, issues=issues)
        return _judge_result(value=9.0)

    monkeypatch.setattr(app_mod, "judge_one", recording_judge)
    pid = _make_para(eval_client, sourceLang="German", targetLang="French")

    ev1 = eval_client.post(f"/api/paragraphs/{pid}/evaluate").json()
    assert ev1["failedCriterionIds"] == []
    issue_id = ev1["issues"][0]["id"]

    applied = eval_client.post(f"/api/paragraphs/{pid}/apply-edit",
                               json={"issueId": str(issue_id)})
    assert applied.status_code == 200

    ev2 = eval_client.post(f"/api/paragraphs/{pid}/evaluate").json()
    assert ev2["failedCriterionIds"] == []

    assert len(prompts_seen) == 2, "expected one judge_one call per evaluate (initial + re-judge)"
    for system, user in prompts_seen:
        assert system.startswith("You are evaluating a translation from German into French.")
        assert "This rubric was written for Russian→English." in system
        assert user.startswith("[SOURCE — German]")


def test_free_text_language_precompute_also_gets_preamble(eval_client, monkeypatch):
    """precompute._run funnels through the same _judge_live -> judge_one seam;
    confirm the free-text language preamble applies there too."""
    prompts_seen: list[str] = []

    def recording_judge(client, criterion_id, source, target, *, source_lang, target_lang):
        from palimpsest.webapp.judge import scoring_system_prompt
        prompts_seen.append(scoring_system_prompt(criterion_id, source_lang, target_lang))
        return _judge_result()

    monkeypatch.setattr(app_mod, "judge_one", recording_judge)
    doc = eval_client.post("/api/documents", json=_body(
        sourceLang="German", targetLang="French", precompute=False,
        paragraphs=[{"source": "Ein Absatz.", "target": "Un paragraphe."}])).json()

    asyncio.run(precompute.run(doc["id"], app_mod._judge_live))
    assert len(prompts_seen) == 1
    assert prompts_seen[0].startswith("You are evaluating a translation from German into French.")


# ── 3. no-key / bad-key classification is fail-fast (quantified) ──────────

def test_missing_key_fails_fast_no_retry_no_delay(client, monkeypatch):
    """A model with no api_key at all (no OPENROUTER_API_KEY env fallback
    either) makes _client_for return None -> _judge_live raises RuntimeError
    immediately. RuntimeError is not in is_transient_error's allow-list, so
    this must NOT be retried, and must add ~0 latency before falling back to
    cache."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    conn = db.connect()
    conn.execute("INSERT INTO model(name,base_url,api_key,params_json) "
                 "VALUES('m','https://openrouter.ai/api/v1','','{}')")   # empty key
    conn.execute("INSERT INTO criterion(id,name,model_name,weight,scale_min,scale_max,enabled) "
                 "VALUES('accuracy','Accuracy','m',1.0,1,10,1)")
    conn.commit()
    budget.reset()

    real_sleep_calls = []
    orig_sleep = asyncio.sleep

    async def counting_sleep(dur):
        real_sleep_calls.append(dur)
        await orig_sleep(0)      # don't actually wait in the test, just count would-be sleeps

    monkeypatch.setattr(app_mod.asyncio, "sleep", counting_sleep)

    pid = _make_para(client)
    t0 = time.monotonic()
    ev = client.post(f"/api/paragraphs/{pid}/evaluate").json()
    elapsed = time.monotonic() - t0

    assert ev["failedCriterionIds"] == ["accuracy"]
    assert real_sleep_calls == [], "missing-key error must not trigger any backoff sleep"
    assert elapsed < 0.1, f"missing-key path took {elapsed:.3f}s — should fail immediately"


def test_bad_key_auth_error_fails_fast_no_retry(eval_client, monkeypatch):
    """An invalid key (401 AuthenticationError from the provider) must be
    classified deterministic, not transient — zero retries, zero backoff."""
    monkeypatch.setattr(app_mod, "EVAL_BACKOFF", 5.0)   # if this were used, the test would time out

    calls = {"n": 0}

    def bad_key(*a, **kw):
        calls["n"] += 1
        resp = httpx.Response(401, request=httpx.Request("POST", "http://or"))
        raise openai.AuthenticationError("Incorrect API key provided", response=resp, body=None)

    monkeypatch.setattr(app_mod, "judge_one", bad_key)
    pid = _make_para(eval_client)
    t0 = time.monotonic()
    ev = eval_client.post(f"/api/paragraphs/{pid}/evaluate").json()
    elapsed = time.monotonic() - t0

    assert calls["n"] == 1                    # no retry attempts
    assert ev["failedCriterionIds"] == ["accuracy"]
    assert elapsed < 0.5, f"auth-error path took {elapsed:.3f}s — must fail fast, not backoff"


def test_bad_key_falls_back_to_cache_without_retry_delay(eval_client, monkeypatch):
    """End-to-end: a precomputed/seeded paragraph with a bad key on live judge
    still serves the cached result, and does so without retry-induced delay."""
    monkeypatch.setattr(app_mod, "EVAL_BACKOFF", 5.0)

    def bad_key(*a, **kw):
        resp = httpx.Response(401, request=httpx.Request("POST", "http://or"))
        raise openai.AuthenticationError("bad key", response=resp, body=None)

    monkeypatch.setattr(app_mod, "judge_one", bad_key)
    pid = _make_para(eval_client)

    # seed a cache row directly (simulates a prior successful precompute)
    conn = db.connect()
    conn.execute(
        "INSERT INTO score(paragraph_id,criterion_id,value,summary,aggregate,criteria_key,kind,created_at) "
        "VALUES(?,?,?,?,?,?,?,?)", (pid, "accuracy", 7.5, "cached ok", 7.5, "accuracy", "cache", "2020-01-01"))
    conn.commit()

    t0 = time.monotonic()
    ev = eval_client.post(f"/api/paragraphs/{pid}/evaluate").json()
    elapsed = time.monotonic() - t0

    assert ev["cached"] is True
    assert ev["scores"][0]["value"] == pytest.approx(7.5)
    assert elapsed < 0.5, f"cache fallback with a bad key took {elapsed:.3f}s"
