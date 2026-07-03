"""Dismiss persistence: PATCH /api/issues/{iid} must survive a document reload."""
from __future__ import annotations

import pytest
from fastapi import HTTPException


@pytest.fixture
def seeded(tmp_path, monkeypatch):
    from palimpsest.webapp import db
    from palimpsest.webapp import seed as seedmod
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(db, "_conn", None)
    seedmod.seed()
    yield db
    if db._conn is not None:
        db._conn.close()
        db._conn = None


def test_dismiss_persists_in_document(seeded):
    from palimpsest.webapp.app import IssueStatusBody, get_document, patch_issue_status

    conn = seeded.connect()
    r = conn.execute("SELECT id, paragraph_id FROM issue WHERE status='open' LIMIT 1").fetchone()
    out = patch_issue_status(r["id"], IssueStatusBody(status="dismissed"))
    assert out["status"] == "dismissed"

    doc_id = conn.execute("SELECT document_id FROM paragraph WHERE id=?",
                          (r["paragraph_id"],)).fetchone()["document_id"]
    doc = get_document(doc_id)
    statuses = {i["id"]: i["status"] for p in doc["paragraphs"] for i in p["issues"]}
    assert statuses[str(r["id"])] == "dismissed"


def test_dismiss_can_be_reopened(seeded):
    from palimpsest.webapp.app import IssueStatusBody, patch_issue_status

    conn = seeded.connect()
    iid = conn.execute("SELECT id FROM issue WHERE status='open' LIMIT 1").fetchone()["id"]
    patch_issue_status(iid, IssueStatusBody(status="dismissed"))
    out = patch_issue_status(iid, IssueStatusBody(status="open"))
    assert out["status"] == "open"


def test_accepted_issue_is_409(seeded):
    from palimpsest.webapp.app import IssueStatusBody, patch_issue_status

    conn = seeded.connect()
    iid = conn.execute("SELECT id FROM issue LIMIT 1").fetchone()["id"]
    conn.execute("UPDATE issue SET status='accepted' WHERE id=?", (iid,))
    conn.commit()
    with pytest.raises(HTTPException) as e:
        patch_issue_status(iid, IssueStatusBody(status="dismissed"))
    assert e.value.status_code == 409


def test_invalid_status_is_422(seeded):
    from palimpsest.webapp.app import IssueStatusBody, patch_issue_status

    with pytest.raises(HTTPException) as e:
        patch_issue_status(1, IssueStatusBody(status="accepted"))
    assert e.value.status_code == 422


def test_outdated_status_is_accepted(seeded):
    """'outdated' marks an issue whose fragment was overlapped by an earlier edit."""
    from palimpsest.webapp.app import IssueStatusBody, patch_issue_status

    conn = seeded.connect()
    iid = conn.execute("SELECT id FROM issue WHERE status='open' LIMIT 1").fetchone()["id"]
    out = patch_issue_status(iid, IssueStatusBody(status="outdated"))
    assert out["status"] == "outdated"


def test_unknown_issue_is_404(seeded):
    from palimpsest.webapp.app import IssueStatusBody, patch_issue_status

    with pytest.raises(HTTPException) as e:
        patch_issue_status(999999, IssueStatusBody(status="dismissed"))
    assert e.value.status_code == 404
