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

describe('groupTerms — display-level stemmer fallback (wave5 §5, unnormalized source_lemma)', () => {
  it('merges "Тигр" (grounded) with "Тигра" (ungrounded) when source_lemma === source_surface for both', () => {
    const paragraphs = [buildParagraph(1, 0), buildParagraph(2, 1)];
    const terms = [
      buildTerm({ id: 'a', paragraphId: 1, sourceSurface: 'Тигр', sourceLemma: 'Тигр', grounded: wd({ qid: 'Q35591', label: 'Tigris' }), difficulty: 'yellow' }),
      buildTerm({ id: 'b', paragraphId: 2, sourceSurface: 'Тигра', sourceLemma: 'Тигра', grounded: null, difficulty: 'red' }),
    ];
    const groups = groupTerms(terms, paragraphs);
    expect(groups).toHaveLength(1);
    expect(groups[0].qid).toBe('Q35591'); // merged group shows the grounded qid
    expect(groups[0].mentions).toHaveLength(2);
    expect(groups[0].difficulty).toBe('red'); // worst-of across the merged mentions
  });

  it('merges "Евфрат" (grounded) with "Евфрата" (ungrounded) the same way', () => {
    const paragraphs = [buildParagraph(1, 0), buildParagraph(2, 1)];
    const terms = [
      buildTerm({ id: 'a', paragraphId: 1, sourceSurface: 'Евфрат', sourceLemma: 'Евфрат', grounded: wd({ qid: 'Q39644', label: 'Euphrates' }) }),
      buildTerm({ id: 'b', paragraphId: 2, sourceSurface: 'Евфрата', sourceLemma: 'Евфрата', grounded: null }),
    ];
    const groups = groupTerms(terms, paragraphs);
    expect(groups).toHaveLength(1);
    expect(groups[0].qid).toBe('Q39644');
    expect(groups[0].mentions).toHaveLength(2);
  });

  it('"Ура"/"Ур" stay separate: both <=4 chars so no ending is ever stripped, and their stems differ', () => {
    const paragraphs = [buildParagraph(1, 0), buildParagraph(2, 1)];
    const terms = [
      buildTerm({ id: 'a', paragraphId: 1, sourceSurface: 'Ура', sourceLemma: 'Ура', grounded: wd({ qid: 'Q11701', label: 'Ur' }) }),
      buildTerm({ id: 'b', paragraphId: 2, sourceSurface: 'Ур', sourceLemma: 'Ур', grounded: null }),
    ];
    const groups = groupTerms(terms, paragraphs);
    expect(groups).toHaveLength(2); // 'ура' !== 'ур' — merge only happens when stems actually match
  });

  it('never merges two grounded groups into each other, even when their heuristic stems coincide', () => {
    const paragraphs = [buildParagraph(1, 0), buildParagraph(2, 1)];
    const terms = [
      buildTerm({ id: 'a', paragraphId: 1, sourceSurface: 'Марса', sourceLemma: 'Марса', grounded: wd({ qid: 'Q111' }) }),
      buildTerm({ id: 'b', paragraphId: 2, sourceSurface: 'Марс', sourceLemma: 'Марс', grounded: wd({ qid: 'Q222' }) }),
    ];
    const groups = groupTerms(terms, paragraphs);
    expect(groups).toHaveLength(2); // same stem ('марс') but different qids — never collapse
    expect(groups.map((g) => g.qid).sort()).toEqual(['Q111', 'Q222']);
  });

  it('leaves an ungrounded stem-group unmerged when it would be ambiguous between two grounded qids', () => {
    const paragraphs = [buildParagraph(1, 0), buildParagraph(2, 1), buildParagraph(3, 2)];
    const terms = [
      buildTerm({ id: 'a', paragraphId: 1, sourceSurface: 'Марса', sourceLemma: 'Марса', grounded: wd({ qid: 'Q111' }) }),
      buildTerm({ id: 'b', paragraphId: 2, sourceSurface: 'Марс', sourceLemma: 'Марс', grounded: wd({ qid: 'Q222' }) }),
      buildTerm({ id: 'c', paragraphId: 3, sourceSurface: 'Марсу', sourceLemma: 'Марсу', grounded: null }),
    ];
    const groups = groupTerms(terms, paragraphs);
    // 3 rows: the two grounded qids stay put, and the ambiguous ungrounded
    // stem-group ("марс" matches both) is left standalone rather than
    // guessing which entity it belongs to.
    expect(groups).toHaveLength(3);
    expect(groups.filter((g) => g.qid === null)).toHaveLength(1);
  });

  it('does not stem an already-normalized lemma (sourceLemma !== sourceSurface bypasses the heuristic)', () => {
    const paragraphs = [buildParagraph(1, 0)];
    const group = groupTerms(
      [buildTerm({ id: 'a', paragraphId: 1, sourceSurface: 'Тигра', sourceLemma: 'тигр', grounded: null })],
      paragraphs,
    )[0];
    expect(group.lemma).toBe('тигр');
  });

  it('multi-word phrase "Среднем Тигре" stems per-word and stays a distinct row from "Тигр"', () => {
    const paragraphs = [buildParagraph(1, 0), buildParagraph(2, 1)];
    const terms = [
      buildTerm({ id: 'a', paragraphId: 1, sourceSurface: 'Тигр', sourceLemma: 'Тигр', grounded: wd({ qid: 'Q35591' }) }),
      buildTerm({ id: 'b', paragraphId: 2, sourceSurface: 'Среднем Тигре', sourceLemma: 'Среднем Тигре', grounded: null }),
    ];
    const groups = groupTerms(terms, paragraphs);
    expect(groups).toHaveLength(2); // correct — a distinct phrase, not a duplicate of "Тигр"
  });

  it('summarizeGroups counts the merged pair as a single grounded row, not two', () => {
    const paragraphs = [buildParagraph(1, 0), buildParagraph(2, 1)];
    const terms = [
      buildTerm({ id: 'a', paragraphId: 1, sourceSurface: 'Тигр', sourceLemma: 'Тигр', grounded: wd({ qid: 'Q35591' }) }),
      buildTerm({ id: 'b', paragraphId: 2, sourceSurface: 'Тигра', sourceLemma: 'Тигра', grounded: null }),
    ];
    const summary = summarizeGroups(groupTerms(terms, paragraphs));
    expect(summary.groups).toBe(1);
    expect(summary.mentions).toBe(2);
    expect(summary.deterministic).toBe(1);
    expect(summary.notGrounded).toBe(0);
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

describe('resolveBadge — ambiguous/unresolved states (e2e addendum findings)', () => {
  const base = {
    id: '1', paragraphId: 1, sourceSurface: 'Евфрата', sourceLemma: 'Евфрата',
    context: '', charStart: 0, charEnd: 7, difficulty: 'yellow' as const,
    grounded: null, targetSurface: 'Euphrates', pairAccuracy: null,
    recommended: null, note: '',
  };
  const cands = [
    { qid: 'Q26690015', label: 'Operation Euphrates Shield', description: '' },
    { qid: 'Q1728989', label: 'Karasu River', description: '' },
  ];

  it('maps ambiguous_candidates to the ambiguous badge with candidate count', () => {
    const badge = resolveBadge({
      ...base, candidates: cands,
      traceJson: { decision: { resolved_by: 'ambiguous_candidates' } },
    } as never);
    expect(badge.tone).toBe('rej');
    expect(badge.label).toBe('◇ ambiguous · 2 candidates');
  });

  it('maps judge_unavailable to the ambiguous badge', () => {
    const badge = resolveBadge({
      ...base, candidates: cands,
      traceJson: { decision: { resolved_by: 'judge_unavailable' } },
    } as never);
    expect(badge.tone).toBe('rej');
    expect(badge.label).toBe('◇ ambiguous · 2 candidates');
  });

  it('unknown resolved_by with candidates degrades to ambiguous, not "no candidates"', () => {
    const badge = resolveBadge({
      ...base, candidates: cands,
      traceJson: { decision: { resolved_by: 'mystery_future_value' } },
    } as never);
    expect(badge.tone).toBe('rej');
    expect(badge.label).toBe('◇ ambiguous · 2 candidates');
  });

  it('unknown resolved_by without candidates stays "no candidates"', () => {
    const badge = resolveBadge({
      ...base, candidates: [],
      traceJson: { decision: { resolved_by: 'mystery_future_value' } },
    } as never);
    expect(badge.tone).toBe('none');
    expect(badge.label).toBe('○ no candidates');
  });
});
