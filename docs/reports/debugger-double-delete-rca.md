# RCA: "double DELETE per one confirm" (BUG-4, prod-stability-iter2-2026-07-16)

Agent: debugger (read-only, root-cause diagnosis only — no code changes made).
Target: https://glossa-mt.com (live prod). Worktree: `/Users/a1111/Projects/Work/worktrees/emnlp-demo-sprint`.
Tool: `playwright-cli` (session `-s=rca-doubledelete`).

## Verdict

**DRIVER ARTIFACT — not a real app bug.** No code fix needed.

## Method

Instrumented the live page (no app code touched): monkeypatched `window.fetch` to log
every `DELETE {method,url,ts}` into `window.__deletes`, created a throwaway model
(`rca-doubledelete-probe`, safe — carries no `score`/`issue` rows), and reproduced the
Model Registry "Remove" action four ways, resetting `window.__deletes = []` before each:

| # | Method | `confirm()` | DELETE count |
|---|---|---|---|
| (a) | ONE synthetic `el.dispatchEvent(new MouseEvent('click'))` via `evaluate`, no `.click()` | stubbed → `true`, no dialog | **1** |
| (b) | Baseline: one direct `fetch('/api/models/{name}', {method:'DELETE'})` call, bypassing the app entirely | n/a | **1** (204) |
| (c) | Normal `playwright-cli click` on the Remove button (the way the e2e driver does it) | stubbed → `true`, no dialog | **1** |
| (d) | Normal `playwright-cli click` + real blocking `window.confirm()` dialog + `playwright-cli dialog-accept` (exact e2e-driver sequence, dialog un-stubbed) | real, native | **1** |

All four controlled reproductions — including (d), which reproduces the exact
click-then-native-dialog-then-accept sequence the e2e driver goes through — returned
**exactly one** `DELETE`. The doubling from BUG-4 could not be reproduced under
controlled conditions with `playwright-cli` itself.

## Supporting evidence

**No app-level double-binding.**
- `document.querySelectorAll('[data-testid="upload-open"]').length === 1`, single
  `#root`, `document.body.children.length === 1` — no duplicate React mount.
- Per-model-row Remove-button count on the live registry table (4 real rows):
  `{"perRowRemoveButtonCounts":[1,1,1,1]}` — exactly one Remove button per row, no
  duplicate listener/element.
- Static code confirms two entirely separate, non-shared handlers:
  - `VariantA.tsx:520-525` (document 🗑) — HAS a synchronous in-flight guard
    (`deleteDocInFlight.current`), checked before `confirm()`.
  - `SettingsTab.tsx:175-186` (`handleRemoveModel`) — **no** in-flight guard, single
    `await onRemoveModel(name)` call inside a `try/catch`.
  Two unrelated code paths, one hardened and one not, both showed doubling in the
  original e2e report and neither showed it in this controlled repro — the *shared*
  factor across the two BUG-4 findings is not app code (there is none shared) but the
  presence of `window.confirm()` gating the action. That correlation (100% of
  confirm()-gated actions doubled: delete-doc, remove-model; 0% of non-gated actions
  doubled: refine/evaluate/create) is diagnostic of a client-side automation quirk keyed
  on the blocking native dialog, not of an app defect — a real app bug wouldn't
  discriminate along "does this handler happen to call `window.confirm()` first."

**Idempotency check (closes a possible gap in the hypothesis).** BUG-4 recorded *both*
DELETEs returning 204, which could look like it needs two live rows to explain. Verified
directly: calling `DELETE /api/models/{name}` twice in a row (second call on an
already-deleted name) returns `204` both times — the endpoint is unconditionally
idempotent. So a genuine double physical click (real double request, whatever produced
it) is fully consistent with "both 204" without requiring any race or duplicate
resource — this removes the one piece of the original report that looked inconsistent
with a simple double-click.

**Mechanism (why confirm() specifically).** `window.confirm()` blocks the renderer's JS
main thread synchronously until answered. Browser-automation click actions that don't
pre-register a `page.on('dialog')` handler before triggering the click can observe the
resulting thread-freeze as a stalled/failed action (their own actionability or
navigation-settle wait times out while the thread is frozen on the dialog) and retry the
click. If retried, two physical click events end up queued against the still-live
button; both resolve once the dialog is finally answered, each independently calling
`confirm()` → the handler → one `DELETE` apiece. `playwright-cli` itself does not
exhibit this — it explicitly pauses and surfaces `"confirm" dialog ... can be handled by
dialog-accept or dialog-dismiss"` rather than blindly retrying the click (confirmed in
run (d) above) — so whichever tool actually produced BUG-4's transcript either used a
different click/dialog-handling path than `playwright-cli`'s documented flow, or hit a
timing-dependent variant of this same class of bug that this session's clean, low-latency
runs didn't trigger.

## Cleanup

- Probe model `rca-doubledelete-probe` deleted; `GET /api/models` post-run:
  `['deepseek/deepseek-v4-flash', 'google/gemini-3.1-flash-lite', 'google/gemma-3-27b-it', 'qwen/qwen3.6-27b']`
  (exactly the 4 real models, no probe residue).
- Documents untouched: `GET /api/documents` post-run shows ids `1, 10, 13` unchanged
  (`Mesopotamia — ancient Near East (pilot)`, `World History — Selected Passages (Draft
  Translation)`, `The Qin State — Ancient China`).
- No `score`/`issue` rows touched (probe model carried none; no document delete was
  performed against real data).
- Browser session `-s=rca-doubledelete` closed.

## Open questions (not settled by this RCA)

1. The exact tool/sequence that produced the original BUG-4 transcript wasn't specified
   in the e2e report — this run used `playwright-cli` (the project's canonical driver)
   and could not reproduce the doubling even with the real dialog. If BUG-4's run also
   used `playwright-cli`, the artifact is timing/environment-dependent (not
   deterministic on this connection/latency) — retry BUG-4's exact e2e scenario a few
   more times to check flake rate before closing it as "understood."
2. Whether the e2e-tester agent code path pre-registers a `dialog` handler before
   clicking confirm()-gated buttons was not inspected in this task (out of scope — this
   RCA covers the app, not the e2e harness's own click helper). If a fix is wanted, it
   belongs in the e2e driver/harness, not in `VariantA.tsx` or `SettingsTab.tsx`.

## NOT done

- Did not inspect the e2e-tester agent's own Playwright driver code/config to find the
  exact retry trigger — flagged as an open question above, would require a separate
  pass over the e2e harness, not the demo app.
- Did not add an in-flight guard to `SettingsTab.tsx`'s `handleRemoveModel` — per the
  verdict, no app code fix is indicated; a guard there would be speculative defensive
  code against an artifact that isn't in the app.
- Did not attempt to reproduce BUG-4 via MCP-based `browser_click` (playwright MCP) as
  an alternative driver, which per CLAUDE.md is the fallback behind `playwright-cli` —
  could be a fast follow-up if the flake needs pinning down further.
