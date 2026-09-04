"""Document picker curation (2026-07-16, owner UI review #1): hide the two
retired demo documents from GET /api/documents while keeping them fully
present -- score/issue rows untouched, still reachable via
GET /api/documents/{id}. See docs/superpowers/specs/2026-06-30-demo-
contracts.md "Document picker curation delta" and migrate.py's
_curate_demo_documents.
"""
from __future__ import annotations

import sqlite3

from palimpsest.webapp import db, migrate

# ── app-level: GET /api/documents filters hidden, GET /{id} does not ───────

def test_list_documents_excludes_hidden(client):
    conn = db.connect()
    visible_id = conn.execute(
        "INSERT INTO document(title,source_lang,target_lang,version,origin,created_at,hidden) "
        "VALUES('World History — Selected Passages','ru','en',0,'upload','now',0)").lastrowid
    hidden_id = conn.execute(
        "INSERT INTO document(title,source_lang,target_lang,version,origin,created_at,hidden) "
        "VALUES('Mesopotamia — ancient Near East','ru','en',0,'seed','now',1)").lastrowid
    conn.commit()

    ids = [d["id"] for d in client.get("/api/documents").json()]
    assert visible_id in ids
    assert hidden_id not in ids


def test_get_document_by_id_still_returns_hidden_doc(client):
    conn = db.connect()
    hidden_id = conn.execute(
        "INSERT INTO document(title,source_lang,target_lang,version,origin,created_at,hidden) "
        "VALUES('The Qin State — Ancient China','ru','en',0,'upload','now',1)").lastrowid
    conn.commit()

    r = client.get(f"/api/documents/{hidden_id}")
    assert r.status_code == 200
    assert r.json()["title"] == "The Qin State — Ancient China"


def test_list_documents_hidden_column_defaults_to_visible(client):
    # a document created without an explicit `hidden` value (e.g. via
    # POST /api/documents, which has no such field) stays visible.
    conn = db.connect()
    doc_id = conn.execute(
        "INSERT INTO document(title,source_lang,target_lang,version,origin,created_at) "
        "VALUES('A brand new upload','ru','en',0,'upload','now')").lastrowid
    conn.commit()
    ids = [d["id"] for d in client.get("/api/documents").json()]
    assert doc_id in ids


# ── migrate-level: title-prefix hide + suffix-strip rename, idempotent ─────

def _fresh_conn(tmp_path, name="curation.db"):
    path = tmp_path / name
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(db.SCHEMA)
    conn.commit()
    return conn


def _insert_doc(conn, title, origin="seed"):
    return conn.execute(
        "INSERT INTO document(title,source_lang,target_lang,version,origin,created_at) "
        "VALUES(?,?,?,0,?,?)", (title, "ru", "en", origin, "2026-01-01T00:00:00Z")).lastrowid


def test_curate_demo_documents_hides_by_title_prefix_and_renames(tmp_path):
    conn = _fresh_conn(tmp_path)
    keep_id = _insert_doc(
        conn, "World History — Selected Passages (Draft Translation)", origin="upload")
    hide_meso_id = _insert_doc(conn, "Mesopotamia — ancient Near East (pilot)", origin="seed")
    hide_qin_id = _insert_doc(conn, "The Qin State — Ancient China", origin="upload")
    other_id = _insert_doc(conn, "Some other upload", origin="upload")
    conn.commit()

    migrate._curate_demo_documents(conn)
    conn.commit()

    rows = {r["id"]: r for r in conn.execute("SELECT id, title, hidden FROM document")}
    assert rows[keep_id]["title"] == "World History — Selected Passages"
    assert rows[keep_id]["hidden"] == 0
    assert rows[hide_meso_id]["title"] == "Mesopotamia — ancient Near East"   # "(pilot)" stripped
    assert rows[hide_meso_id]["hidden"] == 1
    assert rows[hide_qin_id]["title"] == "The Qin State — Ancient China"  # no suffix, unchanged
    assert rows[hide_qin_id]["hidden"] == 1
    assert rows[other_id]["hidden"] == 0                                 # unrelated doc untouched


def test_curate_demo_documents_idempotent_double_run(tmp_path):
    conn = _fresh_conn(tmp_path)
    _insert_doc(conn, "World History — Selected Passages (Draft Translation)", origin="upload")
    _insert_doc(conn, "Mesopotamia — ancient Near East (pilot)", origin="seed")
    _insert_doc(conn, "The Qin State — Ancient China", origin="upload")
    conn.commit()

    migrate._curate_demo_documents(conn)
    conn.commit()
    state_1 = [dict(r) for r in conn.execute("SELECT id,title,hidden FROM document ORDER BY id")]

    migrate._curate_demo_documents(conn)  # second run must be a no-op
    conn.commit()
    state_2 = [dict(r) for r in conn.execute("SELECT id,title,hidden FROM document ORDER BY id")]

    assert state_1 == state_2


def test_curate_demo_documents_never_touches_scores_or_issues(tmp_path):
    """The hidden document's score/issue rows survive curation byte-for-byte
    -- hiding is a `document.hidden` flag flip only (owner hard invariant
    against deleting predictions, .claude/rules/invariants.md)."""
    conn = _fresh_conn(tmp_path)
    conn.execute("INSERT INTO model(name,base_url,api_key,params_json) VALUES('m','u','k','{}')")
    conn.execute(
        "INSERT INTO criterion(id,name,model_name,prompt,scale_min,scale_max,weight,color,enabled) "
        "VALUES('accuracy','Accuracy','m','p',1.0,10.0,0.4,'#4d8dff',1)")
    doc_id = _insert_doc(conn, "Mesopotamia — ancient Near East (pilot)", origin="seed")
    pid = conn.execute(
        "INSERT INTO paragraph(document_id,idx,source,target,seed_target) VALUES(?,0,'s','t','t')",
        (doc_id,)).lastrowid
    conn.execute(
        "INSERT INTO score(paragraph_id,criterion_id,value,summary,aggregate,criteria_key,"
        "kind,created_at) VALUES(?,'accuracy',8.0,'ok',8.0,'accuracy','seed',"
        "'2026-01-01T00:00:00Z')", (pid,))
    conn.execute(
        "INSERT INTO issue(paragraph_id,criterion_id,target_fragment,source_fragment,explanation,"
        "suggestion,severity,mqm_category,status,kind,created_at) VALUES"
        "(?,'accuracy','tf','sf','e','sg','minor',NULL,'open','seed','2026-01-01T00:00:00Z')",
        (pid,))
    conn.commit()

    before_score = dict(conn.execute("SELECT * FROM score").fetchone())
    before_issue = dict(conn.execute("SELECT * FROM issue").fetchone())

    migrate._curate_demo_documents(conn)
    conn.commit()

    after_score = dict(conn.execute("SELECT * FROM score").fetchone())
    after_issue = dict(conn.execute("SELECT * FROM issue").fetchone())
    assert before_score == after_score
    assert before_issue == after_issue
    assert conn.execute("SELECT COUNT(*) c FROM score").fetchone()["c"] == 1
    assert conn.execute("SELECT COUNT(*) c FROM issue").fetchone()["c"] == 1
    hidden_row = conn.execute("SELECT hidden FROM document WHERE id=?", (doc_id,)).fetchone()
    assert hidden_row["hidden"] == 1


def test_add_document_hidden_column_idempotent(tmp_path):
    path = tmp_path / "old.db"
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(
        "CREATE TABLE document ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, source_lang TEXT, target_lang TEXT,"
        "version INTEGER DEFAULT 0, origin TEXT DEFAULT 'seed', created_at TEXT,"
        "terms_status TEXT NOT NULL DEFAULT 'none')"
    )
    conn.execute("INSERT INTO document(title) VALUES('X')")
    conn.commit()

    migrate._add_document_hidden_column(conn)
    migrate._add_document_hidden_column(conn)  # must not raise or duplicate the column
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(document)")]
    assert cols.count("hidden") == 1
    row = conn.execute("SELECT hidden FROM document").fetchone()
    assert row["hidden"] == 0  # pre-existing row backfilled to visible by the ALTER's DEFAULT


def test_full_migrate_pipeline_curates_documents_too(tmp_path, monkeypatch):
    """migrate() (the full pipeline the app runs at every startup) applies
    curation alongside all its other steps, without any special setup, and
    stays idempotent across repeated runs."""
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "boot.db")
    monkeypatch.setattr(db, "_conn", None)
    conn = db.init_db(reset=True)
    _insert_doc(conn, "The Qin State — Ancient China", origin="upload")
    conn.commit()

    migrate.migrate(conn)
    row = conn.execute(
        "SELECT hidden FROM document WHERE title='The Qin State — Ancient China'").fetchone()
    assert row["hidden"] == 1

    migrate.migrate(conn)  # idempotent
    row2 = conn.execute(
        "SELECT hidden FROM document WHERE title='The Qin State — Ancient China'").fetchone()
    assert row2["hidden"] == 1
