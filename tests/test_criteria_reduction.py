"""EMNLP demo sprint (2026-07-11): criterion set collapses to
{accuracy, fluency, style} — a live prod DB carries 5 legacy criteria
(terminology + the already-disabled 'cultural') with score/issue history.
`migrate.migrate()` must archive that history (never delete — predictions are
irreproducible), delete the two retired criterion rows, and recompute the
`aggregate`/`criteria_key` stamped on every surviving score row so it reflects
only the 3 remaining criteria."""
from __future__ import annotations

import sqlite3

import pytest

from palimpsest.webapp import migrate
from palimpsest.webapp.aggregate import compute_aggregate
from palimpsest.webapp.model_matrix import DEFAULT_CRITERION_MODEL

OLD_MODEL = "openai/gpt-5.4-mini"  # a pre-sprint model name, on purpose

# 5 legacy criteria as they exist on the live prod DB today: the old
# 0.30/0.20/0.15/0.20 scheme plus the pre-wave-4 disabled 'cultural' row.
_LEGACY_CRITERIA = [
    ("accuracy", "Accuracy", 0.30, 1),
    ("fluency", "Fluency", 0.20, 1),
    ("style", "Style", 0.15, 1),
    ("terminology", "Terminology", 0.20, 1),
    ("cultural", "Cultural Adaptation", 0.20, 0),  # disabled legacy leftover
]


@pytest.fixture()
def prod_conn(tmp_path):
    """A DB shaped like the live prod DB pre-sprint: 5 criteria (one already
    disabled), all pointing at the retiring default model, with 'seed'/'cache'
    baseline scores+issues on EVERY criterion for one paragraph, plus a second
    paragraph carrying a partial 'live' re-evaluate history (only 'accuracy'
    re-scored after the original 4-criterion baseline) to exercise the
    pass-by-pass aggregate carry-forward."""
    path = tmp_path / "prod.db"
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        PRAGMA foreign_keys = ON;
        CREATE TABLE document (
          id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, source_lang TEXT, target_lang TEXT,
          source_model TEXT, seed_model TEXT, seed_prompt_variant TEXT,
          version INTEGER DEFAULT 0, origin TEXT DEFAULT 'seed', created_at TEXT
        );
        CREATE TABLE paragraph (
          id INTEGER PRIMARY KEY AUTOINCREMENT, document_id INTEGER REFERENCES document(id),
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
          id INTEGER PRIMARY KEY, paragraph_id INTEGER REFERENCES paragraph(id),
          criterion_id TEXT REFERENCES criterion(id), value REAL, summary TEXT,
          aggregate REAL, criteria_key TEXT, kind TEXT DEFAULT 'live', created_at TEXT,
          revision_id INTEGER REFERENCES target_revision(id)
        );
        CREATE TABLE issue (
          id INTEGER PRIMARY KEY, paragraph_id INTEGER REFERENCES paragraph(id),
          criterion_id TEXT REFERENCES criterion(id), target_fragment TEXT, source_fragment TEXT,
          explanation TEXT, suggestion TEXT, severity TEXT, mqm_category TEXT,
          status TEXT DEFAULT 'open', kind TEXT DEFAULT 'live', created_at TEXT
        );
        CREATE TABLE term (
          id INTEGER PRIMARY KEY, paragraph_id INTEGER REFERENCES paragraph(id),
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
          id INTEGER PRIMARY KEY CHECK (id = 1), model_name TEXT REFERENCES model(name),
          prompt TEXT, params_json TEXT
        );
        CREATE TABLE target_revision (
          id INTEGER PRIMARY KEY AUTOINCREMENT, paragraph_id INTEGER REFERENCES paragraph(id),
          text TEXT NOT NULL, origin TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE translator_config (
          id INTEGER PRIMARY KEY CHECK (id = 1), model_name TEXT REFERENCES model(name),
          prompt TEXT, params_json TEXT
        );
    """)
    conn.execute("INSERT INTO model(name,base_url,api_key,params_json) VALUES(?,?,?,?)",
                 (OLD_MODEL, "https://openrouter.ai/api/v1", "k", "{}"))
    for cid, name, weight, enabled in _LEGACY_CRITERIA:
        conn.execute(
            "INSERT INTO criterion(id,name,model_name,prompt,scale_min,scale_max,weight,color,enabled) "
            "VALUES(?,?,?,?,1.0,10.0,?,?,?)",
            (cid, name, OLD_MODEL, "p", weight, "#888", enabled))
    doc_id = conn.execute(
        "INSERT INTO document(title,source_lang,target_lang,source_model,version,origin,created_at) "
        "VALUES('T','ru','en','user',0,'seed','2026-01-01T00:00:00Z')").lastrowid

    # paragraph 1: full 4-criterion 'seed' + 'cache' baseline (mirrors real
    # seed.py — 'cultural' was already dropped from CRITERIA well before this
    # sprint, so only the 4 non-disabled criteria ever got scored)
    p1 = conn.execute(
        "INSERT INTO paragraph(document_id,idx,source,target,seed_target) VALUES(?,0,'s1','t1','t1')",
        (doc_id,)).lastrowid
    rev1 = conn.execute(
        "INSERT INTO target_revision(paragraph_id,text,origin,created_at) VALUES(?,'t1','seed','2026-01-01T00:00:00Z')",
        (p1,)).lastrowid
    seed_vals = {"accuracy": 8.0, "fluency": 7.0, "style": 6.0, "terminology": 9.0}
    legacy_crit_rows = conn.execute("SELECT * FROM criterion WHERE enabled=1").fetchall()
    seed_agg, seed_key = compute_aggregate(seed_vals, legacy_crit_rows)
    cache_vals = {k: v + 1.0 for k, v in seed_vals.items()}
    cache_agg, _ = compute_aggregate(cache_vals, legacy_crit_rows)
    for cid, val in seed_vals.items():
        conn.execute(
            "INSERT INTO score(paragraph_id,criterion_id,value,summary,aggregate,criteria_key,kind,created_at,revision_id) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (p1, cid, val, "s", seed_agg, seed_key, "seed", "2026-01-01T00:00:00Z", rev1))
        conn.execute(
            "INSERT INTO score(paragraph_id,criterion_id,value,summary,aggregate,criteria_key,kind,created_at,revision_id) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (p1, cid, cache_vals[cid], "s", cache_agg, seed_key, "cache", "2026-01-01T00:00:00Z", rev1))
        conn.execute(
            "INSERT INTO issue(paragraph_id,criterion_id,target_fragment,source_fragment,explanation,"
            "suggestion,severity,mqm_category,status,kind,created_at) "
            "VALUES(?,?,?,?,?,?,?,?,'open','seed',?)",
            (p1, cid, "frag", "srcfrag", "expl", "sug", "minor", None, "2026-01-01T00:00:00Z"))
    # one already-accepted terminology issue (history — must NOT be silently
    # resurrected as 'open', but must also no longer leak once archived)
    conn.execute(
        "INSERT INTO issue(paragraph_id,criterion_id,target_fragment,source_fragment,explanation,"
        "suggestion,severity,mqm_category,status,kind,created_at) "
        "VALUES(?,?,?,?,?,?,?,?,'accepted','seed',?)",
        (p1, "terminology", "old frag", "old src", "old expl", "", "minor", None, "2026-01-01T00:00:00Z"))

    # paragraph 2: a 'live' partial re-evaluate history — pass 1 scores ALL 4
    # legacy criteria, pass 2 only re-scores 'accuracy' (mirrors a real
    # partial POST /evaluate {criterionIds:['accuracy']})
    p2 = conn.execute(
        "INSERT INTO paragraph(document_id,idx,source,target,seed_target) VALUES(?,1,'s2','t2','t2')",
        (doc_id,)).lastrowid
    rev2 = conn.execute(
        "INSERT INTO target_revision(paragraph_id,text,origin,created_at) VALUES(?,'t2','seed','2026-01-01T00:00:00Z')",
        (p2,)).lastrowid
    pass1_vals = {"accuracy": 5.0, "fluency": 5.0, "style": 5.0, "terminology": 5.0}
    pass1_agg, pass1_key = compute_aggregate(pass1_vals, legacy_crit_rows)
    for cid, val in pass1_vals.items():
        conn.execute(
            "INSERT INTO score(paragraph_id,criterion_id,value,summary,aggregate,criteria_key,kind,created_at,revision_id) "
            "VALUES(?,?,?,?,?,?,'live',?,?)",
            (p2, cid, val, "s", pass1_agg, pass1_key, "2026-01-02T00:00:00Z", rev2))
    pass2_vals = {**pass1_vals, "accuracy": 9.0}
    pass2_agg, pass2_key = compute_aggregate(pass2_vals, legacy_crit_rows)
    conn.execute(
        "INSERT INTO score(paragraph_id,criterion_id,value,summary,aggregate,criteria_key,kind,created_at,revision_id) "
        "VALUES(?,'accuracy',9.0,'s',?,?,'live',?,?)",
        (p2, pass2_agg, pass2_key, "2026-01-03T00:00:00Z", rev2))

    conn.commit()
    return conn, p1, p2


def test_reduces_to_three_criteria(prod_conn):
    conn, _, _ = prod_conn
    migrate.migrate(conn)
    ids = {r["id"] for r in conn.execute("SELECT id FROM criterion")}
    assert ids == {"accuracy", "fluency", "style"}


def test_removed_criteria_score_rows_archived_not_deleted(prod_conn):
    conn, p1, _ = prod_conn
    n_before = conn.execute("SELECT COUNT(*) c FROM score WHERE criterion_id='terminology'").fetchone()["c"]
    assert n_before > 0
    migrate.migrate(conn)
    n_after = conn.execute("SELECT COUNT(*) c FROM score WHERE criterion_id='terminology'").fetchone()["c"]
    assert n_after == n_before, "score rows for a retired criterion must never be deleted"
    kinds = {r["kind"] for r in conn.execute("SELECT kind FROM score WHERE criterion_id='terminology'")}
    assert kinds == {"archived"}


def test_removed_criteria_issue_rows_archived_not_deleted(prod_conn):
    conn, p1, _ = prod_conn
    n_before = conn.execute("SELECT COUNT(*) c FROM issue WHERE criterion_id='terminology'").fetchone()["c"]
    assert n_before > 0
    migrate.migrate(conn)
    n_after = conn.execute("SELECT COUNT(*) c FROM issue WHERE criterion_id='terminology'").fetchone()["c"]
    assert n_after == n_before, "issue rows for a retired criterion must never be deleted"
    statuses = {r["status"] for r in conn.execute("SELECT status FROM issue WHERE criterion_id='terminology'")}
    assert statuses == {"archived"}, "including the previously-'accepted' row — archived hides it, never resurrects it"


def test_archived_issues_never_reach_para_issues_wire_shape(prod_conn):
    """Regression for the exact bug an over-broad status choice would cause:
    _para_issues (app.py) must never surface a dangling criterionId for a
    criterion row that no longer exists."""
    conn, p1, _ = prod_conn
    migrate.migrate(conn)
    from palimpsest.webapp.app import _para_issues
    issues = _para_issues(conn, p1)
    assert all(i["criterionId"] != "terminology" for i in issues)


def test_criterion_rows_actually_deleted(prod_conn):
    conn, _, _ = prod_conn
    migrate.migrate(conn)
    row = conn.execute("SELECT 1 FROM criterion WHERE id IN ('terminology','cultural')").fetchone()
    assert row is None


def test_weights_migrated_to_new_scheme(prod_conn):
    conn, _, _ = prod_conn
    migrate.migrate(conn)
    weights = {r["id"]: r["weight"] for r in conn.execute("SELECT id,weight FROM criterion")}
    assert weights == {"accuracy": 0.40, "fluency": 0.30, "style": 0.30}


def test_weight_migration_leaves_owner_customization_alone(tmp_path):
    """A criterion whose weight was already hand-edited via Settings (neither
    the old nor the new default) must not be silently reverted."""
    path = tmp_path / "customized.db"
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        PRAGMA foreign_keys = ON;
        CREATE TABLE document (id INTEGER PRIMARY KEY, title TEXT, source_lang TEXT, target_lang TEXT,
          source_model TEXT, seed_model TEXT, seed_prompt_variant TEXT, version INTEGER DEFAULT 0,
          origin TEXT DEFAULT 'seed', created_at TEXT);
        CREATE TABLE paragraph (id INTEGER PRIMARY KEY, document_id INTEGER, idx INTEGER,
          source TEXT, target TEXT, seed_target TEXT);
        CREATE TABLE criterion (id TEXT PRIMARY KEY, name TEXT, model_name TEXT REFERENCES model(name),
          prompt TEXT, scale_min REAL, scale_max REAL, weight REAL, color TEXT, enabled INTEGER DEFAULT 1);
        CREATE TABLE model (name TEXT PRIMARY KEY, base_url TEXT, api_key TEXT, params_json TEXT);
        CREATE TABLE score (id INTEGER PRIMARY KEY, paragraph_id INTEGER, criterion_id TEXT,
          value REAL, summary TEXT, aggregate REAL, criteria_key TEXT, kind TEXT DEFAULT 'live', created_at TEXT);
        CREATE TABLE issue (id INTEGER PRIMARY KEY, paragraph_id INTEGER, criterion_id TEXT,
          target_fragment TEXT, source_fragment TEXT, explanation TEXT, suggestion TEXT, severity TEXT,
          mqm_category TEXT, status TEXT DEFAULT 'open', kind TEXT DEFAULT 'live', created_at TEXT);
        CREATE TABLE term (id INTEGER PRIMARY KEY, paragraph_id INTEGER, source_surface TEXT,
          source_lemma TEXT, context TEXT, char_start INTEGER, char_end INTEGER, difficulty TEXT,
          grounded_json TEXT, candidates_json TEXT, target_surface TEXT, pair_accuracy TEXT,
          recommended TEXT, note TEXT, UNIQUE (paragraph_id, char_start, char_end));
        CREATE TABLE target_revision (id INTEGER PRIMARY KEY AUTOINCREMENT, paragraph_id INTEGER,
          text TEXT NOT NULL, origin TEXT NOT NULL, created_at TEXT NOT NULL);
    """)
    conn.execute("INSERT INTO model(name,base_url,api_key,params_json) VALUES(?,?,?,?)",
                 (OLD_MODEL, "https://openrouter.ai/api/v1", "k", "{}"))
    # owner hand-set accuracy's weight to 0.55 via Settings — neither 0.30 (old
    # default) nor 0.40 (new default)
    conn.execute(
        "INSERT INTO criterion(id,name,model_name,prompt,scale_min,scale_max,weight,color,enabled) "
        "VALUES('accuracy','Accuracy',?,'p',1.0,10.0,0.55,'#888',1)", (OLD_MODEL,))
    conn.commit()
    migrate.migrate(conn)
    assert conn.execute("SELECT weight FROM criterion WHERE id='accuracy'").fetchone()["weight"] == 0.55


def test_aggregate_recomputed_over_remaining_criteria_seed_and_cache(prod_conn):
    conn, p1, _ = prod_conn
    migrate.migrate(conn)
    remaining = conn.execute("SELECT * FROM criterion").fetchall()
    seed_rows = conn.execute(
        "SELECT * FROM score WHERE paragraph_id=? AND kind='seed'", (p1,)).fetchall()
    expected_agg, expected_key = compute_aggregate(
        {"accuracy": 8.0, "fluency": 7.0, "style": 6.0}, remaining)
    for r in seed_rows:
        assert r["aggregate"] == expected_agg
        assert r["criteria_key"] == expected_key == "accuracy,fluency,style"

    cache_rows = conn.execute(
        "SELECT * FROM score WHERE paragraph_id=? AND kind='cache'", (p1,)).fetchall()
    expected_cache_agg, _ = compute_aggregate(
        {"accuracy": 9.0, "fluency": 8.0, "style": 7.0}, remaining)
    for r in cache_rows:
        assert r["aggregate"] == expected_cache_agg


def test_aggregate_recomputed_over_remaining_criteria_live_carry_forward(prod_conn):
    """Paragraph 2's live history: pass 1 scored all 4 legacy criteria, pass 2
    re-scored only 'accuracy'. Post-migration, pass 2's aggregate must reflect
    accuracy's NEW value carried forward against fluency/style's pass-1
    values (mirrors evaluate()'s own "latest overridden by fresh successes"),
    entirely excluding the retired 'terminology' criterion from both passes."""
    conn, _, p2 = prod_conn
    migrate.migrate(conn)
    remaining = conn.execute("SELECT * FROM criterion").fetchall()

    pass1 = conn.execute(
        "SELECT * FROM score WHERE paragraph_id=? AND kind='live' AND created_at='2026-01-02T00:00:00Z'",
        (p2,)).fetchall()
    expected_pass1_agg, _ = compute_aggregate({"accuracy": 5.0, "fluency": 5.0, "style": 5.0}, remaining)
    for r in pass1:
        assert r["aggregate"] == expected_pass1_agg

    pass2 = conn.execute(
        "SELECT * FROM score WHERE paragraph_id=? AND kind='live' AND created_at='2026-01-03T00:00:00Z'",
        (p2,)).fetchall()
    assert len(pass2) == 1 and pass2[0]["criterion_id"] == "accuracy"
    expected_pass2_agg, expected_pass2_key = compute_aggregate(
        {"accuracy": 9.0, "fluency": 5.0, "style": 5.0}, remaining)
    assert pass2[0]["aggregate"] == expected_pass2_agg
    assert pass2[0]["criteria_key"] == expected_pass2_key == "accuracy,fluency,style"


def test_idempotent_double_run(prod_conn):
    conn, p1, p2 = prod_conn
    migrate.migrate(conn)
    criteria_1 = {dict(r)["id"]: dict(r) for r in conn.execute("SELECT * FROM criterion")}
    scores_1 = [dict(r) for r in conn.execute("SELECT * FROM score ORDER BY id")]
    issues_1 = [dict(r) for r in conn.execute("SELECT * FROM issue ORDER BY id")]

    migrate.migrate(conn)  # run again — must be a no-op
    criteria_2 = {dict(r)["id"]: dict(r) for r in conn.execute("SELECT * FROM criterion")}
    scores_2 = [dict(r) for r in conn.execute("SELECT * FROM score ORDER BY id")]
    issues_2 = [dict(r) for r in conn.execute("SELECT * FROM issue ORDER BY id")]

    assert criteria_1 == criteria_2
    assert scores_1 == scores_2
    assert issues_1 == issues_2


def test_migrate_no_op_when_criteria_already_reduced(tmp_path, monkeypatch):
    """A DB that's already on the new 3-criterion scheme (e.g. a freshly
    seeded dev DB) must sail through migrate() without error — the guard is
    existence-based, not a hardcoded 'was there a 5th row' assumption."""
    from palimpsest.webapp import db as db_mod
    monkeypatch.setattr(db_mod, "DB_PATH", tmp_path / "fresh.db")
    monkeypatch.setattr(db_mod, "_conn", None)
    conn = db_mod.init_db(reset=True)
    conn.execute("INSERT INTO model(name,base_url,api_key,params_json) VALUES(?,?,?,?)",
                 (DEFAULT_CRITERION_MODEL, "https://openrouter.ai/api/v1", "k", "{}"))
    conn.execute(
        "INSERT INTO criterion(id,name,model_name,prompt,scale_min,scale_max,weight,color,enabled) "
        "VALUES('accuracy','Accuracy',?,'p',1.0,10.0,0.40,'#888',1)", (DEFAULT_CRITERION_MODEL,))
    conn.commit()
    migrate.migrate(conn)  # must not raise
    ids = {r["id"] for r in conn.execute("SELECT id FROM criterion")}
    assert ids == {"accuracy"}


def test_foreign_keys_re_enabled_after_migration(prod_conn):
    """The PRAGMA foreign_keys=OFF window inside _reduce_to_three_criteria
    must not leak — FK enforcement must be back ON once migrate() returns."""
    conn, _, _ = prod_conn
    migrate.migrate(conn)
    row = conn.execute("PRAGMA foreign_keys").fetchone()
    assert row[0] == 1
