# docs-keeper report — Table A judge rows fill (gemini flash-lite, opus, gpt-5.5)

## Scope

Diff zone: `docs/paper/table-a-judges.tex` (skeleton added in commit `ef98e33`) and
`docs/paper/paper-state.md` (Table A section), branch `claude/ner-translation-config-b0ozsc`.
Data sources read: `reports/bouquet/judges/gemini-3.1-flash-lite/stats.json`,
`reports/bouquet/judges/claude-opus-4.8/stats.json`, `reports/bouquet/judges/gpt-5.5/stats.json`.
Shared worktree — staged only the two target files, did not touch `reports/**`,
`src/**`, or `docs/reports/ml-engineer-grounding-run-gpt54.md` (other live agents' files
present as untracked/modified in the working tree, left untouched).

## Files changed

- `docs/paper/table-a-judges.tex` — filled 3 of 8 rows with real numbers, added a new
  `Gemini-3.1-Flash-Lite (reas. on)` row (slug `gemini-3.1-flash-lite-think`) since the
  owner's status list calls it out as its own tracked run, marked `---` on all
  not-yet-filled rows/cells with `%` TODO comments explaining status, and rewrote the
  caption (removed em-dashes/semicolons, added the 198x4x3=2376-calls-per-judge count,
  `v1_core3` prompt-identity statement, `T=0` for locals, provider-default effort
  disclosure for frontier judges).
- `docs/paper/paper-state.md` — added a "Table A fill status" summary block (3 DONE /
  2 PARTIAL / 3 pending, with commit citations) directly above the existing "Table A —
  LLM-as-a-judge, 7-judge lineup" section it complements.

## Decisions & rationale

1. **No skeleton relocation needed.** `docs/paper/sections/` exists but only holds
   `3-1-wikipedia-dataset.tex` and `table-c-grounding.tex`; `table-a-judges.tex` is still
   at its original `docs/paper/` path from `ef98e33` — verified via `git log --follow`.
2. **Kept the skeleton's exact column structure** (mean x3, rho-vs-MetricX x3,
   rho-vs-CometKiwi x3, single Ties% column) — did not add per-criterion tie-rate
   columns or a 4th metric family even though the stats.json has more granularity
   (metricx_qe is available but the skeleton only has one MetricX column, matching the
   caption's MetricX-24 reference-based framing, so I used `metricx_ref`, not
   `metricx_qe`). Per-instructions ("if the skeleton has fewer columns... leave for the
   appendix"), `metricx_qe` numbers were not added anywhere in this diff.
3. **No gemini-3.1-pro replacement needed** — grepped the skeleton, it already reads
   `Gemini-3.1-Flash-Lite` (the swap happened in `ef98e33` itself), nothing to fix.
4. **Aggregation method**: each filled cell is a simple unweighted mean over the 4
   BOUQUET systems (qwen-27b-bouquet, qwen-27b-bouquet-refined, translate-gemma-bouquet,
   translate-gemma-bouquet-refined), per-criterion, computed directly from
   `stats.json`. The single "Ties, %" column is the unweighted mean of
   `tie_rate_9_10` across all 4 systems x 3 criteria (12 values) — the skeleton has no
   per-criterion tie columns, so this is the only value that fits the existing cell.
5. **New `gemini-3.1-flash-lite-think` row**: the task's status list treats it as a
   distinctly tracked (partial) run separate from the reasoning-off row already in the
   skeleton, so I added it as a real table row (not commented out, unlike the
   pre-existing "sensitivity row" for the old Danil-verbatim Qwen config, which is a
   genuinely optional/deprioritized variant) — marked entirely `---` with a `%` TODO
   comment citing the HTTP 503 outage and the 797/2376 partial count. This is an
   additive change beyond the skeleton's original 7 data rows; flagging it explicitly
   since "extend minimally where statuses demand" was the given license and this is the
   only place I used it.
6. **GPT-5.5's 2375/2376 disclosure**: added as a `%` comment above its row (not a table
   footnote, since the skeleton has no footnote apparatus) noting the deterministic
   model-output JSON bug drops n to 197 for one cell (translate-gemma-bouquet-refined,
   fluency) — the aggregate mean/rho in that row is a mean over the available calls,
   consistent with how `stats.json` itself reports `n:197` only for that one leaf.
7. **Caption rewrite constraints**: removed all three em-dash uses (`---`) and the one
   semicolon-joined clause from the prior caption text, per the academic-English/no-em-
   dash/no-semicolon instruction; kept the MetricX lower-is-better explanation and the
   Ties definition, since those are facts the reader needs to interpret the numbers.

## Open questions

- Whether `gemini-3.1-flash-lite-think` should ultimately be a full 8th row in the main
  table or move to the appendix as a sensitivity variant (like the retained
  Qwen3.6-27B-verbatim commented row) is an owner call once the run completes — flagged
  here, not decided unilaterally.
- The paper-state.md "Table A protocol" section below the new summary block still lists
  the lineup as "7-judge"; I did not renumber it to 8 (including the -think variant)
  since the owner's own framing in the task counts only the 7 core judges — the -think
  row is additive tracking, not a lineup change. If the owner intends 8, that section's
  header needs a follow-up edit (out of this diff's stated scope).

## NOT done (explicit)

- Did not fill DeepSeek-V4-Flash, the 3 local judges (Qwen3.6-27B, Qwen3-4B-Instruct,
  Gemma-3-27B-it), or the Gemini-3.1-Flash-Lite reasoning-on row — all still pending per
  the task's own status list (marked `---` + TODO as instructed).
- Did not touch `docs/paper/sections/table-c-grounding.tex`, `3-1-wikipedia-dataset.tex`,
  `docs/reports/ml-engineer-grounding-run-gpt54.md`, or anything under `reports/**` /
  `src/**` — out of the stated selective-staging zone.
- Did not renumber or otherwise edit the "Table A protocol" / "7-judge lineup" narrative
  section further down `paper-state.md` beyond the new summary block prepended to it —
  see Open questions.
- Did not run a LaTeX compile check (no local TeX toolchain invoked); table syntax was
  hand-verified against the pre-existing skeleton's column/row grammar only.

## Verified code<->doc pairs

| Doc claim | Source verified |
|---|---|
| Gemini-3.1-Flash-Lite row (mean/rho/ties) | `reports/bouquet/judges/gemini-3.1-flash-lite/stats.json` (4-system average, computed) |
| Claude Opus 4.8 row (mean/rho/ties) | `reports/bouquet/judges/claude-opus-4.8/stats.json` (4-system average, computed) |
| GPT-5.5 row (mean/rho/ties), 2375/2376 note | `reports/bouquet/judges/gpt-5.5/stats.json` (4-system average, computed; n=197 leaf confirmed for translate-gemma-bouquet-refined/fluency) |
| `ced45c3` = gemini-3.1-flash-lite DONE commit | `git cat-file -t ced45c3` -> commit, exists in repo |
| `6a90dec` = claude-opus-4.8 DONE commit | `git cat-file -t 6a90dec` -> commit, exists in repo |
| `336f272` = gpt-5.5 DONE commit | `git log --oneline -3 336f272` -> "feat(eval): BOUQUET judge run — gpt-5.5 (2375/2376 calls)" |
| `501c394`, `85e5435` = deepseek-v4-flash park commits | `git cat-file -t` both -> commit, exist in repo |
| `0c48124` = sr004 runbook commit | `git cat-file -t 0c48124` -> commit, exists in repo |
| `table-a-judges.tex` still at `docs/paper/` (not moved to `sections/`) | `git log --oneline --follow -- docs/paper/table-a-judges.tex` shows only `ef98e33`; `docs/paper/sections/` listing does not include it |
| No `gemini-3.1-pro` leftovers in the tex | `grep -n "gemini-3.1-pro\|Gemini-3.1-Pro" docs/paper/table-a-judges.tex` -> no matches |
