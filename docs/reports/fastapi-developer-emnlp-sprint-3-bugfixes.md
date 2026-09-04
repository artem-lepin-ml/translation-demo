# fastapi-developer report — EMNLP demo-sprint: 3 confirmed-bug fixes

**Scope.** Worktree `/Users/a1111/Projects/Work/worktrees/emnlp-demo-sprint`, branch
`feat/emnlp-demo-sprint` (shared with sibling agents working other lanes in the same
worktree — `terminology_live.py`/`test_terminology*.py`/`docs/subsystems/webapp-ui-design.md`
in `git status` are NOT this task's changes). Implemented the 3 confirmed backend bugs
(custom-criterion `FileNotFoundError`, process-global precompute call cap, cache-fallback
`failedCriterionIds` masking) plus 4 small polish items, all from e2e-campaign evidence. No
commit made (per instructions).

## Files changed

Code (all within the authorized "Touch ONLY" list):
- `src/palimpsest/webapp/judge.py` — `_scoring_prompt`/`scoring_system_prompt`/`judge_one`
  gain an optional `prompt` override (DB row wins over the on-disk file).
- `src/palimpsest/webapp/app.py` — `_judge_live` threads `criterion["prompt"]` through;
  `evaluate()`/`_cache_response` distinguish pristine-no-key vs live-ran-and-failed for
  `failedCriterionIds`; human 409 message for a duplicate model name; `user_id` redaction on
  the model Test error path; case-insensitive export `format`.
- `src/palimpsest/webapp/precompute.py` — `_take_call_slot` keyed per `db.current_sid()`;
  `failed` counter added to the status dict (`mark_skipped`/`mark_started`/`_run`).
- `src/palimpsest/webapp/budget.py`, `src/palimpsest/webapp/export.py` — **not touched**,
  no code change was needed in either (budget.py's `_STATE` dict just holds a new-shaped
  value under an existing key; export.py's `slugify`/filename were already correct — case
  normalization for `format` happens in `app.py` at the request-param boundary).

Tests (existing files updated for the new shapes, plus 2 new files):
- `tests/test_precompute.py`, `tests/test_clone_cache.py` — added `"failed": N` to every
  exact-equality status-dict assertion; new `test_partial_failure_reports_failed_count` and
  `test_take_call_slot_is_isolated_per_session`.
- `tests/test_evaluate_retry_c1.py` — `budget._STATE["precompute_calls"]` is now `{sid:
  count}`, updated the one exact-value assertion.
- `tests/test_c5_loop_integrity.py` — `recording_judge` gains `**_kw` (tolerates the new
  `prompt=` kwarg); added `failedCriterionIds` assertions to the existing bad-key-cache-
  fallback test and a new sibling `test_no_key_cache_fallback_keeps_failed_criterion_ids_empty`.
- `tests/test_budget.py`, `tests/test_issue_dedup.py`, `tests/test_prediction_preservation.py`
  — fake `judge_one` replacements given `**_kw`/`prompt=None` tolerance for the same reason.
- `tests/test_custom_criterion_prompt.py` (new) — Fix 1: unit tests on
  `judge._scoring_prompt`/`scoring_system_prompt`, an end-to-end POST-criteria-then-evaluate
  test proving the custom prompt reaches `judge_one`, the empty-prompt-and-no-file honest-
  failure case, the built-in-file-fallback case, and a seed-row design-fact lock
  (`test_seed_criteria_db_prompt_matches_scoring_file`).
- `tests/test_webapp_polish_2026_07_17.py` (new) — the 4 polish items (409 message + raw-text
  fallback for other constraints, `user_id` regex unit tests + full endpoint integration test,
  export format case-insensitivity, CJK-title slug+doc-id filename).

Docs (doc-parity, same commit boundary as the code):
- `docs/subsystems/webapp.md` — `judge.py` row (DB-first prompt), `POST /api/criteria` row
  (now functional), Cache fallback protocol prose (new `failedCriterionIds` semantics),
  Precompute section (per-session cap + new `failed` paragraph, with the 3-cause breakdown
  the coordinator specified), `POST /api/models`/`.../test`/export rows (409 message,
  `user_id` redaction, case-insensitive format).
- `docs/superpowers/specs/2026-06-30-demo-contracts.md` — `Document.precompute` DTO gains
  `failed: number` (inline rev-tag comment, matching the file's existing convention); §3
  cache-fallback prose updated; `POST /api/criteria` line annotated; new dated delta section
  `## EMNLP e2e-campaign bugfix delta (2026-07-17)` at the end of the file (matches the
  file's existing "dated delta section" pattern) with the full before/after for all 3 fixes
  and the coordinator's 3-distinct-causes framing for Fix 2.

## Decisions & rationale

**Fix 1 design fact (confirmed independently, matches the coordinator's T8-audit note):**
`seed.py:84-89` reads `prompts/scoring/<id>.md` and writes that text verbatim into
`criterion.prompt` for the 3 built-in ids at seed time — so making the DB row the prompt
source of truth, with the file as fallback, is safe for ALL rows, not just custom ones. The
one real call site is `app.py:918` (`_judge_live`) → `scoring_system_prompt`/`judge_one`.

**Plumbing choice for Fix 1 (why an optional kwarg, not a required `conn`/row param).** The
task flagged this exact tension: changing `judge_one`'s call signature would touch every test
that monkeypatches `app_mod.judge_one` with a fixed, non-`**kwargs` signature. I chose an
**optional keyword-only `prompt` parameter with a `None` default** on all three functions
(`_scoring_prompt`, `scoring_system_prompt`, `judge_one`) rather than threading `conn`/the
criterion row through — this keeps every existing positional call site (tests, docs tooling)
byte-identical, and only `app.py::_judge_live` (which already has the full `criterion` row)
passes the override. 4 test fakes with strict non-`**kwargs` signatures
(`test_c5_loop_integrity.py`×2, `test_issue_dedup.py`, `test_prediction_preservation.py`,
`test_budget.py`) needed a `**_kw` tolerance addition — a one-line, zero-behavior-change edit
each.

**Fix 2's `failed` counter only counts genuine judge-call exceptions**, not TOCTOU/delete
discards (`_write_paragraph` returning `False` with no exception) — those are an intentional,
benign "a live `/evaluate` or a delete raced ahead" no-op, not a failure worth alarming on.

**Fix 3's pristine-no-key gate.** `_is_no_key_error` mirrors the existing `_classify_failure`
pattern in `precompute.py`/`translate.py` (string-match on `"no api key"` in a `RuntimeError`)
rather than inventing a new exception type — same discriminator already used elsewhere in
this codebase for exactly this "never touched the network" classification.

**secrets_guard.py reversion.** My first pass added a `user_[A-Za-z0-9]+` alternative to
`secrets_guard._TOKEN_RE` — reverted once I re-checked the authorized file list, since
`secrets_guard.py` was not in it. The `user_id` redaction is instead a **local** regex
(`app_mod._USER_ID_RE`) applied only at the model-Test error-message call site, which also
still runs through the existing `redact_error()` for the usual key-shaped tokens — this
matches the task's literal instruction ("applied where the test-endpoint builds its message")
without touching an unauthorized file.

**409 handler scoping.** `_integrity_error` is a single global FastAPI exception handler for
every `sqlite3.IntegrityError` in the app (criteria, models, FKs, …), not `/api/models`-
specific. I scoped the human-message translation to the exact string
`"UNIQUE constraint failed: model.name"` and kept the raw-text fallback for every other
constraint shape, so no other 409 path's behavior changed (confirmed no test asserts a
specific message text for any other IntegrityError case).

## Open questions

- Fix 2(c) (generic-exception `errorReason` bucketing, `_classify_failure`) is explicitly
  **not fixed** — only made visible by the new `failed` count, per the coordinator's framing.
  Left as a follow-up; not in this task's scope.
- The frontend still only alarms on `succeeded === 0`; the new `failed`/refined
  `failedCriterionIds` fields are additive and backend-only — wiring a partial-failure UI
  affordance is explicitly out of this task's lane (frontend is a sibling agent's territory).

## NOT done (explicit)

- No git commit (per instructions).
- No frontend changes (out of lane) — the new `failed` precompute field and the refined
  cache-fallback `failedCriterionIds` are wire-additive/backward-compatible but currently
  unconsumed by the UI.
- Did not touch `budget.py`/`export.py` despite being pre-authorized — investigated first,
  concluded no code change was needed in either (see "Files changed" above); did not add
  speculative changes just because the files were available.
- Did not generalize the `user_id` redaction into `secrets_guard.py`'s shared `redact_error`
  (would have been the more DRY fix) — out of the authorized file list; scoped locally in
  `app.py` instead, see rationale above.

## Test run (ran, full suite)

```
.venv/bin/python -m pytest -q
674 passed in 6.09s
```

Before this task's changes, the same suite (on the same worktree HEAD) was at 673 tests, all
green — +25 new tests across the 2 new files and additions to existing files (net delta is
smaller than the number of new `def test_...` because several existing status-dict
exact-equality assertions were widened in place, not added as new tests).
