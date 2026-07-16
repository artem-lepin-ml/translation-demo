import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, fireEvent, screen } from '@testing-library/react';
import TermPopover from './TermPopover';
import type { Term } from '../api-client';
import type { TermWithTrace } from './glossary-grouping';

afterEach(cleanup);

const term: Term = {
  id: 't1',
  paragraphId: 1,
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
};

describe('TermPopover Escape-to-close (LOW-a)', () => {
  it('calls onClose when Escape is pressed', () => {
    const onClose = vi.fn();
    const rect = { bottom: 0, left: 0, top: 0, right: 0, width: 0, height: 0 } as DOMRect;
    render(<TermPopover term={term} rect={rect} onClose={onClose} />);

    fireEvent.keyDown(document, { key: 'Escape' });

    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('does not call onClose for an unrelated key', () => {
    const onClose = vi.fn();
    const rect = { bottom: 0, left: 0, top: 0, right: 0, width: 0, height: 0 } as DOMRect;
    render(<TermPopover term={term} rect={rect} onClose={onClose} />);

    fireEvent.keyDown(document, { key: 'a' });

    expect(onClose).not.toHaveBeenCalled();
  });
});

describe('TermPopover Ambiguous senses (same dead-field fix as the Glossary tab Candidates table, BUG-6/wave2)', () => {
  const rect = { bottom: 0, left: 0, top: 0, right: 0, width: 0, height: 0 } as DOMRect;

  it('falls back to the plain WikidataRef candidates list when there is no trace_json', () => {
    const withPlainCandidates: Term = {
      ...term,
      difficulty: 'yellow',
      candidates: [
        { qid: 'Q1', label: 'Sense one', description: 'first sense', url: 'https://www.wikidata.org/wiki/Q1' },
      ],
    };
    render(<TermPopover term={withPlainCandidates} rect={rect} onClose={vi.fn()} />);

    expect(screen.getByText('Ambiguous senses')).toBeTruthy();
    expect(screen.getByText('Sense one')).toBeTruthy();
    expect(screen.getByText(/first sense/)).toBeTruthy();
  });

  it('BUG-6: prefers trace_json.candidates when the top-level candidates dropped to [] (judge_rejected)', () => {
    const judgeRejected: TermWithTrace = {
      ...term,
      difficulty: 'yellow',
      candidates: [],   // dead per BUG-6: empties for judge_rejected even though real candidates existed
      traceJson: {
        resolved_by: 'llm_rejected',
        candidates: [
          { qid: 'Q10', label_en: 'Rejected sense A', description: 'desc A', matched: null },
          { qid: 'Q11', label_ru: 'Отклонённый смысл B', description: 'desc B', matched: { kind: 'label_ru', value: 'x', query: 'y' } },
        ],
      },
    };
    render(<TermPopover term={judgeRejected} rect={rect} onClose={vi.fn()} />);

    expect(screen.getByText('Ambiguous senses')).toBeTruthy();
    expect(screen.getByText('Rejected sense A')).toBeTruthy();
    expect(screen.getByText('Отклонённый смысл B')).toBeTruthy();
    // Trace-derived candidates get a real, QID-derived Wikidata link.
    expect(screen.getByText('Rejected sense A').closest('a')).toHaveProperty(
      'href', 'https://www.wikidata.org/wiki/Q10',
    );
  });

  it('does not render the Ambiguous senses block when both the plain and trace candidate lists are empty', () => {
    render(<TermPopover term={term} rect={rect} onClose={vi.fn()} />);
    expect(screen.queryByText('Ambiguous senses')).toBeNull();
  });
});
