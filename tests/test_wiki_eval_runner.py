"""Tests for scripts/wiki_eval.py's runner-upgrade pieces (ticket 002):
model_slug, BudgetGuard's thread-safe extract/judge split accounting,
_resolve_route's CLI-wins-over-env resolution, and CLI parsing. Also covers
ticket 002b (article-level parallelism): `_process_articles_parallel`'s
order-preserving article dispatch, the process-wide `llm_semaphore` bound
shared by `_build_extract_fn`/`_build_judge`, and `_canonicalize_fn`'s
thread-safe cache.

scripts/ isn't a package (pyproject [tool.pytest.ini_options] only puts
src/ on pythonpath) -- import the module directly off its file path, the
same convention scripts/wiki_eval.py itself uses for src/ at the top of the
file.
"""
from __future__ import annotations

import json
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


def test_resolve_route_auto_provider_omits_provider_key(monkeypatch):
    """ticket 004: --provider auto must not send {"provider": "auto"} -- the
    provider key is omitted from extra_body entirely so CloseRouter's own
    routing picks a route (verified in ticket-003 triage for models with no
    clean pinned route, e.g. qwen3.7-plus)."""
    route = wiki_eval._resolve_route("qwen/qwen3.7-plus", "auto")
    assert route["extract_extra_body"] is None
    assert route["judge_extra_body"] is None
    # model_slug still appends "--auto" verbatim -- no special-casing needed there.
    assert wiki_eval.model_slug("qwen/qwen3.7-plus", "auto") == "qwen--qwen3.7-plus--auto"


def test_resolve_route_non_auto_provider_still_pins_explicit_route():
    route = wiki_eval._resolve_route("openai/gpt-5.5", "provider-8")
    assert route["extract_extra_body"] == {"provider": "provider-8"}
    assert route["judge_extra_body"] == {"provider": "provider-8"}


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


def test_cli_run_article_workers_default_and_override():
    args = wiki_eval._build_parser().parse_args(["run"])
    assert args.article_workers == wiki_eval.DEFAULT_ARTICLE_WORKERS == 3

    args2 = wiki_eval._build_parser().parse_args(["run", "--article-workers", "5"])
    assert args2.article_workers == 5


def test_cli_ablate_article_workers_default_and_override():
    args = wiki_eval._build_parser().parse_args(["ablate"])
    assert args.article_workers == wiki_eval.DEFAULT_ARTICLE_WORKERS == 3

    args2 = wiki_eval._build_parser().parse_args(["ablate", "--article-workers", "2"])
    assert args2.article_workers == 2


def test_cli_run_llm_workers_default_and_override():
    args = wiki_eval._build_parser().parse_args(["run"])
    assert args.llm_workers == wiki_eval.DEFAULT_LLM_WORKERS == 4

    args2 = wiki_eval._build_parser().parse_args(["run", "--llm-workers", "16"])
    assert args2.llm_workers == 16


def test_cli_ablate_llm_workers_default_and_override():
    args = wiki_eval._build_parser().parse_args(["ablate"])
    assert args.llm_workers == wiki_eval.DEFAULT_LLM_WORKERS == 4

    args2 = wiki_eval._build_parser().parse_args(["ablate", "--llm-workers", "16"])
    assert args2.llm_workers == 16


def test_cli_run_wikidata_cache_default_and_override():
    args = wiki_eval._build_parser().parse_args(["run"])
    assert args.wikidata_cache == str(wiki_eval.WIKIDATA_CACHE)

    args2 = wiki_eval._build_parser().parse_args([
        "run", "--wikidata-cache", "reports/terminology/wikidata_cache.gemini.jsonl",
    ])
    assert args2.wikidata_cache == "reports/terminology/wikidata_cache.gemini.jsonl"


def test_cli_ablate_wikidata_cache_default_and_override():
    args = wiki_eval._build_parser().parse_args(["ablate"])
    assert args.wikidata_cache == str(wiki_eval.WIKIDATA_CACHE)

    args2 = wiki_eval._build_parser().parse_args([
        "ablate", "--wikidata-cache", "reports/terminology/wikidata_cache.qwen.jsonl",
    ])
    assert args2.wikidata_cache == "reports/terminology/wikidata_cache.qwen.jsonl"


def test_cli_run_wikidata_workers_default_and_override():
    args = wiki_eval._build_parser().parse_args(["run"])
    assert args.wikidata_workers == wiki_eval.DEFAULT_NETWORK_CONCURRENCY == 3

    args2 = wiki_eval._build_parser().parse_args(["run", "--wikidata-workers", "2"])
    assert args2.wikidata_workers == 2


def test_cli_ablate_wikidata_workers_default_and_override():
    args = wiki_eval._build_parser().parse_args(["ablate"])
    assert args.wikidata_workers == wiki_eval.DEFAULT_NETWORK_CONCURRENCY == 3

    args2 = wiki_eval._build_parser().parse_args(["ablate", "--wikidata-workers", "2"])
    assert args2.wikidata_workers == 2


# ── _process_articles_parallel (article-level parallelism, ticket 002b) ────


def test_process_articles_parallel_preserves_gt_order_with_shuffled_completion():
    """Regression for ticket 002b's article-level parallelism: pred_records must
    come back in `articles`/gt_records input order regardless of which article
    finishes first. `predict.predict_tuples` is faked out entirely (with a
    per-title sleep that scrambles completion order) so this test exercises
    ONLY `_process_articles_parallel`'s own collection/ordering logic, not the
    real grounding/judge pipeline (already covered elsewhere)."""
    import time

    calls_order: list[str] = []
    order_lock = threading.Lock()
    # Deliberately inverse of gt/article order: "d" finishes first, "a" last.
    delays = {"a": 0.09, "b": 0.06, "c": 0.03, "d": 0.0}

    def fake_predict_tuples(article_text, paragraphs, extract_fn, ground_fn, *,
                             judge, judge_cache, scope_id, canonicalize):
        time.sleep(delays[scope_id])
        with order_lock:
            calls_order.append(scope_id)
        return {
            "tuples": [],
            "records": [{"index": 0, "surface": scope_id, "lemma": None,
                          "qid": "Q1", "span_len": 1, "resolved_by": "exact_label"}],
        }

    original = wiki_eval.predict.predict_tuples
    wiki_eval.predict.predict_tuples = fake_predict_tuples
    try:
        articles = [(t, ["p1"], "p1") for t in ("a", "b", "c", "d")]
        pred_records, n_paragraphs_total = wiki_eval._process_articles_parallel(
            articles, article_workers=4, extract_fn=lambda p: [], judge=None,
            canonicalize=lambda q: q, wd=None,
            config=wiki_eval._config_from_bits("111"), guard=None,
        )
    finally:
        wiki_eval.predict.predict_tuples = original

    # Completion really was scrambled (sanity check the test is exercising
    # concurrency, not accidentally degrading to sequential a,b,c,d order).
    assert calls_order != ["a", "b", "c", "d"]
    assert calls_order[0] == "d"  # fastest (0 delay) finishes first
    # ...but pred_records preserve gt-input order regardless of completion order.
    assert [r["title"] for r in pred_records] == ["a", "b", "c", "d"]
    assert n_paragraphs_total == 4  # 1 paragraph x 4 articles


def test_process_articles_parallel_skips_new_articles_once_guard_stopped():
    """Once the shared BudgetGuard is stopped, articles not yet started must
    not run at all (mirrors ticket 002's sequential early-break, adapted to
    concurrent article workers -- see _process_articles_parallel's docstring)."""
    guard = wiki_eval.BudgetGuard(max_usd=10.0)
    guard.stopped_reason = "budget cap $10.00 hit (test)"

    calls: list[str] = []

    def fake_predict_tuples(article_text, paragraphs, extract_fn, ground_fn, *,
                             judge, judge_cache, scope_id, canonicalize):
        calls.append(scope_id)
        return {"tuples": [], "records": []}

    original = wiki_eval.predict.predict_tuples
    wiki_eval.predict.predict_tuples = fake_predict_tuples
    try:
        articles = [(t, ["p1"], "p1") for t in ("a", "b", "c")]
        pred_records, n_paragraphs_total = wiki_eval._process_articles_parallel(
            articles, article_workers=2, extract_fn=lambda p: [], judge=None,
            canonicalize=lambda q: q, wd=None,
            config=wiki_eval._config_from_bits("111"), guard=guard,
        )
    finally:
        wiki_eval.predict.predict_tuples = original

    assert calls == []
    assert pred_records == []
    assert n_paragraphs_total == 0


# ── global LLM semaphore (ticket 002b) ──────────────────────────────────────


def test_llm_semaphore_bounds_concurrent_extract_and_judge_calls(monkeypatch):
    """Regression: article-level parallelism must never allow more than
    DEFAULT_MAX_CONCURRENCY real LLM calls (extract OR judge) in flight at
    once, across however many article/paragraph worker threads are calling
    concurrently -- the ONE shared `llm_semaphore` built in `_run_one_config`
    and threaded into both `_build_extract_fn` and `_build_judge` is what
    enforces this, not either builder's own ThreadPoolExecutor size."""
    import time

    from palimpsest.llm.client import DEFAULT_MAX_CONCURRENCY, LLMResult, Usage

    in_flight = [0]
    max_in_flight = [0]
    lock = threading.Lock()

    class FakeLLMClient:
        """Counts concurrent complete() calls (retries now loop over
        client.complete() inside wiki_eval's own _complete_with_slot helper,
        not client.complete_retrying -- see its docstring); distinguishes
        judge calls (non-empty `system`) from extract calls (system="") to
        return shaped-appropriately content for each."""

        def __init__(self, config):
            self.config = config

        def complete(self, system, user):
            with lock:
                in_flight[0] += 1
                max_in_flight[0] = max(max_in_flight[0], in_flight[0])
            time.sleep(0.03)
            with lock:
                in_flight[0] -= 1
            if system:  # judge call
                return LLMResult(content='{"qid": null, "reason": "no match"}',
                                  usage=Usage(10, 5, 0, 0.0001))
            return LLMResult(content="[]", usage=Usage(10, 5, 0, 0.0001))  # extract call

    monkeypatch.setattr("palimpsest.llm.client.LLMClient", FakeLLMClient)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-not-a-secret")

    guard = wiki_eval.BudgetGuard(max_usd=1000.0)
    llm_semaphore = wiki_eval._CountingSemaphore(DEFAULT_MAX_CONCURRENCY)
    extract_fn = wiki_eval._build_extract_fn(guard, llm_semaphore)
    judge = wiki_eval._build_judge(guard, llm_semaphore)
    assert judge is not None

    paragraphs = [f"paragraph {i}" for i in range(12)]
    threads = [threading.Thread(target=extract_fn, args=(p,)) for p in paragraphs]
    threads += [threading.Thread(target=judge, args=("some judge prompt",)) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert max_in_flight[0] > 1  # actually overlapped, not accidentally serialized
    assert max_in_flight[0] <= DEFAULT_MAX_CONCURRENCY  # the hard cap held
    # The production _CountingSemaphore observed the same bound it enforced --
    # this is the figure meta.json reports as llm_max_in_flight_observed.
    assert 1 < llm_semaphore.max_in_use <= DEFAULT_MAX_CONCURRENCY
    assert guard.calls_by_kind["extract"] == 12
    assert guard.calls_by_kind["judge"] == 6


def test_counting_semaphore_enforces_bound_and_records_peak():
    """_CountingSemaphore (ticket 002b): same blocking bound as a plain
    threading.Semaphore, plus a `max_in_use` peak that meta.json reports as
    llm_max_in_flight_observed."""
    import time

    sem = wiki_eval._CountingSemaphore(2)
    in_use = [0]
    over_bound = [False]
    lock = threading.Lock()

    def worker():
        with sem:
            with lock:
                in_use[0] += 1
                if in_use[0] > 2:
                    over_bound[0] = True
            time.sleep(0.02)
            with lock:
                in_use[0] -= 1

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not over_bound[0]  # never more than 2 holders at once
    assert sem.max_in_use == 2  # 8 workers vs 2 slots -> the peak is exactly the cap


# ── thread-safe dict caches (ticket 002b) ───────────────────────────────────


def test_canonicalize_fn_cache_is_thread_safe_under_concurrent_reuse():
    """`_canonicalize_fn`'s closure-local dict cache is now guarded by a lock
    (ticket 002b) since `_run_one_config` shares ONE `canonicalize` across
    every concurrent article worker. Hammer it from many threads reusing only
    a handful of distinct QIDs (forcing cache hits to race with cache
    fills) and assert every call still returns the correct canonical form."""
    import time

    calls = []
    call_lock = threading.Lock()

    class FakeWD:
        def get_entities(self, qids, props=""):
            with call_lock:
                calls.append(qids[0])
            time.sleep(0.005)
            return {qids[0]: {"id": qids[0] + "-canon"}}

    canonicalize = wiki_eval._canonicalize_fn(FakeWD())

    n = 60
    results: list[str | None] = [None] * n

    def worker(i: int) -> None:
        results[i] = canonicalize(f"Q{i % 5}")  # only 5 distinct qids -> heavy cache reuse

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    for i, r in enumerate(results):
        assert r == f"Q{i % 5}-canon"


# ── _run_one_config wiring for --llm-workers / --wikidata-cache (ticket 004) ─


def test_run_one_config_sizes_llm_semaphore_from_llm_workers(monkeypatch, tmp_path):
    """--llm-workers must size the process-wide llm_semaphore that
    _run_one_config builds (meta.json's llm_semaphore field then reflects
    it), not the hardcoded palimpsest.llm.client.DEFAULT_MAX_CONCURRENCY."""
    captured_sizes = []

    class FakeSemaphore:
        def __init__(self, value):
            captured_sizes.append(value)
            self.max_in_use = value

    monkeypatch.setattr(wiki_eval, "_CountingSemaphore", FakeSemaphore)
    monkeypatch.setattr(wiki_eval, "_build_judge", lambda guard, sem, **kw: None)
    monkeypatch.setattr(wiki_eval, "_build_extract_fn", lambda guard, sem, **kw: (lambda p: []))
    monkeypatch.setattr(wiki_eval, "_process_articles_parallel", lambda articles, **kw: ([], 0))
    monkeypatch.setattr(
        wiki_eval, "WikidataClient", lambda cache_path=None, network_concurrency=3: object(),
    )
    monkeypatch.setattr(wiki_eval, "_canonicalize_fn", lambda wd: (lambda q: q))

    guard = wiki_eval.BudgetGuard(max_usd=10.0)
    _, counters = wiki_eval._run_one_config(
        "111", [], str(tmp_path), dry_run=False, guard=guard, llm_workers=7,
    )
    assert captured_sizes == [7]
    assert counters["llm_max_in_flight_observed"] == 7  # FakeSemaphore.max_in_use == its size


def test_run_one_config_default_llm_workers_matches_constant(monkeypatch, tmp_path):
    captured_sizes = []

    class FakeSemaphore:
        def __init__(self, value):
            captured_sizes.append(value)
            self.max_in_use = value

    monkeypatch.setattr(wiki_eval, "_CountingSemaphore", FakeSemaphore)
    monkeypatch.setattr(wiki_eval, "_build_judge", lambda guard, sem, **kw: None)
    monkeypatch.setattr(wiki_eval, "_build_extract_fn", lambda guard, sem, **kw: (lambda p: []))
    monkeypatch.setattr(wiki_eval, "_process_articles_parallel", lambda articles, **kw: ([], 0))
    monkeypatch.setattr(
        wiki_eval, "WikidataClient", lambda cache_path=None, network_concurrency=3: object(),
    )
    monkeypatch.setattr(wiki_eval, "_canonicalize_fn", lambda wd: (lambda q: q))

    guard = wiki_eval.BudgetGuard(max_usd=10.0)
    wiki_eval._run_one_config("111", [], str(tmp_path), dry_run=False, guard=guard)
    assert captured_sizes == [wiki_eval.DEFAULT_LLM_WORKERS] == [4]


def test_run_one_config_threads_wikidata_cache_path_to_client(monkeypatch, tmp_path):
    """--wikidata-cache must reach WikidataClient(cache_path=...) -- both the
    dry-run and non-dry-run branches build `wd` from the same parameter."""
    captured: dict = {}

    class FakeWD:
        def __init__(self, cache_path=None, network_concurrency=3):
            captured["cache_path"] = cache_path
            captured["network_concurrency"] = network_concurrency

    monkeypatch.setattr(wiki_eval, "WikidataClient", FakeWD)
    monkeypatch.setattr(wiki_eval, "_canonicalize_fn", lambda wd: (lambda q: q))

    custom_cache = str(tmp_path / "wikidata_cache.custom.jsonl")
    wiki_eval._run_one_config(
        "111", [], str(tmp_path), dry_run=True, guard=None, wikidata_cache=custom_cache,
    )
    assert captured["cache_path"] == custom_cache


def test_run_one_config_default_wikidata_cache_is_shared_path(monkeypatch, tmp_path):
    captured: dict = {}

    class FakeWD:
        def __init__(self, cache_path=None, network_concurrency=3):
            captured["cache_path"] = cache_path
            captured["network_concurrency"] = network_concurrency

    monkeypatch.setattr(wiki_eval, "WikidataClient", FakeWD)
    monkeypatch.setattr(wiki_eval, "_canonicalize_fn", lambda wd: (lambda q: q))

    wiki_eval._run_one_config("111", [], str(tmp_path), dry_run=True, guard=None)
    assert captured["cache_path"] == wiki_eval.WIKIDATA_CACHE


def test_run_one_config_threads_wikidata_workers_to_client(monkeypatch, tmp_path):
    """--wikidata-workers must reach WikidataClient(network_concurrency=...)
    (2026-07-05 canary 429-storm adaptation: matrix runs pass 2 to halve
    per-process Wikidata pressure)."""
    captured: dict = {}

    class FakeWD:
        def __init__(self, cache_path=None, network_concurrency=3):
            captured["network_concurrency"] = network_concurrency

    monkeypatch.setattr(wiki_eval, "WikidataClient", FakeWD)
    monkeypatch.setattr(wiki_eval, "_canonicalize_fn", lambda wd: (lambda q: q))

    wiki_eval._run_one_config(
        "111", [], str(tmp_path), dry_run=True, guard=None, wikidata_workers=2,
    )
    assert captured["network_concurrency"] == 2

    # default stays the client's own politeness constant
    wiki_eval._run_one_config("111", [], str(tmp_path), dry_run=True, guard=None)
    assert captured["network_concurrency"] == wiki_eval.DEFAULT_NETWORK_CONCURRENCY == 3


# ── qwen-run resilience patch (2026-07-05): FailureTracker ─────────────────
#
# A single call that fails 3x (client.py's pre-patch default) can kill an
# entire ~35k-call run when its only route flaps with 429s and CloseRouter's
# circuit breaker turns that into minutes-long hard-503 windows. The fix is
# three layers: (1) longer retries (RESILIENT_ATTEMPTS/RESILIENT_BACKOFF),
# (2) last-resort tolerance once even that's exhausted, (3) LOUD accounting
# of every tolerated failure via FailureTracker so a run never silently
# degrades without the owner knowing. Tests below cover (2)+(3); (1) is
# covered by the "resilient attempts/backoff wired" tests further down.


def test_failure_tracker_records_failed_paragraphs_and_judge_calls():
    tracker = wiki_eval.FailureTracker()
    tracker.record_failed_paragraph("Article A", 3)
    tracker.record_failed_paragraph("Article B", 0)
    tracker.record_failed_judge_call()
    tracker.record_failed_judge_call()

    assert tracker.n_failed_paragraphs == 2
    assert tracker.failed_paragraphs == [
        {"title": "Article A", "paragraph_index": 3},
        {"title": "Article B", "paragraph_index": 0},
    ]
    assert tracker.n_failed_judge_calls == 2


def test_failure_tracker_thread_safe_under_concurrent_recording():
    tracker = wiki_eval.FailureTracker()
    n_threads, n_per_thread = 8, 50

    def worker(i: int) -> None:
        for j in range(n_per_thread):
            tracker.record_failed_paragraph(f"t{i}", j)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert tracker.n_failed_paragraphs == n_threads * n_per_thread
    assert len(tracker.failed_paragraphs) == n_threads * n_per_thread


# ── _parallel_extract_fn: last-resort extraction tolerance ─────────────────


def test_parallel_extract_fn_tolerates_transient_exhausted_paragraph():
    """A paragraph whose extract_fn call is still TRANSIENT-failing (simulating
    complete_retrying having exhausted RESILIENT_ATTEMPTS against a flapping
    provider-8-style route) must not kill the whole article -- it's tolerated
    as zero mentions, and the failure is recorded loudly via FailureTracker,
    never silently dropped."""

    def flaky_extract_fn(paragraph):
        if paragraph == "bad":
            raise TimeoutError("simulated exhausted retries against a 429/503 route")
        return [paragraph.upper()]

    tracker = wiki_eval.FailureTracker()
    wrapped = wiki_eval._parallel_extract_fn(
        flaky_extract_fn, ["good1", "bad", "good2"], title="Ancient Sumer", tracker=tracker,
    )
    results = [wrapped(p) for p in ["good1", "bad", "good2"]]

    assert results == [["GOOD1"], [], ["GOOD2"]]
    assert tracker.n_failed_paragraphs == 1
    assert tracker.failed_paragraphs == [{"title": "Ancient Sumer", "paragraph_index": 1}]
    assert tracker.n_failed_judge_calls == 0  # unaffected, different counter


def test_parallel_extract_fn_deterministic_error_still_raises_and_kills_run():
    """A deterministic failure (bad request / bad model config) must NOT be
    tolerated -- it means every remaining paragraph would fail identically,
    so the whole run must still die loudly instead of silently degrading."""

    def bad_extract_fn(paragraph):
        raise ValueError("400 bad request -- misconfigured model id")

    tracker = wiki_eval.FailureTracker()
    with pytest.raises(ValueError):
        wiki_eval._parallel_extract_fn(bad_extract_fn, ["p1"], title="X", tracker=tracker)

    assert tracker.n_failed_paragraphs == 0  # not tolerated, not counted as a tolerance


def test_parallel_extract_fn_without_tracker_still_tolerates_silently():
    """title/tracker default to None so existing callers (this function's own
    pre-ticket tests included) keep working unchanged -- the tolerance logic
    still runs, it just has nothing to record into."""

    def flaky_extract_fn(paragraph):
        if paragraph == "bad":
            raise TimeoutError("simulated exhausted retries")
        return [paragraph]

    wrapped = wiki_eval._parallel_extract_fn(flaky_extract_fn, ["good", "bad"])
    results = [wrapped(p) for p in ["good", "bad"]]
    assert results == [["good"], []]


# ── _complete_with_slot: semaphore released during backoff (2026-07-06) ────
#
# Root cause diagnosed live via py-spy: the old code held the llm_semaphore
# slot around the ENTIRE complete_retrying(...) call, backoff sleeps
# included. Under a sustained upstream 429 storm, all N slots ended up held
# by threads that were merely sleeping (observed: 8/8 slots sleeping,
# ~20 threads queued on acquire, zero open connections for over an hour) --
# throughput collapsed to zero. The fix moves the retry loop into wiki_eval
# itself (_complete_with_slot) so the slot is acquired fresh for each
# individual network attempt and released before the backoff sleep.


def test_complete_with_slot_releases_semaphore_during_backoff_sleep(monkeypatch):
    """The whole point of the fix: while a call is sleeping between retry
    attempts, the llm_semaphore slot must be free for another thread to use
    -- not held for the full 1..60s backoff window."""
    from palimpsest.llm.client import LLMResult, Usage

    calls: list[int] = []

    class FlakyOnceClient:
        def complete(self, system, user):
            calls.append(1)
            if len(calls) == 1:
                raise TimeoutError("transient")
            return LLMResult(content="ok", usage=Usage(1, 1, 0, 0.0))

    semaphore = threading.Semaphore(1)  # single slot: any hold during sleep would show up
    slot_free_during_sleep: list[bool] = []

    def fake_sleep(seconds):
        acquired = semaphore.acquire(blocking=False)
        slot_free_during_sleep.append(acquired)
        if acquired:
            semaphore.release()

    monkeypatch.setattr(wiki_eval.time, "sleep", fake_sleep)

    result = wiki_eval._complete_with_slot(
        FlakyOnceClient(), "sys", "user", semaphore, attempts=3, backoff=(0.01, 0.01, 0.01),
    )

    assert result.content == "ok"
    assert len(calls) == 2  # one transient failure, then success
    assert slot_free_during_sleep == [True]  # free during the one backoff window


def test_complete_with_slot_deterministic_error_raises_without_retry(monkeypatch):
    """A deterministic error (bad request / bad config) must raise on the
    first attempt, with no backoff sleep and no further attempts -- a retry
    would just burn another paid call and fail identically."""
    calls: list[int] = []

    class BadClient:
        def complete(self, system, user):
            calls.append(1)
            raise ValueError("400 bad request -- misconfigured model id")

    def fail_if_called(seconds):
        raise AssertionError("must not sleep on a deterministic error")

    monkeypatch.setattr(wiki_eval.time, "sleep", fail_if_called)
    semaphore = threading.Semaphore(1)

    with pytest.raises(ValueError):
        wiki_eval._complete_with_slot(
            BadClient(), "sys", "user", semaphore,
            attempts=wiki_eval.RESILIENT_ATTEMPTS, backoff=wiki_eval.RESILIENT_BACKOFF,
        )

    assert len(calls) == 1


def test_complete_with_slot_acquires_semaphore_once_per_attempt(monkeypatch):
    """Each retry attempt acquires+releases the slot on its own -- the slot is
    never held across the whole retry loop, only for the duration of each
    individual client.complete() call."""
    from palimpsest.llm.client import LLMResult, Usage

    acquire_count = [0]

    class CountingSemaphore:
        def __init__(self):
            self._sem = threading.Semaphore(4)

        def __enter__(self):
            self._sem.acquire()
            acquire_count[0] += 1
            return self

        def __exit__(self, *exc):
            self._sem.release()

    calls: list[int] = []

    class FlakyTwiceClient:
        def complete(self, system, user):
            calls.append(1)
            if len(calls) < 3:
                raise TimeoutError("transient")
            return LLMResult(content="ok", usage=Usage(1, 1, 0, 0.0))

    monkeypatch.setattr(wiki_eval.time, "sleep", lambda s: None)
    semaphore = CountingSemaphore()

    result = wiki_eval._complete_with_slot(
        FlakyTwiceClient(), "sys", "user", semaphore,
        attempts=wiki_eval.RESILIENT_ATTEMPTS, backoff=wiki_eval.RESILIENT_BACKOFF,
    )

    assert result.content == "ok"
    assert len(calls) == 3
    assert acquire_count[0] == 3  # acquired exactly once per attempt, not once total


# ── _build_judge / _build_extract_fn: resilient retries + judge tolerance ──


def _fake_llm_client_factory(*, always_raise=None, contents=None):
    """Builds a FakeLLMClient class for monkeypatching
    palimpsest.llm.client.LLMClient. Fakes ``.complete()`` (the bare,
    non-retrying network call) -- retries now loop over ``.complete()``
    inside wiki_eval's own ``_complete_with_slot`` helper, they are no longer
    delegated to ``client.complete_retrying`` (semaphore-starvation fix,
    2026-07-06). ``always_raise`` (if set) is raised on EVERY ``.complete()``
    call, simulating a route that keeps 429/503-flapping across every retry
    attempt. ``contents`` (if set) is a list of successive ``.content``
    values returned across calls, in order (one entry consumed per call)."""
    calls: list[dict] = []

    class FakeLLMClient:
        def __init__(self, config):
            self.config = config

        def complete(self, system, user):
            calls.append({"system": system, "user": user})
            if always_raise is not None:
                raise always_raise
            from palimpsest.llm.client import LLMResult, Usage
            content = contents[len(calls) - 1] if contents else "{}"
            return LLMResult(content=content, usage=Usage(10, 5, 0, 0.0001))

    return FakeLLMClient, calls


def test_build_judge_transient_exhausted_raises_and_counts(monkeypatch):
    """A judge call still TRANSIENT-failing after RESILIENT_ATTEMPTS retries
    must propagate unchanged (LabelFirstGrounding.ground() already treats ANY
    judge exception as terminal judge_unavailable) but must ALSO increment
    FailureTracker.n_failed_judge_calls -- otherwise a run could silently
    degrade with no owner-visible signal. Retries (and their backoff sleeps)
    now happen inside wiki_eval's own _complete_with_slot helper -- monkeypatch
    time.sleep so this test doesn't actually wait out 1+3+9+20+40s."""
    FakeLLMClient, calls = _fake_llm_client_factory(always_raise=TimeoutError("exhausted"))
    monkeypatch.setattr("palimpsest.llm.client.LLMClient", FakeLLMClient)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-not-a-secret")
    monkeypatch.setattr(wiki_eval.time, "sleep", lambda s: None)

    guard = wiki_eval.BudgetGuard(max_usd=1000.0)
    llm_semaphore = wiki_eval._CountingSemaphore(4)
    tracker = wiki_eval.FailureTracker()
    judge = wiki_eval._build_judge(guard, llm_semaphore, tracker=tracker)

    with pytest.raises(TimeoutError):
        judge("some judge prompt")

    assert tracker.n_failed_judge_calls == 1
    assert len(calls) == wiki_eval.RESILIENT_ATTEMPTS  # all 6 attempts exhausted, then raised


def test_build_judge_transient_exhausted_used_with_real_grounding_leaves_mention_unresolved():
    """Full call-boundary integration: when the judge closure raises after
    exhausting retries, LabelFirstGrounding.ground() -- unchanged, pre-existing
    contract -- resolves the mention as judge_unavailable/yellow with no
    grounded QID, i.e. the mention proceeds exactly as if judge were
    unavailable for it. This is why the judge-side fix needs no change at the
    grounding call boundary itself (see _build_judge's docstring)."""
    from palimpsest.terminology.base import GroundingConfig, TermMention
    from palimpsest.terminology.grounding.label_first import LabelFirstGrounding

    class _FakeWD:
        def __init__(self):
            self.n_calls = 0

        def search_entities(self, term, lang="ru", limit=7):
            return [{"id": "Q1"}, {"id": "Q2"}]  # ambiguous -> forces judge escalation

        def search_cirrus(self, term, limit=7):
            return []

        def wikipedia_wikibase_item(self, title, lang="ru"):
            return None

        def get_entities(self, qids, **kw):
            entities = {
                "Q1": {"id": "Q1", "labels": {"ru": {"value": "Тутмос"}}, "aliases": {},
                       "descriptions": {}, "claims": {}, "sitelinks": {}},
                "Q2": {"id": "Q2", "labels": {"ru": {"value": "Тутмос"}}, "aliases": {},
                       "descriptions": {}, "claims": {}, "sitelinks": {}},
            }
            return {q: entities[q] for q in qids if q in entities}

    def exhausted_judge(prompt):
        raise TimeoutError("simulated exhausted retries against a flapping route")

    strategy = LabelFirstGrounding(_FakeWD(), GroundingConfig())
    result = strategy.ground(TermMention(surface="Тутмос", lemma="Тутмос"), judge=exhausted_judge)

    assert result.difficulty == "yellow"
    assert result.trace["resolved_by"] == "judge_unavailable"
    assert result.grounded is None  # mention stays unresolved, not silently top-1'd


def test_build_judge_malformed_json_recovers_on_one_reask(monkeypatch):
    """Unparseable JSON on the first attempt gets exactly ONE corrective
    re-ask; if THAT succeeds, judge() returns normally and the tolerance
    counter stays untouched (this mention was fully resolved, no failure to
    report)."""
    FakeLLMClient, calls = _fake_llm_client_factory(
        contents=["not json at all", '{"qid": "Q1", "reason": "ok"}'],
    )
    monkeypatch.setattr("palimpsest.llm.client.LLMClient", FakeLLMClient)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-not-a-secret")

    guard = wiki_eval.BudgetGuard(max_usd=1000.0)
    llm_semaphore = wiki_eval._CountingSemaphore(4)
    tracker = wiki_eval.FailureTracker()
    judge = wiki_eval._build_judge(guard, llm_semaphore, tracker=tracker)

    result = judge("some judge prompt")

    assert result == {"qid": "Q1", "reason": "ok"}
    assert len(calls) == 2  # original + exactly one re-ask
    assert calls[1]["system"] == wiki_eval.JUDGE_REASK_SYSTEM_PROMPT
    assert tracker.n_failed_judge_calls == 0  # recovered -- not a tolerated failure


def test_build_judge_malformed_json_gives_up_after_one_reask_and_counts(monkeypatch):
    """If the re-ask ALSO fails to parse, judge() gives up: raises (so
    ground() falls back to judge_unavailable exactly as it already does for
    any judge exception) and counts it -- exactly ONE re-ask, never an
    unbounded retry loop."""
    import json

    FakeLLMClient, calls = _fake_llm_client_factory(contents=["not json", "still not json"])
    monkeypatch.setattr("palimpsest.llm.client.LLMClient", FakeLLMClient)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-not-a-secret")

    guard = wiki_eval.BudgetGuard(max_usd=1000.0)
    llm_semaphore = wiki_eval._CountingSemaphore(4)
    tracker = wiki_eval.FailureTracker()
    judge = wiki_eval._build_judge(guard, llm_semaphore, tracker=tracker)

    with pytest.raises(json.JSONDecodeError):
        judge("some judge prompt")

    assert len(calls) == 2  # original + exactly one re-ask, no more
    assert tracker.n_failed_judge_calls == 1


def test_build_judge_uses_resilient_attempts_and_backoff(monkeypatch):
    """Task requirement: judge closures retry up to RESILIENT_ATTEMPTS=6
    times with RESILIENT_BACKOFF=(1,3,9,20,40,60) sleeps between them -- long
    enough to ride out a multi-minute CloseRouter circuit-breaker window, not
    client.py's 3-attempt complete_retrying default. Retries are driven by
    wiki_eval's own _complete_with_slot helper (not delegated to
    complete_retrying, semaphore-starvation fix 2026-07-06), so this is now
    observed via the actual number of client.complete() calls and the
    recorded backoff sleep durations, not via kwargs passed to the client."""
    FakeLLMClient, calls = _fake_llm_client_factory(always_raise=TimeoutError("flapping"))
    monkeypatch.setattr("palimpsest.llm.client.LLMClient", FakeLLMClient)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-not-a-secret")
    sleeps: list[float] = []
    monkeypatch.setattr(wiki_eval.time, "sleep", lambda s: sleeps.append(s))

    guard = wiki_eval.BudgetGuard(max_usd=1000.0)
    llm_semaphore = wiki_eval._CountingSemaphore(4)
    judge = wiki_eval._build_judge(guard, llm_semaphore)

    with pytest.raises(TimeoutError):
        judge("prompt")

    assert wiki_eval.RESILIENT_BACKOFF == (1.0, 3.0, 9.0, 20.0, 40.0, 60.0)
    assert len(calls) == 6 == wiki_eval.RESILIENT_ATTEMPTS
    assert sleeps == list(wiki_eval.RESILIENT_BACKOFF[:5])  # 5 sleeps between 6 attempts


def test_build_extract_fn_uses_resilient_attempts_and_backoff(monkeypatch):
    """Same requirement as above, for the extraction closure."""
    FakeLLMClient, calls = _fake_llm_client_factory(always_raise=TimeoutError("flapping"))
    monkeypatch.setattr("palimpsest.llm.client.LLMClient", FakeLLMClient)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-not-a-secret")
    sleeps: list[float] = []
    monkeypatch.setattr(wiki_eval.time, "sleep", lambda s: sleeps.append(s))

    guard = wiki_eval.BudgetGuard(max_usd=1000.0)
    llm_semaphore = wiki_eval._CountingSemaphore(4)
    extract_fn = wiki_eval._build_extract_fn(guard, llm_semaphore)

    with pytest.raises(TimeoutError):
        extract_fn("some paragraph")

    assert wiki_eval.RESILIENT_BACKOFF == (1.0, 3.0, 9.0, 20.0, 40.0, 60.0)
    assert len(calls) == 6 == wiki_eval.RESILIENT_ATTEMPTS
    assert sleeps == list(wiki_eval.RESILIENT_BACKOFF[:5])


# ── meta.json counters wiring ────────────────────────────────────────────────


def test_run_one_config_surfaces_failure_counters_in_meta(monkeypatch, tmp_path):
    """n_failed_paragraphs/failed_paragraphs/n_failed_judge_calls must land in
    _run_one_config's returned counters dict (which cmd_run spreads straight
    into meta.json) -- this is the actual owner-visible surface for the loud
    accounting, not just an internal FailureTracker attribute."""
    captured: dict = {}

    def fake_build_judge(guard, sem, **kw):
        captured["tracker"] = kw.get("tracker")
        return None

    def fake_process_articles_parallel(articles, **kw):
        tracker = kw.get("tracker")
        tracker.record_failed_paragraph("Some Article", 4)
        tracker.record_failed_judge_call()
        return [], 0

    monkeypatch.setattr(wiki_eval, "_build_judge", fake_build_judge)
    monkeypatch.setattr(wiki_eval, "_build_extract_fn", lambda guard, sem, **kw: (lambda p: []))
    monkeypatch.setattr(wiki_eval, "_process_articles_parallel", fake_process_articles_parallel)
    monkeypatch.setattr(
        wiki_eval, "WikidataClient", lambda cache_path=None, network_concurrency=3: object(),
    )
    monkeypatch.setattr(wiki_eval, "_canonicalize_fn", lambda wd: (lambda q: q))

    guard = wiki_eval.BudgetGuard(max_usd=10.0)
    _, counters = wiki_eval._run_one_config("111", [], str(tmp_path), dry_run=False, guard=guard)

    assert counters["n_failed_paragraphs"] == 1
    assert counters["failed_paragraphs"] == [{"title": "Some Article", "paragraph_index": 4}]
    assert counters["n_failed_judge_calls"] == 1
    assert captured["tracker"] is not None  # the same FailureTracker instance was threaded through


# ── Checkpointer (per-article on-disk checkpointing) ────────────────────────
#
# Container-restart resilience patch: the container hosting long `run`
# invocations has been restarted twice in 1.5h, killing multi-hour runs --
# pred records were held only in memory and written to disk once at the very
# end, so every restart lost ALL paid LLM work. Checkpointer writes each
# completed article's records + a progress line immediately, so a killed
# container loses at most the article(s) in flight when it died.


def _read_jsonl(path: Path) -> list[dict]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def test_checkpointer_appends_partial_pred_and_progress_lines(tmp_path):
    guard = wiki_eval.BudgetGuard(max_usd=10.0)
    guard.spent = 1.25
    checkpoint = wiki_eval.Checkpointer(tmp_path, n_total=3, guard=guard)

    checkpoint.record("Article A", [{"title": "Article A", "index": 0, "qid": "Q1"}])
    guard.spent = 2.5
    checkpoint.record("Article B", [
        {"title": "Article B", "index": 0, "qid": "Q2"},
        {"title": "Article B", "index": 1, "qid": "Q3"},
    ])

    partial_lines = _read_jsonl(tmp_path / "pred.partial.jsonl")
    assert [r["title"] for r in partial_lines] == ["Article A", "Article B", "Article B"]

    progress_lines = _read_jsonl(tmp_path / "progress.jsonl")
    assert progress_lines == [
        {"article": "Article A", "done": 1, "of": 3, "spent": 1.25},
        {"article": "Article B", "done": 2, "of": 3, "spent": 2.5},
    ]


def test_checkpointer_seeds_n_done_from_resume_and_defaults_spent_without_guard(tmp_path):
    checkpoint = wiki_eval.Checkpointer(tmp_path, n_total=5, n_done=2)
    checkpoint.record("Article C", [{"title": "Article C"}])

    progress_lines = _read_jsonl(tmp_path / "progress.jsonl")
    assert progress_lines == [{"article": "Article C", "done": 3, "of": 5, "spent": 0.0}]


def test_checkpointer_thread_safe_under_concurrent_article_completion(tmp_path):
    """Hammer record() from many threads at once (mirroring several article
    workers finishing back-to-back) -- no lost writes, no scrambled `done`
    counter."""
    checkpoint = wiki_eval.Checkpointer(tmp_path, n_total=20)
    titles = [f"Article {i}" for i in range(20)]

    threads = [threading.Thread(target=checkpoint.record, args=(t, [{"title": t}])) for t in titles]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    partial_lines = _read_jsonl(tmp_path / "pred.partial.jsonl")
    assert sorted(r["title"] for r in partial_lines) == sorted(titles)

    progress_lines = _read_jsonl(tmp_path / "progress.jsonl")
    # every increment landed exactly once, none lost or duplicated
    assert sorted(p["done"] for p in progress_lines) == list(range(1, 21))


# ── _process_articles_parallel: checkpoint wiring ───────────────────────────


def test_process_articles_parallel_checkpoints_each_completed_article():
    """checkpoint.record must fire once per completed article, from inside
    process_one (the completing worker thread) -- this is what makes on-disk
    progress reflect real completion order rather than pool.map's
    submission-order yield."""
    recorded: list[tuple[str, list[dict]]] = []
    lock = threading.Lock()

    class FakeCheckpoint:
        def record(self, title, records):
            with lock:
                recorded.append((title, records))

    def fake_predict_tuples(article_text, paragraphs, extract_fn, ground_fn, *,
                             judge, judge_cache, scope_id, canonicalize):
        return {
            "tuples": [],
            "records": [{"index": 0, "surface": scope_id, "lemma": None,
                          "qid": "Q1", "span_len": 1, "resolved_by": "exact_label"}],
        }

    original = wiki_eval.predict.predict_tuples
    wiki_eval.predict.predict_tuples = fake_predict_tuples
    try:
        articles = [(t, ["p1"], "p1") for t in ("a", "b", "c")]
        pred_records, _ = wiki_eval._process_articles_parallel(
            articles, article_workers=3, extract_fn=lambda p: [], judge=None,
            canonicalize=lambda q: q, wd=None,
            config=wiki_eval._config_from_bits("111"), guard=None,
            checkpoint=FakeCheckpoint(),
        )
    finally:
        wiki_eval.predict.predict_tuples = original

    assert sorted(t for t, _ in recorded) == ["a", "b", "c"]
    for title, records in recorded:
        assert [r["title"] for r in records] == [title]
    assert len(pred_records) == 3


def test_process_articles_parallel_without_checkpoint_is_unaffected():
    """checkpoint=None (default) must not attempt any I/O -- every
    pre-existing caller/test of this function keeps working unchanged."""

    def fake_predict_tuples(article_text, paragraphs, extract_fn, ground_fn, *,
                             judge, judge_cache, scope_id, canonicalize):
        return {"tuples": [], "records": []}

    original = wiki_eval.predict.predict_tuples
    wiki_eval.predict.predict_tuples = fake_predict_tuples
    try:
        pred_records, n = wiki_eval._process_articles_parallel(
            [("a", ["p1"], "p1")], article_workers=1, extract_fn=lambda p: [], judge=None,
            canonicalize=lambda q: q, wd=None,
            config=wiki_eval._config_from_bits("111"), guard=None,
        )
    finally:
        wiki_eval.predict.predict_tuples = original
    assert pred_records == []
    assert n == 1


# ── _run_one_config: out_dir/skip_titles/n_done_start wiring ────────────────


def test_run_one_config_builds_checkpoint_from_out_dir_and_seeds_n_done(monkeypatch, tmp_path):
    captured: dict = {}

    def fake_process_articles_parallel(articles, **kw):
        captured["checkpoint"] = kw.get("checkpoint")
        captured["n_articles_seen"] = len(articles)
        return [], 0

    monkeypatch.setattr(wiki_eval, "_build_judge", lambda guard, sem, **kw: None)
    monkeypatch.setattr(wiki_eval, "_build_extract_fn", lambda guard, sem, **kw: (lambda p: []))
    monkeypatch.setattr(wiki_eval, "_process_articles_parallel", fake_process_articles_parallel)
    monkeypatch.setattr(
        wiki_eval, "WikidataClient", lambda cache_path=None, network_concurrency=3: object(),
    )
    monkeypatch.setattr(wiki_eval, "_canonicalize_fn", lambda wd: (lambda q: q))

    guard = wiki_eval.BudgetGuard(max_usd=10.0)
    wiki_eval._run_one_config(
        "111", [{"title": "A"}, {"title": "B"}], str(tmp_path), dry_run=False, guard=guard,
        out_dir=tmp_path, skip_titles=frozenset({"A"}), n_done_start=1,
    )

    checkpoint = captured["checkpoint"]
    assert isinstance(checkpoint, wiki_eval.Checkpointer)
    assert checkpoint.n_total == 2  # full gt_records count, not just the remaining article
    assert checkpoint.n_done == 1  # seeded from n_done_start
    assert captured["n_articles_seen"] == 0  # "A" has no cached HTML, also skip_titles-filtered


def test_run_one_config_without_out_dir_builds_no_checkpoint(monkeypatch, tmp_path):
    captured: dict = {}

    def fake_process_articles_parallel(articles, **kw):
        captured["checkpoint"] = kw.get("checkpoint")
        return [], 0

    monkeypatch.setattr(wiki_eval, "_build_judge", lambda guard, sem, **kw: None)
    monkeypatch.setattr(wiki_eval, "_build_extract_fn", lambda guard, sem, **kw: (lambda p: []))
    monkeypatch.setattr(wiki_eval, "_process_articles_parallel", fake_process_articles_parallel)
    monkeypatch.setattr(
        wiki_eval, "WikidataClient", lambda cache_path=None, network_concurrency=3: object(),
    )
    monkeypatch.setattr(wiki_eval, "_canonicalize_fn", lambda wd: (lambda q: q))

    guard = wiki_eval.BudgetGuard(max_usd=10.0)
    wiki_eval._run_one_config("111", [], str(tmp_path), dry_run=False, guard=guard)
    assert captured["checkpoint"] is None


def test_run_one_config_skip_titles_excludes_articles_with_cached_html(monkeypatch, tmp_path):
    """skip_titles must filter BEFORE the html-cache-existence check -- an
    already-checkpointed article must never be reprocessed (re-billed) even
    though its cached HTML is still present on disk."""
    done_html = tmp_path / f"{wiki_eval.wiki_gt._safe_filename('Done Article')}.html"
    new_html = tmp_path / f"{wiki_eval.wiki_gt._safe_filename('New Article')}.html"
    done_html.write_text("<p>x</p>", encoding="utf-8")
    new_html.write_text("<p>y</p>", encoding="utf-8")

    captured: dict = {}

    def fake_process_articles_parallel(articles, **kw):
        captured["titles"] = [a[0] for a in articles]
        return [], 0

    monkeypatch.setattr(wiki_eval, "_build_judge", lambda guard, sem, **kw: None)
    monkeypatch.setattr(wiki_eval, "_build_extract_fn", lambda guard, sem, **kw: (lambda p: []))
    monkeypatch.setattr(wiki_eval, "_process_articles_parallel", fake_process_articles_parallel)
    monkeypatch.setattr(
        wiki_eval, "WikidataClient", lambda cache_path=None, network_concurrency=3: object(),
    )
    monkeypatch.setattr(wiki_eval, "_canonicalize_fn", lambda wd: (lambda q: q))

    guard = wiki_eval.BudgetGuard(max_usd=10.0)
    wiki_eval._run_one_config(
        "111", [{"title": "Done Article"}, {"title": "New Article"}], str(tmp_path),
        dry_run=False, guard=guard, out_dir=tmp_path, skip_titles=frozenset({"Done Article"}),
    )
    assert captured["titles"] == ["New Article"]


# ── cmd_run: checkpoint dir-at-start + --resume ─────────────────────────────


def _write_gt_jsonl(path: Path, titles: list[str]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for t in titles:
            rec = {"title": t, "gt_tuples": [], "stratum": "typical"}
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _fake_counters() -> dict:
    return {
        "n_articles": 2, "n_paragraphs": 2, "n_pred_mentions": 2,
        "llm_max_in_flight_observed": 1, "n_failed_paragraphs": 0,
        "failed_paragraphs": [], "n_failed_judge_calls": 0,
    }


def test_cmd_run_creates_out_dir_before_processing_and_deletes_partial(monkeypatch, tmp_path):
    gt_path = tmp_path / "gt.jsonl"
    _write_gt_jsonl(gt_path, ["Article A", "Article B"])

    captured: dict = {}

    def fake_run_one_config(config, gt_records, cache, *, dry_run, guard, **kw):
        out_dir = Path(kw["out_dir"])
        captured["out_dir_existed_during_call"] = out_dir.is_dir()
        # Simulate a partial file left behind by checkpointing mid-run.
        (out_dir / "pred.partial.jsonl").write_text(
            json.dumps({"title": "Article A", "index": 0, "qid": "Q1"}) + "\n", encoding="utf-8",
        )
        records = [
            {"title": "Article A", "index": 0, "qid": "Q1"},
            {"title": "Article B", "index": 0, "qid": "Q2"},
        ]
        return records, _fake_counters()

    monkeypatch.setattr(wiki_eval, "_run_one_config", fake_run_one_config)
    monkeypatch.setattr(wiki_eval, "OUT_ROOT", tmp_path / "out")

    args = wiki_eval._build_parser().parse_args(["run", "--gt", str(gt_path), "--max-usd", "5"])
    rc = wiki_eval.cmd_run(args)

    assert rc == 0
    assert captured["out_dir_existed_during_call"] is True  # run dir created at START, not the end

    out_dirs = list((tmp_path / "out").glob("*/*/*"))
    assert len(out_dirs) == 1
    out_dir = out_dirs[0]
    assert (out_dir / "pred.jsonl").exists()
    assert (out_dir / "meta.json").exists()
    assert not (out_dir / "pred.partial.jsonl").exists()  # deleted on clean completion

    meta = json.loads((out_dir / "meta.json").read_text(encoding="utf-8"))
    assert "resumed_from_n_articles" not in meta  # fresh run, --resume not used


def test_cmd_run_resume_skips_done_titles_seeds_guard_and_merges(monkeypatch, tmp_path):
    gt_path = tmp_path / "gt.jsonl"
    _write_gt_jsonl(gt_path, ["Article A", "Article B"])

    resume_dir = tmp_path / "prior_run"
    resume_dir.mkdir()
    (resume_dir / "pred.partial.jsonl").write_text(
        json.dumps({"title": "Article A", "index": 0, "qid": "Q1"}) + "\n", encoding="utf-8",
    )
    progress_line = {"article": "Article A", "done": 1, "of": 2, "spent": 3.5}
    (resume_dir / "progress.jsonl").write_text(json.dumps(progress_line) + "\n", encoding="utf-8")

    captured: dict = {}

    def fake_run_one_config(config, gt_records, cache, *, dry_run, guard, **kw):
        captured["skip_titles"] = kw["skip_titles"]
        captured["n_done_start"] = kw["n_done_start"]
        captured["guard_spent_at_call"] = guard.spent
        captured["out_dir"] = Path(kw["out_dir"])
        new_record = {"title": "Article B", "index": 0, "qid": "Q2"}
        return [new_record], _fake_counters()

    monkeypatch.setattr(wiki_eval, "_run_one_config", fake_run_one_config)

    args = wiki_eval._build_parser().parse_args([
        "run", "--gt", str(gt_path), "--resume", str(resume_dir), "--max-usd", "5",
    ])
    rc = wiki_eval.cmd_run(args)

    assert rc == 0
    assert captured["skip_titles"] == frozenset({"Article A"})
    assert captured["n_done_start"] == 1
    assert captured["guard_spent_at_call"] == 3.5  # seeded from progress.jsonl's last line
    assert captured["out_dir"] == resume_dir  # reused, not a fresh OUT_ROOT path

    assert (resume_dir / "pred.jsonl").exists()
    pred_records = _read_jsonl(resume_dir / "pred.jsonl")
    assert [r["title"] for r in pred_records] == ["Article A", "Article B"]  # merged, gt order

    assert not (resume_dir / "pred.partial.jsonl").exists()  # deleted on clean completion

    meta = json.loads((resume_dir / "meta.json").read_text(encoding="utf-8"))
    assert meta["resumed_from_n_articles"] == 1
    assert meta["run_id"] == resume_dir.name  # run_id reused, not a fresh timestamp


def test_cmd_run_resume_without_prior_partial_file_behaves_like_fresh_run(monkeypatch, tmp_path):
    """--resume pointing at a dir with no pred.partial.jsonl yet (e.g. the
    very first article hadn't finished before the restart) must not crash --
    it degenerates to processing every article, same as a fresh run, just
    reusing the given dir/run_id."""
    gt_path = tmp_path / "gt.jsonl"
    _write_gt_jsonl(gt_path, ["Article A"])

    resume_dir = tmp_path / "prior_run_empty"
    resume_dir.mkdir()

    captured: dict = {}

    def fake_run_one_config(config, gt_records, cache, *, dry_run, guard, **kw):
        captured["skip_titles"] = kw["skip_titles"]
        captured["n_done_start"] = kw["n_done_start"]
        return [{"title": "Article A", "index": 0, "qid": "Q1"}], _fake_counters()

    monkeypatch.setattr(wiki_eval, "_run_one_config", fake_run_one_config)

    args = wiki_eval._build_parser().parse_args([
        "run", "--gt", str(gt_path), "--resume", str(resume_dir),
    ])
    rc = wiki_eval.cmd_run(args)

    assert rc == 0
    assert captured["skip_titles"] == frozenset()
    assert captured["n_done_start"] == 0
    meta = json.loads((resume_dir / "meta.json").read_text(encoding="utf-8"))
    assert meta["resumed_from_n_articles"] == 0  # --resume was used, just with nothing done yet


def test_cli_run_resume_flag_default_and_value():
    args = wiki_eval._build_parser().parse_args(["run"])
    assert args.resume is None

    args2 = wiki_eval._build_parser().parse_args(["run", "--resume", "/tmp/some-run-dir"])
    assert args2.resume == "/tmp/some-run-dir"
