import { describe, expect, it } from 'vitest';
import { buildSourceSegments, computeChipDelta, deltaBadge, type Segment } from '../EditorParagraph';
import type { Term } from '../../api-client';

describe('deltaBadge', () => {
  it('first score (no previous, delta null) → no badge', () => {
    expect(deltaBadge(null)).toBeNull();
  });

  it('improvement → ▲ with magnitude', () => {
    expect(deltaBadge(1.5)).toEqual({ glyph: '▲', magnitude: '1.5' });
  });

  it('regression → ▼ with absolute magnitude', () => {
    expect(deltaBadge(-2.3)).toEqual({ glyph: '▼', magnitude: '2.3' });
  });

  it('delta exactly zero → suppressed (no badge)', () => {
    expect(deltaBadge(0)).toBeNull();
  });
});

describe('computeChipDelta', () => {
  it('no aggregate yet → null', () => {
    expect(computeChipDelta(null, 6, 6)).toBeNull();
  });

  it('first-ever score (aggregatePrev undefined, no baseline either) → null', () => {
    expect(computeChipDelta(7, undefined, null)).toBeNull();
  });

  it('prev-defined + improvement → positive delta', () => {
    expect(computeChipDelta(9, 7, 7)).toBe(2);
  });

  it('prev-defined + regression → negative delta', () => {
    expect(computeChipDelta(5, 8, 8)).toBe(-3);
  });

  it('unchanged score → null (suppressed)', () => {
    expect(computeChipDelta(7, 7, 7)).toBeNull();
  });

  it('baseline fallback: aggregatePrev undefined falls back to aggregateBaseline', () => {
    // Straight from GET (no live /evaluate yet), so aggregatePrev is undefined —
    // the badge compares against the precompute seed baseline instead.
    expect(computeChipDelta(9, undefined, 7)).toBe(2);
  });

  it('aggregatePrev null (explicit "first score" from server) is NOT overridden by baseline', () => {
    expect(computeChipDelta(9, null, 7)).toBeNull();
  });
});

describe('buildSourceSegments', () => {
  function makeTerm(overrides: Partial<Term>): Term {
    return {
      id: 'term-0',
      paragraphId: 14,
      sourceSurface: '',
      sourceLemma: '',
      context: '',
      charStart: 0,
      charEnd: 0,
      difficulty: 'green',
      grounded: null,
      candidates: [],
      targetSurface: null,
      pairAccuracy: null,
      recommended: null,
      note: '',
      ...overrides,
    };
  }

  function termSegments(segments: Segment[]): Segment[] {
    return segments.filter((s) => s.kind === 'term');
  }

  it('fully-nested RU term (эдикт ⊂ титулы эдикта, ¶14 seed geometry) renders both spans', () => {
    // seed: term 135 'титулы эдикта' chars 22-35, term 134 'эдикт' chars 29-34
    // (29-22=7, 34-22=12 → "титулы эдикта".slice(7,12) === "эдикт")
    const text = 'см. в комментариях на титулы эдикта претора.';
    const outer = makeTerm({ id: '135', charStart: 22, charEnd: 35 });
    const inner = makeTerm({ id: '134', charStart: 29, charEnd: 34 });
    expect(text.slice(outer.charStart, outer.charEnd)).toBe('титулы эдикта');
    expect(text.slice(inner.charStart, inner.charEnd)).toBe('эдикт');

    const segments = buildSourceSegments(text, [outer, inner]);
    const terms = termSegments(segments);

    // exactly one top-level term segment (the outer one) — the nested term
    // is not a sibling, it's a child
    expect(terms).toHaveLength(1);
    const outerSeg = terms[0];
    expect(outerSeg.term?.id).toBe('135');
    expect(outerSeg.content).toBe('титулы эдикта');

    // nested child present, with its own id/content and no text loss
    expect(outerSeg.children).toBeDefined();
    const nestedSeg = outerSeg.children!.find((c) => c.kind === 'term');
    expect(nestedSeg?.term?.id).toBe('134');
    expect(nestedSeg?.content).toBe('эдикт');

    // outer text reconstructs losslessly around the nested span (no double render)
    const rebuilt = outerSeg
      .children!.map((c) => c.content)
      .join('');
    expect(rebuilt).toBe('титулы эдикта');

    // both carry their own difficulty class inputs — markup structure enables
    // independent cross-hover (nested span inside outer span, each with its
    // own data-term-id — see closest('[data-term-id]') on the EN side and
    // direct onMouseEnter/onMouseLeave on this RU side, both keyed by id)
    expect(outerSeg.term?.difficulty).toBeDefined();
    expect(nestedSeg?.term?.difficulty).toBeDefined();
  });

  it('shared-boundary nesting (пир ⊂ Эпир, ¶11 seed geometry) still nests correctly', () => {
    // seed: 'пир' chars 139-142 fully inside 'Эпир' chars 138-142 (shared right edge).
    // Reproduced here with a short deterministic string of the same shape:
    // outer spans 4 chars, inner shares the outer's right edge over the last 3.
    const t = 'xxxЭпирxxx';
    const outerTerm = makeTerm({ id: 'outer', charStart: 3, charEnd: 7 }); // "Эпир"
    const innerTerm = makeTerm({ id: 'inner', charStart: 4, charEnd: 7 }); // "пир" (shared end)
    expect(t.slice(outerTerm.charStart, outerTerm.charEnd)).toBe('Эпир');
    expect(t.slice(innerTerm.charStart, innerTerm.charEnd)).toBe('пир');

    const segments = buildSourceSegments(t, [outerTerm, innerTerm]);
    const terms = termSegments(segments);
    expect(terms).toHaveLength(1);
    expect(terms[0].term?.id).toBe('outer');
    const nested = terms[0].children?.find((c) => c.kind === 'term');
    expect(nested?.term?.id).toBe('inner');
    expect(nested?.content).toBe('пир');
  });

  it('no nesting: plain adjacent terms render unchanged as siblings', () => {
    const text = 'Ромул основал Рим';
    const t1 = makeTerm({ id: 'a', charStart: 0, charEnd: 5 }); // "Ромул"
    const t2 = makeTerm({ id: 'b', charStart: 14, charEnd: 17 }); // "Рим"

    const segments = buildSourceSegments(text, [t1, t2]);
    const terms = termSegments(segments);

    expect(terms).toHaveLength(2);
    expect(terms.map((s) => s.term?.id)).toEqual(['a', 'b']);
    expect(terms.every((s) => s.children === undefined)).toBe(true);
    expect(segments.map((s) => s.content).join('')).toBe(text);
  });

  it('partial (non-containment) overlap is dropped, not nested', () => {
    // Ill-formed data: two terms overlap without one containing the other.
    // buildSourceSegments only understands full containment (one level) —
    // a partial overlap has no valid nested/sibling placement, so the
    // later-starting term is dropped, same as historic pre-nesting behaviour.
    const text = 'преторский эдикт претора';
    const t1 = makeTerm({ id: 'a', charStart: 0, charEnd: 16 }); // "преторский эдикт"
    const t2 = makeTerm({ id: 'b', charStart: 11, charEnd: 24 }); // "эдикт претора" (overlaps, not contained)

    const segments = buildSourceSegments(text, [t1, t2]);
    const terms = termSegments(segments);

    expect(terms).toHaveLength(1);
    expect(terms[0].term?.id).toBe('a');
  });
});
