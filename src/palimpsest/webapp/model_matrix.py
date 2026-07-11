"""The 5 EMNLP-demo models (paper registry): per-model capability + seed defaults
(single source of truth) — replaces the prior 8-row matrix wholesale (2026-07-11
sprint; see docs/superpowers/specs/2026-06-30-demo-contracts.md rev-6 delta).

`default_params` are intentionally small (cheap judge calls). Reasoning effort is
OMITTED where the provider has a usable default (owner: "run on default effort");
sent only where obligatory (gemini). Pricing is fetched live from OpenRouter at
runtime (see budget.py), so no prices are hardcoded here.

Capability flags for the 4 OpenRouter rows are cross-checked against a live
``GET /api/v1/models`` fetch (2026-07-11): ``supported_parameters`` confirmed
temperature/min_p/top_k/seed/reasoning per row below. The one deliberate
departure from raw metadata is Gemini: OpenRouter's schema lists `temperature`
as accepted for gemini-3.1-flash-lite too, but `supports_temperature=False` is
carried over from the retired gemini-3.5-flash row's empirical finding — an
obligatory-reasoning Gemini route ignores temperature in practice, schema
acceptance notwithstanding (unverified against a fresh live call on THIS exact
model; flagged, not just assumed).
"""
from __future__ import annotations

from dataclasses import dataclass

OPENROUTER = "https://openrouter.ai/api/v1"
VLLM = "http://localhost:8001/v1"  # placeholder; not run now


@dataclass(frozen=True, slots=True)
class ModelSpec:
    name: str
    base_url: str
    is_openrouter: bool
    supports_temperature: bool
    supports_top_k: bool
    supports_min_p: bool
    supports_seed: bool
    reasoning: str            # "effort" | "max_tokens" | "enable_thinking" | "none"
    default_params: dict


def _or(name, *, temp, top_k, min_p, seed, reasoning, default_params) -> ModelSpec:
    return ModelSpec(name, OPENROUTER, True, temp, top_k, min_p, seed, reasoning, default_params)


def _vllm(name, *, temp, top_k, min_p, seed, reasoning, default_params) -> ModelSpec:
    return ModelSpec(name, VLLM, False, temp, top_k, min_p, seed, reasoning, default_params)


_SPECS = [
    # Demo-matrix temperature: forced to 0 on all 4 OpenRouter rows (judge/
    # refiner determinism for the recorded demo — carried over from the
    # 2026-07-05 settings-fixes §2.4 policy). A no-op where
    # supports_temperature=False (ModelParams.for_model strips the key before
    # the call — see model_params.py), but kept on the row so the raw params
    # vs `effective_params` distinction is visible in Settings.
    #
    # supports_seed: OpenRouter's `seed` param is accepted by every OR route
    # here per the live metadata fetch (best-effort determinism hint
    # per-provider, not a hard guarantee). vLLM's OpenAI-compat server does
    # not wire `seed` through by default in this deployment, so the local
    # placeholder keeps it off.
    # demo default model — everywhere (criteria, translator, grounding, refiner)
    _or("qwen/qwen3.6-27b", temp=True, top_k=True, min_p=True, seed=True,
        reasoning="effort",
        default_params={"max_tokens": 1536, "temperature": 0}),
    # no reasoning surface on this route
    _or("google/gemma-3-27b-it", temp=True, top_k=True, min_p=True, seed=True,
        reasoning="none",
        default_params={"max_tokens": 1536, "temperature": 0}),
    # local placeholder, display-only
    _vllm("TranslateGemma-27B", temp=True, top_k=False, min_p=False, seed=False,
          reasoning="none",
          default_params={"max_tokens": 1024, "temperature": 0.0}),
    # effort omitted → provider default (fast/cheap tier)
    _or("deepseek/deepseek-v4-flash", temp=True, top_k=True, min_p=True, seed=True,
        reasoning="effort",
        default_params={"max_tokens": 1536, "temperature": 0}),
    # effort obligatory, mirrors the retired gemini-3.5-flash row
    _or("google/gemini-3.1-flash-lite", temp=False, top_k=False, min_p=False, seed=True,
        reasoning="effort",
        default_params={"max_tokens": 2048, "temperature": 0,
                        "reasoning": {"effort": "low"}}),
]

MATRIX: dict[str, ModelSpec] = {s.name: s for s in _SPECS}

# Criteria/translator/grounding/refiner all point here by default. Must be FAST
# (< the 20s /evaluate timeout) and emit clean parseable scoring JSON — qwen3.6-27b
# is the paper's headline model and the OpenRouter row every role is seeded/
# migrated onto (2026-07-11 EMNLP sprint; retires openai/gpt-5.4-mini).
DEFAULT_CRITERION_MODEL = "qwen/qwen3.6-27b"


def additive_reasoning_tokens(name: str, params: dict) -> int:
    """Reasoning tokens billed ON TOP of max_tokens (Anthropic only). 0 elsewhere."""
    spec = MATRIX.get(name)
    if spec is None or spec.reasoning != "max_tokens":
        return 0
    r = params.get("reasoning") or {}
    return int(r.get("max_tokens", 0))
