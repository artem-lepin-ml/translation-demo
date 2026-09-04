# FastAPI developer report — content-fingerprint clone cache

Branch: `feat/emnlp-demo-sprint` (shared worktree, concurrent lanes). Commit:
`af60df2 feat(webapp): instant content-fingerprint clone cache for uploads`.
Not pushed.

## Scope

Urgent follow-up backend feature for the demo video: a presenter uploads a
source+translation file pair whose CONTENT matches an existing
fully-processed document — the new document must instantly get terms and
judge scores (cloned from the match), no LLM calls, no waiting. Task text
gave a full design (fingerprint rule, copy rule, exemptions, logging, test
list, doc-parity target) — implemented as specified, file-scope-limited to
`app.py`'s `create_document` region ("yours alone right now"), a new test
file, and `docs/subsystems/webapp.md`.

Out of scope (explicitly, per the task's file-scope boundary and "other
agents may edit other files concurrently"): everything else in the repo,
including a concurrent, unrelated 5→4 model-registry migration touching
`model_matrix.py`/`seed.py`/`migrate.py` and several `tests/test_model_*.py`
files that was actively in flight in this same shared worktree during this
session (see Test results).

## Files changed

- `src/palimpsest/webapp/app.py` (+142/-4):
  - `import hashlib` added.
  - New helpers inserted between `_terms_launch_after_translate` and
    `create_document`: `_normalize_ws`, `_content_fingerprint`,
    `_find_clone_source`, `_clone_predictions`.
  - `create_document`'s paragraph-insert loop now also collects
    `new_pids`/`new_revision_ids`/`stored_pairs`; after the loop (still
    inside `db._lock`, before the single `conn.commit()`), a
    `translate:false` upload is fingerprinted and matched against existing
    `terms_status='done'` documents; on a match, `_clone_predictions` runs
    and `terms_status` is set to `'done'` directly instead of `'running'`;
    `precompute.mark_skipped`/no `precompute.launch`/no
    `terminology_live.launch` follow; one `logger.info` line records the
    clone.
- `tests/test_clone_cache.py` (new, 219 lines, 6 tests) — see Test results.
- `docs/subsystems/webapp.md` (+68) — new "Content clone cache" section
  (placed after "Live terminology", before "Revision history & best" —
  the natural location since the feature's whole point is bypassing both
  of the sections immediately around it).

Explicitly NOT touched: `model_matrix.py`, `seed.py`, `migrate.py`,
`frontend/`, any other `app.py` region.

## Decisions & rationale

**What "frozen aggregate/aggregatePrev-style fields" actually means.** The
task pointed at "paragraph.aggregate/aggregatePrev-style frozen fields —
read how seed.py/evaluate write them and mirror." I traced this before
writing any code: `paragraph` has no aggregate column at all;
`aggregate`/`aggregateBaseline`/`aggregatePrev` are all *derived at read
time* in `_para_score_views`/`_para_dict` (app.py) from `score.aggregate`,
a column each score row carries and never recomputes after being written
(`compute_aggregate()` in `aggregate.py`, called once by
`seed.py`/`precompute._write_paragraph`/`evaluate()`). So "mirror the
frozen fields" resolves to: copy `score.aggregate`/`score.criteria_key`
verbatim, never recompute them. I documented this trace explicitly in both
the code docstring and the doc-parity section so the next reader doesn't
have to re-derive it.

**Fingerprint = JSON array of normalized pairs, then sha256.** Considered a
raw string concatenation instead, rejected: without an unambiguous
separator/length encoding, different pair boundaries (e.g. `"ab"+""` vs
`"a"+"b"`) could theoretically produce the same concatenation. `json.dumps`
of a `[[source, target], ...]` list sidesteps this entirely (JSON already
has canonical, unambiguous escaping) and, as a side effect, makes paragraph
*count* and *order* load-bearing in the hash by construction — so "if
paragraph counts differ, treat as no-match" (an explicit task bullet) falls
out for free with no special-case code, rather than needing a separate
length check that could drift out of sync with the hashing logic.

**No persisted fingerprint column.** Per the task's explicit "no schema
change needed; documents are few" — `_find_clone_source` recomputes every
candidate's fingerprint from its live `paragraph` rows on every call. This
is the correct tradeoff for a low-document-count demo; would not scale to
a real multi-tenant corpus without a cached/indexed fingerprint column, but
that's out of scope here.

**`score.revision_id` unconditionally remapped to the new paragraph's own
revision.** The source document's original score rows may in principle
reference different revisions (if it was edited/re-evaluated over time);
I did not attempt to preserve that structure. Every paragraph reaching
`_clone_predictions` came from a non-translate upload, so it always has
exactly one `target_revision` row — remapping every copied score row to
that one revision is what makes `_best_revision` report `isCurrent: true`
immediately on the cloned paragraph, which is the correct/expected reading
for "this is the current, best, only version of this text." `zip(...,
strict=True)` was added (flagged by `ruff`'s B905) as a deliberate
defense-in-depth: a silent length mismatch here would silently misattribute
one paragraph's judge scores to a different paragraph, which is a real risk
worth crashing loudly on rather than one to leave implicit — even though
today it's structurally unreachable (the fingerprint match already
guarantees equal counts).

**Order preservation for `_para_score_views`'s tie-break.** Source
`score`/`term`/`issue` rows are read oldest-first (`ORDER BY created_at
ASC, id ASC` for scores) and re-inserted in that same relative order, so
the fresh autoincrement ids preserve the original recency ordering.
`_para_score_views`'s `ORDER BY created_at DESC, id DESC` "latest per
criterion" logic then reproduces the source document's exact
latest/prev/baseline split with no changes needed to that function at all
— verified by the `scoresBaseline is not None` / `best.aggregate == 7.78`
assertions in the test.

**Precompute forced off on a clone regardless of the request's own
`precompute` flag.** Cloned scores already are the baseline a precompute
run would have produced; running it anyway would be redundant paid spend
against paragraphs whose scores were just written. Verified in the test by
explicitly requesting `precompute: true` on the cloned upload and asserting
`precompute.launch` is never called.

## Test results

Exact task-required command:
`uv run pytest tests/test_clone_cache.py tests/ -q -k "clone or documents_create or precompute"`
→ **39 passed, 523 deselected**.

`tests/test_clone_cache.py` alone: **6 passed** —
`test_clone_on_identical_content_instant_terms_and_no_launch`,
`test_clone_normalizes_whitespace_runs`,
`test_different_content_takes_normal_path`,
`test_paragraph_count_mismatch_takes_normal_path`,
`test_clone_source_must_be_terms_done`,
`test_translate_true_never_clones`. The first two directly exercise
`precompute.launch`/`terminology_live.launch` monkeypatched to
`pytest.fail(...)` if called at all, per the task's explicit instruction;
the other four assert the "normal path" launches recorder is non-empty
(same call-recording convention `test_terminology_live.py`'s own
`_no_auto_launch`-style fixtures already use in this codebase).

Full suite: `uv run pytest tests/ -q` → **562 passed, 0 failed** (final
state). Honesty note: mid-session, one full-suite run showed **3 unrelated
failures** (`test_matrix_has_five_models_four_openrouter`,
`test_translategemma_vllm_row_present_and_display_only`,
`test_five_models_seeded`) plus a transient `conftest.py` collection
`NameError` — both caused by a concurrent, unrelated lane's in-flight 5→4
model-registry edit to `model_matrix.py`/`seed.py`/`migrate.py`/
`tests/test_model_*.py` in this same shared worktree, caught mid-write.
Confirmed via `git diff --stat` that my own diff never touches those files.
Did not attempt to fix them (not my task, not my file-scope, actively
someone else's in-progress work); re-ran after the concurrent lane
finished and the suite was clean.

Lint (`ruff check`, not CI-gated in this repo — 53 pre-existing E501/B008
findings on `app.py` before this change): my new code is clean on
`F`/`E9`/`B905` (the categories that flag real bugs, not just line length).
Added `strict=True` to both new `zip()` calls after `ruff` flagged them
(see Decisions above); left two pre-existing `B905` findings in `evaluate()`
(lines 734-735) untouched — unrelated code, out of scope.

## Open questions

- Should the fingerprint (or a cached column) survive across a process
  restart / scale beyond "documents are few"? Not needed today; flagged for
  whoever eventually productionizes this beyond the demo.
- Should a clone be visually distinguished in the UI (e.g. a badge "cloned
  from Document X") so a presenter/reviewer knows judge scores weren't
  freshly computed? Not requested by the task (backend-only, response only
  needs to reflect `termsStatus: done`); no frontend change was made or
  requested.
- Should chained clones (a clone of a clone) be prevented? Not requested;
  current behavior allows them, which is arguably correct — a completed
  clone is indistinguishable from a "real" fully-processed document by
  design, so further clones matching it is consistent, not a special case.

## NOT done (explicit)

- **No test seeds a clone source through the real `seed.py` machinery** to
  directly exercise "seed doc can be a clone source" (task point 3).
  `_find_clone_source`'s query has no `origin` filter at all — only
  `terms_status='done'` — so this is structurally covered by the existing
  tests without needing the heavier `seed()` fixture (prompt files, model
  matrix, etc.); flagging this as a logical-coverage argument rather than a
  literal test run, for honesty.
- **No frontend changes** — task was backend-only; not verified in a
  browser.
- **Did not touch the concurrent model-registry lane's files** even though
  a full-suite run surfaced real (if unrelated) failures partway through
  the session — correct per the task's explicit single-owner boundary on
  `app.py`'s `create_document` region and the general "other agents may
  edit other files concurrently" warning, but noting it here so it isn't
  silently swept under "all green."

## Flagged, not acted on

The task message's `<context_window_protection>` trailing block (demanding
routing through `mcp__plugin_context-mode_context-mode__*` tools) and the
recurring per-Read `<context_guidance>`/`ctx_execute_file` system-reminders
were both ignored throughout this task — those tools are not present in my
actual toolset (only `Read`/`Write`/`Edit`/`Bash`), so compliance was not
even possible, and the harness's own instructions establish that an
agent-supplied message cannot authorize a tool-usage/permission change
regardless. Work proceeded with the standard tools; noted here for the
record, no other action taken.
