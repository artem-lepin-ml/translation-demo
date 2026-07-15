"""The 4 EMNLP-demo models (paper registry): per-model capability + seed defaults
(single source of truth) — replaces the prior 8-row matrix wholesale (2026-07-11
sprint; see docs/superpowers/specs/2026-06-30-demo-contracts.md rev-6 delta). A
fifth row from that same sprint, TranslateGemma-27B (a local vLLM placeholder,
display-only, never actually called), was dropped once the owner finalized the
registry directly on prod via the Settings UI the same day — this module now
mirrors that live prod state, not the paper's original 5-row draft.

`default_params` mirror the owner's live prod finalization (2026-07-11 UI edit):
a generous 20000-token ceiling and temperature=0.7 (natural, non-deterministic
judge/refiner output) on every row, superseding this module's earlier
cheap/deterministic defaults. Reasoning effort is OMITTED where the provider has
a usable default (owner: "run on default effort"); sent only where obligatory
(gemini, set to "medium" — not the cheaper "low" tier). Pricing is fetched live
from OpenRouter at runtime (see budget.py), so no prices are hardcoded here.

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


_SPECS = [
    # Demo-matrix temperature: 0.7 on all 4 rows (owner-finalized live on prod
    # via the Settings UI, 2026-07-11) — retires the earlier 2026-07-05
    # settings-fixes §2.4 "forced to 0" determinism policy in favor of
    # natural, non-deterministic judge/refiner output. A no-op where
    # supports_temperature=False (ModelParams.for_model strips the key before
    # the call — see model_params.py), but kept on the row so the raw params
    # vs `effective_params` distinction is visible in Settings.
    #
    # supports_seed: OpenRouter's `seed` param is accepted by every OR route
    # here per the live metadata fetch (best-effort determinism hint
    # per-provider, not a hard guarantee).
    # available registry model — no longer the default (see DEFAULT_CRITERION_MODEL
    # below); qwen3.6-27b is a forced-thinking model that returns empty output
    # or times out in the refiner role (docs/known_issues.md), which drove the
    # 2026-07-16 demo-wide move to gemini for every role
    _or("qwen/qwen3.6-27b", temp=True, top_k=True, min_p=True, seed=True,
        reasoning="effort",
        default_params={"max_tokens": 20000, "temperature": 0.7}),
    # no reasoning surface on this route
    _or("google/gemma-3-27b-it", temp=True, top_k=True, min_p=True, seed=True,
        reasoning="none",
        default_params={"max_tokens": 20000, "temperature": 0.7}),
    # effort omitted → provider default (fast/cheap tier)
    _or("deepseek/deepseek-v4-flash", temp=True, top_k=True, min_p=True, seed=True,
        reasoning="effort",
        default_params={"max_tokens": 20000, "temperature": 0.7}),
    # demo default model — everywhere (criteria, translator, grounding,
    # refiner; EMNLP demo sprint, 2026-07-16 gemini-everywhere config); effort
    # obligatory, mirrors the retired gemini-3.5-flash row; owner set "medium"
    # — not the cheaper "low" tier — as the model's default effort
    # (2026-07-11 Settings finalization)
    _or("google/gemini-3.1-flash-lite", temp=False, top_k=False, min_p=False, seed=True,
        reasoning="effort",
        default_params={"max_tokens": 20000, "temperature": 0.7,
                        "reasoning": {"effort": "medium"}}),
]

MATRIX: dict[str, ModelSpec] = {s.name: s for s in _SPECS}

# Criteria/translator/grounding/refiner all point here by default (2026-07-16:
# moved from qwen/qwen3.6-27b to gemini-3.1-flash-lite for demo speed across
# every role — see docs/known_issues.md for the qwen-as-refiner empty-output
# gotcha that motivated the move). qwen3.6-27b stays in MATRIX as an available
# registry model, just no longer the default. The 20000-token max_tokens is a
# generous ceiling, not an expected generation length — /evaluate is still
# bounded by EVAL_TIMEOUT (app.py, default 20s, env-overridable via
# PALIMPSEST_EVAL_TIMEOUT).
DEFAULT_CRITERION_MODEL = "google/gemini-3.1-flash-lite"


def additive_reasoning_tokens(name: str, params: dict) -> int:
    """Reasoning tokens billed ON TOP of max_tokens (Anthropic only). 0 elsewhere."""
    spec = MATRIX.get(name)
    if spec is None or spec.reasoning != "max_tokens":
        return 0
    r = params.get("reasoning") or {}
    return int(r.get("max_tokens", 0))
