import { describe, expect, it } from 'vitest';
import {
  findMatchSpan,
  findSentenceContaining,
  groupTerms,
  resolveBadge,
  summarizeGroups,
  titleCase,
  type TermWithTrace,
} from '../glossary-grouping';
import type { Paragraph, WikidataRef } from '../../api-client';

function buildParagraph(id: number, idx: number, overrides: Partial<Paragraph> = {}): Paragraph {
  return {
    id,
    idx,
    source: '',
    target: '',
    scores: [],
    scoresPrev: null,
    scoresBaseline: null,
    aggregate: null,
    aggregateBaseline: null,
    issues: [],
    terms: [],
    ...overrides,
  };
}

function buildTerm(overrides: Partial<TermWithTrace> = {}): TermWithTrace {
  return {
    id: 't1',
    paragraphId: 1,
    sourceSurface: 'Тигр',
    sourceLemma: 'тигр',
    context: 'context',
    charStart: 0,
    charEnd: 4,
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

const wd = (over: Partial<WikidataRef> = {}): WikidataRef => ({
  qid: 'Q1',
  label: 'Tigris',
  description: 'river',
  url: 'https://www.wikidata.org/wiki/Q1',
  ...over,
});

describe('groupTerms (S2 §2.1)', () => {
  it('merges inflected surface duplicates sharing lemma + qid ("Тигр"/"Тигра")', () => {
    const paragraphs = [buildParagraph(1, 0), buildParagraph(2, 1)];
    const terms = [
      buildTerm({ id: 'a', paragraphId: 1, sourceSurface: 'Тигр', sourceLemma: 'тигр', grounded: wd(), charStart: 5 }),
      buildTerm({ id: 'b', paragraphId: 2, sourceSurface: 'Тигра', sourceLemma: 'тигр', grounded: wd(), charStart: 2 }),
    ];
    const groups = groupTerms(terms, paragraphs);
    expect(groups).toHaveLength(1);
    expect(groups[0].mentions).toHaveLength(2);
    expect(groups[0].sourceSurface).toBe('Тигр'); // representative = first by appearance
  });

  it('keeps distinct entities sharing a lemma apart when qids differ', () => {
    const paragraphs = [buildParagraph(1, 0)];
    const terms = [
      buildTerm({ id: 'a', paragraphId: 1, sourceLemma: 'харбе', grounded: wd({ qid: 'Q100' }) }),
      buildTerm({ id: 'b', paragraphId: 1, sourceLemma: 'харбе', grounded: wd({ qid: 'Q200' }) }),
    ];
    expect(groupTerms(terms, paragraphs)).toHaveLength(2);
  });

  it('keeps ungrounded terms with the same lemma in one group, separate from grounded ones', () => {
    const paragraphs = [buildParagraph(1, 0)];
    const terms = [
      buildTerm({ id: 'a', paragraphId: 1, sourceLemma: 'фантом', grounded: null }),
      buildTerm({ id: 'b', paragraphId: 1, sourceLemma: 'фантом', grounded: null }),
      buildTerm({ id: 'c', paragraphId: 1, sourceLemma: 'фантом', grounded: wd() }),
    ];
    const groups = groupTerms(terms, paragraphs);
    expect(groups).toHaveLength(2);
    expect(groups.find((g) => g.qid === null)?.mentions).toHaveLength(2);
  });

  it('group difficulty is the worst among mentions (red > yellow > green)', () => {
    const paragraphs = [buildParagraph(1, 0), buildParagraph(2, 1)];
    const terms = [
      buildTerm({ id: 'a', paragraphId: 1, sourceLemma: 'x', difficulty: 'green' }),
      buildTerm({ id: 'b', paragraphId: 2, sourceLemma: 'x', difficulty: 'red' }),
    ];
    expect(groupTerms(terms, paragraphs)[0].difficulty).toBe('red');
  });

  it('group pair is the worst among mentions that have a pairAccuracy; null if none do', () => {
    const paragraphs = [buildParagraph(1, 0), buildParagraph(2, 1)];
    const withPair = groupTerms(
      [
        buildTerm({ id: 'a', paragraphId: 1, sourceLemma: 'y', pairAccuracy: 'green' }),
        buildTerm({ id: 'b', paragraphId: 2, sourceLemma: 'y', pairAccuracy: 'yellow' }),
      ],
      paragraphs,
    )[0];
    expect(withPair.pair).toBe('yellow');

    const withoutPair = groupTerms(
      [buildTerm({ id: 'a', paragraphId: 1, sourceLemma: 'z', pairAccuracy: null })],
      paragraphs,
    )[0];
    expect(withoutPair.pair).toBeNull();
  });

  it('translation: recommended||targetSurface of the first linked mention; siblings with no target inherit it', () => {
    const paragraphs = [buildParagraph(1, 0), buildParagraph(2, 1)];
    const group = groupTerms(
      [
        buildTerm({ id: 'a', paragraphId: 1, sourceLemma: 'w', targetSurface: null }),
        buildTerm({ id: 'b', paragraphId: 2, sourceLemma: 'w', targetSurface: 'Foo', recommended: 'Better Foo' }),
      ],
      paragraphs,
    )[0];
    expect(group.translation).toBe('Better Foo');
  });

  it('translation falls back to null (renders as —) when no mention has a target at all', () => {
    const paragraphs = [buildParagraph(1, 0)];
    const group = groupTerms([buildTerm({ id: 'a', paragraphId: 1, sourceLemma: 'v', targetSurface: null })], paragraphs)[0];
    expect(group.translation).toBeNull();
  });

  it('sorts groups and mentions by first appearance (paragraph idx, then charStart)', () => {
    const paragraphs = [buildParagraph(10, 0), buildParagraph(20, 1)];
    const terms = [
      buildTerm({ id: 'late', paragraphId: 20, sourceLemma: 'late', charStart: 0 }),
      buildTerm({ id: 'early', paragraphId: 10, sourceLemma: 'early', charStart: 0 }),
    ];
    const groups = groupTerms(terms, paragraphs);
    expect(groups.map((g) => g.lemma)).toEqual(['early', 'late']);
  });

  it('category pill is Title Case from term.note; empty note → null (no pill)', () => {
    const paragraphs = [buildParagraph(1, 0)];
    expect(titleCase('place')).toBe('Place');
    expect(titleCase('  ')).toBeNull();
    const group = groupTerms([buildTerm({ id: 'a', paragraphId: 1, note: 'geographical' })], paragraphs)[0];
    expect(group.category).toBe('Geographical');
  });
});

describe('summarizeGroups counters', () => {
  it('buckets rej + none together as "not grounded"', () => {
    const paragraphs = [buildParagraph(1, 0)];
    const groups = groupTerms(
      [
        buildTerm({ id: 'a', paragraphId: 1, sourceLemma: 'det1', grounded: wd(), traceJson: {} }),
        buildTerm({ id: 'b', paragraphId: 1, sourceLemma: 'llm1', traceJson: { resolved_by: 'llm_disambiguation' } }),
        buildTerm({ id: 'c', paragraphId: 1, sourceLemma: 'rej1', traceJson: { resolved_by: 'llm_rejected' } }),
        buildTerm({ id: 'd', paragraphId: 1, sourceLemma: 'none1', traceJson: { resolved_by: 'no_candidates' } }),
      ],
      paragraphs,
    );
    const summary = summarizeGroups(groups);
    expect(summary).toEqual({ groups: 4, mentions: 4, deterministic: 1, llm: 1, notGrounded: 2 });
  });
});

describe('resolveBadge (S2 §2.2 strict priority)', () => {
  it('rule 1: resolved_by exact_label / label_match → det, "label match"', () => {
    expect(resolveBadge(buildTerm({ traceJson: { resolved_by: 'exact_label' } }))).toEqual({
      tone: 'det',
      label: '◆ label match',
    });
    expect(resolveBadge(buildTerm({ traceJson: { resolved_by: 'label_match' } }))).toEqual({
      tone: 'det',
      label: '◆ label match',
    });
  });

  it('rule 1: llm_disambiguation → llm badge with model, fallback "LLM" when model absent', () => {
    expect(
      resolveBadge(buildTerm({ traceJson: { resolved_by: 'llm_disambiguation', model: 'gpt-5.5-low' } })),
    ).toEqual({ tone: 'llm', label: '◇ LLM · gpt-5.5-low' });
    expect(resolveBadge(buildTerm({ traceJson: { resolved_by: 'llm_disambiguation' } }))).toEqual({
      tone: 'llm',
      label: '◇ LLM · LLM',
    });
  });

  it('rule 1: llm_rejected → rej badge', () => {
    expect(resolveBadge(buildTerm({ traceJson: { resolved_by: 'llm_rejected' } }))).toEqual({
      tone: 'rej',
      label: '◇ LLM rejected all',
    });
  });

  it('rule 1: no_candidates → none badge', () => {
    expect(resolveBadge(buildTerm({ traceJson: { resolved_by: 'no_candidates' } }))).toEqual({
      tone: 'none',
      label: '○ no candidates',
    });
  });

  it('rule 2 (degradation): trace empty object but qid grounded → "grounded", no path', () => {
    expect(resolveBadge(buildTerm({ traceJson: {}, grounded: wd() }))).toEqual({
      tone: 'det',
      label: '◆ grounded',
    });
  });

  it('rule 2 (degradation): traceJson missing entirely but qid grounded → same "grounded" result', () => {
    const term = buildTerm({ grounded: wd() });
    delete (term as { traceJson?: unknown }).traceJson;
    expect(resolveBadge(term)).toEqual({ tone: 'det', label: '◆ grounded' });
  });

  it('rule 3 heuristic: trace non-empty, no resolved_by, qid + multiple candidates → llm', () => {
    const term = buildTerm({
      grounded: wd(),
      candidates: [wd({ qid: 'Q1' }), wd({ qid: 'Q2' })],
      traceJson: { query: { lemma_hits: 1 } },
    });
    expect(resolveBadge(term)).toEqual({ tone: 'llm', label: '◇ LLM · LLM' });
  });

  it('rule 3 heuristic: trace non-empty, no resolved_by, qid + exactly one candidate → det', () => {
    const term = buildTerm({
      grounded: wd(),
      candidates: [wd()],
      traceJson: { query: { lemma_hits: 1 } },
    });
    expect(resolveBadge(term)).toEqual({ tone: 'det', label: '◆ label match' });
  });

  it('rule 3 heuristic: trace non-empty, no resolved_by, no qid but candidates existed → rej', () => {
    const term = buildTerm({
      grounded: null,
      candidates: [wd(), wd({ qid: 'Q2' })],
      traceJson: { search: { hits: 2 } },
    });
    expect(resolveBadge(term)).toEqual({ tone: 'rej', label: '◇ LLM rejected all' });
  });

  it('rule 4: nothing at all (no trace, no qid, no candidates) → none', () => {
    expect(resolveBadge(buildTerm())).toEqual({ tone: 'none', label: '○ no candidates' });
  });

  it('never throws on an unrecognized resolved_by value', () => {
    expect(() => resolveBadge(buildTerm({ traceJson: { resolved_by: 'something_future' } }))).not.toThrow();
    expect(resolveBadge(buildTerm({ traceJson: { resolved_by: 'something_future' } })).tone).toBe('none');
  });
});

describe('context highlighting helpers (S2 §2.3)', () => {
  it('findMatchSpan splits around the first case-insensitive occurrence', () => {
    expect(findMatchSpan('Дальнейшее продвижение сутиев привело в Заиорданье, где', 'заиорданье')).toEqual({
      before: 'Дальнейшее продвижение сутиев привело в ',
      match: 'Заиорданье',
      after: ', где',
    });
  });

  it('findMatchSpan returns null when the needle is absent or empty', () => {
    expect(findMatchSpan('some text', 'missing')).toBeNull();
    expect(findMatchSpan('some text', '')).toBeNull();
  });

  it('findSentenceContaining extracts just the sentence with the match', () => {
    const text = 'First sentence here. Their further southward advance brought the Sutians into Transjordan. Third sentence.';
    expect(findSentenceContaining(text, 'Transjordan')).toBe(
      'Their further southward advance brought the Sutians into Transjordan.',
    );
  });

  it('findSentenceContaining returns null when the needle is not present', () => {
    expect(findSentenceContaining('First. Second.', 'nowhere')).toBeNull();
  });
});
