from palimpsest.webapp import model_matrix as mm
from palimpsest.webapp.model_params import JUDGE_SEED, ModelParams


def test_matrix_has_eight_models_five_openrouter():
    assert len(mm.MATRIX) == 8
    assert sum(s.is_openrouter for s in mm.MATRIX.values()) == 5


def test_claude_and_gemini_drop_temperature():
    for name in ("anthropic/claude-haiku-4.5", "anthropic/claude-sonnet-5", "google/gemini-3.5-flash"):
        assert mm.MATRIX[name].supports_temperature is False


def test_additive_reasoning_only_for_anthropic_max_tokens_kind():
    # haiku bills reasoning additively (reasoning kind == "max_tokens")
    assert mm.additive_reasoning_tokens(
        "anthropic/claude-haiku-4.5", {"reasoning": {"max_tokens": 1024}}) == 1024
    # gpt reasoning is joint with max_tokens → not additive
    assert mm.additive_reasoning_tokens(
        "openai/gpt-5.4-mini", {"reasoning": {"effort": "low"}}) == 0


def test_temperature_dropped_for_claude():
    mp = ModelParams.for_model("anthropic/claude-sonnet-5",
                               {"temperature": 0.5, "max_tokens": 512})
    assert mp.temperature is None and mp.max_tokens == 512


def test_min_p_dropped_for_haiku_top_k_kept():
    mp = ModelParams.for_model("anthropic/claude-haiku-4.5",
                               {"top_k": 40, "min_p": 0.1})
    eb = mp.to_extra_body("anthropic/claude-haiku-4.5",
                          "https://openrouter.ai/api/v1")
    assert eb.get("top_k") == 40 and "min_p" not in eb
    assert eb["usage"] == {"include": True}           # OR → cost accounting on


def test_top_k_dropped_for_gemini():
    mp = ModelParams.for_model("google/gemini-3.5-flash", {"top_k": 5})
    eb = mp.to_extra_body("google/gemini-3.5-flash", "https://openrouter.ai/api/v1")
    assert "top_k" not in eb


def test_unknown_model_passes_known_fields_through():
    mp = ModelParams.for_model("some/custom", {"temperature": 0.3, "max_tokens": 256})
    assert mp.temperature == 0.3 and mp.max_tokens == 256


def test_vllm_no_usage_accounting_field():
    mp = ModelParams.for_model("Qwen/Qwen3-4B-Thinking-2507",
                               {"top_k": 20, "min_p": 0.0})
    eb = mp.to_extra_body("Qwen/Qwen3-4B-Thinking-2507", "http://localhost:8001/v1")
    assert "usage" not in eb                          # non-OR → no OR accounting param


def test_temperature_dropped_for_gpt_5_4_mini():
    mp = ModelParams.for_model("openai/gpt-5.4-mini",
                               {"temperature": 0.5, "max_tokens": 512})
    assert mp.temperature is None and mp.max_tokens == 512


def test_max_tokens_kind_coerces_away_stray_effort_key():
    # haiku is reasoning="max_tokens" kind → a hand-edited "effort" sub-key must not reach extra_body
    mp = ModelParams.for_model("anthropic/claude-haiku-4.5",
                               {"reasoning": {"effort": "high"}})
    eb = mp.to_extra_body("anthropic/claude-haiku-4.5", "https://openrouter.ai/api/v1")
    assert "effort" not in (eb.get("reasoning") or {})


def test_effort_kind_coerces_away_stray_max_tokens_key():
    # sonnet is reasoning="effort" kind → a hand-edited "max_tokens" sub-key must not reach extra_body
    mp = ModelParams.for_model("anthropic/claude-sonnet-5",
                               {"reasoning": {"max_tokens": 4096}})
    eb = mp.to_extra_body("anthropic/claude-sonnet-5", "https://openrouter.ai/api/v1")
    assert "max_tokens" not in (eb.get("reasoning") or {})


def test_seed_included_when_supported():
    # OpenRouter models in the matrix are supports_seed=True → fixed judge seed included
    mp = ModelParams.for_model("anthropic/claude-sonnet-5", {"max_tokens": 512})
    assert mp.seed == JUDGE_SEED


def test_seed_omitted_when_unsupported():
    # vLLM models are supports_seed=False → seed must not be sent
    mp = ModelParams.for_model("Qwen/Qwen3-4B-Thinking-2507", {"max_tokens": 512})
    assert mp.seed is None
