"""Session isolation (2026-07-16,
docs/superpowers/specs/2026-07-16-session-isolation.md) — success criterion 3:
cookie is set, two sids are isolated after a mutation, connect()/
current_lock() fail loud without a sid post-startup, the clone-on-first-use
race is double-checked-locked, the TTL sweep removes a stale session's file
AND its keys from all seven in-memory structures while sparing a sid with a
live task, wipe_sessions() clears leftover files (incl. -wal/-shm), and a
golden-token request routes to golden and is visible to a brand-new session.

No paid LLM calls anywhere in this file — every document created here is a
plain non-translate/non-precompute upload (no background LLM call is ever
scheduled for its content path; the module's own terminology_live launch is
still triggered but fails fast on the absent grounding_config, no network).
"""
from __future__ import annotations

import asyncio
import sqlite3
import threading
import time
import uuid

import httpx
import pytest
from fastapi.testclient import TestClient

from palimpsest.webapp import app as app_mod
from palimpsest.webapp import db, precompute, terminology_live, translate

# A note on WHY some tests below drive the app via httpx.AsyncClient +
# ASGITransport (a single event loop, `async with app.router.lifespan_context
# (app):`) instead of starlette.testclient.TestClient, unlike the rest of this
# file: a document create launches a background asyncio task
# (terminology_live.launch), and starlette.testclient.TestClient spins up a
# SEPARATE OS-thread "blocking portal" (its own private event loop) per
# TestClient instance. Two such portals racing on `db._lock` (one running the
# background task's _finish(), the other cloning golden for a second,
# freshly-instantiated TestClient) was empirically found to deadlock inside
# `sqlite3.Connection.backup()` -- confirmed test-harness-only (NOT
# reproducible through a single-event-loop httpx.AsyncClient driving the
# exact same ASGI app, i.e. not a real concern for the single-event-loop
# production server) via a bisection with faulthandler thread dumps during
# implementation. Using AsyncClient here sidesteps that harness artifact
# entirely while still exercising the real app + real middleware + real
# lifespan.


def _async_client(transport: httpx.ASGITransport) -> httpx.AsyncClient:
    """https:// base_url: the Set-Cookie carries `Secure` (spec requirement)
    -- httpx's own cookie jar only resends a Secure cookie over an https://
    origin, so a client needs it to keep ONE consistent session across
    several calls (a real browser over TLS, or over http://localhost
    specifically, doesn't have this restriction -- test-transport-only)."""
    return httpx.AsyncClient(transport=transport, base_url="https://testserver")


def _isolate(tmp_path, monkeypatch, *, startup_done: bool = True) -> None:
    """Reset every module-global session-routing bit of state to a fresh,
    isolated-per-test slate: a real (empty-schema-then-built) golden DB at a
    tmp path, no legacy `_conn`, no leftover golden/session caches."""
    db_path = tmp_path / "golden.db"
    monkeypatch.setattr(db, "DB_PATH", db_path)
    monkeypatch.setattr(db, "_conn", None)
    db.init_db(reset=True)                       # builds golden's schema via the legacy path
    monkeypatch.setattr(db, "_conn", None)        # ...then hand routing back to sessions
    monkeypatch.setattr(db, "_golden_conn", None)
    monkeypatch.setattr(db, "_golden_conn_path", None)
    monkeypatch.setattr(db, "_sessions", {})
    monkeypatch.setattr(db, "SESSIONS_DIR", tmp_path / "sessions")
    monkeypatch.setattr(db, "_startup_done", startup_done)


# ─────────────────────────── cookie ───────────────────────────

def test_middleware_sets_glossa_sid_cookie(client):
    """`client` (conftest.py) is legacy-mode (`db._conn` monkeypatched), but
    the ASGI middleware runs regardless of that — it doesn't consult
    db._conn at all, only db.py's connect()/current_lock() do."""
    resp = client.get("/api/health")
    assert app_mod.GLOSSA_SID_COOKIE in resp.cookies
    sid = resp.cookies[app_mod.GLOSSA_SID_COOKIE]
    uuid.UUID(sid)                                # well-formed uuid4


def test_middleware_reuses_a_wellformed_cookie_without_resetting_it():
    # NOT the shared `client` fixture: this test needs the cookie to actually
    # be RESENT across two calls by httpx's own jar, which — per the cookie
    # spec — only resends a `Secure` cookie over an `https://` origin; the
    # shared fixture's plain TestClient(app) defaults to `http://testserver`.
    from palimpsest.webapp.app import app
    https_client = TestClient(app, base_url="https://testserver")
    r1 = https_client.get("/api/health")
    sid1 = r1.cookies[app_mod.GLOSSA_SID_COOKIE]
    r2 = https_client.get("/api/health")
    # httpx's cookie jar resends sid1 automatically; a second Set-Cookie only
    # fires for a FRESH sid, so the jar's value must be unchanged.
    assert https_client.cookies[app_mod.GLOSSA_SID_COOKIE] == sid1
    assert r2.status_code == 200
    assert app_mod.GLOSSA_SID_COOKIE not in r2.cookies, "no 2nd Set-Cookie for an already-valid sid"


def test_non_api_path_gets_no_cookie(client):
    resp = client.get("/")
    assert app_mod.GLOSSA_SID_COOKIE not in resp.cookies


# ─────────────────────────── fail-loud without a sid ───────────────────────────

def test_connect_fails_loud_without_sid_after_startup(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch, startup_done=True)
    assert db.current_sid() is None
    with pytest.raises(RuntimeError):
        db.connect()


def test_current_lock_fails_loud_without_sid_after_startup(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch, startup_done=True)
    with pytest.raises(RuntimeError):
        db.current_lock()


def test_connect_uses_golden_before_startup_done(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch, startup_done=False)
    conn = db.connect()                            # no sid needed pre-startup
    assert conn.execute("SELECT 1").fetchone()[0] == 1


# ─────────────────────────── double-checked clone ───────────────────────────

def test_double_checked_clone_exactly_one_file_both_threads_get_a_conn(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch, startup_done=True)
    sid = str(uuid.uuid4())
    results: list[sqlite3.Connection] = []
    barrier = threading.Barrier(2)

    def worker():
        token = db._session_id.set(sid)
        try:
            barrier.wait(timeout=5)
            results.append(db.connect())
        finally:
            db._session_id.reset(token)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    assert len(results) == 2
    for conn in results:
        assert conn.execute("SELECT 1").fetchone()[0] == 1
    clone_files = list(db.SESSIONS_DIR.glob(f"{sid}.db"))
    assert len(clone_files) == 1, f"expected exactly one clone file, found {clone_files}"
    assert len(db._sessions) == 1


# ─────────────────────────── two sessions, isolated after a mutation ───────────────────────────

def _seed_one_document(conn: sqlite3.Connection) -> tuple[int, int]:
    ts = "2026-01-01T00:00:00+00:00"
    doc_id = conn.execute(
        "INSERT INTO document(title,source_lang,target_lang,source_model,version,origin,created_at,"
        "terms_status) VALUES('Seed','de','fr','seed',0,'seed',?,'done')", (ts,)).lastrowid
    pid = conn.execute(
        "INSERT INTO paragraph(document_id,idx,source,target,seed_target) VALUES(?,0,?,?,?)",
        (doc_id, "Quelle", "Cible", "Cible")).lastrowid
    conn.execute("INSERT INTO target_revision(paragraph_id,text,origin,created_at) VALUES(?,?,?,?)",
                 (pid, "Cible", "seed", ts))
    conn.commit()
    return doc_id, pid


def test_two_sessions_isolated_after_mutation_golden_unchanged(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch, startup_done=False)
    golden_conn = db.connect()
    doc_id, pid = _seed_one_document(golden_conn)
    db_path = db.DB_PATH

    from palimpsest.webapp.app import app
    # https:// base_url: the Set-Cookie carries `Secure` (spec requirement) —
    # httpx's own cookie jar only resends a Secure cookie over an https://
    # origin, so each client needs it to keep ONE consistent session across
    # its own several calls below (a real browser over TLS, or over
    # http://localhost specifically, doesn't have this restriction — this is
    # a test-transport-only accommodation, not a server-side relaxation).
    with TestClient(app, base_url="https://testserver") as client_a:
        client_b = TestClient(app, base_url="https://testserver")   # separate jar, SAME running app

        assert client_a.get(f"/api/documents/{doc_id}").json()["paragraphs"][0]["target"] == "Cible"
        assert client_b.get(f"/api/documents/{doc_id}").json()["paragraphs"][0]["target"] == "Cible"

        r = client_a.patch(f"/api/paragraphs/{pid}", json={"target": "Cible modifiee par A"})
        assert r.status_code == 200

        after_a = client_a.get(f"/api/documents/{doc_id}").json()["paragraphs"][0]["target"]
        after_b = client_b.get(f"/api/documents/{doc_id}").json()["paragraphs"][0]["target"]
        assert after_a == "Cible modifiee par A"
        assert after_b == "Cible", "session B must not see session A's mutation"

        # golden itself (criterion #2 of the spec) is untouched by either session's traffic
        direct = sqlite3.connect(str(db_path))
        golden_target = direct.execute(
            "SELECT target FROM paragraph WHERE id=?", (pid,)).fetchone()[0]
        assert golden_target == "Cible"
        direct.close()

    # two distinct session clone files were created
    clone_files = sorted(p.name for p in db.SESSIONS_DIR.glob("*.db"))
    assert len(clone_files) == 2


def test_document_created_in_session_a_is_absent_in_session_b(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch, startup_done=False)
    db.connect()                                    # build golden's schema/tables only

    from palimpsest.webapp.app import app
    body = {"title": "A-only doc", "sourceLang": "de", "targetLang": "fr",
            "precompute": False, "paragraphs": [{"source": "s", "target": "t"}]}

    async def scenario():
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with _async_client(transport) as client_a:
                r = await client_a.post("/api/documents", json=body)
                assert r.status_code == 201
                doc_id = r.json()["id"]

                assert (await client_a.get(f"/api/documents/{doc_id}")).status_code == 200

            async with _async_client(transport) as client_b:
                assert (await client_b.get(f"/api/documents/{doc_id}")).status_code == 404

    asyncio.run(scenario())


# ─────────────────────────── golden-token ───────────────────────────

def test_golden_token_routes_to_golden_and_is_visible_to_a_fresh_session(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch, startup_done=False)
    db.connect()
    monkeypatch.setenv("DEMO_ADMIN_TOKEN", "s3cr3t-test-token")

    from palimpsest.webapp.app import app
    body = {"title": "Golden doc", "sourceLang": "de", "targetLang": "fr",
            "precompute": False, "paragraphs": [{"source": "s", "target": "t"}]}

    async def scenario():
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with _async_client(transport) as client:
                r = await client.post("/api/documents", json=body,
                                       headers={"X-Golden-Session": "s3cr3t-test-token"})
                assert r.status_code == 201
                doc_id = r.json()["id"]
                assert app_mod.GLOSSA_SID_COOKIE not in r.cookies, \
                    "golden-token path must never Set-Cookie"

            # a brand new session (separate client, no cookie at all)
            async with _async_client(transport) as fresh:
                r2 = await fresh.get(f"/api/documents/{doc_id}")
                assert r2.status_code == 200, \
                    "golden-token write must land in golden, visible to any clone"

    asyncio.run(scenario())


def test_golden_token_ignored_when_env_unset(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch, startup_done=False)
    db.connect()
    monkeypatch.delenv("DEMO_ADMIN_TOKEN", raising=False)

    from palimpsest.webapp.app import app
    with TestClient(app) as client:
        r = client.get("/api/health", headers={"X-Golden-Session": "whatever"})
        assert app_mod.GLOSSA_SID_COOKIE in r.cookies, "no env token: header ignored, plain session"


# ─────────────────────────── wipe_sessions ───────────────────────────

def test_wipe_sessions_clears_files_including_wal_and_shm(tmp_path, monkeypatch):
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    (sessions_dir / "abc.db").write_bytes(b"x")
    (sessions_dir / "abc.db-wal").write_bytes(b"x")
    (sessions_dir / "abc.db-shm").write_bytes(b"x")
    monkeypatch.setattr(db, "SESSIONS_DIR", sessions_dir)
    monkeypatch.setattr(db, "_sessions", {})

    db.wipe_sessions()

    assert list(sessions_dir.glob("*")) == []
    assert db._sessions == {}


def test_wipe_sessions_is_a_noop_on_a_missing_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "SESSIONS_DIR", tmp_path / "does-not-exist")
    monkeypatch.setattr(db, "_sessions", {})
    db.wipe_sessions()                              # must not raise


# ─────────────────────────── TTL sweep ───────────────────────────

def test_ttl_sweep_removes_file_and_purges_all_seven_structures(tmp_path, monkeypatch):
    """The realistic "genuinely stale, no live task" shape: translate._tasks/
    _translating and precompute._tasks/terminology_live._tasks are ALREADY
    empty for this sid (a real background task always clears its own
    _tasks-done-callback and _translating on completion — see translate.py's
    run_translation finally/precompute.py's launch done_callback) — only the
    persistent "last known status" dicts and app._evaluating can realistically
    outlive a finished task. Purging _tasks/_translating themselves (the two
    structures ALSO used as the sweep's live-task signal) is covered
    separately below, as a direct unit test of _purge_session_state."""
    _isolate(tmp_path, monkeypatch, startup_done=True)
    sid = str(uuid.uuid4())
    token = db._session_id.set(sid)
    try:
        db.connect()                                # clones + caches the session
    finally:
        db._session_id.reset(token)

    assert sid in db._sessions
    db._sessions[sid].last_used = time.monotonic() - app_mod.SESSION_IDLE_TTL_S - 1

    doc_id = 7
    translate._status[(sid, doc_id)] = {"status": "done"}
    precompute._status[(sid, doc_id)] = {"status": "done"}
    app_mod._evaluating.add((sid, doc_id))

    closed = asyncio.run(app_mod._sweep_sessions_once())

    assert closed == 1
    assert sid not in db._sessions
    assert not any(db.SESSIONS_DIR.glob(f"{sid}.db*"))
    assert (sid, doc_id) not in translate._status
    assert (sid, doc_id) not in precompute._status
    assert (sid, doc_id) not in app_mod._evaluating


def test_purge_session_state_clears_tasks_and_translating_too(tmp_path, monkeypatch):
    """Direct unit test of _purge_session_state completeness — all SEVEN
    structures, including the two that also double as the sweep's live-task
    signal (translate._tasks/_translating), get their (sid, doc_id) key
    dropped."""
    sid = str(uuid.uuid4())
    doc_id = 11
    key = (sid, doc_id)
    translate._status[key] = {"status": "running"}
    translate._tasks[key] = object()
    translate._translating.add(key)
    precompute._status[key] = {"status": "running"}
    precompute._tasks[key] = object()
    terminology_live._tasks[key] = object()
    app_mod._evaluating.add(key)

    app_mod._purge_session_state(sid)

    assert key not in translate._status
    assert key not in translate._tasks
    assert key not in translate._translating
    assert key not in precompute._status
    assert key not in precompute._tasks
    assert key not in terminology_live._tasks
    assert key not in app_mod._evaluating


def test_ttl_sweep_spares_a_sid_with_a_live_task(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch, startup_done=True)
    sid = str(uuid.uuid4())
    token = db._session_id.set(sid)
    try:
        db.connect()
    finally:
        db._session_id.reset(token)

    db._sessions[sid].last_used = time.monotonic() - app_mod.SESSION_IDLE_TTL_S - 1
    doc_id = 9
    # a live task registered for this sid -- the sweep must skip it despite
    # being well past the idle TTL (spec: task-liveness beats last_used).
    # `_session_has_live_task` only checks dict-key membership, so a plain
    # sentinel object is enough to stand in for a real asyncio.Task here.
    translate._tasks[(sid, doc_id)] = object()

    try:
        closed = asyncio.run(app_mod._sweep_sessions_once())
        assert closed == 0
        assert sid in db._sessions
        assert list(db.SESSIONS_DIR.glob(f"{sid}.db"))
    finally:
        translate._tasks.pop((sid, doc_id), None)


def test_ttl_sweep_ignores_a_fresh_session(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch, startup_done=True)
    sid = str(uuid.uuid4())
    token = db._session_id.set(sid)
    try:
        db.connect()
    finally:
        db._session_id.reset(token)

    closed = asyncio.run(app_mod._sweep_sessions_once())
    assert closed == 0
    assert sid in db._sessions
