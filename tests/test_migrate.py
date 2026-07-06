"""Additive prod-DB migration (spec 2026-07-05-score-history-best §2.4 /
2026-07-05-translator §2.1): idempotent, and a migrated old-shape DB ends up
schema-equivalent to a freshly-seeded one."""
from __future__ import annotations

import json
import sqlite3

import pytest

from palimpsest.webapp import db, migrate
from palimpsest.webapp.model_matrix import DEFAULT_CRITERION_MODEL

# The schema as it existed BEFORE this PR (no target_revision, no
# translator_config, no score.revision_id) — used to build a DB that looks
# like an un-migrated prod database.
OLD_SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE document (
  id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, source_lang TEXT, target_lang TEXT,
  source_model TEXT, seed_model TEXT, seed_prompt_variant TEXT,
  version INTEGER DEFAULT 0, origin TEXT DEFAULT 'seed', created_at TEXT
);
CREATE TABLE paragraph (
  id INTEGER PRIMARY KEY AUTOINCREMENT, document_id INTEGER REFERENCES document(id) ON DELETE CASCADE,
  idx INTEGER, source TEXT, target TEXT, seed_target TEXT
);
CREATE TABLE criterion (
  id TEXT PRIMARY KEY, name TEXT, model_name TEXT REFERENCES model(name),
  prompt TEXT, scale_min REAL, scale_max REAL, weight REAL, color TEXT, enabled INTEGER DEFAULT 1
);
CREATE TABLE model (
  name TEXT PRIMARY KEY, base_url TEXT, api_key TEXT, params_json TEXT
);
CREATE TABLE score (
  id INTEGER PRIMARY KEY, paragraph_id INTEGER REFERENCES paragraph(id) ON DELETE CASCADE,
  criterion_id TEXT REFERENCES criterion(id), value REAL, summary TEXT,
  aggregate REAL, criteria_key TEXT, kind TEXT DEFAULT 'live', created_at TEXT
);
CREATE TABLE issue (
  id INTEGER PRIMARY KEY, paragraph_id INTEGER REFERENCES paragraph(id) ON DELETE CASCADE,
  criterion_id TEXT REFERENCES criterion(id), target_fragment TEXT, source_fragment TEXT,
  explanation TEXT, suggestion TEXT, severity TEXT, mqm_category TEXT,
  status TEXT DEFAULT 'open', kind TEXT DEFAULT 'live', created_at TEXT
);
CREATE TABLE term (
  id INTEGER PRIMARY KEY, paragraph_id INTEGER REFERENCES paragraph(id) ON DELETE CASCADE,
  source_surface TEXT, source_lemma TEXT, context TEXT, char_start INTEGER, char_end INTEGER,
  difficulty TEXT, grounded_json TEXT, candidates_json TEXT,
  target_surface TEXT, pair_accuracy TEXT, recommended TEXT, note TEXT,
  trace_json TEXT NOT NULL DEFAULT '{}',
  UNIQUE (paragraph_id, char_start, char_end)
);
CREATE TABLE glossary (
  id INTEGER PRIMARY KEY, term TEXT, context TEXT, target_equivalent TEXT,
  wikidata_url TEXT NOT NULL, wikidata_id TEXT,
  UNIQUE (term, context)
);
CREATE TABLE grounding_config (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  model_name TEXT REFERENCES model(name),
  prompt TEXT,
  params_json TEXT
);
"""


@pytest.fixture()
def old_conn(tmp_path):
    path = tmp_path / "old.db"
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(OLD_SCHEMA)
    conn.execute("INSERT INTO model(name,base_url,api_key,params_json) VALUES(?,?,?,?)",
                 (DEFAULT_CRITERION_MODEL, "https://openrouter.ai/api/v1", "k", "{}"))
    conn.execute("INSERT INTO criterion(id,name,model_name,prompt,scale_min,scale_max,weight,color,enabled) "
                 "VALUES('accuracy','Accuracy',?,'p',1.0,10.0,0.3,'#4d8dff',1)",
                 (DEFAULT_CRITERION_MODEL,))
    doc_id = conn.execute(
        "INSERT INTO document(title,source_lang,target_lang,source_model,version,origin,created_at) "
        "VALUES('T','ru','en','user',0,'upload','2026-01-01T00:00:00Z')").lastrowid
    pid = conn.execute(
        "INSERT INTO paragraph(document_id,idx,source,target,seed_target) VALUES(?,?,?,?,?)",
        (doc_id, 0, "s", "t", "t")).lastrowid
    conn.execute(
        "INSERT INTO score(paragraph_id,criterion_id,value,summary,aggregate,criteria_key,kind,created_at) "
        "VALUES(?,'accuracy',8.0,'ok',8.0,'accuracy','live','2026-01-01T00:00:00Z')", (pid,))
    conn.commit()
    return conn


def _tables(conn) -> dict[str, set[str]]:
    names = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    return {t: {r["name"] for r in conn.execute(f"PRAGMA table_info({t})")} for t in names}


def test_migrate_adds_new_tables_and_column(old_conn):
    migrate.migrate(old_conn)
    tables = _tables(old_conn)
    assert "target_revision" in tables
    assert "translator_config" in tables
    assert "revision_id" in tables["score"]


def test_migrate_seeds_translator_config_when_model_exists(old_conn):
    migrate.migrate(old_conn)
    row = old_conn.execute("SELECT * FROM translator_config WHERE id=1").fetchone()
    assert row is not None
    assert row["model_name"] == DEFAULT_CRITERION_MODEL
    assert json.loads(row["params_json"]) == {"max_tokens": 2048, "temperature": 0.3}


def test_migrate_skips_translator_config_seed_when_model_absent(tmp_path):
    path = tmp_path / "old2.db"
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(OLD_SCHEMA)
    conn.commit()
    migrate.migrate(conn)
    row = conn.execute("SELECT * FROM translator_config WHERE id=1").fetchone()
    assert row is None                          # no FK target → left unseeded, honestly


def test_migrate_backfills_paragraph_revision(old_conn):
    migrate.migrate(old_conn)
    pid = old_conn.execute("SELECT id FROM paragraph LIMIT 1").fetchone()["id"]
    revs = old_conn.execute("SELECT * FROM target_revision WHERE paragraph_id=?", (pid,)).fetchall()
    assert len(revs) == 1
    assert revs[0]["origin"] == "seed"
    assert revs[0]["text"] == "t"


def test_migrate_leaves_old_score_rows_revision_null(old_conn):
    migrate.migrate(old_conn)
    row = old_conn.execute("SELECT revision_id FROM score LIMIT 1").fetchone()
    assert row["revision_id"] is None            # historical rows stay honestly NULL


def test_migrate_idempotent_double_run(old_conn):
    migrate.migrate(old_conn)
    n_revisions_1 = old_conn.execute("SELECT COUNT(*) c FROM target_revision").fetchone()["c"]
    n_scores_1 = old_conn.execute("SELECT COUNT(*) c FROM score").fetchone()["c"]
    migrate.migrate(old_conn)                    # run again — must be a no-op
    n_revisions_2 = old_conn.execute("SELECT COUNT(*) c FROM target_revision").fetchone()["c"]
    n_scores_2 = old_conn.execute("SELECT COUNT(*) c FROM score").fetchone()["c"]
    assert n_revisions_1 == n_revisions_2
    assert n_scores_1 == n_scores_2
    cols = [r["name"] for r in old_conn.execute("PRAGMA table_info(score)")]
    assert cols.count("revision_id") == 1        # ALTER TABLE didn't run twice


def test_migrated_schema_equivalent_to_fresh_seed(old_conn, tmp_path, monkeypatch):
    migrate.migrate(old_conn)
    migrated_tables = _tables(old_conn)

    from palimpsest.webapp import db as db_mod
    monkeypatch.setattr(db_mod, "DB_PATH", tmp_path / "fresh.db")
    monkeypatch.setattr(db_mod, "_conn", None)
    fresh_conn = db_mod.init_db(reset=True)
    fresh_tables = _tables(fresh_conn)

    # Every table in the fresh SCHEMA exists (with the same columns) in the
    # migrated DB — a migrated prod DB and a freshly-seeded dev/test DB have
    # the same *shape*, per spec §2.4's "fresh-seed vs migrated" equivalence.
    for table, cols in fresh_tables.items():
        assert table in migrated_tables, f"missing table after migrate: {table}"
        assert cols <= migrated_tables[table], f"missing columns in {table}: {cols - migrated_tables[table]}"


def test_migrate_cli_help_runs():
    """`python -m palimpsest.webapp.migrate --help` must exit 0 (argparse's
    --help path) without touching a real DB connection."""
    import sys
    old_argv = sys.argv
    try:
        sys.argv = ["migrate.py", "--help"]
        with pytest.raises(SystemExit) as ei:
            migrate.main()
        assert ei.value.code == 0
    finally:
        sys.argv = old_argv
