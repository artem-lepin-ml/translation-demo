# Final 4x5 scoring — G6 baseline judge runs (2026-07-11)

## Scope

Deadline-critical, offline scoring task (target <=15 min, no API keys, no repo
edits/commits to the working tree beyond this report). Score the owner's 4x5
table: 4 models (gemma-3-27b-it/Parasail, qwen3.6-27b/Io Net,
gemini-3.1-flash-lite/Google AI Studio, deepseek-v4-flash/Novita) x 5 metrics
(R_NER, R_search, A_disamb, R, P), each row over **its own** completed
article set (no cross-model intersection, unlike the prior 3-mode-intersection
pass). Judge dirs used `search_mode=baseline` (G_6) with `--reuse-extraction`.
Also required: an extraction-dir sanity cross-check of R_NER/R_search per
model, a bounded (<=10 min) wait for the two in-flight judges (qwen of:62,
gemini of:59) preferring COMPLETE, deepseek scored as-is at snapshot, and a
full spend ledger across all 8 run dirs touched.

This is a read-only analysis task against existing `reports/terminology/
wiki-eval/**` run directories — no production code, pipeline, or contract was
changed. Filed under `ml-engineer` because it reuses/extends the survival
metrics driver (`aggregate_survival` from `metrics.py`, commit `0fcc0e6`)
against live/partial eval-harness run output, per the dispatch map.

## Files changed

All outputs are in the task's scratchpad (not the repo), per the task's own
instruction ("outputs to .../scratchpad/final-scoring/"):

- `scratchpad/final-scoring/driver_4x5.py` — new driver (adapted from the
  prior `driver.py`/`driver_refresh.py` in the same dir): per-model
  independent scoring (no intersection), plus a judge-vs-extraction sanity
  cross-check section, plus a title-dedup fix for resumed extraction runs.
- `scratchpad/final-scoring/snapshot_4x5/` — read-only copies of
  `progress.jsonl`/`pred(.partial).jsonl`/`meta.json` for 4 judge dirs + 4
  extraction dirs, taken at `2026-07-11T06:55:54Z`.
- `scratchpad/final-scoring/scores_final_4x5.json` — machine-readable output
  (per-model judge + extraction metrics, sanity cross-check, spend, notes).
- `scratchpad/final-scoring/metrics_0fcc0e6.py` — `git show` dump of
  `metrics.py` at commit `0fcc0e6`, diffed against the working tree to
  confirm no drift (byte-identical) before trusting the import.
- This report: `docs/reports/ml-engineer-final-4x5-scoring.md` (new; written
  only because the stop hook required a report artifact — the task itself
  explicitly said "no repo edits/commits", so nothing else in the repo was
  touched and this file was not committed).

Repo working tree: unchanged other than this report file (verified via
`git status --short` on the metrics/data files used — clean before and
during the run).

## Decisions & rationale

- **No intersection this pass.** Prior drivers (`driver.py`) froze judge
  rows to the intersection of 3 search-mode dirs for a single model. This
  task explicitly wants 4 independent per-model rows, each over its own
  `progress.jsonl`-checkpointed set — implemented as a straight per-run
  `completed_titles` -> `build_survival_articles` -> `aggregate_survival`
  call, no set-intersection step in the judge loop.
- **Bounded wait, then proceed.** Polled qwen/gemini `progress.jsonl` every
  20s for up to 10 minutes (hit the wall-clock cap, exit 143 as expected).
  qwen reached 61/62, gemini 57/59 — neither completed. Given the 15-minute
  overall budget (already ~11 min elapsed after the wait), proceeded with
  snapshot-as-is per the task's own fallback ("prefer... COMPLETE" implies a
  preference, not a hard requirement) rather than waiting further and
  blowing the deadline.
- **Snapshot-before-score discipline** (carried over from the prior passes
  in this dir): copied `progress.jsonl` + `pred(.partial).jsonl` (+
  `meta.json` where present) for all 8 dirs at one wall-clock point
  (`06:55:54Z`) before running any metrics code, so all 8 rows are
  mutually consistent to a single instant despite 4 of the source dirs
  still being live-appended by running eval processes.
- **Deduped extraction-dir checkpoint titles.** `extract-gemini` (24 dup
  lines/108) and `extract-deepseek` (21 dup/82) had duplicate
  `progress.jsonl` entries for the same article — a resumed run
  re-appending a checkpoint line for an already-completed title. Original
  driver code asserted uniqueness and crashed; fixed by dedup-to-first-
  occurrence (`dict.fromkeys`) rather than failing the whole pass, since
  `aggregate_survival`'s R_NER/R_search are presence/boolean-based per
  gold entity (duplicate predicted mentions for a re-appended title don't
  change the boolean "was it recognized" outcome) — only the *article
  list itself* needed deduping to avoid double-counting that article's
  gold population. `judge-*` dirs had zero duplicates (fresh single-shot
  runs); this only affected the extraction sanity-check side.
- **Verified `metrics.py` has zero drift** from commit `0fcc0e6` (`git show
  0fcc0e6:...` diffed byte-identical against the working tree) before
  trusting the import — commit `0fcc0e6` is also the last commit touching
  that file, so there is no ambiguity about which version is live.
- **Spend is cumulative-across-resumes by construction**: confirmed in
  `scripts/wiki_eval.py` (`Checkpointer`/`cmd_run`, ~line 1738) that on
  resume `guard.spent_by_kind` is reloaded from the last checkpoint line
  before continuing, so the `spent` field in each dir's final
  `progress.jsonl` line is already the correct all-time total for that run
  dir (including gemma-3 judge's `resumed_from_n_articles: 32` restart) —
  no extra reconciliation needed for the ledger.
- **R + n_resolved_correct_search_miss == R_direct identity checked** for
  all 4 judge rows as an internal consistency sanity check (mirroring the
  "anomalies" section of the prior `driver.py`) — held exactly (divergence
  0) for all four, giving confidence the factorized survival pipeline is
  behaving consistently across all 4 independent article sets.

## Open questions

- Whether the owner wants qwen/gemini re-scored once they actually finish
  (62/62, 59/59) — this pass intentionally used the bounded-wait snapshot
  per the deadline constraint; a follow-up refresh pass (mirroring
  `driver_refresh.py`'s pattern) would take under a minute to rerun once
  those two runs reach `done==of`.
- deepseek judge is genuinely early (14/54 at snapshot) — its P/R numbers
  in the 4x5 table are the least statistically stable of the four rows;
  not flagged as an "anomaly" since the task explicitly said to score
  deepseek as-is at snapshot, but worth the owner's awareness when reading
  the table.
- The extraction-dir duplicate-checkpoint-lines issue (resumed runs
  re-appending) wasn't in scope to root-cause/fix upstream in
  `scripts/wiki_eval.py` — flagged here for `debugger`/`python-pro` if it
  recurs on future runs; this pass only worked around it read-only in the
  scratchpad driver.

## NOT done

- Did not wait for qwen/gemini to reach 100% completion (would have
  exceeded the 15-minute deadline; bounded 10-minute wait per instructions,
  then proceeded with best-available snapshot).
- Did not root-cause the resumed-run duplicate-checkpoint-line issue in
  `scripts/wiki_eval.py`'s `Checkpointer` — worked around it in the
  read-only scratchpad driver only, no upstream fix proposed or applied.
- Did not touch/commit anything in the repository proper other than this
  mandatory report file (no code, data, or contract changes) — matches the
  task's explicit "no repo edits/commits" constraint.
- Did not re-run or refresh the earlier 3-mode-intersection pass
  (`scores.json`/`scores_refresh.json` in the same scratchpad dir) — those
  are untouched, this is a wholly separate `scores_final_4x5.json` output.
