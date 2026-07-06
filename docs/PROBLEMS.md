# Pipeline problems log

Up-link: [docs/README.md](README.md). Logs **systemic or complex** pipeline problems per
[CLAUDE.md](../CLAUDE.md) § Process step 7 ("Fix") — the kind that need a real root-cause
pass (systematic-debugging) and possibly a deep-research + tournament before a fix lands,
not a one-line patch. This is a working log, not a limitations doc:

- A **fixed** bug moves here only if it was systemic enough to need tracking across a fix
  cycle; once resolved, mark the entry `RESOLVED` in place (date + commit/PR) rather than
  deleting it — the reasoning stays useful.
- **Open product limitations** (accepted scope cuts, known cosmetic issues, documented
  workarounds) belong in [docs/known_issues.md](known_issues.md), not here.
- **Day-to-day fixed bugs** with no systemic angle are git history, not a doc entry.

Entry format: symptom → impact → root-cause area (hypothesis, until verified) → proposed
fix → status.

## OPEN — wiki-eval checkpointing desyncs progress markers from persisted predictions under provider outages (2026-07-06)

**Symptom:** During the 2026-07-06 overnight `qwen/qwen3.7-plus` (`provider-8`) wiki-eval
run, an upstream 429 storm caused `progress.jsonl` to record articles as done (99/100)
while `pred.partial.jsonl` actually held predictions for only 36 articles — extraction
results were silently lost but the per-article completion marker was written anyway
(progress/pred desync). A later `--resume` trusted the done-markers instead of
reconciling against `pred.partial.jsonl` content, so it recovered only the 29 articles it
could positively detect as absent (36 → 65), and the final `pred.jsonl` covers **65/100
articles**, not 100. In the same run, judge calls made during re-grounding also failed
under the same 429s (gold mentions covered by `judge_unavailable` groundings per
`metrics.json` `slices.resolved_by`: 735, vs 12 in the clean
`google/gemini-3.1-flash-lite` run on the same config; raw `pred.jsonl` lines with
`resolved_by=judge_unavailable`: 2929 vs 6), silently zeroing their recall
contribution instead of failing loud.

**Impact:** Metrics computed over a run directory like this look plausible on the surface
(per-stratum precision cells render fine) while being invalid overall — `R_doc`
(document-level recall, M3) reads **0.164** against an expected ~0.6+ for this
model/config. Without a forensic pass (pred.jsonl article coverage vs gt.jsonl,
judge_unavailable share per metrics slice) this would have been published as a genuine
model-quality result instead of an infrastructure artifact. Run dir kept for forensics,
marked invalidated: `reports/terminology/wiki-eval/qwen--qwen3.7-plus--provider-8/111/2026-07-06T09-55-11Z/`.

**Root-cause area (hypothesis — verify before fixing):**
- Per-article completion is written to `progress.jsonl` on task completion regardless of
  whether that article's predictions were actually flushed to `pred.partial.jsonl`.
- Extraction failures after retry exhaustion (`RESILIENT_ATTEMPTS`/`RESILIENT_BACKOFF` in
  `scripts/wiki_eval.py`) degrade to empty results (`safe_extract`) instead of failing the
  article outright.
- `--resume`'s checkpoint merge trusts `progress.jsonl`'s done-markers over actual
  `pred.partial.jsonl` content, so it cannot distinguish "done and persisted" from "marked
  done but lost".

**Proposed guards (not implemented today — scope for the fix):**
1. `report`/metrics must hard-fail (or at minimum print a red banner into stdout and
   `metrics.json`) when predicted article coverage < GT article coverage, or when
   `judge_unavailable` share exceeds a threshold.
2. An article is "done" only if its predictions were actually flushed — completion and
   persistence must be the same atomic fact, not two independently-written signals.
3. `--resume` should reconcile `progress.jsonl` against `pred.partial.jsonl` content, not
   trust the progress markers alone.

**Status:** OPEN. Logged 2026-07-06. Next step: `superpowers-systematic-debugging` on the
three root-cause hypotheses above, then implement the guards.

**Related:** [docs/known_issues.md](known_issues.md) (provider-outage-window entry),
[docs/stages/wiki-eval.md](stages/wiki-eval.md) (checkpointing design — "Per-article
checkpointing + `--resume`" and "Resilience patch" subtleties).
