# docs-keeper report — model-comparison 2026-07-05 close-out doc-parity

Branch: `claude/ner-wikidata-grounding-eval-bqa4l2`. Not committed — orchestrator commits.

## Scope

Doc-parity pass for the 2026-07-05/06 model-comparison experiment close-out:
1. Update `docs/stages/wiki-eval.md` § Status to the true end-of-day state.
2. Append night's/today's lessons to `docs/experiments/LESSONS.md`.
3. Scan `docs/` (excluding `docs/experiments/2026-07-05-model-comparison/drafts/`
   and `docs/superpowers/specs/`) for stale "qwen still running" claims and
   graphify stragglers; report only, no edits outside item 1.

`docs/experiments/ACTIVE` was not touched (owner-reset separately).

## Files changed

- `docs/stages/wiki-eval.md` — § Status, one new paragraph appended.
- `docs/experiments/LESSONS.md` — one new dated section appended (7 bullets).

No other files edited.

## Decisions & rationale

- **"RU report v4" interpretation**: no `report-ru-v4.md` exists in `drafts/`
  (only `report-ru-v3.md`, per `SESSION-LOG.md` §8's v1→v3 history). The v4
  artifact that does exist is `docs/experiments/2026-07-05-model-comparison/model-comparison-experiment-v4.docx`
  (top-level, not in `drafts/`). Linked both: the docx as the current RU
  write-up, and `drafts/` (containing `paper-section-en.tex`) as the paper
  drafts directory — rather than inventing a `v4.md` that doesn't exist.
- **Single source of truth**: the Status paragraph links to `docs/PROBLEMS.md`
  for the qwen incident detail and to the experiment dir for process detail
  (session log/findings/budget) instead of restating them — per the
  Convention's "link, never copy" rule.
- **Sitelink numbers**: verified against `sitelink-contamination.md`
  (`drafts/`) and its underlying `sitelink_contamination.py` — clean R_doc
  0.684/0.609 matches exactly, "validated to exact matched-tuple counts"
  refers to the 4th-decimal reproduction of `metrics.json`'s own recall the
  replay documents.
- **`docs/PROBLEMS.md` link path fix**: initially wrote `[docs/PROBLEMS.md](PROBLEMS.md)`
  in `LESSONS.md` (which lives at `docs/experiments/LESSONS.md`, one level
  below `docs/`) — corrected to `../PROBLEMS.md` before finishing, since the
  wrong relative path would have silently 404'd.
- **LESSONS.md was previously just the header** (no prior dated entries) — this
  is the first substantive append, not a rewrite of prior content (none existed).

## Diffs applied (verbatim)

### docs/stages/wiki-eval.md (§ Status — appended paragraph)

```
**Model-comparison experiment close-out (2026-07-06, corpus v2, config `111`,
`use_sitelink=False` clean numbers unless noted):** `gemini-3.1-flash-lite` and
`deepseek-v4-flash` completed full 100-article runs with P3 active; every
headline number adversarially re-verified. Sitelink-rung annotation
circularity (Subtleties, above) is now quantified, not just disclosed:
`scripts/sitelink_contamination.py` (git-tracked, offline replay against each
run's own Wikidata cache) gives clean `R_doc` **0.684 (gemini) / 0.609
(deepseek)**, validated to exact matched-tuple counts against `metrics.json`.
`qwen3.7-plus`'s run finished mechanically (progress markers at 100%) but is
**INVALIDATED** by provider-outage data corruption discovered in the
reconciliation pass — see [docs/PROBLEMS.md](../PROBLEMS.md) ("wiki-eval
checkpointing desyncs progress markers from persisted predictions under
provider outages"); a clean re-run is queued. `gpt-5.5` is excluded from this
comparison — no stable gateway route held for >16h across every provider
tried. Paper artifacts: RU report drafts and the acmart paper section live in
[docs/experiments/2026-07-05-model-comparison/drafts/](../experiments/2026-07-05-model-comparison/drafts/)
(`paper-section-en.tex`), with the current RU write-up as
`docs/experiments/2026-07-05-model-comparison/model-comparison-experiment-v4.docx`;
experiment process detail (session log, findings, budget) lives in that same
directory — not duplicated here.
```

### docs/experiments/LESSONS.md (new section, verbatim)

```
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
```

## Stragglers found (out-of-zone drift — reported only, NOT edited)

### Stale "qwen still running/pending" claims (outside drafts/ and specs/)

| File | Line(s) | Claim |
|---|---|---|
| `docs/reports/2026-07-06-model-comparison.html` | 153, 194, 225, 256, 287, 318, 336, 364, 367, 373, 466, 509, 529, 532–535 | "qwen3.7-plus всё ещё выполняются в фоне", `badge--data` "идёт" cells, "Достроить прогоны gpt-5.5 и qwen3.7-plus" — an intermediate HTML report, now superseded by the close-out state. |
| `docs/reports/2026-07-06-model-comparison-v4-render-report.md` | 79–81, 116 | "qwen/gpt-5.5 in-progress/blocked status" narrated as current. |
| `docs/reports/html/2026-07-06-model-comparison-v4.html` | 145, 156, 159, 200, 202, 225, 258, 269–270, 298, 390–391, 411, 434–438, 461 | Explicitly tagged "ПРОМЕЖУТОЧНЫЙ — v4-draft, qwen в процессе (52/100)" and multiple "in progress"/badge--warn cells for the qwen resume and final artifact assembly. |
| `docs/experiments/2026-07-05-model-comparison/FINDINGS.md` | 3–4, 15, 45 | "Статус на 06:30 UTC 2026-07-06: 2 из 4 прогонов завершены... gpt-5.5 и qwen3.7-plus ещё идут" — the whole file is a stale intermediate aggregation; it is inside the experiment dir but NOT inside `drafts/`, so technically in this task's scan zone, but updating it is a bigger rewrite than a "clear one-line staleness fix" (task instruction caps edits to that bar) — left for the owner/orchestrator to decide whether to supersede-banner or rewrite. |
| `docs/experiments/2026-07-05-model-comparison/SESSION-LOG.md` | 29 (`⏳ 87/100, --resume`) | This is a dated historical session log entry (matrix table for a specific point in time), not a live status claim — judged NOT stale (it correctly records what was true at the time the log was written), so not flagged as a doc-parity problem, only noted here for completeness. |

None of these were edited — they sit outside this task's owned file
(`wiki-eval.md`) and fixing them (especially the two HTML reports and
FINDINGS.md) needs more than a one-line change: they are dated point-in-time
artifacts that arguably should get a "⚠️ superseded by the 2026-07-06 close-out,
see docs/stages/wiki-eval.md § Status" banner rather than in-place rewrites,
which is an editorial call best left to the reports' owner/orchestrator.

### Graphify stragglers

Searched all of `docs/` for `graphify` (case-insensitive). Only two hits, both
in dated historical reports, both already describing graphify's removal
correctly rather than presenting it as active:

- `docs/reports/html/2026-07-06-model-comparison-v4.html:257` — table row
  "graphify-хук удалён (решение владельца)" with a `badge--pass` "done" —
  correctly recorded as removed.
- `docs/reports/pocock-skills-install.md:47,48,51,79,131` — an installation
  report discussing the graphify skill's cap wording; historical record of
  work already done, not a live claim that graphify still exists as an active
  hook.

No stragglers requiring a fix were found — CLAUDE.md/README/`.claude/README`
are confirmed already updated per the task brief, and no other `docs/` file
references graphify as if it were still wired in.

## Open questions

- Should `docs/experiments/2026-07-05-model-comparison/FINDINGS.md` and the
  two intermediate HTML reports get a `⚠️ superseded` banner pointing at the
  close-out Status paragraph, or be left as historical point-in-time
  snapshots? Recommend a banner (Convention: "Legacy docs are deleted or get a
  `⚠️ LEGACY` banner") but this is outside the task's edit scope (not
  `wiki-eval.md`) — flagging for the orchestrator/owner.
- `docs/experiments/2026-07-05-model-comparison/model-comparison-experiment-v4.docx`
  is itself the "current" RU report per file naming, but nothing in the repo
  states whether it already incorporates the qwen-invalidated / gpt-5.5-excluded
  final decision or still reflects an earlier in-progress state (SESSION-LOG's
  "Осталось" list implies v4 was meant to include qwen's numbers, which turned
  out to be invalid) — worth the owner confirming the docx content matches the
  now-final Status paragraph before it's called done.

## NOT done (explicit)

- Did not edit `docs/experiments/2026-07-05-model-comparison/FINDINGS.md` or
  either intermediate HTML report — flagged above, not a one-line fix, and
  outside this task's owned file.
- Did not touch `docs/experiments/ACTIVE` (excluded by task instructions,
  owner resets it separately).
- Did not touch anything under `docs/experiments/2026-07-05-model-comparison/drafts/`
  or `docs/superpowers/specs/` (excluded by task instructions).
- Did not commit — orchestrator commits.
