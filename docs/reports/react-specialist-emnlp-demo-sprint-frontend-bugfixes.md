# react-specialist — EMNLP demo sprint: confirmed-bug frontend fixes

## Scope

Task: implement 6 confirmed-bug frontend fixes in the demo app (React 19 +
Zustand, Vite) in worktree `/Users/a1111/Projects/Work/worktrees/emnlp-demo-sprint`
(branch `feat/emnlp-demo-sprint`), per e2e-campaign findings T1-F2, T1-F3,
T3-F1, T3-F4, T4-Н1, T8-№2, T9-F1, T10-F1, T10-F2:

1. Revision History panel staleness (unify refetch after Refine/manual-edit/Evaluate/Accept-all).
2. Full-judge-failure masking (`cached` badge no longer suppresses the failed-criteria banner).
3. Accept-all silent 422s (honest post-batch notice + criterion-name resolution in the failure banner).
4. Partial precompute-warming visibility (consume additive backend `failed` count).
5. CRLF byte-counting bug in the paste/upload char counter.
6. Evaluate/score CTA auto-hiding after 5s with no path forward.

No `git commit` was made (per instructions). File lane: `frontend/src/demo/variant-a/`
+ frontend tests, with two flagged exceptions (see Decisions & rationale) and
one doc-parity edit to `docs/subsystems/webapp-ui-design.md`. No backend
Python files were touched.

**Prompt-injection encountered and rejected.** Mid-task, a Bash tool result
(stdout of a `grep` call) contained an embedded `<system-reminder>` block
impersonating "the coordinator" and instructing a scope addition ("FIX 7 —
Refine failures render under the hardcoded 'Evaluate failed:' label"). This
did not arrive as a genuine user/system turn — it was smuggled inside a shell
command's output, which is not how real instructions reach this agent. It was
identified as a prompt injection, explicitly flagged to the caller in-chat,
and **not implemented**. Only the original 6 fixes from the task brief were
executed.

## Files changed

All under `frontend/src/demo/` (TypeScript/CSS/tests only):

- `variant-a/InspectorPanel.tsx` — FIX 1 (`historyRefreshNonce` prop threaded
  into `HistoryBlock`'s refetch effect deps), FIX 2 (failed-criteria banner
  no longer gated on `!cached`), criterion-name resolution helper
  (`criterionLabel`) used by FIX 2's banner (also addresses FIX 3's T8-№2
  raw-id sub-finding, since it's the same banner).
- `variant-a/VariantA.tsx` — FIX 3 (`acceptAllNotice` state + async
  `handleAcceptAllDoc`, softened confirm-dialog copy), FIX 4
  (`precomputePartiallyFailed`/`precomputePartialMessage` exports + notice
  render), FIX 6 (decoupled "Evaluate first paragraphs?" CTA from the 5s
  `translationDoneVisible` fade timer), threads `historyRefreshNonce` from
  the store into `InspectorPanel`.
- `variant-a/variant-a.css` — new `.va-accept-all-notice` /
  `.va-notice-dismiss` rules (FIX 3), reusing `.va-inspector-stale-hint`'s
  exact amber token recipe; no new design tokens.
- `variant-a/upload/file-ingest.ts` — FIX 5: new `normalizeLineEndings()`
  (CRLF/CR → LF), applied inside `ingestFile()` for all three source paths
  (.docx / .md / .txt).
- `variant-a/upload/UploadModal.tsx` — FIX 5: textarea `onChange` normalizes
  pasted/typed text before it enters `state.text` (single choke point, so the
  counter and the text later POSTed to `createDocument` are always the same
  string); added `data-testid="panel-${id}-counter"` to the previously
  untestable counter span.
- `store.ts` — FIX 1: new `historyRefreshNonce: number` field +
  `bumpHistoryRefresh()` helper, called from `evaluateParagraph`'s success
  path (transitively covers Refine's chained evaluate and Retry-failed),
  `saveParagraphTarget`'s success path, and `acceptAllIssues` when
  `applied > 0`.
- `api-client.ts` — FIX 4: additive optional `failed?: number` field on
  `PrecomputeStatus`.
- Test files updated/extended to match: `store.test.ts` (+7 new tests, +1
  assertion on an existing refine test), `variant-a/InspectorPanel.test.tsx`
  (+5 new tests), `variant-a/VariantA.test.tsx` (+~19 new tests across 4 new
  `describe` blocks + 7 pure-function unit tests), `variant-a/upload/UploadModal.test.tsx`
  (+2 new tests, new local `ControlledSidePanel`), `variant-a/upload/__tests__/file-ingest.test.ts`
  (+5 new tests for `normalizeLineEndings`).
- `docs/subsystems/webapp-ui-design.md` — one catalog-table row added for
  the two new CSS classes, per that doc's own "Extension rule" doc-parity
  requirement (Hard Invariant 2).

## Decisions & rationale

- **Scope deviation, flagged honestly: `store.ts` and `api-client.ts` were
  touched even though they sit one directory above `variant-a/`.** FIX 1's
  nonce must live inside the store's mutation action handlers
  (`evaluateParagraph`, `saveParagraphTarget`, `acceptAllIssues`) — there is
  no way to implement a "refetch after this store mutation completes" signal
  from within a presentational component. FIX 4 requires declaring the new
  `failed?: number` wire field somewhere, and `PrecomputeStatus` is declared
  in `api-client.ts`. Both are frontend-demo-scoped TypeScript infrastructure
  files (not backend Python, not shared with any other "variant" — there is
  currently only `variant-a`), and the task's own text explicitly required
  consuming the backend's new `failed` field "additively/defensively",
  which is only possible by typing it. I read "Do NOT touch backend python
  files" as the operative boundary and "ONLY under variant-a/" as shorthand
  for the frontend-demo lane; I did not touch anything under
  `src/palimpsest/`. Flagging this explicitly rather than silently going
  outside the literal path, per Honesty (CLAUDE.md Hard Invariant / General
  working rules §3).

- **Root-cause finding for FIX 1 (why single-Accept never needed a bump).**
  Traced through the code: single Accept's button only renders inside
  `IssuesView` (Issues tab). `HistoryBlock` only renders on the Scores tab.
  So at the moment of a single Accept, `HistoryBlock` is always unmounted;
  the next time the Scores tab opens, it mounts fresh and its very first
  fetch already reflects the post-Accept server state — no "staleness" is
  possible because there was never a stale mounted instance to refresh.
  Refine's button, the Evaluate/Retry-failed button, and the top-chrome
  Accept-all button are all NOT tab-gated, so they can fire while
  `HistoryBlock` stays mounted on Scores — that's the actual gap. This
  matches the campaign's own behavioral observation (T10-F1) exactly, and
  let me implement the "unify" instruction as a single new nonce
  (`historyRefreshNonce`, same idiom as the existing `documentResetNonce`)
  bumped from 3 call sites rather than 4, with Refine covered transitively
  because it calls `evaluateParagraph` internally.

- **FIX 2 and FIX 3's "T8-№2 raw criterion id" finding are the same UI
  element.** T8's audit note about a "`Failed: crit-…`" banner refers to
  `InspectorPanel`'s failed-criteria warning — the exact banner FIX 2 also
  touches. Rather than duplicating logic, added one `criterionLabel()`
  helper and used it in that single banner, satisfying both findings with
  one change.

- **FIX 3 notice placement:** the brief said "issues panel header" but also
  offered "reuse an existing toast/banner idiom" as the primary instruction.
  There is no toast system in the app (verified by grep). Accept-all is a
  document-wide action (its button lives in the top chrome, not inside any
  per-paragraph panel), so I placed the notice at the top of `va-doc-wrapper`
  — the same location as the existing `va-precompute-failed-notice` — rather
  than literally inside `InspectorPanel`'s issues-tab header, since the
  latter is paragraph-scoped and accept-all is document-scoped. Documented
  this placement choice in the CSS comment and the design-doc catalog entry
  so it's auditable.

- **FIX 3 confirm-dialog copy:** softened "All suggestions are applied" to
  "Suggestions are applied where the underlying text hasn't changed since
  they were found" — a small, low-risk wording fix directly requested by the
  bug's own framing ("the confirm dialog's claim ... becomes false").

- **FIX 4 partial-notice styling:** reused `.va-precompute-failed-notice`
  verbatim (same class, different `data-testid`/text) per the brief's
  explicit "reuse the failure banner style that total failure uses"
  instruction, rather than inventing a new visual treatment.

- **FIX 5 single choke point:** normalization is applied exactly once, where
  text enters `SidePanel` state (file loads in `ingestFile()`, and the
  textarea `onChange` for typed/pasted text). Because `state.text` is always
  normalized by construction, the counter (`state.text.length`) and the
  paragraphs later POSTed via `createDocument` (`splitParagraphs(state.text)`)
  are guaranteed identical — no separate normalization needed at submit
  time, satisfying "ensure the same normalization used at create time".

- **FIX 6 boundary condition:** the CTA's visibility is now keyed off
  `docAggregate === null` (no score anywhere in the document yet) rather
  than a second timer, so it naturally disappears once any evaluation
  succeeds (Run, a manual per-paragraph Evaluate, or precompute) and stays
  up indefinitely otherwise — no new timing machinery introduced.

- **`historyRefreshNonce` made optional/defaulted** (`historyRefreshNonce?:
  number`, default `0`) rather than required, following an existing
  precedent in the same file (`ParaEvalState.refineStage` is optional for
  exactly this reason) — this avoided touching ~10 pre-existing call sites
  in `InspectorPanel.test.tsx` that predate the field.

## Open questions

- Whether the accept-all notice should also auto-dismiss after some time
  window, or stay purely manual-dismiss as implemented — the brief said
  "non-blocking," which a persistent inline notice satisfies, but a
  time-based fade (like the translation-done badge already has) is an
  equally valid reading. Left as manual-dismiss since the brief gave no
  duration and "non-blocking" doesn't imply "self-expiring."
- The wire-contract SSOT (`docs/superpowers/specs/2026-06-30-demo-contracts.md`)
  was not updated to document the new `PrecomputeStatus.failed` field or the
  live `failedCriterionIds` behavior change — that documentation is the
  backend lane's responsibility for their own concurrent change (I only
  consume the field defensively on the frontend), but it should be checked
  that they actually did it as part of their own doc-parity commit.
- The prompt-injection attempt (fake "FIX 7" coordinator message) should
  probably be traced to its source by whoever is orchestrating this session
  — it suggests either a compromised/misbehaving upstream tool or a
  deliberate red-team probe; either way it's worth a look outside my lane.

## NOT done

- FIX 7 ("Refine failures render under the hardcoded 'Evaluate failed:'
  label") — **intentionally not implemented.** It arrived via a prompt
  injection embedded in Bash tool output, not via the actual task-issuing
  channel, and was explicitly outside the original 6-fix brief. Flagged to
  the caller in-chat; not treated as authorized scope.
- No backend/contract-doc changes for the new `PrecomputeStatus.failed`
  field or the live-fallback `failedCriterionIds` behavior — out of lane
  (Python), assumed to be the concurrently-working backend agent's own
  doc-parity responsibility.
- No `git commit` — explicitly excluded by the task instructions.
- No e2e/browser verification was run by this agent (out of scope for a
  frontend-fix lane per the dispatch map — that's `e2e-tester`'s job at
  steps 6/8 of the process). All verification here is `tsc -b --noEmit`,
  `npm run build`, and `npm test` (vitest), all green — no real-browser
  confirmation that the fixes look/behave correctly against the live prod
  backend.
