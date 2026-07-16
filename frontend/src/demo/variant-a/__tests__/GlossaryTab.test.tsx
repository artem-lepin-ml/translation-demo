import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import GlossaryTab from '../GlossaryTab';
import type { Paragraph } from '../../api-client';
import type { TermWithTrace } from '../glossary-grouping';

afterEach(cleanup);

function buildParagraph(id: number, idx: number, overrides: Partial<Paragraph> = {}): Paragraph {
  return {
    id,
    idx,
    source: '',
    target: 'Their further southward advance brought the Sutians into Transjordan.',
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
    sourceSurface: 'Заиорданье',
    sourceLemma: 'заиорданье',
    context: 'Их поход привёл в Заиорданье, где они смешались с местными.',
    charStart: 0,
    charEnd: 10,
    difficulty: 'green',
    grounded: { qid: 'Q1097394', label: 'Transjordan', description: 'region east of the Jordan River', url: 'https://www.wikidata.org/wiki/Q1097394' },
    candidates: [],
    targetSurface: 'Transjordan',
    pairAccuracy: 'green',
    recommended: null,
    note: 'geographical',
    ...overrides,
  };
}

describe('GlossaryTab empty state (status-aware, EMNLP sprint)', () => {
  it('renders the neutral empty state when termsStatus is absent/none', () => {
    render(<GlossaryTab terms={[]} paragraphs={[]} sourceLang="ru" targetLang="en" />);
    expect(screen.getByText('No terminology extracted for this document.')).toBeTruthy();
  });

  it('renders the running message while extraction is in progress', () => {
    render(<GlossaryTab terms={[]} paragraphs={[]} sourceLang="ru" targetLang="en" termsStatus="running" />);
    expect(
      screen.getByText('Terminology pipeline is running — terms appear as paragraphs complete.'),
    ).toBeTruthy();
  });

  it('renders the failure message when extraction failed', () => {
    render(<GlossaryTab terms={[]} paragraphs={[]} sourceLang="ru" targetLang="en" termsStatus="failed" />);
    expect(screen.getByText('Terminology extraction failed for this document.')).toBeTruthy();
  });

  it('renders the neutral empty state for termsStatus="done" with zero terms found', () => {
    render(<GlossaryTab terms={[]} paragraphs={[]} sourceLang="ru" targetLang="en" termsStatus="done" />);
    expect(screen.getByText('No terminology extracted for this document.')).toBeTruthy();
  });

  it('shows the populated table instead of the empty state once terms exist, even mid-run', () => {
    const paragraphs = [buildParagraph(1, 0)];
    const terms = [buildTerm()];
    render(
      <GlossaryTab
        terms={terms}
        paragraphs={paragraphs}
        sourceLang="ru"
        targetLang="en"
        termsStatus="running"
      />,
    );
    expect(screen.queryByText(/Terminology pipeline is running/)).toBeNull();
    expect(screen.getAllByText('Transjordan').length).toBeGreaterThan(0);
  });
});

describe('GlossaryTab grouped table', () => {
  it('renders one row per group with combined Source/Translation headers and the summary line', () => {
    const paragraphs = [buildParagraph(1, 0)];
    const terms = [buildTerm()];
    render(<GlossaryTab terms={terms} paragraphs={paragraphs} sourceLang="ru" targetLang="en" />);
    expect(screen.getByText('Source · Russian')).toBeTruthy();
    expect(screen.getByText('Translation · English')).toBeTruthy();
    expect(screen.getByText(/Grouped by lemma \+ entity/)).toBeTruthy();
    expect(screen.getAllByText('Transjordan').length).toBeGreaterThan(0);
  });

  it('degradation: empty trace_json + grounded qid shows "grounded" badge with no path stepper', () => {
    const paragraphs = [buildParagraph(1, 0)];
    const terms = [buildTerm({ traceJson: {} })];
    render(<GlossaryTab terms={terms} paragraphs={paragraphs} sourceLang="ru" targetLang="en" />);
    expect(screen.getByText('◆ grounded')).toBeTruthy();

    fireEvent.click(screen.getByText('◆ grounded').closest('tr')!);
    expect(screen.getByText(/^Context$/)).toBeTruthy();
    expect(screen.queryByText(/Grounding path/)).toBeNull();
  });

  it('mention click calls onMentionClick with the paragraph idx (Document-tab navigation)', () => {
    const onMentionClick = vi.fn();
    const paragraphs = [buildParagraph(5, 4), buildParagraph(9, 8)];
    const terms = [
      buildTerm({ id: 'a', paragraphId: 5, charStart: 0 }),
      buildTerm({ id: 'b', paragraphId: 9, charStart: 0 }),
    ];
    render(
      <GlossaryTab terms={terms} paragraphs={paragraphs} sourceLang="ru" targetLang="en" onMentionClick={onMentionClick} />,
    );

    // Expand the group (×2 mentions) to reveal the "All mentions" list.
    fireEvent.click(screen.getByText('×2').closest('tr')!);
    const secondMention = screen.getByText('§9');
    fireEvent.click(secondMention);

    expect(onMentionClick).toHaveBeenCalledWith(8);
  });

  it('clicking the Wikidata link does not also toggle the row (stopPropagation)', () => {
    const paragraphs = [buildParagraph(1, 0)];
    const terms = [buildTerm()];
    render(<GlossaryTab terms={terms} paragraphs={paragraphs} sourceLang="ru" targetLang="en" />);
    const link = screen.getByRole('link', { name: 'Transjordan' });
    fireEvent.click(link);
    expect(screen.queryByText(/Grounding path|Context/)).toBeNull();
  });
});

// ─── Real flat trace_json rendering (debugger-glossary-reddot-trace.md §2) ──
//
// The backend's real `trace_json` shape is flat: {v, config, queries,
// search_source, candidates, exact_matches, resolved_by, judge, chosen_qid,
// canon_en, n_api_calls, latency_ms} (label_first.py::_result). These tests
// use that real shape (not the earlier forward-looking nested guess) to
// prove the Matched column, the Grounding-path steps, and the Judge decision
// block all render live data instead of "none" / "Skipped — no trace".
describe('GlossaryTab — real flat trace_json rendering (BUG-6 / debugger fixes)', () => {
  function buildLiveTerm(overrides: Partial<TermWithTrace> = {}): TermWithTrace {
    return buildTerm({
      id: 'qin',
      sourceSurface: 'Цинь',
      sourceLemma: 'Цинь',
      difficulty: 'yellow',
      grounded: { qid: 'Q7181', label: 'Qin dynasty', description: 'Chinese dynasty', url: 'https://www.wikidata.org/wiki/Q7181' },
      candidates: [
        { qid: 'Q7181', label: 'Qin dynasty', description: 'Chinese dynasty', url: 'https://www.wikidata.org/wiki/Q7181' },
        { qid: 'Q49751', label: 'Guqin', description: 'Chinese string instrument', url: 'https://www.wikidata.org/wiki/Q49751' },
      ],
      traceJson: {
        resolved_by: 'llm_disambiguation',
        queries: [{ q: 'Цинь', kind: 'lemma', mechanism: 'wbsearchentities', n_hits: 2 }],
        search_source: 'wbsearchentities',
        candidates: [
          { qid: 'Q7181', label_ru: 'Цинь', label_en: 'Qin dynasty', description: 'Chinese dynasty',
            matched: { kind: 'label_ru', value: 'Цинь', query: 'Цинь' } },
          { qid: 'Q49751', label_ru: 'Цинь (инструмент)', label_en: 'Guqin', description: 'Chinese string instrument',
            matched: null },
        ],
        exact_matches: [
          { qid: 'Q7181', label_ru: 'Цинь', matched: { kind: 'label_ru', value: 'Цинь', query: 'Цинь' } },
        ],
        judge: {
          response: { qid: 'Q7181', reason: 'The sentence discusses the historical Chinese state, not the instrument.' },
          error: null, latency_ms: 812, cache_hit: false,
        },
        chosen_qid: 'Q7181',
        n_api_calls: 2,
        latency_ms: 950,
      },
      ...overrides,
    });
  }

  function renderAndExpand() {
    const paragraphs = [buildParagraph(1, 0)];
    const terms = [buildLiveTerm()];
    render(<GlossaryTab terms={terms} paragraphs={paragraphs} sourceLang="ru" targetLang="en" />);
    fireEvent.click(screen.getByText('×1').closest('tr')!);
  }

  it('Matched column shows the real match kind, and "—" (not "none") for a candidate that never matched', () => {
    renderAndExpand();
    expect(screen.getByText('label')).toBeTruthy();     // Q7181's real matched.kind
    expect(screen.queryByText('none')).toBeNull();       // the old always-on fallback must be gone
    expect(screen.getAllByTitle('No match provenance recorded for this candidate').length).toBe(1);
  });

  it('Grounding-path panel renders live search/candidate/decision data instead of "Skipped — no trace" for every step', () => {
    renderAndExpand();
    // Each step's title (.va-gl-step-t) is real, live-pipeline content — not
    // the dead nested-shape fallback that rendered "Skipped" for every one of
    // the 4 steps on every live-pipeline term before this fix.
    expect(screen.getByText('wbsearchentities')).toBeTruthy();        // search step: real search_source
    expect(screen.getByText('2 candidates found')).toBeTruthy();      // candidates step: real count
    expect(screen.getByText('Exactly 1 exact match')).toBeTruthy();   // exact step: real exact_matches
    expect(screen.getByText('llm disambiguation')).toBeTruthy();      // decision step: real resolved_by
    expect(screen.getByText(/resolved_by: llm_disambiguation/)).toBeTruthy();
    expect(screen.queryAllByText('Skipped').length).toBe(0);
  });

  it('Judge decision block shows the real reason from traceJson.judge.response.reason', () => {
    renderAndExpand();
    expect(screen.getByText(/historical Chinese state/)).toBeTruthy();
  });

  it('#4: renders a query row\'s search strategy as a distinct dim label (prefix/full-text/sitelink map)', () => {
    const paragraphs = [buildParagraph(1, 0)];
    const terms = [buildLiveTerm({
      traceJson: {
        resolved_by: 'llm_disambiguation',
        queries: [
          { q: 'приевфратский', kind: 'lemma', mechanism: 'wbsearchentities', n_hits: 0, strategy: 'prefix' },
          { q: 'Цинь', kind: 'surface', mechanism: 'cirrussearch', n_hits: 3, strategy: 'cirrus' },
          { q: 'Q7181', kind: 'lemma', mechanism: 'sitelinks', n_hits: 1, strategy: 'sitelink' },
        ],
        search_source: 'wbsearchentities',
        candidates: [],
      },
    })];
    render(<GlossaryTab terms={terms} paragraphs={paragraphs} sourceLang="ru" targetLang="en" />);
    fireEvent.click(screen.getByText('×1').closest('tr')!);

    // All three strategy labels are distinct and visible — not 3 identical rows.
    expect(screen.getByText('prefix ·')).toBeTruthy();
    expect(screen.getByText('full-text ·')).toBeTruthy();
    expect(screen.getByText('sitelink ·')).toBeTruthy();
  });

  it('#4: defensive fallback — a query row without `strategy` (older trace) renders kind+q as before, no stray label', () => {
    renderAndExpand(); // buildLiveTerm's default queries carry no `strategy` field
    expect(screen.getByText('lemma')).toBeTruthy();
    expect(screen.queryByText('prefix ·')).toBeNull();
    expect(screen.queryByText('full-text ·')).toBeNull();
    expect(screen.queryByText('sitelink ·')).toBeNull();
  });

  it('falls back to the plain candidates list (all "—" Matched) for legacy/seed rows with trace_json={}', () => {
    const paragraphs = [buildParagraph(1, 0)];
    const terms = [buildLiveTerm({ traceJson: {} })];
    render(<GlossaryTab terms={terms} paragraphs={paragraphs} sourceLang="ru" targetLang="en" />);
    fireEvent.click(screen.getByText('×1').closest('tr')!);
    // Grounding path is not shown at all for empty trace_json (hasTrace gate,
    // unchanged behavior) but the Candidates table still renders from the
    // top-level `candidates` field, honestly reporting no match provenance.
    expect(screen.queryByText(/Grounding path/)).toBeNull();
    expect(screen.getAllByTitle('No match provenance recorded for this candidate').length).toBe(2);
    expect(screen.queryByText('none')).toBeNull();
  });
});
