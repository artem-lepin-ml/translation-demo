"""Small-polish fixes bundled with the EMNLP demo sprint bugfix wave
(2026-07-17): a human 409 message for a duplicate model name, redaction of a
provider-internal user_id leaking into the model Test error message,
case-insensitive export ?format=, and an explicit lock on the CJK-title
export filename (slug falls back to 'document', but the doc id still makes
the filename unique).
"""
from __future__ import annotations

import openai
import httpx
import pytest

from palimpsest.webapp import app as app_mod
from palimpsest.webapp import budget, db
from palimpsest.webapp.secrets_guard import redact_error
from tests.conftest import _body


# ── (a) human 409 message for a duplicate model name ────────────────────────

def test_duplicate_model_name_returns_human_409_message(client):
    payload = {"baseUrl": "https://openrouter.ai/api/v1", "apiKey": "", "params": {}}
    r1 = client.post("/api/models", json={"name": "dup/model", **payload})
    assert r1.status_code == 200, r1.text
    r2 = client.post("/api/models", json={"name": "dup/model", **payload})
    assert r2.status_code == 409
    assert r2.json()["error"] == "A model with this name already exists"
    assert "UNIQUE constraint" not in r2.json()["error"]


def test_other_integrity_errors_keep_raw_text_fallback():
    """The human-message translation is scoped to the specific duplicate-
    model-name shape; any other constraint violation still surfaces the raw
    SQLite text (no regression on the general 409 safety net)."""
    from fastapi.responses import JSONResponse

    class _FakeIntegrityError(Exception):
        def __str__(self):
            return "FOREIGN KEY constraint failed"

    resp = app_mod._integrity_error(None, _FakeIntegrityError())
    assert isinstance(resp, JSONResponse)
    assert resp.status_code == 409
    import json
    assert json.loads(resp.body)["error"] == "FOREIGN KEY constraint failed"


# ── (b) provider user_id redaction in the model Test error message ─────────
#
# The user_id scrub is local to app.py's test-endpoint (app_mod._USER_ID_RE),
# not secrets_guard.redact_error — that module is outside this task's edit
# lane, and the regex needs to work regardless of the id's length (unlike
# redact_error's own generic 24+-char catch-all, which only coincidentally
# happens to cover the specific real-world example seen in prod).

def test_user_id_regex_masks_real_world_example():
    text = app_mod._USER_ID_RE.sub("[REDACTED]", redact_error(
        "BadRequestError: Error code: 400 - {'error': {'message': 'not a valid model ID', "
        "'code': 400}, 'user_id': 'user_3DSjOtCFgWsPlqyYKDeAIpsKkPf'}"))
    assert "user_3DSjOtCFgWsPlqyYKDeAIpsKkPf" not in text
    assert "[REDACTED]" in text


def test_user_id_regex_masks_a_short_id_too():
    """Unlike redact_error's own 24+-char generic token catch-all, the
    user_id-specific regex fires regardless of length."""
    text = app_mod._USER_ID_RE.sub("[REDACTED]", "provider said: user_ab12")
    assert text == "provider said: [REDACTED]"


def test_model_test_endpoint_sanitizes_user_id_in_message(client, monkeypatch):
    budget.reset()
    budget._CAP_USD = 2.0
    budget._CALL_CAP = 200
    monkeypatch.setattr(budget, "_PRICES", {"m": (1e-6, 1e-6)})
    conn = db.connect()
    conn.execute("INSERT INTO model(name,base_url,api_key,params_json) "
                 "VALUES('m','https://openrouter.ai/api/v1','k','{}')")
    conn.commit()

    def bad_request(*a, **kw):
        resp = httpx.Response(400, request=httpx.Request("POST", "http://or"))
        raise openai.BadRequestError(
            "Error code: 400 - {'error': {'message': 'bad model', 'code': 400}, "
            "'user_id': 'user_3DSjOtCFgWsPlqyYKDeAIpsKkPf'}", response=resp, body=None)

    class _DummyClient:
        class config:
            max_tokens = 512
            extra_body = None

        complete = staticmethod(bad_request)

    monkeypatch.setattr(app_mod, "_client_for", lambda conn, name: _DummyClient())
    r = client.post("/api/models/m/test")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert "user_3DSjOtCFgWsPlqyYKDeAIpsKkPf" not in body["message"]


# ── (c) export ?format= is case-insensitive ─────────────────────────────────

def test_export_format_case_insensitive(client):
    doc = client.post("/api/documents", json=_body(paragraphs=[
        {"source": "s", "target": "t"}])).json()
    r = client.get(f"/api/documents/{doc['id']}/export?format=MD")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/markdown")

    r2 = client.get(f"/api/documents/{doc['id']}/export?format=Xlsx")
    assert r2.status_code == 200
    assert r2.headers["content-type"] == (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# ── (d) CJK title still slugs to 'document', filename still keyed by doc id ─

def test_export_cjk_title_slug_falls_back_but_filename_keeps_doc_id(client):
    doc = client.post("/api/documents", json=_body(title="测试文档")).json()
    r = client.get(f"/api/documents/{doc['id']}/export?format=md")
    assert r.status_code == 200
    disp = r.headers["content-disposition"]
    assert f"document-{doc['id']}.md" in disp
