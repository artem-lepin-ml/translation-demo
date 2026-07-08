"""Async LLM client. OpenAI-compatible endpoints + Anthropic SDK path for extended thinking."""
from __future__ import annotations

import asyncio
import json
import os
import random
import sys
from dataclasses import dataclass
from typing import Literal

import anthropic
import openai
from anthropic import AsyncAnthropic
from openai import AsyncOpenAI

from ..config import ModelConfig


# Anthropic SDK appends `/v1/messages` to the base_url itself, so we must hand it
# the proxy host without the `/v1` suffix that the yaml entry uses for OpenAI-compat
# chat/completions. Applied only when the yaml-declared provider is "anthropic".
def _anthropic_base_url(base_url: str) -> str:
    return base_url.rstrip("/").removesuffix("/v1")


# Fallback Anthropic tool input schema when the caller asks for JSON-object
# output but supplies no `tool_schema` and no `json_schema` in `response_format`.
# Anthropic needs *some* declared schema for the forced-tool path to work
# reliably; an empty `properties` block makes Opus drop synthetic single-key
# wrappers (`{"$PARAMETER_NAME": …}`). Callers with a real contract should pass
# `tool_schema=` to `complete()` — see scoring._JUDGE_TOOL_SCHEMA.
_GENERIC_TOOL_SCHEMA: dict = {"type": "object", "additionalProperties": True}


@dataclass(slots=True)
class LLMResult:
    """One LLM call's output. `usage` is the provider's raw usage block
    (e.g. OpenAI/CloseRouter: prompt_tokens/completion_tokens/total_tokens
    [+cost], Anthropic: input_tokens/output_tokens). None when the SDK
    didn't surface usage (e.g. stream without include_usage)."""

    content: str
    usage: dict | None = None


def _usage_to_dict(usage) -> dict | None:
    """Best-effort serialization of a provider usage block. OpenAI/Anthropic
    SDKs return pydantic v2 models with extra='allow', so model_dump
    surfaces non-standard fields like CloseRouter's `cost` automatically."""
    if usage is None:
        return None
    if hasattr(usage, "model_dump"):
        return usage.model_dump(exclude_none=False)
    if hasattr(usage, "__dict__"):
        return {k: v for k, v in vars(usage).items() if not k.startswith("_")}
    try:
        return dict(usage)
    except Exception:
        return None


@dataclass(slots=True)
class LLMConfig:
    """Runtime LLM connection params. Mirrors ModelConfig + resolved api_key.

    `or_style` is True iff the yaml literal base_url is OpenRouter — that
    declaration drives ephemeral-marker dispatch in _complete_openai
    (Decision 3 in the spec), regardless of any runtime base_url override.
    """

    model: str
    base_url: str
    api_key: str
    max_tokens: int

    temperature: float | None = None
    top_p: float | None = None
    top_k: int | None = None
    min_p: float | None = None
    reasoning_effort: str | None = None
    extra_body: dict | None = None
    or_style: bool = False
    supports_structured_output: bool = False
    stream: bool = False
    provider: str | None = None

    @classmethod
    def from_model_config(cls, cfg: ModelConfig) -> LLMConfig:
        or_style = cfg.base_url == "https://openrouter.ai/api/v1"
        base_url = cfg.base_url
        if or_style:
            base_url = os.environ.get("OPENROUTER_BASE_URL", base_url)
        return cls(
            model=cfg.name,
            base_url=base_url,
            api_key=os.environ[cfg.api_key_env],
            max_tokens=cfg.max_tokens,
            temperature=cfg.temperature,
            top_p=cfg.top_p,
            top_k=cfg.top_k,
            min_p=cfg.min_p,
            reasoning_effort=cfg.reasoning_effort,
            extra_body=cfg.extra_body,
            or_style=or_style,
            supports_structured_output=cfg.supports_structured_output,
            stream=cfg.stream,
            provider=cfg.provider,
        )


Provider = Literal["openai", "anthropic"]


class EmptyContentError(Exception):
    """LLM returned 200 OK but empty `content` — treated as transient.

    Common with reasoning models on OpenRouter under load: tokens go into
    a reasoning channel and `content` is empty. Retry usually fixes it.
    """


# Transient errors that warrant a retry with backoff. Both SDKs ship their own
# class hierarchy, so we list both. APIStatusError is handled separately because
# we only retry 5xx, not 4xx.
_TRANSIENT_ERRORS = (
    openai.RateLimitError,
    openai.APIConnectionError,
    openai.APITimeoutError,
    anthropic.RateLimitError,
    anthropic.APIConnectionError,
    anthropic.APITimeoutError,
    EmptyContentError,
)

_RETRY_MAX_ATTEMPTS = 3         # 1 initial + 2 retries (spec D3).
_RETRY_BASE_SECONDS = 2.0       # exponent base; 2,4s with cap.
_RETRY_CAP_SECONDS = 8.0


def _retry_delay(attempt: int) -> float:
    """Exponential backoff with full jitter. `attempt` is 1-based retry number."""
    raw = min(_RETRY_CAP_SECONDS, _RETRY_BASE_SECONDS * (2 ** (attempt - 1)))
    return random.uniform(0, raw)


class LLMClient:
    """One client per model. Provider is picked from the yaml `provider:` flag when set, falling back to a base_url sniff; dispatch is per-call."""

    # 2**20 is "effectively unlimited" for our pilot workloads; spec D2 keeps
    # this as the no-op behavior when max_concurrency <= 0.
    _UNLIMITED: int = 2**20

    def __init__(self, config: LLMConfig, *, max_concurrency: int = 0):
        self.config = config
        # Explicit yaml flag wins; fall back to base_url sniff for legacy entries
        # that talk to api.anthropic.com directly.
        if config.provider == "anthropic" or "anthropic.com" in config.base_url:
            self._provider = "anthropic"
        else:
            self._provider = "openai"
        if self._provider == "anthropic":
            self._anthropic = AsyncAnthropic(
                api_key=config.api_key,
                base_url=_anthropic_base_url(config.base_url),
            )
        else:
            self._openai = AsyncOpenAI(base_url=config.base_url, api_key=config.api_key)
        effective = max_concurrency if max_concurrency > 0 else self._UNLIMITED
        self._gate = asyncio.Semaphore(effective)

    async def complete(
        self,
        system: str,
        user: str,
        *,
        thinking: bool = False,
        thinking_budget_tokens: int | None = None,
        tool_schema: dict | None = None,
        **overrides,
    ) -> LLMResult:
        """Send one prompt to the configured LLM. Retries transient failures
        (RateLimit / connection / timeout / empty-content) with exponential
        backoff up to _RETRY_MAX_ATTEMPTS. Raises the last exception only when
        every attempt has been exhausted. The internal semaphore (set via
        max_concurrency at construction) caps simultaneous SDK calls.

        `tool_schema` is the Anthropic-only escape hatch for callers that
        request JSON-object output and need a concrete tool input_schema
        (Anthropic's `tool_use` path needs declared properties to behave
        reliably on Opus 4.7). Ignored on the OpenAI path.

        Returns an LLMResult carrying the response text and the provider's
        raw usage block (when present). Callers that only care about the text
        unpack `result.content`; scoring also reads `result.usage` to log
        token counts and cost per row.
        """
        last_exc: Exception | None = None
        for attempt in range(1, _RETRY_MAX_ATTEMPTS + 1):
            try:
                async with self._gate:
                    if self._provider == "anthropic":
                        result = await self._complete_anthropic(
                            system, user, thinking, thinking_budget_tokens,
                            tool_schema, overrides,
                        )
                    else:
                        result = await self._complete_openai(system, user, overrides)
                if not result.content.strip():
                    raise EmptyContentError(
                        f"{self.config.model}: empty content from provider"
                    )
                return result
            except _TRANSIENT_ERRORS as exc:
                last_exc = exc
            except (openai.APIStatusError, anthropic.APIStatusError) as exc:
                status = getattr(exc, "status_code", None)
                if status is None or status < 500:
                    raise
                last_exc = exc

            if attempt >= _RETRY_MAX_ATTEMPTS:
                break
            delay = _retry_delay(attempt)
            print(
                f"[retry] {self.config.model} attempt {attempt}/{_RETRY_MAX_ATTEMPTS} "
                f"after {type(last_exc).__name__}: sleep {delay:.1f}s",
                file=sys.stderr,
                flush=True,
            )
            await asyncio.sleep(delay)

        assert last_exc is not None
        raise last_exc

    async def _complete_openai(self, system: str | None, user: str, overrides: dict) -> LLMResult:
        # Build messages. When the yaml entry declared itself OR-style, wrap
        # system in array-content with cache_control: ephemeral. Anthropic-via-OR
        # honors this directly; Gemini/Qwen/DeepSeek-via-OR best-effort. For
        # OpenAI direct (or_style=False), plain string + automatic prefix caching.
        messages: list[dict] = [{"role": "user", "content": user}]
        if system is not None:
            if self.config.or_style:
                system_content: str | list[dict] = [
                    {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
                ]
            else:
                system_content = system
            messages.insert(0, {"role": "system", "content": system_content})

        # Send each sampling param only if explicitly set (None means "let provider decide").
        # Standard OpenAI Chat Completions params go top-level; non-OpenAI params
        # (top_k, min_p — accepted by OpenRouter / vLLM / DashScope but rejected by
        # the OpenAI SDK's client-side validation) go through extra_body.
        kwargs: dict = {
            "model": self.config.model,
            "messages": messages,
            "max_completion_tokens": overrides.get("max_tokens", self.config.max_tokens),
            "timeout": 1200.0,
            "stream": self.config.stream
        }
        for field in ("temperature", "top_p", "reasoning_effort"):
            value = overrides.get(field, getattr(self.config, field))
            if value is not None:
                kwargs[field] = value

        # Per-call structured-output: caller passes `response_format` uniformly,
        # but we only forward it to providers that support it (set via
        # supports_structured_output in models.yaml). Providers without
        # support (e.g. local vLLM started without guided-decoding) would
        # otherwise 400 on the unknown param.
        response_format = overrides.get("response_format")
        if response_format is not None and self.config.supports_structured_output:
            kwargs["response_format"] = response_format

        extra_body: dict = dict(self.config.extra_body) if self.config.extra_body else {}
        for field in ("top_k", "min_p"):
            value = overrides.get(field, getattr(self.config, field))
            if value is not None:
                extra_body[field] = value
        kwargs["extra_body"] = extra_body or None

        resp = await self._openai.chat.completions.create(**kwargs)

        if kwargs["stream"]:
            full_content = []
            usage = None
            async for chunk in resp:
                if chunk.choices and chunk.choices[0].delta.content:
                    full_content.append(chunk.choices[0].delta.content)
                chunk_usage = getattr(chunk, "usage", None)
                if chunk_usage is not None:
                    usage = chunk_usage
            return LLMResult(content="".join(full_content), usage=_usage_to_dict(usage))

        return LLMResult(
            content=resp.choices[0].message.content or "",
            usage=_usage_to_dict(getattr(resp, "usage", None)),
        )

    async def _complete_anthropic(
        self,
        system: str,
        user: str,
        thinking: bool,
        budget_tokens: int | None,
        tool_schema: dict | None,
        overrides: dict,
    ) -> LLMResult:
        kwargs: dict = {
            "model": self.config.model,
            "max_tokens": overrides.get("max_tokens", self.config.max_tokens),
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        if thinking:
            # Anthropic requires budget_tokens when thinking is enabled.
            kwargs["thinking"] = {
                "type": "enabled",
                "budget_tokens": budget_tokens if budget_tokens is not None else 4000,
            }
        else:
            temp = overrides.get("temperature", self.config.temperature)
            if temp is not None:
                kwargs["temperature"] = temp

        # Structured output: Anthropic has no `response_format`; we coerce
        # caller's request into a forced tool-call. Schema priority:
        #   1. explicit `tool_schema` kwarg (caller's contract — e.g. scoring),
        #   2. `response_format.json_schema.schema` when the caller picked the
        #      json_schema form,
        #   3. a minimal generic object schema as a last-resort fallback.
        # Anthropic ≠ OpenAI: declared `properties` actually shape the tool
        # input on Opus / Sonnet, so callers are expected to supply a real
        # schema via `tool_schema`. The generic fallback exists only so the
        # request doesn't fail outright for one-off probes.
        response_format = overrides.get("response_format")
        input_schema: dict | None = None
        if response_format is not None and self.config.supports_structured_output:
            if tool_schema is not None:
                input_schema = tool_schema
            elif response_format.get("type") == "json_schema":
                input_schema = response_format["json_schema"]["schema"]
            elif response_format.get("type") == "json_object":
                input_schema = _GENERIC_TOOL_SCHEMA
            if input_schema is not None:
                kwargs["tools"] = [{
                    "name": "emit_response",
                    "description": "Emit the structured response.",
                    "input_schema": input_schema,
                }]
                kwargs["tool_choice"] = {"type": "tool", "name": "emit_response"}

        resp = await self._anthropic.messages.create(**kwargs)

        # Prefer the forced tool's input as JSON; some Claude variants ignore
        # `tool_choice` when the prompt insists on "return JSON only" — they emit
        # a text block whose body is already valid JSON, which parse_judge_response
        # accepts. Concatenate text blocks as the fallback.
        # Schema's `required` keys drive the Opus-4.7 unwrap heuristic below.
        required = tuple(input_schema.get("required", ())) if input_schema else ()
        for b in resp.content:
            if getattr(b, "type", None) == "tool_use" and b.input is not None:
                payload = b.input
                # Opus 4.7 occasionally wraps the structured payload under a
                # single synthetic key ("response", "$PARAMETER_NAME", …) — peek
                # one level down when an expected required key is missing at
                # the top level but present inside.
                if (
                    required
                    and isinstance(payload, dict)
                    and len(payload) == 1
                    and isinstance(next(iter(payload.values())), dict)
                ):
                    only_key, only = next(iter(payload.items()))
                    if any(k not in payload and k in only for k in required):
                        print(
                            f"[anthropic-unwrap] {self.config.model}: unwrapped {only_key!r}",
                            file=sys.stderr,
                            flush=True,
                        )
                        payload = only
                content = json.dumps(payload)
                break
        else:
            content = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
        return LLMResult(content=content, usage=_usage_to_dict(getattr(resp, "usage", None)))
