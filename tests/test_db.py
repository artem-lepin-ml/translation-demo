"""DB invariants: FK restrict, latest-excludes-cache, reset restores seed."""
from __future__ import annotations

import sqlite3

import pytest

from palimpsest.webapp import db


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


def test_seed_populated(seeded):
    conn = seeded.connect()
    assert conn.execute("SELECT COUNT(*) c FROM paragraph").fetchone()["c"] == 15
    assert conn.execute("SELECT COUNT(*) c FROM criterion").fetchone()["c"] == 4


def test_fk_restrict_blocks_criterion_delete(seeded):
    conn = seeded.connect()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM criterion WHERE id='accuracy'")


def test_latest_excludes_cache(seeded):
    conn = seeded.connect()
    kinds = {r["kind"] for r in conn.execute(
        "SELECT kind FROM score WHERE paragraph_id=1 AND criterion_id='accuracy'")}
    assert {"seed", "cache"} <= kinds
    latest = conn.execute(
        "SELECT value FROM score WHERE paragraph_id=1 AND criterion_id='accuracy' "
        "AND kind IN ('seed','live') ORDER BY created_at DESC, id DESC LIMIT 1").fetchone()["value"]
    cache = conn.execute(
        "SELECT value FROM score WHERE paragraph_id=1 AND criterion_id='accuracy' AND kind='cache'"
    ).fetchone()["value"]
    assert cache > latest        # cache is the uplifted "expected post-fix" value


def test_reset_restores_seed_target(seeded):
    from palimpsest.webapp import app as appmod
    conn = seeded.connect()
    conn.execute("UPDATE paragraph SET target='EDITED' WHERE id=1")
    conn.commit()
    doc = appmod.reset_document(1)
    assert doc["paragraphs"][0]["target"] != "EDITED"
    assert doc["paragraphs"][0]["target"] == conn.execute(
        "SELECT seed_target FROM paragraph WHERE id=1").fetchone()["seed_target"]


def test_reset_preserves_cache(seeded):
    """Reset clears live results but must keep cache scores (the canned uplift)."""
    from palimpsest.webapp import app as appmod
    conn = seeded.connect()
    before = conn.execute("SELECT COUNT(*) c FROM score WHERE kind='cache'").fetchone()["c"]
    assert before > 0
    appmod.reset_document(1)
    after = conn.execute("SELECT COUNT(*) c FROM score WHERE kind='cache'").fetchone()["c"]
    assert after == before, "reset must not delete cache (uplift) scores"


def test_document_origin_default_and_cascade(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(db, "_conn", None)
    conn = db.init_db(reset=True)
    conn.execute("INSERT INTO criterion(id,name) VALUES('accuracy','Accuracy')")
    doc = conn.execute(
        "INSERT INTO document(title,source_lang,target_lang,version,created_at) "
        "VALUES('t','ru','en',0,'now')").lastrowid
    assert conn.execute("SELECT origin FROM document WHERE id=?", (doc,)).fetchone()["origin"] == "seed"
    pid = conn.execute(
        "INSERT INTO paragraph(document_id,idx,source,target,seed_target) VALUES(?,0,'s','t','t')",
        (doc,)).lastrowid
    conn.execute(
        "INSERT INTO score(paragraph_id,criterion_id,value,kind,created_at) VALUES(?,'accuracy',5,'seed','now')",
        (pid,))
    conn.execute(
        "INSERT INTO issue(paragraph_id,criterion_id,explanation,status,kind,created_at) "
        "VALUES(?,'accuracy','e','open','seed','now')", (pid,))
    conn.execute(
        "INSERT INTO term(paragraph_id,source_surface,char_start,char_end) VALUES(?,'x',0,1)", (pid,))
    conn.execute("DELETE FROM document WHERE id=?", (doc,))
    conn.commit()
    for table in ("paragraph", "score", "issue", "term"):
        assert conn.execute(f"SELECT COUNT(*) c FROM {table}").fetchone()["c"] == 0
