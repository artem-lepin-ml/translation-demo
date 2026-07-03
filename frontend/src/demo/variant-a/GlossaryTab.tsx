import { langLabel } from '../lang';
import type { Term, Paragraph } from '../api-client';

interface Props {
  terms: Term[];
  paragraphs: Paragraph[];
  sourceLang: string;
  targetLang: string;
}

const difficultyEmoji: Record<string, string> = {
  green: '🟢',
  yellow: '🟡',
  red: '🔴',
};

const pairEmoji: Record<string, string> = {
  green: '🟢',
  yellow: '🟡',
  red: '🔴',
};

export default function GlossaryTab({ terms, paragraphs, sourceLang, targetLang }: Props) {
  if (terms.length === 0) {
    return (
      <div className="va-tab-content">
        <div className="va-section-title">Terminology Glossary</div>
        <p className="va-empty-note">
          Terminology signals are precomputed offline and available for the seeded pilot document.
        </p>
      </div>
    );
  }

  return (
    <div className="va-tab-content">
      <div className="va-section-title">Terminology Glossary</div>
      <table className="va-table">
        <thead>
          <tr>
            <th title="Difficulty (Wikidata grounding)">Difficulty</th>
            <th title="Pair accuracy (translation quality)">Pair</th>
            <th>Source · {langLabel(sourceLang)}</th>
            <th>Translation · {langLabel(targetLang)}</th>
            <th>Wikidata</th>
            <th>Paragraph</th>
            <th>Note</th>
          </tr>
        </thead>
        <tbody>
          {terms.map((t) => {
            const para = paragraphs.find((p) => p.id === t.paragraphId);
            const snippet = para ? para.source.slice(0, 40) + '…' : `#${t.paragraphId}`;
            const paraLabel = para ? `§${para.idx + 1}` : `#${t.paragraphId}`;
            return (
              <tr key={t.id}>
                <td>
                  <span title={`Difficulty: ${t.difficulty}`}>
                    {difficultyEmoji[t.difficulty] ?? t.difficulty}
                  </span>
                </td>
                <td>
                  {t.pairAccuracy !== null ? (
                    <span title={`Pair accuracy: ${t.pairAccuracy}`}>
                      {pairEmoji[t.pairAccuracy] ?? t.pairAccuracy}
                    </span>
                  ) : (
                    <span title="No grounding — cannot assess pair" style={{ color: 'var(--va-text-dim)' }}>—</span>
                  )}
                </td>
                <td style={{ fontStyle: 'italic', color: 'var(--va-text-muted)' }}>
                  {t.sourceSurface}
                </td>
                <td style={{ fontWeight: 600 }}>
                  {t.targetSurface ?? (
                    <span style={{ color: 'var(--va-text-dim)', fontStyle: 'italic' }}>absent</span>
                  )}
                </td>
                <td>
                  {t.grounded ? (
                    <a
                      href={t.grounded.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      style={{ color: 'var(--va-accent)', fontSize: 12 }}
                      title={t.grounded.description}
                    >
                      {t.grounded.label}
                    </a>
                  ) : (
                    <span style={{ color: 'var(--va-text-dim)', fontSize: 11 }}>—</span>
                  )}
                </td>
                <td style={{ color: 'var(--va-text-muted)', fontSize: 12 }} title={snippet}>
                  {paraLabel}
                </td>
                <td style={{ color: 'var(--va-text-muted)', fontSize: 12, maxWidth: 200 }}>{t.note}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
