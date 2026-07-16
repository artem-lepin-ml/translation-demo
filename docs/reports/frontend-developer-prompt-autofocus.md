# PromptEditor: autofocus + cursor-to-end on preview -> edit transition

## Scope

Fix keyboard-a11y gap flagged in `docs/reports/e2e/prod-stability-iter2-2026-07-16.md`
§6, point 2 (SUSPECTED-2 in that report's own numbering): clicking the "Edit"
toggle in `PromptEditor` switched `mode` to `'edit'` and rendered the
`<textarea>`, but never moved DOM focus into it. A keyboard-only user who
clicked Edit and started typing got nothing, because focus was still on the
Edit toggle button. The same report's point 1 (Ctrl+End landing at the wrong
offset, ~char 473 instead of the true end at 526) is explained by the same
root cause: the textarea was never the active/focused element, so Ctrl+End
had nothing meaningful to act on.

`PromptEditor` is shared by all five prompt-editable surfaces in Settings:
grounding, translator, refiner, and each of the (currently one) judge/evaluator
criteria. Fixing it once fixes it everywhere it's mounted.

## Files changed

- `frontend/src/demo/variant-a/SettingsTab.tsx`
  - `PromptEditor` (component starts at `SettingsTab.tsx:665` after the edit):
    - Added `const textareaRef = useRef<HTMLTextAreaElement>(null);`
    - Added a second `useEffect` keyed only on `[mode]`: when `mode === 'edit'`,
      calls `el.focus()` then `el.setSelectionRange(end, end)` with
      `end = el.value.length`, placing the caret at the end of the current
      draft text.
    - Wired `ref={textareaRef}` onto the `<textarea>` JSX.
  - No changes to Save/Revert/dirty logic, the preview branch, or any other
    component in the file.

- `frontend/src/demo/variant-a/SettingsTab.test.tsx`
  - Added one focused test inside the existing
    `describe('SettingsTab PromptEditor (S1 §2.3, shared by evaluator + translator)', ...)`
    block: `'moves focus into the textarea (cursor at end) on the preview ->
    edit transition (keyboard a11y)'`. It renders with a non-empty saved
    criterion prompt, clicks the Edit toggle, and asserts
    `document.activeElement === textarea` plus
    `selectionStart === selectionEnd === textarea.value.length`.

## Decisions & rationale

- **Effect keyed on `[mode]` only, not on `draft` or `prompt`.** The task
  explicitly forbids stealing focus on every render or while the user is
  typing. Keying solely on `mode` means the effect only re-runs on an actual
  preview<->edit toggle, never on keystrokes inside the textarea (`draft`
  changes) or on background prop re-syncs (`prompt` changes while in preview
  mode, handled by the existing separate effect).
- **Cursor placed at the end of `el.value` at focus time, not at `draft.length`
  from React state.** Using the live DOM `.value` avoids any risk of a stale
  closure over `draft`; since the effect runs synchronously after the
  textarea has already rendered with the current `draft` as its `value`, the
  two are equivalent in practice, but reading off the DOM node is the more
  defensive idiom for a ref-based imperative effect and matches how the task
  description phrased the fix (`setSelectionRange(len, len)` on the focused
  element).
- **No guard against re-focusing on unrelated re-renders while already in
  edit mode.** Not needed: `useEffect` with `[mode]` as the only dependency
  does not re-fire on `draft` changes (typing) by React's own dependency
  semantics, so this was a matter of dependency-array correctness rather than
  needing an extra ref/flag.
- **Did not touch the Ctrl+End key-handling itself.** The task's own framing
  (and the e2e report) treats the wrong-offset Ctrl+End behavior as a
  consequence of the missing focus, not a separate custom keydown handler —
  there is no keydown handler on the textarea in this component. Moving
  focus to the textarea (with native browser text-editing behavior) is the
  complete fix; no separate Ctrl+End interception exists to patch.

## Test / build run (all commands executed in this worktree's `frontend/`)

- `npx vitest run` — **ran**. Result: `Test Files 21 passed (21)`,
  `Tests 351 passed (351)` (350 pre-existing + 1 new). No regressions in the
  grounding Save/Revert suite, translator/refiner prompt tests, or the
  evaluator PromptEditor suite.
- `npx tsc -b` — **ran**. Clean exit, no type errors.
- `npx vite build` — **ran**. Clean build: `✓ 360 modules transformed`,
  `✓ built in 916ms`. The only output is a pre-existing chunk-size-limit
  warning (`dist/assets/index-*.js` 867.60 kB) unrelated to this change — the
  bundle did not grow meaningfully from a two-line `useRef`/`useEffect`
  addition.

## Open questions

None — the fix is narrowly scoped and the e2e report's own root-cause framing
(focus never moves into the field) fully explains both SUSPECTED items it
raised.

## NOT done (explicit)

- Did not re-run the browser-based e2e suite (`playwright-cli` /
  `prod-stability-iter2` scenarios) against this fix — that is out of scope
  for this frontend-lane task; verification here is unit-test + build only,
  per the task's own VERIFY instructions. A follow-up e2e pass (real
  keyboard-only Tab -> Edit -> type -> Ctrl+End flow in a live browser)
  would be the natural way to close the loop on the original e2e finding,
  but was not requested and not run.
- Did not audit or change any other keyboard-focus behavior in
  `SettingsTab.tsx` (e.g. focus return to the Edit/Preview toggle after
  Save, or focus trapping in the Add Evaluator / Add Model / Edit Model
  modals) — out of scope, not mentioned in the task.
- Did not commit or push — per instructions, frontend lane only, no git
  commit/push performed.
