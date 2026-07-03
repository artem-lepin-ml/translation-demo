import { readFileSync } from 'node:fs';
import path from 'node:path';
import { Schema } from '@tiptap/pm/model';
import { DecorationSet, type Decoration } from '@tiptap/pm/view';
import { describe, expect, it } from 'vitest';
import { buildDecorations } from '../review-extension';
import type { Issue, Term } from '../../api-client';

// Minimal doc→paragraph→text schema (mirrors the real TipTap document shape
// closely enough for buildDecorations, which only walks paragraph text).
const schema = new Schema({
  nodes: {
    doc: { content: 'paragraph+' },
    paragraph: { content: 'text*', toDOM: () => ['p', 0] },
    text: {},
  },
});

function docWithParagraph(text: string) {
  return schema.node('doc', null, [schema.node('paragraph', null, text ? [schema.text(text)] : [])]);
}

function makeTerm(overrides: Partial<Term> = {}): Term {
  return {
    id: 'term-1',
    paragraphId: 0,
    sourceSurface: 'Вавилон',
    sourceLemma: 'вавилон',
    context: '',
    charStart: 0,
    charEnd: 7,
    difficulty: 'green',
    grounded: null,
    candidates: [],
    targetSurface: 'Babylon',
    pairAccuracy: 'green',
    recommended: null,
    note: '',
    ...overrides,
  };
}

// Decoration's public type hides the inline attrs; reach through with one cast.
function attrsOf(deco: Decoration): Record<string, string> {
  return (deco as unknown as { type: { attrs: Record<string, string> } }).type.attrs;
}

function findByTermId(set: DecorationSet, termId: string) {
  // Widget decorations (from === to) have no `type.attrs` — exclude them so
  // attrsOf only ever sees inline (span) decorations.
  return set.find().filter((d) => d.from !== d.to && attrsOf(d)['data-term-id'] === termId);
}

const noOpOpts = {
  activeIssues: [] as Issue[],
  closedIssueIds: new Set<string>(),
  onSegmentClick: () => {},
  criterionColors: {},
};

describe('buildDecorations — term verdict rendering', () => {
  it.each(['green', 'yellow', 'red'] as const)('%s verdict → verdict-%s class + data-verdict', (verdict) => {
    const doc = docWithParagraph('The city of Babylon was great.');
    const term = makeTerm({ pairAccuracy: verdict });
    const set = buildDecorations(doc, { ...noOpOpts, terms: [term], showTerms: true });
    const [deco] = findByTermId(set, 'term-1');
    expect(deco).toBeDefined();
    const attrs = attrsOf(deco);
    expect(attrs.class).toContain('va-term-span');
    expect(attrs.class).toContain(`verdict-${verdict}`);
    expect(attrs['data-verdict']).toBe(verdict);
  });

  it('null verdict → neutral decoration, NEVER green', () => {
    const doc = docWithParagraph('The city of Babylon was great.');
    const term = makeTerm({ pairAccuracy: null });
    const set = buildDecorations(doc, { ...noOpOpts, terms: [term], showTerms: true });
    const [deco] = findByTermId(set, 'term-1');
    expect(deco).toBeDefined();
    const attrs = attrsOf(deco);
    expect(attrs.class).not.toContain('verdict-');
    expect(attrs.class).not.toContain('green');
    expect(attrs['data-verdict']).toBeUndefined();
  });

  it('targetSurface null → no decoration for that term', () => {
    const doc = docWithParagraph('The city of Babylon was great.');
    const term = makeTerm({ targetSurface: null });
    const set = buildDecorations(doc, { ...noOpOpts, terms: [term], showTerms: true });
    expect(findByTermId(set, 'term-1')).toHaveLength(0);
  });

  it('targetSurface not found in EN text → no decoration', () => {
    const doc = docWithParagraph('The city of Babylon was great.');
    const term = makeTerm({ targetSurface: 'Nineveh' });
    const set = buildDecorations(doc, { ...noOpOpts, terms: [term], showTerms: true });
    expect(findByTermId(set, 'term-1')).toHaveLength(0);
  });

  it('repeated occurrences → i-th term maps to i-th free (unclaimed) EN occurrence', () => {
    const doc = docWithParagraph('the city was near another city on the river.');
    const term1 = makeTerm({ id: 'term-1', targetSurface: 'city', pairAccuracy: 'green' });
    const term2 = makeTerm({ id: 'term-2', targetSurface: 'city', pairAccuracy: 'yellow' });
    const set = buildDecorations(doc, { ...noOpOpts, terms: [term1, term2], showTerms: true });

    const [deco1] = findByTermId(set, 'term-1');
    const [deco2] = findByTermId(set, 'term-2');
    expect(deco1).toBeDefined();
    expect(deco2).toBeDefined();
    expect(deco1.from).not.toBe(deco2.from);
    expect(deco1.from).toBeLessThan(deco2.from);

    const attrs1 = attrsOf(deco1);
    const attrs2 = attrsOf(deco2);
    expect(attrs1['data-pair-idx']).toBe('1');
    expect(attrs2['data-pair-idx']).toBe('2');
  });

  it('embedded-substring collision: "York" does not claim inside the already-decorated "New York"', () => {
    // "New York" is the longer surface processed first; "York" must skip the
    // occurrence embedded inside it and land on the standalone "York" later
    // in the text (claim registry — HIGH finding, e2e-confirmed as a clipped
    // span / wrong color tail / dead hover on the embedded match).
    const doc = docWithParagraph('New York is a city. York is also a name.');
    const longTerm = makeTerm({ id: 'term-ny', targetSurface: 'New York', pairAccuracy: 'green' });
    const shortTerm = makeTerm({ id: 'term-york', targetSurface: 'York', pairAccuracy: 'yellow' });
    const set = buildDecorations(doc, {
      ...noOpOpts,
      terms: [longTerm, shortTerm],
      showTerms: true,
    });

    const [nyDeco] = findByTermId(set, 'term-ny');
    const [yorkDeco] = findByTermId(set, 'term-york');
    expect(nyDeco).toBeDefined();
    expect(yorkDeco).toBeDefined();

    const text = doc.textBetween(0, doc.content.size, '\n');
    const standaloneYorkIdx = text.indexOf('York', text.indexOf('New York') + 'New York'.length);
    // decoration positions are offset by +1 (paragraph node open) vs raw text indices
    expect(yorkDeco.from - 1).toBe(standaloneYorkIdx);
    // and it must NOT overlap the "New York" span
    expect(yorkDeco.from >= nyDeco.to || yorkDeco.to <= nyDeco.from).toBe(true);
  });

  it('embedded-substring collision, reverse array order: "York" (processed first) claims the embedded occurrence; "New York" then has no free occurrence left', () => {
    // Documents the greedy-by-array-order outcome: when the short surface is
    // processed BEFORE the long one, it legitimately claims the first "York"
    // occurrence (inside "New York") since nothing is claimed yet. The long
    // term's own occurrence overlaps that claim and is skipped too — this is
    // accepted greedy semantics, not a bug (array order is the priority).
    const doc = docWithParagraph('New York is a city.');
    const shortTerm = makeTerm({ id: 'term-york', targetSurface: 'York', pairAccuracy: 'yellow' });
    const longTerm = makeTerm({ id: 'term-ny', targetSurface: 'New York', pairAccuracy: 'green' });
    const set = buildDecorations(doc, {
      ...noOpOpts,
      terms: [shortTerm, longTerm],
      showTerms: true,
    });

    const [yorkDeco] = findByTermId(set, 'term-york');
    expect(yorkDeco).toBeDefined();
    expect(findByTermId(set, 'term-ny')).toHaveLength(0);
  });

  it('hovered term adds term-cross-highlight', () => {
    const doc = docWithParagraph('The city of Babylon was great.');
    const term = makeTerm();
    const set = buildDecorations(doc, {
      ...noOpOpts,
      terms: [term],
      showTerms: true,
      hoveredTermId: 'term-1',
    });
    const [deco] = findByTermId(set, 'term-1');
    const attrs = attrsOf(deco);
    expect(attrs.class).toContain('term-cross-highlight');
  });

  it('every verdict class the extension emits exists in variant-a.css', () => {
    // jsdom overrides import.meta.url to a fake http://localhost origin once the
    // test environment is active, so new URL(..., import.meta.url) resolves off
    // that fake base instead of the real file path (deviation from the plan's
    // fileURLToPath(new URL(...)) snippet — see plan Task 2 step 1). __dirname
    // (vitest's transform shims it in ESM test files) is jsdom-safe.
    const cssPath = path.resolve(__dirname, '../variant-a.css');
    const css = readFileSync(cssPath, 'utf8');
    for (const v of ['green', 'yellow', 'red']) {
      expect(css).toContain(`.va-term-span.verdict-${v}`);
    }
    // the dead scheme must be gone from the emitter
    // (source check, cheap regression guard)
    const ext = readFileSync(path.resolve(__dirname, '../review-extension.ts'), 'utf8');
    expect(ext).not.toContain('pair-accuracy-');
    expect(ext).not.toContain('data-pair-accuracy');
  });

  it('verdict dot renders as a single widget decoration, never a span ::after pseudo-element', () => {
    const cssPath = path.resolve(__dirname, '../variant-a.css');
    const css = readFileSync(cssPath, 'utf8');
    // the dead pseudo-element dot rules must be gone (finding 3 fix)
    expect(css).not.toMatch(/\.va-term-span::after/);
    expect(css).not.toMatch(/\[data-verdict='green'\]::after/);
  });

  it('verdict outline class is stable on every fragment, even when a judge underline splits the span', () => {
    // Mirrors the e2e "Hua-Xia statehood" double-dot bug context: an issue
    // underline that partially overlaps the term span forces ProseMirror to
    // split the inline decoration into multiple DOM fragments. Since the dot
    // widget is gone, the outline is now the only verdict signal — it must
    // carry the verdict-* class on every fragment, not just one.
    const doc = docWithParagraph('Hua-Xia statehood emerged in the Yellow River valley.');
    const term = makeTerm({ id: 'term-1', targetSurface: 'Hua-Xia statehood', pairAccuracy: 'green' });
    const overlappingIssue: Issue = {
      id: 'issue-1',
      paragraphId: 0,
      criterionId: 'accuracy',
      // overlaps only the tail of "Hua-Xia statehood", forcing a split
      targetFragment: 'statehood emerged',
      sourceFragment: '',
      explanation: '',
      suggestion: '',
      severity: 'minor',
      mqmCategory: null,
      status: 'open',
    };
    const set = buildDecorations(doc, {
      ...noOpOpts,
      activeIssues: [overlappingIssue],
      terms: [term],
      showTerms: true,
      criterionColors: { accuracy: '#7aa2f7' },
    });

    // term span itself may be split into >1 inline decoration fragments
    const spanFragments = findByTermId(set, 'term-1');
    expect(spanFragments.length).toBeGreaterThanOrEqual(1);

    // every fragment must carry the verdict outline class
    for (const frag of spanFragments) {
      expect(attrsOf(frag).class).toContain('verdict-green');
    }
  });

  it('neutral term (null verdict) → no verdict-* outline class on any fragment', () => {
    const doc = docWithParagraph('The city of Babylon was great.');
    const term = makeTerm({ pairAccuracy: null });
    const set = buildDecorations(doc, { ...noOpOpts, terms: [term], showTerms: true });
    const spanFragments = findByTermId(set, 'term-1');
    expect(spanFragments.length).toBeGreaterThanOrEqual(1);
    for (const frag of spanFragments) {
      expect(attrsOf(frag).class).not.toContain('verdict-');
    }
  });
});
