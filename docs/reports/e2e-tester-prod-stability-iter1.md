# e2e-tester report: prod-stability-iter1

## Scope
Adversarial e2e run against live prod https://glossa-mt.com right after a stability-wave deploy. Verified 7 named "fresh-fix" claims (red-dot bug, glossary trace, reset dialog copy, refine-from-scores, doc-switch race, deleted-doc polling, clone-cache fallback), re-attempted a specific adversarial dblclick repro from a prior incident, ran the full money-shot Refine/Restore/Evaluate/Reset flow on doc10 §4, and exercised every Settings control (Model Registry Add/Edit/Test/Remove + invalid input, Judges/Translator/Grounding/Refiner model+prompt+weight+enabled edits), plus Ranking sort/click, Export (xlsx+md), Wikidata links, Escape-closes-modal, and a full-run console sweep.

## Files changed
- `docs/reports/e2e/prod-stability-iter1-2026-07-16.md` — full evidence-first report (Russian, per project convention), scenario-provenance table, bug list, final-state GET-diff verification.
- `docs/reports/e2e/shots/prod-stability-iter1/` — 50 screenshots, all personally inspected.
- `/Users/a1111/.claude/agent-memory/e2e-tester/translation-demo-bugs.md` — appended 2026-07-16 findings section + marked the previously-flagged "Reset dialog says lost" issue as FIXED-and-confirmed.
- `/Users/a1111/.claude/agent-memory/e2e-tester/MEMORY.md` — updated index line.

No product code was touched (QA-only run). Two temporary upload documents (ids 14, 15) and one temporary registry model entry were created during testing and deleted before finishing; one nameless registry-model row created by a discovered bug was also deleted as cleanup.

## Decisions & rationale
- **Interpreted "Reset the paragraph back to seed" (money-shot scenario) as the document-level Reset**, since no separate per-paragraph reset control exists in the UI (confirmed via DOM search — only one `title="Reset document to seed state"` button exists app-wide). Journey 5 in the manifest is also document-scoped. Flagged this interpretation explicitly rather than inventing a UI element that isn't there.
- **When the adversarial dblclick grid accidentally accepted a real Issue (not a hidden one), restored via document Reset rather than trying to surgically undo just that action** — Reset is the only documented, invariant-safe restoration path (archives scores/issues, doesn't delete), and using it doubled as a live confirmation of journey 4 (accept→rescore→delta) and journey 5 (Reset→exact baseline).
- **Ran Evaluate on doc10 §4 (scenario 5) knowing it would append a new score row and shift the displayed aggregate**, since the task explicitly required it; followed up with an extra document Reset afterward specifically to bring the *displayed/current* state back to baseline, per the task's "FINAL STATE must equal INITIAL STATE" rule — the underlying score-row IS permanently appended per the project's own hard invariant (never delete scores), which is expected and not a violation.
- **Precisely restored two edited prompts (Judges/Accuracy, Translator) byte-for-byte** by adding exactly the same delta I'd introduced (not `trimEnd()`, which turned out to eat an extra pre-existing trailing newline on the first attempt) — verified via exact length + tail-slice comparison against the original GET, not just "looks about right."
- **Did not attempt to fix BUG-1 (Grounding prompt has no save)** — out of scope for a QA run; flagged with full repro and DOM evidence for a follow-up dev task.

## Open questions
- Is the Grounding-prompt no-save behavior (BUG-1) intentional (e.g. grounding prompt meant to be read-only/config-managed only) or an oversight? The presence of a fully-wired, editable textarea with no save path strongly suggests oversight, but I did not find any documentation stating grounding prompts are intentionally non-editable via UI.
- Should empty model Name in Add-model actually be blocked, or does the backend rely on the frontend for this validation entirely (i.e., is there also a server-side gap)? I only tested via the UI form; did not attempt a raw API POST to check if the server itself would also accept an empty name.

## NOT done (explicit)
- No re-audit of Wikidata QID grounding accuracy across the full term corpus (already documented separately in agent memory as a known pre-existing issue; not in this wave's fresh-fix list).
- No load/concurrency testing with multiple simultaneous sessions.
- No AI-translate / DE→FR live-translation journey (wave-5 scope, not requested this run).
- Did not attempt a raw-API validation-bypass check for BUG-2 (see Open questions above) — UI-only testing per the task's "through the UI" instruction.

Full evidence-first report with per-scenario provenance table: `docs/reports/e2e/prod-stability-iter1-2026-07-16.md` (Russian, owner-facing). Screenshots: `docs/reports/e2e/shots/prod-stability-iter1/` (50 files).
