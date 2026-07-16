"""SQLite layer for the demo backend (rev-4 contract §4).

Session isolation (2026-07-16, docs/superpowers/specs/2026-07-16-session-isolation.md):
``/data/demo.db`` is the **golden** template, mutated only by startup
procedures (migrate/curation/sweep/seed) and by golden-token requests from
the owner. Every regular browser session gets its own lazily-cloned SQLite
file under ``SESSIONS_DIR`` (``sqlite3`` backup API — the golden DB is a few
MB, so a clone is effectively instant) so parallel reviewers never see or
mutate each other's data. Routing is a ``contextvars.ContextVar`` the
ASGI session middleware (``app.py``) sets before the request handler runs;
``connect()``/``current_lock()`` below resolve against it. Every existing
``db.connect()`` call site (37 of them across the module) is UNCHANGED —
only what ``connect()`` returns changed.

**Test compatibility (load-bearing):** 17 existing test files directly
monkeypatch ``db.DB_PATH``/``db._conn`` to point at an isolated tmp DB and
treat the whole test as ONE shared connection/lock, exactly like the
pre-session-isolation code did. ``connect()``/``current_lock()``/
``current_sid()`` all check ``_conn is not None`` FIRST, unconditionally,
before consulting any session/contextvar routing — so those fixtures keep
working with no edits, regardless of what sid the ASGI middleware happens to
assign to a TestClient request made from inside such a test.
"""
from __future__ import annotations

import logging
import os
import sqlite3
import threading
import time
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path

from .. import paths

logger = logging.getLogger(__name__)

DB_PATH = Path(os.environ.get("PALIMPSEST_DB", str(paths.DATA / "demo.db")))
SESSIONS_DIR = Path(os.environ.get(
    "PALIMPSEST_SESSIONS_DIR", str(DB_PATH.parent / "sessions")))

GOLDEN_SID = "__golden__"          # owner golden-token requests route here
_LEGACY_SID = "__legacy__"         # current_sid()'s answer whenever legacy `_conn` is in play

# ─────────────────────────── legacy single-connection mode ───────────────────────────
# `_lock`/`_conn` are the ENTIRE pre-session-isolation design: one process-wide
# SQLite connection, one process-wide write lock (the app runs single-writer,
# `uvicorn --workers 1`). They are kept exactly as-is — `_conn` is the load-bearing
# test-compat escape hatch above, and `_lock` doubles as the write lock for the
# GOLDEN connection too (golden mutation is already single-writer: startup
# procedures run before any request is served, and golden-token requests are rare
# owner-only traffic — no reason to invent a second lock object for it).
_lock = threading.Lock()
_conn: sqlite3.Connection | None = None

# ─────────────────────────── golden connection (production) ───────────────────────────
_golden_conn: sqlite3.Connection | None = None
_golden_conn_path: Path | None = None   # detects a monkeypatched DB_PATH across repeated
                                         # ASGI lifespan cycles within one test process

# ─────────────────────────── session routing ───────────────────────────
_session_id: ContextVar[str | None] = ContextVar("glossa_session_id", default=None)
_startup_done = False


@dataclass
class SessionConn:
    conn: sqlite3.Connection
    lock: threading.Lock
    last_used: float


_sessions: dict[str, SessionConn] = {}
_sessions_guard = threading.Lock()

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE document (
  id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, source_lang TEXT, target_lang TEXT,
  source_model TEXT, seed_model TEXT, seed_prompt_variant TEXT,
  version INTEGER DEFAULT 0, origin TEXT DEFAULT 'seed', created_at TEXT,
  terms_status TEXT NOT NULL DEFAULT 'none',
  hidden INTEGER NOT NULL DEFAULT 0   -- picker curation (2026-07-16); deep link ignores it
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
CREATE TABLE refiner_config (   -- singleton, mirrors translator_config (EMNLP sprint 2026-07-11)
  id INTEGER PRIMARY KEY CHECK (id = 1),
  model_name TEXT REFERENCES model(name),
  prompt TEXT,
  params_json TEXT
);
"""

# `model` is referenced by `criterion` FK but created after it; SQLite resolves
# table references lazily, so declaration order is fine.


def _open_conn(path: Path) -> sqlite3.Connection:
    """Open one SQLite connection with this app's standard settings (shared
    across FastAPI threads, row access by name, FK enforcement on)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def current_sid() -> str | None:
    """Single source of truth for "which session is this call in". Every
    module rekeying its in-memory state to ``(current_sid(), doc_id)`` reads
    this, and so does ``connect()``/``current_lock()`` below.

    Legacy test mode (module ``_conn`` monkeypatched directly — the 17 test
    files this module's docstring describes) always answers the same
    constant, regardless of whatever real sid the ASGI session middleware
    assigned to a TestClient request made from inside such a test — so every
    module's in-memory bookkeeping collapses onto one key per test, exactly
    like the single global dict/set design before session isolation existed.
    """
    if _conn is not None:
        return _LEGACY_SID
    return _session_id.get()


def set_startup_done() -> None:
    """Flip the "the app is now serving requests" flag — called once, at the
    end of the lifespan's startup phase (after the golden-only migrate/sweep/
    wipe sequence), so that every ``connect()``/``current_lock()`` call from
    then on must resolve through a real session (or fail loud)."""
    global _startup_done
    _startup_done = True


def _connect_golden() -> sqlite3.Connection:
    """The one long-lived connection to the golden DB at ``DB_PATH``,
    (re)opened whenever ``DB_PATH`` itself changes — this happens for real
    only in tests that repeatedly enter/exit the ASGI lifespan against a
    different monkeypatched ``DB_PATH`` each time (e.g. ``test_migrate.py``'s
    ``with TestClient(app) as client:`` cases); the app's lifespan also
    explicitly closes and resets this on shutdown (see ``app.py``) so a
    fresh lifespan cycle never reads a stale golden connection."""
    global _golden_conn, _golden_conn_path
    if _golden_conn is None or _golden_conn_path != DB_PATH:
        if _golden_conn is not None:
            _golden_conn.close()
        _golden_conn = _open_conn(DB_PATH)
        _golden_conn_path = DB_PATH
    return _golden_conn


def clone_golden(sid: str) -> Path:
    """Backup-API clone of the golden DB into ``SESSIONS_DIR/<sid>.db`` —
    golden is a couple MB at this demo's scale, so the copy is effectively
    instant. Golden's own write lock (``_lock``) is held for the copy so a
    concurrent golden-token write can't produce a torn clone. Returns the
    clone's path; does not open it (see ``_get_or_clone_session``, the only
    caller, for the double-checked-locking wrapper around this)."""
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    dest_path = SESSIONS_DIR / f"{sid}.db"
    golden = _connect_golden()
    dest_conn = sqlite3.connect(str(dest_path))
    try:
        with _lock:
            golden.backup(dest_conn)
    finally:
        dest_conn.close()
    return dest_path


def _get_or_clone_session(sid: str) -> SessionConn:
    """Cache lookup with double-checked locking around the clone-on-first-use
    path (spec: sync endpoints run in real anyio-pool threads, so the race on
    a brand-new sid's first request is real). ``_sessions_guard`` protects
    the cache dict itself; each session's own ``SessionConn.lock`` is a
    SEPARATE per-session lock, acquired by ``current_lock()`` — holding the
    guard only for the (sub-millisecond) clone+insert, never for the
    session's own query traffic."""
    entry = _sessions.get(sid)
    if entry is None:
        with _sessions_guard:
            entry = _sessions.get(sid)             # re-check under the guard
            if entry is None:
                dest_path = clone_golden(sid)
                conn = _open_conn(dest_path)
                entry = SessionConn(conn=conn, lock=threading.Lock(), last_used=time.monotonic())
                _sessions[sid] = entry
                logger.info("session clone created sid=%s", sid[:8])
    entry.last_used = time.monotonic()
    return entry


def connect() -> sqlite3.Connection:
    """Resolve the connection for the current call per the session-routing
    matrix (docs/superpowers/specs/2026-07-16-session-isolation.md):
    legacy test compat -> startup phase -> golden-token -> per-session clone
    -> fail-loud without a session id. Every existing call site (``conn =
    db.connect()``) is unchanged; only the resolution logic here changed."""
    if _conn is not None:
        return _conn                               # legacy test compat, unconditional
    sid = current_sid()
    if not _startup_done or sid == GOLDEN_SID:
        return _connect_golden()
    if sid is None:
        raise RuntimeError(
            "db.connect() called with no session id after startup — the "
            "/api/* session middleware should have set one before the handler ran")
    return _get_or_clone_session(sid).conn


def current_lock() -> threading.Lock:
    """Per-session accessor replacing the old global ``db._lock`` at call
    sites (``with db.current_lock():``). Same routing matrix as ``connect()``
    — legacy/startup/golden-token all serialize on the single global
    ``_lock`` (golden and the legacy single-DB test mode are both
    single-writer by construction); a real per-sid session gets its OWN
    lock, so two sessions' writes never block each other."""
    if _conn is not None:
        return _lock
    sid = current_sid()
    if not _startup_done or sid == GOLDEN_SID:
        return _lock
    if sid is None:
        raise RuntimeError(
            "db.current_lock() called with no session id after startup — the "
            "/api/* session middleware should have set one before the handler ran")
    return _get_or_clone_session(sid).lock


def touch(sid: str | None) -> None:
    """Explicit ``last_used`` refresh for a long-running background task
    (translate/precompute/terminology_live) that captured ``conn =
    db.connect()`` once at task start and therefore doesn't naturally
    re-trigger ``connect()``/``current_lock()``'s own bump on every
    per-paragraph write — called from each module's per-paragraph write
    helper (spec §"Распространение контекста"). A no-op for a sid with no
    live cache entry (golden/legacy never have one)."""
    if sid is None:
        return
    with _sessions_guard:
        entry = _sessions.get(sid)
        if entry is not None:
            entry.last_used = time.monotonic()


def close_session(sid: str) -> None:
    """Close and unlink one session's clone (TTL sweep / explicit cleanup).
    Safe to call for a sid with no cached entry — just removes any leftover
    files (e.g. a stale ``-wal``/``-shm`` sibling)."""
    with _sessions_guard:
        entry = _sessions.pop(sid, None)
    if entry is not None:
        entry.conn.close()
    for p in SESSIONS_DIR.glob(f"{sid}.db*"):
        p.unlink(missing_ok=True)


def wipe_sessions() -> None:
    """Startup-time wipe of every session clone left over from a prior
    process ("рестарт = свежий стенд для всех" — owner decision 2026-07-16).
    Closes any cached connections first (defensive — a fresh process's
    ``_sessions`` is normally already empty at this point) then deletes
    every ``<sid>.db*`` file under ``SESSIONS_DIR``, including ``-wal``/
    ``-shm`` siblings."""
    with _sessions_guard:
        for entry in _sessions.values():
            entry.conn.close()
        _sessions.clear()
    if not SESSIONS_DIR.exists():
        return
    for p in SESSIONS_DIR.glob("*.db*"):
        p.unlink(missing_ok=True)


def init_db(*, reset: bool = False) -> sqlite3.Connection:
    """Create the schema. With ``reset`` drop the file first (used by seed).

    Legacy/build-time helper — always operates on the module-global ``_conn``
    at ``DB_PATH`` (never on a session clone), exactly as before session
    isolation existed. Used by ``seed.py`` (a build-time script, not the live
    server) and directly by test fixtures."""
    global _conn
    if reset and DB_PATH.exists():
        if _conn is not None:
            _conn.close()
            _conn = None
        DB_PATH.unlink()
    if _conn is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA foreign_keys = ON")
    conn = _conn
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
