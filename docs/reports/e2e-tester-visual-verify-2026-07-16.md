# e2e-tester report: tight visual-polish verification, prod glossa-mt.com — 2026-07-16

## Scope

Tight (~20 tool-call) read-only visual verification of a just-shipped visual-polish wave against LIVE PROD https://glossa-mt.com. 7 items requested by the caller: picker card dedup, upload-modal glyph removal, term-popover cleanup (Note row / Candidate senses naming / spacing / scroll), glossary badges + trace rendering + difficulty dots, Add-model params placeholder, revision-history row-count reduction, console error count. No data mutation permitted (no refine/evaluate/delete/save).

## Files changed

- Created `docs/reports/e2e/visual-verify-2026-07-16.md` (owner-facing report, Russian) — this is the primary deliverable.
- Created 15 screenshots under `docs/reports/e2e/shots/visual-verify/` (01–15, one file `03b-...` is a discarded/unused crop attempt, not referenced in the report). `15-popover-gap-fixed.png` was added in the re-check pass below.
- This file (internal report).

## Decisions & rationale

- Used a single named playwright-cli session (`-s=visual-verify`) against prod directly, no worktree app boot needed since target is a live URL.
- To reach a low-in-viewport term for popover-scroll testing (item 3d), I resized the browser viewport to 1280×550 to force real overflow, since the popover auto-repositions to stay on-screen at normal viewport height and never naturally overflows on a 1280×720 screen. Restored to 1280×720 immediately after.
- To select paragraph §4 (needed for the revision-history check, item 6), clicking the paragraph text itself does not change which paragraph the right-side inspector panel shows — the panel is bound to whichever `.va-para-row` has `class="selected"`. I clicked the paragraph's score-chip (`.va-score-chip` inside the §4 row) via `page.evaluate`, which did change the selection (confirmed via `classList.contains('selected')` check before/after). This is worth noting as a UX quirk but not a bug per se — clicking the score chip is a discoverable interaction pattern, just not the first thing I tried.
- Found and root-caused a genuine CSS bug in the term popover (item 3c not fully fixed): `.va-term-popover-label { flex: 0 0 80px; }` in `variant-a.css:1095-1098` is designed for row-mode label columns, but the "Disambiguating context" block in `TermPopover.tsx:159-160` switches to `flexDirection: 'column'`, so the flex-basis applies to height instead of width, forcing the label span to 80px tall for one line of text (~18px needed). Verified via `getComputedStyle` (height:80px, line-height:18px, margin/padding 0) and reproduced on two different terms (Вавилония, Гандаша). This is a real, code-traced finding, not a guess — logged as the report's main bug.
- Did not attempt to seed a second document to test a "legacy pre-strategy-field trace" (item 4b sub-check) — the only document available via the picker is the one that shipped with this wave (already fully re-indexed with the new trace format across all 91 terms). Escalation order per protocol: manifest doesn't apply here (no data-manifest read needed for a read-only visual smoke test against prod with a single pre-existing document); generating a second document would require an actual upload+translate+ground cycle, which violates the read-only constraint given for this run. Logged as an explicit coverage gap in the report rather than silently marking PASS.

## Open questions

- Whether the "not scored" intermediate rows in revision history (4 of them, between CURRENT and Best) are expected to collapse further, or whether "~6 rows" already accounts for them as-is — flagged to owner in the report's SUSPECTED section, not something I could resolve unilaterally without a manifest/spec reference for the exact expected row semantics.
- Whether any other prod document with a legacy (pre-strategy-field) grounding trace exists outside what the picker currently surfaces — could not confirm either way within the read-only scope.

## NOT done (explicit)

- Did not test Settings sections other than Model Registry (Translator/Judges/Grounding/Refiner) — out of the stated 7-item scope.
- Did not run any mutating flow (refine, evaluate, accept/dismiss issue, delete, save) — explicitly forbidden by the task.
- Did not verify mobile/narrow layout beyond the one deliberate viewport shrink used to force popover scroll (item 3d), restored immediately after.
- Did not audit this report myself — per the global CLAUDE.md loop, a Sonnet auditor pass over this e2e report is the next step owned by the orchestrator, not by this agent.

## Re-check (same session, after prod deploy of commit `5f20c3c`)

Coordinator deployed a fix (`.va-term-popover-label` changed from `flex: 0 0 80px` to `flex: 0 0 auto; min-width: 80px`) and asked for a one-item re-verify without ending the session. Reopened the `visual-verify` playwright-cli session, reloaded prod, reopened the same Babylonia term popover on the same seed document (§1). Confirmed via `getComputedStyle`: the "Disambiguating context" label's computed height dropped from 80px (first run) to 18px (matches natural line-height) — the dead gap is gone, label sits directly above its text. Cross-checked the four row-mode labels (Difficulty/Pair accuracy/Source lemma/Wikidata) still hold an ~80px column via the new `min-width: 80px` (rectW 80–82px), so the fix didn't regress the row layout. Screenshot `15-popover-gap-fixed.png`. Popover closed via Escape, session closed, nothing saved/mutated. Appended a confirmation section to the owner-facing Russian report and flipped its top verdict from PASS-with-findings to PASS.

## Verdict handed to caller

**PASS** (updated from PASS-with-findings after the re-check above): all 7/7 items now confirmed fixed on prod, including the term-popover spacing bug found in the first pass. 0 console errors across the whole run. Nothing was saved/mutated at any point.
