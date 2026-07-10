"""is_transient_error lives in palimpsest.llm.client (by design all LLM/
openai access goes through this module). app.py's `_judge_live` retry loop
imports it from here instead of importing `openai` itself.

Classification semantics (unchanged from the old app.py `_is_transient`):
Timeout/Connection/RateLimit/InternalServer/5xx APIStatusError -> True;
4xx, everything else -> False; never treats CancelledError as transient (it
must always propagate to cancel the task).

Malformed provider response bodies (2026-07-10 wiki-eval v2 pilot, Novita):
`LLMClient.complete` wraps ONLY its own transport call
(`chat.completions.create`) so a non-JSON HTTP body raises
`MalformedProviderResponseError` -> transient (True); a bare
`json.JSONDecodeError` (as raised by caller-side content parsing, e.g.
webapp `judge_one`'s `_parse_json` on the model's own malformed reply text)
stays -> False, since it never goes through that wrapper. See
`test_complete_wraps_transport_json_decode_error` below for the wrapping
behavior itself, in addition to the classifier tests.
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import httpx
import openai
import pytest

from palimpsest.llm.client import (
    LLMClient,
    LLMConfig,
    MalformedProviderResponseError,
    is_transient_error,
)


def _status_error(cls, status):
    resp = httpx.Response(status, request=httpx.Request("POST", "http://x"))
    return cls("boom", response=resp, body=None)


def _response_validation_error():
    resp = httpx.Response(200, request=httpx.Request("POST", "http://x"), content=b"not json")
    return openai.APIResponseValidationError(response=resp, body=None)


@pytest.mark.parametrize("exc", [
    TimeoutError("t"),
    openai.APITimeoutError(request=httpx.Request("POST", "http://x")),
    openai.APIConnectionError(request=httpx.Request("POST", "http://x")),
    _status_error(openai.RateLimitError, 429),
    _status_error(openai.InternalServerError, 500),
    _status_error(openai.APIStatusError, 503),
    MalformedProviderResponseError("Expecting value: line 169 column 1 (char 924)"),
    _response_validation_error(),
])
def test_transient_errors_classified_true(exc):
    assert is_transient_error(exc) is True


@pytest.mark.parametrize("exc", [
    _status_error(openai.AuthenticationError, 401),
    _status_error(openai.BadRequestError, 400),
    _status_error(openai.APIStatusError, 404),
    RuntimeError("no api key for model"),
    ValueError("nope"),
])
def test_deterministic_errors_classified_false(exc):
    assert is_transient_error(exc) is False


def test_content_level_json_decode_error_stays_deterministic():
    """Regression pin for the judge_one path (2026-07-10 safety analysis):
    a plain json.JSONDecodeError -- as raised by webapp judge_one's
    `_parse_json(result.content)` when the MODEL's own reply text is
    malformed -- must stay non-transient. Only LLMClient.complete's own
    transport-call wrapping (-> MalformedProviderResponseError, tested
    above) is transient; `is_transient_error` itself never special-cases
    a bare JSONDecodeError, precisely so a caller-side content parse
    failure is never silently retried."""
    assert is_transient_error(json.JSONDecodeError("bad json", "doc", 0)) is False


class _RaisingCompletions:
    """Fake `chat.completions` whose `.create()` mimics httpx's
    `response.json()` blowing up inside the openai SDK on a non-JSON HTTP
    body -- the exact failure observed live on Novita, 2026-07-10."""

    def create(self, **kwargs):
        raise json.JSONDecodeError("Expecting value", "line 169 column 1 (char 924)", 0)


def test_complete_wraps_transport_json_decode_error():
    """LLMClient.complete's own transport call (chat.completions.create)
    turns a raw json.JSONDecodeError into MalformedProviderResponseError --
    the transport/content disambiguation this whole design rests on."""
    cfg = LLMConfig(model="m", base_url="u", api_key="k", max_tokens=64)
    client = LLMClient.__new__(LLMClient)
    client.config = cfg
    client._client = SimpleNamespace(chat=SimpleNamespace(completions=_RaisingCompletions()))
    with pytest.raises(MalformedProviderResponseError):
        client.complete("system", "user")


def test_cancelled_error_never_classified_transient():
    # asyncio.CancelledError must propagate to cancel the task, never be
    # swallowed into a retry loop.
    assert is_transient_error(asyncio.CancelledError()) is False


def test_webapp_has_no_direct_openai_import():
    import pathlib
    import re
    root = pathlib.Path(__file__).resolve().parents[1] / "src/palimpsest/webapp"
    pattern = re.compile(r"^\s*(import openai\b|from openai\b)", re.M)
    for p in root.rglob("*.py"):
        assert not pattern.search(p.read_text()), p
