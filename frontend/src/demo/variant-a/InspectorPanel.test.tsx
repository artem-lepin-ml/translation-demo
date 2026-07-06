import { afterEach, describe, expect, it, vi } from 'vitest';
import { render, screen, fireEvent, cleanup, within, waitFor } from '@testing-library/react';
import InspectorPanel from './InspectorPanel';
import * as apiClient from '../api-client';
import type { Paragraph, Revision } from '../api-client';

// HistoryBlock fetches GET /paragraphs/{id}/revisions on mount (component-owned
// fetch, same pattern as SettingsTab's getBudget) — default to empty so tests
// that don't care about revision history don't hit real fetch() in jsdom.
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
        acceptAllSummary={null}
        onAccept={vi.fn()}
        onDismiss={vi.fn()}
        onAcceptAll={vi.fn()}
        onEvaluate={vi.fn()}
        onRetryFailed={vi.fn()}
        visibleIssues={[]}
        onRestoreRevision={vi.fn()}
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
        onRestoreRevision={vi.fn()}
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
        onRestoreRevision={vi.fn()}
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
        onRestoreRevision={vi.fn()}
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
    onRestoreRevision: vi.fn(),
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
    onRestoreRevision: vi.fn(),
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
    onRestoreRevision: vi.fn(),
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
    isCollapsed: false, onToggleCollapse: vi.fn(), acceptAllSummary: null, onAccept: vi.fn(),
    onDismiss: vi.fn(), onAcceptAll: vi.fn(), onEvaluate: vi.fn(), onRetryFailed: vi.fn(),
    evalState, visibleIssues: [],
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
});
