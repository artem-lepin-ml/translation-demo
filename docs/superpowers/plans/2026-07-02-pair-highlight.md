# Pair-Highlight Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Deviations from spec:** None substantive. One decision the spec delegated to the planner is PINNED here: the RU side **stays on `difficulty-*`** (semantically correct — it is the difficulty signal, not the pair verdict — and the smaller diff). The consolidation instead **deletes** the dead parallel color families (`.va-term-span-source.verdict-*` and the prefix-less `.va-term-dot.green/.yellow/.red`), so no duplicate color rules for the same live element survive. See Task 3 rationale.

**Goal:** Term spans in the Translation (EN) panel light up with the `pairAccuracy` traffic-light; a null verdict is never green (neutral, no dot); repeated occurrences of the same `targetSurface` map to distinct positions; one canonical CSS class scheme (`verdict-{color}` + `[data-verdict]`) replaces the dead `pair-accuracy-*` emission.

**Why:** The feature is implemented end-to-end but dead from a name mismatch. `review-extension.ts:180` emits `pair-accuracy-${verdict}` + `data-pair-accuracy`, but the CSS only styles `.verdict-*` + `[data-verdict]` (variant-a.css:491-580). Result: EN term spans render as a neutral dotted border with no color and no dot. Additionally `?? 'green'` (review-extension.ts:177) paints ungrounded terms green — the UI visually approves what the system "cannot assess" (GlossaryTab honestly renders "—" for the same null). And `findLeftmost` (review-extension.ts:175) stacks every decoration for one `targetSurface` on the first occurrence, breaking cross-hover on repeats.

**Architecture:** Single-file behavior fix in `review-extension.ts` (EN render path) + a CSS cleanup in `variant-a.css` + one non-behavioral touch in `EditorParagraph.tsx`'s `SourceWithTerms` (RU render path — comment/convention only, RU stays `difficulty-*`). Export `buildDecorations` so vitest can exercise it directly (the file has zero test coverage today). Add a grep-style guard test that the class the code emits actually exists in the CSS.

**Tech Stack:** React 19 + TipTap/ProseMirror v3 + vitest (jsdom, `css:false`). Frontend only; backend/data untouched.

**Data note (report to owner, not fixed here):** Verdicts are `seed.py`'s placeholder `VERDICTS[i % 3]` rotation (`_seed_terms`, seed.py:119-152) and become meaningful only after a seed-refresh. 177/269 terms (66%) are renderable; paragraph id=8 has zero colored terms. Do **not** change seed.py.

---

### Task 1: EN render path — consolidate class scheme, ground null, sequential occurrence matching

**Files:**
- Modify: `frontend/src/demo/variant-a/review-extension.ts`
- Test (new): `frontend/src/demo/variant-a/__tests__/review-extension.test.ts`

Do the test first (TDD): write the failing test, then make it pass with the code change.

- [ ] **Step 1: write the failing test** at `frontend/src/demo/variant-a/__tests__/review-extension.test.ts`. Build a minimal ProseMirror doc from `@tiptap/pm/model` `Schema` (doc→paragraph→text) and call the newly-exported `buildDecorations(doc, opts)`. Read emitted attrs via `deco.type.attrs` (InlineType stores them there — verified against prosemirror-view runtime) and positions via `deco.from`/`deco.to`. Use `DecorationSet.find()` to enumerate. Cover:
  - **green/yellow/red verdict → class + data-verdict.** A term with `targetSurface:'Babylon'` present in the paragraph and `pairAccuracy:'green'` yields a decoration whose `class` contains `va-term-span verdict-green` and `attrs['data-verdict'] === 'green'`. Repeat for yellow, red.
  - **null verdict → neutral, NEVER green.** `pairAccuracy:null`, `targetSurface` present → decoration exists (dotted neutral) but `class` contains **no** `verdict-` token and `attrs['data-verdict']` is absent/undefined. Assert explicitly `expect(cls).not.toContain('verdict-')` and `expect(cls).not.toContain('green')`.
  - **targetSurface null → no decoration.** A term with `targetSurface:null` produces zero term decorations for that term id.
  - **targetSurface not found in EN text → no decoration.** `targetSurface:'Nineveh'` when the paragraph text lacks it → no decoration for that term id.
  - **repeated occurrences → distinct positions + correct data-term-id.** Two terms whose `targetSurface` is the same string (e.g. both `'city'`) in a paragraph containing `'city ... city'`: the 1st term maps to the 1st `city`, the 2nd term to the 2nd `city`. Assert two decorations at different `from` offsets, each carrying its own `data-term-id`, and `data-pair-idx` `'1'` and `'2'` respectively.
  - **hovered term adds `term-cross-highlight`.** `hoveredTermId` equal to a rendered term's id → its class contains `term-cross-highlight`.
  - Keep an issue-underline smoke assertion optional (not required by spec); focus on term decorations.

- [ ] **Step 2: export `buildDecorations`.** Change `function buildDecorations(` (review-extension.ts:109) to `export function buildDecorations(`. No other signature change.

- [ ] **Step 3: sequential occurrence matching (replace `findLeftmost` with index-consuming `findOccurrences`).** In the `showTerms && terms` block (review-extension.ts:170-191), before the `terms.forEach`, precompute the occurrence list per paragraph and consume indices per surface so the i-th term using a surface takes the i-th free EN occurrence:

  ```ts
  // Sequential occurrence matching: the i-th term that references a given
  // targetSurface anchors to the i-th free EN occurrence of it (mirrors the
  // RU pairIndex derivation in SourceWithTerms, keeping both sides in sync).
  const surfaceCursor = new Map<string, number>();
  terms.forEach((term, idx) => {
    const pairIndex = idx + 1;
    const surface = term.targetSurface;
    if (!surface) return; // no EN equivalent → RU badge only (SourceWithTerms)
    const occs = findOccurrences(paraText, surface);
    const used = surfaceCursor.get(surface) ?? 0;
    const occ = occs[used];
    if (!occ) return; // no free EN occurrence left → EN side dims for this term
    surfaceCursor.set(surface, used + 1);

    const verdict = term.pairAccuracy; // null when difficulty=red → neutral, never green
    const isHovered = hoveredTermId === term.id;
    const cls =
      'va-term-span' +
      (verdict ? ` verdict-${verdict}` : '') +
      (isHovered ? ' term-cross-highlight' : '');
    const attrs: Record<string, string> = {
      class: cls,
      'data-term-id': term.id,
      'data-pair-idx': String(pairIndex),
    };
    if (verdict) attrs['data-verdict'] = verdict;
    decos.push(Decoration.inline(base + occ.from, base + occ.to, attrs));
  });
  ```

  This deletes: the `?? 'green'` fallback (review-extension.ts:177), the `pair-accuracy-${accuracy}` class (line 180), and the `data-pair-accuracy` attr (line 186). `findOccurrences` already exists (review-extension.ts:58-68) and is reused; `findLeftmost` (review-extension.ts:50-55) becomes dead — **delete it** (Step 4).

- [ ] **Step 4: delete now-dead `findLeftmost`** (review-extension.ts:50-55). Confirm no other reference: `grep -rn findLeftmost frontend/src` returns nothing after removal.

- [ ] **Step 5: update the module header comment** (review-extension.ts:8-12) — replace the "§6 anchoring by leftmost substring match" and "pairAccuracy → EN-side colour class" lines to reflect: EN side emits `verdict-{color}` + `data-verdict` (null → neutral, no dot); repeated surfaces anchor by sequential occurrence.

- [ ] **Step 6: run** `cd frontend && npx vitest run src/demo/variant-a/__tests__/review-extension.test.ts` → all pass; then `npx tsc --noEmit` → clean.

- [ ] **Step 7: commit** `fix(webapp): render EN term spans on the verdict-* scheme with grounded null and sequential occurrence matching` (git add ONLY `review-extension.ts` and the new test; no Co-Authored-By trailer).

### Task 2: CSS-selector-exists guard test

**Files:**
- Test (extend): `frontend/src/demo/variant-a/__tests__/review-extension.test.ts`

- [ ] **Step 1: add a guard test** that the class the extension emits actually exists in the stylesheet — this is exactly the bug class that lived unnoticed. Read the CSS as a plain string (vitest runs with `css:false`, so import it as text) and assert each emitted verdict token is defined:

  ```ts
  import { readFileSync } from 'node:fs';
  import { fileURLToPath } from 'node:url';

  it('every verdict class the extension emits exists in variant-a.css', () => {
    const cssPath = fileURLToPath(new URL('../variant-a.css', import.meta.url));
    const css = readFileSync(cssPath, 'utf8');
    for (const v of ['green', 'yellow', 'red']) {
      expect(css).toContain(`.va-term-span.verdict-${v}`);
      expect(css).toContain(`[data-verdict='${v}']`);
    }
    // the dead scheme must be gone from the emitter
    // (source check, cheap regression guard)
    const ext = readFileSync(
      fileURLToPath(new URL('../review-extension.ts', import.meta.url)), 'utf8');
    expect(ext).not.toContain('pair-accuracy-');
    expect(ext).not.toContain('data-pair-accuracy');
  });
  ```

  Note: use `readFileSync` with a path relative to the test file, not a bundler import, so `css:false` does not strip the content.

- [ ] **Step 2: run** `npx vitest run src/demo/variant-a/__tests__/review-extension.test.ts` → pass.
- [ ] **Step 3: commit** `test(webapp): guard that emitted term-verdict classes exist in the stylesheet` (test file only; no trailer).

### Task 3: CSS cleanup — remove dead duplicate color families, pin the dotted-vs-solid convention

**Files:**
- Modify: `frontend/src/demo/variant-a/variant-a.css`
- Modify: `frontend/src/demo/variant-a/EditorParagraph.tsx` (comment-only, RU stays `difficulty-*`)

**Rationale (pinned decision):** RU emits `difficulty-*` in four live spots — `EditorParagraph.tsx:300` (`va-term-span-source difficulty-${d}`), `:302` (`data-difficulty`), `:311` (`va-term-dot difficulty-${d}`), and `TermPopover.tsx:46` (`va-term-dot difficulty-${d}`). Migrating those to `verdict-*` is the *larger* diff and is semantically wrong (RU signal is difficulty, not the pair verdict). So RU **stays** `difficulty-*`. The redundancy the spec targets is the set of CSS rules that are **dead** (no emitter):
  - `.va-term-span-source.verdict-green/-yellow/-red` (the RU half of variant-a.css:494/500/506) — RU never emits `verdict-*`. **Delete only the `-source` selector**; keep the `.va-term-span.verdict-*` (EN) half, now live via Task 1.
  - `.va-term-dot.green/.yellow/.red` (variant-a.css:527-529, prefix-less) — zero emitters (`grep -rn 'va-term-dot' frontend/src | grep -v difficulty-` is empty; `SettingsTab` uses the unrelated `va-verdict-dot`). **Delete.**
  Keep live RU rules: `.va-term-dot.difficulty-*` (533-535) and `.va-term-span-source.difficulty-*` (537-549). After the deletions, no two live rules define the same color for the same element — the consolidation invariant holds.

- [ ] **Step 1: split the shared EN/RU verdict selectors** (variant-a.css:491-508). Rewrite the three `.va-term-span.verdict-* , .va-term-span-source.verdict-*` blocks to drop the `-source` line, leaving EN-only:

  ```css
  .va-term-span.verdict-green {
    border-color: var(--va-green);
    background: rgba(61, 220, 132, 0.07);
  }
  .va-term-span.verdict-yellow {
    border-color: var(--va-yellow);
    background: rgba(224, 175, 104, 0.08);
  }
  .va-term-span.verdict-red {
    border-color: var(--va-red);
    background: rgba(247, 118, 142, 0.08);
  }
  ```

- [ ] **Step 2: delete the prefix-less dot rules** (variant-a.css:527-529): the three `.va-term-dot.green/.yellow/.red { ... }` lines. Keep `.va-term-dot.difficulty-*` (533-535) untouched.

- [ ] **Step 3: pin the dotted-vs-solid convention with a comment.** At the top of the `.va-term-span, .va-term-span-source` base block (variant-a.css:481) add:

  ```css
  /* CONVENTION (emergent — do not "unify" away in a refactor):
     terminology spans use a 1px DOTTED border (this block);
     judge/issue underlines use a SOLID box-shadow (.va-underline-seg /
     stackedUnderlineStyle in review-extension.ts). The two signals must stay
     visually distinct on a paragraph that carries both at once. */
  ```

- [ ] **Step 4: update the difficulty-comment** at variant-a.css:531-532 to note the split: RU emits `difficulty-*` (its own color rules below); EN emits `verdict-*` (block above) + `[data-verdict]` (pseudo-element dot). No parallel duplicate families remain.

- [ ] **Step 5: EditorParagraph.tsx comment-only touch.** In `SourceWithTerms` (EditorParagraph.tsx:286-329) and its header doc (line 264-270), leave the `difficulty-*` emission as-is; add a one-line comment above the RU term `<span>` (line ~300) clarifying RU intentionally uses `difficulty-*` (Wikidata grounding), while the EN pair verdict is handled in `review-extension.ts` via `verdict-*`. No className change. (This is the spec's "both render paths touched" requirement — RU path is touched for the convention comment, not behavior.)

- [ ] **Step 6: verify no orphaned selectors.** `grep -rn 'verdict-\|difficulty-\|va-term-dot' frontend/src/demo/variant-a/variant-a.css` and cross-check every remaining color selector has a live emitter in `.ts/.tsx`. Confirm `[data-verdict]` pseudo-element rules (variant-a.css:578-580) remain (now live via Task 1).

- [ ] **Step 7: run** `npx vitest run` (full suite, so the Task 2 guard re-checks the stylesheet) and `npx tsc --noEmit` → clean.
- [ ] **Step 8: commit** `refactor(webapp): drop dead duplicate term-color CSS families, keep RU on difficulty-*` (variant-a.css + EditorParagraph.tsx; no trailer).

### Task 4: doc-parity (webapp.md)

**Files:**
- Modify: `docs/subsystems/webapp.md`

- [ ] **Step 1: update the `review-extension.ts` row** (webapp.md:63) to note it renders EN term spans with the `pairAccuracy` traffic-light via the `verdict-{color}` class + `data-verdict` scheme (null verdict → neutral dotted span, no dot); RU difficulty stays on `difficulty-*` in `SourceWithTerms`/`TermPopover`. Repeated `targetSurface` anchors by sequential occurrence.
- [ ] **Step 2: add the staleness limitation to `## Subtleties`** (webapp.md:193+): a term's EN highlight anchors to `targetSurface` inside the current translation text; after a live edit that removes/changes that substring the EN span silently goes dark (no color/dot), the same accepted semantics as judge underlines that no longer match — an accepted limitation, not fixed. Cross-hover and the RU-side difficulty badge are unaffected.
- [ ] **Step 3: commit** `docs(webapp): pair-accuracy term rendering + targetSurface staleness limitation` (webapp.md only; no trailer).

---

### Verification checklist (run before claiming done)

- [ ] `cd frontend && npx vitest run` — all green, including the new `review-extension.test.ts` (verdict classes, null≠green, repeated-occurrence positions, targetSurface-null suppression, CSS-selector-exists guard).
- [ ] `npx tsc --noEmit` — clean.
- [ ] `grep -rn 'pair-accuracy-\|data-pair-accuracy\|findLeftmost' frontend/src` — empty.
- [ ] `grep -rn '\.va-term-span-source\.verdict-\|\.va-term-dot\.green' frontend/src/demo/variant-a/variant-a.css` — empty.
- [ ] Manual (optional, `npm run dev` against local backend): EN panel term spans show green/yellow/red borders + dots; a `difficulty=red`/`pair=null` term is neutral (no green); a paragraph with both a term span and a judge underline shows dotted-vs-solid distinctly. **Exclude paragraph id=8 from any e2e screenshot (empty of colored terms).**
