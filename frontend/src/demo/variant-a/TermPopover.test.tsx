import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, fireEvent, screen, within } from '@testing-library/react';
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

describe('TermPopover Candidate senses (same dead-field fix as the Glossary tab Candidates table, BUG-6/wave2; renamed from "Ambiguous senses" per #3c)', () => {
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

    expect(screen.getByText('Candidate senses')).toBeTruthy();
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

    expect(screen.getByText('Candidate senses')).toBeTruthy();
    expect(screen.getByText('Rejected sense A')).toBeTruthy();
    expect(screen.getByText('Отклонённый смысл B')).toBeTruthy();
    // Trace-derived candidates get a real, QID-derived Wikidata link.
    expect(screen.getByText('Rejected sense A').closest('a')).toHaveProperty(
      'href', 'https://www.wikidata.org/wiki/Q10',
    );
  });

  it('does not render the Candidate senses block when both the plain and trace candidate lists are empty', () => {
    render(<TermPopover term={term} rect={rect} onClose={vi.fn()} />);
    expect(screen.queryByText('Candidate senses')).toBeNull();
  });

  it('marks the candidate matching term.grounded.qid as chosen (✓ + bold), leaves the rest unmarked', () => {
    const withGrounded: TermWithTrace = {
      ...term,
      grounded: { qid: 'Q7181', label: 'Qin dynasty', description: '', url: 'https://www.wikidata.org/wiki/Q7181' },
      candidates: [],
      traceJson: {
        candidates: [
          { qid: 'Q7181', label_en: 'Qin dynasty', description: 'Chinese dynasty', matched: null },
          { qid: 'Q49751', label_en: 'Guqin', description: 'Chinese string instrument', matched: null },
        ],
      },
    };
    render(<TermPopover term={withGrounded} rect={rect} onClose={vi.fn()} />);

    // Scope to the "Candidate senses" row — "Qin dynasty" also appears once
    // more, unmarked, in the Wikidata row above (the resolved-entity link).
    const candidatesRow = screen.getByText('Candidate senses').parentElement!;
    const chosenRow = within(candidatesRow).getByText('Qin dynasty').closest('div')!;
    expect(chosenRow.textContent).toContain('✓');
    expect(chosenRow.style.fontWeight).toBe('600');

    const otherRow = within(candidatesRow).getByText('Guqin').closest('div')!;
    expect(otherRow.textContent).not.toContain('✓');
    expect(otherRow.style.fontWeight).toBe('');
  });
});

describe('TermPopover Note row removed (#3b — note duplicates the category badge already shown elsewhere)', () => {
  const rect = { bottom: 0, left: 0, top: 0, right: 0, width: 0, height: 0 } as DOMRect;

  it('never renders a "Note" row, even when term.note is set', () => {
    const withNote: Term = { ...term, note: 'Place' };
    render(<TermPopover term={withNote} rect={rect} onClose={vi.fn()} />);
    expect(screen.queryByText('Note')).toBeNull();
    expect(screen.queryByText('Place')).toBeNull();
  });
});

describe('TermPopover viewport clamp (#3a — popover must stay fully on-screen and scroll internally)', () => {
  const originalInnerHeight = window.innerHeight;
  afterEach(() => {
    Object.defineProperty(window, 'innerHeight', { value: originalInnerHeight, configurable: true });
  });

  it('clamps top so the popover, at its max possible height, never extends past the viewport bottom', () => {
    Object.defineProperty(window, 'innerHeight', { value: 500, configurable: true });
    const rect = { bottom: 480, left: 0, top: 400, right: 0, width: 0, height: 0 } as DOMRect;
    const { container } = render(<TermPopover term={term} rect={rect} onClose={vi.fn()} />);

    const popover = container.querySelector('.va-term-popover') as HTMLElement;
    const top = parseFloat(popover.style.top);
    const margin = 16;
    const maxPopoverHeight = Math.min(window.innerHeight * 0.8, window.innerHeight - margin * 2);

    expect(top).toBeGreaterThanOrEqual(margin);
    expect(top + maxPopoverHeight).toBeLessThanOrEqual(window.innerHeight - margin + 0.001);
  });

  it('still positions right below the click when there is ample room (unchanged happy path)', () => {
    Object.defineProperty(window, 'innerHeight', { value: 1200, configurable: true });
    const rect = { bottom: 100, left: 0, top: 60, right: 0, width: 0, height: 0 } as DOMRect;
    const { container } = render(<TermPopover term={term} rect={rect} onClose={vi.fn()} />);

    const popover = container.querySelector('.va-term-popover') as HTMLElement;
    expect(parseFloat(popover.style.top)).toBe(108); // rect.bottom (100) + 8
  });
});
