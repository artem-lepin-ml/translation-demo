# frontend-developer report — align Glossary/TermPopover UI copy to the paper's 3-state vocabulary

## Scope

Worktree: `/Users/a1111/Projects/Work/worktrees/emnlp-demo-sprint`, branch
`feat/emnlp-demo-sprint`. Frontend lane only (`frontend/src/demo/**`), no commit/push.

Align UI copy in the demo's terminology/grounding surfaces with the EMNLP "Glossa-MT"
paper's canonical §2.1 / Figure 1 vocabulary — three confidence states:
**unambiguous** (exact Wikidata label/alias match, no LLM call), **context-resolved**
(multiple candidates, LLM selects by paragraph context, shown with justification),
**unresolved** (no candidate retrieved or LLM abstains, source form preserved, span
flagged as ungrounded). Reviewers reading the paper must meet the same terms in the UI.

## Files changed

- `frontend/src/demo/variant-a/TermPopover.tsx` — `difficultyLabel` map renamed to the
  paper's three states (kept the emoji-dot prefix convention):
  - green: `🟢 Confirmed (Wikidata)` → `🟢 Unambiguous (exact label match)`
  - yellow: `🟡 Ambiguous (multiple senses)` → `🟡 Context-resolved (AI-disambiguated)`
  - red: `🔴 Not found in Wikidata` → `🔴 Unresolved (not grounded)`
- `frontend/src/demo/variant-a/glossary-grouping.ts` — `resolveBadge`/`llmBadgeLabel`
  badge labels renamed (every call site, all switch branches and the heuristic
  fallback branch):
  - `◆ label match` → `◆ unambiguous · label match` (2 call sites)
  - `◇ resolved by AI` → `◇ context-resolved · AI`; `◇ AI · <model>` → `◇ context-resolved
    · <model>` (in `llmBadgeLabel`)
  - `○ no candidates` → `○ unresolved · no candidates` (4 call sites)
  - `◇ LLM rejected all` → `◇ unresolved · AI abstained` (2 call sites)
  - `◇ ambiguous · N candidates` → `◇ unresolved · N candidates` (2 call sites)
  - `◆ grounded` (rule-2 degraded path, empty `trace_json` + grounded qid — legacy/seed
    data only) intentionally **left unchanged**: not in the task's rename list, and it
    isn't one of the paper's three named states (it's a "no path info" fallback for
    rows with no trace at all).
  - Doc comments (`summarizeGroups`) updated to reference the new vocabulary; the
    `GlossarySummary` interface field names (`deterministic`/`llm`/`notGrounded`) are
    internal API, intentionally left unchanged — only rendered copy follows the paper.
- `frontend/src/demo/variant-a/__tests__/glossary-grouping.test.ts` — every
  `resolveBadge` assertion (`toEqual`/`toBe`/`toMatch` on badge labels) and the regex
  in the "ambiguous badge with candidate count" tests updated to the new label text;
  a few test titles that quoted the old label text updated for accuracy. No test
  logic/structure changed, only expected strings.
- `frontend/src/demo/variant-a/GlossaryTab.tsx`:
  - Trace stepper: step 4 header text (`{i+1} · {KEY}`) — added a
    `STEP_HEADER_LABEL` map so only the **rendered header text** changes
    (`'DECISION'` → `'DISAMBIGUATION'`, matching the paper §2.1 step-iii name);
    the underlying `StepKey`/`stepPresentation`/trace-shape `'decision'` identifier is
    **unchanged** (renaming that would ripple into `TraceJson`'s nested-shape field
    names and the `resolved_by`/tone-gating switch — out of scope, mechanical
    identifier, not user-facing copy).
  - Judge-decision quote block: added a small muted `"Justification"` label above the
    quote (plain text, no box/accent, per Figure 1's "shown alongside the model's
    justification"), with matching CSS.
  - Sweep-driven copy also updated for consistency with the same three terms (found by
    grepping the exact strings named in the task, item 5): `pathHeading()`'s four
    "Grounding path — …" strings, the summary-line counters (`resolved
    deterministically: N · via LLM: N · not grounded: N` → `unambiguous: N ·
    context-resolved: N · unresolved: N`), and the below-table legend paragraph
    (all five glyph/label combinations rewritten to match the new `resolveBadge`
    label text verbatim).
- `frontend/src/demo/variant-a/variant-a.css` — new `.va-gl-judge-label` rule (10px,
  uppercase, letter-spaced, `--va-text-dim`), styled to match the pre-existing
  `.va-gl-lang` micro-label convention; no box/border/accent per the task's "plain
  text label" instruction.

## Decisions & rationale

- **`StepKey`/`resolved_by` identifiers kept as `'decision'`.** The task asked to
  rename the *header* text users see, not the wire/trace vocabulary
  (`trace_json.resolved_by` values like `llm_disambiguation`, `no_candidates` are a
  backend contract — renaming them is out of scope for a frontend-only copy task and
  would touch `TraceJson`'s doc-comments about the real backend shape). Solved with a
  presentation-only lookup map (`STEP_HEADER_LABEL`) so the display text and the
  internal key can diverge cleanly.
- **`◆ grounded` left as-is.** It's reachable only when `trace_json` is empty/absent
  (today's seed-data legacy path per the code's own docstring) — not one of the task's
  five explicit renames, and not one of the paper's three named states (it carries no
  path/justification info at all, unlike a genuine "unambiguous" resolution). Renaming
  it wasn't requested and would be scope creep on a mechanical copy-alignment task.
  Flagged here in case the owner wants it aligned too.
- **`GlossarySummary` field names unchanged, only rendered text changed.** Renaming
  `deterministic`/`llm`/`notGrounded` to e.g. `unambiguous`/`contextResolved`/
  `unresolved` would touch the interface, the tests' `toEqual({...})` shape assertions,
  and any other reader of `GlossarySummary` — broader than a UI-copy task. The task's
  literal ask ("summary-line counters … N") is about the *rendered* string, which is
  the only thing changed.
- **Legend/`pathHeading` prose rewritten, not just literal-matched.** The task's step 5
  explicitly named `"resolved deterministically"`/`"via LLM:"`/`"not grounded"` as
  greppable leftovers to sweep — found 3 more occurrences beyond items 1-4 (the
  `pathHeading()` panel heading and the below-table legend paragraph) and aligned all
  of them to the same `resolveBadge` label vocabulary so nothing readable in the tab
  still uses the old terms.

## Verification (all ran, all green)

- `npx vitest run` → **21 test files passed (21), 378 tests passed (378)**, 0 failures.
- `npx tsc -b` → clean, no output, no errors.
- `npx vite build` → succeeded (`dist/index.html`, `dist/assets/index-*.css` 44.67 kB,
  `dist/assets/index-*.js` 868.46 kB; only the pre-existing >500kB chunk-size advisory
  warning, unrelated to this change).

## Open questions

- Whether `◆ grounded` (legacy empty-trace path) should also be renamed to fit the
  paper's three-state vocabulary — deferred, see rationale above.
- Whether `GlossarySummary`'s internal field names should eventually be renamed to
  match the new vocabulary (`unambiguous`/`contextResolved`/`unresolved`) for
  code-readability — out of scope for a copy-only task; flagged for a future pass if
  the owner wants full-stack terminology parity, not just the rendered UI.

## NOT done (explicit)

- Did not touch `docs/subsystems/webapp-ui-design.md` or any other doc describing the
  Glossary UI copy — task scope was `frontend/src/demo/**` only; if any doc quotes the
  old badge/legend strings verbatim it will need a follow-up doc-parity pass (not
  checked here, out of the stated frontend-only lane).
- Did not run the e2e/browser suite (task only asked for vitest/tsc/vite build) —
  no screenshot verification of the rendered stepper/legend/popover.
- Did not touch any file outside `frontend/src/demo/**`; the worktree already had
  unrelated pending changes in `docs/subsystems/webapp.md`,
  `src/palimpsest/webapp/migrate.py`, `src/palimpsest/webapp/model_matrix.py` (visible
  in `git status` before I started) — left untouched, not part of this task's scope.
