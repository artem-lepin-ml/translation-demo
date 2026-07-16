import { afterEach, describe, expect, it, vi } from 'vitest';
import { render, screen, fireEvent, cleanup, within, waitFor } from '@testing-library/react';
import InspectorPanel from './InspectorPanel';
import * as apiClient from '../api-client';
import type { Paragraph, Revision } from '../api-client';

// HistoryBlock fetches GET /paragraphs/{id}/revisions on mount (component-owned
// fetch) — default to empty so tests that don't care about revision history
// don't hit real fetch() in jsdom.
vi.mock('../api-client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api-client')>();
  return { ...actual, getRevisions: vi.fn().mockResolvedValue({ revisions: [] }) };
});

afterEach(() => {
  cleanup();
  vi.mocked(apiClient.getRevisions).mockResolvedValue({ revisions: [] });
});

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
        onAccept={vi.fn()}
        onDismiss={vi.fn()}
        onRefine={vi.fn()}
        onEvaluate={vi.fn()}
        onRetryFailed={vi.fn()}
        visibleIssues={[]}
        onRestoreRevision={vi.fn()}
        documentResetNonce={0}
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
        onAccept={vi.fn()}
        onDismiss={vi.fn()}
        onRefine={vi.fn()}
        onEvaluate={onEvaluate}
        onRetryFailed={vi.fn()}
        visibleIssues={[]}
        onRestoreRevision={vi.fn()}
        documentResetNonce={0}
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
        onAccept={vi.fn()}
        onDismiss={vi.fn()}
        onRefine={vi.fn()}
        onEvaluate={vi.fn()}
        onRetryFailed={onRetryFailed}
        visibleIssues={[]}
        onRestoreRevision={vi.fn()}
        documentResetNonce={0}
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
        onAccept={vi.fn()}
        onDismiss={vi.fn()}
        onRefine={vi.fn()}
        onEvaluate={vi.fn()}
        onRetryFailed={vi.fn()}
        visibleIssues={[]}
        onRestoreRevision={vi.fn()}
        documentResetNonce={0}
      />,
    );
    expect((screen.getByTestId('evaluate-para') as HTMLButtonElement).disabled).toBe(true);
  });
});

describe('InspectorPanel stale hint (explicit re-eval)', () => {
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
    onRefine: vi.fn(),
    onEvaluate: vi.fn(),
    onRetryFailed: vi.fn(),
    visibleIssues: [],
    onRestoreRevision: vi.fn(),
    documentResetNonce: 0,
  };

  it('shows the stale hint when evalState.stale', () => {
    render(
      <InspectorPanel
        {...baseProps}
        evalState={{ loading: false, cached: false, cachedAt: null, failedCriterionIds: [], error: null, stale: true }}
      />,
    );
    expect(screen.getByText(/Scores are for a previous version/)).toBeTruthy();
  });
});

describe('InspectorPanel Refine paragraph (EMNLP sprint — replaces per-paragraph Accept all)', () => {
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
    onEvaluate: vi.fn(),
    onRetryFailed: vi.fn(),
    onRestoreRevision: vi.fn(),
    documentResetNonce: 0,
  };

  const openIssueWithSuggestion = {
    id: '1', paragraphId: 1, criterionId: 'accuracy', targetFragment: '', sourceFragment: '',
    explanation: 'x', suggestion: 'fix', severity: 'minor', mqmCategory: null, status: 'open',
  };

  const idleEval = { loading: false, cached: false, cachedAt: null, failedCriterionIds: [], error: null, stale: false };

  it('disables Refine with a "No open findings" tooltip when there are no open issues', () => {
    render(<InspectorPanel {...baseProps} onRefine={vi.fn()} visibleIssues={[]} evalState={idleEval} />);
    const btn = screen.getByTestId('refine-paragraph') as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
    expect(btn.title).toBe('No open findings');
  });

  it('enables Refine with the aggregate tooltip when open findings exist', () => {
    render(
      <InspectorPanel
        {...baseProps}
        onRefine={vi.fn()}
        visibleIssues={[openIssueWithSuggestion as never]}
        evalState={idleEval}
      />,
    );
    const btn = screen.getByTestId('refine-paragraph') as HTMLButtonElement;
    expect(btn.disabled).toBe(false);
    expect(btn.title).toBe('Aggregate all findings and rewrite with the refiner model');
    expect(btn.textContent).toBe('Refine paragraph ✦');
  });

  it('calls onRefine when clicked', () => {
    const onRefine = vi.fn();
    render(
      <InspectorPanel
        {...baseProps}
        onRefine={onRefine}
        visibleIssues={[openIssueWithSuggestion as never]}
        evalState={idleEval}
      />,
    );
    fireEvent.click(screen.getByTestId('refine-paragraph'));
    expect(onRefine).toHaveBeenCalledTimes(1);
  });

  it('shows "Refining…" and disables Evaluate/Accept/Dismiss during the refine phase', () => {
    render(
      <InspectorPanel
        {...baseProps}
        onRefine={vi.fn()}
        visibleIssues={[openIssueWithSuggestion as never]}
        evalState={{ ...idleEval, refineStage: 'refining' }}
      />,
    );
    const btn = screen.getByTestId('refine-paragraph') as HTMLButtonElement;
    expect(btn.textContent).toBe('Refining…');
    expect(btn.disabled).toBe(true);
    expect((screen.getByTestId('evaluate-para') as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByText('Dismiss') as HTMLButtonElement).disabled).toBe(true);
  });

  it('shows "Re-scoring…" during the chained-evaluate phase', () => {
    render(
      <InspectorPanel
        {...baseProps}
        onRefine={vi.fn()}
        visibleIssues={[openIssueWithSuggestion as never]}
        evalState={{ ...idleEval, refineStage: 'rescoring' }}
      />,
    );
    expect(screen.getByTestId('refine-paragraph').textContent).toBe('Re-scoring…');
  });

  it('BUG-5: Refine is also present (and clickable) on the Scores tab, not just Issues', () => {
    const onRefine = vi.fn();
    render(
      <InspectorPanel
        {...baseProps}
        tab="scores"
        onRefine={onRefine}
        visibleIssues={[openIssueWithSuggestion as never]}
        evalState={idleEval}
      />,
    );
    const btn = screen.getByTestId('refine-paragraph') as HTMLButtonElement;
    expect(btn.disabled).toBe(false);
    fireEvent.click(btn);
    expect(onRefine).toHaveBeenCalledTimes(1);
  });
});

describe('InspectorPanel tab isolation (BUG-2: non-active tab body is unmounted, not merely hidden, ' +
  'frontend-developer-stability-wave1)', () => {
  const criteria = [
    { id: 'accuracy', name: 'Accuracy', modelName: 'm', prompt: '', scaleMin: 1, scaleMax: 10,
      weight: 1, color: '#888', enabled: true },
  ] as never;
  const evalState = { loading: false, cached: false, cachedAt: null, failedCriterionIds: [], error: null, stale: false };
  const paragraph = {
    id: 1, idx: 0, source: 's', target: 't',
    issues: [{ id: '1', paragraphId: 1, criterionId: 'accuracy', targetFragment: '', sourceFragment: '',
      explanation: 'x', suggestion: 'fix', severity: 'minor', mqmCategory: null, status: 'open' }],
    scores: [{ criterionId: 'accuracy', value: 8, summary: '' }],
    scoresPrev: null, scoresBaseline: null, aggregate: 8, aggregateBaseline: null, aggregatePrev: null,
  } as unknown as Paragraph;
  const base = {
    onTabChange: vi.fn(), activeCriteria: new Set<string>(['accuracy']), criteria,
    isCollapsed: false, onToggleCollapse: vi.fn(), onAccept: vi.fn(),
    onDismiss: vi.fn(), onRefine: vi.fn(), onEvaluate: vi.fn(), onRetryFailed: vi.fn(),
    onRestoreRevision: vi.fn(), evalState, paragraph, visibleIssues: paragraph.issues,
    documentResetNonce: 0,
  };

  it('Scores tab: the Issues body (Accept/Dismiss buttons) is not in the DOM at all', () => {
    render(<InspectorPanel {...base} tab="scores" />);
    expect(screen.queryByText('Dismiss')).toBeNull();
    expect(screen.queryByText('Accept')).toBeNull();
    // The Scores body IS present.
    expect(screen.getByText('Aggregate')).toBeTruthy();
  });

  it('Issues tab: the Scores body (Aggregate row) is not in the DOM at all', () => {
    render(<InspectorPanel {...base} tab="issues" />);
    expect(screen.queryByText('Aggregate')).toBeNull();
    // The Issues body IS present.
    expect(screen.getByText('Accept')).toBeTruthy();
  });
});

describe('InspectorPanel resolved/passive-note visibility (Б2)', () => {
  const para = { id: 1, idx: 0, source: 's', target: 't', issues: [], scores: [],
    scoresPrev: null, scoresBaseline: null, aggregate: null, aggregateBaseline: null,
    aggregatePrev: null } as unknown as Paragraph;
  const base = {
    tab: 'issues' as const, onTabChange: vi.fn(), paragraph: para,
    activeCriteria: new Set<string>(), criteria: [], isCollapsed: false,
    onToggleCollapse: vi.fn(), onAccept: vi.fn(),
    onDismiss: vi.fn(), onRefine: vi.fn(), onEvaluate: vi.fn(), onRetryFailed: vi.fn(),
    onRestoreRevision: vi.fn(),
    documentResetNonce: 0,
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
    isCollapsed: false, onToggleCollapse: vi.fn(), onAccept: vi.fn(),
    onDismiss: vi.fn(), onRefine: vi.fn(), onEvaluate: vi.fn(), onRetryFailed: vi.fn(),
    onRestoreRevision: vi.fn(),
    documentResetNonce: 0,
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

  it('shows a "cached" mini-badge on every scored criterion when the response was a cache fallback', () => {
    render(
      <InspectorPanel
        {...base}
        paragraph={mkParagraph('key-a', 'key-a')}
        evalState={{ ...evalState, cached: true }}
      />,
    );
    expect(screen.getByTitle('Offline fallback estimate, not a live judgment')).toBeTruthy();
  });

  it('does not show the "cached" mini-badge on a live (non-cache) response', () => {
    render(<InspectorPanel {...base} paragraph={mkParagraph('key-a', 'key-a')} />);
    expect(screen.queryByTitle('Offline fallback estimate, not a live judgment')).toBeNull();
  });

  it('hides the "different criteria set" note when scores and scoresPrev criteriaKey match', () => {
    render(<InspectorPanel {...base} paragraph={mkParagraph('key-a', 'key-a')} />);
    expect(screen.queryByText('different criteria set')).toBeNull();
  });
});

describe('InspectorPanel Revision history (S5 §3.2-3.3)', () => {
  const criteria = [
    { id: 'accuracy', name: 'Accuracy', modelName: 'm', prompt: '', scaleMin: 1, scaleMax: 10,
      weight: 1, color: '#888', enabled: true },
  ] as never;
  const evalState = { loading: false, cached: false, cachedAt: null, failedCriterionIds: [], error: null, stale: false };
  const base = {
    tab: 'scores' as const, onTabChange: vi.fn(), activeCriteria: new Set<string>(), criteria,
    isCollapsed: false, onToggleCollapse: vi.fn(), onAccept: vi.fn(),
    onDismiss: vi.fn(), onRefine: vi.fn(), onEvaluate: vi.fn(), onRetryFailed: vi.fn(),
    evalState, visibleIssues: [],
    documentResetNonce: 0,
  };
  const paragraph = {
    id: 1, idx: 0, source: 's', target: 't', issues: [],
    scores: [{ criterionId: 'accuracy', value: 8, summary: '' }],
    scoresPrev: null, scoresBaseline: null, aggregate: 8, aggregateBaseline: null, aggregatePrev: null,
  } as unknown as Paragraph;

  const revisions: Revision[] = [
    { id: 3, origin: 'edit', createdAt: new Date().toISOString(), text: 'current text', aggregate: 7.9, isBest: false, isCurrent: true },
    { id: 2, origin: 'translate', createdAt: new Date(Date.now() - 18 * 60000).toISOString(), text: 'best text', aggregate: 8.4, isBest: true, isCurrent: false },
    { id: 1, origin: 'seed', createdAt: new Date(Date.now() - 2 * 3600000).toISOString(), text: 'seed text', aggregate: 6.5, isBest: false, isCurrent: false },
  ];

  it('renders revision rows with best marker, current tag, and a Best-N header summary', async () => {
    vi.mocked(apiClient.getRevisions).mockResolvedValue({ revisions });
    render(<InspectorPanel {...base} paragraph={paragraph} onRestoreRevision={vi.fn()} />);

    const block = await screen.findByTestId('revision-history');
    expect(within(block).getByText(/Best 8.4/, { selector: '.va-history-best' })).toBeTruthy();
    expect(within(block).getByText('current')).toBeTruthy();
    expect(within(block).getAllByText('⭰ Best').length).toBe(1); // the row badge (header uses "Best 8.4")
    // Current revision cannot restore itself
    expect((screen.getByTestId('history-restore-3') as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByTestId('history-restore-2') as HTMLButtonElement).disabled).toBe(false);
  });

  it('shows "not scored" for a revision with no aggregate', async () => {
    vi.mocked(apiClient.getRevisions).mockResolvedValue({
      revisions: [{ id: 1, origin: 'apply_edit', createdAt: new Date().toISOString(), text: 't', aggregate: null, isBest: false, isCurrent: true }],
    });
    render(<InspectorPanel {...base} paragraph={paragraph} onRestoreRevision={vi.fn()} />);
    const row = await screen.findByTestId('history-row-1');
    expect(within(row).getByText(/not scored/)).toBeTruthy();
  });

  it('clicking Restore calls onRestoreRevision with the revision id', async () => {
    vi.mocked(apiClient.getRevisions).mockResolvedValue({ revisions });
    const onRestoreRevision = vi.fn().mockResolvedValue(undefined);
    render(<InspectorPanel {...base} paragraph={paragraph} onRestoreRevision={onRestoreRevision} />);
    await screen.findByTestId('revision-history');
    const callsBeforeRestore = vi.mocked(apiClient.getRevisions).mock.calls.length;

    fireEvent.click(screen.getByTestId('history-restore-2'));
    expect(onRestoreRevision).toHaveBeenCalledWith(2);
    await waitFor(() => expect(vi.mocked(apiClient.getRevisions).mock.calls.length).toBe(callsBeforeRestore + 1));
  });

  it('re-fetches the revisions list wholesale after a successful restore, instead of keeping the stale pre-restore array (wave5 §4.1)', async () => {
    // Mount: server has 2 revisions (current edit + best seed). Restore
    // succeeds and the backend now has a 3rd row (the new restore revision) —
    // proving the fix re-fetches rather than locally splicing the old list.
    const afterRestore: Revision[] = [
      { id: 4, origin: 'restore', createdAt: new Date().toISOString(), text: 'best text', aggregate: null, isBest: false, isCurrent: true },
      ...revisions,
    ];
    vi.mocked(apiClient.getRevisions)
      .mockResolvedValueOnce({ revisions })
      .mockResolvedValueOnce({ revisions: afterRestore });
    const onRestoreRevision = vi.fn().mockResolvedValue(undefined);
    render(<InspectorPanel {...base} paragraph={paragraph} onRestoreRevision={onRestoreRevision} />);
    await screen.findByTestId('revision-history');
    expect(screen.getAllByTestId(/^history-row-/).length).toBe(3);
    const callsBeforeRestore = vi.mocked(apiClient.getRevisions).mock.calls.length;

    fireEvent.click(screen.getByTestId('history-restore-2'));

    // The restore call resolves before the re-fetch fires (no local splice
    // in between) and the component ends up showing the freshly-fetched list.
    await waitFor(() => expect(screen.getAllByTestId(/^history-row-/).length).toBe(4));
    expect(screen.getByTestId('history-row-4')).toBeTruthy();
    expect(vi.mocked(apiClient.getRevisions).mock.calls.length).toBe(callsBeforeRestore + 1);
  });

  it('does not refetch revisions when the restore itself fails', async () => {
    vi.mocked(apiClient.getRevisions).mockResolvedValue({ revisions });
    const onRestoreRevision = vi.fn().mockRejectedValue(new Error('POST /paragraphs/1/restore → 500'));
    render(<InspectorPanel {...base} paragraph={paragraph} onRestoreRevision={onRestoreRevision} />);
    await screen.findByTestId('revision-history');
    const callsBeforeRestore = vi.mocked(apiClient.getRevisions).mock.calls.length;

    fireEvent.click(screen.getByTestId('history-restore-2'));
    await waitFor(() => expect(onRestoreRevision).toHaveBeenCalled());
    // Give any (incorrect) follow-up refetch a tick to happen, then assert it didn't.
    await new Promise((r) => setTimeout(r, 0));
    expect(vi.mocked(apiClient.getRevisions).mock.calls.length).toBe(callsBeforeRestore);
  });

  it('clicking a row toggles a read-only text preview', async () => {
    vi.mocked(apiClient.getRevisions).mockResolvedValue({ revisions });
    render(<InspectorPanel {...base} paragraph={paragraph} onRestoreRevision={vi.fn()} />);
    await screen.findByTestId('revision-history');

    expect(screen.queryByTestId('history-preview')).toBeNull();
    fireEvent.click(screen.getByTestId('history-row-2'));
    expect(screen.getByTestId('history-preview').textContent).toBe('best text');
    fireEvent.click(screen.getByTestId('history-row-2'));
    expect(screen.queryByTestId('history-preview')).toBeNull();
  });

  it('caps the row list at 8 with a "+N more" expander', async () => {
    const many: Revision[] = Array.from({ length: 11 }, (_, i) => ({
      id: i + 1, origin: 'edit', createdAt: new Date().toISOString(), text: `t${i}`,
      aggregate: 7, isBest: false, isCurrent: i === 0,
    }));
    vi.mocked(apiClient.getRevisions).mockResolvedValue({ revisions: many });
    render(<InspectorPanel {...base} paragraph={paragraph} onRestoreRevision={vi.fn()} />);

    await screen.findByTestId('revision-history');
    expect(screen.getAllByTestId(/^history-row-/).length).toBe(8);
    fireEvent.click(screen.getByTestId('history-show-more'));
    await waitFor(() => expect(screen.getAllByTestId(/^history-row-/).length).toBe(11));
  });

  it('renders nothing when the paragraph has no revisions', async () => {
    vi.mocked(apiClient.getRevisions).mockResolvedValue({ revisions: [] });
    render(<InspectorPanel {...base} paragraph={paragraph} onRestoreRevision={vi.fn()} />);
    await waitFor(() => expect(apiClient.getRevisions).toHaveBeenCalled());
    expect(screen.queryByTestId('revision-history')).toBeNull();
  });

  it('SUSPECTED-1 (wave2): re-fetches revisions when documentResetNonce changes, even though paragraph.id stayed the same (Document Reset)', async () => {
    // Reset rewrites the paragraph's target/revision but keeps the same
    // paragraph id, so before this fix a plain `paragraph.id`-keyed effect
    // never re-fired and the panel kept showing the stale pre-reset list.
    const afterReset: Revision[] = [
      { id: 5, origin: 'seed', createdAt: new Date().toISOString(), text: 'seed text', aggregate: null, isBest: false, isCurrent: true },
    ];
    vi.mocked(apiClient.getRevisions)
      .mockResolvedValueOnce({ revisions })
      .mockResolvedValueOnce({ revisions: afterReset });
    const { rerender } = render(
      <InspectorPanel {...base} paragraph={paragraph} onRestoreRevision={vi.fn()} documentResetNonce={0} />,
    );
    await screen.findByTestId('revision-history');
    expect(screen.getAllByTestId(/^history-row-/).length).toBe(3);
    const callsBeforeReset = vi.mocked(apiClient.getRevisions).mock.calls.length;

    // Same paragraph object/id — only the nonce changes, simulating
    // store.resetDoc()'s bump after a successful reset.
    rerender(
      <InspectorPanel {...base} paragraph={paragraph} onRestoreRevision={vi.fn()} documentResetNonce={1} />,
    );

    await waitFor(() => expect(vi.mocked(apiClient.getRevisions).mock.calls.length).toBe(callsBeforeReset + 1));
    expect(screen.getAllByTestId(/^history-row-/).length).toBe(1);
    expect(screen.getByTestId('history-row-5')).toBeTruthy();
  });

  it('does NOT re-fetch on an unrelated re-render where neither paragraph.id nor documentResetNonce changed', async () => {
    vi.mocked(apiClient.getRevisions).mockResolvedValue({ revisions });
    const { rerender } = render(
      <InspectorPanel {...base} paragraph={paragraph} onRestoreRevision={vi.fn()} documentResetNonce={0} />,
    );
    await screen.findByTestId('revision-history');
    const callsBefore = vi.mocked(apiClient.getRevisions).mock.calls.length;

    // Unrelated re-render (a fresh onAccept callback identity, same
    // paragraph/nonce) — must not unmount/re-fetch HistoryBlock.
    rerender(
      <InspectorPanel {...base} onAccept={vi.fn()} paragraph={paragraph} onRestoreRevision={vi.fn()} documentResetNonce={0} />,
    );

    expect(vi.mocked(apiClient.getRevisions).mock.calls.length).toBe(callsBefore);
  });
});
