# Report — docs-keeper: rewrite Table C to R_doc+P_label main format

## Scope

Task: rewrite `docs/paper/sections/table-c-grounding.tex` on branch
`claude/ner-translation-config-b0ozsc` to the owner-locked final format (main table:
Model | R_doc | P_label, 6-row canonical order, Opus dropped; full 6-metric grid moved to
an appendix table), and update `docs/paper/paper-state.md`'s Table C section to match.
Shared worktree — staged selectively, did not touch the many unrelated in-flight files
already modified/untracked there (bouquet judges, sitelink scripts, gpt-5.4 run dir, etc).

## Files changed

- `docs/paper/sections/table-c-grounding.tex` — rewritten. Main `table` env (2-column,
  `tab:grounding-results`) with the canonical 6-row order (Qwen3-4B-Instruct,
  Gemma-3-27B-it, Qwen3.6-27B, Gemini-3.1-Flash-Lite, DeepSeek-V4-Flash, GPT-5.5), no Opus
  row. Filled cells: Gemini-3.1-Flash-Lite R_doc 0.735 [.724-.745] (5269/7174),
  DeepSeek-V4-Flash R_doc 0.657 [.646-.668] (4716/7174) — both R_term tier (n=7174),
  sitelink-clean, verified against
  `docs/reports/python-pro-ner-wikidata-table-c-extraction.md` (0.7345/5269 and
  0.6574/4716 there, matching the task-provided rounded values and CIs). All other cells
  `---` with a `% TODO` comment per pending run. Caption states the R_term tier (n=7174),
  sitelink-signal-disabled replay (no circularity vs the gold annotation), and that
  P_label is a lower bound; academic English, no em-dashes, no semicolons. Old 6-metric
  table content (unchanged numbers) moved verbatim into a second `table*` env labeled
  `app:grounding-full`, with one added sentence on the main-table selection rationale
  (R_doc = most permissive recall rung, P_label = strictest precision rung).
- `docs/paper/paper-state.md` — two Table C passages (the "Evaluation restructuring" bullet
  and the "Done" bullet under NER+Wikidata grounding) updated to describe the new
  R_doc+P_label main format, the appendix move, and the current fill status: 2/6 R_doc rows
  filled (R_term-tier, sitelink-clean), P_label pending live recomputation for all rows
  including the two filled ones, 4 R_doc rows still pending (3 local sr004, GPT-5.5
  provider smoke / gpt-5.4 fallback).

## Decisions & rationale

- **Used the R_term tier (n=7174), not the R_all/T0 tier (n=7959)** for the main table, per
  explicit task instructions. This differs from the tier used in the old main table
  (which was R_all/T0, values 0.684/0.609) — the appendix now correctly labels its
  preserved numbers as R_all/T0 tier so the two tables aren't silently conflated under one
  tier assumption.
- **Verified the task-given R_doc numbers (0.735/0.657) against the extraction report**
  rather than trusting them blindly: extraction report's R_term-tier sitelink-clean values
  are 0.7345 (5269/7174) for gemini and 0.6574 (4716/7174) for deepseek — both round to the
  task-provided figures and match matched/total counts exactly. No discrepancy found for
  these two cells.
- **Did not touch the CI figures' provenance beyond the task's own numbers** — the
  extraction report doesn't print a separate Wilson CI for the R_term-tier clean variant
  (only point estimates + matched/total), so I used the CIs as given in the task
  instructions without independent recomputation. Flagging this as unverified-by-me in
  Open questions.
- **Kept the appendix table's numbers byte-identical to the pre-existing main table**
  (including the still-open `XX` placeholders and the `$^{\S}$`/`$^{\dagger}$` footnote
  markers) per the "preserve exactly, do not recompute" instruction — only moved it and
  renamed its `\label` is unchanged (`tab:grounding-results` stays on the main table; the
  appendix table gets the new `app:grounding-full` label, since the old label was on the
  content now duplicated conceptually into two tables and the main table needed the
  reference name for in-text citations).
- **P_label is `---` for every row in the main table**, including the two rows with a
  filled R_doc, because the task explicitly states "P_label live computation in progress
  for gemini+deepseek" — the appendix's `0.526$^{\S}$`/`0.530$^{\S}$` are a different tier
  (R_all/T0) and explicitly marked as pending clean recomputation themselves, so they
  cannot be reused as the main table's R_term-tier P_label without recomputation.

## Open questions

- The R_term-tier Wilson CIs (.724-.745 / .646-.668) used in the main table are as given
  in the task prompt; I could not find them independently reported with that exact
  precision in the extraction report (which gives point estimates + matched/total for the
  R_term-clean variant but not a re-derived CI for that specific slice). If these CIs came
  from a different/newer replay than the one the extraction report covers, worth a
  provenance comment in a follow-up commit.
- `docs/reports/python-pro-ner-wikidata-table-c-extraction.md` itself flags an unresolved
  named/term recall discrepancy and an unresolved "which variant is authoritative"
  question between `drafts/paper-section-en-final.md` and `paper-state.md`. Not in this
  task's scope (main-table R_doc/P_label only) — left exactly as flagged in that report,
  not re-litigated here.

## NOT done

- Did not recompute or independently re-derive any number — sourced only from the task
  prompt (cross-checked against the extraction report) and the pre-existing appendix
  content (preserved verbatim, not recomputed).
- Did not touch `drafts/paper-section-en-final.md` or any other draft file referencing
  Table C — out of the stated scope (`table-c-grounding.tex` + `paper-state.md` only).
- Did not stage or touch the many unrelated modified/untracked files present in this
  shared worktree (`configs/bouquet_judges.yaml`, `scripts/wiki_eval.py`,
  `reports/bouquet/judges/*`, `reports/terminology/wiki-eval/openai--gpt-5.4--auto/`,
  etc.) — selective `git add` on only the two files this task changed, plus this report.
- Did not run a LaTeX compile check (no local TeX toolchain available in this sandbox) —
  the tabular column counts (`lcc` main table 3 cols vs 3 `&`-separated fields per row,
  `lcccccc` appendix table 7 cols vs 7 fields per row) were checked by manual count only.
