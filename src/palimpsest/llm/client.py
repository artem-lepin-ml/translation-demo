"""Thin OpenAI-compatible client. Same interface for vLLM, xAI, OpenAI, OpenRouter."""
from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass

import openai
from openai import OpenAI

from ..config import ModelConfig

# CloseRouter's WAF blocks the OpenAI SDK's default User-Agent (HTTP 403 "Your
# request was blocked") before it ever routes to a model — any neutral UA
# passes. Sent on every client so identical code works against CloseRouter,
# OpenRouter, OpenAI and local vLLM.
USER_AGENT = "palimpsest-llm/1.0"

# Hard ceiling on concurrent in-flight requests when a caller fans out. Providers
# run ~90% per-route success under load, so parallelism stays bounded (owner
# directive); callers gate their own fan-out on this.
DEFAULT_MAX_CONCURRENCY = 4


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
    seed: int | None = None               # None → omit (capability-gated, see model_matrix.supports_seed)
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
        # OpenRouter surfaces `cost`; CloseRouter surfaces `cost_usd`.
        cost = extra.get("cost")
        if cost is None:
            cost = extra.get("cost_usd")
    return Usage(int(getattr(u, "prompt_tokens", 0) or 0),
                 int(getattr(u, "completion_tokens", 0) or 0),
                 int(reasoning or 0),
                 float(cost) if cost is not None else None)


def is_transient_error(exc: BaseException) -> bool:
    """A provider error worth retrying: timeout / connection drop / 429 / 5xx.

    Deterministic errors (bad request, auth, unparseable JSON) are NOT
    transient — a retry would just burn another paid call and fail the same
    way. ``asyncio.CancelledError`` is never treated as transient: it must
    always propagate to cancel the task, never be swallowed into a retry.

    Single source of truth for this classification (by design all LLM/
    openai access goes through this module); callers outside `palimpsest.llm`
    must not import `openai` directly just to replicate it.
    """
    if isinstance(exc, asyncio.CancelledError):
        return False
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError,
                        openai.APITimeoutError, openai.APIConnectionError,
                        openai.RateLimitError, openai.InternalServerError)):
        return True
    status = getattr(exc, "status_code", None)
    return isinstance(exc, openai.APIStatusError) and isinstance(status, int) and status >= 500


class LLMClient:
    """Stateless wrapper over chat.completions. One instance per model. No retries."""

    def __init__(self, config: LLMConfig):
        self.config = config
        self._client = OpenAI(base_url=config.base_url, api_key=config.api_key,
                              max_retries=0, timeout=30.0,
                              default_headers={"User-Agent": USER_AGENT})

    def complete(self, system: str, user: str) -> LLMResult:
        kwargs: dict = {
            "model": self.config.model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "max_tokens": self.config.max_tokens,
        }
        if self.config.temperature is not None:
            kwargs["temperature"] = self.config.temperature
        if self.config.seed is not None:
            kwargs["seed"] = self.config.seed
        if self.config.extra_body:
            kwargs["extra_body"] = self.config.extra_body
        resp = self._client.chat.completions.create(**kwargs)
        content = resp.choices[0].message.content or ""
        return LLMResult(content=content, usage=_extract_usage(resp))

    def complete_retrying(self, system: str, user: str, *, attempts: int = 3,
                          backoff: tuple[float, ...] = (1.0, 3.0, 9.0)) -> LLMResult:
        """`complete()` with bounded retries on transient errors only.

        Retries 429/5xx/timeout/connection failures (`is_transient_error`) up to
        `attempts` times, sleeping `backoff[i]` between tries; deterministic
        errors (400/401/malformed JSON) propagate on the first hit — a retry
        would only burn another paid call and fail the same way. Owner directive
        for CloseRouter's ~90% per-route success: 3 attempts, 1s/3s/9s backoff.
        """
        for i in range(attempts):
            try:
                return self.complete(system, user)
            except Exception as exc:  # noqa: BLE001 — re-raised unless transient
                if not is_transient_error(exc) or i == attempts - 1:
                    raise
                time.sleep(backoff[min(i, len(backoff) - 1)])
        raise RuntimeError("unreachable")  # pragma: no cover
