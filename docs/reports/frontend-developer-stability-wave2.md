# frontend-developer — stability wave2 (e2e-found bugs, prod-stability-iter1)

Worktree: `/Users/a1111/Projects/Work/worktrees/emnlp-demo-sprint`, branch `feat/emnlp-demo-sprint`.
Source evidence: `docs/reports/e2e/prod-stability-iter1-2026-07-16.md` §4-5.
Lane: `frontend/src/demo/**` + one line in `docs/testing/e2e-data.md`. `src/palimpsest/` untouched (verified — only `Read`, never `Edit`/`Write`; the `app.py`/`tests/test_http_routing.py`/contracts-spec diffs visible in `git status` are the backend agent's concurrent work in the same worktree, confirmed by inspecting the diff, not mine).

## Scope

Fix 7 e2e-found frontend issues (BUG-1..5, SUSPECTED-1, term-popup dead-field check) plus one doc-manifest alignment line, per the task brief. All 7 addressed; none deferred.

## Per-bug status

| ID | Status | Fix |
|---|---|---|
| BUG-1 (Grounding prompt has no save) | **Fixed** | Verified `GroundingConfig` wire contract already carries `prompt` (api-client.ts, PUT `/grounding-config`) — no backend gap. Rewired `GroundingEditor` to the shared `PromptEditor` component (same one `TranslatorCard`/`RefinerCard`/`EvaluatorEditor` already use) instead of a bespoke onBlur-autosave textarea. |
| BUG-2 (empty Name accepted) | **Fixed (frontend half)** | `AddModelModal`: Save disabled while `!name.trim()`; inline "Name is required" shown once the field is touched-and-empty. Confirmed backend also now 422s (`_require_model_name`, `app.py`, concurrent backend-agent commit) — added `parseApiError`-based clean-message handling for that path. |
| BUG-3 (Effective Params frozen) | **Fixed** | `EditModelModal` recomputes the preview live from the Params textarea on every edit (React's documented "adjust state during render" pattern, gated so it can't loop); invalid JSON keeps the last valid preview + a `va-unsaved`-styled hint instead of crashing or going stale forever. |
| BUG-4 (double DELETE) | **Fixed** | Root cause not fully bisectable from the frontend alone (prod build, so React StrictMode's dev-only double-invoke is ruled out — most likely a `window.confirm()` "ghost click" re-firing after the dialog closes). Applied the same synchronous re-entry guard idiom already used elsewhere in this codebase (`SettingsTab`'s `handleTest`/modal `inFlight` refs): a `useRef` checked *before* `window.confirm()`, so neither the dialog nor the DELETE can fire twice regardless of the exact browser-level cause. |
| BUG-5 (2 trailing 404 GETs after delete) | **Fixed** | `deleteDoc` now calls `stopTermsPolling()` and clears `document` (with `documentLoading:true`, avoiding a picker flash) synchronously right after the DELETE succeeds, instead of waiting for `switchDocument` to eventually replace `document` — which is what let the precompute/translation/terms pollers fire one more tick against the deleted id. Mirrors the existing `refreshDocument` 404-recovery path. Side benefit: also fixes a pre-existing (unreported) edge case where deleting the last remaining document left the UI stuck showing the deleted doc's stale data forever. |
| SUSPECTED-1 (History stale after Reset) | **Fixed** | Root cause: Reset rewrites every paragraph's target/revision but reuses the same paragraph id, so `HistoryBlock`'s `paragraph.id`-keyed refetch effect (already fixed for Restore in an earlier wave via `handleRestore`'s explicit re-fetch) never re-fires for Reset. Added a client-side-only `documentResetNonce` counter to the store (bumped on every successful `resetDoc()`), threaded through `VariantA → InspectorPanel → HistoryBlock`, added to the effect's dependency array. Deliberately **not** wired to the backend's `document.version` field — that was explicitly rejected as a contract field (2026-06-30-demo-contracts.md §7, "Отклонено... поле `version` контракта") — this is a separate, purely-frontend signal. |
| Term popup dead-field check | **Was broken, now fixed** | `TermPopover`'s "Ambiguous senses" used the plain `term.candidates` (`WikidataRef[]`), which — per `GlossaryTab.tsx`'s own documented BUG-6 finding — drops to `[]` for a `judge_rejected` term even though real candidates were considered (they only survive in `trace_json.candidates`). Same dead-field class as the already-fixed Glossary tab. Moved `candidatesForDisplay`/`DisplayCandidate` (+ helpers) out of `GlossaryTab.tsx` into `glossary-grouping.ts` (the designated React-free shaping module) so both views share one implementation instead of `TermPopover` importing display logic out of another component; added a `url` field (real `WikidataRef.url` when present, else derived `https://www.wikidata.org/wiki/{qid}` — the exact convention `terminology/base.py` already uses) since the trace-derived candidates never had one. |
| DOC ALIGNMENT | **Fixed** | `docs/testing/e2e-data.md` line 79: replaced the "score resets to not scored" claim with actual behavior (stale-hint banner + last known score), and corrected the "Not yet fixed" note on History staleness — Restore was already fixed in an earlier wave (confirmed live in the source e2e run itself, §3 row "4. Restore к более старой ревизии" — pass, no staleness observed), only Reset needed the fix in this wave. |

## Files changed

Frontend (implementation):
- `frontend/src/demo/store.ts` — `documentResetNonce` field + bump in `resetDoc`; `deleteDoc` synchronous poll-stop + `document:null` clear (BUG-5).
- `frontend/src/demo/variant-a/SettingsTab.tsx` — `GroundingEditor` → shared `PromptEditor` (BUG-1); `AddModelModal` name validation + friendly 422 (BUG-2); `EditModelModal` live Effective Params preview (BUG-3).
- `frontend/src/demo/variant-a/VariantA.tsx` — delete-button `inFlight` guard + `data-testid="delete-doc-btn"` (BUG-4); threads `documentResetNonce` to `InspectorPanel`; `termPopover` state retyped to `TermWithTrace`.
- `frontend/src/demo/variant-a/InspectorPanel.tsx` — `documentResetNonce` prop threaded to `HistoryBlock`; effect dependency array extended (SUSPECTED-1).
- `frontend/src/demo/variant-a/glossary-grouping.ts` — new home for `DisplayCandidate`/`candidatesForDisplay`/`fromTraceCandidate`/`fromWikidataRef`/`matchKindLabel` (moved from `GlossaryTab.tsx`, `url` field added).
- `frontend/src/demo/variant-a/GlossaryTab.tsx` — now imports the moved helpers instead of defining them locally; unused `WikidataRef`/`TraceCandidate` imports dropped.
- `frontend/src/demo/variant-a/TermPopover.tsx` — uses `candidatesForDisplay(term)` instead of raw `term.candidates`; prop type widened to `TermWithTrace`.
- `docs/testing/e2e-data.md` — line 79 rewritten (doc alignment).

Tests (added/updated, all in the same commit-worthy change set):
- `frontend/src/demo/store.test.ts` — `deleteDoc` BUG-5 coverage (poller stop-on-delete via fake timers mirroring the existing terms-polling describe block; synchronous `document:null` clear; empty-picker landing; switch-to-first-remaining) + `resetDoc` `documentResetNonce` bump/no-bump-on-failure.
- `frontend/src/demo/variant-a/VariantA.test.tsx` — new `describe` block: 3-synchronous-click guard (raw DOM `.click()`, same idiom as the existing Evaluate/Refine double-submit tests), confirm-declined no-op, re-arm-after-settle. `makeStore` updated with the new required field.
- `frontend/src/demo/variant-a/InspectorPanel.test.tsx` — 10 call sites updated for the new required `documentResetNonce` prop; 2 new tests in the Revision-history block: re-fetch on nonce change with the same `paragraph.id` (the actual SUSPECTED-1 assertion), and no re-fetch on an unrelated re-render.
- `frontend/src/demo/variant-a/TermPopover.test.tsx` — 3 new tests: plain-candidates fallback, trace-candidates preferred over an emptied top-level list (BUG-6-class), and the block absent when both lists are empty.
- `frontend/src/demo/variant-a/SettingsTab.test.tsx` — Grounding-card tests rewritten for the explicit Save/Revert flow (+ a new "blur without Save does NOT save" regression guard proving the old silent-loss path is gone); 4 new AddModelModal name-validation tests (disabled state, whitespace-only, re-enable, 422 message); 2 new EditModelModal live-preview tests.

## Decisions & rationale

- **BUG-1**: confirmed via `api-client.ts`/contracts spec that the wire contract already supports `prompt` before touching any UI — no backend gap to report.
- **BUG-4**: could not pin the exact browser-level root cause from the frontend lane alone (would need live devtools tracing against the prod build, out of scope here); applied the codebase's own established defensive idiom instead of guessing at a specific "double-bound handler" fix, since the guard is correct regardless of the precise cause.
- **SUSPECTED-1**: explicitly avoided reusing the backend's `document.version` field even though it's present on the wire (`_doc_dict` in `app.py`) — the contracts spec (2026-06-30-demo-contracts.md §7) records that field as deliberately rejected from the frontend contract ("оверинжиниринг/мимо"). Used a purely client-side nonce instead, honoring that prior decision (ground-before-you-design).
- **Term popup fix**: relocated (not duplicated) the candidate-shaping helpers to `glossary-grouping.ts`, the module already documented as "deliberately React-free" for exactly this kind of shared, testable shaping logic — avoids one view component importing display logic out of another.
- **BUG-3**: deliberately scoped as a client-side echo of the typed JSON, not a replay of the server's own capability-filter logic (e.g. forced seed) — matches the bug's own LOW/cosmetic severity and explicit ask ("recompute live from the current textarea content").

## Open questions

None blocking. One thing worth the owner's attention: BUG-4's guard treats the symptom (idempotent re-entry) rather than the diagnosed cause, since diagnosing further would need a live browser trace against the actual prod deploy — flagging in case a future e2e run wants to specifically try to reproduce the double-click/ghost-click mechanism live to confirm which theory was correct.

## NOT done / explicitly out of scope

- Did not touch `src/palimpsest/` (out of lane; backend BUG-2 422 already landed there via the concurrent backend agent, confirmed via `git diff`).
- Did not attempt a live-browser repro of BUG-4's exact root cause (ghost-click vs double-bound handler) — fixed defensively instead, per above.
- Did not add a "matched via" provenance column to `TermPopover`'s Ambiguous-senses list (GlossaryTab's Candidates table shows one) — out of scope for this popover, which never showed that column even before the fix; kept the fix minimal (candidate source correctness only, no new UI surface).
- `git commit`/`git push` — not run (per task instructions: worktree lane, no commit).

## Verification (ran)

- `npx vitest run` (frontend/): **350/350 tests passed**, 21/21 files, 0 failures.
- `npx tsc -b`: clean, exit 0 (full project type-check — `vite build` alone doesn't type-check, so ran this explicitly too since many prop/type surfaces changed).
- `npx vite build`: succeeded, `dist/` emitted (860KB single-chunk warning is pre-existing, unrelated to this change).

## NOT run / why

- Browser/e2e verification (playwright) — out of scope for this frontend-lane fix pass; the task's own verification bar was `vitest run` + `vite build`. A follow-up e2e pass (step 6/8 of the process) would be the right place to confirm these fixes live against a running server, per the project's normal `/verify-pr` flow.
