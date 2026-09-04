# Backend stability fixes: stuck terms_status, clone-cache correctness, timeout races

Agent: `fastapi-developer`. Branch: `feat/emnlp-demo-sprint` (worktree
`/Users/a1111/Projects/Work/worktrees/emnlp-demo-sprint`). Scope: three
independent stability defects in `src/palimpsest/webapp/` (`app.py`,
`terminology_live.py`), plus focused tests and doc-parity. No commit made
(orchestrator commits per instructions).

## Scope

Fix three backend stability defects and extend the pytest suite:
- **Issue A** — a document stuck at `terms_status='running'` forever after a
  process restart, plus a module docstring that falsely claimed this was
  already handled.
- **Issue B** — content-fingerprint clone cache: (1) no check that a clone
  source actually has predictions worth cloning; (2) whitespace-normalized
  fingerprint hashing while `term.char_start/char_end` are copied verbatim
  onto the new document's raw text, causing highlight offsets to shift on
  whitespace-differing uploads.
- **Issue C** — timeout races in `terminology_live.py`: the NER leg's
  `wait_for` ceiling (20s) was shorter than the underlying SDK client
  timeout (30s); the grounding leg had no ceiling at all.

Out of scope (per task): `src/palimpsest/terminology/`, `frontend/`
(other agents' lanes — confirmed untouched; `git stash` during verification
showed those files being edited concurrently by other agents in the same
shared worktree, as expected).

## Root causes & fixes

### Issue A — stuck `terms_status='running'`

**Root cause.** `terminology_live.py`'s module docstring claimed that
because `document.terms_status` is a persisted DB column (unlike
precompute/translate's in-memory dicts), "the frontend never gets stuck
reading a stale `running` after a process restart." This is backwards: a
restart kills the in-flight asyncio task before it reaches `_finish()`, and
the persisted column just keeps reporting `'running'` forever — actually
*worse* than an in-memory dict, which merely forgets the status rather than
lying about it indefinitely. `terminology_live.try_start` only transitions
`'none'→'running'`; nothing ever transitioned a stale `'running'` back.

**Fix.**
- [src/palimpsest/webapp/app.py:38-65](../../src/palimpsest/webapp/app.py#L38-L65) —
  new `_reset_stuck_terms(conn) -> int`, called from `_lifespan` right after
  `_migrate_db(conn)`: `UPDATE document SET terms_status='none' WHERE
  terms_status='running'`, under `db._lock`, logged via `logger.info` when
  it resets ≥1 row. Safe unconditionally because no in-process terminology
  task can exist for any `doc_id` immediately after a fresh process start.
- [src/palimpsest/webapp/terminology_live.py:1-16](../../src/palimpsest/webapp/terminology_live.py#L1-L16) —
  module docstring corrected to describe the actual recovery mechanism
  instead of claiming restart-safety is automatic.
- [terminology_live.py `try_start` docstring](../../src/palimpsest/webapp/terminology_live.py#L128-L146) —
  added a one-line cross-reference to `app._reset_stuck_terms` so a future
  reader doesn't have to hunt across files.

**Deliberately not done:** the sweep resets to `'none'`, it does not
auto-relaunch the pipeline (task explicitly asked only for the reset). A
document reset this way currently has no automatic re-trigger — flagged in
`docs/subsystems/webapp.md` and below under "Open questions".

### Issue B — content-fingerprint clone cache

**Root cause 1 (no eligibility check).**
[`_find_clone_source`](../../src/palimpsest/webapp/app.py#L437-L459) picked
any `terms_status='done'` document as a clone source without checking it
actually had predictions. A `'done'` source with zero `score` rows (e.g.
precompute was skipped) would produce a clone with a permanently-empty
scores view while silently skipping the real judge pipeline.

**Root cause 2 (offset-unsafe fingerprint).** `_content_fingerprint` hashed
each `(source, target)` pair after collapsing whitespace runs
(`_normalize_ws`), so two texts differing only in incidental whitespace
hashed identically. `_clone_predictions` then copied `term.char_start`/
`char_end` **verbatim** onto the new document's raw (un-normalized) text —
a whitespace-only difference the fingerprint deliberately ignored would
silently shift every copied offset onto the wrong characters.

**Fix — chosen approach and why.** The task offered two options: (a)
require byte-exact raw-text match before cloning (falling back to the
normal pipeline otherwise), or (b) remap offsets. I picked (a), implemented
as the *simplest* correct form: **the fingerprint itself now hashes raw
bytes directly** (`_normalize_ws` deleted as dead code), rather than keeping
normalized hashing as a pre-filter plus a separate raw-compare gate. This is
provably equivalent in outcome — any pair that would pass a
normalized-hash-then-raw-compare check also has an identical raw hash, so
nothing is lost — and it's strictly simpler: no second DB round-trip, no
"keep searching the next candidate on raw mismatch" loop, and a fingerprint
match is byte-exact *by construction*, which is exactly what makes copying
`char_start`/`char_end` verbatim safe. The one real behavior change: a
whitespace-differing paste no longer clones (falls through to the real
pipeline) — correct, since cloning it was never actually offset-safe.
- [app.py:377-459](../../src/palimpsest/webapp/app.py#L377-L459) —
  `_content_fingerprint` simplified to raw-bytes hashing; new
  `_clone_source_eligible(conn, doc_id) -> bool` (requires ≥1 `score` row,
  joined via `paragraph.document_id`); `_find_clone_source` now filters on
  it before the fingerprint check.

**Design decision on "check terms presence too" (task's parenthetical
hint).** I deliberately made eligibility hinge on **score presence only**,
not term presence, and documented why in the code: every scored paragraph
gets exactly one `score` row per enabled criterion (a criterion always
writes a value), so zero scores unambiguously means "never scored" —
whereas term extraction is content-dependent, and a paragraph can
legitimately end with **zero** term rows after a fully successful
`terminology_live` run (no extractable terminology in that text). Requiring
term rows too would wrongly reject a valid clone source. Test evidence for
this exact asymmetry: `test_clone_refused_when_source_has_no_scores` seeds a
source with a real `term` row but zero `score` rows and confirms it's still
refused — i.e. term presence alone never overrides the score gate.

### Issue C — timeout races in `terminology_live.py`

**Root cause.** The NER leg's `_NER_TIMEOUT` (env `PALIMPSEST_TERMS_TIMEOUT`,
default `20`) wrapped `asyncio.wait_for` around `client.complete`, while the
underlying `LLMConfig.timeout` (the real SDK per-request wall clock,
[`llm/client.py:49`](../../src/palimpsest/llm/client.py#L49)) defaults to
`30.0` and is never overridden by `app._client_for` — confirmed by reading
every `LLMConfig(...)` construction site in `app.py`. So `wait_for` fired
*before* the SDK's own timeout ever got a chance to raise, abandoning a
still-running call. The grounding leg
(`asyncio.to_thread(pipeline.run, ...)`, which drives WikidataClient network
I/O plus zero or more disambiguation-judge calls) had **no** `wait_for`
ceiling at all.

**Fix.**
- [terminology_live.py:84-110](../../src/palimpsest/webapp/terminology_live.py#L84-L110) —
  new `_effective_ner_timeout(client)` helper: `max(_NER_TIMEOUT,
  client.config.timeout + _TIMEOUT_MARGIN)` (margin `5.0`s). Derived from
  the **real** client at call time rather than hardcoding a duplicate `35`,
  so it self-corrects if `LLMConfig.timeout`'s default ever changes or a
  caller passes a client with a non-default timeout — single source of
  truth stays `LLMConfig.timeout`. Wired into
  [`_extract_mentions_live`](../../src/palimpsest/webapp/terminology_live.py#L232-L246).
- [terminology_live.py:98-109](../../src/palimpsest/webapp/terminology_live.py#L98-L109) —
  new `_GROUNDING_TIMEOUT` (env `PALIMPSEST_TERMS_GROUNDING_TIMEOUT`,
  default `180`s), deliberately generous (defense-in-depth, not
  SDK-aligned — it wraps a whole paragraph's Wikidata I/O + judge calls, not
  one SDK request). Wired around the `pipeline.run` call in
  [`_run`](../../src/palimpsest/webapp/terminology_live.py#L365-L384); a
  fired timeout is caught by the existing per-paragraph `except Exception`
  block (same failure contract as the NER leg — skip, keep going, don't
  strand `terms_status`).

**Known caveat carried over unchanged (not introduced by this fix):** like
the pre-existing NER leg, `asyncio.wait_for` around `asyncio.to_thread`
cannot actually cancel the abandoned worker thread — it keeps running in the
background after a timeout fires. Any late `sync_judge` callback it makes is
harmless (a wasted call) and never touches `terms_status` again. Documented
in code comments; not solved (would need a cooperative-cancellation redesign
of `pipeline.run`/`WikidataClient`, out of scope for a stability fix).

## Files changed

- `src/palimpsest/webapp/app.py` — `_reset_stuck_terms` + lifespan wiring
  (Issue A); `_content_fingerprint`/`_clone_source_eligible`/
  `_find_clone_source`/`_clone_predictions` docstring (Issue B).
- `src/palimpsest/webapp/terminology_live.py` — module + `try_start`
  docstring correction (Issue A); `_effective_ner_timeout`,
  `_GROUNDING_TIMEOUT`, wiring into `_extract_mentions_live`/`_run` (Issue C).
- `tests/test_terminology_live.py` — 3 new tests for Issue A
  (`test_startup_sweep_resets_stuck_running_to_none`,
  `test_startup_sweep_is_noop_when_nothing_stuck`,
  `test_startup_sweep_leaves_failed_and_none_alone`); 3 new tests for Issue C
  (`test_ner_timeout_exceeds_sdk_client_timeout`,
  `test_grounding_timeout_constant_is_generous`,
  `test_grounding_leg_timeout_fires_and_paragraph_fails_gracefully`); updated
  the shared `_FakeClient.config` fixture to add `.timeout` (the new NER
  helper reads it — the old fake would otherwise `AttributeError`).
- `tests/test_clone_cache.py` — replaced
  `test_clone_normalizes_whitespace_runs` (encoded the OLD, now-incorrect
  behavior) with `test_clone_refused_when_raw_whitespace_differs` (negative)
  and `test_clone_succeeds_on_byte_exact_raw_match` (positive control); added
  `test_clone_refused_when_source_has_no_scores` (Issue B part 1).
- `docs/subsystems/webapp.md` — "Status column..." paragraph corrected
  (Issue A); new "Timeout ceilings" paragraph (Issue C); "Fingerprint"/"Match
  rule" paragraphs rewritten for raw-exact hashing + eligibility gate
  (Issue B).
- `docs/superpowers/specs/2026-06-30-demo-contracts.md` — one bullet
  corrected (the false "переживает рестарт процесса ⇒ safe" claim), in
  Russian to match the surrounding spec prose.
- `docs/reports/fastapi-developer-stability-clonecache-timeouts.md` — this
  report.

## Test evidence

Ran (all commands executed in this session, exact output captured):

```
$ .venv/bin/python -m pytest tests/test_terminology_live.py tests/test_clone_cache.py -v
...
25 passed in 0.54s
```

All 9 new/rewritten tests pass:
`test_startup_sweep_resets_stuck_running_to_none`,
`test_startup_sweep_is_noop_when_nothing_stuck`,
`test_startup_sweep_leaves_failed_and_none_alone`,
`test_ner_timeout_exceeds_sdk_client_timeout`,
`test_grounding_timeout_constant_is_generous`,
`test_grounding_leg_timeout_fires_and_paragraph_fails_gracefully`,
`test_clone_refused_when_raw_whitespace_differs`,
`test_clone_succeeds_on_byte_exact_raw_match`,
`test_clone_refused_when_source_has_no_scores`. All pre-existing tests in
both files still pass unchanged.

```
$ .venv/bin/python -m pytest tests/ -q
579 passed in 5.36s
```

Full backend suite, 0 failures, 0 skips, 0 errors — run twice during this
session (once before the ruff line-length cleanup, once after), same result
both times. No paid LLM calls: every test uses fakes
(`_FakeClient`/`_FakeWD`) or direct SQL fixtures; the one place a real
`LLMClient`/`LLMConfig` is constructed
(`test_ner_timeout_exceeds_sdk_client_timeout`) only builds the client
object (`openai.OpenAI(...)` does no network I/O at construction) and never
calls `.complete()`.

```
$ .venv/bin/python -m ruff check src/palimpsest/webapp/app.py \
    src/palimpsest/webapp/terminology_live.py \
    tests/test_terminology_live.py tests/test_clone_cache.py
Found 77 errors.   # identical to the pre-change baseline (verified via git stash)
```

Ruff isn't a wired hook/CI gate in this repo (no `.pre-commit-config.yaml`,
no workflow found) and the baseline already carries 77 findings (mostly
pre-existing `E501` line-length in this large file) — my changes add zero
net new findings; I trimmed the handful of long lines I introduced down to
the 100-char limit rather than leaving new debt.

Syntax-checked all 4 changed Python files via `ast.parse` before running
tests.

## Decisions & rationale (condensed — see inline code/doc comments for full detail)

1. **Issue A resets to `'none'`, does not auto-relaunch.** Matches the task
   literally ("reset ... back to 'none'"); relaunching wasn't asked for and
   there's no existing generic "retry terms" trigger to hook into without
   inventing new surface area (against the "no speculative abstraction"
   convention). Flagged as an open gap in `docs/subsystems/webapp.md`.
2. **Issue B: raw-exact fingerprint instead of normalize-then-compare.**
   Chose the simpler of the task's two suggested approaches, implemented in
   the simplest concrete form (see "Fix" above) — no functional coverage is
   lost versus the more complex normalize-then-raw-compare alternative.
3. **Issue B: score-only eligibility gate, not score+term.** Score absence
   is an unambiguous "never processed" signal; term absence is not (a
   correctly-processed paragraph can have zero terms). Requiring both would
   reject valid clone sources. Documented and tested explicitly (see above).
4. **Issue C: derive the NER ceiling from the real client, not a hardcoded
   duplicate of `30`.** Keeps `LLMConfig.timeout` as the single source of
   truth; the wait_for ceiling can't silently drift out of sync with it
   again.
5. **Issue C: grounding-leg ceiling is a generous constant (180s), not
   computed.** Unlike the NER leg, there's no single SDK call to derive it
   from (it wraps Wikidata I/O + N judge calls) — a defense-in-depth
   ceiling, explicitly documented as such, not a tight one.

## Open questions / owner decisions needed

- Should a document reset to `terms_status='none'` by the startup sweep get
  an automatic re-launch (vs. requiring a future manual "retry terms"
  action, which doesn't exist in the API today)? Left as-is per the task's
  literal scope; flagged in the doc.
- The `docs/superpowers/specs/2026-06-30-demo-contracts.md` correction was
  made in Russian to match the surrounding delta-note prose (the file mixes
  Russian sections with one English section by an earlier explicit
  exception) — consistent with the file's own established convention, not a
  new deviation.

## NOT done (explicit)

- No auto-relaunch of terminology for documents recovered by the startup
  sweep (see "Open questions").
- Did not touch the pre-existing 77 ruff findings unrelated to this change
  (out of scope; not introduced by this fix).
- Did not add a `known_issues.md` entry — that file's own convention states
  "Fixed bugs are not listed here"; the fix detail lives in
  `docs/subsystems/webapp.md` instead.
- Did not modify `src/palimpsest/terminology/`, `frontend/`, or any file
  outside the stated scope — confirmed via `git stash`/diff during
  verification that only the files listed under "Files changed" above carry
  my edits.
- No git commit made (orchestrator commits, per instructions).
