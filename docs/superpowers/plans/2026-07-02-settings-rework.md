# Settings Rework Implementation Plan

⚠️ **LEGACY (admin-gate removed in wave-4).** The owner rejected admin-token gating: Settings are fully open to everyone, no unlock step. All admin/unlock content in this plan is historical — not current behavior. See [2026-07-03-wave-4.md, block Б5](../specs/2026-07-03-wave-4.md).

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Implement spec rev-2 [2026-07-02-settings-rework.md](../specs/2026-07-02-settings-rework.md) — admin unlock, Add-Evaluator/Add-Model modals, seed demo flag, visible errors. The spec is the contract; this plan sequences it. The approved mockup [docs/mockups/settings-rework.html](../../mockups/settings-rework.html) is the visual ground truth (its inline CSS is a style reference for the real `variant-a.css` additions).

**Architecture:** backend gets `GET /api/admin/check` (3-state contract) + `PALIMPSEST_SEED_DEMO` flag; frontend gets an admin-token module in api-client (sessionStorage, Bearer on the 8 gated routes), unlock/lock UI state in SettingsTab, two new modals. No store-wide state needed beyond what SettingsTab owns (admin state lives in SettingsTab or a small context — prefer local state + api-client module, NOT new zustand slices).

**Tech Stack:** FastAPI + pytest; React + vitest. UI strings English-only.

---

### Task 1: backend — /api/admin/check + compare_digest

**Files:** Modify `src/palimpsest/webapp/app.py`; Test `tests/test_admin_check.py` (new)

- [ ] Step 1: failing tests — 3 contract states: token unset → 200 `{"required": false}` (no header needed); token set + valid Bearer → 200 `{"required": true, "ok": true}`; token set + missing/wrong/empty-Bearer → 401. Plus regression: existing gated route still 401s without token.
- [ ] Step 2: implement route `GET /api/admin/check` per spec §1 exactly. Switch `_require_admin` comparison to `hmac.compare_digest(authorization or "", f"Bearer {ADMIN_TOKEN}")`.
- [ ] Step 3: pytest green → commit `feat(webapp): admin check endpoint + constant-time token compare` (docs in Task 6 commit).

### Task 2: backend — seed demo flag

**Files:** Modify `src/palimpsest/webapp/seed.py`; Test extend `tests/test_seed.py` or new

- [ ] Step 1: failing tests — with `PALIMPSEST_SEED_DEMO=1` (monkeypatch env): model count == 5, all `base_url` contain openrouter, `criterion.model_name` FK resolves; without flag: count == 8 (regression).
- [ ] Step 2: in `seed()`: `demo = bool(os.environ.get("PALIMPSEST_SEED_DEMO"))`; skip `MATRIX` rows with `not spec.is_openrouter` when demo.
- [ ] Step 3: green → commit `feat(webapp): PALIMPSEST_SEED_DEMO seed flag`.

### Task 3: frontend — admin token module + Bearer wiring

**Files:** Modify `frontend/src/demo/api-client.ts`; Test `frontend/src/demo/api-client.test.ts` (extend/new)

- [ ] Step 1: module-level token helpers in api-client: `getAdminToken()/setAdminToken(t|null)` backed by `sessionStorage['palimpsest-admin-token']` (guard typeof window). `adminCheck(token?)` → GET /api/admin/check returning `{required, ok}` (401 → `{required: true, ok: false}`).
- [ ] Step 2: attach `Authorization: Bearer <token>` ONLY on the 8 gated calls (criteria add/save/remove, models add/save/remove, testModel, budget-reset) when a token is stored. Do NOT touch public routes (document reset/delete stay public per spec).
- [ ] Step 3: 401-mid-session hook: export `onAdminReject(cb)` (or simplest: gated helpers throw a typed-ish error whose message contains `→ 401`; SettingsTab catches and calls `setAdminToken(null)`). Keep idiomatic — no event-bus abstraction if a try/catch in the caller suffices.
- [ ] Step 4: vitest (mock fetch): Bearer present on gated calls when token set, absent when not, absent on public calls. Green → commit `feat(webapp): admin bearer wiring in api client`.

### Task 4: frontend — unlock UI + gating in SettingsTab

**Files:** Modify `frontend/src/demo/variant-a/SettingsTab.tsx`, `frontend/src/demo/variant-a/variant-a.css`, `frontend/src/demo/VariantA.tsx` (only if props plumbing needed); Test `frontend/src/demo/variant-a/SettingsTab.test.tsx`

- [ ] Step 1: on mount call `adminCheck(storedToken)` → state `admin: {required: boolean, unlocked: boolean}`. Render per spec: required&&!unlocked → lock row (`data-testid="unlock-row"`, input `unlock-token-input`, button `unlock-btn`, error line `unlock-error`); unlocked → badge `admin-badge` + `relock-btn`; !required → nothing (dev mode).
- [ ] Step 2: Unlock flow: adminCheck(input) → ok: setAdminToken + unlocked; 401: inline `Invalid token`. Lock: setAdminToken(null), unlocked=false, close open modals. Session-expired: any gated call catching 401 → setAdminToken(null), unlocked=false, inline `Session expired — unlock again`.
- [ ] Step 3: locked mode gates ALL mutating controls: Add evaluator, Add model, Edit/Remove/Test buttons AND the enabled checkbox — `disabled` + tooltip `Unlock with admin token to edit` (CSS `.va-disabled-tt[data-tt]` from mockup, add `:focus-visible` variant). The enabled-checkbox `onChange` also gets try/catch → inline error (kill the silent `void`). Same for `onRemoveModel` (currently un-awaited at ~line 256).
- [ ] Step 4: CSS: port `.va-unlock-row`, `.va-admin-badge`, `.va-disabled-tt` styles from the mockup into variant-a.css (adapt tokens, don't duplicate existing ones).
- [ ] Step 5: vitest: locked → all mutating controls disabled AND no fetch fired on click attempts (success criterion 2); unlock/invalid/lock/session-expired flows. Green + tsc → commit `feat(webapp): admin unlock flow and read-only gating in settings`.

### Task 5: frontend — Add Evaluator + Add Model modals, params badge

**Files:** Modify `frontend/src/demo/variant-a/SettingsTab.tsx`, `variant-a.css`; Test `SettingsTab.test.tsx`

- [ ] Step 1: Add-Evaluator modal (reuse the EditModelModal popover pattern; `data-testid="add-evaluator-modal"`, error `add-evaluator-error`): Name, Model select, Weight (number input; invalid → inline `Weight must be between 0 and 1`, Save blocked — NO silent clamp in the modal), Prompt textarea (markdown, set once at creation), Color auto via `unusedColor` + editable color input. Save → POST via onAddCriterion with `enabled: false`; server error → inline. Replaces `handleAddEvaluator`'s phantom-row creation entirely.
- [ ] Step 2: Add-Model modal (extend EditModelModal or sibling; `add-model-modal`, `add-model-error`): Name, Base URL default `https://openrouter.ai/api/v1`, API key password (optional), Params JSON textarea placeholder `{"max_tokens": 1536}` with parse-error inline. Replaces `window.prompt`.
- [ ] Step 3: params column → `N params` badge (`params-badge-{name}`) toggling `params-expanded-{name}`; independent toggles, multiple open OK, state resets on refetch (local component state keyed by name is fine).
- [ ] Step 4: existing inline EvaluatorEditor stays untouched (spec: post-creation editing remains; prompt preview stays read-only).
- [ ] Step 5: vitest both modals (validation paths + server-error inline) → green + tsc → commit `feat(webapp): add-evaluator and add-model modals, params badges`.

### Task 6: docs parity

**Files:** Modify `docs/subsystems/webapp.md`, `docs/known_issues.md`

- [ ] webapp.md: admin/check contract (3 states), Bearer wiring note, seed flag, new Settings UX (unlock/modals/badges), test-id table from spec. known_issues.md: two follow-ups from spec (`test_model` message not redacted; judge path lacks env-fallback for empty DB key). Commit together with or right after Task 5: `docs(webapp): settings rework contracts`.

---

**Final verification (mandatory):** `uv run python -m pytest tests/ -q` green; `cd frontend && npx vitest run` green; `npx tsc --noEmit` clean; `grep -rn "window.prompt" frontend/src` → 0 hits; UI strings English-only.

**Constraints:** work ONLY in `/Users/a1111/Projects/Work/worktrees/settings-rework` (branch feat/settings-rework). git add specific files only, never -A (31 LFS png pointers must stay untouched). No Co-Authored-By trailer. Conventional Commits.
