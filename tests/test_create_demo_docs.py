"""scripts/create_demo_docs.py: golden-token header propagation + the
session-cookie fallback (session isolation, 2026-07-16,
docs/superpowers/specs/2026-07-16-session-isolation.md
§"scripts/create_demo_docs.py"). No network access -- urllib.request.urlopen
is monkeypatched throughout; these tests only assert on the outgoing
urllib.request.Request objects the script builds, never on a real server."""
from __future__ import annotations

import email.message
import importlib.util
import json
import sys
from pathlib import Path

import pytest

_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "create_demo_docs.py"
_spec = importlib.util.spec_from_file_location("create_demo_docs", _SCRIPT_PATH)
create_demo_docs = importlib.util.module_from_spec(_spec)
sys.modules["create_demo_docs"] = create_demo_docs
_spec.loader.exec_module(create_demo_docs)


class _FakeResponse:
    def __init__(self, payload: dict, set_cookie: str | None = None):
        self._body = json.dumps(payload).encode("utf-8")
        self.headers = email.message.Message()
        if set_cookie:
            self.headers["Set-Cookie"] = set_cookie

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture(autouse=True)
def _reset_session_cookie(monkeypatch):
    # `_session_cookie` is a module-global tracked across the whole process
    # (by design — see the module's own docstring on it); reset it per test
    # so tests don't leak a cookie captured by an earlier one.
    monkeypatch.setattr(create_demo_docs, "_session_cookie", None)


@pytest.fixture()
def captured_requests(monkeypatch):
    captured = []

    def fake_urlopen(req, *a, **kw):
        captured.append(req)
        return _FakeResponse({"id": 42, "title": "Doc"})

    monkeypatch.setattr(create_demo_docs.urllib.request, "urlopen", fake_urlopen)
    return captured


def _header(req, name: str) -> str | None:
    """Case-insensitive header lookup on a urllib.request.Request — its own
    .headers dict keys are stored as `name.capitalize()` (e.g.
    "X-Golden-Session" -> "X-golden-session"), so a plain-cased lookup is
    fragile; this normalizes both sides."""
    lname = name.lower()
    for k, v in req.headers.items():
        if k.lower() == lname:
            return v
    return None


def test_post_json_sends_golden_header_when_token_given(captured_requests):
    create_demo_docs._post_json(
        "http://x/api/documents", {"a": 1}, golden_token="s3cr3t")
    req = captured_requests[0]
    assert _header(req, create_demo_docs.GOLDEN_TOKEN_HEADER) == "s3cr3t"


def test_post_json_omits_golden_header_without_token_or_cookie(captured_requests):
    create_demo_docs._post_json("http://x/api/documents", {"a": 1})
    req = captured_requests[0]
    assert _header(req, create_demo_docs.GOLDEN_TOKEN_HEADER) is None
    assert _header(req, "Cookie") is None


def test_get_json_sends_golden_header_when_token_given(captured_requests):
    create_demo_docs._get_json("http://x/api/documents/1", golden_token="s3cr3t")
    req = captured_requests[0]
    assert _header(req, create_demo_docs.GOLDEN_TOKEN_HEADER) == "s3cr3t"


def test_create_document_carries_the_token(tmp_path, captured_requests):
    payload_path = tmp_path / "doc.json"
    payload_path.write_text(json.dumps({
        "title": "T", "sourceLang": "de", "targetLang": "fr",
        "precompute": False, "paragraphs": [{"source": "s", "target": "t"}],
    }), encoding="utf-8")

    create_demo_docs.create_document("http://x", payload_path, golden_token="s3cr3t")
    assert _header(captured_requests[0], create_demo_docs.GOLDEN_TOKEN_HEADER) == "s3cr3t"


def test_poll_document_carries_the_token(monkeypatch):
    captured = []

    def fake_urlopen(req, *a, **kw):
        captured.append(req)
        return _FakeResponse({"termsStatus": "done", "translation": None, "precompute": None})

    monkeypatch.setattr(create_demo_docs.urllib.request, "urlopen", fake_urlopen)
    ok = create_demo_docs.poll_document(
        "http://x", 42, interval=0, timeout=5, golden_token="s3cr3t")
    assert ok is True
    assert _header(captured[0], create_demo_docs.GOLDEN_TOKEN_HEADER) == "s3cr3t"


def test_main_falls_back_to_env_var(tmp_path, monkeypatch, captured_requests):
    payload_path = tmp_path / "doc.json"
    payload_path.write_text(json.dumps({
        "title": "T", "sourceLang": "de", "targetLang": "fr",
        "precompute": False, "paragraphs": [{"source": "s", "target": "t"}],
    }), encoding="utf-8")
    monkeypatch.setenv(create_demo_docs.GOLDEN_TOKEN_ENV, "env-token")

    rc = create_demo_docs.main(["--base-url", "http://x", str(payload_path)])
    assert rc == 0
    assert _header(captured_requests[0], create_demo_docs.GOLDEN_TOKEN_HEADER) == "env-token"


def test_main_no_token_sends_no_golden_header(tmp_path, monkeypatch, captured_requests):
    payload_path = tmp_path / "doc.json"
    payload_path.write_text(json.dumps({
        "title": "T", "sourceLang": "de", "targetLang": "fr",
        "precompute": False, "paragraphs": [{"source": "s", "target": "t"}],
    }), encoding="utf-8")
    monkeypatch.delenv(create_demo_docs.GOLDEN_TOKEN_ENV, raising=False)

    rc = create_demo_docs.main(["--base-url", "http://x", str(payload_path)])
    assert rc == 0
    assert _header(captured_requests[0], create_demo_docs.GOLDEN_TOKEN_HEADER) is None


# ─────────────────── session-cookie fallback (no golden token at all) ───────────────────

def test_session_cookie_is_captured_and_resent_on_the_next_request(monkeypatch):
    """Without a golden token, this process's OWN first-received session
    cookie is echoed back on every later request -- otherwise, since plain
    urllib has no cookie jar, create+poll would each land in a DIFFERENT
    fresh session clone and the script could never see its own document."""
    captured = []
    responses = [
        _FakeResponse({"id": 42}, set_cookie="glossa_sid=abc-123; HttpOnly; Path=/; "
                                              "SameSite=lax; Secure; Max-Age=14400"),
        _FakeResponse({"termsStatus": "done", "translation": None, "precompute": None}),
    ]

    def fake_urlopen(req, *a, **kw):
        captured.append(req)
        return responses.pop(0)

    monkeypatch.setattr(create_demo_docs.urllib.request, "urlopen", fake_urlopen)

    create_demo_docs._post_json("http://x/api/documents", {"a": 1})
    assert _header(captured[0], "Cookie") is None       # nothing to send yet on the FIRST call

    create_demo_docs._get_json("http://x/api/documents/42")
    assert _header(captured[1], "Cookie") == "glossa_sid=abc-123"  # echoed on the SECOND call


def test_golden_token_takes_priority_over_a_tracked_cookie(monkeypatch):
    monkeypatch.setattr(create_demo_docs, "_session_cookie", "glossa_sid=leftover-from-earlier")
    captured = []

    def fake_urlopen(req, *a, **kw):
        captured.append(req)
        return _FakeResponse({"id": 1})

    monkeypatch.setattr(create_demo_docs.urllib.request, "urlopen", fake_urlopen)
    create_demo_docs._post_json("http://x/api/documents", {"a": 1}, golden_token="s3cr3t")
    assert _header(captured[0], create_demo_docs.GOLDEN_TOKEN_HEADER) == "s3cr3t"
    assert _header(captured[0], "Cookie") is None
