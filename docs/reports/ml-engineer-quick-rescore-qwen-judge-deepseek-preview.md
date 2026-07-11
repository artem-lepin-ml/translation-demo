# QUICK rescore — qwen judge (full, 100/100) + deepseek judge (54-prefix preview)

## Scope

Requested: an offline, no-repo-edits, ≤10min rescore of two wiki-eval judge run
directories, reusing `driver_final.py` (from the immediately prior same-session task)
as a base, adapted minimally:

1. `reports/terminology/wiki-eval/qwen--qwen3.6-27b--Io-Net/111/2026-07-11T05-26-05Z`
   (judge run, extended from a 62-article prefix to 100/100, per `meta.json`
   `resumed_from_n_articles=62` and `finished_at` present) — full survival metrics
   (R_NER, R_search, A_disamb, R, R_direct, P, each with matched/total counts) plus
   the `resolved_by` confidence-state distribution (counts + %) over the full
   pred population.
2. `reports/terminology/wiki-eval/deepseek--deepseek-v4-flash--Novita/111/2026-07-11T06-18-48Z`
   (judge run, 54/54 per its final `progress.jsonl` line at snapshot time, not yet
   extended to 100) — same metric set reported as an explicit PREVIEW over the
   54-article prefix currently on disk.

Out of scope by explicit instruction: no repo/DB edits, no commits, no key usage,
no re-running the underlying wiki-eval pipeline — pure read-only scoring against
snapshot copies of the two run directories, taken first.

## Files changed

**Repo:**
- `docs/reports/ml-engineer-quick-rescore-qwen-judge-deepseek-preview.md` (this
  report — written per the mandatory reporting protocol; not committed, per the
  task's own "no commits" instruction).

No files under `src/palimpsest/`, `reports/terminology/wiki-eval/`, or anywhere
else in the repo were modified. `git status --porcelain` at completion shows only
pre-existing, in-flight changes from other background processes (the deepseek run
itself is still actively appending to `calls.jsonl`/`progress.jsonl`/
`pred.partial.jsonl` in the live repo tree, and unrelated gemma-3/wikidata-cache
runs are also live) — none of that is attributable to this task, which only read
files and wrote to scratchpad + this one report file.

**Scratchpad only** (`/tmp/claude-0/-home-user-translation-demo/d94abddc-f105-576c-b81a-a51a1ca3f0ff/scratchpad/final-scoring/`), not part of the repo, not committed:
- `driver_qwen_final.py` — new driver, adapted from `driver_final.py` (itself
  adapted from `driver_4x5.py`): same `load_gt`/`load_pred_records`/
  `completed_titles` (dedup-to-first-occurrence)/`build_survival_articles`/`cell`/
  `resolved_by_distribution` helpers; changed only `score_run()`'s call sites (both
  runs now get `full_metrics=True`, since both are judge runs, unlike the prior
  task's asymmetric judge/extraction-only pairing) and `main()`'s two run
  selections + provenance notes.
- `snapshot_qwen_final/qwen-judge/` — snapshot copy (`calls.jsonl`, `meta.json`,
  `metrics.json`, `pred.jsonl`, `progress.jsonl`, `report.html`) of the qwen judge
  run dir, taken at 2026-07-11T09:25:00Z, before scoring.
- `snapshot_qwen_final/deepseek-judge/` — snapshot copy of the deepseek judge run
  dir at the same timestamp (7 files incl. `pred.partial.jsonl`, byte-identical to
  `pred.jsonl` at copy time).
- `scores_qwen_final.json` — the requested output: both runs' metrics, counts, and
  resolved_by distributions, plus provenance/anomaly notes.
- `run_output.txt` — captured stdout of the final driver run (human-readable
  summary table), for cross-checking against the JSON.

## Decisions & rationale

- **Snapshot-copy-first**: copied both run dirs' full file sets into
  `snapshot_qwen_final/` before running any scoring, per the task's explicit
  instruction — important here specifically because `git status` confirms the
  deepseek run dir is being concurrently written to by a live background process
  (`calls.jsonl` mtime kept advancing after the copy), so scoring against a live
  path instead of a snapshot would have been non-reproducible.
- **Reused the dedup-to-first-occurrence rule verbatim** from `driver_4x5.py`/
  `driver_final.py`. The task description flagged qwen as needing "dedup duplicate
  progress lines" — checked explicitly: qwen's `progress.jsonl` has 100 lines, 100
  unique titles, 0 duplicates at this snapshot (the phrase in the task is the
  standing *rule* to apply, not a report of duplicates actually found this time).
  Deepseek: 54 lines, 54 unique, likewise 0 duplicates.
- **Both runs scored with `full_metrics=True`** (all 6 survival cells), unlike the
  prior task's qwen-extraction/gemini-judge pairing — both dirs here are genuine
  judge runs (`no_judge: false` in both `meta.json`s), so A_disamb/R/R_direct/P are
  well-defined for both.
- **Deepseek reported explicitly as a PREVIEW, not a final score** — its `meta.json`
  has `n_articles: 54`, no `resumed_from_n_articles`/`finished_at` marking a
  completed extend-to-100 cycle (unlike qwen, which does), and the task instruction
  itself frames it as "will be extended to 100 later." The label, JSON key
  (`deepseek_judge_54prefix_preview`), and every printed line say "54-prefix
  PREVIEW" to prevent this being read as comparable-to-100 later without context.
- **Traced and documented the qwen R_search off-by-one anomaly** (see Critical
  findings below) rather than silently reporting a number that looked
  inconsistent with the prior task's extraction-only sanity preview for the same
  underlying extraction. Root-caused to one specific article/mention via a
  standalone per-title diff script (not part of the driver — throwaway, run once,
  not saved to scratchpad as a reusable artifact since it isn't needed again).
- **`aggregate_survival` imported live** from
  `src/palimpsest/terminology/evaluation/metrics.py`, consistent with the prior
  task in this same scratchpad chain.

## Open questions

- None raised back to the owner — the task was fully executable from existing run-dir
  artifacts (`meta.json`, `progress.jsonl`, `pred.jsonl`) with no missing inputs.
  The deepseek run's eventual 100/100 completion is explicitly out of scope per the
  task framing ("will be extended to 100 later" — a future rescore, not this one).

## NOT done

- **No re-scoring once deepseek reaches 100/100.** This task reports the 54-prefix
  as it stood at snapshot time only; a follow-up QUICK rescore will be needed once
  that run finishes (owner already anticipates this per the task wording).
- **No cross-check against the 4x5 driver's own scoring of these two models**
  (`scores_final_4x5.json` in the same scratchpad dir) beyond the one targeted
  diff against `scores_gemini_final.json`'s qwen-extraction-only preview (used to
  root-cause the R_search anomaly) — no broader reconciliation was performed since
  it wasn't asked for.
- **No investigation into *why* qwen shows `judge_unavailable`/`wikidata_unavailable`
  resolved_by states beyond confirming they are documented graceful-degradation
  paths in `label_first.py`** (not hard call failures — `meta.json` reports
  `n_failed_judge_calls: 0` for this run). Whether 286 judge_unavailable mentions
  (1.31% of predictions) is an acceptable rate for this model/provider pairing is
  an owner/data-scientist judgment call, not made here.
- **No commit.** Per the task's own instruction ("no repo edits/commits") the
  intended deliverable is scratchpad-only; this report file is the one exception,
  written per the mandatory reporting protocol, left uncommitted.
- **No re-run/verification of the underlying wiki-eval pipeline** (e.g. independently
  re-deriving `done`/`of` counts or `finished_at` timestamps) — trusted each run
  dir's own bookkeeping at face value, consistent with the "≤10 min offline" framing.
