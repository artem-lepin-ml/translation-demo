"""EMNLP demo sprint (2026-07-11): the model registry collapses to the 4
paper models (a 5th, TranslateGemma-27B, was dropped the same day once the
owner finalized the registry on prod via the Settings UI), migrate() upserts
them on a live prod DB and remaps every role reference (criterion/
translator_config/grounding_config/refiner_config) to the new default, then
prunes the 8 obsolete rows once nothing references them."""
from __future__ import annotations

import sqlite3

import pytest

from palimpsest.webapp import migrate
from palimpsest.webapp.model_matrix import DEFAULT_CRITERION_MODEL, MATRIX

OLD_MODEL = "openai/gpt-5.4-mini"
OLD_VLLM = "Qwen/Qwen3.6-27B"  # old vLLM placeholder name — NOT in the new MATRIX


@pytest.fixture()
def prod_conn(tmp_path):
    """A DB shaped like the live prod DB pre-sprint: 8 legacy model rows
    (5 OpenRouter + 3 vLLM, none of which share a name with the new 4),
    3 criteria + translator_config + grounding_config all pointing at the
    retiring default."""
    path = tmp_path / "prod.db"
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        PRAGMA foreign_keys = ON;
        CREATE TABLE document (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, source_lang TEXT,
          target_lang TEXT, source_model TEXT, seed_model TEXT, seed_prompt_variant TEXT,
          version INTEGER DEFAULT 0, origin TEXT DEFAULT 'seed', created_at TEXT);
        CREATE TABLE paragraph (id INTEGER PRIMARY KEY AUTOINCREMENT, document_id INTEGER,
          idx INTEGER, source TEXT, target TEXT, seed_target TEXT);
        CREATE TABLE criterion (id TEXT PRIMARY KEY, name TEXT, model_name TEXT REFERENCES model(name),
          prompt TEXT, scale_min REAL, scale_max REAL, weight REAL, color TEXT, enabled INTEGER DEFAULT 1);
        CREATE TABLE model (name TEXT PRIMARY KEY, base_url TEXT, api_key TEXT, params_json TEXT);
        CREATE TABLE score (id INTEGER PRIMARY KEY, paragraph_id INTEGER, criterion_id TEXT,
          value REAL, summary TEXT, aggregate REAL, criteria_key TEXT, kind TEXT DEFAULT 'live',
          created_at TEXT, revision_id INTEGER);
        CREATE TABLE issue (id INTEGER PRIMARY KEY, paragraph_id INTEGER, criterion_id TEXT,
          target_fragment TEXT, source_fragment TEXT, explanation TEXT, suggestion TEXT, severity TEXT,
          mqm_category TEXT, status TEXT DEFAULT 'open', kind TEXT DEFAULT 'live', created_at TEXT);
        CREATE TABLE term (id INTEGER PRIMARY KEY, paragraph_id INTEGER, source_surface TEXT,
          source_lemma TEXT, context TEXT, char_start INTEGER, char_end INTEGER, difficulty TEXT,
          grounded_json TEXT, candidates_json TEXT, target_surface TEXT, pair_accuracy TEXT,
          recommended TEXT, note TEXT, trace_json TEXT NOT NULL DEFAULT '{}',
          UNIQUE (paragraph_id, char_start, char_end));
        CREATE TABLE glossary (id INTEGER PRIMARY KEY, term TEXT, context TEXT, target_equivalent TEXT,
          wikidata_url TEXT NOT NULL, wikidata_id TEXT, UNIQUE (term, context));
        CREATE TABLE grounding_config (id INTEGER PRIMARY KEY CHECK (id = 1),
          model_name TEXT REFERENCES model(name), prompt TEXT, params_json TEXT);
        CREATE TABLE target_revision (id INTEGER PRIMARY KEY AUTOINCREMENT, paragraph_id INTEGER,
          text TEXT NOT NULL, origin TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE translator_config (id INTEGER PRIMARY KEY CHECK (id = 1),
          model_name TEXT REFERENCES model(name), prompt TEXT, params_json TEXT);
    """)
    legacy_models = [
        (OLD_MODEL, "https://openrouter.ai/api/v1"),
        ("anthropic/claude-haiku-4.5", "https://openrouter.ai/api/v1"),
        ("anthropic/claude-sonnet-5", "https://openrouter.ai/api/v1"),
        ("google/gemini-3.5-flash", "https://openrouter.ai/api/v1"),
        ("qwen/qwen3.6-plus", "https://openrouter.ai/api/v1"),
        ("Qwen/Qwen3-4B-Thinking-2507", "http://localhost:8001/v1"),
        ("Infomaniak-AI/vllm-translategemma-27b-it", "http://localhost:8001/v1"),
        (OLD_VLLM, "http://localhost:8001/v1"),
    ]
    for name, base_url in legacy_models:
        conn.execute("INSERT INTO model(name,base_url,api_key,params_json) VALUES(?,?,?,?)",
                     (name, base_url, "k" if "openrouter" in base_url else "", "{}"))
    for cid in ("accuracy", "fluency", "style"):
        conn.execute(
            "INSERT INTO criterion(id,name,model_name,prompt,scale_min,scale_max,weight,color,enabled) "
            "VALUES(?,?,?,?,1.0,10.0,0.33,'#888',1)", (cid, cid.title(), OLD_MODEL, "p"))
    conn.execute(
        "INSERT INTO translator_config(id,model_name,prompt,params_json) VALUES(1,?,?,?)",
        (OLD_MODEL, "translate prompt", "{}"))
    conn.execute(
        "INSERT INTO grounding_config(id,model_name,prompt,params_json) VALUES(1,?,?,?)",
        (OLD_MODEL, "ground prompt", "{}"))
    conn.commit()
    return conn


def test_four_matrix_models_present_after_migration(prod_conn):
    migrate.migrate(prod_conn)
    names = {r["name"] for r in prod_conn.execute("SELECT name FROM model")}
    assert names == set(MATRIX.keys())


def test_obsolete_model_rows_pruned(prod_conn):
    migrate.migrate(prod_conn)
    row = prod_conn.execute(
        "SELECT 1 FROM model WHERE name IN (?,?,?,?,?)",
        (OLD_MODEL, "anthropic/claude-haiku-4.5", "anthropic/claude-sonnet-5",
         "google/gemini-3.5-flash", OLD_VLLM)).fetchone()
    assert row is None


def test_criteria_remapped_to_new_default(prod_conn):
    migrate.migrate(prod_conn)
    for r in prod_conn.execute("SELECT model_name FROM criterion"):
        assert r["model_name"] == DEFAULT_CRITERION_MODEL


def test_translator_config_remapped_to_new_default(prod_conn):
    migrate.migrate(prod_conn)
    row = prod_conn.execute("SELECT model_name, prompt FROM translator_config WHERE id=1").fetchone()
    assert row["model_name"] == DEFAULT_CRITERION_MODEL
    assert row["prompt"] == "translate prompt", "remap touches model_name only, never the owner's prompt"


def test_grounding_config_remapped_to_new_default(prod_conn):
    migrate.migrate(prod_conn)
    row = prod_conn.execute("SELECT model_name FROM grounding_config WHERE id=1").fetchone()
    assert row["model_name"] == DEFAULT_CRITERION_MODEL


def test_refiner_config_created_and_seeded_with_new_default(prod_conn):
    migrate.migrate(prod_conn)
    row = prod_conn.execute("SELECT model_name, prompt, params_json FROM refiner_config WHERE id=1").fetchone()
    assert row is not None
    assert row["model_name"] == DEFAULT_CRITERION_MODEL
    assert "expert translation editor" in row["prompt"]
    assert row["params_json"]


def test_translategemma_not_in_matrix_and_never_inserted(prod_conn):
    """TranslateGemma-27B (the local vLLM placeholder from the 2026-07-11
    sprint's original 5-row draft) was dropped once the owner finalized the
    registry to 4 OpenRouter-only rows on prod — migrate() must never
    (re)insert it."""
    assert "TranslateGemma-27B" not in MATRIX
    migrate.migrate(prod_conn)
    row = prod_conn.execute("SELECT 1 FROM model WHERE name='TranslateGemma-27B'").fetchone()
    assert row is None


def test_translategemma_pruned_if_present_from_pre_finalization_snapshot(prod_conn):
    """A DB snapshotted before the owner's prod finalization may still carry
    the row from the sprint's original 5-row draft — migrate() prunes it like
    any other now-obsolete, unreferenced model row (never re-added since it
    is no longer in MATRIX)."""
    prod_conn.execute(
        "INSERT INTO model(name,base_url,api_key,params_json) VALUES(?,?,?,?)",
        ("TranslateGemma-27B", "http://localhost:8001/v1", "", "{}"))
    prod_conn.commit()
    migrate.migrate(prod_conn)
    row = prod_conn.execute("SELECT 1 FROM model WHERE name='TranslateGemma-27B'").fetchone()
    assert row is None


def test_owner_edited_api_key_not_clobbered_on_second_run(prod_conn):
    """INSERT OR IGNORE semantics: once the qwen row exists, migrate() must
    never overwrite an api_key/params the owner set via Settings."""
    migrate.migrate(prod_conn)
    prod_conn.execute("UPDATE model SET api_key='sk-owner-set', params_json='{\"temperature\":0.9}' "
                       "WHERE name=?", (DEFAULT_CRITERION_MODEL,))
    prod_conn.commit()
    migrate.migrate(prod_conn)  # run again — must not clobber the owner's edit
    row = prod_conn.execute("SELECT api_key, params_json FROM model WHERE name=?",
                             (DEFAULT_CRITERION_MODEL,)).fetchone()
    assert row["api_key"] == "sk-owner-set"
    assert row["params_json"] == '{"temperature":0.9}'


def test_operator_set_current_matrix_criterion_model_survives_migrate(prod_conn):
    """Durability fix (2026-07-16, CRITICAL): _upsert_model_registry_and_remap
    used to test `model_name != DEFAULT_CRITERION_MODEL`, so an operator's
    deliberate choice of any OTHER current-MATRIX model (e.g. qwen, kept in
    place after gemini became the default) was silently reverted back to the
    default on the very next migrate() run — and migrate() runs on every app
    startup (app.py lifespan), i.e. every restart/redeploy. The fixed
    predicate (`model_name NOT IN (<MATRIX names>)`) must leave it alone."""
    migrate.migrate(prod_conn)  # first run: bootstraps the default onto every role
    other_matrix_model = next(name for name in MATRIX if name != DEFAULT_CRITERION_MODEL)
    prod_conn.execute("UPDATE criterion SET model_name=? WHERE id='accuracy'", (other_matrix_model,))
    prod_conn.commit()
    migrate.migrate(prod_conn)  # simulates a container restart/redeploy
    row = prod_conn.execute("SELECT model_name FROM criterion WHERE id='accuracy'").fetchone()
    assert row["model_name"] == other_matrix_model, \
        "operator's current-MATRIX model choice must survive a migrate() restart"


def test_operator_set_current_matrix_model_survives_migrate(prod_conn):
    """Same durability fix as above, for the singleton configs
    (translator_config/grounding_config/refiner_config via
    _remap_singleton_config_model_refs) — an operator's current-MATRIX model
    choice for grounding (e.g. gemini, distinct from a non-gemini default)
    must survive a migrate() re-run, not just the first one."""
    migrate.migrate(prod_conn)
    other_matrix_model = next(name for name in MATRIX if name != DEFAULT_CRITERION_MODEL)
    prod_conn.execute("UPDATE grounding_config SET model_name=? WHERE id=1", (other_matrix_model,))
    prod_conn.commit()
    migrate.migrate(prod_conn)  # simulates a container restart/redeploy
    row = prod_conn.execute("SELECT model_name FROM grounding_config WHERE id=1").fetchone()
    assert row["model_name"] == other_matrix_model, \
        "operator's current-MATRIX model choice must survive a migrate() restart"


def test_idempotent_double_run_registry(prod_conn):
    migrate.migrate(prod_conn)
    models_1 = {dict(r)["name"]: dict(r) for r in prod_conn.execute("SELECT * FROM model")}
    migrate.migrate(prod_conn)
    models_2 = {dict(r)["name"]: dict(r) for r in prod_conn.execute("SELECT * FROM model")}
    assert models_1 == models_2


def test_still_referenced_model_row_not_pruned(tmp_path):
    """Defensive branch: if a model row outside MATRIX is somehow still
    referenced (e.g. a criterion the remap step didn't cover), prune must
    skip it rather than leaving a dangling FK or raising."""
    path = tmp_path / "edge.db"
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        PRAGMA foreign_keys = ON;
        CREATE TABLE criterion (id TEXT PRIMARY KEY, name TEXT, model_name TEXT REFERENCES model(name),
          prompt TEXT, scale_min REAL, scale_max REAL, weight REAL, color TEXT, enabled INTEGER DEFAULT 1);
        CREATE TABLE model (name TEXT PRIMARY KEY, base_url TEXT, api_key TEXT, params_json TEXT);
        CREATE TABLE translator_config (id INTEGER PRIMARY KEY CHECK (id = 1),
          model_name TEXT REFERENCES model(name), prompt TEXT, params_json TEXT);
        CREATE TABLE grounding_config (id INTEGER PRIMARY KEY CHECK (id = 1),
          model_name TEXT REFERENCES model(name), prompt TEXT, params_json TEXT);
        CREATE TABLE refiner_config (id INTEGER PRIMARY KEY CHECK (id = 1),
          model_name TEXT REFERENCES model(name), prompt TEXT, params_json TEXT);
    """)
    conn.execute("INSERT INTO model(name,base_url,api_key,params_json) VALUES('weird/off-matrix','u','k','{}')")
    # a disabled criterion still pointing off-matrix — _upsert_model_registry_and_remap
    # remaps unconditionally (WHERE model_name!=DEFAULT), so this row would
    # normally get repointed too; simulate the defensive path directly.
    conn.commit()
    from palimpsest.webapp.migrate import _prune_obsolete_model_rows
    conn.execute(
        "INSERT INTO criterion(id,name,model_name,prompt,scale_min,scale_max,weight,color,enabled) "
        "VALUES('x','X','weird/off-matrix','p',1,10,1,'#888',1)")
    conn.commit()
    _prune_obsolete_model_rows(conn)
    assert conn.execute("SELECT 1 FROM model WHERE name='weird/off-matrix'").fetchone() is not None
