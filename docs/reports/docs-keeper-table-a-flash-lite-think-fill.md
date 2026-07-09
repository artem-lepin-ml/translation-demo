# docs-keeper report — Table A flash-lite-think row fill (reasoning sensitivity pair complete)

## Scope

Source of truth: commit `f901210` — `reports/bouquet/judges/gemini-3.1-flash-lite-think/stats.json`
(read-only) and `docs/reports/python-pro-judge-run-gemini-flash-lite.md` Part 2. The
`gemini-3.1-flash-lite-think` judge run (reasoning ON) is complete: 2376/2376, $0.4749.

Diff zone (shared worktree, `claude/ner-translation-config-b0ozsc`): `docs/paper/table-a-judges.tex`,
`docs/paper/paper-state.md`, `docs/reports/html/overnight-mission-2026-07-09.html`, and the scratchpad
mirror `overnight-report-artifact.html`. Did not touch `reports/bouquet/deepseek-v4-flash/**` or any
other live agent's files — verified via `git status --porcelain` before editing (only my 3 target
files plus an unrelated `reports/bouquet/judges/summary.md` modification by another agent, left
untouched, and untracked files from other agents, left untouched).

## Files changed

- `docs/paper/table-a-judges.tex` — filled the `Gemini-3.1-Flash-Lite (default, reas. on)` row with
  real numbers computed from `stats.json` (4-system unweighted average per cell, `metricx_ref` only,
  Ties% = unweighted mean of `tie_rate_9_10` across all 4 systems x 3 criteria — same methodology as
  the three already-filled rows per `docs/reports/docs-keeper-table-a-judge-rows-fill.md`). Removed
  the row's `---` placeholders and the PARTIAL/797-out-of-2376 TODO comment; replaced it with a NOTE
  comment recording the reasoning-sensitivity finding (same underlying model as the row above,
  commit `f901210`). Updated the DeepSeek-V4-Flash TODO comment: `19/2376` &rarr; `19-290/2376 across
  parked resumes`, added the two newer park commits (`02e4f25`, `70e9ba5`) to the citation list. Left
  the local-judges TODO (sr004) untouched — still pending, out of this task's data.
- `docs/paper/paper-state.md` — Table A fill-status block: `3/8 DONE, 2 PARTIAL` &rarr; `4/8 DONE, 1
  PARTIAL`; moved `gemini-3.1-flash-lite-think` from the PARTIAL bullet to the DONE bullet with its
  real commit/cost/outage-survival note; added a one-paragraph reasoning-sensitivity finding
  (Acc +0.20, Flu +0.35, Sty +0.35 means; style tie-rate 71.1% &rarr; 85.4%; no COMET/MetricX
  correlation gain except style 0.149 &rarr; 0.198) directly under the DONE bullet, since the pair is
  now complete on both sides and this is the paper-relevant conclusion. Updated the DeepSeek bullet
  to the current 290/2376 state with all four park commits and the latest outage window
  (~09:55-10:15Z). Left the older narrative "Table A protocol, 7-judge lineup" section further down
  untouched — same scoping call the prior docs-keeper report made (that section counts only the
  7 core judges, not the -think tracking row; out of this diff).
- `docs/reports/html/overnight-mission-2026-07-09.html` — flash-lite-think card flipped
  yellow&rarr;green across every place it appears: lead summary, radar legend table + polygon
  geometry (moved that axis from a partial radius to the axis's full-radius point, matching how the
  other 3 DONE axes are already drawn), the Table A status table (badge, progress, commit `f901210`,
  cost, one-line outage-survival note), the per-judge comparison table (added a new row: Acc 9.68 /
  Flu 9.87 / Sty 9.03 / ties 97.7/98.2/85.4%), a new narrative paragraph under that table stating the
  reasoning-sensitivity finding, the findings section (replaced the old "HIGH — Gemini outage" finding
  with an "INFO — РЕШЕНО" resolution note, added a new INFO finding for the sensitivity result), an
  evidence-item for the completed run, and a next-steps bullet recommending the pair for the paper's
  judge-protocol section. DeepSeek card updated in parallel per the task brief: 19/2376 &rarr;
  290/2376, four park commits listed, the ~09:55-10:15Z growth-then-relapse window described, "agent
  in a resident probe-retry loop" language used instead of the old "recovery poller".
- `/tmp/.../scratchpad/overnight-report-artifact.html` — overwritten with a byte-identical copy of the
  repo HTML (verified via `cmp`); this file is outside the repo and was not staged.

## Decisions & rationale

1. **Fill methodology matches the prior docs-keeper precedent exactly** (verified by re-deriving the
   already-filled Gemini-3.1-Flash-Lite reasoning-off row's numbers from its own `stats.json` and
   confirming they reproduce the table's existing 9.48/9.52/8.67/87.8 cell before trusting the same
   formula for the new row): simple unweighted mean over the 4 BOUQUET systems per criterion for the
   mean-score and rho columns, and Ties% as the unweighted mean of `tie_rate_9_10` across all 12
   (system x criterion) cells, `metricx_ref` only (not `metricx_qe`, per the skeleton's single MetricX
   column). Computed by hand from the stats.json values shown in the tool transcript; every intermediate
   sum is reproducible from the raw per-system numbers.
2. **New row placement**: filled the existing skeleton row (the prior docs-keeper report had already
   added a distinct `Gemini-3.1-Flash-Lite (reas. on)` row for exactly this run) rather than adding
   another row — the skeleton already anticipated this fill point.
3. **Radar polygon**: rather than leave the flash-lite-think axis at its old partial-radius point (which
   would now misrepresent a DONE thread as PARTIAL), moved it to the same full-radius coordinate the
   axis's own line endpoint defines (`234.85,234.85`), matching how the other 3 already-DONE axes are
   plotted at their own full-radius endpoints. Also nudged the DeepSeek axis point slightly outward
   (150.00,160.88 &rarr; 150.00,164.64) to reflect 290/2376 vs. the old 19/2376, using the same linear
   scale the other partial point implied is not strictly followed by the source chart (it uses a
   visibility floor); kept the same qualitative "still near-center, clearly PARTIAL" shape rather than
   over-fit a precise formula that isn't recoverable from the original SVG alone.
4. **Byte-identical scratchpad copy**: rather than hand-edit both files in parallel (error-prone, could
   drift), edited the repo copy first, verified it parses as valid HTML, then `cp`'d it over the
   scratchpad file and confirmed with `cmp` (byte-for-byte identical, not just `diff`-equal).
5. **Findings section**: downgraded the Gemini outage entry from HIGH to an INFO "РЕШЕНО" (resolved)
   entry rather than deleting it — the ~11h outage/detachment saga (session-teardown death, container
   recycle) is itself a real operational finding worth keeping for the record (structural lesson about
   detached processes), just no longer an open risk.

## Open questions

- Whether the reasoning-sensitivity finding belongs in the paper's main results section or only the
  appendix/limitations discussion is an owner call — flagged in both the tex comment and paper-state.md
  as "worth a line", not prescribed further.
- `reports/bouquet/judges/summary.md` was modified in the working tree (visible in `git status`) by
  another agent's `stats` regeneration; per the established shared-worktree convention (see the earlier
  python-pro report's "NOT done" section) this is not this task's file to commit — left untouched and
  unstaged.

## NOT done (explicit)

- Did not touch `reports/bouquet/deepseek-v4-flash/**`, `reports/bouquet/judges/summary.md`, or any
  other live agent's files — read-only checks only (`wc -l` on deepseek's `scores.jsonl`, `git log`
  for its park commits) to source the deepseek-status numbers cited in the docs.
- Did not fill the 3 local-judge rows (sr004) or complete the deepseek row in the tex table — both
  still genuinely pending, marked `---` with TODO as before (only the TODO comment text for deepseek
  was refreshed with current counts/commits).
- Did not renumber or otherwise touch the "Table A protocol, 7-judge lineup" narrative section in
  `paper-state.md` beyond the summary block — same scoping precedent as the prior docs-keeper report.
- Did not run a LaTeX compile check (no local TeX toolchain invoked) — table syntax hand-verified
  against the existing row grammar only.
- Did not stage or commit the scratchpad HTML file (outside the repo, edited in place only, per the
  task's explicit instruction).

## Verified code&harr;doc pairs

| Doc claim | Source verified |
|---|---|
| flash-lite-think row: Acc 9.68 / Flu 9.87 / Sty 9.03, rho MetricX -0.08/-0.16/-0.11, rho COMET 0.15/0.14/0.20, ties 93.8 | `reports/bouquet/judges/gemini-3.1-flash-lite-think/stats.json` (4-system average, hand-computed and cross-checked against the per-system table already published in `docs/reports/python-pro-judge-run-gemini-flash-lite.md` Part 2, which independently reports the same rounded per-criterion averages: Acc 9.679, Flu 9.872, Sty 9.025, ties 97.7/98.2/85.4%) |
| 2376/2376 calls, $0.4749, commit `f901210` | `docs/reports/python-pro-judge-run-gemini-flash-lite.md` Part 2 "Run artifacts" section |
| DeepSeek 290/2376, park commits `501c394`/`85e5435`/`02e4f25`/`70e9ba5` | `wc -l reports/bouquet/judges/deepseek-v4-flash/scores.jsonl` -> 290; `git log --oneline -3 -- reports/bouquet/judges/deepseek-v4-flash/` shows all 4 commit subjects matching the citation |
| Reasoning-on vs. reasoning-off deltas (Acc +0.20, Flu +0.35, Sty +0.35, style ties +14.3pp, style rho COMET 0.149->0.198) | `docs/reports/python-pro-judge-run-gemini-flash-lite.md` "Reasoning-ON vs. reasoning-OFF comparison" table, Part 2 |
| Outage timeline (01:21Z 503 storm, 05:41Z session-teardown death, 09:13:49Z container recycle, 12:26Z complete) | `docs/reports/python-pro-judge-run-gemini-flash-lite.md` "Outage timeline" table, Part 2 |
| Repo HTML and scratchpad HTML byte-identical after edits | `cmp` exit 0 (no output = identical) between `docs/reports/html/overnight-mission-2026-07-09.html` and the scratchpad copy |
