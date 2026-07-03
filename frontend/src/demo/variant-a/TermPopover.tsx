import { useEffect } from 'react';
import type { Term } from '../api-client';

interface Props {
  term: Term;
  rect: DOMRect;
  onClose: () => void;
}

const difficultyLabel: Record<string, string> = {
  green: '🟢 Confirmed (Wikidata)',
  yellow: '🟡 Ambiguous (multiple senses)',
  red: '🔴 Not found in Wikidata',
};

const pairLabel: Record<string, string> = {
  green: '🟢 Correct translation',
  yellow: '🟡 Disputed',
  red: '🔴 Wrong translation',
};

export default function TermPopover({ term, rect, onClose }: Props) {
  const top = Math.min(rect.bottom + 8, window.innerHeight - 320);
  const left = Math.min(rect.left, window.innerWidth - 380);

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
        className="va-popover"
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

        {/* Candidates (ambiguous) */}
        {term.candidates.length > 0 && (
          <div className="va-term-popover-row" style={{ flexDirection: 'column', gap: 4 }}>
            <span className="va-term-popover-label">Ambiguous senses</span>
            {term.candidates.map((c) => (
              <div key={c.qid} style={{ fontSize: 11, color: 'var(--va-text-muted)', paddingLeft: 8 }}>
                <a href={c.url} target="_blank" rel="noopener noreferrer" style={{ color: 'var(--va-accent)' }}>
                  {c.label}
                </a>
                {' '}— {c.description}
              </div>
            ))}
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

        {/* Note */}
        {term.note && (
          <div className="va-term-popover-row" style={{ flexDirection: 'column', gap: 3 }}>
            <span className="va-term-popover-label">Note</span>
            <span className="va-term-popover-val" style={{ fontStyle: 'italic', fontSize: 12 }}>
              {term.note}
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
