# docs-keeper report — fill clean P_label cells in Table C

## Scope

Diff zone: fill the just-computed clean $P_{\mathrm{label}}$ values (Gemini-3.1-Flash-Lite,
DeepSeek-V4-Flash) into `docs/paper/sections/table-c-grounding.tex` (main table + appendix
table `app:grounding-full`), and update the Table C fill status in `docs/paper/paper-state.md`.
Branch `claude/ner-translation-config-b0ozsc`, shared worktree — selective staging only.

Ground truth verified before editing:
- `docs/experiments/2026-07-05-model-comparison/sitelink-clean-full-metrics.json`
  (commit `4770157`) — `p_label_p3ex` blocks confirm gemini `0.5304` [0.5206, 0.5401]
  5340/10068, deepseek `0.5346` [0.5238, 0.5453] 4409/8248.
- `docs/reports/python-pro-sitelink-clean-replay.md` — postmortem + headline tables,
  same values, cross-checked ("Final clean P_label" table).

## Files changed

- `docs/paper/sections/table-c-grounding.tex`
  - MAIN table: filled $P_{\mathrm{label}}$ cells for Gemini-3.1-Flash-Lite
    (`0.530 [.521--.540]`) and DeepSeek-V4-Flash (`0.535 [.524--.545]`), matching the
    existing `R_doc` cell style (`{\scriptsize[...]}` bracketed CI). Removed the two
    `% TODO(P_label): ...` comment lines above those rows (only those two — the three
    `sr004` TODOs and the GPT-5.5 TODO are untouched, out of this task's zone).
  - APPENDIX table (`app:grounding-full`): replaced the old `0.526$^{\S}$`/`0.530$^{\S}$`
    cells with the clean `0.530`/`0.535` values. Removed the `$^{\S}$` marker from both
    cells and replaced the `$^{\S}$...pending clean recomputation` footnote sentence with
    one stating the values are the clean, live-label-check recomputation, and that the
    same clean values are reused in the main table since $P_{\mathrm{label}}$ has no
    gold-tier (`R_all` vs `R_term`) dependence — kept in plain academic English, no
    em-dashes, no semicolons.
  - Added a one-line `%` comment above the main table stating CI provenance (binomial
    95% CIs from matched/total counts in `sitelink-clean-full-metrics.json`, cross-checked
    against `python-pro-ner-wikidata-table-c-extraction.md`).
- `docs/paper/paper-state.md` — updated the Table C status paragraph (owner-locked format
  bullet) and the "Done" bullet: fill status now reads 2/6 rows FULLY filled (R_doc +
  P_label) for Gemini/DeepSeek, with the clean P_label values and CIs spelled out and a
  link to the source JSON and the replay report; remaining 4 rows pending — 3 local
  `sr004` rows, and the GPT row where the `gpt-5.4` fallback grounding run is in progress
  (pointed at `docs/reports/ml-engineer-grounding-run-gpt54.md`, read but not modified).
- This report.

## Decisions & rationale

- **Reused the existing R_doc cell CI style** (`{\scriptsize[.xxx--.xxx]}`) for the new
  P_label cells in the main table for visual consistency within the same row/column
  family, rather than pushing CIs to a footnote — matches the instruction's stated
  preference when R_doc cells already carry bracketed CIs (they do).
- **Applied the same clean P_label values to both the main table (R_term tier) and the
  appendix table (R_all/T0 tier)**, per the task's explicit instruction that precision has
  no GT-tier dependence — added one short sentence to the appendix caption to make that
  reasoning legible in the paper itself, not just in this report.
- **Did not touch the GPT-5.5 row or its TODO comment** in either table, nor the three
  `sr004` TODOs — those are unrelated pending rows outside this task's zone (confirmed
  `gpt-5.4` run is still in progress per `docs/reports/ml-engineer-grounding-run-gpt54.md`,
  a live agent's file, read-only).
- **Left `$^{\dagger}$` (deepseek paragraph-loss footnote) untouched** — unrelated to
  P_label, still valid.

## Open questions

- None blocking. The appendix footnote sentence is intentionally short per the
  instruction ("one短 sentence only if the footnote needs it") — if the owner wants more
  detail (e.g. citing the exact matched/total counts in-paper), that's a follow-up, not
  done here to avoid over-filling the caption.

## NOT done

- Did not fill any of the 4 remaining pending rows (3 local `sr004`, GPT-5.5/gpt-5.4) —
  out of scope, those numbers don't exist yet.
- Did not touch `reports/bouquet/**`, `reports/terminology/**`, or
  `docs/reports/ml-engineer-grounding-run-gpt54.md` — confirmed via `git status` before
  staging; these belong to concurrently running agents in the shared worktree.
- Did not modify `docs/reports/python-pro-sitelink-clean-replay.md` or
  `docs/experiments/2026-07-05-model-comparison/sitelink-clean-full-metrics.json` — read
  only, as instructed (ground truth, not part of the edit zone).

## Verified code↔doc pairs

| Fact | Source of truth | Doc location |
|---|---|---|
| Gemini clean P_label 0.5304 [0.5206–0.5401], 5340/10068 | `sitelink-clean-full-metrics.json` (`p_label_p3ex`) | `table-c-grounding.tex` main + appendix tables |
| DeepSeek clean P_label 0.5346 [0.5238–0.5453], 4409/8248 | `sitelink-clean-full-metrics.json` (`p_label_p3ex`) | `table-c-grounding.tex` main + appendix tables |
| P_label has no GT-tier dependence (main table R_term vs appendix R_all) | `python-pro-sitelink-clean-replay.md` task framing + owner instruction | `table-c-grounding.tex` appendix caption sentence |
| GPT row status: `gpt-5.4` fallback run in progress | `docs/reports/ml-engineer-grounding-run-gpt54.md` (status: IN PROGRESS) | `docs/paper/paper-state.md` Table C fill-status bullet |
| Table C fill status 2/6 rows fully filled | this task's own edits | `docs/paper/paper-state.md` (two bullets updated) |
