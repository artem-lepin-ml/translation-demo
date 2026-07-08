# BOUQUET judge-vs-metric Spearman/tie/delta analysis — validation report

Agent: python-pro. Task: write `scripts/judge_metric_stats.py` against the vendored
BOUQUET evaluation outputs and reproduce a colleague's screenshot Spearman table to
confirm which MetricX variant it used.

## Scope

- Read-only analysis over `external/gse-translation/data/bouquet/evaluation/<system>/`
  for the 4 vendored systems (`qwen-27b-bouquet`, `qwen-27b-bouquet-refined`,
  `translate-gemma-bouquet`, `translate-gemma-bouquet-refined`). Nothing under
  `external/` was modified.
- New script `scripts/judge_metric_stats.py` computing, per system: paragraph-level
  Spearman rho (judge criterion × metric), judge-score tie statistics, paired
  initial→refined deltas with sign-agreement and Kendall tau-b, and a validation
  section reproducing a colleague's reported Spearman/headline numbers.
- Goal was explicitly diagnostic/validation, not a new pipeline stage: confirm our
  reading of the vendored files (which MetricX variant, which alignment, which null
  handling) against known target numbers before trusting the data for the paper.
- Out of scope (not requested): adding scipy/numpy as permanent project
  dependencies, unit tests for the script, any change to `pyproject.toml`/`uv.lock`,
  any commit (explicitly forbidden by the task — "Commit NOTHING").

## Files changed

- `scripts/judge_metric_stats.py` (new, 450 lines) — the analysis script.
- `reports/bouquet/judge_metric_stats.json` (new, generated output) — full JSON dump
  of the Spearman table, headline stats, refinement deltas, and the
  validation-vs-colleague section.
- This report: `docs/reports/python-pro-bouquet-spearman-validation.md` (new).
- Nothing else in the working tree was touched (`git status --porcelain` showed only
  these two new/untracked paths before this report was added; verified no commits
  were made).

## Decisions & rationale

- **MetricX source field**: read `metricx/scores.jsonl`'s `prediction` (ref-based)
  and `metricx/scores_wo_ref.jsonl`'s `prediction` (QE) directly, rather than trusting
  the rollup `scores.jsonl`'s own unlabelled `metricx` column — spot-checked and
  confirmed identical to the ref-based file's `prediction`, so the labelled sub-file
  is the source of truth per the task's "inspect actual keys first" instruction.
- **Which MetricX variant matches the colleague's "MetX" column**: computed
  Spearman with both variants against his 24 target cells (4 systems × 3 criteria ×
  {MetX, Comet}) and picked whichever minimizes mean |residual|. Ref-based MetricX
  gives 0.0000 mean |residual| (23/24 cells exact to 4 decimals); QE gives 0.101.
  This is a hard, non-ambiguous result, not a judgment call.
- **No null-dropping/imputation logic exercised**: implemented (drops rows where the
  judge score is null before computing Spearman) per the task spec, but the vendored
  data has zero nulls across all 4×198×3 judge-score cells, so this path never
  actually triggers on real data — noted as a real (not hypothetical) finding, not a
  gap in the code.
- **No sign flip needed**: MetricX (error-style, lower=better) naturally anti-correlates
  with judge quality and Comet (quality-style) positively correlates; raw scipy
  `spearmanr` on unflipped values reproduces the targets exactly, so the "try
  sign-flipped metricx" contingency in the task brief wasn't needed.
- **Sign-agreement orientation**: for the delta/sign-agreement stat only (not the
  correlation or Kendall tau-b), metricx deltas are oriented by `sign=-1` (improvement
  = metric decreasing) and comet by `sign=+1`, per the task's explicit
  "−Δmetricx / +Δcomet" convention. Kendall tau-b is reported on the raw, unoriented
  deltas to stay consistent with the sign convention used in the main correlation
  table (negative tau for metricx is the "expected" direction there too).
- **scipy/numpy not added as project dependencies**: ran via
  `uv run --with scipy scripts/judge_metric_stats.py` (numpy comes in as scipy's own
  dependency) rather than `uv add scipy`, to keep the diff limited to exactly the two
  artifacts the task asked to leave in the tree (script + JSON), with no
  `pyproject.toml`/`uv.lock` churn for the owner to review separately.
- **Output path** `reports/bouquet/judge_metric_stats.json` follows the existing
  `reports/<topic>/...` convention already used by `reports/terminology/g6/...`,
  rather than `docs/reports/` (which is reserved for HTML/owner-facing report
  artifacts per CLAUDE.md's report template, not raw JSON analysis dumps).
- **Ruff compliance**: iterated to satisfy the repo's `ruff check` (line-length 100,
  E/F/I/B/UP) — confirmed `All checks passed!` and re-ran the script after the
  reformatting to confirm output was unchanged (byte-identical stdout tail and
  JSON `best_matching_metricx_variant`).

## Open questions

- The one non-reproducing cell (Qwen3.6-27B Accuracy/Comet: his target −0.0690 vs.
  our computed −0.0069, residual 0.0621) is most plausibly a transcription slip
  (dropped/added a leading zero) in the screenshot, since it's the only cell out of
  24 off by >0.01 and no alternate config (QE variant, sign flip) gets closer — but
  this is inference, not confirmed with the colleague directly. Worth a direct
  ping before citing that exact number in the paper.
- Sign-agreement rates are computed over small subsets per cell (n_nonzero_both
  ranges 17–54 out of 198, because judge-score ties suppress most deltas to zero) —
  these rates carry real sampling noise at that n; flagged as reported, not
  smoothed or bootstrapped.

## NOT done

- No unit tests were written for `judge_metric_stats.py` — this was scoped as a
  one-off validation/analysis tool, not asked for in the task, and I flagged this
  explicitly rather than silently skip it.
- Did not modify `pyproject.toml`/`uv.lock` to make scipy/numpy first-class project
  dependencies (see rationale above) — anyone re-running the script later needs
  `uv run --with scipy` (or an env with scipy/numpy already installed) rather than a
  bare `uv run`.
- Did not reach out to the colleague to confirm the one-cell discrepancy is a typo;
  reported it as the most likely explanation from the data side only.
- Nothing was committed, per the task's explicit instruction — script, JSON output,
  and this report are left as untracked files in the working tree for owner review.
