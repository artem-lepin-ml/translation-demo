"""SQLite layer for the demo backend (rev-4 contract §4).

One file DB under data/. The connection is shared across FastAPI threads
(``check_same_thread=False``) and serialized by a module-level lock — the app
runs single-writer (``uvicorn --workers 1``), so a process lock is enough.
"""
from __future__ import annotations

import os
import sqlite3
import threading
from pathlib import Path

from .. import paths

DB_PATH = Path(os.environ.get("PALIMPSEST_DB", str(paths.DATA / "demo.db")))

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None

SCHEMA = """
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

# `model` is referenced by `criterion` FK but created after it; SQLite resolves
# table references lazily, so declaration order is fine.


def connect() -> sqlite3.Connection:
    """Return the shared connection (lazily opened)."""
    global _conn
    if _conn is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA foreign_keys = ON")
    return _conn


def init_db(*, reset: bool = False) -> sqlite3.Connection:
    """Create the schema. With ``reset`` drop the file first (used by seed)."""
    global _conn
    if reset and DB_PATH.exists():
        if _conn is not None:
            _conn.close()
            _conn = None
        DB_PATH.unlink()
    conn = connect()
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def row_to_dict(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row is not None else None


def latest_revision_id(conn: sqlite3.Connection, paragraph_id: int) -> int | None:
    """Id of the most recent ``target_revision`` row for a paragraph, or None if
    the paragraph has never had one written (e.g. pre-migration history)."""
    row = conn.execute(
        "SELECT id FROM target_revision WHERE paragraph_id=? ORDER BY id DESC LIMIT 1",
        (paragraph_id,)).fetchone()
    return row["id"] if row else None


def write_revision(conn: sqlite3.Connection, paragraph_id: int, text: str, origin: str, created_at: str) -> int:
    """Insert a new ``target_revision`` row and return its id. Caller owns the
    transaction/commit and the "did the text actually change" decision."""
    return conn.execute(
        "INSERT INTO target_revision(paragraph_id,text,origin,created_at) VALUES(?,?,?,?)",
        (paragraph_id, text, origin, created_at)).lastrowid
