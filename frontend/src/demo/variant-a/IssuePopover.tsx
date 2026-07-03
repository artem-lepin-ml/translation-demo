import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import type { Issue, Criterion } from '../api-client';

interface Props {
  issues: Issue[];
  criteria: Criterion[];
  rect: DOMRect;
  onAccept: (issue: Issue) => void;
  onDismiss: (issue: Issue) => void;
  onClose: () => void;
}

const severityLabel: Record<string, string> = {
  minor: 'Minor',
  major: 'Major',
};

/** Clamp the popover's top so both edges stay inside the viewport.
 *  Prefer just below the anchor; if the measured stack would overflow the
 *  bottom, lift it up; never above 8px. Pure — unit-tested. */
export function clampTop(anchorBottom: number, popoverHeight: number, viewportHeight: number): number {
  const preferred = anchorBottom + 8;
  const maxTop = viewportHeight - popoverHeight - 8;
  return Math.max(8, Math.min(preferred, maxTop));
}

export default function IssuePopover({ issues, criteria, rect, onAccept, onDismiss, onClose }: Props) {
  // outdated issues disappear entirely (spec §4); accepted/dismissed never reach
  // the popover because it is anchored to open segments only.
  const visible = issues.filter((i) => i.status !== 'outdated');

  const ref = useRef<HTMLDivElement>(null);
  const [top, setTop] = useState(() => rect.bottom + 8);
  const left = Math.min(rect.left, window.innerWidth - 480);

  useLayoutEffect(() => {
    const h = ref.current?.getBoundingClientRect().height ?? 0;
    setTop(clampTop(rect.bottom, h, window.innerHeight));
  }, [rect, visible.length]);

  // Non-blocking outside-click close: a document-level mousedown listener (not a
  // full-viewport backdrop div) so the triggering click still reaches its own
  // target underneath — one click both closes this popover AND selects/opens
  // whatever was clicked (row, another underline). Capture phase so we observe
  // the click before React's own bubble-phase handlers on the new target run.
  useEffect(() => {
    const handleOutside = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose();
    };
    document.addEventListener('mousedown', handleOutside, true);
    return () => document.removeEventListener('mousedown', handleOutside, true);
  }, [onClose]);

  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handleKey);
    return () => document.removeEventListener('keydown', handleKey);
  }, [onClose]);

  if (visible.length === 0) return null;

  return (
    <div
      ref={ref}
      className="va-popover"
      data-testid="issue-popover"
      style={{ top, left }}
    >
      <button className="va-popover-close" onClick={onClose}>✕</button>
      {visible.map((issue) => {
        const criterion = criteria.find((c) => c.id === issue.criterionId);
        const color = criterion?.color ?? '#7aa2f7';
        const label = criterion?.name ?? issue.criterionId;
        return (
          <div key={issue.id} className="va-issue-card">
            <div className="va-issue-card-header">
              <span
                className="va-issue-criterion-badge"
                style={{ background: color + '22', color }}
              >
                {label}
              </span>
              <span className={`va-issue-severity severity-${issue.severity}`}>
                {severityLabel[issue.severity] ?? issue.severity}
              </span>
              {issue.mqmCategory && (
                <span className="va-issue-mqm-category">{issue.mqmCategory}</span>
              )}
            </div>
            <div className="va-issue-explanation">{issue.explanation}</div>
            {issue.suggestion ? (
              <>
                <div className="va-issue-suggestion">
                  <strong>Suggestion:</strong> {issue.suggestion}
                </div>
                <div className="va-issue-actions">
                  <button className="va-btn-accept" onClick={() => onAccept(issue)}>
                    Accept
                  </button>
                  <button className="va-btn-dismiss" onClick={() => onDismiss(issue)}>
                    Dismiss
                  </button>
                </div>
              </>
            ) : (
              <div className="va-issue-note-tag">Note — no concrete suggestion</div>
            )}
          </div>
        );
      })}
    </div>
  );
}
