/**
 * InspectorPanel — focused on the currently selected paragraph.
 *
 * Tabs: Issues | Scores
 * Header: "§N — M active issues" + Refine paragraph button (refiner LLM pass:
 *   aggregates every open finding into one rewrite, then re-scores).
 * Issues: per-criterion cards with Accept / Dismiss; resolved (accepted/dismissed)
 *   issues vanish from the panel once acted on (they remain in the DB for
 *   preservation — see the wave-4 invariant — but drop out of this UI view).
 *   Issues with no concrete suggestion render as passive read-only notes.
 * Scores: per-criterion bars + aggregate; prev/baseline deltas
 */

import { useEffect, useState } from 'react';
import type { Issue, Score, Criterion, Paragraph, Revision, RevisionOrigin } from '../api-client';
import { getRevisions } from '../api-client';
import type { ParaEvalState } from '../store';

/** Human-readable criterion name for a raw criterionId, falling back to the
 *  id itself when it isn't resolvable against the loaded criteria list
 *  (T8-№2: the failed-criteria banner was showing internal ids like
 *  "crit-…" verbatim). */
function criterionLabel(id: string, criteria: Criterion[]): string {
  return criteria.find((c) => c.id === id)?.name ?? id;
}

interface Props {
  tab: 'issues' | 'scores';
  onTabChange: (t: 'issues' | 'scores') => void;
  paragraph: Paragraph | null;
  activeCriteria: Set<string>;
  evalState: ParaEvalState;
  criteria: Criterion[];
  isCollapsed: boolean;
  onToggleCollapse: () => void;
  onAccept: (issue: Issue) => void;
  onDismiss: (issue: Issue) => void;
  /** Refiner pass: aggregate every open finding in this paragraph into one
   *  LLM rewrite, then re-score (store.refineParagraph). Busy phase comes
   *  from evalState.refineStage ('refining' | 'rescoring' | undefined). */
  onRefine: () => void;
  /** Re-judge the selected paragraph on demand (dead-paragraph revival: the only
   * other evaluate trigger is Accept, which needs an existing issue to accept). */
  onEvaluate: () => void;
  /** Re-judge only the criteria that failed on the last pass (transient-blip retry). */
  onRetryFailed: (criterionIds: string[]) => void;
  /** Issues already filtered by active criteria; status filtering (open-only) happens here */
  visibleIssues: Issue[];
  /** Restore the selected paragraph's text to a past revision (S5 §3.3).
   *  Returns a promise that resolves once the restore round-trip (and the
   *  paragraph refresh it triggers) has completed, so HistoryBlock can
   *  re-fetch the revision list only after the server state has settled. */
  onRestoreRevision: (revisionId: number) => Promise<void>;
  /** Bumped by store.resetDoc() on every successful Document Reset
   *  (SUSPECTED-1, wave2) — HistoryBlock re-fetches revisions when this
   *  changes, the same way it already does after a Restore, since Reset
   *  reuses the same paragraph id and would otherwise never re-fire that
   *  effect. */
  documentResetNonce: number;
  /** Bumped by store on Refine completion, manual edit save, Evaluate
   *  completion and Accept-all completion (T3-F4/T10-F1) — HistoryBlock
   *  re-fetches revisions when this changes, same idiom as
   *  documentResetNonce. Optional/defaulted so pre-existing test fixtures
   *  that predate this field don't all need updating. */
  historyRefreshNonce?: number;
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
  onAccept,
  onDismiss,
  onRefine,
  onEvaluate,
  onRetryFailed,
  visibleIssues,
  onRestoreRevision,
  documentResetNonce,
  historyRefreshNonce = 0,
}: Props) {
  const paraLabel = paragraph ? `§${paragraph.idx + 1}` : '§—';
  const openIssues = visibleIssues.filter((i) => i.status === 'open');
  const activeIssueCount = openIssues.length;
  // Folds the refine flow's own busy phase in with the generic evaluate
  // loading flag so Accept/Dismiss/Evaluate/Retry-failed all disable for the
  // whole "Refining… → Re-scoring…" lifecycle, not just the re-score half.
  const isLoading = evalState.loading || !!evalState.refineStage;

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
          {!isCollapsed && (
            <button
              className="va-btn-refine"
              data-testid="refine-paragraph"
              disabled={isLoading || activeIssueCount === 0}
              onClick={onRefine}
              title={
                activeIssueCount === 0
                  ? 'No open findings'
                  : 'Aggregate all findings and rewrite with the refiner model'
              }
            >
              {evalState.refineStage === 'refining'
                ? 'Refining…'
                : evalState.refineStage === 'rescoring'
                ? 'Re-scoring…'
                : 'Refine paragraph ✦'}
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

      {/* ── Stale-scores hint (accept/refine/manual edit outdated the scores) ── */}
      {evalState.stale && !isCollapsed && (
        <div className="va-inspector-stale-hint">
          Scores are for a previous version — press Evaluate ↻
        </div>
      )}

      {/* ── Failed criteria warning. Shown whenever the last pass had genuine
          live failures, REGARDLESS of evalState.cached: cached is a separate
          signal (a cache-fallback response was shown for the failed
          criteria) — the two used to be mutually exclusive in this banner,
          which silently hid real judge-call failures whenever a cache
          fallback happened to exist (T4-Н1). Both now render together. ── */}
      {evalState.failedCriterionIds.length > 0 && !isCollapsed && (
        <div className="va-inspector-warning">
          <span>
            Failed: {evalState.failedCriterionIds.map((id) => criterionLabel(id, criteria)).join(', ')}
            {evalState.error && <> — {evalState.error}</>}
            {!evalState.cached && evalState.failedCriterionIds.length === criteria.length && (
              <div>Live evaluation failed and no warmed cache exists for this paragraph. Retry.</div>
            )}
            {evalState.cached && (
              <div>Showing a cached fallback for the failed criteria — Retry for a live judgment.</div>
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
          {evalState.errorOp === 'refine' ? 'Refine failed:'
            : evalState.errorOp === 'dismiss' ? 'Dismiss failed:'
            : 'Evaluate failed:'} {evalState.error}
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
              <>
                <ScoresView
                  scores={paragraph.scores}
                  scoresPrev={paragraph.scoresPrev}
                  scoresBaseline={paragraph.scoresBaseline}
                  aggregate={paragraph.aggregate}
                  aggregateBaseline={paragraph.aggregateBaseline}
                  aggregatePrev={paragraph.aggregatePrev ?? null}
                  criteria={criteria}
                  isLoading={isLoading}
                  cached={evalState.cached}
                />
                <HistoryBlock
                  paragraph={paragraph}
                  onRestore={onRestoreRevision}
                  documentResetNonce={documentResetNonce}
                  historyRefreshNonce={historyRefreshNonce}
                />
              </>
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
  cached,
}: {
  scores: Score[];
  scoresPrev: Score[] | null;
  scoresBaseline: Score[] | null;
  aggregate: number | null;
  aggregateBaseline: number | null;
  aggregatePrev: number | null;
  criteria: Criterion[];
  isLoading: boolean;
  /** The whole /evaluate response was an offline-fallback cache read (S5
   * §3.4) — cached is all-or-nothing per response (app.py `_cache_response`),
   * so every enabled criterion shown here is equally "affected". */
  cached: boolean;
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
              {cached && v !== null && (
                <span className="va-cached-mini" title="Offline fallback estimate, not a live judgment">
                  cached
                </span>
              )}
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

// ─── History block (S5 §3.2–3.3) ───────────────────────────────────────────────

const MAX_HISTORY_ROWS = 8;

function relativeTime(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return iso;
  const mins = Math.round((Date.now() - then) / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins} min ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours} hour${hours !== 1 ? 's' : ''} ago`;
  const days = Math.round(hours / 24);
  return `${days} day${days !== 1 ? 's' : ''} ago`;
}

function OriginIcon({ origin }: { origin: RevisionOrigin }) {
  const p = { width: 11, height: 11, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor',
    strokeWidth: 1.8, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const };
  switch (origin) {
    case 'seed':
      return <svg {...p}><path d="M5 12c0-4 3-7 7-7s7 3 7 7-3 7-7 7" /><circle cx="9" cy="12" r="1.4" /></svg>;
    case 'upload':
      return <svg {...p}><path d="M12 15V4M12 4l-4.5 4.5M12 4l4.5 4.5" /><path d="M4 16v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2" /></svg>;
    case 'edit':
      return <svg {...p}><path d="M4 20l1-4L16 5l3 3L8 19l-4 1z" /></svg>;
    case 'apply_edit':
      return <svg {...p}><path d="M5 13l4 4L19 7" /></svg>;
    case 'translate':
      return <svg {...p}><circle cx="12" cy="12" r="8" /><path d="M4 12h16M12 4c2.5 2.5 2.5 13.5 0 16M12 4c-2.5 2.5-2.5 13.5 0 16" /></svg>;
    case 'restore':
      return <svg {...p}><path d="M4 4v6h6" /><path d="M4.5 15a8 8 0 1 0 2-9.5L4 10" /></svg>;
    default:
      return null;
  }
}

function HistoryBlock({
  paragraph,
  onRestore,
  documentResetNonce,
  historyRefreshNonce = 0,
}: {
  paragraph: Paragraph;
  onRestore: (revisionId: number) => Promise<void>;
  documentResetNonce: number;
  historyRefreshNonce?: number;
}) {
  const [revisions, setRevisions] = useState<Revision[] | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [previewId, setPreviewId] = useState<number | null>(null);
  const [restoringId, setRestoringId] = useState<number | null>(null);

  // Re-fetch on paragraph switch, on documentResetNonce (SUSPECTED-1, wave2:
  // Document Reset writes a fresh 'seed' revision but reuses the same
  // paragraph id, so a plain `paragraph.id` dependency alone never re-fires
  // this effect after a Reset), AND on historyRefreshNonce (T3-F4/T10-F1:
  // Refine/Evaluate/manual-edit/Accept-all can all mutate the current
  // revision's text or score while this block stays mounted on the Scores
  // tab — same staleness class as Reset, same nonce-bump fix). Restore below
  // still uses its own explicit re-fetch in handleRestore rather than this
  // nonce — it already resolves via the same round trip.
  useEffect(() => {
    let cancelled = false;
    setRevisions(null);
    setExpanded(false);
    setPreviewId(null);
    getRevisions(paragraph.id)
      .then((r) => { if (!cancelled) setRevisions(r.revisions); })
      .catch(() => { if (!cancelled) setRevisions([]); });
    return () => { cancelled = true; };
  }, [paragraph.id, documentResetNonce, historyRefreshNonce]);

  // The backend is authoritative immediately after a restore (GET
  // /revisions already returns all rows) — the bug was purely client-side:
  // this component kept whichever `revisions` array it had fetched on mount
  // and never refetched, so a restore appeared to "lose" the intermediate
  // revision until an unrelated reload. Fix: re-fetch and replace the whole
  // list wholesale once the restore round-trip resolves — no local splicing
  // of the previous array.
  async function handleRestore(revisionId: number) {
    setRestoringId(revisionId);
    try {
      await onRestore(revisionId);
    } catch {
      // Restore itself failed (network/5xx) — nothing changed server-side,
      // so there is nothing to refresh; the caller surfaces its own error.
      return;
    } finally {
      setRestoringId(null);
    }
    try {
      const r = await getRevisions(paragraph.id);
      setRevisions(r.revisions);
    } catch {
      // Refetch failed even though restore succeeded — keep showing the
      // previous (pre-restore) list rather than blanking it to empty.
    }
  }

  if (!revisions || revisions.length === 0) return null;

  const shown = expanded ? revisions : revisions.slice(0, MAX_HISTORY_ROWS);
  const hiddenCount = revisions.length - shown.length;
  const best = revisions.find((r) => r.isBest);

  return (
    <div className="va-history-block" data-testid="revision-history">
      <div className="va-history-title">
        Revision history
        {best && best.aggregate !== null && (
          <span className="va-history-best">⭰ Best {best.aggregate.toFixed(1)}</span>
        )}
      </div>
      {shown.map((r) => (
        <div
          key={r.id}
          className={`va-history-row${r.isBest ? ' va-history-row-best' : ''}`}
          data-testid={`history-row-${r.id}`}
          onClick={() => setPreviewId(previewId === r.id ? null : r.id)}
        >
          <span className="va-history-origin" title={r.origin}><OriginIcon origin={r.origin} /></span>
          <span
            className="va-history-agg"
            style={r.aggregate === null
              ? { color: 'var(--va-text-dim)' }
              : r.isBest ? { color: 'var(--va-yellow)' } : undefined}
          >
            {r.aggregate !== null ? r.aggregate.toFixed(1) : '—'}
          </span>
          <span className="va-history-time">
            {relativeTime(r.createdAt)}{r.aggregate === null ? ' · not scored' : ''}
          </span>
          {r.isCurrent && <span className="va-history-tag">current</span>}
          {r.isBest && !r.isCurrent && <span className="va-history-best">⭰ Best</span>}
          <button
            className="va-history-restore"
            data-testid={`history-restore-${r.id}`}
            disabled={r.isCurrent || restoringId !== null}
            onClick={(e) => { e.stopPropagation(); void handleRestore(r.id); }}
          >
            {restoringId === r.id ? '…' : 'Restore'}
          </button>
        </div>
      ))}
      {hiddenCount > 0 && (
        <button className="va-btn-secondary" data-testid="history-show-more" onClick={() => setExpanded(true)}>
          +{hiddenCount} more
        </button>
      )}
      {previewId !== null && (
        <div className="va-history-preview" data-testid="history-preview">
          {revisions.find((r) => r.id === previewId)?.text}
        </div>
      )}
    </div>
  );
}
