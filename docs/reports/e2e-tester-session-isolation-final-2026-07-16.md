# e2e-tester agent report — session isolation final verification (prod)

## Scope

Final e2e verification against **live prod** `https://glossa-mt.com`, run from worktree
`/Users/a1111/Projects/Work/worktrees/emnlp-demo-sprint` (branch `feat/emnlp-demo-sprint`).
Two parts requested by the orchestrator:

- **Part 1**: verify the session-isolation feature (`glossa_sid` cookie → per-session
  cloned DB) using two independent named `playwright-cli` browser sessions/profiles
  (`iso-a`, `iso-b`) — dismiss-issue, settings/model-param edit, paragraph refine,
  document upload, all checked for leakage between A and B.
- **Part 2**: verify 5 specific "fresh-trace quality" review items the owner asked
  about (Paris grounding, candidates table, judge decision panel, no Wikinews
  candidates, term popover layout) — single session sufficient.

## Files changed

- `docs/reports/e2e/session-isolation-final-2026-07-16.md` — full evidence-first e2e
  report (Russian, per project convention), scenario table, bug repro steps.
- `docs/reports/e2e/shots/session-isolation-final/01…26*.png` — 26 screenshots
  (requirement was ≥14).
- `/Users/a1111/.claude/agent-memory/e2e-tester/translation-demo-bugs.md` — appended a
  new dated section with the Reset/Dismiss bug, the transient-404-on-delete finding,
  a positive confirmation that session isolation itself holds, and a UI-mismatch note
  about refiner temperature not having its own Settings field.
- No application code was touched — read-only QA run against prod, all mutations
  live only in the two ephemeral session clones (`glossa_sid`-scoped DB clones); the
  golden seed document was never written to directly.

## Decisions & rationale

- **No manifest value was invented.** Used `docs/testing/e2e-data.md` as the primary
  source; the two upload files (`andrey_upload_source_ru.txt` /
  `andrey_upload_translation_en.txt`) were taken from `data/seed/demo_docs/` exactly as
  named in the task. The only `GENERATED` value was the upload document's title
  ("Session B isolation upload test") — a plain descriptive label with no sensitive
  content, needed because the Title field is required and the task didn't specify one.
- **"Refiner temperature" deviation.** The task asked to "change refiner temperature to
  0.9" via Settings, but Settings → Refiner has no such field — temperature lives on
  the shared Model Registry entry. Conservative choice: edited the temperature on the
  model Refiner actually uses (`google/gemini-3.1-flash-lite`, Model Registry → Edit →
  Params JSON), which is the closest functional equivalent and still fully exercises
  the settings-isolation check (A shows 0.9, B still shows 0.7). Logged as a deviation
  rather than silently reinterpreting the task.
- **Did not attempt to "undo" the Reset-corruption of session A's §1 after discovering
  BUG-1.** The task's cleanup step asked to restore the dismissed issue in A, but by
  the time Reset had run, §1 was no longer just "dismissed" — it had switched to an
  entirely different historical translation revision with 6 issues instead of 1.
  Patching that state via API would have destroyed the only live repro of a real bug.
  Session A is an ephemeral per-session DB clone (golden untouched), so leaving it in
  this state carries no lasting cost, and it is more valuable as evidence for the
  follow-up fix cycle than a "clean" but undocumented rollback would have been.
- **Verified cross-session negatives via full server reload, not just client state.**
  For every "session X should NOT see session Y's change" check, reloaded the page
  from the server before asserting absence — the app has no client-side router/deep
  link (confirmed: reload always drops back to the picker), so a same-tab check alone
  risked a false negative from stale client cache rather than a true server-side
  isolation guarantee.

## Open questions

- Is the "Reset restores wrong revision after Dismiss" bug (BUG-1 in the e2e report)
  specific to the Dismiss→Reset combination, or does a bare Accept→Reset (no Dismiss)
  also trigger it? Not tested — would need a dedicated debugging session
  (`systematic-debugging`) with DB-level inspection of how many translation revisions
  exist per paragraph and what "restore to seed" actually queries.
- Why did doc-level "Accept all" read 19 after Reset (was 14 before any action)? Likely
  the same root cause as BUG-1 but not confirmed — flagged as SUSPECTED, not
  independently isolated.
- Is refiner temperature intentionally model-scoped (shared across all roles using that
  model), or is a per-role override a known gap? Not answerable from QA alone — needs
  an owner/product decision, flagged explicitly rather than assumed.

## NOT done (explicit)

- Ranking tab, Export (xlsx/md), and the AI-translate/revision-history UI were **not**
  exercised in this run — out of scope for the two parts requested; Export was already
  covered by a prior run (`wave5-run.md`).
- Term-popover **scroll-when-long** behavior (part of review item P2.e) was **not**
  verified — neither of the two live examples used (5 and 1 candidate senses) was long
  enough to force an overflow/scroll state; no live term with a longer candidate list
  was found in this document.
- Did **not** restore session A's dismissed issue / did not "clean up" §1 after BUG-1
  surfaced — left as live repro evidence (see Decisions & rationale above); this is a
  deliberate deviation from the literal cleanup instruction, disclosed here and in the
  e2e report rather than silently skipped.
- Did not root-cause BUG-1 (no DB/backend code inspection) — this was a black-box
  browser QA run only, per the e2e-tester agent's scope; root-causing is a
  `systematic-debugging` follow-up.
