from palimpsest.webapp import model_matrix as mm
from palimpsest.webapp.model_matrix import ModelSpec
from palimpsest.webapp.model_params import JUDGE_SEED, ModelParams


def test_matrix_has_five_models_four_openrouter():
    assert len(mm.MATRIX) == 5
    assert sum(s.is_openrouter for s in mm.MATRIX.values()) == 4


def test_gemini_flash_lite_drops_temperature():
    # the one temp=False row in the new 5-model matrix (mirrors the retired
    # gemini-3.5-flash row's obligatory-reasoning finding)
    assert mm.MATRIX["google/gemini-3.1-flash-lite"].supports_temperature is False


def test_additive_reasoning_only_for_max_tokens_kind(monkeypatch):
    # No row in the current 5-model matrix is reasoning="max_tokens" kind (that
    # was Anthropic-specific, and Anthropic isn't in the new registry) — this
    # pure-function behavior is exercised via a synthetic spec instead of
    # depending on which real models happen to be seeded right now.
    # `setitem` (not a full setattr rebind) mutates the SAME dict object that
    # model_params.py imported by value (`from .model_matrix import MATRIX`)
    # — a rebind would only be visible from this module's own `mm.MATRIX` name.
    monkeypatch.setitem(mm.MATRIX, "test/max-tokens-kind", ModelSpec(
        "test/max-tokens-kind", mm.OPENROUTER, True, True, True, True, True, "max_tokens", {}))

    assert mm.additive_reasoning_tokens(
        "test/max-tokens-kind", {"reasoning": {"max_tokens": 1024}}) == 1024
    # qwen3.6-27b is reasoning="effort" kind → joint with max_tokens, not additive
    assert mm.additive_reasoning_tokens(
        "qwen/qwen3.6-27b", {"reasoning": {"effort": "low"}}) == 0


def test_temperature_dropped_for_gemini_flash_lite():
    mp = ModelParams.for_model("google/gemini-3.1-flash-lite",
                               {"temperature": 0.5, "max_tokens": 512})
    assert mp.temperature is None and mp.max_tokens == 512


def test_top_k_min_p_independent_stripping(monkeypatch):
    # None of the 5 real rows has an asymmetric (top_k, min_p) capability
    # combo any more (they're either both True or both False) — exercise the
    # independent-stripping LOGIC in ModelParams.for_model via a synthetic
    # spec, decoupled from whichever real models happen to be registered.
    monkeypatch.setitem(mm.MATRIX, "test/asymmetric", ModelSpec(
        "test/asymmetric", mm.OPENROUTER, True, True, True, False, True, "none", {}))

    mp = ModelParams.for_model("test/asymmetric", {"top_k": 40, "min_p": 0.1})
    eb = mp.to_extra_body("test/asymmetric", "https://openrouter.ai/api/v1")
    assert eb.get("top_k") == 40 and "min_p" not in eb
    assert eb["usage"] == {"include": True}           # OR → cost accounting on


def test_top_k_dropped_for_gemini_flash_lite():
    mp = ModelParams.for_model("google/gemini-3.1-flash-lite", {"top_k": 5})
    eb = mp.to_extra_body("google/gemini-3.1-flash-lite", "https://openrouter.ai/api/v1")
    assert "top_k" not in eb


def test_unknown_model_passes_known_fields_through():
    mp = ModelParams.for_model("some/custom", {"temperature": 0.3, "max_tokens": 256})
    assert mp.temperature == 0.3 and mp.max_tokens == 256


def test_vllm_no_usage_accounting_field():
    mp = ModelParams.for_model("TranslateGemma-27B", {"max_tokens": 1024})
    eb = mp.to_extra_body("TranslateGemma-27B", "http://localhost:8001/v1")
    assert "usage" not in eb                          # non-OR → no OR accounting param


def test_max_tokens_kind_coerces_away_stray_effort_key(monkeypatch):
    monkeypatch.setitem(mm.MATRIX, "test/max-tokens-kind", ModelSpec(
        "test/max-tokens-kind", mm.OPENROUTER, True, True, True, True, True, "max_tokens", {}))

    # a hand-edited "effort" sub-key must not reach extra_body on a
    # max_tokens-kind model
    mp = ModelParams.for_model("test/max-tokens-kind", {"reasoning": {"effort": "high"}})
    eb = mp.to_extra_body("test/max-tokens-kind", "https://openrouter.ai/api/v1")
    assert "effort" not in (eb.get("reasoning") or {})


def test_effort_kind_coerces_away_stray_max_tokens_key():
    # qwen3.6-27b is reasoning="effort" kind → a hand-edited "max_tokens"
    # sub-key must not reach extra_body
    mp = ModelParams.for_model("qwen/qwen3.6-27b", {"reasoning": {"max_tokens": 4096}})
    eb = mp.to_extra_body("qwen/qwen3.6-27b", "https://openrouter.ai/api/v1")
    assert "max_tokens" not in (eb.get("reasoning") or {})


def test_seed_included_when_supported():
    mp = ModelParams.for_model("qwen/qwen3.6-27b", {"max_tokens": 512})
    assert mp.seed == JUDGE_SEED


def test_seed_omitted_when_unsupported():
    # the vLLM placeholder is supports_seed=False → seed must not be sent
    mp = ModelParams.for_model("TranslateGemma-27B", {"max_tokens": 512})
    assert mp.seed is None
