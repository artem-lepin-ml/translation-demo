import { afterEach, describe, expect, it } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';
import { ScoreChip, buildScoreChipTooltip } from '../EditorParagraph';
import type { Criterion, Score } from '../../api-client';

afterEach(cleanup);

const criteria: Criterion[] = [
  { id: 'accuracy', name: 'Accuracy', modelName: 'm', prompt: '', scaleMin: 0, scaleMax: 10, weight: 1, color: '#7aa2f7', enabled: true },
  { id: 'fluency', name: 'Fluency', modelName: 'm', prompt: '', scaleMin: 0, scaleMax: 10, weight: 1, color: '#9ece6a', enabled: true },
  { id: 'cultural', name: 'Cultural Adaptation', modelName: 'm', prompt: '', scaleMin: 0, scaleMax: 10, weight: 1, color: '#bb9af7', enabled: false },
];

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

  // S5 — hover tooltip: per-criterion breakdown + provenance.
  describe('hover tooltip (title attribute)', () => {
    it('with no criteria/scores passed, tooltip still shows the aggregate line', () => {
      render(<ScoreChip label="§1" score={8.4} loading={false} delta={null} />);
      expect(screen.getByTestId('score-chip').title).toBe('§1 aggregate: 8.4');
    });

    it('breaks down enabled criteria only, in order, skipping disabled ones', () => {
      const scores: Score[] = [
        { criterionId: 'accuracy', value: 9.0, summary: '' },
        { criterionId: 'fluency', value: 7.5, summary: '' },
        { criterionId: 'cultural', value: 2.0, summary: '' },
      ];
      render(
        <ScoreChip
          label="§2"
          score={8.25}
          loading={false}
          delta={null}
          criteria={criteria}
          scores={scores}
        />,
      );
      const title = screen.getByTestId('score-chip').title;
      expect(title).toBe('§2 aggregate: 8.3\nAccuracy: 9.0\nFluency: 7.5');
      expect(title).not.toContain('Cultural Adaptation');
    });

    it('a criterion with no score yet renders "—" in the tooltip, not blank/undefined', () => {
      const scores: Score[] = [{ criterionId: 'accuracy', value: 9.0, summary: '' }];
      render(
        <ScoreChip label="§3" score={null} loading={false} delta={null} criteria={criteria} scores={scores} />,
      );
      const title = screen.getByTestId('score-chip').title;
      expect(title).toBe('§3 aggregate: —\nAccuracy: 9.0\nFluency: —');
    });

    it('while loading, every line (aggregate + each criterion) shows "…", never blank', () => {
      const scores: Score[] = [{ criterionId: 'accuracy', value: 9.0, summary: '' }];
      render(
        <ScoreChip label="§4" score={7.1} loading={true} delta={null} criteria={criteria} scores={scores} />,
      );
      const title = screen.getByTestId('score-chip').title;
      expect(title).toBe('§4 aggregate: …\nAccuracy: …\nFluency: …');
    });

    it('appends cached/stale provenance notes when set', () => {
      render(<ScoreChip label="§1" score={8.0} loading={false} delta={null} cached stale />);
      const title = screen.getByTestId('score-chip').title;
      expect(title).toContain('Cached: offline fallback estimate, not a live judgment');
      expect(title).toContain('Stale: scores refer to an earlier version of this paragraph');
    });

    it('buildScoreChipTooltip is a pure function matching the rendered title', () => {
      const scores: Score[] = [{ criterionId: 'accuracy', value: 6.0, summary: '' }];
      expect(buildScoreChipTooltip('§5', 6.0, false, criteria, scores)).toBe(
        '§5 aggregate: 6.0\nAccuracy: 6.0\nFluency: —',
      );
    });
  });
});
