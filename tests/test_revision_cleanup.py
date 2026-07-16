"""Stale revision-history cleanup (2026-07-16, owner UI review #7): prune
orphan "not scored" `target_revision` rows for the ONE curated demo
document's paragraphs only, never touching a revision any `score` row
references. See docs/superpowers/specs/2026-06-30-demo-contracts.md
"Revision-history cleanup delta" and migrate.py's _prune_orphan_revisions.
"""
from __future__ import annotations

import logging
import sqlite3

import pytest

from palimpsest.webapp import db, migrate

_CURATED_TITLE = migrate._REVISION_CLEANUP_DOC_TITLE


def _fresh_conn(tmp_path, name="revisions.db"):
    path = tmp_path / name
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(db.SCHEMA)
    conn.commit()
    return conn


def _seed_minimal_model_and_criterion(conn):
    conn.execute("INSERT INTO model(name,base_url,api_key,params_json) VALUES('m','u','k','{}')")
    conn.execute(
        "INSERT INTO criterion(id,name,model_name,prompt,scale_min,scale_max,weight,color,enabled) "
        "VALUES('accuracy','Accuracy','m','p',1.0,10.0,0.4,'#4d8dff',1)")


def _insert_doc(conn, title, origin="upload"):
    return conn.execute(
        "INSERT INTO document(title,source_lang,target_lang,version,origin,created_at) "
        "VALUES(?,?,?,0,?,?)", (title, "ru", "en", origin, "2026-01-01T00:00:00Z")).lastrowid


def _insert_paragraph(conn, doc_id, idx=0):
    return conn.execute(
        "INSERT INTO paragraph(document_id,idx,source,target,seed_target) VALUES(?,?,?,?,?)",
        (doc_id, idx, "s", "t", "t")).lastrowid


def _insert_score(conn, pid, revision_id, kind="live"):
    conn.execute(
        "INSERT INTO score(paragraph_id,criterion_id,value,summary,aggregate,criteria_key,kind,"
        "created_at,revision_id) VALUES(?,'accuracy',8.0,'ok',8.0,'accuracy',?,?,?)",
        (pid, kind, "2026-01-01T02:05:00Z", revision_id))


# ── the exact required scenario: [seed, orphan-edit, scored-edit] -> [seed, scored-edit] ──

def test_prune_orphan_revisions_keeps_seed_and_scored_only(tmp_path):
    conn = _fresh_conn(tmp_path)
    _seed_minimal_model_and_criterion(conn)
    doc_id = _insert_doc(conn, _CURATED_TITLE)
    pid = _insert_paragraph(conn, doc_id)

    seed_rev = db.write_revision(conn, pid, "seed text", "seed", "2026-01-01T00:00:00Z")
    orphan_rev = db.write_revision(conn, pid, "orphan edit text", "edit", "2026-01-01T01:00:00Z")
    scored_rev = db.write_revision(conn, pid, "scored edit text", "edit", "2026-01-01T02:00:00Z")
    _insert_score(conn, pid, scored_rev)
    conn.commit()

    before_score = dict(conn.execute("SELECT * FROM score").fetchone())

    migrate._prune_orphan_revisions(conn)
    conn.commit()

    remaining = {r["id"] for r in conn.execute(
        "SELECT id FROM target_revision WHERE paragraph_id=?", (pid,))}
    assert remaining == {seed_rev, scored_rev}
    assert orphan_rev not in remaining

    after_score = dict(conn.execute("SELECT * FROM score").fetchone())
    assert before_score == after_score      # score row byte-for-byte untouched
    assert conn.execute("SELECT COUNT(*) c FROM score").fetchone()["c"] == 1  # never deleted


def test_prune_orphan_revisions_idempotent_double_run(tmp_path):
    conn = _fresh_conn(tmp_path)
    _seed_minimal_model_and_criterion(conn)
    doc_id = _insert_doc(conn, _CURATED_TITLE)
    pid = _insert_paragraph(conn, doc_id)
    db.write_revision(conn, pid, "seed text", "seed", "2026-01-01T00:00:00Z")
    db.write_revision(conn, pid, "orphan edit text", "edit", "2026-01-01T01:00:00Z")
    scored_rev = db.write_revision(conn, pid, "scored edit text", "edit", "2026-01-01T02:00:00Z")
    _insert_score(conn, pid, scored_rev)
    conn.commit()

    migrate._prune_orphan_revisions(conn)
    conn.commit()
    state_1 = {r["id"] for r in conn.execute(
        "SELECT id FROM target_revision WHERE paragraph_id=?", (pid,))}

    migrate._prune_orphan_revisions(conn)   # second run must be a no-op
    conn.commit()
    state_2 = {r["id"] for r in conn.execute(
        "SELECT id FROM target_revision WHERE paragraph_id=?", (pid,))}

    assert state_1 == state_2


def test_prune_orphan_revisions_gated_to_curated_doc_title_only(tmp_path):
    conn = _fresh_conn(tmp_path)
    doc_id = _insert_doc(conn, "Some other document, not the curated one")
    pid = _insert_paragraph(conn, doc_id)
    seed_rev = db.write_revision(conn, pid, "t", "seed", "2026-01-01T00:00:00Z")
    orphan_rev = db.write_revision(conn, pid, "orphan", "edit", "2026-01-01T01:00:00Z")
    conn.commit()

    migrate._prune_orphan_revisions(conn)
    conn.commit()

    remaining = {r["id"] for r in conn.execute(
        "SELECT id FROM target_revision WHERE paragraph_id=?", (pid,))}
    assert remaining == {seed_rev, orphan_rev}   # untouched -- not the gated document


def test_prune_orphan_revisions_no_curated_doc_present_is_a_noop(tmp_path):
    conn = _fresh_conn(tmp_path)
    # no document at all -- must not raise
    migrate._prune_orphan_revisions(conn)


def test_prune_orphan_revisions_logs_pruned_count(tmp_path, caplog):
    conn = _fresh_conn(tmp_path)
    doc_id = _insert_doc(conn, _CURATED_TITLE)
    pid = _insert_paragraph(conn, doc_id)
    db.write_revision(conn, pid, "seed", "seed", "2026-01-01T00:00:00Z")
    db.write_revision(conn, pid, "orphan", "edit", "2026-01-01T01:00:00Z")
    # a later revision so the orphan sits in the MIDDLE of history — the
    # latest revision itself is never pruned (it is the CURRENT pointer)
    db.write_revision(conn, pid, "current", "edit", "2026-01-01T02:00:00Z")
    conn.commit()

    with caplog.at_level(logging.INFO, logger="palimpsest.webapp.migrate"):
        migrate._prune_orphan_revisions(conn)
    assert "pruned 1" in caplog.text


def test_prune_orphan_revisions_never_prunes_latest_unscored(tmp_path):
    """The LATEST revision is the API's CURRENT pointer (db.latest_revision_id
    = MAX(id)) and paragraph.target carries its text — pruning it would leave
    the CURRENT badge on an older row whose text no longer matches the live
    paragraph. Exactly prod's state right after a Document Reset (the reset
    revision is unscored)."""
    conn = _fresh_conn(tmp_path)
    _seed_minimal_model_and_criterion(conn)
    doc_id = _insert_doc(conn, _CURATED_TITLE)
    pid = _insert_paragraph(conn, doc_id)

    seed_rev = db.write_revision(conn, pid, "seed text", "seed", "2026-01-01T00:00:00Z")
    orphan_mid = db.write_revision(conn, pid, "middle orphan", "edit", "2026-01-01T01:00:00Z")
    scored_rev = db.write_revision(conn, pid, "scored edit", "edit", "2026-01-01T02:00:00Z")
    _insert_score(conn, pid, scored_rev)
    latest_unscored = db.write_revision(conn, pid, "reset text", "reset", "2026-01-01T03:00:00Z")
    conn.commit()

    migrate._prune_orphan_revisions(conn)
    conn.commit()

    remaining = {r["id"] for r in conn.execute(
        "SELECT id FROM target_revision WHERE paragraph_id=?", (pid,))}
    assert remaining == {seed_rev, scored_rev, latest_unscored}
    assert orphan_mid not in remaining


# ── FK safety net: a scored revision can never be deleted while foreign_keys=ON ──

def test_target_revision_fk_enforced_deleting_a_scored_revision_directly_raises(tmp_path):
    """Direct proof the schema really protects a scored revision: deleting a
    target_revision row a score.revision_id points at raises IntegrityError
    when foreign_keys=ON -- the safety net _prune_orphan_revisions relies on
    (it never attempts such a delete by construction; if it ever did, the DB
    itself refuses)."""
    conn = _fresh_conn(tmp_path)
    _seed_minimal_model_and_criterion(conn)
    doc_id = _insert_doc(conn, _CURATED_TITLE)
    pid = _insert_paragraph(conn, doc_id)
    rev = db.write_revision(conn, pid, "t", "seed", "2026-01-01T00:00:00Z")
    _insert_score(conn, pid, rev, kind="seed")
    conn.commit()

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM target_revision WHERE id=?", (rev,))


# ── full pipeline: rename (task #1) must run before prune (task #7) ────────

def test_full_migrate_pipeline_prunes_after_curation_rename(tmp_path, monkeypatch):
    """The full migrate() pipeline renames the pre-fix "... (Draft
    Translation)" title to the canonical one BEFORE pruning runs, so a
    document still carrying the old title is nonetheless correctly gated."""
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "boot.db")
    monkeypatch.setattr(db, "_conn", None)
    conn = db.init_db(reset=True)
    doc_id = _insert_doc(conn, f"{_CURATED_TITLE} (Draft Translation)")
    pid = _insert_paragraph(conn, doc_id)
    seed_rev = db.write_revision(conn, pid, "seed", "seed", "2026-01-01T00:00:00Z")
    orphan_rev = db.write_revision(conn, pid, "orphan", "edit", "2026-01-01T01:00:00Z")
    # latest revision is always kept (CURRENT pointer) — the orphan must sit
    # mid-history to be prunable
    current_rev = db.write_revision(conn, pid, "current", "edit", "2026-01-01T02:00:00Z")
    conn.commit()

    migrate.migrate(conn)

    remaining = {r["id"] for r in conn.execute(
        "SELECT id FROM target_revision WHERE paragraph_id=?", (pid,))}
    assert remaining == {seed_rev, current_rev}
    assert orphan_rev not in remaining
    title = conn.execute("SELECT title FROM document WHERE id=?", (doc_id,)).fetchone()["title"]
    assert title == _CURATED_TITLE
