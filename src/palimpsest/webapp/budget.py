"""In-process spend/call guard for real OpenRouter calls (hard $2 cap).

`reserve()` atomically checks-and-increments under an asyncio.Lock BEFORE the
network call, so concurrent /evaluate coroutines (asyncio.gather) can't read a
stale `spent` and jump the cap. `settle()` corrects the reservation to the actual
cost reported by OpenRouter. Prices are fetched live from OR /models (free
metadata call), never hardcoded.

`_STATE["generation"]` guards against a stale settle: `reset()` (admin action or
test isolation) increments it, `reserve()` captures the generation current at
reservation time, and `settle()` no-ops the spent-delta if the generation it was
given no longer matches — an in-flight call reserved before a reset must not
perturb the freshly-reset spend counter. The `calls` counter is NOT rolled back
by a stale settle either way (settle never touches `calls`) — `calls` tracks
"how many LLM calls were admitted", which stays true regardless of a later reset.
"""
from __future__ import annotations

import asyncio
import json
import os

from .model_matrix import OPENROUTER
from .secrets_guard import is_secret_key

_CAP_USD = float(os.environ.get("PALIMPSEST_BUDGET_USD", "2.0"))
_CALL_CAP = int(os.environ.get("PALIMPSEST_BUDGET_CALLS", "200"))
_LOG_PATH = os.environ.get("PALIMPSEST_BUDGET_LOG", "budget_calls.jsonl")

_STATE = {"spent": 0.0, "calls": 0, "generation": 0}
_lock = asyncio.Lock()
_PRICES: dict[str, tuple[float, float]] | None = None  # name → ($/tok in, $/tok out)


class BudgetExceeded(Exception):
    pass


def reset() -> None:
    _STATE["spent"] = 0.0
    _STATE["calls"] = 0
    _STATE["generation"] += 1


def count_tokens(text: str) -> int:
    """Conservative upper bound on BPE tokens: UTF-8 byte count (bytes >= tokens
    always, unlike char count which undercounts multi-byte scripts like
    Cyrillic). Real cost reconciled via settle()."""
    return max(1, len(text.encode("utf-8")))


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
        return {}                          # don't cache a failure — retry next call
    if not prices:
        return {}                          # don't cache an empty fetch — retry next call
    _PRICES = prices
    return _PRICES


def _price(name: str) -> tuple[float, float]:
    p = _load_prices().get(name)
    if p is not None:
        return p
    # Unknown/unfetched → conservative fallback so the guard never divides by zero.
    return (1e-5, 3e-5)


def estimate(name: str, prompt_tokens: int, max_tokens: int, reasoning_max_tokens: int = 0) -> float:
    pin, pout = _price(name)
    return prompt_tokens * pin + (max_tokens + reasoning_max_tokens) * pout


async def reserve(est: float) -> int:
    """Reserve ``est`` against the budget; returns the generation to pass to the
    matching ``settle()`` call so a reset in between can be detected."""
    async with _lock:
        if _STATE["calls"] >= _CALL_CAP:
            raise BudgetExceeded(f"call cap {_CALL_CAP} reached")
        if _STATE["spent"] + est > _CAP_USD:
            raise BudgetExceeded(f"${_STATE['spent']:.4f}+${est:.4f} > cap ${_CAP_USD}")
        _STATE["spent"] += est
        _STATE["calls"] += 1
        return _STATE["generation"]


async def settle(reserved: float, actual: float | None, generation: int) -> None:
    """Correct a reservation to the actual cost. No-ops the spent-delta if
    ``generation`` predates the current one (a ``reset()`` happened in between —
    the reservation it corrects no longer exists in the current budget epoch)."""
    if actual is None:
        return                              # keep the worst-case reservation
    async with _lock:
        if generation != _STATE["generation"]:
            return                          # stale settle — reservation was wiped by reset()
        _STATE["spent"] += (actual - reserved)


def snapshot() -> dict:
    return {"spentUsd": round(_STATE["spent"], 6), "capUsd": _CAP_USD,
            "calls": _STATE["calls"], "callCap": _CALL_CAP}


def _safe_params(params: dict) -> dict:
    return {k: v for k, v in (params or {}).items() if not is_secret_key(k)}


def log_call(record: dict) -> None:
    rec = dict(record)
    if "params" in rec:
        rec["params"] = _safe_params(rec["params"])
    try:
        with open(_LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass
