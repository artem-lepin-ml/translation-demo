# python-pro report — `stats --judge` no longer drops other judges from summary.md

Branch: `claude/ner-translation-config-b0ozsc`. Small bug fix, no worktree switch
(task explicitly scoped to a selective-staging fix on the current branch).

## Scope

Fix `scripts/bouquet_judge_rerun.py`'s `cmd_stats`: an explicit `--judge` flag was
scoping not just the stats *recomputation* (correct, documented CLI behavior) but
also which judges' rows `build_summary_md()` renders into
`reports/bouquet/judges/summary.md` — silently dropping every other judge's row
from the combined summary. Observed live 2026-07-09 (`stats --judge
gemini-3.1-flash-lite-think` wiped 4 other judges from summary.md; caught and
hand-repaired in commit `2c3eebd`, see
`docs/reports/docs-keeper-tree-cleanup-b0ozsc.md`).

## Files changed

- [scripts/bouquet_judge_rerun.py](../../scripts/bouquet_judge_rerun.py) — `cmd_stats`
  (~line 885): `summary_slugs` is now always the sorted list of judge dirs under
  `out_dir` that have a `stats.json` on disk, never `args.judge`. `--judge` still
  scopes the loop above it (which judges get `compute_stats_for_judge` re-run and
  their `stats.json` rewritten) — that part was already correct and is unchanged.
- [tests/test_bouquet_judge_rerun.py](../../tests/test_bouquet_judge_rerun.py) —
  new regression test
  `test_cmd_stats_with_explicit_judge_keeps_other_judges_in_summary`: two fake
  judge dirs (`judge-a`, `judge-b`) each with a minimal `scores.jsonl` +
  `stats.json` under `tmp_path`; runs `cmd_stats` with `args.judge=["judge-a"]`
  and asserts `summary.md` still contains `judge-b`. `bjr.load_judges` and
  `bjr.compute_stats_for_judge` are monkeypatched to avoid touching the real
  YAML registry / vendored MetricX/COMET files (network-free, disk-only);
  `bjr.ROOT` is monkeypatched to `tmp_path` because `cmd_stats` logs paths via
  `.relative_to(ROOT)` and `tmp_path` lives outside the real repo root.
  6 tests total in the file (5 pre-existing `t0_local`/`extra_body` tests
  untouched + 1 new).

## Decisions & rationale

- **Minimal, idiomatic fix**: dropped the `args.judge or` short-circuit and always
  discover from disk — exactly the fix path called out in the task ("pass the
  discovered full judge list into `build_summary_md()`"), no new function/flag
  introduced. The stats-recomputation scoping loop (`for slug in slugs`) is
  untouched; only the summary-rebuild source changed.
- **Regression-test isolation**: used monkeypatch rather than real config/data
  fixtures so the test has zero dependency on `configs/bouquet_judges.yaml`
  contents or vendored BOUQUET/MetricX/COMET files staying stable — the test
  verifies the aggregation *logic*, not the data.
- **Verified the test actually catches the bug**: `git stash`ed the fix, reran
  the new test alone — it failed with `AssertionError: stats --judge judge-a
  must not drop judge-b from summary.md`, confirming the pre-fix code reproduces
  exactly the observed 2026-07-09 incident. Then restored the fix and reran —
  green.

## Run artifacts (evidence)

- `uv run pytest tests/test_bouquet_judge_rerun.py -v` → **6 passed** (0 failed),
  exit 0.
- Pre-fix repro (`git stash push -- scripts/bouquet_judge_rerun.py`, rerun new
  test alone): **1 failed** with the exact "must not drop judge-b" assertion,
  confirming the test is not a false positive; `git stash pop` restored the fix.
- `ruff check scripts/bouquet_judge_rerun.py tests/test_bouquet_judge_rerun.py`:
  1 pre-existing `E501` (line 45, `test_extra_body_none_by_default_is_a_noop_for_existing_regimes`,
  not touched by this change — confirmed via `git diff` showing that line
  unmodified). No new lint issues from this fix.
- Regenerated `reports/bouquet/judges/summary.md` locally via the fixed path
  (`uv run python scripts/bouquet_judge_rerun.py stats --judge
  gemini-3.1-flash-lite-think` — pure local aggregation over on-disk
  `scores.jsonl`/vendored MetricX/COMET files, no network) and diffed against
  the committed version: **identical except the `generated_at` timestamp** in
  both `gemini-3.1-flash-lite-think/stats.json` and `summary.md` (inherent —
  every `stats` run stamps `datetime.now(UTC)`). All 6 judges'
  rows present in both. Since the diff is non-substantive, reverted the
  regenerated files (`git checkout --`) rather than committing timestamp-only
  noise — confirmed via `git status --short` showing only the two source files
  (`scripts/bouquet_judge_rerun.py`, `tests/test_bouquet_judge_rerun.py`)
  staged.

## Open questions

None — scope was narrow and fully verified.

## NOT done (explicit)

- Did not re-run `stats` for all 6 judges (only `gemini-3.1-flash-lite-think`,
  the judge from the original incident) — sufficient to prove the fix path
  works; a full re-run would only regenerate more `generated_at` timestamps
  with no other diff, per the single-judge check above.
- Did not touch `gemini-3.1-pro` (no `stats.json` on disk — aborted run per
  commit `2c3eebd`'s message); out of scope for this bug fix.
- Did not fix the pre-existing `E501` on test line 45 — not part of this
  bug's blast radius, left untouched per "keep the change minimal."
