# QUICK rescore — gemini judge (full) + qwen extraction (sanity preview), both now 100/100

## Scope

Requested: an offline, no-repo-edits, ≤10min rescore of two wiki-eval runs that had
just reached their full 100-article set, reusing `driver_4x5.py` (from a prior task
in the same scratchpad) as a base, adapted minimally:

1. `reports/terminology/wiki-eval/google--gemini-3.1-flash-lite--Google-AI-Studio/111/2026-07-11T05-27-07Z`
   (judge run, extended from a 59-article prefix to 100/100) — full survival metrics
   (R_NER, R_search, A_disamb, R, R_direct, P, each with matched/total counts) plus
   the `resolved_by` confidence-state distribution over the full pred population.
2. `reports/terminology/wiki-eval/qwen--qwen3.6-27b--Io-Net/111/2026-07-10T20-19-44Z`
   (extraction-only run, `no_judge=true`, extended to 100/100) — sanity preview:
   R_NER/R_search only (no judge stage in this run, so A_disamb/R/R_direct/P don't
   apply).

Out of scope by explicit instruction: no repo/DB edits, no commits, no key usage,
no re-running the underlying wiki-eval pipeline — pure read-only scoring against
snapshot copies of the two run directories.

## Files changed

**Repo (this commit-worthy artifact only):**
- `docs/reports/ml-engineer-quick-rescore-gemini-qwen-final.md` (this report — written
  only because the stop-hook mandated it; not committed unless the owner asks per
  CLAUDE.md Hard Invariant "commit only when explicitly requested").

**Scratchpad only** (`/tmp/claude-0/-home-user-translation-demo/d94abddc-f105-576c-b81a-a51a1ca3f0ff/scratchpad/final-scoring/`), not part of the repo, not committed:
- `driver_final.py` — new driver, adapted from `driver_4x5.py`'s helper functions
  (`load_gt`, `load_pred_records`, `completed_titles` with dedup-to-first-occurrence,
  `build_survival_articles`, `cell`); added `resolved_by_distribution()` (new, not in
  `driver_4x5.py`) and simplified `score_run()`/`main()` to two runs instead of a 4x5
  grid (no cross-model intersection or sanity cross-check needed here since each run
  is scored standalone on its own completed set).
- `snapshot_final/judge-gemini/` — snapshot copy (`calls.jsonl`, `pred.jsonl`,
  `progress.jsonl`, `meta.json`) of the gemini judge run dir, taken before scoring.
- `snapshot_final/extract-qwen/` — snapshot copy of the qwen extraction run dir.
- `scores_gemini_final.json` — the requested output: both runs' metrics, counts,
  and the gemini `resolved_by` distribution, plus provenance notes.

No source files under `src/palimpsest/` were modified; `metrics.py` was imported
read-only from the live repo tree (not the `metrics_0fcc0e6.py` snapshot copy sitting
in scratchpad from the prior task — confirmed no drift is a fact from that prior
task's notes, not re-verified here since this task didn't touch metrics.py).

## Decisions & rationale

- **Snapshot-copy-first**: copied both run dirs' 4 files each into
  `snapshot_final/` before running any scoring, per the task's explicit instruction
  and to avoid any risk of scoring against a directory that could still be
  concurrently written to by another process.
- **Reused `driver_4x5.py`'s dedup rule verbatim**: `completed_titles()` dedups
  `progress.jsonl` checkpoint lines to first occurrence, exactly as instructed
  ("dedup duplicate progress lines to first occurrence as the driver already does").
  Both runs showed 0 duplicate lines at final snapshot (unlike the earlier
  gemini/deepseek extraction dirs the 4x5 driver had flagged with 24/21 dups) —
  100 unique titles, 100 progress lines, no drops.
- **Asymmetric metric scope per run, per task instruction**: gemini gets all 6
  survival cells (`R_NER, R_search, A_disamb, R, R_direct, P`) since it's a judge
  run with disambiguation; qwen gets only `R_NER, R_search` since it's
  extraction-only (`no_judge=true` in its `meta.json`) — `A_disamb`/`R`/`R_direct`/`P`
  are undefined without a judge/resolved-`qid` stage to score against, so computing
  them would have been meaningless, not merely omitted for time.
- **`resolved_by_distribution()` is new** (not present in `driver_4x5.py`): a flat
  `Counter` over every pred record's `resolved_by` field across the gemini run's
  full 100-article set, not gold-filtered — this matches what the task asked for
  ("resolved_by distribution ... needed for the paper's confidence-state shares"),
  which is a property of the *prediction* population, not the *gold* population.
  Verified the four counts sum exactly to `meta.json`'s `n_pred_mentions` (22649) —
  no `judge_unavailable`/`wikidata_unavailable` values appeared, consistent with
  `meta.json.n_failed_judge_calls: 0`.
- **`aggregate_survival` imported live** from `src/palimpsest/terminology/evaluation/metrics.py`
  (not the frozen `metrics_0fcc0e6.py` copy in scratchpad) since the task didn't ask
  to re-verify byte-identity to that commit and the live file is closer to ground
  truth for a "final" score.
- **R == R_direct exactly (divergence 0)** for the gemini run — flagged as an
  explicit sanity signal in the metrics.py docstring (only diverges if some pred
  record predates the 2026-07-10 `candidates`-field patch); confirmed the field is
  present on every record inspected, so this equality is expected, not a red flag.

## Open questions

- None raised back to the owner — the task was fully executable from existing
  run-dir artifacts (`meta.json`, `progress.jsonl`, `pred.jsonl`) with no missing
  inputs.

## NOT done

- **No `metrics.json` was written into either live run directory.** The gemini
  judge dir already had its own `metrics.json` (auto-generated by the pipeline,
  not touched); the qwen extraction dir has no `metrics.json` on disk (extraction
  dirs apparently don't auto-generate one) — this task did not add one there,
  consistent with "sanity preview" scope (results live only in
  `scores_gemini_final.json`, not written back to the run dir).
- **No cross-check against the 4x5 driver's own scoring of these two same models**
  (`scores_final_4x5.json` in the same scratchpad dir) was performed — that prior
  run scored gemini/qwen judge dirs at 57/59 and 61/62 completion respectively
  (incomplete at that time); this task's numbers supersede those for the now-complete
  100/100 sets but no explicit diff/reconciliation between the two JSON outputs was
  produced, since it wasn't asked for.
- **No commit.** Per the task's own instruction ("no repo edits/commits") the
  intended deliverable was scratchpad-only. This report file is the one exception,
  written only because the stop-hook flagged its absence as mandatory; it is left
  as an uncommitted, untracked file in the working tree — committing it is an
  owner decision, not taken here.
- **No re-run/verification of the underlying wiki-eval pipeline** (e.g., confirming
  `meta.json.finished_at` timestamps against wall-clock, or re-deriving `of=100`
  independently) beyond reading the files as delivered — trusted the run dirs'
  own bookkeeping (`done`, `of`, `finished_at`) at face value, as the task's
  "≤10 min offline" framing implies.
