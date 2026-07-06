# Experiment lessons

Running log of generalizable lessons from experiment runs and sessions. Append
one dated bullet per lesson here (via `/retrospective` or the experiment-runner
self-improvement step); never rewrite prior entries.

## 2026-07-06 — model-comparison experiment close-out

- **Canary-before-matrix paid off.** A small canary run caught the Wikidata
  429/Retry-After truncation and the provider circuit-breaker issue before the
  full multi-model matrix started — keep doing this for any multi-hour paid run.
- **Supervise live long runs from the main thread (harness-tracked bash), not
  via subagents.** Subagents lost the process and its stdout twice overnight;
  the matrix was moved under direct main-thread control after that.
- **Checkpointing is mandatory for long runs, BUT progress markers must be
  reconciled against persisted predictions.** The qwen incident showed a
  `progress.jsonl` "done" marker can lie under provider outages while
  `pred.partial.jsonl` silently holds far fewer records — see
  [docs/PROBLEMS.md](../PROBLEMS.md) ("wiki-eval checkpointing desyncs progress
  markers from persisted predictions under provider outages").
- **Integrity gates before reading scores.** Article coverage in pred vs GT,
  plus `judge_unavailable` share, must be checked before trusting any metric —
  a plausible-looking per-slice precision does not certify a run (the
  qwen run's per-stratum cells looked fine while `R_doc` was 0.164 against
  the true clean baseline).
- **Reconstructed bibliographies must be web-verified entry-by-entry.**
  Today's verification pass found five fabricated co-authors and two invented
  paper titles in entries that "looked right" — the unflagged entry was the
  worst one.
- **Parallel means parallel — check the actual concurrency cap.** The
  Workflow tool caps per-run concurrency at `min(16, cores−2)` — 2 on a
  4-core cloud box; split fans across concurrent runs or use direct
  background agents instead (CLAUDE.md R6).
- **Wikidata-heavy passes compete for the same rate budget.** Never run two
  Wikidata-heavy replays/re-groundings concurrently — observed a 429 storm
  and ~3x slowdown when they overlapped.
