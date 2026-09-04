# Frontend fixes — Refine/Evaluate double-submit guard + dead Budget-strip cleanup

Worktree: `/Users/a1111/Projects/Work/worktrees/emnlp-demo-sprint`, branch `feat/emnlp-demo-sprint`.
Not committed — left staged for the orchestrator per task instructions.

## Scope

Two code-review findings on the demo frontend (`frontend/src/demo/variant-a/`):

1. HIGH — Refine/Evaluate buttons had no synchronous re-entry guard, so a rapid
   double/triple-click could fire multiple paid LLM calls before React's
   `disabled` prop reached the DOM.
2. LOW — dead code left over from the removed Budget strip (stale comment,
   unused CSS rules, an unused exported type+function, a stale test comment).

## Files changed

- `frontend/src/demo/variant-a/VariantA.tsx` — added the guard (this is the fix).
- `frontend/src/demo/variant-a/VariantA.test.tsx` — 2 new regression tests.
- `frontend/src/demo/api-client.ts` — removed `BudgetSnapshot` + `getBudget()`.
- `frontend/src/demo/variant-a/variant-a.css` — removed `.va-budget-line{,.yellow,.red}` + fixed a stale comment.
- `frontend/src/demo/variant-a/InspectorPanel.test.tsx` — fixed a stale comment.

## FIX 1 — double-submit guard (HIGH)

### Root cause

`VariantA.tsx:319-327` (before): `handleRefine`/`handleEvaluate` called
`refineParagraph`/`evaluateParagraph` straight from the store with no local
gate. The buttons in `InspectorPanel.tsx:90-118` are `disabled={isLoading}`,
where `isLoading` is derived from Zustand `paraEvalState` — that flag only
flips *after* the store's `set()` call is processed and React commits the
next render. A synchronous burst of clicks (real double-click, or 3 raw
`.click()` calls in the same JS tick, as in a test or an impatient click)
all fire before that commit, so all of them call the store action and each
one is a real, billed judge-model call. Refine chains rewrite → rescore
(`store.ts:515-553`, `refineParagraph` internally `await`s
`evaluateParagraph`), so a triple-click on Refine can be up to 6 paid calls.

### Pattern mirrored

Read the two existing instances first, as instructed:
- `SettingsTab.tsx:137,144-145,171` — `useRef<Set<string>>` keyed by model
  name, `if (has) return; add(); try {…} finally { delete() }`. Same idiom
  repeated 3 more times in that file at lines 1028/1170/1298 for
  Add/Edit/Test modals (all `useRef(false)` single-flag variants since those
  are per-modal-instance, one entity at a time).
- `UploadModal.tsx:177,211-231` / `Step2` (`UploadModal.tsx:308,316-332`) —
  `useRef(false)`, guarded `submitTranslate`/`submit`, tested in
  `UploadModal.test.tsx:42-61` via 3 raw `btn.click()` calls (not RTL's
  `fireEvent`, specifically to reproduce the pre-React-commit race) asserting
  `createDoc` was called exactly once.

### What I did

In `VariantA.tsx`, added `const inFlightEvalRef = useRef<Set<number>>(new Set());`
and made `handleRefine`/`handleEvaluate` `async`, each checking-and-setting
the ref synchronously before doing any work, and clearing it in `finally`:

```ts
async function handleRefine() {
  if (!selectedPara) return;
  if (inFlightEvalRef.current.has(selectedParaIdx)) return;
  inFlightEvalRef.current.add(selectedParaIdx);
  try {
    await refineParagraph(selectedPara.id, selectedParaIdx);
  } finally {
    inFlightEvalRef.current.delete(selectedParaIdx);
  }
}
```
(`handleEvaluate` is the same shape, calling `evaluateParagraph`.)

Decisions:
- **Placed the guard in the component handler (`VariantA.tsx`), not in the
  store.** `SettingsTab`/`UploadModal` guard at the component level (one
  `useRef` per mounted UI surface), and `VariantA` is the single owner of
  both `handleRefine`/`handleEvaluate` — InspectorPanel is presentation-only
  and just calls the prop it's given, so gating in `VariantA` closes the gap
  for every click path without touching `InspectorPanel.tsx` or `store.ts`
  (`store.ts`'s `evaluateParagraph` is also called internally by
  `acceptIssue`/`acceptAllIssues`/`refineParagraph` itself — putting the
  guard there would have required reasoning about those unrelated call
  sites, which the task didn't ask for and which the review only flagged
  the two buttons for).
- **Keyed by `paraIdx` (a `Set`), not a single boolean** — mirrors
  `SettingsTab.handleTest`'s `Set<string>` keyed by model name (its
  multi-entity case) rather than the single-`useRef(false)` variant used for
  single-instance modals. `VariantA` is one component instance for the whole
  document, so a bare boolean would block a click on paragraph B while
  paragraph A's evaluate is still resolving, even though those are
  independent server calls (the task's own hint: "keyed by paragraph index
  if multiple paragraphs can be acted on independently").
  set — clicking Refine while an Evaluate is already in flight for the
  same paragraph (or vice versa) is blocked too, matching the combined
  `evalState.loading || refineStage` the buttons already render `disabled`
  against, so there's no new inconsistency between the synchronous guard and
  the render-time disabled state.
- Did not touch the "Retry failed ↻" button (`InspectorPanel.tsx:146-154`,
  `handleRetryFailed`) — it also calls `evaluateParagraph` but the task
  scoped the fix to the Refine/Evaluate pair only (lines 90-118); flagging
  it here as a related but out-of-scope spot the same bug class could still
  apply to.

### Test added

`VariantA.test.tsx`, new `describe('VariantA Refine/Evaluate double-submit
guard (paid-LLM-call race)')`, mirroring `UploadModal.test.tsx`'s raw-`.click()`
repro exactly:
- 3 synchronous `btn.click()` on `evaluate-para` → `evaluateParagraph` called
  exactly once.
- 3 synchronous `btn.click()` on `refine-paragraph` (paragraph seeded with one
  open issue on an active criterion so the button isn't disabled by
  `activeIssueCount === 0`) → `refineParagraph` called exactly once.

## FIX 2 — dead Budget-strip code (LOW)

Grepped each spot before touching it (all zero-usage outside their own
definition/comment):

| Spot | Grep evidence | Action |
|---|---|---|
| `variant-a.css:1200-1202` stale "BudgetLine sits above this…" comment | n/a (comment, not code) | Removed the sentence, kept the rest of the comment |
| `variant-a.css:1287-1300` `.va-budget-line{,.yellow,.red}` | `grep -rn "va-budget-line" frontend/src` → only the CSS definitions themselves, no `className` usage | Removed all 3 rules |
| `api-client.ts:255-260` `BudgetSnapshot` interface | `grep -rn "BudgetSnapshot" frontend/src` → only its own definition + the `getBudget()` signature | Removed (with its `§2 budget snapshot` section-comment header) |
| `api-client.ts:430-432` `getBudget()` | `grep -rn "getBudget\b" frontend/src` → only its own definition + one stale comment (next item) | Removed (with its `§2 budget endpoint` section-comment header) |
| `InspectorPanel.test.tsx:8` "same pattern as SettingsTab's getBudget" comment | dangling reference after `getBudget()` removal | Reworded to drop the dangling reference, kept the actual rationale (mount-time fetch → default-mocked so tests don't hit real `fetch()`) |

Final sanity grep across the whole `frontend/src` tree after all edits:
`grep -rn "BudgetSnapshot\|getBudget\b" frontend/src` and
`grep -n "va-budget-line\|BudgetLine" frontend/src/demo/variant-a/variant-a.css`
both return nothing. Nothing was left half-removed.

Nothing in this list turned out to still be referenced — all 5 confirmed spots
were removed/fixed as proposed.

## Tests run

```
cd /Users/a1111/Projects/Work/worktrees/emnlp-demo-sprint/frontend && npm test -- --run
```
Result: `Test Files  21 passed (21)` / `Tests  309 passed (309)` (0 failures),
including the 2 new double-submit tests and the full existing `SettingsTab`/
`UploadModal`/`InspectorPanel`/`VariantA` suites (no regressions from the CSS/
api-client removals).

Also ran `npx tsc -b --force` (the project's `build` script's type-check half)
to catch any dangling-import/type-signature fallout from removing
`BudgetSnapshot`/`getBudget` and from changing `handleRefine`/`handleEvaluate`
to `async` — clean, zero errors/output.

## Open questions / not done

- Did not run `npm run build` (full `vite build`) — only `tsc -b` (type-check)
  and `vitest run` (unit tests), per the task's explicit ask ("run the
  frontend unit tests"). Type-check is clean so a full build should succeed,
  but that specific command was not executed.
- Did not run e2e/browser tests — out of scope for this task (unit-test-only
  ask); the orchestrator's step 6/8 flow is the place for that if this fix
  ships as part of a PR.
- Left `handleRetryFailed` (`InspectorPanel.tsx:146-154`) unguarded — same bug
  class, not in the reviewed scope; flagging for the orchestrator's judgment
  on whether to fold it into this fix or track separately.
- Left staged, not committed, per the task instruction that the orchestrator
  finalizes. Other unrelated pre-existing modified/untracked files already
  present in this shared worktree (`docs/known_issues.md`,
  `docs/superpowers/specs/2026-06-30-demo-contracts.md`,
  `src/palimpsest/webapp/migrate.py`, `model_matrix.py`, `seed.py`,
  `tests/test_model_registry_v2.py`, `tests/test_refiner.py`, and several
  untracked `docs/reports/*`/`docs/testing/*` files) were left untouched and
  unstaged — they are not part of this task's diff.
