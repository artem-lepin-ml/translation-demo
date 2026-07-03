import type { Issue, Criterion, Paragraph } from '../api-client';

interface Props {
  paragraphs: Paragraph[];
  visibleIssues: Issue[];     // already filtered by active criteria + not dismissed
  criteria: Criterion[];
  onAccept: (issue: Issue) => void;
  onDismiss: (issue: Issue) => void;
}

export default function IssuesPanel({ paragraphs, visibleIssues, criteria, onAccept, onDismiss }: Props) {
  const byPara: Map<number, { para: Paragraph | undefined; issues: Issue[] }> = new Map();
  for (const iss of visibleIssues) {
    if (!byPara.has(iss.paragraphId)) {
      byPara.set(iss.paragraphId, {
        para: paragraphs.find((p) => p.id === iss.paragraphId),
        issues: [],
      });
    }
    byPara.get(iss.paragraphId)!.issues.push(iss);
  }

  return (
    <div className="va-issues-panel">
      <div className="va-panel-title">All Issues ({visibleIssues.length})</div>
      {byPara.size === 0 && (
        <div className="va-empty">No issues match the active criteria.</div>
      )}
      {Array.from(byPara.entries()).map(([paraId, { para, issues }]) => (
        <div key={paraId} className="va-panel-group">
          <div className="va-panel-group-header">
            {para ? `§${para.idx + 1} — ${para.source.slice(0, 50)}…` : `Paragraph ${paraId}`}
          </div>
          {issues.map((iss) => {
            const criterion = criteria.find((c) => c.id === iss.criterionId);
            const color = criterion?.color ?? '#7aa2f7';
            const label = criterion?.name ?? iss.criterionId;
            return (
              <div key={iss.id} className="va-panel-card">
                <div className="va-panel-card-header">
                  <span
                    className="va-issue-criterion-badge"
                    style={{ background: color + '22', color, fontSize: 10, padding: '2px 7px' }}
                  >
                    {label}
                  </span>
                  <span className={`va-issue-severity severity-${iss.severity}`} style={{ fontSize: 10 }}>
                    {iss.severity}
                  </span>
                  {iss.mqmCategory && (
                    <span className="va-issue-mqm-category" style={{ fontSize: 10, color: 'var(--va-text-muted)', marginLeft: 4 }}>
                      {iss.mqmCategory}
                    </span>
                  )}
                </div>
                <div className="va-panel-card-fragment">"{iss.targetFragment}"</div>
                <div className="va-panel-card-explanation">{iss.explanation}</div>
                {iss.suggestion && (
                  <div className="va-panel-card-suggestion">→ {iss.suggestion}</div>
                )}
                <div className="va-panel-card-actions">
                  {iss.suggestion && (
                    <button className="va-btn-accept" onClick={() => onAccept(iss)}>
                      Accept
                    </button>
                  )}
                  <button className="va-btn-dismiss" onClick={() => onDismiss(iss)}>
                    Dismiss
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      ))}
    </div>
  );
}
