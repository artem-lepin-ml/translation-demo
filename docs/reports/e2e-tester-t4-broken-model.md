# e2e-tester — T4 broken-model campaign run — meta-report

## Scope

Executed scenario T4 ("Своя модель с ломаными параметрами", owner: `max_tokens=10`)
of the 2026-07-17 e2e mega-campaign against LIVE prod https://glossa-mt.com, per
`docs/superpowers/specs/2026-07-17-e2e-mega-campaign.md` § T4. Full sub-steps (а)-(е)
executed through the UI via a named playwright-cli session (`-s=t4`), on an ephemeral
`glossa_sid`-cloned DB (golden untouched). Session survived a mid-run harness
`ConnectionRefused` interruption — resumed in the SAME session, no baseline re-capture
needed (same clone, same cookie).

**Remediation round (same date, after initial submission).** An independent auditor
failed the report on evidence hygiene (6 items) while confirming both priority findings
(Н1/Н2) were code-accurate. Fixed surgically in the SAME worktree report: 2 items
required live re-capture (new named session `-s=t4b`, its own fresh clone + full
baseline→mutate→restore→GET-diff cycle), 1 item was a genuine duplicate-screenshot
deletion, 3 items were citation/text corrections needing no new prod calls. Also added
one previously-omitted finding (Н7) the auditor spotted evidence for in an already-taken
screenshot.

## Files changed

All in the task worktree `/Users/a1111/Projects/Work/worktrees/emnlp-demo-sprint`, then
synced byte-identical into this checkout's mandated `docs/reports/e2e/` location (this
checkout's copies are what the harness Stop-hook gate checks; the worktree copies are
canonical):

- `docs/reports/e2e/campaign/t4-broken-model.md` — full Russian evidence report.
  Post-remediation: 7 findings (was 6) — Н1 HIGH, Н2 MEDIUM, Н7 MEDIUM/LOW (new — hardcoded
  "Evaluate failed:" label rendering for Refine errors, `InspectorPanel.tsx:166-169` +
  `store.ts`'s shared `paraEvalState[idx].error` field), Н3/Н5 unchanged LOW/SUSPECTED, Н4
  rescoped to the Test-endpoint path only (citation fixed — it never applied to Refine),
  Н6 reframed to cite `docs/reports/debugger-double-delete-rca.md`'s DRIVER ARTIFACT
  verdict instead of asserting an app-side causal claim. Two sessions' worth of step
  tables, GET-diffs, and LLM-ops counts now both present (`t4` primary + `t4b`
  remediation), each independently restored and byte-diffed.
- `docs/reports/e2e/shots/campaign/t4/` — 18 files (was 16): added
  `15-refine-502-redacted-recapture.png`, `16-evaluate-allfail-silent-cached-recapture.png`,
  `17-registry-restored-t4b-recapture.png`; removed `13-partial-judge-failure-inspector.png`
  (confirmed MD5-identical to `-scrolled.png`, an accidental duplicate never uniquely
  cited in the report).
- `scratchpad/t4b/` (session-local, not repo-tracked) — `refine-502-raw.json`,
  `evaluate-allfail-cached-raw.json`, `baseline/configs.json` + `configs-after.json` —
  raw evidence backing the two re-captured claims.
- This file, `docs/reports/e2e-tester-t4-broken-model.md` (worktree + main-checkout
  copies) — updated to describe the remediation round.

Memory (outside any repo, unchanged by remediation):
`/Users/a1111/.claude/agent-memory/e2e-tester/translation-demo-bugs.md` — "2026-07-17 T4"
section from the original run stands; not re-edited this round (no memory-worthy new
generalizable pattern surfaced by the remediation itself — Н7 and the RCA-citation fix
are report-hygiene corrections, not new cross-session lessons).

## Decisions & rationale

**Original run:**
1. Tested BOTH total judge failure (all 3 fail → hits `_cache_response`'s hardcoded
   `failedCriterionIds:[]`) and partial failure (1-of-3 → honest banner) because they hit
   genuinely different code branches (`if not succeeded:` vs. normal write path) with very
   different honesty properties — a single-judge-broken test alone would have missed Н1.
2. Traced Model Registry params not reaching Refiner/Translator/Grounding to
   `_client_for()`'s `params_override` argument and an explicit code comment before
   reporting it as MEDIUM (design gap) rather than a false-negative bug.
3. Used the invalid-provider-ID route (not max_tokens) to get an honest Refine failure,
   since the UI has no path to inject broken Refiner-specific params.
4. Restored via the same UI controls used to break each config, then GET-diffed all 5
   config endpoints — byte-identical.
5. Did not revert paragraph 58's successful Refine mutation — out of scope for T4's
   configs-only restoration criterion, and reverting a real AI-generated revision by
   deletion would itself violate "never delete LLM predictions."

**Remediation round (this turn):**
6. **Re-captured live rather than reconstructing text** for the 2 items where the
   auditor flagged either a factually wrong raw-log block (item 1: the step-12 refine-502
   log was accidentally copy-pasted from the step-6 Test-failure text, which genuinely
   lacks redaction — the auditor caught this because my OWN screenshot 11 already showed
   `[REDACTED]` while my report text claimed otherwise) or a missing artifact (item 2: the
   headline Н1 event had text-only evidence, no screenshot/saved JSON). Chose live
   re-capture over "honestly downgrade" for both, since re-creating the minimal broken
   state was cheap and produces strictly stronger evidence — a fresh session (`t4b`) with
   its own baseline/restore/GET-diff cycle rather than reusing `t4`, so the remediation
   run is independently auditable, not just a patch onto old evidence.
7. **Verified the byte-duplicate claim before deleting** (item 3): ran `md5` on both
   `13-partial-judge-failure-*.png` files, confirmed identical, confirmed only
   `-scrolled.png` was ever cited in the table, then deleted the unused twin rather than
   re-shooting a "different" view that wouldn't add information.
8. **Fixed the Н4 citation by re-reading both screenshots directly**, not by re-deriving
   the code path from memory: screenshot 05 (Test card) genuinely shows the raw
   `user_id`; screenshot 11 (Refine banner) genuinely shows `[REDACTED]`. Narrowed Н4's
   scope to the Test path only rather than leaving a citation that a careful reader could
   falsify by opening the linked image.
9. **Wrote up Н7 from evidence that already existed** — the auditor pointed at my own
   screenshot filename (`11-refine-502-mislabeled-evaluate.png`) as a signal I'd noticed
   the mislabeling but never turned it into a finding. Traced the actual code path
   (`InspectorPanel.tsx:166-169`'s hardcoded "Evaluate failed:" string rendering
   `evalState.error`, which `store.ts`'s `refineParagraph` populates on any non-409
   failure) before writing it up, rather than just describing the symptom.
10. **Reframed Н6 by citing the existing RCA report instead of re-litigating causation.**
    Read `docs/reports/debugger-double-delete-rca.md` in full: its verdict (DRIVER
    ARTIFACT, not an app bug) is well-evidenced (4-way controlled repro, idempotency
    check, correlation-with-`confirm()` analysis). Dropped my own "frontend doesn't gate
    the repeat click" causal claim as instructed. But did NOT simply parrot the RCA
    uncritically either — flagged an honest discrepancy: my exact click+dialog-accept
    sequence (in both `t4` and `t4b`) matches the RCA's own "verified clean" method (d),
    yet doubled in both of my runs. Framed this as additional data toward the RCA's own
    open flake-rate question (which it explicitly left unresolved), not as a new causal
    theory — this satisfies both "don't re-assert the dropped claim" and "don't suppress
    a real observation that doesn't fit the cited conclusion."
11. **Chose not to re-verify Н3 or Н5** during remediation — the auditor's 6 items didn't
    touch them, and re-opening unflagged findings would have been scope creep against an
    explicitly surgical remediation instruction.

## Open questions

- Whether the owner wants `failedCriterionIds` fixed to reflect the truth even in the
  cache-fallback branch (Н1's recommendation), or wants the UI's "cached" badge upgraded
  instead to also show which criteria triggered the fallback.
- Whether Refiner/Translator/Grounding params should get their own UI editor (matching
  Model Registry's "Effective params" preview), or whether the current registry-only
  editing surface is intentional-final (Н2).
- Whether the double-DELETE RCA's "driver artifact" verdict should be revisited given
  that its own "clean" method (d) reproduced the doubling twice more in this campaign
  (see Н6's discrepancy note) — not something I resolved, since re-litigating a separate
  agent's RCA verdict is out of scope for an e2e report; flagged for whoever owns that
  investigation next.
- Whether Н7 (mislabeled "Evaluate failed:" banner on Refine errors) is worth a
  standalone fix ticket or should ride along with any future Н1 fix touching the same
  `InspectorPanel`/`store.ts` surface — not decided, left as an owner call.

## NOT done (explicit)

- Did NOT test 2-of-3 judges failing separately from 1-of-3 — the code branch is
  identical for any partial-failure count (only the `if not succeeded` / total-failure
  branch differs); documented explicitly in the report's "Что не тестировалось" section.
- Did NOT exercise a live `budget_exhausted` path in either session — budget stayed
  healthy throughout both `t4` and `t4b`; nothing new to add to the existing
  cross-campaign investigation of that classifier.
- Did NOT test grounding-config with broken params directly (no explicit T4 sub-step for
  it) — flagged as sharing Н2's architecture, not separately live-verified.
- Did NOT fix or attempt to prevent the provider `user_id` leak (Н4), the params-routing
  asymmetry (Н2), the cache-fallback contract gap (Н1), or the mislabeled banner (Н7) —
  all are read-only findings for owner triage; no application code was changed in either
  the original run or the remediation round (e2e-tester scope is verification, not fixes).
- Did NOT re-litigate or re-run the double-DELETE RCA itself — cited its existing verdict
  and added one honest discrepancy note (see Open questions), not a full re-investigation.
- Did NOT re-verify findings Н3/Н5, which the auditor's remediation instructions didn't
  touch — scoped the remediation strictly to the 6 named items plus the one explicitly
  pointed-at omission (Н7).
