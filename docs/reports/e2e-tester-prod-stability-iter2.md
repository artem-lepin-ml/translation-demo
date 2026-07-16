# e2e-tester: prod stability iter2 verification

## Scope
Adversarial e2e verification run #2 against LIVE PROD https://glossa-mt.com, verifying 6 wave-2
stability fixes claimed to have shipped on top of iter1 (`prod-stability-iter1-2026-07-16.md`),
plus a full P2 regression sweep and P3 adversarial chaos pass, using `playwright-cli` (session
`-s=stability-iter2`) driven entirely through the real browser UI. Test data from
`docs/testing/e2e-data.md` manifest; one GENERATED whitespace-variant file and several GENERATED
test-entity names (documented with provenance in the main report).

## Files changed
- `docs/reports/e2e/prod-stability-iter2-2026-07-16.md` — full evidence-first report (scenario
  plan, step→data→artifact→verdict table, bug list, GET-diff state verification).
- `docs/reports/e2e/shots/prod-stability-iter2/` — 40 screenshots (01–40), all inspected.
- `docs/reports/e2e-tester-prod-stability-iter2.md` — this file.
- `/Users/a1111/.claude/agent-memory/e2e-tester/translation-demo-bugs.md` — appended iter2 findings
  section.
- `/Users/a1111/.claude/agent-memory/e2e-tester/MEMORY.md` — updated one-line index entry.

No product code was touched (read-only QA run); only prod state was mutated in-flight, and fully
restored by run end (verified via byte-exact GET diff on 6 endpoints, see report §9).

## Decisions & rationale
- **Redid the Grounding-prompt "append TEST" step via `page.evaluate`/`fill` instead of
  `Control+End` + `type()`** after discovering Ctrl+End lands mid-text, not at the true end, in
  that specific textarea (reproduced twice). Needed byte-exact restoration at the end, so precision
  mattered more than replicating a literal keystroke sequence.
- **Redid the Evaluate double-click-guard test with `playwright-cli dblclick`** after an initial
  2-separate-`click` test produced 2 successful POSTs and looked like a guard failure — the two
  clicks were ~5s apart, long enough for the first request to have already resolved, so both were
  legitimate independent calls, not a race. The true synchronous dblclick then showed the guard
  correctly holding (1 POST). Documented both results so the false alarm doesn't get repeated in
  future runs.
- **Tested the Model Registry delete flow too**, even though only document delete was named in the
  double-DELETE fix item — found the identical double-DELETE pattern there, which is useful signal
  for whoever fixes BUG-4 (likely one shared component/handler, not two separate call sites).
- **Verdict: PASS-with-findings**, not FAIL — 5/6 targeted fixes confirmed working, the P2 full
  regression sweep and P3 adversarial pass were both clean (0 uncaught JS errors across the whole
  session), and the state was fully restored. The one unconfirmed fix (double DELETE) is LOW
  severity (idempotent, no visible harm) and was already known from iter1, not a new regression.

## Open questions
- Whether the wave-2 deploy actually included an attempted fix for BUG-4 (double DELETE) that
  simply didn't work, or whether that item was never touched this wave — the task framing implied
  it should have been fixed ("was: 2× DELETE per confirm"), but behavior is byte-identical to
  iter1. Worth confirming with whoever shipped wave-2 before re-investigating the root cause.
- Root cause of the Ctrl+End cursor-position quirk in `grounding-prompt-editor` (app-level keydown
  handler vs. Playwright/Chromium environment quirk) was not investigated — flagged as SUSPECTED/LOW
  since it doesn't affect real mouse-driven users.

## NOT done (explicit)
- Full re-audit of grounding accuracy across all ~86–124 terms/QIDs — out of scope for this wave's
  fresh-fix list, already tracked separately in agent memory.
- Weight-field locale/keyboard-layout retest (iter1 SUSPECTED-2) — not part of this wave's fix list.
- Restore-to-older-revision banner re-test (iter1 SUSPECTED-3) — already documented as a likely
  improvement over the manifest's stale wording, not part of this wave's fix list.
- Full regression of Judges/Translator/Refiner under genuinely different live models — only one
  switch+revert cycle per section was run, to limit live LLM spend.
- AI-translate / DE→FR wave-5 journey — not named in this task's scenario list.
