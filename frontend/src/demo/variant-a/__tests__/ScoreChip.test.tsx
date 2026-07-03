import { afterEach, describe, expect, it } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';
import { ScoreChip } from '../EditorParagraph';

afterEach(cleanup);

describe('ScoreChip compact chip', () => {
  it('band classes green/yellow/red for 8.0/6.4/5.7', () => {
    for (const [score, band] of [[8.0, 'green'], [6.4, 'yellow'], [5.7, 'red']] as const) {
      const { unmount } = render(<ScoreChip label="§1" score={score} loading={false} delta={null} />);
      expect(screen.getByTestId('score-chip').className).toContain(band);
      unmount();
    }
  });

  it('null score, not loading → em-dash, §N stays (no layout collapse)', () => {
    render(<ScoreChip label="§2" score={null} loading={false} delta={null} />);
    const chip = screen.getByTestId('score-chip');
    expect(chip.textContent).toContain('§2');
    expect(chip.textContent).toContain('—');
  });

  it('loading → shimmer placeholder, §N stays', () => {
    render(<ScoreChip label="§3" score={7.1} loading={true} delta={null} />);
    const chip = screen.getByTestId('score-chip');
    expect(chip.querySelector('.va-score-chip-loading')).toBeTruthy();
    expect(chip.textContent).toContain('§3');
  });

  it('positive delta → ▲ with .up; negative → ▼ with .down', () => {
    render(<ScoreChip label="§1" score={8.0} loading={false} delta={0.4} />);
    const up = screen.getByTestId('score-chip').querySelector('.va-score-chip-delta');
    expect(up?.className).toContain('up');
    expect(up?.textContent).toContain('▲0.4');
    cleanup();
    render(<ScoreChip label="§1" score={5.7} loading={false} delta={-0.3} />);
    const down = screen.getByTestId('score-chip').querySelector('.va-score-chip-delta');
    expect(down?.className).toContain('down');
    expect(down?.textContent).toContain('▼0.3');
  });

  it('cached badge rendered when cached', () => {
    render(<ScoreChip label="§1" score={8.0} loading={false} delta={null} cached />);
    expect(screen.getByText('cached')).toBeTruthy();
  });

  it('stale badge rendered when stale', () => {
    render(<ScoreChip label="§1" score={8.0} loading={false} delta={null} stale />);
    expect(screen.getByText('stale')).toBeTruthy();
  });

  it('no stale badge when not stale', () => {
    render(<ScoreChip label="§1" score={8.0} loading={false} delta={null} />);
    expect(screen.queryByText('stale')).toBeNull();
  });
});
