"""is_transient_error lives in palimpsest.llm.client (by design all LLM/
openai access goes through this module). app.py's `_judge_live` retry loop
imports it from here instead of importing `openai` itself.

Classification semantics (unchanged from the old app.py `_is_transient`):
Timeout/Connection/RateLimit/InternalServer/5xx APIStatusError -> True;
4xx, JSONDecodeError, everything else -> False; never treats CancelledError
as transient (it must always propagate to cancel the task).
"""
from __future__ import annotations

import asyncio
import json

import httpx
import openai
import pytest

from palimpsest.llm.client import is_transient_error


def _status_error(cls, status):
    resp = httpx.Response(status, request=httpx.Request("POST", "http://x"))
    return cls("boom", response=resp, body=None)


@pytest.mark.parametrize("exc", [
    TimeoutError("t"),
    openai.APITimeoutError(request=httpx.Request("POST", "http://x")),
    openai.APIConnectionError(request=httpx.Request("POST", "http://x")),
    _status_error(openai.RateLimitError, 429),
    _status_error(openai.InternalServerError, 500),
    _status_error(openai.APIStatusError, 503),
])
def test_transient_errors_classified_true(exc):
    assert is_transient_error(exc) is True


@pytest.mark.parametrize("exc", [
    _status_error(openai.AuthenticationError, 401),
    _status_error(openai.BadRequestError, 400),
    _status_error(openai.APIStatusError, 404),
    json.JSONDecodeError("bad json", "doc", 0),
    RuntimeError("no api key for model"),
    ValueError("nope"),
])
def test_deterministic_errors_classified_false(exc):
    assert is_transient_error(exc) is False


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
