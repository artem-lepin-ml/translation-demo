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
