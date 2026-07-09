# docs-keeper report — Table C GPT-5.4 P_label cell fill

## Scope

Selective staging task on the shared worktree `claude/ner-translation-config-b0ozsc`.
Source of truth: commit `19c7389` (`reports/terminology/wiki-eval/openai--gpt-5.4--auto/111/2026-07-09T01-10-47Z/metrics.99of100.json`,
`precision.p3_ex`) and `docs/reports/python-pro-p-label-gpt54-grounding-run.md`. Verified
number: gpt-5.4 clean P_label = **0.5362** (3773/7037, Wilson 95% CI [0.5245, 0.5478]),
computed on the frozen 99/100 snapshot; 3 transient `maxlag` lookups conservatively
counted as `False`.

Task: fill the last empty cell of Table C — GPT-5.4 P_label — in the paper (main table +
appendix grid), the paper-state index, and both HTML overnight reports (repo copy +
Claude-Artifact scratchpad copy), keeping the two HTML files content-identical. Strictly
selective staging: `reports/bouquet/**`, `scripts/**`, `src/**` untouched.

## Files changed

- [docs/paper/sections/table-c-grounding.tex](../paper/sections/table-c-grounding.tex)
  — main table: GPT-5.4 row `P_label` cell filled `0.536 {\scriptsize[.525--.548]}`
  (matches the house style of the Gemini/DeepSeek cells exactly — value + Wilson CI in
  `\scriptsize`). Removed the `% P_label pending: a Wikidata maxlag replay pass, not yet
  computed.` TODO comment, replaced with a filled-source comment citing the commit and
  the matched/total/CI. Checked the `\ddagger` footnote text in both the main and
  appendix captions — neither actually contained a "P_label pending" clause (only the
  removed inline `%`-comment did), so no caption trim was needed.
  Appendix grid: GPT-5.4 row's trailing `P_{\mathrm{label}}` column changed from `---`
  to `0.536` (plain value, no CI — matches the Gemini `0.530`/DeepSeek `0.535` cells in
  that table, which also carry no CI per that table's own convention). Verified the
  appendix column semantics first: the appendix caption already states "$P_{\mathrm{label}}$
  values are the clean, sitelink-off recomputation with live label checks; since
  $P_{\mathrm{label}}$ has no gold-tier dependence, the same clean values are used here
  and in the main table" — so `0.536` is the correct value to carry over unchanged (no
  T0/R_all-tier adjustment applies to P_label, unlike R_doc, which legitimately differs
  between the two tables because it IS tier-dependent, e.g. the appendix's own GPT-5.4
  R_doc cell shows `0.536 [.525--.547]`, a T0-tier figure distinct from the main table's
  R_term-tier `0.583` — a coincidental near-collision in digits with the unrelated
  P_label value, not an error, confirmed by re-deriving both from their respective
  source JSONs).
- [docs/paper/paper-state.md](../paper/paper-state.md) — Table C status line updated:
  "3/6 rows FULLY filled (Gemini, DeepSeek, GPT-5.4) with both $R_{\mathrm{doc}}$ and
  $P_{\mathrm{label}}$; remaining 3 pending local sr004 runs" replaces the previous
  "2/6 FULLY filled... GPT-5.4 has $R_{\mathrm{doc}}$ only... $P_{\mathrm{label}}$
  pending" wording, in both the "Owner-locked main-table format" paragraph and the
  "Done" experiments-mapping paragraph. Added the GPT-5.4 P_label value + CI + source
  commits (`5546459` R_doc, `19c7389` P_label) to both paragraphs.
- [docs/reports/html/overnight-mission-2026-07-09.html](html/overnight-mission-2026-07-09.html)
  and the Claude-Artifact scratchpad copy (outside the repo, edited only, not committed) —
  identical content changes:
  - Lead ("Главное"): "все три готовые строки Table C ... P_label добит отдельным
    ретраем ... (0.536 [.525–.548], коммит `19c7389`)" replaces the "gpt-5.4 P_label
    ждёт ретрая" wording.
  - Radar legend table: GPT-5.4 row badge flipped from `badge--warn` ("R_doc DONE,
    P_label PENDING") to `badge--pass` ("DONE").
  - Table C section: GPT-5.4 row's P_label cell filled `0.536 [.525–.548] (3773/7037)`,
    status badge flipped to `DONE`. The trade-off paragraph rewritten from a 2-model
    (gemini/deepseek) comparison to a 3-model one, adding the requested observation
    sentence: P_label is near-constant across all three models (0.530/0.535/0.536) over
    a recall range of 0.583–0.735, implying label-precision is governed by the Wikidata
    candidate ladder rather than by which model does the extraction. The GPT-5.4 caveats
    paragraph rewritten: "P_label не вычислен — прерван" → "P_label добит отдельным
    ретраем в 08:18Z ... 3773/7037 = 0.5362, Wilson 95% CI [.5245, .5478], 1771 сетевых
    вызовов, 3 транзиентных сбоя (0.19%)".
  - Evidence section: gpt-5.4 evidence-item extended with the P_label value and a
    pointer to `docs/reports/python-pro-p-label-gpt54-grounding-run.md` commit
    `19c7389`.
  - Next-steps section: the "Ретрай P_label для gpt-5.4, как только maxlag спадёт" item
    replaced — that retry already happened — with the one genuinely remaining GPT-5.4
    gap, resuming article "Яффа" (99/100 → 100/100 coverage), phrased so it doesn't
    imply R_doc/P_label are still open.
  - Verified byte-for-byte: the `<div class="wrap">...</div>` content block (repo file
    lines 142–423) and the artifact's equivalent block (lines 136–411) diff to zero
    after the edits (`diff` command run, empty output). The two files remain
    intentionally non-identical outside that block (repo file is a full standalone
    `<html>` document; the scratchpad copy is a Claude-Artifact fragment scoped under
    `.report-root`, per the pre-existing convention from the prior report-generator
    pass) — this mirrors the state already found before this task (confirmed by diffing
    both files before any edits: differences were 100% confined to the CSS/wrapper
    boilerplate, 0% in content).

## Verified code↔doc pairs

| Doc claim | Code/data source | Verified |
|---|---|---|
| GPT-5.4 P_label = 0.536 [.525–.548] (3773/7037) | `reports/terminology/wiki-eval/openai--gpt-5.4--auto/111/2026-07-09T01-10-47Z/metrics.99of100.json` → `precision.p3_ex` = `{matched: 3773, total: 7037, value: 0.5362, ci_lo: 0.5245, ci_hi: 0.5478}` | Yes — read directly via `python3 -c` before writing any cell |
| GPT-5.4 R_doc = 0.583 [.572–.594] (unchanged, not touched this task) | same run dir, prior commit `5546459` (out of scope, re-verified as still correct/untouched) | Yes — file diff shows only the `precision` object touched by this task's commit, R_doc cell in `.tex`/`.md`/`.html` left byte-identical |
| Appendix GPT-5.4 R_doc cell 0.536 [.525–.547] is a *different* metric (T0/R_all tier) from the main-table 0.583 (R_term tier), not a duplicate/mistake | `docs/paper/sections/table-c-grounding.tex` caption: "$R_{\mathrm{all}}$/T0 tier"; Gemini/DeepSeek rows show the same tier-divergence pattern (0.684 vs 0.735, 0.609 vs 0.657) | Yes — cross-checked against the two other rows' known tier deltas before concluding the digit-collision with P_label 0.536 was coincidental |
| Appendix P_label carries no CI, plain value only | Existing Gemini (`0.530`) / DeepSeek (`0.535`) appendix cells, same table | Yes — grep'd the table before writing `0.536` in the same bare style |
| Two HTML reports content-identical in the shared `<div class="wrap">` body | `diff` of the extracted line ranges post-edit | Yes — empty diff, confirmed inline above |

## Decisions & rationale

- Kept the appendix P_label cell as a bare number (`0.536`), matching the two existing
  filled cells in that column rather than importing the main table's CI-bearing format —
  single source of truth for the *value*, format follows the column's own established
  convention, not the main table's.
- Did not touch the `\ddagger` footnote prose in either table — re-read both captions
  closely and neither one actually asserted "P_label pending" (only a `%`-comment did,
  which is now updated); inventing a trim where none was needed would have been a
  spurious edit outside the instructed change.
- Rewrote the overnight-mission HTML's Table C narrative paragraph rather than just the
  table cell, because the paragraph's own prose ("gemini выше по recall... precision
  0.530 vs 0.535") was now stale given a 3rd filled row and the requested
  cross-model-constancy observation — leaving the cell updated but the prose contradicting
  it (still describing a 2-model comparison) would have been a fresh doc-parity gap
  introduced by this task itself.

## Open questions

- None blocking. The appendix's `\dagger`/`\ddagger` footnote wording was reviewed but
  not touched (no drift found there).

## NOT done (explicit)

- **Article "Яффа" (100th article) was not grounded** — out of scope for this task
  (P_label cell fill only); flagged in the HTML next-steps section as the one remaining
  GPT-5.4 gap.
- **The per-`resolved_by`-slice P3 cells in `metrics.99of100.json` remain stub-based**
  (unrelated prior decision, documented in `python-pro-p-label-gpt54-grounding-run.md`,
  not re-litigated here).
- **No push executed by this agent directly in this report step** — done as part of the
  final commit step below, with retry-on-conflict per instructions.
- **Out-of-zone drift**: none found. Scanned `reports/bouquet/**`, `scripts/**`, `src/**`
  per the selective-staging boundary and confirmed via `git status` that no other
  in-progress agent's paths were touched by this task's edits.
