import { afterEach, describe, expect, it, vi } from 'vitest';
import { render, screen, fireEvent, cleanup, within } from '@testing-library/react';
import InspectorPanel from './InspectorPanel';
import type { Paragraph } from '../api-client';

afterEach(cleanup);

describe('InspectorPanel error banner (H3)', () => {
  it('renders the evaluate failure', () => {
    render(
      <InspectorPanel
        tab="issues"
        onTabChange={vi.fn()}
        paragraph={null}
        activeCriteria={new Set()}
        evalState={{
          loading: false,
          cached: false,
          cachedAt: null,
          failedCriterionIds: [],
          error: 'POST /paragraphs/1/evaluate → 500',
          stale: false,
        }}
        criteria={[]}
        isCollapsed={false}
        onToggleCollapse={vi.fn()}
        acceptAllSummary={null}
        onAccept={vi.fn()}
        onDismiss={vi.fn()}
        onAcceptAll={vi.fn()}
        onEvaluate={vi.fn()}
        onRetryFailed={vi.fn()}
        visibleIssues={[]}
      />,
    );
    expect(screen.getByText(/Evaluate failed/)).toBeTruthy();
    expect(screen.getByText(/500/)).toBeTruthy();
  });
});

describe('InspectorPanel evaluate affordance (B1 dead-paragraph revival)', () => {
  const paragraph = {
    id: 1,
    idx: 0,
    source: 'src',
    target: 'tgt',
    issues: [],
    scores: [],
    scoresPrev: null,
    scoresBaseline: null,
    aggregate: null,
    aggregateBaseline: null,
    aggregatePrev: null,
  } as unknown as Paragraph;

  it('calls evaluateParagraph (via onEvaluate) exactly once when clicked', () => {
    const onEvaluate = vi.fn();
    render(
      <InspectorPanel
        tab="issues"
        onTabChange={vi.fn()}
        paragraph={paragraph}
        activeCriteria={new Set()}
        evalState={{ loading: false, cached: false, cachedAt: null, failedCriterionIds: [], error: null, stale: false }}
        criteria={[]}
        isCollapsed={false}
        onToggleCollapse={vi.fn()}
        acceptAllSummary={null}
        onAccept={vi.fn()}
        onDismiss={vi.fn()}
        onAcceptAll={vi.fn()}
        onEvaluate={onEvaluate}
        onRetryFailed={vi.fn()}
        visibleIssues={[]}
      />,
    );
    fireEvent.click(screen.getByTestId('evaluate-para'));
    expect(onEvaluate).toHaveBeenCalledTimes(1);
  });

  it('shows a Retry-failed button that fires onRetryFailed with the failed ids', () => {
    const onRetryFailed = vi.fn();
    render(
      <InspectorPanel
        tab="issues"
        onTabChange={vi.fn()}
        paragraph={paragraph}
        activeCriteria={new Set()}
        evalState={{
          loading: false, cached: false, cachedAt: null,
          failedCriterionIds: ['style', 'cultural'], error: null, stale: false,
        }}
        criteria={[{ id: 'accuracy' }, { id: 'style' }, { id: 'cultural' }] as never}
        isCollapsed={false}
        onToggleCollapse={vi.fn()}
        acceptAllSummary={null}
        onAccept={vi.fn()}
        onDismiss={vi.fn()}
        onAcceptAll={vi.fn()}
        onEvaluate={vi.fn()}
        onRetryFailed={onRetryFailed}
        visibleIssues={[]}
      />,
    );
    expect(screen.getByText(/Failed: style, cultural/)).toBeTruthy();
    fireEvent.click(screen.getByTestId('retry-failed'));
    expect(onRetryFailed).toHaveBeenCalledWith(['style', 'cultural']);
  });

  it('disables the evaluate button while loading', () => {
    render(
      <InspectorPanel
        tab="issues"
        onTabChange={vi.fn()}
        paragraph={paragraph}
        activeCriteria={new Set()}
        evalState={{ loading: true, cached: false, cachedAt: null, failedCriterionIds: [], error: null, stale: false }}
        criteria={[]}
        isCollapsed={false}
        onToggleCollapse={vi.fn()}
        acceptAllSummary={null}
        onAccept={vi.fn()}
        onDismiss={vi.fn()}
        onAcceptAll={vi.fn()}
        onEvaluate={vi.fn()}
        onRetryFailed={vi.fn()}
        visibleIssues={[]}
      />,
    );
    expect((screen.getByTestId('evaluate-para') as HTMLButtonElement).disabled).toBe(true);
  });
});

describe('InspectorPanel stale hint and accept-all summary (explicit re-eval)', () => {
  const paragraph = {
    id: 1, idx: 0, source: 'src', target: 'tgt', issues: [], scores: [],
    scoresPrev: null, scoresBaseline: null, aggregate: null,
    aggregateBaseline: null, aggregatePrev: null,
  } as unknown as Paragraph;

  const baseProps = {
    tab: 'issues' as const,
    onTabChange: vi.fn(),
    paragraph,
    activeCriteria: new Set<string>(),
    criteria: [],
    isCollapsed: false,
    onToggleCollapse: vi.fn(),
    onAccept: vi.fn(),
    onDismiss: vi.fn(),
    onAcceptAll: vi.fn(),
    onEvaluate: vi.fn(),
    onRetryFailed: vi.fn(),
    visibleIssues: [],
  };

  it('shows the stale hint when evalState.stale', () => {
    render(
      <InspectorPanel
        {...baseProps}
        acceptAllSummary={null}
        evalState={{ loading: false, cached: false, cachedAt: null, failedCriterionIds: [], error: null, stale: true }}
      />,
    );
    expect(screen.getByText(/Scores are for a previous version/)).toBeTruthy();
  });

  it('shows the accept-all summary line with applied and outdated counts', () => {
    render(
      <InspectorPanel
        {...baseProps}
        acceptAllSummary={{ applied: 5, outdated: 6 }}
        evalState={{ loading: false, cached: false, cachedAt: null, failedCriterionIds: [], error: null, stale: true }}
      />,
    );
    const line = screen.getByTestId('accept-all-summary');
    expect(line.textContent).toContain('Applied 5');
    expect(line.textContent).toContain('6 outdated (overlapped by earlier edits)');
  });

  it('hides the summary line when acceptAllSummary is null', () => {
    render(
      <InspectorPanel
        {...baseProps}
        acceptAllSummary={null}
        evalState={{ loading: false, cached: false, cachedAt: null, failedCriterionIds: [], error: null, stale: false }}
      />,
    );
    expect(screen.queryByTestId('accept-all-summary')).toBeNull();
  });
});

describe('InspectorPanel resolved/passive-note visibility (Б2)', () => {
  const para = { id: 1, idx: 0, source: 's', target: 't', issues: [], scores: [],
    scoresPrev: null, scoresBaseline: null, aggregate: null, aggregateBaseline: null,
    aggregatePrev: null } as unknown as Paragraph;
  const base = {
    tab: 'issues' as const, onTabChange: vi.fn(), paragraph: para,
    activeCriteria: new Set<string>(), criteria: [], isCollapsed: false,
    onToggleCollapse: vi.fn(), acceptAllSummary: null, onAccept: vi.fn(),
    onDismiss: vi.fn(), onAcceptAll: vi.fn(), onEvaluate: vi.fn(), onRetryFailed: vi.fn(),
    evalState: { loading: false, cached: false, cachedAt: null, failedCriterionIds: [], error: null, stale: false },
  };
  const mk = (id: string, status: string, expl: string, suggestion = 's') => ({
    id, paragraphId: 1, criterionId: 'accuracy', targetFragment: '', sourceFragment: '',
    explanation: expl, suggestion, severity: 'minor', mqmCategory: null, status,
  });

  it('hides outdated issues entirely', () => {
    render(<InspectorPanel {...base} visibleIssues={[mk('9', 'outdated', 'GONE') as never]} />);
    expect(screen.queryByText('GONE')).toBeNull();
    expect(screen.getByText(/No active issues/)).toBeTruthy();
  });

  it('hides an accepted issue — it vanishes, not struck through', () => {
    render(<InspectorPanel {...base} visibleIssues={[mk('8', 'accepted', 'ACCEPTED_HIST') as never]} />);
    expect(screen.queryByText('ACCEPTED_HIST')).toBeNull();
    expect(screen.getByText(/No active issues/)).toBeTruthy();
  });

  it('hides a dismissed issue — it vanishes, not struck through', () => {
    render(<InspectorPanel {...base} visibleIssues={[mk('7', 'dismissed', 'DISMISSED_HIST') as never]} />);
    expect(screen.queryByText('DISMISSED_HIST')).toBeNull();
    expect(screen.getByText(/No active issues/)).toBeTruthy();
  });

  it('renders an open issue card without a closed/struck-through treatment', () => {
    render(<InspectorPanel {...base} visibleIssues={[mk('1', 'open', 'ACTIVE') as never]} />);
    const card = screen.getByText('ACTIVE').closest('.va-insp-issue-card');
    expect(card).not.toBeNull();
    expect(card!.className).not.toContain('closed');
    expect((card as HTMLElement).style.textDecoration).toBe('');
  });

  it('header count matches the number of visible (open) issue cards', () => {
    render(
      <InspectorPanel
        {...base}
        visibleIssues={[
          mk('1', 'open', 'ONE'),
          mk('2', 'accepted', 'TWO_HIDDEN'),
          mk('3', 'dismissed', 'THREE_HIDDEN'),
          mk('4', 'outdated', 'FOUR_HIDDEN'),
        ] as never}
      />,
    );
    expect(screen.getByText('1 active issue')).toBeTruthy();
    expect(screen.getAllByText('ONE').length).toBeGreaterThan(0);
    expect(screen.queryByText('TWO_HIDDEN')).toBeNull();
    expect(screen.queryByText('THREE_HIDDEN')).toBeNull();
    expect(screen.queryByText('FOUR_HIDDEN')).toBeNull();
  });

  it('exposes the scroll container test-id', () => {
    render(<InspectorPanel {...base} visibleIssues={[mk('1', 'open', 'x') as never]} />);
    expect(screen.getByTestId('inspector-issues-scroll')).toBeTruthy();
  });

  it('renders a suggestion-less open issue as a passive note with no Accept/Dismiss buttons', () => {
    render(
      <InspectorPanel
        {...base}
        visibleIssues={[mk('1', 'open', 'NOTE_EXPL', '') as never]}
      />,
    );
    expect(screen.getByText('NOTE_EXPL')).toBeTruthy();
    const card = screen.getByText('NOTE_EXPL').closest('.va-insp-issue-card');
    expect(card).not.toBeNull();
    expect(card!.className).toContain('va-insp-issue-note');
    expect(within(card as HTMLElement).queryByText('Accept')).toBeNull();
    expect(within(card as HTMLElement).queryByText('Dismiss')).toBeNull();
  });

  it('renders an open issue WITH a suggestion as an actionable card (Accept + Dismiss present)', () => {
    render(
      <InspectorPanel
        {...base}
        visibleIssues={[mk('1', 'open', 'ACTIONABLE', 'fix it') as never]}
      />,
    );
    const card = screen.getByText('ACTIONABLE').closest('.va-insp-issue-card');
    expect(card).not.toBeNull();
    expect(card!.className).not.toContain('va-insp-issue-note');
    expect(within(card as HTMLElement).getByText('Accept')).toBeTruthy();
    expect(within(card as HTMLElement).getByText('Dismiss')).toBeTruthy();
  });
});

describe('InspectorPanel criteria-key mismatch note (Б3.6)', () => {
  const criteria = [
    { id: 'accuracy', name: 'Accuracy', modelName: 'm', prompt: '', scaleMin: 1, scaleMax: 10,
      weight: 1, color: '#888', enabled: true },
  ] as never;
  const evalState = { loading: false, cached: false, cachedAt: null, failedCriterionIds: [], error: null, stale: false };
  const base = {
    tab: 'scores' as const, onTabChange: vi.fn(), activeCriteria: new Set<string>(), criteria,
    isCollapsed: false, onToggleCollapse: vi.fn(), acceptAllSummary: null, onAccept: vi.fn(),
    onDismiss: vi.fn(), onAcceptAll: vi.fn(), onEvaluate: vi.fn(), onRetryFailed: vi.fn(),
    evalState, visibleIssues: [],
  };
  const mkParagraph = (latestKey: string, prevKey: string) => ({
    id: 1, idx: 0, source: 's', target: 't', issues: [],
    scores: [{ criterionId: 'accuracy', value: 8, summary: '', criteriaKey: latestKey }],
    scoresPrev: [{ criterionId: 'accuracy', value: 7, summary: '', criteriaKey: prevKey }],
    scoresBaseline: null, aggregate: 8, aggregateBaseline: null, aggregatePrev: 7,
  }) as unknown as Paragraph;

  it('shows the "different criteria set" note when scores and scoresPrev criteriaKey differ', () => {
    render(<InspectorPanel {...base} paragraph={mkParagraph('key-a', 'key-b')} />);
    expect(screen.getByText('different criteria set')).toBeTruthy();
  });

  it('hides the "different criteria set" note when scores and scoresPrev criteriaKey match', () => {
    render(<InspectorPanel {...base} paragraph={mkParagraph('key-a', 'key-a')} />);
    expect(screen.queryByText('different criteria set')).toBeNull();
  });
});
