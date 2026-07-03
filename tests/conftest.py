"""Shared fixtures for webapp API tests."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from palimpsest.webapp import db
from palimpsest.webapp.app import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "demo.db")
    monkeypatch.setattr(db, "_conn", None)
    db.init_db(reset=True)
    return TestClient(app)


def _body(**over):
    base = {"title": "Test pair", "sourceLang": "de", "targetLang": "fr", "precompute": False,
            "paragraphs": [{"source": "Ein Absatz.", "target": "Un paragraphe."}]}
    base.update(over)
    return base
