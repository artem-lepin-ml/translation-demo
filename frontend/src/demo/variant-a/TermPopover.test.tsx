import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, fireEvent } from '@testing-library/react';
import TermPopover from './TermPopover';
import type { Term } from '../api-client';

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
