# Frontend stability wave 1 — six defects + two coordinator-added fixes

Scope: `frontend/src/demo/variant-a/` (+ `frontend/src/demo/store.ts`, which the
variant-a app owns as its Zustand store) and their test files. Base commit
`37977d2` on `feat/emnlp-demo-sprint`. No backend files touched.

## Summary of outcome

- 6 assigned defects fixed (store race, tab-content isolation, 404 polling,
  reset-dialog honesty, Refine button visibility, glossary trace honesty).
- 2 coordinator-added fixes applied on top (red-dot-with-QID grouping bug;
  the glossary "Grounding path" panel wired to the real flat `trace_json`
  schema instead of a nested shape that never existed in backend output).
- Tests: **328/328 passing** (up from a 309 baseline measured by stashing my
  changes and re-running — confirmed via `git stash`/`vitest run`/`git stash
  pop`), +19 new/rewritten tests across 5 files.
- `npx tsc -b`: clean, zero output. `npx vite build`: succeeds (866 KB main
  chunk, pre-existing bundle-size advisory unrelated to this change).
- Item 2 (hidden-tab clickability) — root-caused as **already fixed** in the
  current codebase before I touched anything; I added regression tests
  instead of a functional change (see below — this is the one item where
  "fix" became "verify + lock in").

---

## Item 1 — store.ts `refreshDocument` stale-fetch race

**Root cause**: [store.ts:449-454](../../frontend/src/demo/store.ts#L449)
(pre-fix) awaited `getDocument(cur.id)` and unconditionally `set({ document:
doc })` on resolution. Three call sites poll this action every 2.5-3s
(`startTermsPolling`'s own interval, and two `setInterval`s in
[VariantA.tsx:169,178](../../frontend/src/demo/variant-a/VariantA.tsx#L169)).
If the user switched documents (or backed out to the picker) while a
`refreshDocument()` call was still in flight, the late response clobbered
whatever the user had since switched to.

**Fix**: [store.ts:449-482](../../frontend/src/demo/store.ts#L449) — guard
`if (get().document?.id !== cur.id) return;` immediately before the `set()`
call, re-reading current state right after `await` resolves.

**Tests** (`frontend/src/demo/store.test.ts`, new `describe('refreshDocument
(BUG-1 stale-fetch race / BUG-3 404 handling...)')`):
- discards a resolved refresh for a document the user already switched away
  from (mocks `getDocument` to hang on doc 1, switches to doc 2 mid-flight,
  resolves doc 1 late, asserts state stays on doc 2)
- a same-document refresh still applies normally (guard doesn't block the
  common case)

## Item 3 — polling continues after document deletion (404 spam)

**Root cause**: same code path as item 1 — none of the three pollers
(`store.ts`'s own `termsPollTimer`, and VariantA.tsx's precompute/translation
`setInterval`s) had any 404 handling; a deleted document meant `getDocument`
throwing on every subsequent tick forever (184 console errors observed per
the task brief).

**Fix**: same `refreshDocument` rewrite — on a `→ 404` error (matching the
`GET ${path} → ${res.status}` format `api-client.ts` throws), it calls
`get().stopTermsPolling()` (idempotent, stops the store-owned interval
immediately) and sets `document: null`, which (a) makes VariantA fall through
to the `DocumentPicker` render branch
([VariantA.tsx:451](../../frontend/src/demo/variant-a/VariantA.tsx#L451))
and (b) causes the two VariantA-owned `setInterval` effects to self-clear on
their next render since their dependency arrays include `doc?.id`. Also
calls `refreshDocuments()` so the deleted doc drops out of the picker list.
Guarded by the same stale-fetch id check so a late 404 for an already-
abandoned document never blanks a document the user has since switched to.

**Tests**:
- `store.test.ts`: 404 on the active document clears it + calls
  `refreshDocuments`, without setting `documentError` (neutral state, not an
  error banner); a stale 404 for an already-left document is a no-op; a
  non-404 failure (network/5xx) leaves state untouched.
- `store.test.ts`'s existing `terms-status polling` describe block: new test
  proves the interval genuinely stops after one 404 (`getDocument` called
  exactly once even after 20s of further fake-timer advancement) — this is
  the test that most directly reproduces the "184 errors" failure mode.

## Item 2 — hidden-but-mounted tab content clickable in the DOM

**Finding, not a live bug**: I read both tab systems before touching
anything (per CLAUDE.md's "ground before you design"):
- Main tabs (Document/Glossary/Ranking/Settings),
  [VariantA.tsx:681-837](../../frontend/src/demo/variant-a/VariantA.tsx#L681):
  every tab body is gated by `{activeTab === 'x' && (...)}` — React
  conditional rendering, fully unmounts the non-active tab's subtree.
- Inspector tabs (Issues/Scores),
  [InspectorPanel.tsx:184-210](../../frontend/src/demo/variant-a/InspectorPanel.tsx#L184):
  same pattern, `{tab === 'issues' && (<IssuesView.../>)}` /
  `{tab === 'scores' && paragraph && (<>...</>)}`.

Neither uses CSS-only hiding (`display: none` while mounted) anywhere. I
also checked `IssuesPanel.tsx` (a component with a similar name) and
confirmed via repo-wide grep that it is **dead code, not imported by
anything** — irrelevant to the live render tree. I could not reproduce the
double-click-on-invisible-Dismiss scenario against current source; it is
plausible this was already fixed in an earlier wave, or the description
conflated it with a different defect.

**Action taken**: no functional change (there is nothing to fix); added
regression tests at both the `VariantA` and `InspectorPanel` level asserting
non-active tab content is fully absent from the DOM (`queryByTestId`/
`queryByText` return `null`, not just visually hidden) after a tab switch,
so a future regression to CSS-only hiding would be caught immediately.

**Tests**: `VariantA.test.tsx` `describe('Tab isolation (BUG-2...)')` (2
tests: Document→Glossary unmounts `evaluate-para`/`refine-paragraph`;
Glossary→Document unmounts "Terminology Glossary"); `InspectorPanel.test.tsx`
`describe('InspectorPanel tab isolation (BUG-2...)')` (2 tests: Scores tab
has no Accept/Dismiss; Issues tab has no Aggregate row).

## Item 4 — reset-dialog copy claims scores "will be lost"

**Root cause**: [VariantA.tsx:378-388](../../frontend/src/demo/variant-a/VariantA.tsx#L378)
(pre-fix) — `handleReset`'s `window.confirm` said "All accepted edits,
dismissals and live scores will be lost." Verified against the backend
(`src/palimpsest/webapp/app.py:925-949`, `reset_document`): live scores/
issues are `UPDATE ... SET kind='archived'`/`status='archived'`, never
`DELETE`d — matches the project's Hard Invariant ("never delete LLM
predictions"). Note: this is a **document-level** reset (resets every
paragraph), not a per-paragraph action as the task brief's wording implied —
I verified there is no separate per-paragraph reset anywhere in the codebase
(grepped `variant-a/*.tsx` for "reset") and adapted the copy accordingly
rather than inventing one.

**Fix**: copy now reads "Live scores and issues will be archived (hidden,
not deleted); every paragraph reverts to its seed text." I dropped the
claim that "revisions" are archived too (they aren't — a reset writes a new
`seed`-origin revision and existing revision history is preserved, not
archived or deleted) to avoid over-claiming beyond what's actually true.

**Test**: `VariantA.test.tsx` `describe('Reset confirm dialog (BUG-4...)')`
— clicks Reset, asserts the `window.confirm` message contains "archived"
and does not contain "will be lost".

## Item 5 — Refine button hidden on the Scores tab

**Root cause**: [InspectorPanel.tsx:100](../../frontend/src/demo/variant-a/InspectorPanel.tsx#L100)
(pre-fix) gated the button on `tab === 'issues'` in addition to
`!isCollapsed`, so switching to Scores hid the only entry point to the
refiner pass.

**Fix**: dropped the `tab === 'issues' &&` clause — same handler/state
(`onRefine`, `evalState.refineStage`, `activeIssueCount` from
`visibleIssues`), now rendered for both tabs.

**Tests**: `InspectorPanel.test.tsx` — new test renders with `tab="scores"`
and asserts the button is present, enabled, and its click still fires
`onRefine`. `VariantA.test.tsx` — a second-layer test rendering the full
component with `inspectorTab: 'scores'` in the mocked store confirms the
same at the integration level.

## Item 6 — Glossary trace view: MATCHED column + candidate count

**Root cause (confirmed, not the "1 candidate" framing in the brief)**:
[GlossaryTab.tsx:289](../../frontend/src/demo/variant-a/GlossaryTab.tsx)
(pre-fix) read `primary.candidates` (the wire `Term.candidates` field,
`WikidataRef[]`) and rendered `c.matched_via || 'none'` for the Matched
column. `matched_via` **never existed on the wire type** —
`WikidataRef.as_dict()` (`terminology/base.py:129`) returns exactly `{qid,
url, label, description}` — so the column read `undefined` unconditionally
and always rendered "none". The real per-candidate match provenance lives
at `trace_json.candidates[].matched` (`label_first.py`'s `candidates_traced`,
confirmed against real prod doc 13 in the coordinator-supplied debugger
report). Separately, for a `judge_rejected` term the top-level
`Term.candidates` is explicitly `[]` (see `label_first.py`'s `judge_rejected`
branch, `refs=[]`) while `trace_json.candidates` still holds every candidate
that was considered — a genuine undercount in the old code, not present in
the trace-sourced data.

**Fix**: [GlossaryTab.tsx](../../frontend/src/demo/variant-a/GlossaryTab.tsx)
— `candidatesForDisplay()` now prefers `primary.traceJson?.candidates`
(richer, has real `matched.kind`) and falls back to the plain
`Term.candidates` list only for legacy/seed rows shipping `trace_json={}`.
The Matched column renders the real `matched.kind` (`label`/`alias`) when
known, or an honest `—` (with a `title` explaining why) instead of the old
always-on "none". `glossary-grouping.ts`'s `TraceJson` gained the real flat
schema fields (`queries`, `search_source`, `exact_matches`, `judge`,
`chosen_qid`, `canon_en`, `n_api_calls`, `latency_ms`) alongside the old
nested `query`/`search`/`label_match`/`decision` shape (kept, since
`resolveBadge`'s heuristic fallback and its existing tests still exercise
it — not removed to avoid an unrelated regression).

**Backend finding recorded, no backend change made** (per task instructions):
the backend is not the cause of a permanent "1 candidate" ceiling —
`generate_candidates` is capped by `enrich_top=5`, not 1, and real prod doc
13 shows a `{0:26, 1:11, 2:4, 3:2, 4:5, 5:29}` candidate-count histogram
across 179 terms (from the coordinator-supplied debugger report). The `N=1`
cases users likely perceived as "always 1" are a real, distinct, and
arguably correct backend behavior: `label_first.py` escalates to the LLM
judge whenever `len(exact_matches) != 1`, which includes the case of a
single non-exact fuzzy hit — the UI then labels that "offered to the judge"
with the same framing as a genuine multi-candidate disambiguation. This is
a **cosmetic copy mismatch, not fixed in this pass** (out of the two fixes
the coordinator explicitly asked for; flagged here as a candidate follow-up:
special-case `candidates.length === 1` under the `'llm'` badge tone with
different copy, e.g. "single candidate — confirmed by LLM").

**Tests**: `__tests__/GlossaryTab.test.tsx`, new `describe('GlossaryTab —
real flat trace_json rendering (BUG-6 / debugger fixes)')` — 4 tests using a
realistic fixture shaped exactly like the debugger report's real "Цинь"
prod example: Matched column shows real `matched.kind`, no "none" anywhere;
Grounding-path panel shows live content on all 4 steps, not "Skipped"; Judge
decision block renders the real `judge.response.reason`; legacy/seed
`trace_json={}` rows fall back to the plain candidate list with honest `—`.

---

## Coordinator-added fix A — red-dot-with-QID grouping bug (3rd recurrence)

**Root cause** (per the coordinator-supplied debugger report,
`docs/reports/debugger-glossary-reddot-trace.md`): in
[glossary-grouping.ts](../../frontend/src/demo/variant-a/glossary-grouping.ts),
`groupTerms`'s wave5 merge pass folds an *ungrounded* raw-lemma stem-bucket
into a *grounded* one (e.g. "Тигра" merging into "Тигр"/Q35591) via
`buildFields(allMentions)`, which computed `difficulty` as worst-of across
**every** folded mention — including the ungrounded sibling, which by
contract (`Term` dataclass, `terminology/base.py`) is always `red`. Net
effect: a group with a valid, live Wikidata link renders a red difficulty
dot because an unrelated raw-lemma occurrence of the same word failed to
ground on its own. Confirmed as a real prod repro (doc 1, "Месопотамия",
3 affected groups) in the debugger report. This exact bug was locked in as
*intended* behavior by two existing tests
(`glossary-grouping.test.ts:92-98` and `:157-168`), which is why it recurred
3 times — each prior fix likely patched the visible symptom without
touching the merge logic the tests actively protected.

**Fix**: `buildFields(mentions, qid)` now takes the group's own grounded
`qid` and, when non-null, computes `difficulty` only across mentions that
actually grounded to *that* qid — an ungrounded sibling folded in purely for
lemma-dedup no longer contributes to the headline dot. `pair` deliberately
stays ungated (a red-difficulty mention already has `pairAccuracy=null` by
contract, so it can never skew `pair` anyway — no separate filter needed).
The merge-loop call site passes `target.qid`; the initial per-bucket draft
call site passes `primary.grounded?.qid ?? null` (a no-op there in practice,
since same-bucket mentions already share one qid or are all ungrounded —
the gate only bites in the merge path).

**Tests**: updated `glossary-grouping.test.ts:157-168`'s expected
`difficulty` from `'red'` to `'yellow'` (the grounded mention's own
difficulty) with an updated test name explaining the regression it now
guards; added a clarifying comment to the adjacent ungrounded-only test
(unaffected — genuinely still worst-of, since both mentions there are
ungrounded and share one bucket); added a new dedicated regression test,
"red-dot-with-QID regression: a grounded group keeps its own worst-of
difficulty across MULTIPLE same-qid mentions, still ignoring an unrelated
ungrounded raw-lemma sibling" — 3 mentions (2 genuinely grounded to Q11767 at
green/yellow, 1 ungrounded raw-lemma sibling at red), asserting the group's
difficulty is `'yellow'` (worst of the 2 real Q11767 mentions), never
`'red'`.

## Coordinator-added fix B (part 2) — "Grounding path" panel dead for all live-pipeline terms

Beyond the item-6 Matched-column fix (fix B part 1, folded into item 6
above), the coordinator flagged that the "Grounding path" 4-step panel
(`stepPresentation()`) reads a **nested** `query`/`search`/`label_match`/
`decision` shape that never existed in real backend output — the real
`trace_json` is flat (`{v, config, queries, search_source, candidates,
exact_matches, resolved_by, judge, chosen_qid, canon_en, n_api_calls,
latency_ms}`, confirmed against live prod doc 13 in the debugger report).
Every one of the 4 steps rendered "Skipped — no trace" for every
live-pipeline term (seed/mock data was unaffected only because its
`trace_json='{}'` already skips the whole panel via the pre-existing
`hasTrace` gate).

**Fix**: rewrote `stepPresentation()` against the real flat schema, keeping
4 steps for minimal visual disruption but re-keyed to what the data
actually offers: `search` (real `queries` list + `search_source`),
`candidates` (real candidate count + Wikidata API-call count),
`exact` (real `exact_matches`, replacing the old fictional
`label_match` step), `decision` (real `resolved_by`/`chosen_qid`/`judge`
error, replacing the fictional per-step `api_calls`/`llm_calls`/`elapsed_s`
fields that never existed). While in the same function, also fixed the
adjacent "Judge decision" block (`showJudge`/`judgeReason`), which read
`trace?.judge_reason` — also never populated by the backend — instead of
the real `trace.judge.response.reason`; this was the same root cause,
directly adjacent to code already being touched, so I fixed it rather than
leave a third known-dead spot next to the two I'd just repaired. I did
**not** touch `resolveBadge`'s separate `trace?.model` fallback (also
technically never populated by the real backend, always degrading to the
generic "LLM" label) — that's a lower-severity cosmetic gap the debugger
report explicitly did not flag as needing a fix, and fixing it would need
wiring `groundingConfig` into `GlossaryTab` (currently not a prop), which is
scope beyond what was asked. Noting it here as a candidate follow-up.

**Tests**: covered by the same `GlossaryTab.test.tsx` fixture as item 6
(`Grounding-path panel renders live search/candidate/decision data instead
of "Skipped — no trace" for every step`, `Judge decision block shows the
real reason from traceJson.judge.response.reason`).

---

## Evidence

### Test run (full suite, after all fixes)

```
$ npx vitest run
 Test Files  21 passed (21)
      Tests  328 passed (328)
```

Baseline (measured by `git stash`-ing all my changes, rerunning, then
`git stash pop`):

```
$ npx vitest run   # against unmodified HEAD (37977d2)
 Test Files  21 passed (21)
      Tests  309 passed (309)
```

Net: +19 tests, 0 regressions, 0 failures.

### Build

```
$ npx tsc -b
(no output — clean)

$ npx vite build
✓ 360 modules transformed.
dist/index.html                   0.81 kB
dist/assets/index-*.css          44.61 kB
dist/assets/index-*.js          866.64 kB
✓ built in 1.02s
```

(The >500 KB chunk-size advisory is pre-existing and unrelated to this
change — not a new warning.)

### Files changed

- `frontend/src/demo/store.ts` — items 1 & 3
- `frontend/src/demo/store.test.ts` — items 1 & 3 tests (+7)
- `frontend/src/demo/variant-a/InspectorPanel.tsx` — item 5
- `frontend/src/demo/variant-a/InspectorPanel.test.tsx` — items 2 & 5 tests (+3)
- `frontend/src/demo/variant-a/VariantA.tsx` — item 4
- `frontend/src/demo/variant-a/VariantA.test.tsx` — items 2, 4, 5 tests (+4)
- `frontend/src/demo/variant-a/GlossaryTab.tsx` — item 6, fix B part 2
- `frontend/src/demo/variant-a/glossary-grouping.ts` — item 6 types, fix A
- `frontend/src/demo/variant-a/__tests__/GlossaryTab.test.tsx` — item 6 tests (+4)
- `frontend/src/demo/variant-a/__tests__/glossary-grouping.test.ts` — fix A tests (+1, 1 updated, 1 clarified)

## Open questions / not done

- Item 6's "backend finding" (single-fuzzy-candidate confirm getting the
  same "ambiguous" framing as genuine multi-candidate disambiguation,
  debugger report §2b) — copy-only, low priority, **not implemented** in
  this pass; the coordinator's explicit ask was fixes A and B, and B's own
  scope statement only named the Matched column and the dead trace-step
  panel.
- `resolveBadge`'s `trace?.model ?? trace?.decision?.model` fallback also
  never resolves to a real per-term model name against live data (same root
  cause as the fields I did fix) — **not changed**, since it doesn't error
  or mislead (degrades to the honest generic "LLM" label) and the debugger
  report explicitly scoped the ask to the step panel, not this heuristic.
- Item 2: no functional change was needed or made — confirmed via direct
  code reading, not assumed away. If the double-click-on-Dismiss defect
  described in the brief is still reproducible in a real browser, it is not
  coming from either tab system's render logic and would need a live e2e
  repro to isolate (out of scope for this static/unit-test pass — I did not
  run a browser session).
- I did not run this worktree's Python test suite or touch any backend file
  — out of scope per the task's "frontend-only" instruction, and per the
  coordinator's explicit "Everything stays frontend-only — no backend
  changes."
