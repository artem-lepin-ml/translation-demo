"""Tests for scripts/wiki_eval.py's runner-upgrade pieces (ticket 002):
model_slug, BudgetGuard's thread-safe extract/judge split accounting,
_resolve_route's CLI-wins-over-env resolution, and CLI parsing.

scripts/ isn't a package (pyproject [tool.pytest.ini_options] only puts
src/ on pythonpath) -- import the module directly off its file path, the
same convention scripts/wiki_eval.py itself uses for src/ at the top of the
file.
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import wiki_eval  # noqa: E402, I001


# ── model_slug ────────────────────────────────────────────────────────────


def test_model_slug_replaces_slash_and_appends_provider():
    assert wiki_eval.model_slug("openai/gpt-5.5", "provider-3") == "openai--gpt-5.5--provider-3"


def test_model_slug_preserves_dots():
    slug = wiki_eval.model_slug("google/gemini-3.1-flash-lite", "provider-9")
    assert slug == "google--gemini-3.1-flash-lite--provider-9"
    assert "." in slug  # dots kept, not sanitized away (working-style.md "Naming & PRs")


def test_model_slug_replaces_every_slash():
    assert wiki_eval.model_slug("a/b/c", "provider-1") == "a--b--c--provider-1"


# ── BudgetGuard ───────────────────────────────────────────────────────────


def test_guard_default_kind_is_judge_backward_compatible():
    """The pre-ticket-002 two-arg call sites (can_reserve(est), reserve(est),
    settle(est, actual)) must keep working unchanged -- kind defaults to
    "judge"."""
    guard = wiki_eval.BudgetGuard(max_usd=10.0)
    assert guard.can_reserve(1.0)
    guard.reserve(1.0)
    assert guard.spent == 1.0
    assert guard.calls_by_kind["judge"] == 1
    assert guard.calls_by_kind["extract"] == 0
    guard.settle(1.0, 0.5)
    assert guard.spent == 0.5
    assert guard.spent_by_kind["judge"] == 0.5


def test_guard_extract_kind_does_not_count_against_max_judge_calls():
    guard = wiki_eval.BudgetGuard(max_usd=10.0, max_judge_calls=1)
    assert guard.can_reserve(0.01, kind="judge")
    guard.reserve(0.01, kind="judge")
    assert not guard.can_reserve(0.01, kind="judge")
    assert guard.stopped_reason and "max_judge_calls" in guard.stopped_reason

    # extraction calls are NOT subject to the judge-call ceiling, only the $ cap
    guard2 = wiki_eval.BudgetGuard(max_usd=10.0, max_judge_calls=1)
    for _ in range(5):
        assert guard2.can_reserve(0.01, kind="extract")
        guard2.reserve(0.01, kind="extract")
    assert guard2.calls_by_kind["extract"] == 5
    assert guard2.stopped_reason is None


def test_guard_dollar_cap_applies_to_both_kinds_combined():
    guard = wiki_eval.BudgetGuard(max_usd=0.05)
    assert guard.can_reserve(0.03, kind="extract")
    guard.reserve(0.03, kind="extract")
    assert not guard.can_reserve(0.03, kind="judge")  # 0.03+0.03 > 0.05, shared pool
    assert guard.stopped_reason and "budget cap" in guard.stopped_reason


def test_guard_spend_and_call_split_tracked_per_kind():
    guard = wiki_eval.BudgetGuard(max_usd=10.0)
    guard.reserve(0.01, kind="extract")
    guard.reserve(0.01, kind="extract")
    guard.reserve(0.02, kind="judge")
    assert guard.calls_by_kind == {"extract": 2, "judge": 1}
    assert guard.spent_by_kind["extract"] == pytest.approx(0.02)
    assert guard.spent_by_kind["judge"] == pytest.approx(0.02)
    assert guard.n_calls == 3
    assert guard.spent == pytest.approx(0.04)


def test_guard_settle_corrects_actual_cost_per_kind():
    guard = wiki_eval.BudgetGuard(max_usd=10.0)
    guard.reserve(0.01, kind="extract")
    guard.settle(0.01, 0.004, kind="extract")  # actual cheaper than the estimate
    assert guard.spent == pytest.approx(0.004)
    assert guard.spent_by_kind["extract"] == pytest.approx(0.004)


def test_guard_settle_none_actual_is_a_noop():
    """settle(est, None) means the provider never surfaced usage.cost_usd --
    the caller's fallback token-price estimate stays the settled figure (i.e.
    settle is skipped, not zeroed)."""
    guard = wiki_eval.BudgetGuard(max_usd=10.0)
    guard.reserve(0.01, kind="judge")
    guard.settle(0.01, None, kind="judge")
    assert guard.spent == pytest.approx(0.01)


def test_guard_reserve_is_thread_safe_under_concurrent_extraction():
    """Regression test for the ticket-002 lock: naive += on plain floats/ints
    loses updates under concurrency. Hammer reserve() from several threads
    (mirroring the parallel-extraction ThreadPoolExecutor, DEFAULT_MAX_CONCURRENCY=4)
    and check nothing was lost."""
    guard = wiki_eval.BudgetGuard(max_usd=1000.0)
    n_threads = 8
    n_per_thread = 200

    def worker():
        for _ in range(n_per_thread):
            guard.reserve(0.001, kind="extract")

    threads = [threading.Thread(target=worker) for _ in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert guard.calls_by_kind["extract"] == n_threads * n_per_thread
    assert guard.spent == pytest.approx(0.001 * n_threads * n_per_thread)
    assert guard.n_calls == n_threads * n_per_thread


# ── _parallel_extract_fn (parallel extraction, order-safety) ───────────────


def test_parallel_extract_fn_preserves_order_with_duplicate_paragraphs():
    """The order-safe wrapper design choice (ticket 002): predict_tuples calls
    extract_fn(paragraph) once per paragraph in `paragraphs` order, so the
    replay must be positional, not content-keyed -- duplicate/blank paragraphs
    must not get their results swapped or reused across positions."""
    calls: list[str] = []
    lock = threading.Lock()

    def extract_fn(paragraph):
        with lock:
            calls.append(paragraph)
        return [paragraph.upper()]

    paragraphs = ["a", "", "a", "b", ""]  # duplicates + repeated blanks
    wrapped = wiki_eval._parallel_extract_fn(extract_fn, paragraphs)

    results = [wrapped(p) for p in paragraphs]
    assert results == [["A"], [""], ["A"], ["B"], [""]]
    # every paragraph was actually extracted once (execution order may vary
    # under concurrency, but the content multiset must match exactly).
    assert sorted(calls) == sorted(paragraphs)


def test_parallel_extract_fn_actually_overlaps_in_time():
    """Sanity check that extraction really runs concurrently -- without this,
    "parallel extraction" would silently degrade to sequential."""
    import time

    in_flight: list[str] = []
    max_in_flight = [0]
    lock = threading.Lock()

    def slow_extract_fn(paragraph):
        with lock:
            in_flight.append(paragraph)
            max_in_flight[0] = max(max_in_flight[0], len(in_flight))
        time.sleep(0.05)
        with lock:
            in_flight.remove(paragraph)
        return [paragraph]

    paragraphs = [str(i) for i in range(8)]
    wrapped = wiki_eval._parallel_extract_fn(slow_extract_fn, paragraphs)
    results = [wrapped(p) for p in paragraphs]

    assert results == [[p] for p in paragraphs]
    assert max_in_flight[0] > 1  # overlapped, not run strictly one-at-a-time


# ── _resolve_route (CLI --model/--provider override) ───────────────────────


def test_resolve_route_defaults_to_closerouter_env_values():
    route = wiki_eval._resolve_route(None, None)
    assert route["extract_model"] == wiki_eval.CLOSEROUTER_MODEL
    assert route["judge_model"] == wiki_eval.CLOSEROUTER_MODEL
    assert route["extract_extra_body"] == {"provider": wiki_eval.CLOSEROUTER_PROVIDER}


def test_resolve_route_cli_model_and_provider_win():
    route = wiki_eval._resolve_route("openai/gpt-5.5", "provider-3")
    assert route["extract_model"] == "openai/gpt-5.5"
    assert route["judge_model"] == "openai/gpt-5.5"
    assert route["extract_extra_body"] == {"provider": "provider-3"}
    assert route["judge_extra_body"] == {"provider": "provider-3"}


def test_resolve_route_partial_override_falls_back_per_field():
    # only --model given -> provider still falls back to CLOSEROUTER_PROVIDER
    route = wiki_eval._resolve_route("openai/gpt-5.5", None)
    assert route["extract_model"] == "openai/gpt-5.5"
    assert route["extract_extra_body"] == {"provider": wiki_eval.CLOSEROUTER_PROVIDER}


# ── CLI parsing ──────────────────────────────────────────────────────────


def test_cli_run_defaults():
    args = wiki_eval._build_parser().parse_args(["run"])
    assert args.model is None
    assert args.provider is None
    assert args.max_judge_calls == wiki_eval.MAX_JUDGE_CALLS == 900
    assert args.max_usd == wiki_eval.DEFAULT_MAX_USD
    assert args.func is wiki_eval.cmd_run


def test_cli_run_model_provider_and_max_judge_calls_override():
    args = wiki_eval._build_parser().parse_args([
        "run", "--model", "openai/gpt-5.5", "--provider", "provider-3",
        "--max-judge-calls", "5000", "--max-usd", "12",
    ])
    assert args.model == "openai/gpt-5.5"
    assert args.provider == "provider-3"
    assert args.max_judge_calls == 5000
    assert args.max_usd == 12.0


def test_cli_run_dry_run_flag():
    args = wiki_eval._build_parser().parse_args(["run", "--dry-run"])
    assert args.dry_run is True


def test_cli_ablate_accepts_same_model_provider_flags():
    args = wiki_eval._build_parser().parse_args([
        "ablate", "--model", "deepseek/deepseek-v4-flash", "--provider", "provider-1",
    ])
    assert args.model == "deepseek/deepseek-v4-flash"
    assert args.provider == "provider-1"
    assert args.func is wiki_eval.cmd_ablate
