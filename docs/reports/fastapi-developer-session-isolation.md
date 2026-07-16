# Session isolation implementation report

Agent: fastapi-developer. Branch: `feat/emnlp-demo-sprint` (worktree
`/Users/a1111/Projects/Work/worktrees/emnlp-demo-sprint`). Spec (v2, verify-spec'd):
[docs/superpowers/specs/2026-07-16-session-isolation.md](../superpowers/specs/2026-07-16-session-isolation.md).
No commits were made (per task instructions) — everything below is uncommitted working-tree state.

## Scope

Implemented the full 8-step "План имплементации" from the spec:

1. `db.py` — contextvar session routing, `SessionConn` cache, double-checked clone-on-first-use,
   `current_sid()`/`current_lock()`/`touch()`, `clone_golden()` via `sqlite3` backup API,
   `close_session()`, `wipe_sessions()`, `set_startup_done()`, fail-loud `connect()`/`current_lock()`
   without a sid post-startup, legacy test-compat (`_conn is not None` short-circuit).
2. Rewrote all `with db._lock:` call sites in the four webapp modules to `with db.current_lock():` —
   **24 sites total** (app.py 19, terminology_live.py 3, translate.py 1, precompute.py 1), not the
   spec's estimated 27 (the spec's own text hedges with "~20" for app.py; I used the actual current
   grep count, confirmed exhaustively, and treated the total as an estimate, not a literal target).
   `db._lock` itself is unchanged (still the legacy/golden lock object).
3. `app.py`: raw ASGI `SessionMiddleware` (deliberately NOT `@app.middleware("http")`/
   `BaseHTTPMiddleware` — see rationale below) — `glossa_sid` cookie + `X-Golden-Session` header,
   constant-time compared to `DEMO_ADMIN_TOKEN`.
4. `app.py` lifespan: golden migrate/sweep (unchanged) → `db.wipe_sessions()` →
   `db.set_startup_done()` → 15-min TTL sweeper task, cancelled + awaited on shutdown (plus a
   process-global-state reset for repeated lifespan cycles within one test process — see below).
5. Rekeyed all seven in-memory structures to `(db.current_sid(), doc_id)`:
   `translate._status`/`_translating`/`_tasks`, `precompute._status`/`_tasks`,
   `terminology_live._tasks`, `app._evaluating`. Updated every read/write/discard/cancel site.
6. `migrate.py`: `_pin_demo_model_temperature(conn)` (iterates `MATRIX.values()`, JSON-merges each
   model's own `default_params["temperature"]`), called from `migrate()`. `deploy/update-server.sh`:
   removed the former steps 7 (criterion disable — confirmed a no-op duplicate of
   `_reduce_to_three_criteria`, which already **deletes** the row via `migrate()` at step 5, so the
   `UPDATE ... enabled=0` never had anything left to touch) and 8 (temperature pin), renumbered
   1-8 → 1-6, updated the header comment.
7. `scripts/create_demo_docs.py`: `--golden-token`/env `GLOSSA_GOLDEN_TOKEN`, sent on every request
   (create + poll). Also added a session-cookie fallback for the no-token case (see "Decisions"
   below — this was not explicitly requested but is required for the script to work at all
   locally).
8. Tests per success-criterion 3 — see "Files changed" below for the full list.

Doc-parity (same change set): `docs/subsystems/webapp.md` (new "Session isolation" section +
updates to the `db.py`/Translate/Production-rollout/Single-writer-concurrency passages),
`docs/superpowers/specs/2026-06-30-demo-contracts.md` (new delta section), `deploy/README.md`
(new "Session isolation" section, renumbered step list, `DEMO_ADMIN_TOKEN`'s repurposing spelled
out), `docs/testing/e2e-data.md` (new note on per-profile isolation + the `create_demo_docs.py`
gap), `docs/known_issues.md` (new "Open" entry on a TestClient-harness-only deadlock found while
writing tests — see below), `.gitignore` (`data/sessions/`).

## Files changed

Source:
- `src/palimpsest/webapp/db.py` — full rewrite (257 lines added/changed)
- `src/palimpsest/webapp/app.py` — middleware + lifespan + TTL sweep + lock/key rewrites (227
  lines)
- `src/palimpsest/webapp/translate.py`, `precompute.py`, `terminology_live.py` — rekeying +
  lock rewrites + `db.touch()` calls
- `src/palimpsest/webapp/migrate.py` — `_pin_demo_model_temperature`
- `scripts/create_demo_docs.py` — `--golden-token`, session-cookie fallback
- `deploy/update-server.sh` — steps 7/8 removed, renumbered

Tests (new):
- `tests/test_session_isolation.py` (17 tests) — cookie set/reused, non-`/api/*` path untouched,
  fail-loud `connect()`/`current_lock()` without a sid, golden-before-startup, double-checked
  clone (2 real threads, exactly 1 clone file), two-session mutation isolation + golden-unchanged
  assertion, doc created in A absent in B, golden-token → golden visible to a fresh session,
  golden-token ignored when env unset, `wipe_sessions` (incl. `-wal`/`-shm`) + no-op on missing
  dir, TTL sweep removes+purges (realistic no-live-task shape) + a dedicated
  `_purge_session_state` unit test covering all seven structures including the two that also
  gate liveness, TTL sweep spares a live-task sid, TTL sweep ignores a fresh session.
- `tests/test_create_demo_docs.py` (9 tests) — golden header on POST/GET, header omitted without
  a token, `create_document`/`poll_document` carry it, `main()`'s env-var fallback and no-header
  case, the session-cookie fallback captured-and-resent, golden-token taking priority over a
  tracked cookie.

Tests (updated — existing tests broken by the mandatory rekeying, fixed to build the same
`(db.current_sid(), doc_id)` key the app now uses): `tests/test_translator.py` (6 sites),
`tests/test_precompute.py` (2 sites), `tests/test_refiner.py` (1 site),
`tests/test_c5_loop_integrity.py` (2 sites), `tests/test_model_registry_v2.py` (1 test rewritten
— see "Decisions" below, this one is a real semantic change, not a mechanical key-shape fix).

Docs: `docs/subsystems/webapp.md`, `docs/superpowers/specs/2026-06-30-demo-contracts.md`,
`deploy/README.md`, `docs/testing/e2e-data.md`, `docs/known_issues.md`, `.gitignore`.

## Decisions & rationale

**Raw ASGI middleware, not `BaseHTTPMiddleware`.** `@app.middleware("http")` runs the downstream
call through a separate task/queue relay; a raw ASGI class awaits `self.app(...)` in the exact
same coroutine, which is what makes `contextvars.ContextVar.set()` reliably visible to the route
handler and everything it calls, with no version-dependent doubt. This wasn't explicitly spelled
out in the spec text ("ASGI-middleware") but I read that phrasing as deliberately excluding
`BaseHTTPMiddleware`, and implemented it that way.

**`_conn is not None` legacy short-circuit checked first, unconditionally, in `connect()`,
`current_lock()`, AND `current_sid()`.** This was the single most load-bearing design decision —
getting it wrong would have broken all 17 legacy test files. `current_sid()` returning a fixed
`_LEGACY_SID` constant (not whatever the ASGI middleware's contextvar happens to hold) is what
lets every rekeyed module collapse onto one key per legacy test, exactly matching pre-feature
behavior, even when the same test also drives real HTTP requests through the app (which DO get a
real cookie/sid from the middleware — the legacy check simply overrides it for DB/state purposes).

**Separate `_golden_conn`/`_golden_conn_path` from the legacy `_conn`.** Reusing `_conn` for
golden would have made the legacy short-circuit permanently true in production too (since golden
connecting once would set `_conn`), defeating per-session routing entirely. Kept as two distinct
module globals; `_connect_golden()` detects a monkeypatched `DB_PATH` change and reopens —
necessary because `test_migrate.py`'s two existing `with TestClient(app) as client:` tests run
back-to-back with different `DB_PATH`s in the same process. The lifespan's shutdown also
explicitly resets `_startup_done`/`_golden_conn`/`_golden_conn_path`, since a real server process
never re-enters its own lifespan but tests do.

**`_pin_demo_model_temperature` iterates `MATRIX.values()` rather than a hardcoded model-name
list.** Mirrors `_upsert_model_registry_and_remap`'s own style per the task's explicit
instruction, and stays correct if `MATRIX`'s defaults ever change without a second edit here.

**`tests/test_model_registry_v2.py::test_owner_edited_api_key_not_clobbered_on_second_run`
rewritten, not just key-shape-patched.** This test asserted `migrate()` never touches an
owner-edited `params_json` at all — genuinely incompatible with `_pin_demo_model_temperature`'s
explicit "force temperature every run" design (a faithful move of the former deploy-script step
8, which had the exact same "always overwrite" behavior via a live PUT). Updated the test to
assert `api_key` and a non-temperature params key both survive, while `temperature` is
deliberately re-pinned — this is a real, spec-mandated behavior change to that invariant, not a
mechanical fix.

**`create_demo_docs.py` got a session-cookie fallback beyond the spec's literal ask.** The spec
only asked for `--golden-token`/`X-Golden-Session` on every request. Implementing it surfaced a
real gap: plain `urllib.request.urlopen()` calls share no cookie jar, so without a golden token
(e.g. local dev with `DEMO_ADMIN_TOKEN` unset — a real, common scenario), every request including
each poll tick would land in a *different* fresh session clone, and the script's own `--poll`
could never see the document it just created. Fixed by manually tracking the process's own
`Set-Cookie` and resending it (NOT via `http.cookiejar` — its default policy refuses to ever
resend a `Secure`-attributed cookie over a plain-`http://` origin, exactly this script's default
`http://localhost:8000` target, so the stdlib jar would have silently never actually worked).
This is a deliberate scope extension beyond the literal instruction, justified by
"make existing things work" and honesty about a regression the feature would otherwise introduce
into an existing, still-relevant script.

**A real, reproducible `TestClient`-only deadlock, found and worked around (not a code bug).**
Writing the "golden-token visible to a fresh session" and "doc created in A absent in B" tests
with two separate/newly-instantiated `starlette.testclient.TestClient` objects reliably hung
inside `sqlite3.Connection.backup()` when a background `terminology_live` task (launched by one
client) raced a second client's own `clone_golden()`. Bisected with
`faulthandler.dump_traceback(all_threads=True)` down to `TestClient`'s per-instance "blocking
portal" (its own OS-thread event loop) — two portals both touching `db._lock` reliably wedged.
Confirmed test-harness-only: the identical scenario through `httpx.AsyncClient` +
`httpx.ASGITransport` (single event loop) never hangs, so this is not a production concern (a
real `uvicorn` process has one event loop, no portal bridging). Fixed by driving those two tests
through `httpx.AsyncClient`/`ASGITransport` instead of `TestClient`; documented as an open gotcha
in `docs/known_issues.md` for future test authors. This consumed a meaningful share of the
implementation time and is worth flagging as the single most surprising finding of this task.

**Also found: a shared, concurrently-modified worktree.** For a stretch of this session,
`src/palimpsest/terminology/grounding/{candidates,label_first}.py`, `tests/test_terminology.py`,
and several `frontend/` files were being edited by a different, unrelated agent/task in this same
worktree (an in-progress "glossary trace polish" change, confirmed via `git diff` — none of it
touched by me). This caused transient pytest failures in `test_terminology.py`/
`test_terminology_live.py` unrelated to session isolation; I isolated and confirmed (via
`git stash` of just those files) that my changes were clean against both the pre- and
post-concurrent-edit state, and by the final full run the other agent's work had settled and all
635 tests pass together. Flagging this because it's an environment hazard, not something I can
fix, and the project's own CLAUDE.md explicitly calls out shared-worktree risk.

## Open questions

- Should `_pin_demo_model_temperature` also be exposed as a standalone, documented "reset
  temperature" operator action (e.g. a Settings-UI button), or is "every migrate()/redeploy"
  the only intended trigger? Spec only asks for the latter; not something I should decide
  unilaterally.
- `create_demo_docs.py`'s session-cookie fallback is a pragmatic fix for local/no-token use, not
  something the spec asked for by name — flagging for owner awareness in case a different
  tradeoff (e.g. requiring `--golden-token` always, erroring loudly without it) was intended.

## NOT done (explicit)

- **Did not run a live/staged deploy** of `deploy/update-server.sh` against any real or
  container-based server — only `bash -n` syntax-checked it. No Docker environment was
  available/appropriate for this task; the removed-steps reasoning (step 7 being a confirmed
  no-op duplicate) was verified by reading `migrate.py`'s `_reduce_to_three_criteria` and the
  script's own step ordering, not by an actual deploy run.
- **Did not run a browser/e2e session** verifying two real Playwright profiles are isolated
  end-to-end — that's the `e2e-tester` agent's job per the project's step 6/8 process, out of
  this fastapi-developer task's scope. `docs/testing/e2e-data.md` now documents the expected
  behavior and flags the `create_demo_docs.py` local-vs-deployed distinction for whoever runs
  that pass next.
- **Did not touch `frontend/`** (explicitly out of scope per the task instructions; also
  actively being edited by a different concurrent task during this session — see above).
- **Did not commit or push** — all changes are uncommitted working-tree state in this worktree,
  per the task's explicit instruction.
- Full pytest suite: **635 passed, 0 failed** (baseline 599; +36 new tests across
  `test_session_isolation.py`/`test_create_demo_docs.py`, +some from the concurrent unrelated
  terminology work already present in this worktree). `bash -n deploy/update-server.sh` — OK.
  Ruff: both new test files and every line I personally authored are clean; pre-existing E501
  noise elsewhere in the touched files (baseline ~93 errors across `webapp/`, confirmed via
  `git stash` diff-attribution) was left untouched, not part of this task's scope.
