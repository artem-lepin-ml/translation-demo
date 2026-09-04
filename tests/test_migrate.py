"""Additive prod-DB migration (spec 2026-07-05-score-history-best §2.4 /
2026-07-05-translator §2.1): idempotent, and a migrated old-shape DB ends up
schema-equivalent to a freshly-seeded one."""
from __future__ import annotations

import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

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


def test_create_translator_config_skips_seed_when_model_absent(tmp_path):
    """_create_translator_config's own FK-safety fallback, exercised directly
    (not through the full migrate() pipeline): since 2026-07-11
    (_upsert_model_registry_and_remap, run first in migrate()), the full
    pipeline ALWAYS seeds a default model row before this step ever runs, so
    the "zero model rows at all" scenario this guards against is no longer
    reachable via migrate() itself — the underlying fallback logic is still
    real and still worth its own direct-call regression test."""
    path = tmp_path / "old2.db"
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(OLD_SCHEMA)
    conn.commit()
    migrate._create_translator_config(conn)
    row = conn.execute("SELECT * FROM translator_config WHERE id=1").fetchone()
    assert row is None                          # no FK target → left unseeded, honestly


def test_migrate_seeds_translator_config_even_from_a_bare_model_less_db(tmp_path):
    """The full migrate() pipeline, unlike the unit above, NEVER leaves
    translator_config unseeded any more — _upsert_model_registry_and_remap
    (run first) guarantees a default model row exists before
    _create_translator_config's FK-guard is even checked. A genuinely bare,
    never-migrated DB now bootstraps a working default instead of staying
    permanently unconfigured."""
    path = tmp_path / "bare.db"
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(OLD_SCHEMA)
    conn.commit()
    migrate.migrate(conn)
    row = conn.execute("SELECT * FROM translator_config WHERE id=1").fetchone()
    assert row is not None
    assert row["model_name"] == DEFAULT_CRITERION_MODEL


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


# The schema as it actually exists on prod TODAY (confirmed live via `docker
# exec` against gse-demo, 2026-07-06): target_revision/translator_config/
# score.revision_id/glossary already migrated in, but grounding_config was
# NEVER added (db.py SCHEMA gained it as a fresh-DB table without a matching
# migrate.py step) and term.trace_json is likewise absent — this is the exact
# drift that caused the GET /api/grounding-config 500 in prod.
PROD_SHAPED_SCHEMA = """
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
  aggregate REAL, criteria_key TEXT, kind TEXT DEFAULT 'live', created_at TEXT,
  revision_id INTEGER REFERENCES target_revision(id)
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
  UNIQUE (paragraph_id, char_start, char_end)
);
CREATE TABLE glossary (
  id INTEGER PRIMARY KEY, term TEXT, context TEXT, target_equivalent TEXT,
  wikidata_url TEXT NOT NULL, wikidata_id TEXT,
  UNIQUE (term, context)
);
CREATE TABLE target_revision (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  paragraph_id INTEGER REFERENCES paragraph(id) ON DELETE CASCADE,
  text TEXT NOT NULL,
  origin TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX idx_target_revision_para ON target_revision(paragraph_id, id);
CREATE TABLE translator_config (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  model_name TEXT REFERENCES model(name),
  prompt TEXT,
  params_json TEXT
);
"""


@pytest.fixture()
def prod_conn(tmp_path):
    """A DB shaped exactly like the live prod DB before this fix: every table
    that migrate.py already knew how to add is present (target_revision,
    translator_config + its singleton row, score.revision_id, glossary) —
    only grounding_config (missing table) and term.trace_json (missing
    column) are absent, reproducing the prod 500 root cause precisely."""
    path = tmp_path / "prod.db"
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(PROD_SHAPED_SCHEMA)
    conn.execute("INSERT INTO model(name,base_url,api_key,params_json) VALUES(?,?,?,?)",
                 (DEFAULT_CRITERION_MODEL, "https://openrouter.ai/api/v1", "k", "{}"))
    conn.execute("INSERT INTO criterion(id,name,model_name,prompt,scale_min,scale_max,weight,color,enabled) "
                 "VALUES('accuracy','Accuracy',?,'p',1.0,10.0,0.3,'#4d8dff',1)",
                 (DEFAULT_CRITERION_MODEL,))
    conn.execute(
        "INSERT INTO translator_config(id,model_name,prompt,params_json) VALUES(1,?,?,?)",
        (DEFAULT_CRITERION_MODEL, "some prompt", "{}"))
    doc_id = conn.execute(
        "INSERT INTO document(title,source_lang,target_lang,source_model,version,origin,created_at) "
        "VALUES('T','ru','en','user',0,'upload','2026-01-01T00:00:00Z')").lastrowid
    pid = conn.execute(
        "INSERT INTO paragraph(document_id,idx,source,target,seed_target) VALUES(?,?,?,?,?)",
        (doc_id, 0, "s", "t", "t")).lastrowid
    conn.execute(
        "INSERT INTO term(paragraph_id,source_surface,source_lemma,context,char_start,char_end,"
        "difficulty,target_surface,pair_accuracy,recommended,note) "
        "VALUES(?,'surf','lemma','ctx',0,4,'green','tgt','green',NULL,'')", (pid,))
    conn.execute(
        "INSERT INTO target_revision(paragraph_id,text,origin,created_at) VALUES(?,?,?,?)",
        (pid, "t", "seed", "2026-01-01T00:00:00Z"))
    conn.commit()
    return conn


def test_migrate_adds_grounding_config_table_and_seeds_row(prod_conn):
    migrate.migrate(prod_conn)
    tables = _tables(prod_conn)
    assert "grounding_config" in tables
    row = prod_conn.execute("SELECT * FROM grounding_config WHERE id=1").fetchone()
    assert row is not None
    assert row["model_name"] == DEFAULT_CRITERION_MODEL
    assert json.loads(row["params_json"]) == {"max_tokens": 512, "temperature": 0}
    assert row["prompt"]                          # non-empty judge prompt


def test_create_grounding_config_skips_seed_when_model_absent(tmp_path):
    """_create_grounding_config's own FK-safety fallback, exercised directly —
    see test_create_translator_config_skips_seed_when_model_absent above for
    why this is no longer reachable through the full migrate() pipeline."""
    path = tmp_path / "prod2.db"
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(PROD_SHAPED_SCHEMA)
    conn.commit()
    migrate._create_grounding_config(conn)
    assert "grounding_config" in _tables(conn)
    row = conn.execute("SELECT * FROM grounding_config WHERE id=1").fetchone()
    assert row is None                             # no FK target → left unseeded, honestly


def test_migrate_adds_term_trace_json_column_with_default(prod_conn):
    migrate.migrate(prod_conn)
    cols = _tables(prod_conn)["term"]
    assert "trace_json" in cols
    row = prod_conn.execute("SELECT trace_json FROM term LIMIT 1").fetchone()
    assert row["trace_json"] == "{}"               # pre-existing row backfilled by ALTER's DEFAULT


# ── document.terms_status (2026-07-11 EMNLP sprint: live terminology) ──────

def test_migrate_adds_document_terms_status_column_with_default_none(prod_conn):
    migrate.migrate(prod_conn)
    cols = _tables(prod_conn)["document"]
    assert "terms_status" in cols
    row = prod_conn.execute("SELECT terms_status FROM document LIMIT 1").fetchone()
    assert row["terms_status"] == "none"           # pre-existing (upload) row backfilled by ALTER's DEFAULT


def test_migrate_backfills_seed_document_terms_status_to_done(prod_conn):
    prod_conn.execute(
        "INSERT INTO document(title,source_lang,target_lang,source_model,version,origin,created_at) "
        "VALUES('Seed','ru','en','user',0,'seed','2026-01-01T00:00:00Z')")
    prod_conn.commit()
    migrate.migrate(prod_conn)
    rows = {r["origin"]: r["terms_status"] for r in prod_conn.execute("SELECT origin, terms_status FROM document")}
    assert rows["seed"] == "done"                  # already has precomputed terms
    assert rows["upload"] == "none"                # non-seed rows are left alone


def test_migrate_terms_status_backfill_idempotent_double_run(prod_conn):
    prod_conn.execute(
        "INSERT INTO document(title,source_lang,target_lang,source_model,version,origin,created_at) "
        "VALUES('Seed','ru','en','user',0,'seed','2026-01-01T00:00:00Z')")
    prod_conn.commit()
    migrate.migrate(prod_conn)
    migrate.migrate(prod_conn)                     # second run must not raise or change the result
    rows = {r["origin"]: r["terms_status"] for r in prod_conn.execute("SELECT origin, terms_status FROM document")}
    assert rows == {"seed": "done", "upload": "none"}


def test_migrate_keeps_glossary_table(prod_conn):
    migrate.migrate(prod_conn)
    assert "glossary" in _tables(prod_conn)


def test_migrate_prod_shaped_idempotent_double_run(prod_conn):
    migrate.migrate(prod_conn)
    tables_1 = _tables(prod_conn)
    gc_1 = prod_conn.execute("SELECT * FROM grounding_config WHERE id=1").fetchone()
    migrate.migrate(prod_conn)                     # run again — must be a no-op
    tables_2 = _tables(prod_conn)
    gc_2 = prod_conn.execute("SELECT * FROM grounding_config WHERE id=1").fetchone()
    assert tables_1 == tables_2
    assert dict(gc_1) == dict(gc_2)
    cols = [r["name"] for r in prod_conn.execute("PRAGMA table_info(term)")]
    assert cols.count("trace_json") == 1           # ALTER TABLE didn't run twice


def test_migrated_prod_shaped_schema_equivalent_to_fresh_seed(prod_conn, tmp_path, monkeypatch):
    migrate.migrate(prod_conn)
    migrated_tables = _tables(prod_conn)

    from palimpsest.webapp import db as db_mod
    monkeypatch.setattr(db_mod, "DB_PATH", tmp_path / "fresh2.db")
    monkeypatch.setattr(db_mod, "_conn", None)
    fresh_conn = db_mod.init_db(reset=True)
    fresh_tables = _tables(fresh_conn)

    for table, cols in fresh_tables.items():
        assert table in migrated_tables, f"missing table after migrate: {table}"
        assert cols <= migrated_tables[table], f"missing columns in {table}: {cols - migrated_tables[table]}"


def test_grounding_config_endpoint_200_on_migrated_prod_shaped_db(tmp_path, monkeypatch):
    """Regression test for the prod 500: a DB file that starts in the exact
    prod-shaped state (no grounding_config table, no term.trace_json) must
    still serve GET /api/grounding-config with 200 once the app boots — the
    app's own startup lifespan runs migrate() before any request is served,
    so this never hits the sqlite3.OperationalError('no such table:
    grounding_config') that caused the outage."""
    db_path = tmp_path / "prod_boot.db"
    setup_conn = sqlite3.connect(str(db_path))
    setup_conn.row_factory = sqlite3.Row
    setup_conn.executescript(PROD_SHAPED_SCHEMA)
    setup_conn.execute("INSERT INTO model(name,base_url,api_key,params_json) VALUES(?,?,?,?)",
                        (DEFAULT_CRITERION_MODEL, "https://openrouter.ai/api/v1", "k", "{}"))
    setup_conn.commit()
    setup_conn.close()

    monkeypatch.setattr(db, "DB_PATH", db_path)
    monkeypatch.setattr(db, "_conn", None)

    from palimpsest.webapp.app import app
    with TestClient(app) as client:                # __enter__ runs the lifespan → migrate()
        resp = client.get("/api/grounding-config")
    assert resp.status_code == 200
    body = resp.json()
    assert body["modelName"] == DEFAULT_CRITERION_MODEL


def test_grounding_config_endpoint_200_when_booted_from_a_bare_model_less_db(tmp_path, monkeypatch):
    """Same boot path, but starting with NO model row at all. Before
    2026-07-11 this left grounding_config permanently unseeded (FK-safety
    guard, null/default config forever) — since
    _upsert_model_registry_and_remap now runs first in migrate() and
    unconditionally seeds the 4-model registry, a bare DB now bootstraps a
    REAL default config instead. Either way the endpoint must return 200,
    never 500 — that's the one invariant both the old and new test versions
    protect."""
    db_path = tmp_path / "prod_boot_no_model.db"
    setup_conn = sqlite3.connect(str(db_path))
    setup_conn.executescript(PROD_SHAPED_SCHEMA)
    setup_conn.commit()
    setup_conn.close()

    monkeypatch.setattr(db, "DB_PATH", db_path)
    monkeypatch.setattr(db, "_conn", None)

    from palimpsest.webapp.app import app
    with TestClient(app) as client:
        resp = client.get("/api/grounding-config")
    assert resp.status_code == 200
    assert resp.json()["modelName"] == DEFAULT_CRITERION_MODEL


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
