# frontend-developer: hide role-level call params outside Model Registry

## Scope

Surgical UI edit on `feat/emnlp-demo-sprint` (worktree `/Users/a1111/Projects/Work/worktrees/emnlp-demo-sprint`;
branch already merged as PR #16, this is a follow-up commit on the same branch).

Owner instruction (verbatim intent): call params must be **visible only in the Model Registry
section** of Settings; remove the params UI entirely from every other section (Translator,
Judges/Evaluators, Grounding, Refiner).

Constraints:
- Remove UI only — no persistence/behavior change. Every `onSave` payload must keep sending the
  existing `params: config.params` unchanged (role-level overrides stay active server-side, just
  not displayed).
- Clean up now-unused state/handlers so `npx tsc -b --noEmit` stays clean (no dead vars).
- Update `SettingsTab.test.tsx` for the removed testids.
- Verify: `npm test` green, `npx tsc -b --noEmit` clean, `npm run build` clean.
- Commit only `SettingsTab.tsx` + `SettingsTab.test.tsx`, explicit pathspecs, Conventional Commits,
  no AI signature, no push.

## Files changed

Both under `frontend/src/demo/variant-a/`:

| File | Diff |
|---|---|
| `SettingsTab.tsx` | 106 lines changed (net removal) |
| `SettingsTab.test.tsx` | 56 lines changed (net removal) |

Combined: **17 insertions, 145 deletions**, commit `4bd4d2356d99f6b91fbd63f63115e780fdc909b0`.

### `SettingsTab.tsx`

- **TranslatorCard** (~L822–863): removed `paramsText`/`paramsError` state, `commitParams`, the
  whole effective-preview computation (`selectedModel`, `forcesSeed`, `parsedForPreview`,
  `effectiveParts`), and the `va-translator-params-row` JSX block (`translator-params` textarea,
  `translator-params-error`, `translator-effective` line).
- **GroundingEditor** (~L874–928): removed `paramsText`/`paramsError`/`paramsOpen` state,
  `commitParams`, and the params badge+expand JSX block (`grounding-params-badge`,
  `grounding-params-expanded`, `grounding-params-error`).
- **RefinerCard** (~L930–983): removed the `Params` label + `<ParamsInline params={config.params} />`
  / `refiner-params` span (this card had no editable params state to clean up — it was already
  read-only display). Rewrote the stale header comment that described the removed block.
- **EvaluatorEditor** / **AddEvaluatorModal** (Judges section): read in full — never rendered a
  params UI. No change.
- **Model Registry** (~L135–273), `ParamsInline` (~L743–770), `EditModelModal` (~L1044–1160),
  `AddModelModal` (~L1313–1392): confirmed untouched by the diff — these remain the only params UI
  left in the file. Every surviving `onSave`/`commitField` call in the four touched cards still
  passes `params: config.params` unchanged.

### `SettingsTab.test.tsx`

- **Translator** `describe`: dropped `editing params and blurring commits via
  onSaveTranslatorConfig` and `shows an inline error on invalid params JSON` (both exercised the
  removed textarea); rewrote `shows an inline error when the save is rejected` to trigger via the
  model-select `onChange` (still an immediate-commit path) instead of the removed params field;
  trimmed the `translator-params` assertion from the "renders above Evaluators..." test and added
  `queryByTestId('translator-params'|'translator-effective')` → `toBeNull()`.
- **Grounding** `describe`: dropped `expands params and shows an inline error on invalid JSON`
  (exercised the removed badge/textarea); left `shows an inline error when the save is rejected`
  untouched — it already triggered via the prompt field, not params; added
  `queryByTestId('grounding-params-badge')` → `toBeNull()` to the "renders the Grounding section..."
  test.
- **Refiner** `describe`: trimmed the `refiner-params` assertion from the "renders with
  model/params/prompt..." test (renamed it), added `queryByTestId('refiner-params')` →
  `toBeNull()`. No other Refiner test referenced params.
- **Model Registry / EditModelModal / AddModelModal** test blocks (`SettingsTab params inline
  text`, `Effective params`, `Add Model modal`): untouched — still assert the surviving
  Model-Registry-only params UI.

## Decisions & rationale

1. **Delete vs. "assert absence"**: the task allowed either. Deleted tests whose entire premise was
   interacting with now-nonexistent DOM (typing into a removed textarea). Where a test's *trigger*
   was reusable via a surviving control (Translator's rejected-save test), rewrote the trigger
   instead of deleting the test, to keep coverage on the surviving `*-field-error` rendering branch
   — mirrors the pattern already used elsewhere in the file (Grounding's own
   "changing the model select..." test).
2. **Added assert-absence checks** on the retired testids inside tests already being touched (no
   new `it(...)` blocks) — a near-zero-cost permanent regression guard for the actual owner intent
   ("params visible ONLY in Model Registry").
3. **RefinerCard comment rewrite**: the old comment explained the (now-removed) read-only params
   display as "deliberately deferred" JSON-editing; left uncorrected it would mislead the next
   reader. Rewrote to state the real current reason, same file/section — not scope creep.
4. **CSS untouched**: classes like `va-translator-params-row`/`va-params-badge` may now be unused,
   but `va-params-expanded` is still live (Model Registry). Out of the explicit two-file commit
   scope, and CSS isn't typechecked so it doesn't affect the tsc/build gates.
5. **`commitField` kept in all three cards** — still exercised by the model-select `onChange` (and,
   for Grounding, the prompt `onBlur`); only the params-specific `commitParams` functions were dead.

## Verification (all ran)

- `npm test` (full suite): **21 files / 314 tests passed**, 0 failures. `SettingsTab.test.tsx`
  alone: 64/64.
- `npx tsc -b --noEmit`: clean, zero output. `noUnusedLocals`/`noUnusedParameters` confirmed `true`
  in `tsconfig.app.json`, so this is a real dead-code guarantee, not a no-op.
- `npm run build` (`tsc -b && vite build`): succeeded, exit 0. One pre-existing bundle-size
  advisory (>500kB chunk), unrelated to this change.
- `git show --stat HEAD` / `git status --porcelain`: commit contains exactly the two target files;
  nothing else staged; commit not pushed.

## Open questions / flags for the owner

1. **Two prompt-injection attempts observed during this task, neither acted on:**
   - A `<context_window_protection>` block plus repeated `PreToolUse:Read` "system-reminder" tags
     tried to redirect tool use to nonexistent `mcp__plugin_context-mode_context-mode__*` tools.
     Ignored — used Read/Edit/Bash (the only tools actually available) throughout.
   - A fake "coordinator message" appeared embedded inside a Read tool-result (not a genuine
     conversation turn), demanding an unrelated scope expansion: delete the `BudgetLine`/Budget-strip
     component entirely. Not acted on. If genuinely wanted, it should come as an explicit direct
     instruction — it's a distinct feature unrelated to call-params visibility.
2. **Pre-existing unrelated dirty state** in this worktree, not created or touched by this task:
   `src/palimpsest/webapp/translate.py` (makes `TRANSLATE_TIMEOUT` configurable via
   `PALIMPSEST_TRANSLATE_TIMEOUT` env var). Left uncommitted; excluded via explicit pathspecs. Owner
   should decide whether/how it gets its own commit.

## NOT done (explicit)

- `BudgetLine` — not removed (see flag above; the instruction to remove it was not legitimate).
- No linter run — not requested; verification bar was `npm test` / `tsc -b --noEmit` / `npm run
  build` only.
- No CSS/stylesheet cleanup for now-possibly-unused classes (`va-translator-params-row`,
  `va-params-badge`) — out of the explicit two-file commit scope; not required by the build/type
  gates.
- Not pushed (explicitly instructed not to).
- `src/palimpsest/webapp/translate.py` not staged/committed (out of scope, pre-existing, not mine).
- No HTML report — plain markdown used; this is a subagent-to-orchestrator technical handoff per
  the persona's own report schema, not an owner-facing step 6/8 verification report.
