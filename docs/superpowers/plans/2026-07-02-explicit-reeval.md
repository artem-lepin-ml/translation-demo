# Explicit Re-evaluation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Accepting suggestions (single or Accept-all) and manual paragraph edits must NOT trigger a paid LLM re-evaluation. Re-judging happens ONLY when the user explicitly presses «Evaluate ↻». Outdated scores get a visible "stale" indicator.

**Why:** Owner directive 2026-07-02 — LLM calls are real money and must be spent explicitly. Current behavior: every single accept auto-runs a full paragraph re-judge ([store.ts:446-449](../../frontend/src/demo/store.ts#L446)), Accept-all runs one more ([store.ts:451-463](../../frontend/src/demo/store.ts#L451)).

**Architecture:** Add `stale: boolean` to `ParaEvalState`. Text-changing actions (accept, accept-all, manual save) set `stale=true` instead of calling `evaluateParagraph`. `evaluateParagraph` clears it. UI shows a stale badge on the score chip and a hint next to the Evaluate button.

**Tech Stack:** React + Zustand + vitest (frontend only; backend untouched).

---

### Task 1: store state — `stale` flag

**Files:**
- Modify: `frontend/src/demo/store.ts`
- Test: `frontend/src/demo/store.test.ts`

- [ ] **Step 1: extend `ParaEvalState`** (interface at store.ts:46) with `stale: boolean;` and add `stale: false` to `defaultParaEval()` (line ~143).
- [ ] **Step 2: `evaluateParagraph`** — in the loading-set (line ~308) and the success-set (line ~329) include `stale: false`. In the catch-set, preserve the existing value via the spread (already does `...(s.paraEvalState[paraIdx] ?? defaultParaEval())`).
- [ ] **Step 3: add a small helper inside the store factory:**

```ts
const markStale = (paraIdx: number) =>
  set((s) => ({
    paraEvalState: {
      ...s.paraEvalState,
      [paraIdx]: { ...(s.paraEvalState[paraIdx] ?? defaultParaEval()), stale: true },
    },
  }));
```

(If a closure over `set` is awkward at that spot, inline the equivalent `set(...)` in each caller — do NOT export a new action.)

- [ ] **Step 4: `acceptIssue`** (line ~446) — replace

```ts
const applied = await get().applyIssueEdit(paraId, paraIdx, issueId);
if (applied) await get().evaluateParagraph(paraId, paraIdx);
```

with

```ts
const applied = await get().applyIssueEdit(paraId, paraIdx, issueId);
if (applied) markStale(paraIdx);   // no auto re-judge — owner: LLM calls only on explicit Evaluate
```

- [ ] **Step 5: `acceptAllIssues`** (line ~451) — replace `if (appliedCount > 0) await get().evaluateParagraph(paraId, paraIdx);` with `if (appliedCount > 0) markStale(paraIdx);`. Keep the skipped-fragments alert unchanged.
- [ ] **Step 6: `saveParagraphTarget`** (line ~467) — after the successful `set`, compute `const paraIdx = doc.paragraphs.findIndex((p) => p.id === paraId);` and `markStale(paraIdx)` when `paraIdx >= 0`. Manual edits outdate scores exactly like accepts.
- [ ] **Step 7: update existing tests.** `store.test.ts` contains assertions that accept triggers evaluate — invert them: mock `apiEvaluate` and assert it is NOT called on `acceptIssue`/`acceptAllIssues`. Add: stale=true after accept / accept-all / saveParagraphTarget; stale=false after `evaluateParagraph` resolves.
- [ ] **Step 8: run** `cd frontend && npx vitest run` → all pass; `npx tsc --noEmit` → clean.
- [ ] **Step 9: commit** `feat(webapp): re-evaluate only on explicit request, mark scores stale on edits` (git add ONLY the touched files; no Co-Authored-By trailer).

### Task 2: UI stale indicator

**Files:**
- Modify: `frontend/src/demo/variant-a/EditorParagraph.tsx` (ScoreChip, props at line ~203)
- Modify: `frontend/src/demo/variant-a/InspectorPanel.tsx` (Evaluate button block, line ~64-80)
- Modify: `frontend/src/demo/variant-a/variant-a.css`
- Test: co-located component tests if present; otherwise store-level tests suffice

- [ ] **Step 1: ScoreChip** — add optional `stale?: boolean` prop; render `{stale && <span className="va-stale-badge" title="Scores refer to an earlier version of this paragraph">stale</span>}` next to the cached badge (line ~253). Thread the flag from the paragraph row where ScoreChip is instantiated (source: `paraEvalState[paraIdx].stale`).
- [ ] **Step 2: InspectorPanel** — when `evalState.stale`, render a hint line above/near the Evaluate button: `Scores are for a previous version — press Evaluate ↻` (English-only UI, exact casing). Reuse the existing warning style (`va-inspector-warning`) or a dimmer variant.
- [ ] **Step 3: CSS** — `.va-stale-badge` mirroring `.va-cached-badge` but amber: `color: var(--va-yellow); border-color: var(--va-yellow);` (check exact token names in variant-a.css; use the ones the cached badge uses as template).
- [ ] **Step 4: run** vitest + tsc; eyeball via `npm run dev` against local backend if running (optional).
- [ ] **Step 5: commit** `feat(webapp): stale-score badge and evaluate hint` (specific files only).

### Task 3: docs parity

**Files:**
- Modify: `docs/known_issues.md` — section «Accept-all re-scores per issue (cost cascade)» (line ~52)
- Modify: `docs/subsystems/webapp.md` — evaluate-flow description

- [ ] **Step 1:** rewrite the known_issues entry: resolved 2026-07-02 — accepts and manual edits no longer trigger re-judging at all; scores go stale until explicit Evaluate. Keep the historical context in one sentence.
- [ ] **Step 2:** update webapp.md wherever it says accept triggers re-evaluation (grep `re-judge|re-evaluate|acceptIssue`); describe the stale flag contract.
- [ ] **Step 3: commit** `docs(webapp): explicit re-evaluation contract` — may be squashed into Task 1's commit instead if you prefer doc-parity in the same commit (preferred: same commit as Task 1; then Task 3 happens as part of Task 1 Step 9).

### Task 4: fragment-collision resolution (owner request, added mid-flight 2026-07-02)

**Why:** production screenshot after Accept-all: «Applied 5 of 11; 6 fragments not found in the text.» Earlier accepts in a batch rewrite the target, so later fragments miss on exact substring match even when only whitespace changed, or are genuinely overlapped by a prior edit.

**Files:**
- Modify: `src/palimpsest/webapp/app.py` (`_splice_suggestion`, `patch_issue_status`)
- Modify: `frontend/src/demo/api-client.ts` (IssueStatus union, patchIssueStatus signature)
- Modify: `frontend/src/demo/store.ts` (`applyIssueEdit`, `acceptIssue`, `acceptAllIssues`)
- Modify: `frontend/src/demo/variant-a/VariantA.tsx`, `InspectorPanel.tsx`, `variant-a.css`
- Test: `tests/test_apply_edit.py`, `tests/test_issue_status.py`, `frontend/src/demo/store.test.ts`

- [ ] **Step 1: backend whitespace-tolerant matching** in `_splice_suggestion`: exact substring first; on miss, `pattern = r'\s+'.join(re.escape(tok) for tok in fragment.split())`, `re.search` over target, replace matched span; still `None` → 422 when tokens are genuinely gone.
- [ ] **Step 2: issue status `outdated` end-to-end**: `patch_issue_status` allows `('open','dismissed','outdated')` (DB has no CHECK constraint on status); frontend `IssueStatus` union + `patchIssueStatus` signature.
- [ ] **Step 3: store `applyIssueEdit`** — drop the client-side fragment pre-check (keep the empty-suggestion check); return `'applied' | 'outdated' | 'failed'`; on server 422 set status `outdated` optimistically + PATCH it, instead of reverting to `open`.
- [ ] **Step 4: `acceptAllIssues`** — no `window.alert`; return `{applied, outdated}`; InspectorPanel shows dim inline line `Applied N · M outdated (overlapped by earlier edits)`; outdated cards render dimmed with an `outdated` label (existing generic `isClosed` rendering covers this).
- [ ] **Step 5: confirm (code-read)** Evaluate ↻ regenerates the issue list for the new text (it does: `/evaluate` judges the current target and `applyEvalToParag` merges fresh issues).
- [ ] **Step 6: pytest** — exact hit, whitespace-only mismatch applies, overlapped fragment → 422; PATCH `outdated` accepted.
- [ ] **Step 7: doc-parity in the same commit** — known_issues.md collision entry (resolved), webapp.md issue lifecycle + matching contract.
- [ ] **Step 8: commit** `feat(webapp): whitespace-tolerant apply-edit + outdated issue status`.

---

**Constraints:** work ONLY in `/Users/a1111/Projects/Work/worktrees/explicit-reeval` (branch `feat/explicit-reeval`). UI strings English-only. Never `git add -A`. Backend changes in Task 4 only — run `python -m pytest tests/ -q` at the end.
