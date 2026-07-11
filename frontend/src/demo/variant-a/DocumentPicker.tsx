/**
 * DocumentPicker — landing view shown when no document is loaded
 * (store.document === null): one card per document + a trailing "Blank
 * document" card that opens the upload modal. Reached on boot (init() no
 * longer auto-opens the first document) and via the workspace brand click
 * (backToPicker).
 *
 * Card meta is derived from real DocumentSummary fields only — no fake judge
 * score / findings counts (the summary DTO does not carry per-document score
 * or issue aggregates). The status dot/line reuses `termsStatus` (the one
 * field the contract actually adds to the summary row) rather than a
 * per-verdict term count, which the DTO does not expose either.
 */

import { langLabel } from '../lang';
import type { DocumentSummary, TermsStatus } from '../api-client';

interface Props {
  documents: DocumentSummary[];
  onSelect: (id: number) => void;
  onCreateBlank: () => void;
}

interface TermsStatusPresentation {
  text: string;
  tone: 'green' | 'yellow' | 'red' | 'dim';
}

/** Exported for the top-chrome Terms chip (VariantA.tsx) and GlossaryTab's
 *  empty state, so all three surfaces describe the same status the same way
 *  (single source of truth for terminology-status wording). */
export function termsStatusPresentation(status: TermsStatus | undefined): TermsStatusPresentation {
  switch (status) {
    case 'done':
      return { text: 'Terminology ready', tone: 'green' };
    case 'running':
      return { text: 'Extracting terminology…', tone: 'yellow' };
    case 'failed':
      return { text: 'Terminology extraction failed', tone: 'red' };
    default:
      return { text: 'No terminology extracted', tone: 'dim' };
  }
}

function DocumentCard({ doc, onSelect }: { doc: DocumentSummary; onSelect: (id: number) => void }) {
  const terms = termsStatusPresentation(doc.termsStatus);
  return (
    <button
      className="va-picker-card"
      data-testid={`doc-card-${doc.id}`}
      onClick={() => onSelect(doc.id)}
    >
      <div className="va-picker-card-title">{doc.title}</div>
      <div className="va-picker-card-meta">
        {langLabel(doc.sourceLang)} → {langLabel(doc.targetLang)} · {doc.nParagraphs} ¶
      </div>
      <div className="va-picker-card-status">
        <span className={`va-verdict-dot ${terms.tone}`} />
        {terms.text}
      </div>
    </button>
  );
}

export default function DocumentPicker({ documents, onSelect, onCreateBlank }: Props) {
  return (
    <div className="va-picker" data-testid="doc-picker">
      <div className="va-picker-header">
        <div className="va-brand">Glossa-MT</div>
        <p className="va-picker-subtitle">
          Interpretable translation evaluation — pick a document to review, or start a new one.
        </p>
      </div>
      <div className="va-picker-grid">
        {documents.map((doc) => (
          <DocumentCard key={doc.id} doc={doc} onSelect={onSelect} />
        ))}
        <button
          className="va-picker-card va-picker-card-blank"
          data-testid="doc-card-blank"
          onClick={onCreateBlank}
        >
          <span className="va-picker-blank-plus">+</span>
          <div className="va-picker-card-title">Blank document</div>
          <div className="va-picker-card-meta">
            Paste your own text — translate, ground terminology, and evaluate live
          </div>
        </button>
      </div>
    </div>
  );
}
