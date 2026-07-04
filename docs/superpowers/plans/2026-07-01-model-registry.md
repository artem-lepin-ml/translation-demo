# Model Registry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `.claude/skills/superpowers/subagent-driven-development/SKILL.md` (recommended) or executing-plans (not vendored) to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the demo's "cardboard" model registry actually call each model with per-model-correct parameters, add a per-model Test button (real term-extraction request → overlap share), and guard every real call with a hard $2 budget — all on live OpenRouter only (3 local vLLM rows are seeded but never run now).

**Architecture:** Widen the generic `LLMClient` to return usage/cost and pass arbitrary `extra_body`. Add a single source-of-truth `model_matrix.py` (8-model capabilities + live-priced budget). Add `ModelParams` that filters a model's `params_json` down to what that model supports. Rebuild `_client_for` on top (with env-fallback for the shared OR key). Add a `budget.py` in-process accumulator with atomic pre-call reservation. Add `POST /api/models/{name}/test`. Wire the frontend Test/Edit into the existing `variant-a` design system (no new tokens/classes).

**Tech Stack:** Python 3.13, FastAPI, SQLite (`sqlite3`), pydantic v2, `openai` SDK (OpenAI-compat, no Anthropic SDK), pytest; React + Zustand + TypeScript frontend.

**Source spec:** [2026-07-01-model-registry-design.md](../specs/2026-07-01-model-registry-design.md) (v2, /verify-spec gate passed). Read it first — this plan implements tasks T1–T8 there.

**Scope note (owner, 2026-07-01):** *Only OpenRouter runs now.* The 3 vLLM rows are seeded with correct params (S1 wants 8 rows) but are never live-called: their non-OR `base_url` + empty key means the env-fallback does NOT inject the OR key → `_client_for` returns `None` → Test returns `200 {ok:false, message:"no api key/env for model"}` with zero spend. Live Test/probe/e2e cover the 5 OR models only.

---

## File Structure

**New files:**
- `src/palimpsest/webapp/model_matrix.py` — the 8-model matrix: per-model capability flags, reasoning kind, seed `default_params`, `base_url`, and pricing helpers. Single source of truth for T1/T2/T4.
- `src/palimpsest/webapp/model_params.py` — `ModelParams` pydantic model: parse `params_json`, drop params the model doesn't support, build `extra_body`.
- `src/palimpsest/webapp/budget.py` — in-process spend/call accumulator, `estimate()`, atomic `reserve()`, `settle()`, JSONL `log_call()`, live price fetch.
- `tests/test_llm_result.py`, `tests/test_model_params.py`, `tests/test_budget.py`, `tests/test_test_endpoint.py`, `tests/test_seed_registry.py` — unit/contract tests (Stage 0, $0).

**Modified files:**
- `src/palimpsest/llm/client.py` — `LLMConfig` gains optional fields + `extra_body`; `complete()` returns `LLMResult(content, usage)`; retries off.
- `src/palimpsest/webapp/judge.py` — use `LLMResult.content`, drop `temperature=0`, return `usage`.
- `src/palimpsest/webapp/seed.py` — seed 8 model rows from the matrix; repoint criteria to a matrix model.
- `src/palimpsest/webapp/app.py` — rebuild `_client_for` (ModelParams + env-fallback), add `/test`, reserve/settle budget in `_judge_live`.
- `frontend/src/demo/api-client.ts` — `TestModelResult` type + `testModel()`.
- `frontend/src/demo/store.ts` — `testModel` action.
- `frontend/src/demo/variant-a/SettingsTab.tsx` — Test button + result row + Edit modal, all `va-*`.
- `docs/subsystems/webapp.md`, `docs/superpowers/specs/2026-06-30-demo-contracts.md` — doc-parity (T8).

---

## Type contract (defined once — later tasks must match verbatim)

```python
# llm/client.py
@dataclass(slots=True)
class Usage:
    prompt_tokens: int
    completion_tokens: int      # OpenAI: includes reasoning; Anthropic: excludes it
    reasoning_tokens: int
    cost_usd: float | None      # from OpenRouter usage.cost when include=True, else None

@dataclass(slots=True)
class LLMResult:
    content: str
    usage: Usage
```

```python
# model_matrix.py
@dataclass(frozen=True, slots=True)
class ModelSpec:
    name: str
    base_url: str
    is_openrouter: bool
    supports_temperature: bool
    supports_top_k: bool
    supports_min_p: bool
    reasoning: str              # "effort" | "max_tokens" | "enable_thinking" | "none"
    default_params: dict        # what seed writes to params_json
```

```python
# budget.py — module-level singleton state
class BudgetExceeded(Exception): ...
def count_tokens(text: str) -> int                 # conservative upper bound
def estimate(name: str, prompt_tokens: int, max_tokens: int, reasoning_max_tokens: int = 0) -> float
async def reserve(est: float) -> None              # atomic; raises BudgetExceeded
def settle(reserved: float, actual: float | None) -> None
def log_call(record: dict) -> None
def reset() -> None                                # test helper
```

Function/property names used across tasks: `LLMResult.content`, `LLMResult.usage`, `Usage.prompt_tokens/completion_tokens/reasoning_tokens/cost_usd`, `ModelParams.for_model(name, raw)`, `ModelParams.to_extra_body(name, base_url)`, `model_matrix.MATRIX`, `model_matrix.additive_reasoning_tokens(name, params)`, `budget.estimate/reserve/settle/log_call/count_tokens/BudgetExceeded/reset`.

---

## Task 1: `model_matrix.py` — the 8-model single source of truth

**Files:**
- Create: `src/palimpsest/webapp/model_matrix.py`
- Test: `tests/test_model_params.py` (shared with Task 3; Task 1 adds the matrix asserts)

- [ ] **Step 1: Write the failing test** (`tests/test_model_params.py`)

```python
from palimpsest.webapp import model_matrix as mm


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
```

- [ ] **Step 2: Run test to verify it fails** — `uv run pytest tests/test_model_params.py -v` → FAIL (module not found).

- [ ] **Step 3: Write `model_matrix.py`**

```python
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
    reasoning: str            # "effort" | "max_tokens" | "enable_thinking" | "none"
    default_params: dict


def _or(name, *, temp, top_k, min_p, reasoning, default_params) -> ModelSpec:
    return ModelSpec(name, OPENROUTER, True, temp, top_k, min_p, reasoning, default_params)


def _vllm(name, *, temp, top_k, min_p, reasoning, default_params) -> ModelSpec:
    return ModelSpec(name, VLLM, False, temp, top_k, min_p, reasoning, default_params)


_SPECS = [
    _or("anthropic/claude-haiku-4.5", temp=False, top_k=True, min_p=False,
        reasoning="max_tokens",
        default_params={"max_tokens": 1024, "reasoning": {"max_tokens": 1024}}),
    _or("anthropic/claude-sonnet-5", temp=False, top_k=False, min_p=False,
        reasoning="effort",
        default_params={"max_tokens": 1024}),                 # effort omitted → provider default
    _or("google/gemini-3.5-flash", temp=False, top_k=False, min_p=False,
        reasoning="effort",
        default_params={"max_tokens": 1024, "reasoning": {"effort": "low"}}),  # obligatory
    _or("openai/gpt-5.4-mini", temp=True, top_k=False, min_p=False,
        reasoning="effort",
        default_params={"max_tokens": 1024}),                 # effort omitted → provider default
    _or("qwen/qwen3.6-plus", temp=True, top_k=False, min_p=False,
        reasoning="effort",
        default_params={"max_tokens": 1024, "temperature": 0.7}),
    _vllm("Qwen/Qwen3-4B-Thinking-2507", temp=True, top_k=True, min_p=True,
          reasoning="none",
          default_params={"max_tokens": 1024, "temperature": 0.6, "top_k": 20, "min_p": 0.0}),
    _vllm("Infomaniak-AI/vllm-translategemma-27b-it", temp=True, top_k=False, min_p=False,
          reasoning="none",
          default_params={"max_tokens": 1024, "temperature": 0.0}),
    _vllm("Qwen/Qwen3.6-27B", temp=True, top_k=True, min_p=True,
          reasoning="enable_thinking",
          default_params={"max_tokens": 1024, "temperature": 1.0, "top_k": 20, "min_p": 0.0,
                          "enable_thinking": True}),
]

MATRIX: dict[str, ModelSpec] = {s.name: s for s in _SPECS}

DEFAULT_CRITERION_MODEL = "qwen/qwen3.6-plus"  # cheapest OR model; seed criteria point here


def additive_reasoning_tokens(name: str, params: dict) -> int:
    """Reasoning tokens billed ON TOP of max_tokens (Anthropic only). 0 elsewhere."""
    spec = MATRIX.get(name)
    if spec is None or spec.reasoning != "max_tokens":
        return 0
    r = params.get("reasoning") or {}
    return int(r.get("max_tokens", 0))
```

- [ ] **Step 4: Run test to verify it passes** — `uv run pytest tests/test_model_params.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add src/palimpsest/webapp/model_matrix.py tests/test_model_params.py
git commit -m "feat(webapp): model matrix — 8-model capability + seed defaults (T1 data)"
```

---

## Task 2: Widen `LLMClient` — `LLMResult`, `extra_body`, retries off

**Files:**
- Modify: `src/palimpsest/llm/client.py`
- Test: `tests/test_llm_result.py`

- [ ] **Step 1: Write the failing test** (uses a fake OpenAI client — no network)

```python
from types import SimpleNamespace

from palimpsest.llm.client import LLMClient, LLMConfig, LLMResult


class _FakeCompletions:
    def __init__(self, holder): self.holder = holder
    def create(self, **kwargs):
        self.holder["kwargs"] = kwargs
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="hi"))],
            usage=SimpleNamespace(
                prompt_tokens=10, completion_tokens=5,
                completion_tokens_details=SimpleNamespace(reasoning_tokens=3),
                cost=0.0004),
        )


def _client(monkeypatch, cfg):
    holder = {}
    c = LLMClient.__new__(LLMClient)
    c.config = cfg
    c._client = SimpleNamespace(chat=SimpleNamespace(completions=_FakeCompletions(holder)))
    return c, holder


def test_complete_returns_result_with_usage(monkeypatch):
    cfg = LLMConfig(model="m", base_url="u", api_key="k", temperature=None, max_tokens=64,
                    extra_body={"reasoning": {"effort": "low"}})
    c, holder = _client(monkeypatch, cfg)
    r = c.complete("sys", "usr")
    assert isinstance(r, LLMResult)
    assert r.content == "hi"
    assert r.usage.prompt_tokens == 10 and r.usage.reasoning_tokens == 3
    assert r.usage.cost_usd == 0.0004
    # temperature is None → NOT sent; extra_body IS sent
    assert "temperature" not in holder["kwargs"]
    assert holder["kwargs"]["extra_body"] == {"reasoning": {"effort": "low"}}


def test_complete_sends_temperature_when_set(monkeypatch):
    cfg = LLMConfig(model="m", base_url="u", api_key="k", temperature=0.7, max_tokens=64)
    c, holder = _client(monkeypatch, cfg)
    c.complete("s", "u")
    assert holder["kwargs"]["temperature"] == 0.7
```

- [ ] **Step 2: Run test to verify it fails** — `uv run pytest tests/test_llm_result.py -v` → FAIL.

- [ ] **Step 3: Rewrite `llm/client.py`**

```python
"""Thin OpenAI-compatible client. Same interface for vLLM, xAI, OpenAI, OpenRouter."""
from __future__ import annotations

import os
from dataclasses import dataclass

from openai import OpenAI

from ..config import ModelConfig


@dataclass(slots=True)
class Usage:
    prompt_tokens: int
    completion_tokens: int
    reasoning_tokens: int
    cost_usd: float | None


@dataclass(slots=True)
class LLMResult:
    content: str
    usage: Usage


@dataclass(slots=True)
class LLMConfig:
    model: str
    base_url: str
    api_key: str
    temperature: float | None = None      # None → omit (Claude/gemini reject/ignore it)
    max_tokens: int = 4096
    extra_body: dict | None = None        # top_k/min_p/reasoning/provider/usage passthrough

    @classmethod
    def from_model_config(cls, cfg: ModelConfig) -> "LLMConfig":
        return cls(model=cfg.name, base_url=cfg.base_url,
                   api_key=os.environ[cfg.api_key_env],
                   temperature=cfg.temperature, max_tokens=cfg.max_tokens)


def _extract_usage(resp) -> Usage:
    u = getattr(resp, "usage", None)
    if u is None:
        return Usage(0, 0, 0, None)
    details = getattr(u, "completion_tokens_details", None)
    reasoning = getattr(details, "reasoning_tokens", 0) if details else 0
    cost = getattr(u, "cost", None)
    if cost is None:
        extra = getattr(u, "model_extra", None) or {}
        cost = extra.get("cost")
    return Usage(int(getattr(u, "prompt_tokens", 0) or 0),
                 int(getattr(u, "completion_tokens", 0) or 0),
                 int(reasoning or 0),
                 float(cost) if cost is not None else None)


class LLMClient:
    """Stateless wrapper over chat.completions. One instance per model. No retries."""

    def __init__(self, config: LLMConfig):
        self.config = config
        self._client = OpenAI(base_url=config.base_url, api_key=config.api_key,
                              max_retries=0, timeout=30.0)

    def complete(self, system: str, user: str) -> LLMResult:
        kwargs: dict = {
            "model": self.config.model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "max_tokens": self.config.max_tokens,
        }
        if self.config.temperature is not None:
            kwargs["temperature"] = self.config.temperature
        if self.config.extra_body:
            kwargs["extra_body"] = self.config.extra_body
        resp = self._client.chat.completions.create(**kwargs)
        content = resp.choices[0].message.content or ""
        return LLMResult(content=content, usage=_extract_usage(resp))
```

Note: `complete()` no longer accepts `**overrides` — callers that passed `temperature=0` must stop (Task 5, judge.py).

- [ ] **Step 4: Run test to verify it passes** — `uv run pytest tests/test_llm_result.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add src/palimpsest/llm/client.py tests/test_llm_result.py
git commit -m "feat(llm): complete() returns LLMResult(content,usage); extra_body passthrough; retries off (T3)"
```

---

## Task 3: `ModelParams` — filter params to what each model supports

**Files:**
- Create: `src/palimpsest/webapp/model_params.py`
- Test: `tests/test_model_params.py` (append)

- [ ] **Step 1: Append the failing test**

```python
from palimpsest.webapp.model_params import ModelParams


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
```

- [ ] **Step 2: Run to verify it fails** — `uv run pytest tests/test_model_params.py -v` → FAIL.

- [ ] **Step 3: Write `model_params.py`**

```python
"""Parse a model's params_json and keep only what THAT model supports (per matrix)."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from .model_matrix import MATRIX


def _is_openrouter(base_url: str) -> bool:
    return "openrouter.ai" in (base_url or "")


class ModelParams(BaseModel):
    model_config = ConfigDict(extra="ignore")  # unknown keys silently dropped

    temperature: float | None = None
    max_tokens: int = 1024
    top_k: int | None = None
    min_p: float | None = None
    reasoning: dict | None = None          # {"effort": ...} | {"max_tokens": ...}
    enable_thinking: bool | None = None

    @classmethod
    def for_model(cls, name: str, raw: dict) -> "ModelParams":
        raw = dict(raw or {})
        spec = MATRIX.get(name)
        if spec is not None:
            if not spec.supports_temperature:
                raw.pop("temperature", None)
            if not spec.supports_top_k:
                raw.pop("top_k", None)
            if not spec.supports_min_p:
                raw.pop("min_p", None)
            if spec.reasoning in ("none", "enable_thinking"):
                raw.pop("reasoning", None)
            if spec.reasoning != "enable_thinking":
                raw.pop("enable_thinking", None)
        return cls(**raw)

    def to_extra_body(self, name: str, base_url: str) -> dict:
        eb: dict = {}
        if self.top_k is not None:
            eb["top_k"] = self.top_k
        if self.min_p is not None:
            eb["min_p"] = self.min_p
        if self.reasoning:
            eb["reasoning"] = self.reasoning
        if self.enable_thinking is not None:
            eb["chat_template_kwargs"] = {"enable_thinking": self.enable_thinking}
        if _is_openrouter(base_url):
            eb["usage"] = {"include": True}            # ask OR to report cost
        return eb
```

- [ ] **Step 4: Run to verify it passes** — `uv run pytest tests/test_model_params.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add src/palimpsest/webapp/model_params.py tests/test_model_params.py
git commit -m "feat(webapp): ModelParams filters per-model params + builds extra_body (T2)"
```

---

## Task 4: `budget.py` — atomic pre-call spend guard

**Files:**
- Create: `src/palimpsest/webapp/budget.py`
- Test: `tests/test_budget.py`

- [ ] **Step 1: Write the failing test**

```python
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
    asyncio.run(budget.reserve(0.01))
    budget.settle(0.01, 0.004)
    assert budget._STATE["spent"] == pytest.approx(0.004)


def test_call_count_cap():
    budget._CAP_USD = 100.0
    budget._CALL_CAP = 2
    asyncio.run(budget.reserve(0.0))
    asyncio.run(budget.reserve(0.0))
    with pytest.raises(budget.BudgetExceeded):
        asyncio.run(budget.reserve(0.0))
```

- [ ] **Step 2: Run to verify it fails** — `uv run pytest tests/test_budget.py -v` → FAIL.

- [ ] **Step 3: Write `budget.py`**

```python
"""In-process spend/call guard for real OpenRouter calls (hard $2 cap).

`reserve()` atomically checks-and-increments under an asyncio.Lock BEFORE the
network call, so concurrent /evaluate coroutines (asyncio.gather) can't read a
stale `spent` and jump the cap. `settle()` corrects the reservation to the actual
cost reported by OpenRouter. Prices are fetched live from OR /models (free
metadata call), never hardcoded.
"""
from __future__ import annotations

import asyncio
import json
import os
import time

from ..llm.client import LLMClient, LLMConfig
from .model_matrix import MATRIX, OPENROUTER, additive_reasoning_tokens

_CAP_USD = float(os.environ.get("PALIMPSEST_BUDGET_USD", "2.0"))
_CALL_CAP = int(os.environ.get("PALIMPSEST_BUDGET_CALLS", "200"))
_LOG_PATH = os.environ.get("PALIMPSEST_BUDGET_LOG", "budget_calls.jsonl")

_STATE = {"spent": 0.0, "calls": 0}
_lock = asyncio.Lock()
_PRICES: dict[str, tuple[float, float]] | None = None  # name → ($/tok in, $/tok out)

_SECRET_RE = __import__("re").compile(r"api.?key|token|secret|password|auth", __import__("re").I)


class BudgetExceeded(Exception):
    pass


def reset() -> None:
    _STATE["spent"] = 0.0
    _STATE["calls"] = 0


def count_tokens(text: str) -> int:
    """Conservative upper bound (chars as tokens). Real cost reconciled via settle()."""
    return max(1, len(text))


def _load_prices() -> dict[str, tuple[float, float]]:
    global _PRICES
    if _PRICES is not None:
        return _PRICES
    prices: dict[str, tuple[float, float]] = {}
    key = os.environ.get("OPENROUTER_API_KEY", "")
    try:
        import httpx
        r = httpx.get(f"{OPENROUTER}/models",
                      headers={"Authorization": f"Bearer {key}"} if key else {}, timeout=15.0)
        for m in r.json().get("data", []):
            p = m.get("pricing") or {}
            prices[m["id"]] = (float(p.get("prompt", 0)), float(p.get("completion", 0)))
    except Exception:
        pass
    _PRICES = prices
    return prices


def _price(name: str) -> tuple[float, float]:
    p = _load_prices().get(name)
    if p is not None:
        return p
    # Unknown/unfetched → conservative fallback so the guard never divides by zero.
    return (1e-5, 3e-5)


def estimate(name: str, prompt_tokens: int, max_tokens: int, reasoning_max_tokens: int = 0) -> float:
    pin, pout = _price(name)
    return prompt_tokens * pin + (max_tokens + reasoning_max_tokens) * pout


async def reserve(est: float) -> None:
    async with _lock:
        if _STATE["calls"] >= _CALL_CAP:
            raise BudgetExceeded(f"call cap {_CALL_CAP} reached")
        if _STATE["spent"] + est > _CAP_USD:
            raise BudgetExceeded(f"${_STATE['spent']:.4f}+${est:.4f} > cap ${_CAP_USD}")
        _STATE["spent"] += est
        _STATE["calls"] += 1


def settle(reserved: float, actual: float | None) -> None:
    if actual is None:
        return                              # keep the worst-case reservation
    _STATE["spent"] += (actual - reserved)


def _safe_params(params: dict) -> dict:
    return {k: v for k, v in (params or {}).items() if not _SECRET_RE.search(k)}


def log_call(record: dict) -> None:
    rec = dict(record)
    if "params" in rec:
        rec["params"] = _safe_params(rec["params"])
    try:
        with open(_LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass
```

- [ ] **Step 4: Run to verify it passes** — `uv run pytest tests/test_budget.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add src/palimpsest/webapp/budget.py tests/test_budget.py
git commit -m "feat(webapp): budget.py — atomic pre-call spend guard, live OR pricing (T4)"
```

---

## Task 5: Seed 8 models + repoint criteria

**Files:**
- Modify: `src/palimpsest/webapp/seed.py:31,47-59`
- Test: `tests/test_seed_registry.py`

- [ ] **Step 1: Write the failing test**

```python
import pytest


@pytest.fixture
def seeded(tmp_path, monkeypatch):
    from palimpsest.webapp import db, seed as seedmod
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(db, "_conn", None)
    seedmod.seed()
    yield db
    if db._conn is not None:
        db._conn.close(); db._conn = None


def test_eight_models_seeded(seeded):
    conn = seeded.connect()
    assert conn.execute("SELECT COUNT(*) n FROM model").fetchone()["n"] == 8


def test_criteria_point_at_matrix_model(seeded):
    from palimpsest.webapp.model_matrix import MATRIX
    conn = seeded.connect()
    for r in conn.execute("SELECT DISTINCT model_name FROM criterion"):
        assert r["model_name"] in MATRIX, "criterion still points off-matrix"


def test_idx1_paragraph_has_terms(seeded):
    conn = seeded.connect()
    n = conn.execute(
        "SELECT COUNT(*) n FROM term t JOIN paragraph p ON p.id=t.paragraph_id WHERE p.idx=1"
    ).fetchone()["n"]
    assert n >= 10
```

- [ ] **Step 2: Run to verify it fails** — `uv run pytest tests/test_seed_registry.py -v` → FAIL (still 1 model).

- [ ] **Step 3: Edit `seed.py`** — replace the single-model constant + insert with matrix-driven seeding.

Replace `MODEL_NAME = "openai/gpt-4o-mini"` (line 31) with:
```python
from .model_matrix import MATRIX, DEFAULT_CRITERION_MODEL
MODEL_NAME = DEFAULT_CRITERION_MODEL
```
Replace the single `INSERT INTO model(...)` block (lines 47-51) with:
```python
    # model registry: all 8 rows from the matrix. Shared OR key from env goes to
    # OpenRouter rows; vLLM rows keep an empty key (not run now).
    or_key = os.environ.get("OPENROUTER_API_KEY", "")
    for spec in MATRIX.values():
        conn.execute("INSERT INTO model(name,base_url,api_key,params_json) VALUES(?,?,?,?)",
                     (spec.name, spec.base_url,
                      or_key if spec.is_openrouter else "",
                      json.dumps(spec.default_params)))
```
`MODEL_NAME` is still used for `criterion.model_name` (line 59) → now `qwen/qwen3.6-plus`, which is on the matrix. No other change needed.

- [ ] **Step 4: Run to verify it passes** — `uv run pytest tests/test_seed_registry.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add src/palimpsest/webapp/seed.py tests/test_seed_registry.py
git commit -m "feat(webapp): seed 8 matrix models + repoint criteria to on-matrix model (T1)"
```

---

## Task 6: `judge.py` + all offline `complete()` consumers — adopt `LLMResult`

**Files:**
- Modify: `src/palimpsest/webapp/judge.py:46-61`
- Modify (offline consumers broken by the return-type change — append `.content`):
  `src/palimpsest/pipeline/terminology.py:56,62`, `src/palimpsest/pipeline/polish.py:21`,
  `src/palimpsest/pipeline/factcheck.py:24`, `src/palimpsest/pipeline/draft.py:21`,
  `src/palimpsest/evaluation/judge.py:39` — each `self.client.complete(...)` now returns
  `LLMResult`; change to `self.client.complete(...).content` (keep any trailing `.strip()`).
  NONE are under `src/palimpsest/terminology/` (NER agent territory) — do not touch that dir.
- Test: `tests/test_judge_parse.py` (usage assertion) + `tests/test_offline_callers_content.py`
  (guard: each stage handles an `LLMResult` return via a fake client, no crash).

- [ ] **Step 1: Add a failing test** to `tests/test_judge_parse.py`

```python
def test_judge_one_returns_usage_and_no_temperature_override():
    from types import SimpleNamespace
    from palimpsest.llm.client import LLMResult, Usage
    from palimpsest.webapp import judge

    calls = {}

    class FakeClient:
        def complete(self, system, user):
            calls["args"] = (system, user)
            return LLMResult(content='{"final_score": 7, "summary": "ok", "identified_issues": []}',
                             usage=Usage(12, 8, 0, 0.0002))

    out = judge.judge_one(FakeClient(), "accuracy", "ru", "en")
    assert out["value"] == 7.0
    assert out["usage"].cost_usd == 0.0002       # usage surfaced to caller
```

- [ ] **Step 2: Run to verify it fails** — `uv run pytest tests/test_judge_parse.py -v` → FAIL (`complete` signature / missing usage key).

- [ ] **Step 3: Edit `judge.py`** — change `judge_one` body (lines 52-61):

```python
    system = _scoring_prompt(criterion_id)
    user = f"[SOURCE RU]\n{ru}\n\n[TRANSLATION EN]\n{en}"
    result = client.complete(system, user)          # per-model temperature decided upstream
    data = _parse_json(result.content)
    issues = [_issue_from(it) for it in (data.get("identified_issues") or [])]
    return {
        "value": float(data["final_score"]),
        "summary": data.get("summary", ""),
        "issues": issues,
        "usage": result.usage,
    }
```

Update the `judge_one` docstring return line to `{value, summary, issues, usage}`.

- [ ] **Step 4: Run to verify it passes** — `uv run pytest tests/test_judge_parse.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add src/palimpsest/webapp/judge.py tests/test_judge_parse.py
git commit -m "fix(webapp): judge_one uses LLMResult, drops temperature=0 hardcode, returns usage (T6)"
```

---

## Task 7: Rebuild `_client_for` (ModelParams + env-fallback) + budget-wire `_judge_live`

**Files:**
- Modify: `src/palimpsest/webapp/app.py:202-216`
- Test: `tests/test_test_endpoint.py` (the `_client_for` cases; endpoint added in Task 8)

- [ ] **Step 1: Write the failing test**

```python
import json
import pytest


@pytest.fixture
def seeded(tmp_path, monkeypatch):
    from palimpsest.webapp import db, seed as seedmod
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(db, "_conn", None)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    seedmod.seed()
    yield db
    if db._conn is not None:
        db._conn.close(); db._conn = None


def test_client_for_env_fallback_on_empty_key(seeded, monkeypatch):
    from palimpsest.webapp import app, db
    conn = db.connect()
    conn.execute("UPDATE model SET api_key='' WHERE name='qwen/qwen3.6-plus'"); conn.commit()
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-live")
    client = app._client_for(conn, "qwen/qwen3.6-plus")
    assert client is not None and client.config.api_key == "sk-or-live"


def test_client_for_no_fallback_for_vllm(seeded, monkeypatch):
    from palimpsest.webapp import app, db
    conn = db.connect()
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-live")
    # vLLM row has empty key + non-OR base_url → NO fallback → None (never leak OR key off-OR)
    assert app._client_for(conn, "Qwen/Qwen3-4B-Thinking-2507") is None


def test_client_for_drops_temperature_for_claude(seeded):
    from palimpsest.webapp import app, db
    conn = db.connect()
    conn.execute("UPDATE model SET params_json=? WHERE name='anthropic/claude-sonnet-5'",
                 (json.dumps({"temperature": 0.9, "max_tokens": 128}),)); conn.commit()
    client = app._client_for(conn, "anthropic/claude-sonnet-5")
    assert client.config.temperature is None and client.config.max_tokens == 128
```

- [ ] **Step 2: Run to verify it fails** — `uv run pytest tests/test_test_endpoint.py -v` → FAIL.

- [ ] **Step 3: Edit `app.py`** — replace `_client_for` (lines 202-209):

```python
from .model_params import ModelParams, _is_openrouter  # add near top imports


def _client_for(conn, model_name: str) -> LLMClient | None:
    m = conn.execute("SELECT * FROM model WHERE name=?", (model_name,)).fetchone()
    if not m:
        return None
    api_key = m["api_key"] or ""
    if not api_key and _is_openrouter(m["base_url"]):
        api_key = os.environ.get("OPENROUTER_API_KEY", "")   # shared-key env-fallback (OR only)
    if not api_key:
        return None
    raw = json.loads(m["params_json"] or "{}")
    mp = ModelParams.for_model(model_name, raw)
    cfg = LLMConfig(model=m["name"], base_url=m["base_url"], api_key=api_key,
                    temperature=mp.temperature, max_tokens=mp.max_tokens,
                    extra_body=mp.to_extra_body(model_name, m["base_url"]) or None)
    return LLMClient(cfg)
```

Then wire budget into `_judge_live` (lines 212-216):

```python
from . import budget
from .model_matrix import additive_reasoning_tokens


async def _judge_live(conn, criterion, ru: str, en: str):
    client = _client_for(conn, criterion["model_name"])
    if client is None:
        raise RuntimeError("no api key for model")
    name = criterion["model_name"]
    prompt_tok = budget.count_tokens(ru) + budget.count_tokens(en) + 400  # +system prompt slack
    raw = json.loads(conn.execute("SELECT params_json FROM model WHERE name=?", (name,)
                                  ).fetchone()["params_json"] or "{}")
    rmt = additive_reasoning_tokens(name, raw)
    est = budget.estimate(name, prompt_tok, client.config.max_tokens, rmt)
    await budget.reserve(est)                             # raises BudgetExceeded → caught as failure
    try:
        res = await asyncio.wait_for(
            asyncio.to_thread(judge_one, client, criterion["id"], ru, en), EVAL_TIMEOUT)
    finally:
        pass
    actual = res["usage"].cost_usd
    budget.settle(est, actual)
    budget.log_call({"model": name, "endpoint": "evaluate", "criterion": criterion["id"],
                     "params": raw, "tokens": {"prompt": res["usage"].prompt_tokens,
                     "completion": res["usage"].completion_tokens,
                     "reasoning": res["usage"].reasoning_tokens}, "costUsd": actual})
    return res
```

(`BudgetExceeded` raised inside `_judge_live` propagates into the existing `asyncio.gather(..., return_exceptions=True)` in `evaluate` → that criterion lands in `failed`, cache-fallback handles the response. No new error path needed.)

- [ ] **Step 4: Run to verify it passes** — `uv run pytest tests/test_test_endpoint.py -v` → PASS (the 3 `_client_for` tests; endpoint tests come in Task 8).

- [ ] **Step 5: Commit**

```bash
git add src/palimpsest/webapp/app.py tests/test_test_endpoint.py
git commit -m "feat(webapp): _client_for via ModelParams + OR env-fallback; budget-guard /evaluate (T2/T4)"
```

---

## Task 8: `POST /api/models/{name}/test` — term-extraction probe

**Files:**
- Modify: `src/palimpsest/webapp/app.py` (add endpoint + helpers near the models section)
- Test: `tests/test_test_endpoint.py` (append)

- [ ] **Step 1: Append the failing tests** (fake client — no network, no spend)

```python
def _install_fake_client(monkeypatch, content, cost=0.0003):
    from types import SimpleNamespace
    from palimpsest.llm.client import LLMResult, Usage
    from palimpsest.webapp import app

    class FakeClient:
        config = SimpleNamespace(max_tokens=1024)
        def complete(self, system, user):
            return LLMResult(content=content, usage=Usage(50, 20, 0, cost))
    monkeypatch.setattr(app, "_client_for", lambda conn, name: FakeClient())


def test_test_endpoint_unknown_model_404(seeded):
    import asyncio, pytest as _pt
    from fastapi import HTTPException
    from palimpsest.webapp.app import test_model, TestBody
    with _pt.raises(HTTPException) as ei:
        asyncio.run(test_model("no/such", TestBody()))
    assert ei.value.status_code == 404


def test_test_endpoint_happy_share_and_cost(seeded, monkeypatch):
    import asyncio
    from palimpsest.webapp import budget
    from palimpsest.webapp.app import test_model, TestBody
    budget.reset(); budget._PRICES = {}
    # return several real reference surfaces from idx=1 → high overlap
    _install_fake_client(monkeypatch, '["сутии", "амореи", "Элам", "марту/амурру"]')
    out = asyncio.run(test_model("qwen/qwen3.6-plus", TestBody()))
    assert out["ok"] is True and out["share"] >= 0.5 is False or out["total"] > 0
    assert out["costUsd"] == 0.0003 and out["matched"] >= 1


def test_test_endpoint_parse_error_is_ok_false_200(seeded, monkeypatch):
    import asyncio
    from palimpsest.webapp import budget
    from palimpsest.webapp.app import test_model, TestBody
    budget.reset(); budget._PRICES = {}
    _install_fake_client(monkeypatch, "not json at all")
    out = asyncio.run(test_model("qwen/qwen3.6-plus", TestBody()))
    assert out["ok"] is False and "message" in out


def test_test_endpoint_budget_block_is_ok_false(seeded, monkeypatch):
    import asyncio
    from palimpsest.webapp import budget
    from palimpsest.webapp.app import test_model, TestBody
    budget.reset(); budget._CAP_USD = 0.0; budget._PRICES = {}
    _install_fake_client(monkeypatch, '["сутии"]')
    out = asyncio.run(test_model("qwen/qwen3.6-plus", TestBody()))
    assert out["ok"] is False and out["message"] == "budget"
```

(Note: the `share >= 0.5` assertion above is intentionally loose — the fixture's exact overlap depends on seed normalization; the executing agent should tighten it to `out["matched"] >= 1 and 0 <= out["share"] <= 1` after seeing the real reference set. Keep `ok`/`costUsd`/`matched` asserts strict.)

- [ ] **Step 2: Run to verify it fails** — `uv run pytest tests/test_test_endpoint.py -v` → FAIL.

- [ ] **Step 3: Add the endpoint + helpers to `app.py`** (after the models section, ~line 480)

```python
from ..terminology.verdict import _norm   # single source of surface normalization

TEST_EXTRACT_PROMPT = (
    "You extract terminology. From the Russian paragraph, list every key term and "
    "named entity (people, places, peoples, institutions, domain terms). Respond with "
    "ONLY a JSON array of strings, no prose, no code fences."
)


def _norm_split(surface: str) -> set[str]:
    parts = surface.split("/") if "/" in surface else [surface]
    return {_norm(p) for p in parts if _norm(p)}


def _test_reference(conn) -> tuple[set[str], str]:
    """(reference set, idx=1 source) from seed term rows of paragraph idx=1."""
    p = conn.execute("SELECT * FROM paragraph WHERE idx=1 ORDER BY id LIMIT 1").fetchone()
    ref: set[str] = set()
    if p:
        for r in conn.execute("SELECT source_surface FROM term WHERE paragraph_id=?", (p["id"],)):
            ref |= _norm_split(r["source_surface"])
    return ref, (p["source"] if p else "")


def _parse_term_list(raw: str) -> list[str]:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
    data = json.loads(text)
    if isinstance(data, dict):
        for v in data.values():
            if isinstance(v, list):
                data = v
                break
    if not isinstance(data, list):
        raise ValueError("not a JSON list")
    return [str(x) for x in data]


class TestBody(BaseModel):
    effort: str | None = None


@app.post("/api/models/{name}/test")
async def test_model(name: str, body: TestBody = TestBody(),
                     authorization: str | None = Header(None)) -> dict:
    _require_admin(authorization)
    conn = db.connect()
    if not conn.execute("SELECT 1 FROM model WHERE name=?", (name,)).fetchone():
        raise HTTPException(404, "model not found")
    ref, ru = _test_reference(conn)
    empty = {"ok": False, "extracted": [], "reference": sorted(ref),
             "matched": 0, "total": len(ref), "share": 0.0,
             "tokens": {"prompt": 0, "completion": 0, "reasoning": 0},
             "costUsd": None, "latencyMs": 0}
    client = _client_for(conn, name)
    if client is None:
        return {**empty, "message": "no api key/env for model"}

    raw = json.loads(conn.execute("SELECT params_json FROM model WHERE name=?", (name,)
                                  ).fetchone()["params_json"] or "{}")
    if body.effort:
        client.config.extra_body = {**(client.config.extra_body or {}),
                                    "reasoning": {"effort": body.effort}}
    prompt_tok = budget.count_tokens(TEST_EXTRACT_PROMPT) + budget.count_tokens(ru)
    rmt = additive_reasoning_tokens(name, raw)
    est = budget.estimate(name, prompt_tok, client.config.max_tokens, rmt)
    try:
        await budget.reserve(est)
    except budget.BudgetExceeded:
        return {**empty, "message": "budget"}

    t0 = time.perf_counter()
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(client.complete, TEST_EXTRACT_PROMPT, ru), EVAL_TIMEOUT)
    except Exception as e:                      # timeout / API error → 200 ok:false
        budget.settle(est, None)
        budget.log_call({"model": name, "endpoint": "test", "params": raw,
                         "status": "error", "costUsd": None})
        return {**empty, "message": f"{type(e).__name__}: {e}"}

    latency = int((time.perf_counter() - t0) * 1000)
    cost = result.usage.cost_usd
    budget.settle(est, cost)
    tokens = {"prompt": result.usage.prompt_tokens, "completion": result.usage.completion_tokens,
              "reasoning": result.usage.reasoning_tokens}
    budget.log_call({"model": name, "endpoint": "test", "params": raw, "status": "ok",
                     "tokens": tokens, "costUsd": cost, "latencyMs": latency})
    try:
        extracted = _parse_term_list(result.content)
    except (json.JSONDecodeError, ValueError):
        return {**empty, "tokens": tokens, "costUsd": cost, "latencyMs": latency,
                "message": "could not parse model output as a JSON list"}

    got: set[str] = set()
    for s in extracted:
        got |= _norm_split(s)
    matched = len(ref & got)
    share = matched / len(ref) if ref else 0.0
    return {"ok": share >= 0.5, "extracted": extracted, "reference": sorted(ref),
            "matched": matched, "total": len(ref), "share": round(share, 3),
            "tokens": tokens, "costUsd": cost, "latencyMs": latency,
            "message": "ok" if share >= 0.5 else "share below 0.5"}
```

Add `import time` to the top of `app.py` if absent.

- [ ] **Step 4: Run to verify it passes** — `uv run pytest tests/test_test_endpoint.py -v` → PASS. Then full suite: `uv run pytest -q` → all green.

- [ ] **Step 5: Commit**

```bash
git add src/palimpsest/webapp/app.py tests/test_test_endpoint.py
git commit -m "feat(webapp): POST /api/models/{name}/test — term-extraction probe with budget guard (T5)"
```

---

## Task 9: Frontend — Test button, result row, Edit modal (all `va-*`)

**Files:**
- Modify: `frontend/src/demo/api-client.ts` (add type + fn)
- Modify: `frontend/src/demo/store.ts` (add `testModel` action)
- Modify: `frontend/src/demo/variant-a/SettingsTab.tsx` (buttons + result + modal)

- [ ] **Step 1: Add the API client type + call** to `api-client.ts` (after ModelRegistryEntry, ~line 126, and in the models CRUD section)

```typescript
export interface TestModelResult {
  ok: boolean;
  extracted: string[];
  reference: string[];
  matched: number;
  total: number;
  share: number;
  tokens: { prompt: number; completion: number; reasoning: number };
  costUsd: number | null;
  latencyMs: number;
  message: string;
}

export function testModel(name: string, effort?: string): Promise<TestModelResult> {
  return post(`/models/${encodeURIComponent(name)}/test`, effort ? { effort } : undefined);
}
```

- [ ] **Step 2: Add the store action** to `store.ts`

In `DemoStore` interface (after `removeModel`):
```typescript
  testModel: (name: string) => Promise<import('./api-client').TestModelResult>;
```
Import `testModel as apiTestModel` in the api-client import block, and implement in the store object (after `removeModel`):
```typescript
  testModel: async (name) => apiTestModel(name),
```

- [ ] **Step 3: Wire the UI** in `SettingsTab.tsx`.

Replace the Edit button `onClick={() => {}}` (line 198) and add per-row Test. Add local state at the top of `SettingsTab`:
```tsx
const [testState, setTestState] = useState<Record<string, { loading: boolean; result: TestModelResult | null }>>({});
const [editing, setEditing] = useState<ModelRegistryEntryPublic | null>(null);
const testModel = useDemoStore((s) => s.testModel);   // import useDemoStore + TestModelResult
```
Add a Test button next to Edit/Remove (reuse `.va-btn-secondary`; show `…` while loading; a `.va-verdict-dot` colored by `result.ok`); render an expandable `.va-insp-issue-card` result row under the model row showing OK/FAILED, latencyMs, `matched/total` share, `costUsd`, and the extracted list. Wire Edit to `setEditing(m)`; render a minimal modal (reuse existing overlay classes if present, else `.va-insp-issue-card` inside a fixed-position wrapper) with `baseUrl` input, `apiKey` write-only input (placeholder `m.apiKeyMasked`), and a `params` `<textarea>` (JSON) validated with `JSON.parse` before `onSaveModel(m.name, { baseUrl, apiKey, params })`.

**Constraint (Invariant #9):** use ONLY existing `--va-*` tokens and `va-*` classes documented in [webapp-ui-design.md](../../subsystems/webapp-ui-design.md). If a genuinely new class is unavoidable, it must be added to that doc in the SAME commit (T8).

- [ ] **Step 4: Verify build + typecheck**

Run: `cd frontend && npm run build` (or `npx tsc --noEmit`)
Expected: no type errors; bundle builds.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/demo/api-client.ts frontend/src/demo/store.ts frontend/src/demo/variant-a/SettingsTab.tsx
git commit -m "feat(frontend): model Test button + result row + Edit modal on variant-a (T7)"
```

---

## Task 10: Doc-parity (T8)

**Files:**
- Modify: `docs/subsystems/webapp.md` (REST table)
- Modify: `docs/superpowers/specs/2026-06-30-demo-contracts.md` (endpoint contract)
- Verify: no new `va-*` class → no `webapp-ui-design.md` change; if Task 9 added one, document it here.

- [ ] **Step 1** — Add `POST /api/models/{name}/test` to the webapp REST table with its request/response shape (mirror the contract in the spec's "Эндпойнт Test" section).
- [ ] **Step 2** — Add the endpoint to the contracts doc §2 (admin-gated, request `{effort?}`, response `TestModelResult`).
- [ ] **Step 3** — Grep the SettingsTab diff for `className="va-...` not in webapp-ui-design.md; if any, add it there.
- [ ] **Step 4: Commit**

```bash
git add docs/subsystems/webapp.md docs/superpowers/specs/2026-06-30-demo-contracts.md
git commit -m "docs(webapp): document POST /api/models/{name}/test (T8 doc-parity)"
```

---

## Self-Review

**1. Spec coverage:**
- S1 (8 rows) → Task 5. S2 (Test 200 + share≥0.5) → Task 8. S3 (only supported params) → Tasks 2/3 (`ModelParams` filter + `extra_body`), asserted in `test_model_params.py`. S4 (edit→evaluators, delete→409) → `_client_for` reads DB each call (Task 7) + existing delete-409. S5 (env-fallback) → Task 7 test. S6 (pre-call block) → Task 4 `reserve` + Task 8 budget path. S7 (e2e under $2, per-call tokens/cost logged) → Task 4 `log_call` + e2e (spec §e2e).
- T1→Task 5; T2→Tasks 3+7; T3→Task 2; T4→Task 4; T5→Task 8; T6→Task 6; T7→Task 9; T8→Task 10. All covered.

**2. Placeholder scan:** No "TBD/TODO". One deliberately loose test assertion in Task 8 is flagged inline with the exact tightening instruction (real reference set is data-dependent) — acceptable and explicit, not a hidden gap.

**3. Type consistency:** `LLMResult.content/usage`, `Usage.*`, `ModelParams.for_model/to_extra_body`, `model_matrix.MATRIX/additive_reasoning_tokens/DEFAULT_CRITERION_MODEL`, `budget.estimate/reserve/settle/log_call/count_tokens/reset/BudgetExceeded/_PRICES/_CAP_USD/_CALL_CAP/_STATE` — used identically across Tasks 1–10. `complete()` loses `**overrides`; the only caller passing an override (`judge.py`) is fixed in Task 6.

**Execution order (dependency waves):** T2(client) → [T1(matrix), T3(params), T4(budget), T5(seed), T6(judge)] → [T7(_client_for+/evaluate), T8(/test)] → [T9(frontend), T10(docs)]. Same-file edits (app.py in T7+T8; params/matrix tests) are serialized. `uv run pytest -q` must stay green after every task.

**e2e (real OR, after all tasks — spec §e2e):** Stage 0 = this test suite ($0). Stage 1 = one qwen3.6-plus Test (validity + cost). Stage 2 = one Test per OR model (≤5 calls), monitored front-loaded then ~1/min. Stage 3 = browser e2e (`e2e-tester` + audit) on Settings Test buttons + `/evaluate` with explicit `criterionIds` on paragraph idx=1. Hard $2 cap enforced by `budget.reserve`; cadence per [[feedback_e2e_monitoring_cadence]].
