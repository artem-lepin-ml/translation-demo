import { useEffect } from 'react';
import { candidatesForDisplay, type TermWithTrace } from './glossary-grouping';

interface Props {
  term: TermWithTrace;
  rect: DOMRect;
  onClose: () => void;
}

const difficultyLabel: Record<string, string> = {
  green: '🟢 Unambiguous (exact label match)',
  yellow: '🟡 Context-resolved (AI-disambiguated)',
  red: '🔴 Unresolved (not grounded)',
};

const pairLabel: Record<string, string> = {
  green: '🟢 Correct translation',
  yellow: '🟡 Disputed',
  red: '🔴 Wrong translation',
};

export default function TermPopover({ term, rect, onClose }: Props) {
  // Keep the popover fully inside the viewport regardless of how tall its
  // content grows (up to the CSS max-height cap on `.va-popover` in
  // variant-a.css, `min(80vh, calc(100vh - 2rem))`) — the old fixed "-320"
  // assumed a short, single-screen-fits popover and pushed taller ones below
  // the fold with no way to scroll them into view (owner: "окно до конца не
  // листается"). Margin below mirrors the CSS calc's 2rem (16px each side).
  const POPOVER_MARGIN = 16;
  const maxPopoverHeight = Math.min(window.innerHeight * 0.8, window.innerHeight - POPOVER_MARGIN * 2);
  const top = Math.max(POPOVER_MARGIN, Math.min(rect.bottom + 8, window.innerHeight - maxPopoverHeight - POPOVER_MARGIN));
  const left = Math.min(rect.left, window.innerWidth - 380);
  // Same dead-field fix as the Glossary tab's Candidates table (BUG-6,
  // frontend-developer-stability-wave1): the top-level `term.candidates`
  // drops to `[]` for a judge_rejected term even though real candidates were
  // considered — prefer `trace_json.candidates` when present.
  const candidates = candidatesForDisplay(term);

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [onClose]);

  return (
    <>
      <div className="va-popover-backdrop" onClick={onClose} />
      <div
        className="va-popover va-term-popover"
        style={{ top, left, minWidth: 300, maxWidth: 380 }}
        onClick={(e) => e.stopPropagation()}
      >
        <button className="va-popover-close" onClick={onClose}>✕</button>

        {/* Header */}
        <div className="va-term-popover-header">
          {term.sourceSurface}
          {term.targetSurface && (
            <span style={{ color: 'var(--va-text-muted)', fontSize: 12, marginLeft: 8 }}>
              → {term.targetSurface}
            </span>
          )}
        </div>

        {/* Signal 1: difficulty */}
        <div className="va-term-popover-row">
          <span className="va-term-popover-label">Difficulty</span>
          <span className="va-term-popover-val">{difficultyLabel[term.difficulty] ?? term.difficulty}</span>
        </div>

        {/* Signal 2: pair accuracy */}
        {term.pairAccuracy !== null && (
          <div className="va-term-popover-row">
            <span className="va-term-popover-label">Pair accuracy</span>
            <span className="va-term-popover-val">{pairLabel[term.pairAccuracy] ?? term.pairAccuracy}</span>
          </div>
        )}

        {/* Lemma */}
        <div className="va-term-popover-row">
          <span className="va-term-popover-label">Source lemma</span>
          <span className="va-term-popover-val">{term.sourceLemma}</span>
        </div>

        {/* Wikidata grounding */}
        {term.grounded && (
          <div className="va-term-popover-row">
            <span className="va-term-popover-label">Wikidata</span>
            <span className="va-term-popover-val">
              <a
                href={term.grounded.url}
                target="_blank"
                rel="noopener noreferrer"
                style={{ color: 'var(--va-accent)' }}
              >
                {term.grounded.label}
              </a>
              {' '}({term.grounded.qid})
              {term.grounded.description && (
                <span style={{ color: 'var(--va-text-muted)', fontSize: 11, display: 'block' }}>
                  {term.grounded.description}
                </span>
              )}
            </span>
          </div>
        )}

        {/* Candidates (ambiguous) — the chosen sense (term.grounded.qid, when
            the term did resolve) is marked with a ✓ and bolded so the reader
            can see which candidate "won" without cross-referencing the
            Wikidata row above by QID (owner review #3c). */}
        {candidates.length > 0 && (
          <div className="va-term-popover-row" style={{ flexDirection: 'column', gap: 4 }}>
            <span className="va-term-popover-label">Candidate senses</span>
            {candidates.map((c) => {
              const isChosen = !!term.grounded && c.qid === term.grounded.qid;
              return (
                <div
                  key={c.qid}
                  style={{
                    fontSize: 11,
                    color: isChosen ? 'var(--va-text)' : 'var(--va-text-muted)',
                    fontWeight: isChosen ? 600 : undefined,
                    paddingLeft: 8,
                  }}
                >
                  {isChosen && <span aria-hidden="true">✓ </span>}
                  <a href={c.url} target="_blank" rel="noopener noreferrer" style={{ color: 'var(--va-accent)' }}>
                    {c.label}
                  </a>
                  {' '}— {c.description}
                </div>
              );
            })}
          </div>
        )}

        {/* Recommended translation */}
        {term.recommended && (
          <div className="va-term-popover-row">
            <span className="va-term-popover-label">Recommended</span>
            <span className="va-term-popover-val" style={{ fontWeight: 600 }}>{term.recommended}</span>
          </div>
        )}

        {/* No EN equivalent */}
        {term.targetSurface === null && (
          <div className="va-term-popover-row">
            <span style={{ color: 'var(--va-text-muted)', fontSize: 12, fontStyle: 'italic' }}>
              Term absent from translation
            </span>
          </div>
        )}

        {/* Context */}
        {term.context && (
          <div className="va-term-popover-row" style={{ flexDirection: 'column', gap: 3 }}>
            <span className="va-term-popover-label">Disambiguating context</span>
            <span className="va-term-popover-val" style={{ fontSize: 11, color: 'var(--va-text-muted)' }}>
              {term.context}
            </span>
          </div>
        )}
      </div>
    </>
  );
}
