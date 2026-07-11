# docs-keeper report — Table A judge lineup update (2026-07-08)

## Scope

Diff zone: two owner decisions from the 2026-07-08 session on branch
`claude/ner-translation-config-b0ozsc`, scoped to `docs/paper/`:

1. Update `docs/paper/paper-state.md` Table A judge lineup/protocol —
   swap `gemini-3.1-pro` → `gemini-3.1-flash-lite`, lock
   `deepseek-v4-flash` reasoning ON, disclose the Opus reasoning-drop
   quirk and GPT-5.5 default-effort behavior, add probe cost estimates.
2. Create `docs/paper/table-a-judges.tex` — a verbatim LaTeX skeleton
   for the paper (owner-authored content, pasted as-is, not generated
   from analysis).

No other files were in scope. Per boundaries, drift outside this zone
is reported, not edited.

## Files changed

- `docs/paper/paper-state.md` — edited (34 insertions / 7 deletions in
  the diff). Three edit sites:
  - "Table A — LLM-as-a-judge, 7-judge lineup" block: `gemini-3.1-pro`
    → `gemini-3.1-flash-lite`, with the model-overlap-across-tables
    rationale linked to the existing §4 note in the same file.
  - "Table A protocol" block: deepseek reasoning OFF → ON (marked
    superseded, reason cited — the probe found `reasoning.enabled:false`
    didn't actually suppress thinking, so ON is now the honest, locked
    setting); GPT-5.5/Opus/Gemini-flash-lite config disclosed inline
    with the Opus quirk; cost-estimate paragraph added, linking to
    `docs/experiments/2026-07-08-judge-probe/probe-results.md` (single
    source of truth for the probe numbers — not copied, just cited).
  - "Done" section, deepseek smoke bullet: appended a one-line
    "Superseded 2026-07-08" pointer to the new protocol, so the
    historical record and the current lock don't silently contradict
    each other in the same doc.
- `docs/paper/table-a-judges.tex` — new file, exact verbatim LaTeX
  skeleton as specified by the task (owner will paste into the paper;
  not modified, not fact-checked against results since it has no
  numbers to check — all cells are `XX` placeholders).

Commit: `ef98e33` — `docs(paper): swap Gemini judge to flash-lite, lock
deepseek reasoning-on; add Table A LaTeX skeleton`. Pushed to
`claude/ner-translation-config-b0ozsc` (fast-forward, no rebase
needed).

## Decisions & rationale

- **Single source of truth kept intact**: cost numbers live in
  `docs/experiments/2026-07-08-judge-probe/probe-results.md`;
  `paper-state.md` links to it and restates only the three headline
  numbers the owner explicitly asked to note (opus/gpt-5.5/deepseek),
  not the full probe table (Gemini pro/flash-lite pricing, latency,
  token breakdowns) — that stays in the probe report only.
- **Did not touch `table-a-judges.tex` content** beyond pasting it
  verbatim, per the task's explicit "keep it verbatim" instruction —
  this is an L3/appendix-adjacent artifact the owner will hand-edit in
  the paper, not a generated doc this pass should shape.
- **Left the "old Danil-verbatim qwen3.6-27b run... sensitivity
  footnote" wording untouched** — it's an unrelated fact (a different
  run/config) that happens to sit in the same paragraph as the edits;
  no drift found there, so no edit made (avoids scope creep into
  adjacent prose).
- **Superseded-note style over silent overwrite**: the earlier
  "reasoning OFF mandatory" line in "Done" was marked superseded
  in-place rather than deleted, since it is a historical record of
  what the smoke test actually found (still true as a *finding*, just
  no longer the *locked protocol*) — deleting it would lose the
  provenance of why deepseek's reasoning behavior was ever in question.
- **No new L4 doc created**: Table A protocol is documented at L3
  paper-state granularity already; nothing in this diff introduced a
  new entity/stage warranting its own L4 file, and `table-a-judges.tex`
  is a paper artifact, not a docs-layer node.
- **Report placement**: `docs/reports/` per the project's reporting
  convention, filename slug reflects the concrete change (judge
  lineup), English body per doc-language convention for
  `docs/reports/` under `docs/` (owner-facing reply to the dispatching
  agent was already delivered in Russian in the prior turn; this file
  is the docs-keeper artifact itself).

## Open questions

- The probe report (`probe-results.md`) flags an **open question to
  the owner**: which prompt variant goes to prod re-scoring — `v1`
  (5-criteria, pick 3 of 5) or `universal` (exactly 3 criteria,
  ~2.3× longer) — this materially changes the Gemini-flash-lite cost
  estimate once it lands (the `v1_core3` choice already recorded in
  `paper-state.md` answers "which 3 of `v1`", but doesn't resolve
  `v1` vs `universal` as the family). Not resolved in this pass — it's
  outside the two tasks given and belongs to the owner/orchestrator,
  not to a docs-parity pass.
- Exact CloseRouter router ID for the Gemini swap
  (`google/gemini-3.1-flash-lite` vs `-preview`) is explicitly still
  pending a smoke test per the task instructions — recorded as
  open/TBD in `paper-state.md` rather than guessed.

## NOT done (explicit)

- No L1 (`docs/README.md`) or L2 (`docs/subsystems/`) index edits —
  `docs/paper/paper-state.md` is not currently linked from either
  index (checked: no reference to `docs/paper/` found in
  `docs/README.md` or `docs/subsystems/`), so there was no existing
  index entry to update and adding one is outside this diff's scope
  (would be a separate indexing task, not implied by "update Table A
  judge lineup").
- Did not audit `docs/paper/` for other drift beyond the two named
  edit sites — no broader sweep of the paper-state document was
  performed (out of the stated diff zone).
- Did not touch the untracked `reports/bouquet/judges/{claude-opus-4.8,
  gemini-3.1-pro,gpt-5.5}/` directories seen in `git status` — they
  are not part of this diff and were left untracked/uncommitted, as
  reported to the dispatching agent already.
- No LEGACY banner applied anywhere — the swapped-out
  `gemini-3.1-pro` lineup entry is a superseded *inline value* inside
  a living document (edited in place), not a standalone legacy doc,
  so the LEGACY-banner mechanism doesn't apply here.

## Verified code↔doc pairs

Not applicable in the strict code↔doc sense — this task's zone is
doc↔doc / doc↔decision parity (paper-state.md reflecting the owner's
2026-07-08 protocol decisions), not code↔doc. Verified pairs:

| Fact | Source | Doc location |
|---|---|---|
| Gemini judge model swap + exact-ID uncertainty | Task instructions (owner decision) + `probe-results.md` `-preview` suffix precedent | `docs/paper/paper-state.md` Table A lineup |
| deepseek reasoning ON lock + why OFF didn't work | `probe-results.md` "DeepSeek V4 Flash" nuance section | `docs/paper/paper-state.md` Table A protocol |
| Opus reasoning-drop quirk (0 tokens, 3 param forms tried) | `probe-results.md` "Claude Opus 4.8" nuance section | `docs/paper/paper-state.md` Table A protocol |
| GPT-5.5 default-effort reasoning (110–292 tokens) | `probe-results.md` "GPT-5.5" nuance section | `docs/paper/paper-state.md` Table A protocol |
| Per-judge cost estimates (opus $2.3 / gpt-5.5 $1.3 / deepseek $1.5) | `probe-results.md` "Итоговая сводка" table | `docs/paper/paper-state.md` Table A protocol cost note |
| gemini-3.1-pro cost ~$9–14, dropped partly on cost | `probe-results.md` "Главное" + summary table | `docs/paper/paper-state.md` Table A protocol cost note |
| Model-overlap-across-tables rationale | `docs/paper/paper-state.md` §4 pre-existing note (line "Maximize model overlap across tables") | `docs/paper/paper-state.md` Table A lineup (linked, not duplicated) |
