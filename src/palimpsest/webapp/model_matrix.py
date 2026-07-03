"""The 8 demo models: per-model capability + seed defaults (single source of truth).

Rows mirror the /verify-spec-approved matrix in
docs/superpowers/specs/2026-07-01-model-registry-design.md. `default_params` are
intentionally small (cheap Tests). Reasoning effort is OMITTED where the provider
has a usable default (owner: "run on default effort"); sent only where obligatory
(gemini). Pricing is fetched live from OpenRouter at runtime (see budget.py), so
no prices are hardcoded here.
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
    # Seed defaults are tuned for the light term-extraction Test: reasoning is
    # OMITTED (extraction needs none; on reasoning models it truncates the JSON
    # answer and doubles cost — verified in live e2e), and max_tokens is 1536 so
    # a 20+-term list is never cut off. gemini keeps a low effort (obligatory on
    # its route) and a wider cap since its reasoning counts inside max_tokens.
    #
    # supports_seed: OpenRouter's `seed` param is accepted by every OR route we
    # use here (best-effort determinism hint per-provider, not a hard guarantee)
    # — see docs/known_issues.md for the one model (gpt-5.4-mini) where this is
    # unverified against a live call. vLLM's OpenAI-compat server does not wire
    # `seed` through by default in this deployment, so local models keep it off.
    _or("anthropic/claude-haiku-4.5", temp=False, top_k=True, min_p=False, seed=True,
        reasoning="max_tokens",
        default_params={"max_tokens": 1536}),                 # reasoning off → fast clean output
    _or("anthropic/claude-sonnet-5", temp=False, top_k=False, min_p=False, seed=True,
        reasoning="effort",
        default_params={"max_tokens": 1536}),                 # effort omitted → provider default
    _or("google/gemini-3.5-flash", temp=False, top_k=False, min_p=False, seed=True,
        reasoning="effort",
        default_params={"max_tokens": 2048, "reasoning": {"effort": "low"}}),  # effort obligatory
    _or("openai/gpt-5.4-mini", temp=False, top_k=False, min_p=False, seed=True,
        reasoning="effort",
        default_params={"max_tokens": 1536}),                 # effort omitted → provider default
    _or("qwen/qwen3.6-plus", temp=True, top_k=False, min_p=False, seed=True,
        reasoning="effort",
        default_params={"max_tokens": 1536, "temperature": 0.7}),
    _vllm("Qwen/Qwen3-4B-Thinking-2507", temp=True, top_k=True, min_p=True, seed=False,
          reasoning="none",
          default_params={"max_tokens": 1024, "temperature": 0.6, "top_k": 20, "min_p": 0.0}),
    _vllm("Infomaniak-AI/vllm-translategemma-27b-it", temp=True, top_k=False, min_p=False, seed=False,
          reasoning="none",
          default_params={"max_tokens": 1024, "temperature": 0.0}),
    _vllm("Qwen/Qwen3.6-27B", temp=True, top_k=True, min_p=True, seed=False,
          reasoning="enable_thinking",
          default_params={"max_tokens": 1024, "temperature": 1.0, "top_k": 20, "min_p": 0.0,
                          "enable_thinking": True}),
]

MATRIX: dict[str, ModelSpec] = {s.name: s for s in _SPECS}

# Seed criteria point here. Must be FAST (< the 20s /evaluate timeout) and emit
# clean parseable scoring JSON, else live /evaluate always times out or fails to
# parse and silently falls back to cached scores. gpt-5.4-mini: ~4s, cheap, no
# reasoning, clean JSON (verified live e2e). NOT qwen3.6-plus — it reasons for 60s.
DEFAULT_CRITERION_MODEL = "openai/gpt-5.4-mini"


def additive_reasoning_tokens(name: str, params: dict) -> int:
    """Reasoning tokens billed ON TOP of max_tokens (Anthropic only). 0 elsewhere."""
    spec = MATRIX.get(name)
    if spec is None or spec.reasoning != "max_tokens":
        return 0
    r = params.get("reasoning") or {}
    return int(r.get("max_tokens", 0))
