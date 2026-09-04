"""Shared fixtures for webapp API tests."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from palimpsest.webapp import budget, db, translate
from palimpsest.webapp.app import app


@pytest.fixture(autouse=True)
def _budget_log_tmp(tmp_path, monkeypatch):
    # budget._LOG_PATH defaults to "budget_calls.jsonl" relative to the CWD;
    # without this, every pytest run drops a fake-model spend log into the
    # repo root (which once leaked into the prod image via rsync+docker build).
    monkeypatch.setattr(budget, "_LOG_PATH", str(tmp_path / "budget_calls.jsonl"))


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "demo.db")
    monkeypatch.setattr(db, "_conn", None)
    db.init_db(reset=True)
    # `translate._translating`/`_status` are module-global dicts/sets keyed by
    # doc_id, and every test's DB restarts autoincrement at 1 — without this,
    # a test that creates a translate:true document and leaves it "in
    # progress" (e.g. by stubbing translate.launch to a no-op) can silently
    # gate an unrelated later test's /evaluate or /reset call via the exact
    # same doc_id in a different DB.
    translate._translating.clear()
    translate._status.clear()
    return TestClient(app)


def _body(**over):
    base = {"title": "Test pair", "sourceLang": "de", "targetLang": "fr", "precompute": False,
            "paragraphs": [{"source": "Ein Absatz.", "target": "Un paragraphe."}]}
    base.update(over)
    return base
