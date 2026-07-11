"""Additive, idempotent schema migration for a live prod DB (spec S5 §2.4).

There is no migration framework in this project — ``db.py::SCHEMA`` is the
source of truth for FRESH databases (``init_db(reset=True)``), and this module
is the source of truth for bringing an EXISTING (already-populated) database
up to the same shape without a reseed. Every step here is safe to run twice:
``CREATE TABLE IF NOT EXISTS``, a ``PRAGMA table_info`` guard before
``ALTER TABLE ... ADD COLUMN``, and an existence check before any INSERT.

Called from two places: ``app.py`` at startup (before serving requests) and
the ``python -m palimpsest.webapp.migrate`` CLI (manual prod run).
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone

from .. import paths
from ..terminology.grounding.label_first import DEFAULT_GROUNDING_JUDGE_PROMPT
from . import db
from .model_matrix import DEFAULT_CRITERION_MODEL

TRANSLATOR_PROMPT_FILE = paths.PROMPTS / "translator" / "default.md"
TRANSLATOR_DEFAULT_PARAMS = {"max_tokens": 2048, "temperature": 0.3}
GROUNDING_DEFAULT_PARAMS = {"max_tokens": 512, "temperature": 0}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    return any(r["name"] == column for r in conn.execute(f"PRAGMA table_info({table})"))


def _create_target_revision(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS target_revision ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "paragraph_id INTEGER REFERENCES paragraph(id) ON DELETE CASCADE,"
        "text TEXT NOT NULL,"
        "origin TEXT NOT NULL,"
        "created_at TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_target_revision_para ON target_revision(paragraph_id, id)"
    )


def _create_translator_config(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS translator_config ("
        "id INTEGER PRIMARY KEY CHECK (id = 1),"
        "model_name TEXT REFERENCES model(name),"
        "prompt TEXT,"
        "params_json TEXT)"
    )
    row = conn.execute("SELECT 1 FROM translator_config WHERE id=1").fetchone()
    if row is not None:
        return
    # Only seed the default row if its target model already exists — model_name
    # is FK-constrained, and a bare fresh/test DB may not have any model rows
    # yet (e.g. a schema-only fixture). GET /api/translator-config already
    # handles an absent row (mirrors grounding_config's None-row path).
    model_exists = conn.execute(
        "SELECT 1 FROM model WHERE name=?", (DEFAULT_CRITERION_MODEL,)).fetchone()
    if not model_exists:
        return
    if not TRANSLATOR_PROMPT_FILE.exists():
        return
    prompt = TRANSLATOR_PROMPT_FILE.read_text(encoding="utf-8")
    conn.execute(
        "INSERT INTO translator_config(id,model_name,prompt,params_json) VALUES(1,?,?,?)",
        (DEFAULT_CRITERION_MODEL, prompt, json.dumps(TRANSLATOR_DEFAULT_PARAMS)))


def _create_grounding_config(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS grounding_config ("
        "id INTEGER PRIMARY KEY CHECK (id = 1),"
        "model_name TEXT REFERENCES model(name),"
        "prompt TEXT,"
        "params_json TEXT)"
    )
    row = conn.execute("SELECT 1 FROM grounding_config WHERE id=1").fetchone()
    if row is not None:
        return
    # Same FK-safety guard as _create_translator_config: model_name is
    # FK-constrained, so only seed the default row when its target model
    # already exists. GET /api/grounding-config already tolerates an absent
    # row (returns a null/default config, never 500).
    model_exists = conn.execute(
        "SELECT 1 FROM model WHERE name=?", (DEFAULT_CRITERION_MODEL,)).fetchone()
    if not model_exists:
        return
    conn.execute(
        "INSERT INTO grounding_config(id,model_name,prompt,params_json) VALUES(1,?,?,?)",
        (DEFAULT_CRITERION_MODEL, DEFAULT_GROUNDING_JUDGE_PROMPT, json.dumps(GROUNDING_DEFAULT_PARAMS)))


def _create_glossary(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS glossary ("
        "id INTEGER PRIMARY KEY,"
        "term TEXT, context TEXT, target_equivalent TEXT,"
        "wikidata_url TEXT NOT NULL, wikidata_id TEXT,"
        "UNIQUE (term, context))"
    )


def _add_term_trace_json_column(conn: sqlite3.Connection) -> None:
    if not _has_column(conn, "term", "trace_json"):
        # NOT NULL DEFAULT '{}' matches db.py SCHEMA and backfills every
        # existing row with '{}' in the same ALTER TABLE (SQLite fills a
        # constant default into pre-existing rows) — no separate backfill step.
        conn.execute("ALTER TABLE term ADD COLUMN trace_json TEXT NOT NULL DEFAULT '{}'")


def _add_score_revision_column(conn: sqlite3.Connection) -> None:
    if not _has_column(conn, "score", "revision_id"):
        conn.execute(
            "ALTER TABLE score ADD COLUMN revision_id INTEGER REFERENCES target_revision(id)")


def _add_document_terms_status_column(conn: sqlite3.Connection) -> None:
    """2026-07-11 EMNLP sprint (live terminology pipeline): 'none'|'running'|
    'done'|'failed', see terminology_live.py. NOT NULL DEFAULT 'none' matches
    db.py SCHEMA and backfills every existing row via the ALTER's DEFAULT —
    same pattern as _add_term_trace_json_column."""
    if not _has_column(conn, "document", "terms_status"):
        conn.execute("ALTER TABLE document ADD COLUMN terms_status TEXT NOT NULL DEFAULT 'none'")


def _backfill_seed_document_terms_status(conn: sqlite3.Connection) -> None:
    """The seeded demo document already has precomputed terms (loaded by
    scripts/load_terms.py, not by the live pipeline) — mark it 'done' so the
    frontend never shows it as pending. Idempotent (a 'done' row is simply
    left unchanged); runs unconditionally, unlike the FK-guarded config
    seeds above, since 'origin=seed' rows are safe to touch regardless of
    whether any model row exists yet."""
    conn.execute("UPDATE document SET terms_status='done' WHERE origin='seed' AND terms_status!='done'")


def _backfill_paragraph_revisions(conn: sqlite3.Connection) -> None:
    """Every paragraph without a single ``target_revision`` row gets one,
    seeded from its current ``target`` text — so a migrated prod DB and a
    freshly-seeded dev/test DB have the same *shape* of history (spec S5
    §2.1 point 7 mirrors this for seed.py)."""
    ts = _now()
    missing = conn.execute(
        "SELECT p.id, p.target FROM paragraph p "
        "LEFT JOIN target_revision r ON r.paragraph_id = p.id "
        "WHERE r.id IS NULL"
    ).fetchall()
    for p in missing:
        conn.execute(
            "INSERT INTO target_revision(paragraph_id,text,origin,created_at) VALUES(?,?,?,?)",
            (p["id"], p["target"], "seed", ts))


def migrate(conn: sqlite3.Connection) -> None:
    """Run every additive step, in order, and commit once at the end."""
    _create_target_revision(conn)
    _create_translator_config(conn)
    _create_grounding_config(conn)
    _create_glossary(conn)
    _add_term_trace_json_column(conn)
    _add_score_revision_column(conn)
    _backfill_paragraph_revisions(conn)
    _add_document_terms_status_column(conn)
    _backfill_seed_document_terms_status(conn)
    conn.commit()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Additively migrate the Palimpsest demo SQLite DB in place "
                    "(idempotent — safe to run repeatedly against a live prod DB).")
    parser.parse_args()
    conn = db.connect()
    migrate(conn)
    print(f"migrated {db.DB_PATH}")


if __name__ == "__main__":
    main()
