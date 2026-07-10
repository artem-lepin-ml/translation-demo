"""Tests for scripts/wiki_eval.py's runner pieces: model_slug, BudgetGuard's
thread-safe extract/judge split accounting, `_resolve_route`'s standard-
OpenRouter route resolution (spec 2026-07-10-wiki-eval-experiment-v2.md
§4.1/Р2/Р3/Р13/Р14), the per-call gates (`_gate_reply`, Р15/Р13/Р14) and
`CallLogger` (Р8), and CLI parsing. Also covers ticket 002b (article-level
parallelism): `_process_articles_parallel`'s order-preserving article
dispatch, the process-wide `llm_semaphore` bound shared by
`_build_extract_fn`/`_build_judge`, and `_canonicalize_fn`'s thread-safe
cache.

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


def test_model_slug_sanitizes_spaces_in_provider_display_name():
    """OpenRouter provider pins are display names that may contain spaces
    (spec Р14, e.g. "Google AI Studio") -- the slug must stay one filesystem
    path segment."""
    slug = wiki_eval.model_slug("google/gemini-3.1-flash-lite", "Google AI Studio")
    assert slug == "google--gemini-3.1-flash-lite--Google-AI-Studio"
    assert " " not in slug


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


# ── _resolve_route (standard OpenRouter, spec 2026-07-10 §4.1) ─────────────


def test_resolve_route_defaults_to_default_model_and_base_url():
    route = wiki_eval._resolve_route()
    assert route["model"] == wiki_eval.DEFAULT_MODEL
    assert route["base_url"] == wiki_eval.DEFAULT_BASE_URL
    assert route["api_key_env"] == "OPENROUTER_API_KEY"
    assert route["max_tokens"] == wiki_eval.DEFAULT_MAX_TOKENS == 20000


def test_resolve_route_returns_one_dict_for_both_roles():
    """Unlike the retired CloseRouter three-branch design, there is no
    extract_*/judge_* key split -- one route serves both roles (spec §4.1)."""
    route = wiki_eval._resolve_route("openai/gpt-5.5", "provider-3")
    assert route["model"] == "openai/gpt-5.5"
    assert route["extra_body"]["provider"] == {"order": ["provider-3"], "allow_fallbacks": False}


@pytest.mark.parametrize("model,expected", [
    ("deepseek/deepseek-v4-flash", {"temperature": 1.0, "top_p": 1.0, "provider_pin": "Novita"}),
    ("google/gemini-3.1-flash-lite", {"temperature": 1.0, "top_p": None, "provider_pin": "Google AI Studio"}),
    ("google/gemma-4-31b-it", {"temperature": 1.0, "top_p": 0.95, "provider_pin": "WandB"}),
])
def test_resolve_route_model_params_defaults_land_in_route(model, expected):
    """MODEL_PARAMS' vendor-recommended sampling + pin lands in the route
    when no CLI override is given (spec Р3/Р14)."""
    route = wiki_eval._resolve_route(model)
    assert route["temperature"] == expected["temperature"]
    assert route["top_p"] == expected["top_p"]
    assert route["provider_pin"] == expected["provider_pin"]
    assert route["expect_reasoning"] is True  # all three known models have reasoning ON (Р13)


def test_resolve_route_gemma_top_k_lands_in_extra_body():
    route = wiki_eval._resolve_route("google/gemma-4-31b-it")
    assert route["extra_body"]["top_k"] == 64


def test_resolve_route_deepseek_reasoning_enabled_form():
    route = wiki_eval._resolve_route("deepseek/deepseek-v4-flash")
    assert route["extra_body"]["reasoning"] == {"enabled": True}


def test_resolve_route_gemini_reasoning_effort_form_not_enabled():
    """gemini needs the {"effort": ...} shape -- {"enabled": true} silently
    yields reasoning_tokens=0 on gemini (probed 2026-07-10, spec Р13)."""
    route = wiki_eval._resolve_route("google/gemini-3.1-flash-lite")
    assert route["extra_body"]["reasoning"] == {"effort": "medium"}


def test_resolve_route_cli_overrides_win_over_model_params():
    route = wiki_eval._resolve_route(
        "deepseek/deepseek-v4-flash", "Novita",
        temperature=0.3, top_p=0.5, top_k=10, max_tokens=5000,
    )
    assert route["temperature"] == 0.3
    assert route["top_p"] == 0.5
    assert route["extra_body"]["top_k"] == 10
    assert route["max_tokens"] == 5000


def test_resolve_route_unknown_model_has_no_vendor_defaults():
    route = wiki_eval._resolve_route("some/unknown-model")
    assert route["temperature"] is None
    assert route["top_p"] is None
    assert route["provider_pin"] is None
    assert route["expect_reasoning"] is False
    assert route["max_tokens"] == wiki_eval.DEFAULT_MAX_TOKENS  # still defaults, unlike sampling


def test_resolve_route_auto_provider_disables_pin_and_gate():
    """"auto" disables both the provider-pin default AND the served-by gate
    (no "provider" key -> provider_pin=None -> _gate_reply skips it)."""
    route = wiki_eval._resolve_route("deepseek/deepseek-v4-flash", "auto")
    assert route["provider_pin"] is None
    assert "provider" not in route["extra_body"]


def test_resolve_route_explicit_provider_overrides_model_params_pin():
    route = wiki_eval._resolve_route("deepseek/deepseek-v4-flash", "GMICloud")
    assert route["provider_pin"] == "GMICloud"
    assert route["extra_body"]["provider"] == {"order": ["GMICloud"], "allow_fallbacks": False}


def test_resolve_route_custom_base_url_omits_usage_include():
    """usage.include is an OpenRouter-only default (spec: "OR only returns
    usage.cost when asked") -- a local vLLM base_url must not get it."""
    route = wiki_eval._resolve_route("Qwen/Qwen3.6-27B", base_url="http://localhost:8000/v1")
    assert "usage" not in route["extra_body"]
    assert route["base_url"] == "http://localhost:8000/v1"


def test_resolve_route_extra_body_per_key_merge_preserves_provider_pin():
    """finding 4 regression: a CLI --extra-body that sets an UNRELATED key
    must not silently drop the computed provider pin -- the merge is
    per-key, not a wholesale replace."""
    route = wiki_eval._resolve_route(
        "deepseek/deepseek-v4-flash", extra_body={"some_unrelated_key": 123},
    )
    assert route["extra_body"]["provider"] == {"order": ["Novita"], "allow_fallbacks": False}
    assert route["extra_body"]["some_unrelated_key"] == 123
    assert route["provider_pin"] == "Novita"


def test_resolve_route_explicit_extra_body_provider_key_wins_and_regates():
    """An explicit --extra-body "provider" key REPLACES the computed default
    entirely (top-level per-key merge) -- and the served-by gate is read
    back from the EFFECTIVE body, so it gates against the CLI override, not
    the pre-merge MODEL_PARAMS pin (spec §4.1, finding 4 regression note)."""
    route = wiki_eval._resolve_route(
        "deepseek/deepseek-v4-flash",
        extra_body={"provider": {"order": ["SomeOtherProvider"], "allow_fallbacks": True}},
    )
    assert route["extra_body"]["provider"] == {"order": ["SomeOtherProvider"], "allow_fallbacks": True}
    assert route["provider_pin"] == "SomeOtherProvider"


def test_resolve_route_extra_body_local_vllm_thinking_toggle():
    """sr004 local-judge patch (2026-07-09): a local vLLM thinking-capable
    model still needs chat_template_kwargs.enable_thinking set explicitly --
    merged alongside whatever defaults apply (here: none, unknown model on a
    non-OpenRouter base_url so usage.include isn't added either)."""
    route = wiki_eval._resolve_route(
        "Qwen/Qwen3.6-27B", "auto", base_url="http://localhost:8000/v1",
        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
    )
    assert route["extra_body"] == {"chat_template_kwargs": {"enable_thinking": False}}


def test_resolve_route_expect_reasoning_reflects_effective_extra_body():
    assert wiki_eval._resolve_route("google/gemini-3.1-flash-lite")["expect_reasoning"] is True
    assert wiki_eval._resolve_route("some/unknown-model")["expect_reasoning"] is False


# ── 2026-07-10 amendment: gemma-3-27b-it/qwen3.6-27b added to MODEL_PARAMS
# (OpenRouter routing, owner-authorized per docs/superpowers/specs/
# 2026-07-10-wiki-eval-experiment-v2.md Р1/Р14 amendment) ──────────────────

def test_resolve_route_gemma_3_27b_it_model_params_defaults():
    route = wiki_eval._resolve_route("google/gemma-3-27b-it")
    assert route["temperature"] == 1.0
    assert route["top_p"] == 0.95
    assert route["extra_body"]["top_k"] == 64
    assert route["provider_pin"] == "DeepInfra"
    # Not a reasoning/thinking model -- no "reasoning" key sent at all.
    assert "reasoning" not in route["extra_body"]
    assert route["expect_reasoning"] is False


def test_resolve_route_qwen3_6_27b_model_params_defaults():
    route = wiki_eval._resolve_route("qwen/qwen3.6-27b")
    assert route["temperature"] == 1.0
    assert route["provider_pin"] == "Io Net"
    assert route["extra_body"]["reasoning"] == {"enabled": False}


def test_resolve_route_reasoning_explicitly_disabled_does_not_expect_ignition():
    """qwen3.6-27b's reasoning:{"enabled": False} must NOT set
    expect_reasoning=True -- reasoning_tokens=0 is the correct, intended
    outcome for an explicit off-request, not a Р13 gate violation (unlike
    deepseek/gemini/gemma-4-31b-it's reasoning-ON pins, which DO still expect
    ignition -- see test_resolve_route_model_params_defaults_land_in_route)."""
    route = wiki_eval._resolve_route("qwen/qwen3.6-27b")
    assert route["expect_reasoning"] is False

    # Same holds for an ad-hoc CLI --extra-body reasoning-off override on any
    # model, not just the one MODEL_PARAMS entry that happens to use it.
    route2 = wiki_eval._resolve_route(
        "deepseek/deepseek-v4-flash", extra_body={"reasoning": {"enabled": False}},
    )
    assert route2["extra_body"]["reasoning"] == {"enabled": False}
    assert route2["expect_reasoning"] is False


# ── exception hierarchy (spec Р15) ──────────────────────────────────────────


def test_fatal_error_classes_are_fatal_grounding_judge_error_subclasses():
    from palimpsest.terminology.base import FatalGroundingJudgeError

    for cls in (wiki_eval.LengthOverflowError, wiki_eval.CallGateError, wiki_eval.BudgetExhaustedError):
        assert issubclass(cls, FatalGroundingJudgeError)


# ── _gate_reply (spec Р15/Р13/Р14 §4.1.4) ───────────────────────────────────


def _reply(*, content="ok", finish_reason=None, reasoning_tokens=5, provider=None):
    from palimpsest.llm.client import LLMResult, Usage

    return LLMResult(
        content=content, finish_reason=finish_reason, provider=provider,
        usage=Usage(prompt_tokens=10, completion_tokens=5, reasoning_tokens=reasoning_tokens, cost_usd=0.0001),
    )


def test_gate_reply_finish_reason_length_raises_length_overflow():
    reply = _reply(finish_reason="length")
    with pytest.raises(wiki_eval.LengthOverflowError):
        wiki_eval._gate_reply(reply, kind="extract", model="m", pin=None,
                               expect_reasoning=False, context="ctx")


def test_gate_reply_empty_content_with_reasoning_tokens_raises_length_overflow():
    """finish_reason may be None/"stop" from some providers even when the
    reasoning budget silently ate the whole completion -- the empty-content+
    positive-reasoning-tokens combination is caught independently of
    finish_reason (spec Р15)."""
    reply = _reply(content="   ", finish_reason="stop", reasoning_tokens=20000)
    with pytest.raises(wiki_eval.LengthOverflowError):
        wiki_eval._gate_reply(reply, kind="judge", model="m", pin=None,
                               expect_reasoning=False, context="ctx")


def test_gate_reply_length_overflow_message_carries_diagnostics():
    reply = _reply(finish_reason="length")
    with pytest.raises(wiki_eval.LengthOverflowError) as exc_info:
        wiki_eval._gate_reply(reply, kind="extract", model="my/model", pin=None,
                               expect_reasoning=False, context="paragraph_len=42")
    msg = str(exc_info.value)
    assert "my/model" in msg and "extract" in msg and "paragraph_len=42" in msg
    assert "prompt_tokens=10" in msg and "reasoning_tokens=5" in msg


def test_gate_reply_expect_reasoning_true_and_zero_tokens_raises_call_gate_error():
    reply = _reply(reasoning_tokens=0)
    with pytest.raises(wiki_eval.CallGateError):
        wiki_eval._gate_reply(reply, kind="judge", model="m", pin=None,
                               expect_reasoning=True, context="ctx")


def test_gate_reply_expect_reasoning_true_and_nonzero_tokens_passes():
    reply = _reply(reasoning_tokens=3)
    wiki_eval._gate_reply(reply, kind="judge", model="m", pin=None,
                           expect_reasoning=True, context="ctx")  # no raise


def test_gate_reply_provider_mismatch_raises_call_gate_error():
    reply = _reply(provider="SomeOtherProvider")
    with pytest.raises(wiki_eval.CallGateError):
        wiki_eval._gate_reply(reply, kind="extract", model="m", pin="Novita",
                               expect_reasoning=False, context="ctx")


def test_gate_reply_provider_match_case_and_whitespace_insensitive():
    reply = _reply(provider=" novita ")
    wiki_eval._gate_reply(reply, kind="extract", model="m", pin="Novita",
                           expect_reasoning=False, context="ctx")  # no raise


def test_gate_reply_provider_none_skips_pin_gate():
    """A local vLLM server never sets LLMResult.provider -- the pin gate must
    be skipped entirely (not treated as a mismatch) so local runs stay
    ungated."""
    reply = _reply(provider=None)
    wiki_eval._gate_reply(reply, kind="extract", model="m", pin="Novita",
                           expect_reasoning=False, context="ctx")  # no raise


def test_gate_reply_reasoning_explicitly_off_and_zero_tokens_passes():
    """2026-07-10 qwen3.6-27b amendment: expect_reasoning=False (as
    _resolve_route now correctly computes for an explicit reasoning-off
    request, see test_resolve_route_reasoning_explicitly_disabled_does_not_
    expect_ignition) must not raise even though reasoning_tokens == 0 --
    that's the correct, intended outcome for a deliberate off-request, not a
    Р13 gate violation."""
    reply = _reply(reasoning_tokens=0)
    wiki_eval._gate_reply(reply, kind="extract", model="qwen/qwen3.6-27b", pin="Io Net",
                           expect_reasoning=False, context="ctx")  # no raise


def test_gate_reply_pin_none_skips_pin_gate_regardless_of_provider():
    reply = _reply(provider="AnythingAtAll")
    wiki_eval._gate_reply(reply, kind="extract", model="m", pin=None,
                           expect_reasoning=False, context="ctx")  # no raise


def test_gate_reply_all_gates_pass_on_a_clean_reply():
    reply = _reply(content="fine", finish_reason="stop", reasoning_tokens=7, provider="Novita")
    wiki_eval._gate_reply(reply, kind="judge", model="m", pin="Novita",
                           expect_reasoning=True, context="ctx")  # no raise


# ── CallLogger (spec Р8) ─────────────────────────────────────────────────────


def test_call_logger_writes_one_line_per_call_with_expected_keys(tmp_path):
    logger = wiki_eval.CallLogger(tmp_path)
    reply = _reply(content="hello", finish_reason="stop", reasoning_tokens=12, provider="Novita")
    logger.log(reply, kind="extract", model="deepseek/deepseek-v4-flash", latency_ms=123.456)

    lines = _read_jsonl(tmp_path / "calls.jsonl")
    assert len(lines) == 1
    line = lines[0]
    assert set(line) == {
        "ts", "kind", "model", "provider", "finish_reason", "prompt_tokens",
        "completion_tokens", "reasoning_tokens", "cost_usd", "latency_ms", "content_len",
    }
    assert line["kind"] == "extract"
    assert line["model"] == "deepseek/deepseek-v4-flash"
    assert line["provider"] == "Novita"
    assert line["finish_reason"] == "stop"
    assert line["prompt_tokens"] == 10
    assert line["completion_tokens"] == 5
    assert line["reasoning_tokens"] == 12
    assert line["cost_usd"] == pytest.approx(0.0001)
    assert line["latency_ms"] == pytest.approx(123.5, abs=0.1)
    assert line["content_len"] == len("hello")


def test_call_logger_appends_multiple_calls_in_order(tmp_path):
    logger = wiki_eval.CallLogger(tmp_path)
    logger.log(_reply(content="a"), kind="extract", model="m", latency_ms=1.0)
    logger.log(_reply(content="bb"), kind="judge", model="m", latency_ms=2.0)
    logger.log(_reply(content="ccc"), kind="judge_reask", model="m", latency_ms=3.0)

    lines = _read_jsonl(tmp_path / "calls.jsonl")
    assert [l["kind"] for l in lines] == ["extract", "judge", "judge_reask"]
    assert [l["content_len"] for l in lines] == [1, 2, 3]


def test_call_logger_thread_safe_under_concurrent_logging(tmp_path):
    logger = wiki_eval.CallLogger(tmp_path)
    n = 40

    def worker(i: int) -> None:
        logger.log(_reply(content=f"reply-{i}"), kind="extract", model="m", latency_ms=1.0)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    lines = _read_jsonl(tmp_path / "calls.jsonl")
    assert len(lines) == n  # no lost/corrupted writes under concurrency


# ── CLI parsing ──────────────────────────────────────────────────────────


def test_cli_run_defaults():
    args = wiki_eval._build_parser().parse_args(["run"])
    assert args.model == wiki_eval.DEFAULT_MODEL
    assert args.provider is None
    assert args.base_url is None
    assert args.temperature is None
    assert args.top_p is None
    assert args.top_k is None
    assert args.max_tokens is None
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


def test_cli_run_sampling_and_transport_flags():
    args = wiki_eval._build_parser().parse_args([
        "run", "--temperature", "0.3", "--top-p", "0.5", "--top-k", "10",
        "--max-tokens", "5000", "--base-url", "http://localhost:8000/v1",
    ])
    assert args.temperature == 0.3
    assert args.top_p == 0.5
    assert args.top_k == 10
    assert args.max_tokens == 5000
    assert args.base_url == "http://localhost:8000/v1"


def test_cli_ablate_sampling_and_transport_flags():
    args = wiki_eval._build_parser().parse_args([
        "ablate", "--temperature", "1.0", "--top-p", "0.95", "--top-k", "64",
        "--max-tokens", "20000", "--base-url", "http://localhost:8000/v1",
    ])
    assert args.temperature == 1.0
    assert args.top_p == 0.95
    assert args.top_k == 64
    assert args.max_tokens == 20000
    assert args.base_url == "http://localhost:8000/v1"


def test_cli_run_dry_run_flag():
    args = wiki_eval._build_parser().parse_args(["run", "--dry-run"])
    assert args.dry_run is True


def test_cli_run_extra_body_default_and_override():
    args = wiki_eval._build_parser().parse_args(["run"])
    assert args.extra_body is None

    args2 = wiki_eval._build_parser().parse_args([
        "run", "--extra-body", '{"chat_template_kwargs": {"enable_thinking": false}}',
    ])
    assert args2.extra_body == '{"chat_template_kwargs": {"enable_thinking": false}}'


def test_cli_ablate_extra_body_default_and_override():
    args = wiki_eval._build_parser().parse_args(["ablate"])
    assert args.extra_body is None

    args2 = wiki_eval._build_parser().parse_args(["ablate", "--extra-body", '{"a": 1}'])
    assert args2.extra_body == '{"a": 1}'


def test_parse_extra_body_none_when_flag_absent():
    assert wiki_eval._parse_extra_body(None) is None


def test_parse_extra_body_parses_json_object_string():
    assert wiki_eval._parse_extra_body('{"chat_template_kwargs": {"enable_thinking": false}}') == {
        "chat_template_kwargs": {"enable_thinking": False},
    }


def test_cli_ablate_defaults():
    args = wiki_eval._build_parser().parse_args(["ablate"])
    assert args.model == wiki_eval.DEFAULT_MODEL
    assert args.provider is None


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
        judge calls (any judge system prompt) from extract calls (the fixed
        NER_SYSTEM_PROMPT) to return shaped-appropriately content for each --
        both extraction and judge now send a non-empty system prompt (spec
        Р5/Р7), so the old "truthy system = judge" heuristic no longer
        applies. reasoning_tokens=5 (nonzero) on both so the default model's
        expect_reasoning gate (Р13) doesn't trip -- this test is about
        semaphore concurrency, not the gate."""

        def __init__(self, config):
            self.config = config

        def complete(self, system, user):
            with lock:
                in_flight[0] += 1
                max_in_flight[0] = max(max_in_flight[0], in_flight[0])
            time.sleep(0.03)
            with lock:
                in_flight[0] -= 1
            if system == wiki_eval.NER_SYSTEM_PROMPT:  # extract call
                return LLMResult(content="[]", usage=Usage(10, 5, 5, 0.0001))
            return LLMResult(content='{"qid": null, "reason": "no match"}',
                              usage=Usage(10, 5, 5, 0.0001))  # judge call

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


# ── _run_one_config wiring for CallLogger (spec Р8) ─────────────────────────


def test_run_one_config_builds_call_logger_when_out_dir_given(monkeypatch, tmp_path):
    captured: dict = {}

    def fake_build_judge(guard, sem, **kw):
        captured["judge_call_logger"] = kw.get("call_logger")
        return None

    def fake_build_extract_fn(guard, sem, **kw):
        captured["extract_call_logger"] = kw.get("call_logger")
        return lambda p: []

    monkeypatch.setattr(wiki_eval, "_build_judge", fake_build_judge)
    monkeypatch.setattr(wiki_eval, "_build_extract_fn", fake_build_extract_fn)
    monkeypatch.setattr(wiki_eval, "_process_articles_parallel", lambda articles, **kw: ([], 0))
    monkeypatch.setattr(
        wiki_eval, "WikidataClient", lambda cache_path=None, network_concurrency=3: object(),
    )
    monkeypatch.setattr(wiki_eval, "_canonicalize_fn", lambda wd: (lambda q: q))

    guard = wiki_eval.BudgetGuard(max_usd=10.0)
    wiki_eval._run_one_config("111", [], str(tmp_path), dry_run=False, guard=guard, out_dir=tmp_path)

    assert isinstance(captured["judge_call_logger"], wiki_eval.CallLogger)
    assert captured["extract_call_logger"] is captured["judge_call_logger"]  # SAME instance, shared
    assert captured["judge_call_logger"].path == tmp_path / "calls.jsonl"


def test_run_one_config_without_out_dir_builds_no_call_logger(monkeypatch, tmp_path):
    captured: dict = {}

    def fake_build_judge(guard, sem, **kw):
        captured["call_logger"] = kw.get("call_logger")
        return None

    monkeypatch.setattr(wiki_eval, "_build_judge", fake_build_judge)
    monkeypatch.setattr(wiki_eval, "_build_extract_fn", lambda guard, sem, **kw: (lambda p: []))
    monkeypatch.setattr(wiki_eval, "_process_articles_parallel", lambda articles, **kw: ([], 0))
    monkeypatch.setattr(
        wiki_eval, "WikidataClient", lambda cache_path=None, network_concurrency=3: object(),
    )
    monkeypatch.setattr(wiki_eval, "_canonicalize_fn", lambda wd: (lambda q: q))

    guard = wiki_eval.BudgetGuard(max_usd=10.0)
    wiki_eval._run_one_config("111", [], str(tmp_path), dry_run=False, guard=guard)  # no out_dir
    assert captured["call_logger"] is None


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


# ── _parallel_extract_fn: parse-fail accounting (spec §4.2.5, finding 1) ───


def test_parallel_extract_fn_tolerates_extraction_parse_error():
    """An ExtractionParseError (malformed LLM NER reply, not an honest empty
    [] and not a network failure) is tolerated as zero mentions, same as a
    transient failure -- but counted under its OWN tracker field, never
    conflated with n_failed_paragraphs."""
    from palimpsest.terminology.extract import ExtractionParseError

    def flaky_extract_fn(paragraph):
        if paragraph == "malformed":
            raise ExtractionParseError("no JSON array found in reply")
        return [paragraph.upper()]

    tracker = wiki_eval.FailureTracker()
    wrapped = wiki_eval._parallel_extract_fn(
        flaky_extract_fn, ["good1", "malformed", "good2"], title="Ancient Sumer", tracker=tracker,
    )
    results = [wrapped(p) for p in ["good1", "malformed", "good2"]]

    assert results == [["GOOD1"], [], ["GOOD2"]]
    assert tracker.n_extraction_parse_failures == 1
    assert tracker.parse_failed_paragraphs == [{"title": "Ancient Sumer", "paragraph_index": 1}]
    assert tracker.n_failed_paragraphs == 0  # not conflated with the transient-tolerance counter


def test_parallel_extract_fn_parse_error_printed_to_stderr(capsys):
    from palimpsest.terminology.extract import ExtractionParseError

    def bad_extract_fn(paragraph):
        raise ExtractionParseError("malformed JSON array")

    wrapped = wiki_eval._parallel_extract_fn(bad_extract_fn, ["p1"], title="Ancient Rome")
    wrapped("p1")

    captured = capsys.readouterr()
    assert "Ancient Rome" in captured.err
    assert "parse failure" in captured.err.lower()


def test_parallel_extract_fn_fatal_error_enriched_with_note_and_reraised():
    """A FatalGroundingJudgeError (LengthOverflowError/CallGateError/
    BudgetExhaustedError) is NEVER tolerated -- it's enriched with the
    article/paragraph context via exc.add_note and re-raised to kill the
    run, checked BEFORE the transient/deterministic split."""
    def fatal_extract_fn(paragraph):
        raise wiki_eval.LengthOverflowError("extract call hit the output-length limit")

    with pytest.raises(wiki_eval.LengthOverflowError) as exc_info:
        wiki_eval._parallel_extract_fn(fatal_extract_fn, ["p1"], title="Ancient Egypt")

    notes = getattr(exc_info.value, "__notes__", [])
    assert any("Ancient Egypt" in n and "paragraph=0" in n for n in notes)


def test_parallel_extract_fn_budget_exhausted_is_fatal_not_tolerated():
    def exhausted_extract_fn(paragraph):
        raise wiki_eval.BudgetExhaustedError("budget cap $10.00 hit")

    tracker = wiki_eval.FailureTracker()
    with pytest.raises(wiki_eval.BudgetExhaustedError):
        wiki_eval._parallel_extract_fn(exhausted_extract_fn, ["p1"], title="X", tracker=tracker)

    assert tracker.n_failed_paragraphs == 0
    assert tracker.n_extraction_parse_failures == 0


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
    values returned across calls, in order (one entry consumed per call).
    ``reasoning_tokens=5`` (nonzero) on every reply: the default model
    (DEFAULT_MODEL) has ``expect_reasoning=True`` (spec Р13), so a fake reply
    with rt=0 would trip ``_gate_reply``'s reasoning-ignition gate for tests
    that aren't actually testing that gate."""
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
            return LLMResult(content=content, usage=Usage(10, 5, 5, 0.0001))

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


# ── budget exhaustion is loud (findings 2/10) ───────────────────────────────
#
# A pre-call reservation ceiling hit mid-run used to raise a bare
# RuntimeError -- which ground()'s judge catch-all silently swallowed into
# resolved_by=judge_unavailable, corrupting slices instead of stopping the
# run. Both the extractor and the judge now raise BudgetExhaustedError (a
# FatalGroundingJudgeError subclass), which propagates past that catch-all.


def test_build_extract_fn_raises_budget_exhausted_when_guard_stopped(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-not-a-secret")
    guard = wiki_eval.BudgetGuard(max_usd=10.0)
    guard.stopped_reason = "budget cap $10.00 hit (test)"
    llm_semaphore = wiki_eval._CountingSemaphore(4)
    extract_fn = wiki_eval._build_extract_fn(guard, llm_semaphore)

    with pytest.raises(wiki_eval.BudgetExhaustedError, match="budget cap"):
        extract_fn("some paragraph")


def test_build_judge_raises_budget_exhausted_when_guard_stopped(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-not-a-secret")
    guard = wiki_eval.BudgetGuard(max_usd=10.0)
    guard.stopped_reason = "max_judge_calls=900 reached (test)"
    llm_semaphore = wiki_eval._CountingSemaphore(4)
    judge = wiki_eval._build_judge(guard, llm_semaphore)
    assert judge is not None

    with pytest.raises(wiki_eval.BudgetExhaustedError, match="max_judge_calls"):
        judge("some judge prompt")


def test_build_judge_budget_exhausted_used_with_real_grounding_propagates_and_kills_run():
    """Integration: BudgetExhaustedError is NOT swallowed by
    LabelFirstGrounding.ground()'s judge catch-all -- unlike a generic judge
    exception (see test_build_judge_transient_exhausted_used_with_real_grounding_leaves_mention_unresolved),
    this one propagates all the way out of ground() (spec Р15)."""
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
        raise wiki_eval.BudgetExhaustedError("budget cap $10.00 hit")

    strategy = LabelFirstGrounding(_FakeWD(), GroundingConfig())
    with pytest.raises(wiki_eval.BudgetExhaustedError):
        strategy.ground(TermMention(surface="Тутмос", lemma="Тутмос"), judge=exhausted_judge)


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
        tracker.record_parse_failure("Some Article", 7)
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
    # spec §4.2.5, finding 1: parse-fail accounting is a SEPARATE counter,
    # never conflated with the transient-tolerance ones above.
    assert counters["n_extraction_parse_failures"] == 1
    assert counters["parse_failed_paragraphs"] == [{"title": "Some Article", "paragraph_index": 7}]
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
    checkpoint = wiki_eval.Checkpointer(tmp_path, n_total=3, guard=guard)

    guard.reserve(1.25, kind="extract")
    checkpoint.record("Article A", [{"title": "Article A", "index": 0, "qid": "Q1"}])

    guard.reserve(1.25, kind="judge")
    checkpoint.record("Article B", [
        {"title": "Article B", "index": 0, "qid": "Q2"},
        {"title": "Article B", "index": 1, "qid": "Q3"},
    ])

    partial_lines = _read_jsonl(tmp_path / "pred.partial.jsonl")
    assert [r["title"] for r in partial_lines] == ["Article A", "Article B", "Article B"]

    # spent_by_kind/calls_by_kind (finding 3): every progress line carries a
    # SNAPSHOT of the guard's split at that instant, not just the total.
    progress_lines = _read_jsonl(tmp_path / "progress.jsonl")
    assert progress_lines == [
        {"article": "Article A", "done": 1, "of": 3, "spent": 1.25,
         "spent_by_kind": {"extract": 1.25, "judge": 0.0}, "calls_by_kind": {"extract": 1, "judge": 0}},
        {"article": "Article B", "done": 2, "of": 3, "spent": 2.5,
         "spent_by_kind": {"extract": 1.25, "judge": 1.25}, "calls_by_kind": {"extract": 1, "judge": 1}},
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
        "n_extraction_parse_failures": 0, "parse_failed_paragraphs": [],
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


def test_cmd_run_resume_skips_done_titles_seeds_guard_and_merges(monkeypatch, tmp_path, capsys):
    """This resume dir's progress.jsonl is OLD-FORMAT (no spent_by_kind/
    calls_by_kind, finding 3): the total spend still restores correctly, but
    the split degrades to zero and a loud warning fires -- bounded
    imprecision, not silent data loss. See
    test_cmd_run_resume_restores_spent_by_kind_and_calls_by_kind_from_new_format_progress
    for the new-format restoration path."""
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
        captured["guard_spent_by_kind_at_call"] = dict(guard.spent_by_kind)
        captured["guard_calls_by_kind_at_call"] = dict(guard.calls_by_kind)
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
    # old-format degrade: bounded imprecision, not a crash.
    assert captured["guard_spent_by_kind_at_call"] == {"extract": 0.0, "judge": 0.0}
    assert captured["guard_calls_by_kind_at_call"] == {"extract": 0, "judge": 0}
    assert captured["out_dir"] == resume_dir  # reused, not a fresh OUT_ROOT path

    stderr = capsys.readouterr().err
    assert "WARNING" in stderr and "old-format" in stderr

    assert (resume_dir / "pred.jsonl").exists()
    pred_records = _read_jsonl(resume_dir / "pred.jsonl")
    assert [r["title"] for r in pred_records] == ["Article A", "Article B"]  # merged, gt order

    assert not (resume_dir / "pred.partial.jsonl").exists()  # deleted on clean completion

    meta = json.loads((resume_dir / "meta.json").read_text(encoding="utf-8"))
    assert meta["resumed_from_n_articles"] == 1
    assert meta["run_id"] == resume_dir.name  # run_id reused, not a fresh timestamp
    # finding 3 self-consistency: n_pred_mentions reflects the MERGED total
    # (2: "Article A" resumed + "Article B" new), not _run_one_config's
    # new-only counter (_fake_counters() sets n_pred_mentions=2 already, so
    # this specifically checks the merged-count override didn't regress it
    # to a stale/undercounted value on the merge path).
    assert meta["n_pred_mentions"] == 2


def test_cmd_run_resume_restores_spent_by_kind_and_calls_by_kind_from_new_format_progress(monkeypatch, tmp_path, capsys):
    """New-format progress.jsonl (finding 3): the spend/call SPLIT restores
    exactly, and no warning fires."""
    gt_path = tmp_path / "gt.jsonl"
    _write_gt_jsonl(gt_path, ["Article A", "Article B"])

    resume_dir = tmp_path / "prior_run"
    resume_dir.mkdir()
    (resume_dir / "pred.partial.jsonl").write_text(
        json.dumps({"title": "Article A", "index": 0, "qid": "Q1"}) + "\n", encoding="utf-8",
    )
    progress_line = {
        "article": "Article A", "done": 1, "of": 2, "spent": 3.5,
        "spent_by_kind": {"extract": 1.5, "judge": 2.0},
        "calls_by_kind": {"extract": 30, "judge": 15},
    }
    (resume_dir / "progress.jsonl").write_text(json.dumps(progress_line) + "\n", encoding="utf-8")

    captured: dict = {}

    def fake_run_one_config(config, gt_records, cache, *, dry_run, guard, **kw):
        captured["guard_spent_by_kind_at_call"] = dict(guard.spent_by_kind)
        captured["guard_calls_by_kind_at_call"] = dict(guard.calls_by_kind)
        return [{"title": "Article B", "index": 0, "qid": "Q2"}], _fake_counters()

    monkeypatch.setattr(wiki_eval, "_run_one_config", fake_run_one_config)

    args = wiki_eval._build_parser().parse_args([
        "run", "--gt", str(gt_path), "--resume", str(resume_dir), "--max-usd", "5",
    ])
    rc = wiki_eval.cmd_run(args)
    assert rc == 0

    assert captured["guard_spent_by_kind_at_call"] == {"extract": 1.5, "judge": 2.0}
    assert captured["guard_calls_by_kind_at_call"] == {"extract": 30, "judge": 15}

    stderr = capsys.readouterr().err
    assert "WARNING" not in stderr


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


# ── Wikidata usage counters surfaced in meta.json ───────────────────────────


def test_cmd_run_surfaces_wikidata_counters_in_meta_json(monkeypatch, tmp_path):
    """_run_one_config's counters dict carries a "wikidata" sub-dict (calls/
    cache_hits/seconds off its shared WikidataClient); cmd_run merges the
    whole counters dict into meta via **counters, so it must land in
    meta.json verbatim -- same evidence contract as the existing LLM
    "calls" (extract/judge) split."""
    gt_path = tmp_path / "gt.jsonl"
    _write_gt_jsonl(gt_path, ["Article A"])

    def fake_run_one_config(config, gt_records, cache, *, dry_run, guard, **kw):
        counters = _fake_counters()
        counters["n_articles"] = 1
        counters["wikidata"] = {"calls": 7, "cache_hits": 3, "seconds": 0.456}
        return [{"title": "Article A", "index": 0, "qid": "Q1"}], counters

    monkeypatch.setattr(wiki_eval, "_run_one_config", fake_run_one_config)
    monkeypatch.setattr(wiki_eval, "OUT_ROOT", tmp_path / "out")

    args = wiki_eval._build_parser().parse_args(["run", "--gt", str(gt_path), "--max-usd", "5"])
    rc = wiki_eval.cmd_run(args)
    assert rc == 0

    out_dir = list((tmp_path / "out").glob("*/*/*"))[0]
    meta = json.loads((out_dir / "meta.json").read_text(encoding="utf-8"))
    assert meta["wikidata"] == {"calls": 7, "cache_hits": 3, "seconds": 0.456}


# ── meta.json generation_params (spec Р3/Р8: effective params, auditable) ──


def test_cmd_run_writes_generation_params_into_meta_json(monkeypatch, tmp_path):
    gt_path = tmp_path / "gt.jsonl"
    _write_gt_jsonl(gt_path, ["Article A"])

    def fake_run_one_config(config, gt_records, cache, *, dry_run, guard, **kw):
        return [{"title": "Article A", "index": 0, "qid": "Q1"}], _fake_counters()

    monkeypatch.setattr(wiki_eval, "_run_one_config", fake_run_one_config)
    monkeypatch.setattr(wiki_eval, "OUT_ROOT", tmp_path / "out")

    args = wiki_eval._build_parser().parse_args([
        "run", "--gt", str(gt_path), "--max-usd", "5", "--model", "deepseek/deepseek-v4-flash",
    ])
    rc = wiki_eval.cmd_run(args)
    assert rc == 0

    out_dir = list((tmp_path / "out").glob("*/*/*"))[0]
    meta = json.loads((out_dir / "meta.json").read_text(encoding="utf-8"))
    gp = meta["generation_params"]
    assert gp["model"] == "deepseek/deepseek-v4-flash"
    assert gp["base_url"] == wiki_eval.DEFAULT_BASE_URL
    assert gp["provider_pin"] == "Novita"
    assert gp["temperature"] == 1.0
    assert gp["top_p"] == 1.0
    assert gp["max_tokens"] == wiki_eval.DEFAULT_MAX_TOKENS
    assert gp["reasoning"] == {"enabled": True}
    assert gp["extra_body_effective"]["provider"] == {"order": ["Novita"], "allow_fallbacks": False}
    # meta's top-level model/provider mirror the resolved route, not the raw CLI value.
    assert meta["model"] == "deepseek/deepseek-v4-flash"
    assert meta["provider"] == "Novita"


# ── cmd_report: protocol v3 (spec Р9) ───────────────────────────────────────


def test_cli_report_tier_default_and_override():
    args = wiki_eval._build_parser().parse_args(["report", "--pred", "/tmp/some-run-dir"])
    assert args.tier == str(wiki_eval.TIER_PATH)

    args2 = wiki_eval._build_parser().parse_args([
        "report", "--pred", "/tmp/some-run-dir", "--tier", "/tmp/custom-tier.json",
    ])
    assert args2.tier == "/tmp/custom-tier.json"


def test_cli_report_has_no_p3_flag():
    """--p3/label-credit precision was retired (spec Р9, §7) along with the
    mention-level protocol -- the flag must not exist any more."""
    with pytest.raises(SystemExit):
        wiki_eval._build_parser().parse_args(["report", "--pred", "/tmp/x", "--p3"])


def _write_tier_json(path: Path, tier_by_qid: dict[str, int]) -> None:
    path.write_text(json.dumps(tier_by_qid), encoding="utf-8")


def test_cmd_report_writes_v3_metrics_with_named_and_term_classes(tmp_path):
    """cmd_report on a tiny synthetic gt/pred/tier fixture writes a v3
    metrics.json (classes.named/term present) and a report.html."""
    gt_path = tmp_path / "gt.jsonl"
    with gt_path.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps({
            "title": "Article A", "stratum": "typical",
            "gt_tuples": [[0, "Рим", "Q220", 1], [10, "легион", "Qterm", 1]],
        }) + "\n")

    tier_path = tmp_path / "tier.json"
    _write_tier_json(tier_path, {})

    pred_dir = tmp_path / "run"
    pred_dir.mkdir()
    with (pred_dir / "pred.jsonl").open("w", encoding="utf-8") as fh:
        fh.write(json.dumps({
            "title": "Article A", "index": 0, "surface": "Рим", "qid": "Q220",
            "span_len": 1, "resolved_by": "exact_label",
        }) + "\n")
        fh.write(json.dumps({
            "title": "Article A", "index": 20, "surface": "wrong", "qid": "Qfp",
            "span_len": 1, "resolved_by": "llm_disambiguation",
        }) + "\n")

    args = wiki_eval._build_parser().parse_args([
        "report", "--gt", str(gt_path), "--pred", str(pred_dir), "--tier", str(tier_path),
    ])
    rc = wiki_eval.cmd_report(args)
    assert rc == 0

    metrics = json.loads((pred_dir / "metrics.json").read_text(encoding="utf-8"))
    assert metrics["protocol"] == "v3"
    named, term = metrics["classes"]["named"], metrics["classes"]["term"]
    assert named["tp"] == 1 and named["gold_units"] == 1  # "Рим" matched
    assert term["fn"] == 1 and term["gold_units"] == 1  # "легион" (Qterm) not predicted
    assert term["fp"] == 1  # "wrong"/Qfp: not in gold, classified by its own (lowercase) surface
    assert (pred_dir / "report.html").exists()
    html = (pred_dir / "report.html").read_text(encoding="utf-8")
    assert "protocol v3" in html.lower()


def test_cmd_report_applies_tier_filter_to_gold_but_not_predictions(tmp_path):
    """A gold tuple whose QID is tiered (tier != 0) is dropped from gold_units
    but a same-QID prediction still counts as FP (protocol asymmetry, spec
    Sec.4.5) -- end-to-end through the CLI, not just the aggregator unit
    tests in test_wiki_metrics_v3.py."""
    gt_path = tmp_path / "gt.jsonl"
    with gt_path.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps({
            "title": "Article A", "stratum": "typical",
            "gt_tuples": [[0, "кошка", "Qtiered", 1]],
        }) + "\n")

    tier_path = tmp_path / "tier.json"
    _write_tier_json(tier_path, {"Qtiered": 1})

    pred_dir = tmp_path / "run"
    pred_dir.mkdir()
    with (pred_dir / "pred.jsonl").open("w", encoding="utf-8") as fh:
        fh.write(json.dumps({
            "title": "Article A", "index": 0, "surface": "кошка", "qid": "Qtiered",
            "span_len": 1, "resolved_by": "exact_label",
        }) + "\n")

    args = wiki_eval._build_parser().parse_args([
        "report", "--gt", str(gt_path), "--pred", str(pred_dir), "--tier", str(tier_path),
    ])
    rc = wiki_eval.cmd_report(args)
    assert rc == 0

    metrics = json.loads((pred_dir / "metrics.json").read_text(encoding="utf-8"))
    assert metrics["n_gold_mentions_dropped_by_tier"] == 1
    assert metrics["classes"]["term"]["gold_units"] == 0
    assert metrics["classes"]["term"]["fp"] == 1


def test_cmd_report_pred_records_without_qid_are_excluded(tmp_path):
    """pred_tuples building uses ``if r.get("qid")`` -- a record with
    ``qid=None`` (ungrounded mention, still logged for auditing) must not
    enter the scored prediction set, i.e. must not be counted as an FP."""
    gt_path = tmp_path / "gt.jsonl"
    _write_gt_jsonl(gt_path, ["Article A"])

    tier_path = tmp_path / "tier.json"
    _write_tier_json(tier_path, {})

    pred_dir = tmp_path / "run"
    pred_dir.mkdir()
    with (pred_dir / "pred.jsonl").open("w", encoding="utf-8") as fh:
        fh.write(json.dumps({
            "title": "Article A", "index": 0, "surface": "нечто", "qid": None,
            "span_len": 1, "resolved_by": "no_candidates",
        }) + "\n")

    args = wiki_eval._build_parser().parse_args([
        "report", "--gt", str(gt_path), "--pred", str(pred_dir), "--tier", str(tier_path),
    ])
    rc = wiki_eval.cmd_report(args)
    assert rc == 0

    metrics = json.loads((pred_dir / "metrics.json").read_text(encoding="utf-8"))
    assert metrics["classes"]["named"]["fp"] == 0
    assert metrics["classes"]["term"]["fp"] == 0
