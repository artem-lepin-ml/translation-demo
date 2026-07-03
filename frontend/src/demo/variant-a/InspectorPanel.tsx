/**
 * InspectorPanel — focused on the currently selected paragraph.
 *
 * Tabs: Issues | Scores
 * Header: "§N — M active issues" + Accept all button
 * Issues: per-criterion cards with Accept / Dismiss; resolved (accepted/dismissed)
 *   issues vanish from the panel once acted on (they remain in the DB for
 *   preservation — see the wave-4 invariant — but drop out of this UI view).
 *   Issues with no concrete suggestion render as passive read-only notes.
 * Scores: per-criterion bars + aggregate; prev/baseline deltas
 */

import type { Issue, Score, Criterion, Paragraph } from '../api-client';
import type { ParaEvalState } from '../store';

interface Props {
  tab: 'issues' | 'scores';
  onTabChange: (t: 'issues' | 'scores') => void;
  paragraph: Paragraph | null;
  activeCriteria: Set<string>;
  evalState: ParaEvalState;
  criteria: Criterion[];
  isCollapsed: boolean;
  onToggleCollapse: () => void;
  /** Outcome of the last Accept-all on the selected paragraph; null = nothing to report */
  acceptAllSummary: { applied: number; outdated: number } | null;
  onAccept: (issue: Issue) => void;
  onDismiss: (issue: Issue) => void;
  onAcceptAll: () => void;
  /** Re-judge the selected paragraph on demand (dead-paragraph revival: the only
   * other evaluate trigger is Accept, which needs an existing issue to accept). */
  onEvaluate: () => void;
  /** Re-judge only the criteria that failed on the last pass (transient-blip retry). */
  onRetryFailed: (criterionIds: string[]) => void;
  /** Issues already filtered by active criteria; status filtering (open-only) happens here */
  visibleIssues: Issue[];
}

export default function InspectorPanel({
  tab,
  onTabChange,
  paragraph,
  activeCriteria: _activeCriteria,
  evalState,
  criteria,
  isCollapsed,
  onToggleCollapse,
  acceptAllSummary,
  onAccept,
  onDismiss,
  onAcceptAll,
  onEvaluate,
  onRetryFailed,
  visibleIssues,
}: Props) {
  const paraLabel = paragraph ? `§${paragraph.idx + 1}` : '§—';
  const openIssues = visibleIssues.filter((i) => i.status === 'open');
  const activeIssueCount = openIssues.length;
  const isLoading = evalState.loading;

  return (
    <div className={`va-inspector${isCollapsed ? ' collapsed' : ''}`}>
      {/* ── Header ── */}
      <div className="va-inspector-header">
        <div className="va-inspector-header-left">
          <span className="va-inspector-para-label">{paraLabel}</span>
          <span className="va-inspector-issue-count">
            {activeIssueCount} active issue{activeIssueCount !== 1 ? 's' : ''}
          </span>
          {evalState.cached && (
            <span className="va-cached-badge" title={`Cached preview from ${evalState.cachedAt ?? '?'}`}>
              cached
            </span>
          )}
        </div>
        <div className="va-inspector-header-right">
          {!isCollapsed && (
            <button
              className="va-btn-secondary"
              data-testid="evaluate-para"
              disabled={isLoading || !paragraph}
              onClick={onEvaluate}
              title="Re-evaluate this paragraph"
            >
              {isLoading ? '…' : 'Evaluate ↻'}
            </button>
          )}
          {!isCollapsed && activeIssueCount > 0 && tab === 'issues' && (
            <button
              className="va-btn-accept-all"
              disabled={isLoading}
              onClick={onAcceptAll}
            >
              Accept all
            </button>
          )}
          <button
            className="va-inspector-collapse-btn"
            onClick={onToggleCollapse}
            title={isCollapsed ? 'Expand inspector' : 'Collapse inspector'}
          >
            {isCollapsed ? '◀' : '▶'}
          </button>
        </div>
      </div>

      {/* ── Accept-all outcome (dim, informational — replaces the old alert) ── */}
      {acceptAllSummary && !isCollapsed && (
        <div className="va-accept-summary" data-testid="accept-all-summary">
          Applied {acceptAllSummary.applied} · {acceptAllSummary.outdated} outdated (overlapped by earlier edits)
        </div>
      )}

      {/* ── Stale-scores hint (accept/accept-all/manual edit outdated the scores) ── */}
      {evalState.stale && !isCollapsed && (
        <div className="va-inspector-stale-hint">
          Scores are for a previous version — press Evaluate ↻
        </div>
      )}

      {/* ── Failed criteria warning (genuine live failures only; cached fallback is not a failure) ── */}
      {evalState.failedCriterionIds.length > 0 && !evalState.cached && !isCollapsed && (
        <div className="va-inspector-warning">
          <span>
            Failed: {evalState.failedCriterionIds.join(', ')}
            {evalState.error && <> — {evalState.error}</>}
            {evalState.failedCriterionIds.length === criteria.length && (
              <div>Live evaluation failed and no warmed cache exists for this paragraph. Retry.</div>
            )}
          </span>
          <button
            className="va-btn-secondary va-retry-failed"
            data-testid="retry-failed"
            disabled={isLoading}
            onClick={() => onRetryFailed(evalState.failedCriterionIds)}
            title="Re-run only the criteria that failed"
          >
            {isLoading ? '…' : 'Retry failed ↻'}
          </button>
        </div>
      )}

      {/* ── Evaluate failure (network / 5xx / budget cut-off) ── */}
      {evalState.error && evalState.failedCriterionIds.length === 0 && !isCollapsed && (
        <div className="va-inspector-warning">
          Evaluate failed: {evalState.error}
        </div>
      )}

      {!isCollapsed && (
        <>
          {/* ── Tab toggle ── */}
          <div className="va-inspector-tabs">
            <button
              className={`va-inspector-tab${tab === 'issues' ? ' active' : ''}`}
              onClick={() => onTabChange('issues')}
            >
              Issues{activeIssueCount > 0 ? ` (${activeIssueCount})` : ''}
            </button>
            <button
              className={`va-inspector-tab${tab === 'scores' ? ' active' : ''}`}
              onClick={() => onTabChange('scores')}
            >
              Scores
            </button>
          </div>

          {/* ── Body ── */}
          <div className="va-inspector-body" data-testid="inspector-issues-scroll">
            {tab === 'issues' && (
              <IssuesView
                issues={visibleIssues}
                criteria={criteria}
                isLoading={isLoading}
                onAccept={onAccept}
                onDismiss={onDismiss}
              />
            )}
            {tab === 'scores' && paragraph && (
              <ScoresView
                scores={paragraph.scores}
                scoresPrev={paragraph.scoresPrev}
                scoresBaseline={paragraph.scoresBaseline}
                aggregate={paragraph.aggregate}
                aggregateBaseline={paragraph.aggregateBaseline}
                aggregatePrev={paragraph.aggregatePrev ?? null}
                criteria={criteria}
                isLoading={isLoading}
              />
            )}
          </div>
        </>
      )}
    </div>
  );
}

// ─── Issues View ─────────────────────────────────────────────────────────────

function IssuesView({
  issues,
  criteria,
  isLoading,
  onAccept,
  onDismiss,
}: {
  issues: Issue[];
  criteria: Criterion[];
  isLoading: boolean;
  onAccept: (issue: Issue) => void;
  onDismiss: (issue: Issue) => void;
}) {
  const shown = issues.filter((i) => i.status === 'open');
  if (shown.length === 0) {
    return <div className="va-insp-empty">No active issues for this paragraph.</div>;
  }

  return (
    <div className="va-insp-issues-list">
      {shown.map((iss) => {
        const criterion = criteria.find((c) => c.id === iss.criterionId);
        const color = criterion?.color ?? '#7aa2f7';
        const label = criterion?.name ?? iss.criterionId;
        const isNote = !iss.suggestion;

        return (
          <div
            key={iss.id}
            className={`va-insp-issue-card${isNote ? ' va-insp-issue-note' : ''}`}
          >
            <div className="va-insp-issue-header">
              <span
                className="va-insp-crit-badge"
                style={{ background: color + '22', color, borderColor: color }}
              >
                {label}
              </span>
              {iss.severity && (
                <span className={`va-issue-severity severity-${iss.severity}`} style={{ fontSize: 10 }}>
                  {iss.severity}
                </span>
              )}
              {iss.mqmCategory && (
                <span className="va-issue-mqm-category" style={{ fontSize: 10, color: 'var(--va-text-muted)', marginLeft: 4 }}>
                  {iss.mqmCategory}
                </span>
              )}
            </div>
            <div className="va-insp-issue-expl">{iss.explanation}</div>
            {iss.suggestion && (
              <div className="va-insp-issue-suggest">→ {iss.suggestion}</div>
            )}
            {!isNote && (
              <div className="va-insp-issue-actions">
                <button
                  className="va-btn-accept"
                  disabled={isLoading}
                  onClick={() => onAccept(iss)}
                >
                  {isLoading ? '…' : 'Accept'}
                </button>
                <button
                  className="va-btn-dismiss"
                  disabled={isLoading}
                  onClick={() => onDismiss(iss)}
                >
                  Dismiss
                </button>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ─── Scores View ─────────────────────────────────────────────────────────────

function ScoresView({
  scores,
  scoresPrev,
  scoresBaseline,
  aggregate,
  aggregateBaseline,
  aggregatePrev,
  criteria,
  isLoading,
}: {
  scores: Score[];
  scoresPrev: Score[] | null;
  scoresBaseline: Score[] | null;
  aggregate: number | null;
  aggregateBaseline: number | null;
  aggregatePrev: number | null;
  criteria: Criterion[];
  isLoading: boolean;
}) {
  function findScore(list: Score[] | null, criterionId: string): number | null {
    return list?.find((s) => s.criterionId === criterionId)?.value ?? null;
  }

  // criteriaKey encodes the enabled-criterion set an aggregate was computed
  // over; a mismatch means the comparison spans a criteria-set change (e.g.
  // a criterion was added/removed) and the delta isn't apples-to-apples.
  const compareList = scoresPrev ?? scoresBaseline;
  const latestKey = scores[0]?.criteriaKey;
  const compareKey = compareList?.[0]?.criteriaKey;
  const criteriaKeyMismatch =
    latestKey != null && compareKey != null && latestKey !== compareKey;

  return (
    <div className="va-insp-scores">
      {criteria.filter((c) => c.enabled).map((c) => {
        const v = findScore(scores, c.id);
        const prev = findScore(scoresPrev, c.id);
        const baseline = findScore(scoresBaseline, c.id);
        const pct = v !== null ? ((v - c.scaleMin) / (c.scaleMax - c.scaleMin)) * 100 : 0;
        const deltaPrev = v !== null && prev !== null ? Math.round((v - prev) * 10) / 10 : null;
        const deltaBaseline = v !== null && baseline !== null ? Math.round((v - baseline) * 10) / 10 : null;

        return (
          <div key={c.id} className="va-insp-score-row">
            <div className="va-insp-score-label-row">
              <span className="va-insp-score-dot" style={{ background: c.color }} />
              <span className="va-insp-score-label">{c.name}</span>
              <div className="va-insp-score-right">
                {isLoading ? (
                  <span className="va-score-loading">…</span>
                ) : v !== null ? (
                  <>
                    <span className="va-insp-score-val" style={{ color: c.color }}>
                      {v.toFixed(1)}
                    </span>
                    {deltaPrev !== null && deltaPrev > 0 && (
                      <span className="va-score-delta" title="vs previous">▲ +{deltaPrev.toFixed(1)}</span>
                    )}
                    {deltaBaseline !== null && deltaBaseline > 0 && deltaPrev === null && (
                      <span className="va-score-delta-base" title="vs baseline">▲ +{deltaBaseline.toFixed(1)}</span>
                    )}
                  </>
                ) : (
                  <span className="va-score-na">—</span>
                )}
              </div>
            </div>
            <div className="va-insp-score-bar-wrap">
              {isLoading ? (
                <div className="va-score-bar-shimmer" />
              ) : (
                <div
                  className="va-insp-score-bar"
                  style={{ width: `${pct}%`, background: c.color }}
                />
              )}
            </div>
          </div>
        );
      })}

      <div className="va-insp-agg-row">
        <span className="va-insp-agg-label">Aggregate</span>
        {isLoading ? (
          <span className="va-score-loading">…</span>
        ) : aggregate !== null ? (
          <span
            className="va-insp-agg-val"
            style={{
              color: aggregate >= 8 ? 'var(--va-green)' : aggregate >= 6 ? 'var(--va-yellow)' : 'var(--va-red)',
            }}
          >
            {aggregate.toFixed(1)}
            {aggregatePrev != null ? (
              <span className="va-insp-agg-baseline" title="Previous score">
                {' '}(prev {aggregatePrev.toFixed(1)})
              </span>
            ) : (
              aggregateBaseline !== null && (
                <span className="va-insp-agg-baseline" title="Baseline">
                  {' '}(base {aggregateBaseline.toFixed(1)})
                </span>
              )
            )}
          </span>
        ) : (
          <span className="va-score-na">—</span>
        )}
        {criteriaKeyMismatch && (
          <span
            className="va-insp-criteria-key-note"
            style={{ opacity: 0.6, fontSize: '0.85em', marginLeft: 6 }}
          >
            different criteria set
          </span>
        )}
      </div>
    </div>
  );
}
