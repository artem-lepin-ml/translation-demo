import asyncio

import pytest

from palimpsest.webapp import budget


def setup_function():
    budget.reset()
    budget._PRICES = {"m": (1e-6, 2e-6)}   # $/token in,out (injected; no live fetch)


def test_estimate_openai_style_no_additive_reasoning():
    # prompt 100 tok * 1e-6 + (out 1000) * 2e-6
    assert budget.estimate("m", 100, 1000, reasoning_max_tokens=0) == pytest.approx(100e-6 + 2000e-6)


def test_estimate_anthropic_additive_reasoning():
    assert budget.estimate("m", 100, 1000, reasoning_max_tokens=500) == pytest.approx(100e-6 + 3000e-6)


def test_reserve_blocks_before_overshoot():
    budget._CAP_USD = 0.005
    asyncio.run(budget.reserve(0.004))
    with pytest.raises(budget.BudgetExceeded):
        asyncio.run(budget.reserve(0.004))   # 0.004+0.004 > 0.005 → blocked BEFORE spend


def test_reserve_is_atomic_under_gather():
    budget._CAP_USD = 0.01
    budget._CALL_CAP = 100

    async def run():
        async def one():
            try:
                await budget.reserve(0.003)
                return True
            except budget.BudgetExceeded:
                return False
        return await asyncio.gather(*[one() for _ in range(10)])

    results = asyncio.run(run())
    # cap 0.01 / 0.003 → at most 3 succeed; never exceeds cap
    assert sum(results) == 3
    assert budget._STATE["spent"] <= 0.01 + 1e-9


def test_settle_corrects_to_actual():
    budget._CAP_USD = 1.0
    gen = asyncio.run(budget.reserve(0.01))
    asyncio.run(budget.settle(0.01, 0.004, gen))
    assert budget._STATE["spent"] == pytest.approx(0.004)


def test_call_count_cap():
    budget._CAP_USD = 100.0
    budget._CALL_CAP = 2
    asyncio.run(budget.reserve(0.0))
    asyncio.run(budget.reserve(0.0))
    with pytest.raises(budget.BudgetExceeded):
        asyncio.run(budget.reserve(0.0))


def test_count_tokens_cyrillic_is_upper_bound_on_bytes():
    text = "Привет мир, это кириллица"       # multi-byte UTF-8 chars
    tok = budget.count_tokens(text)
    assert tok >= len(text)                  # bytes >= chars always for Cyrillic
    assert tok == len(text.encode("utf-8"))


def test_judge_style_estimate_includes_system_prompt_settle_only_lowers_spent():
    from palimpsest.webapp.judge import _scoring_prompt

    budget._CAP_USD = 1.0
    system = _scoring_prompt("accuracy")
    ru, en = "Съешь ещё этих мягких французских булок", "Have some more soft French buns"
    prompt_tok = budget.count_tokens(system) + budget.count_tokens(ru) + budget.count_tokens(en)
    est = budget.estimate("m", prompt_tok, 1024, 0)
    gen = asyncio.run(budget.reserve(est))
    spent_after_reserve = budget._STATE["spent"]

    # a realistic actual cost is much smaller than the worst-case reservation
    # (system prompt alone dwarfs a one-paragraph judge call's real usage)
    actual = est * 0.1
    asyncio.run(budget.settle(est, actual, gen))
    assert budget._STATE["spent"] < spent_after_reserve   # settle only ever lowers spend here
    assert budget._STATE["spent"] == pytest.approx(actual)


def test_load_prices_does_not_cache_failure(monkeypatch):
    budget._PRICES = None

    def _raise(*a, **kw):
        raise OSError("network down")

    import httpx
    monkeypatch.setattr(httpx, "get", _raise)

    first = budget._load_prices()
    assert first == {}
    assert budget._PRICES is None            # not cached → next call retries the fetch

    second = budget._load_prices()
    assert second == {}
    assert budget._PRICES is None


def test_budget_endpoints_snapshot_and_reset():
    from palimpsest.webapp import budget
    from palimpsest.webapp.app import get_budget, reset_budget

    budget.reset()
    asyncio.run(budget.reserve(0.001))
    snap = get_budget()
    assert snap["calls"] == 1 and snap["spentUsd"] > 0
    out = reset_budget()
    assert out["calls"] == 0 and out["spentUsd"] == 0.0


def test_stale_settle_after_reset_does_not_go_negative():
    """Reserve, then reset() (simulating an admin action mid-run), then settle
    the OLD reservation with its stale generation. The generation guard must
    make settle() a no-op for spend — reset()'s fresh spent=0.0 must survive
    an in-flight call's settle() firing after the reset."""
    budget._CAP_USD = 1.0
    budget.reset()
    gen = asyncio.run(budget.reserve(0.05))
    budget.reset()                                    # spent=0 now, generation bumped
    asyncio.run(budget.settle(0.05, 0.001, gen))       # stale settle — must no-op
    assert budget._STATE["spent"] == 0.0
    assert budget._STATE["spent"] >= 0


def test_fresh_settle_after_reset_still_applies():
    """Sanity counterpart: a settle() using the CURRENT generation (a new
    reserve() made after reset) must still apply normally — the guard only
    blocks stale generations, not settles in general."""
    budget._CAP_USD = 1.0
    budget.reset()
    gen = asyncio.run(budget.reserve(0.05))
    asyncio.run(budget.settle(0.05, 0.01, gen))
    assert budget._STATE["spent"] == pytest.approx(0.01)


def test_error_settle_releases_reservation():
    """_judge_live's error path settles to 0.0 (not None) so a hard provider
    error releases the worst-case reservation instead of holding it forever."""
    budget._CAP_USD = 1.0
    budget.reset()
    gen = asyncio.run(budget.reserve(0.05))
    assert budget._STATE["spent"] == pytest.approx(0.05)
    asyncio.run(budget.settle(0.05, 0.0, gen))         # simulates the error-path settle
    assert budget._STATE["spent"] == pytest.approx(0.0)


def test_judge_live_error_path_releases_reservation_end_to_end(tmp_path, monkeypatch):
    """Integration check of app.py's _judge_live wiring (not just budget.py in
    isolation): a failing judge call must not permanently hold its worst-case
    budget reservation."""
    from types import SimpleNamespace

    from palimpsest.webapp import app as appmod, db
    from palimpsest.webapp import seed as seedmod

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "budget_err.db")
    monkeypatch.setattr(db, "_conn", None)
    seedmod.seed()
    try:
        budget.reset()
        budget._CAP_USD = 100.0
        budget._CALL_CAP = 10000
        budget._PRICES = {}

        def _raise_judge(client, criterion_id, ru, en, *, source_lang="ru", target_lang="en", **_kw):
            raise RuntimeError("simulated provider error")

        monkeypatch.setattr(appmod, "_client_for", lambda conn, name: SimpleNamespace(
            config=SimpleNamespace(max_tokens=1024, extra_body=None)))
        monkeypatch.setattr(appmod, "judge_one", _raise_judge)

        conn = db.connect()
        pid = conn.execute("SELECT id FROM paragraph ORDER BY id LIMIT 1").fetchone()["id"]
        crit = conn.execute("SELECT * FROM criterion WHERE enabled=1 LIMIT 1").fetchone()

        asyncio.run(appmod._judge_live(conn, crit, "ru text", "en text", "ru", "en"))
    except RuntimeError:
        pass
    else:
        raise AssertionError("expected the simulated judge failure to propagate")
    finally:
        if db._conn is not None:
            db._conn.close()
            db._conn = None

    assert budget._STATE["spent"] == pytest.approx(0.0), (
        "a hard provider error must release its worst-case reservation, not hold it forever"
    )
