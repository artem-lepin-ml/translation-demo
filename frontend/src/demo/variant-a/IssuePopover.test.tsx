import { afterEach, describe, expect, it, vi } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';
import IssuePopover, { clampTop } from './IssuePopover';
import type { Issue } from '../api-client';

afterEach(cleanup);

function iss(id: string, over: Partial<Issue> = {}): Issue {
  return {
    id, paragraphId: 1, criterionId: 'accuracy', targetFragment: 'f', sourceFragment: '',
    explanation: 'why', suggestion: 'fix', severity: 'minor', mqmCategory: null, status: 'open',
    ...over,
  };
}
const rect = { bottom: 100, left: 40 } as DOMRect;

describe('clampTop (pure positioning)', () => {
  it('sits below the anchor when it fits', () => {
    expect(clampTop(100, 200, 1000)).toBe(108);
  });
  it('never goes above 8px on a short viewport with a tall stack', () => {
    expect(clampTop(600, 700, 650)).toBe(8);
  });
  it('lifts up so the bottom edge stays in view', () => {
    expect(clampTop(900, 300, 1000)).toBe(692); // 1000 - 300 - 8
  });
});

describe('IssuePopover visibility', () => {
  it('renders open issues in the scroll container', () => {
    render(<IssuePopover issues={[iss('1')]} criteria={[]} rect={rect}
      onAccept={vi.fn()} onDismiss={vi.fn()} onClose={vi.fn()} />);
    expect(screen.getByTestId('issue-popover')).toBeTruthy();
    expect(screen.getByText('why')).toBeTruthy();
  });
  it('does NOT render an outdated issue', () => {
    render(<IssuePopover issues={[iss('1', { status: 'outdated', explanation: 'gone' })]}
      criteria={[]} rect={rect} onAccept={vi.fn()} onDismiss={vi.fn()} onClose={vi.fn()} />);
    expect(screen.queryByText('gone')).toBeNull();
    expect(screen.queryByTestId('issue-popover')).toBeNull();
  });
  it('renders no blocking backdrop element', () => {
    const { container } = render(<IssuePopover issues={[iss('1')]} criteria={[]} rect={rect}
      onAccept={vi.fn()} onDismiss={vi.fn()} onClose={vi.fn()} />);
    expect(container.querySelector('.va-popover-backdrop')).toBeNull();
  });
  it('renders a suggestion-less issue as a passive note with no Accept/Dismiss buttons', () => {
    render(<IssuePopover issues={[iss('1', { suggestion: '', explanation: 'advice only' })]}
      criteria={[]} rect={rect} onAccept={vi.fn()} onDismiss={vi.fn()} onClose={vi.fn()} />);
    expect(screen.getByText('advice only')).toBeTruthy();
    expect(screen.queryByText('Accept')).toBeNull();
    expect(screen.queryByText('Dismiss')).toBeNull();
    expect(screen.getByText(/no concrete suggestion/i)).toBeTruthy();
  });
  it('renders an issue WITH a suggestion with Accept/Dismiss buttons present', () => {
    render(<IssuePopover issues={[iss('1')]} criteria={[]} rect={rect}
      onAccept={vi.fn()} onDismiss={vi.fn()} onClose={vi.fn()} />);
    expect(screen.getByText('Accept')).toBeTruthy();
    expect(screen.getByText('Dismiss')).toBeTruthy();
  });
});

describe('IssuePopover outside-click / escape close (non-blocking backdrop)', () => {
  it('closes on an outside mousedown, and the listener is attached/detached with mount lifecycle', () => {
    const addSpy = vi.spyOn(document, 'addEventListener');
    const removeSpy = vi.spyOn(document, 'removeEventListener');
    const onClose = vi.fn();
    const { unmount } = render(<IssuePopover issues={[iss('1')]} criteria={[]} rect={rect}
      onAccept={vi.fn()} onDismiss={vi.fn()} onClose={onClose} />);

    expect(addSpy).toHaveBeenCalledWith('mousedown', expect.any(Function), true);

    const outside = document.createElement('div');
    document.body.appendChild(outside);
    outside.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
    expect(onClose).toHaveBeenCalledTimes(1);

    unmount();
    expect(removeSpy).toHaveBeenCalledWith('mousedown', expect.any(Function), true);
    document.body.removeChild(outside);
    addSpy.mockRestore();
    removeSpy.mockRestore();
  });

  it('does NOT close on a mousedown inside the popover', () => {
    const onClose = vi.fn();
    render(<IssuePopover issues={[iss('1')]} criteria={[]} rect={rect}
      onAccept={vi.fn()} onDismiss={vi.fn()} onClose={onClose} />);
    screen.getByTestId('issue-popover').dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
    expect(onClose).not.toHaveBeenCalled();
  });

  it('closes on Escape', () => {
    const onClose = vi.fn();
    render(<IssuePopover issues={[iss('1')]} criteria={[]} rect={rect}
      onAccept={vi.fn()} onDismiss={vi.fn()} onClose={onClose} />);
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
