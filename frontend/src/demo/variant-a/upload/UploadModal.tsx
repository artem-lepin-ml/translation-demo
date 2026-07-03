import { useEffect, useRef, useState } from 'react';
import { useDemoStore } from '../../store';
import { ACCEPT, errorMessage, ingestFile, splitParagraphs } from './file-ingest';

const MAX_PARAS = 40;
const MAX_PARA_CHARS = 4000;
// Mirrors precompute.py: PRECOMPUTE_PARAS (first 12 ¶) x one judge call per
// enabled criterion x ~$0.004/call (default seed model).
const PRECOMPUTE_MAX_PARAS = 12;
const PRECOMPUTE_COST_PER_CALL = 0.004;

interface SideState { text: string; lang: string; busy: boolean; error: string | null }

export function SidePanel(props: {
  id: 'source' | 'target';
  label: string;
  langPlaceholder: string;
  state: SideState;
  onChange: (patch: Partial<SideState>) => void;
}) {
  const { id, label, langPlaceholder, state, onChange } = props;
  const fileRef = useRef<HTMLInputElement>(null);
  const paras = splitParagraphs(state.text);

  const loadFile = async (file: File | undefined, warning: string | null = null) => {
    if (!file) return;
    if (state.text.trim() && !window.confirm('Replace the pasted text with the file contents?')) return;
    onChange({ busy: true, error: null });
    try {
      const text = await ingestFile(file);
      // Re-apply the caller's warning (e.g. "multiple files dropped") only on
      // success — a failed load already reports its own error and a stale
      // warning would be misleading.
      onChange({ text, busy: false, error: warning });
    } catch (e: unknown) {
      const status = (e as { status?: number }).status;
      onChange({ busy: false, error: status ? errorMessage(status) : String(e) });
    }
  };

  return (
    <div className="va-upload-panel" data-testid={`panel-${id}`}>
      <div className="va-upload-panel-head">
        <span>{label}</span>
        <input
          className="va-lang-input"
          data-testid={`panel-${id}-lang`}
          placeholder={langPlaceholder}
          value={state.lang}
          onChange={(e) => onChange({ lang: e.target.value })}
        />
      </div>
      <textarea
        data-testid={`panel-${id}-textarea`}
        dir="auto"
        disabled={state.busy}
        placeholder={'Paste text\nor drop a file here (.docx, .md, .txt)'}
        value={state.text}
        onChange={(e) => onChange({ text: e.target.value, error: null })}
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => {
          e.preventDefault();
          const warning = e.dataTransfer.files.length > 1 ? 'Only the first file was loaded' : null;
          void loadFile(e.dataTransfer.files[0], warning);
        }}
      />
      {state.busy && <div className="va-upload-busy">Extracting text…</div>}
      <div className="va-upload-panel-foot">
        <button className="va-upload-file-btn" data-testid={`panel-${id}-file-btn`} onClick={() => fileRef.current?.click()}>
          📄 Upload file
        </button>
        <span className="va-upload-file-hint">{ACCEPT.split(',').join(' · ')}</span>
        <input ref={fileRef} type="file" accept={ACCEPT} hidden
               onChange={(e) => void loadFile(e.target.files?.[0])} />
        <span className="va-upload-counter">{paras.length} ¶ · {state.text.length} chars</span>
      </div>
      {state.error && <div className="va-upload-error" data-testid={`panel-${id}-error`}>{state.error}</div>}
    </div>
  );
}

export default function UploadModal() {
  const closeUploadModal = useDemoStore((s) => s.closeUploadModal);
  const [title, setTitle] = useState('');
  const [src, setSrc] = useState<SideState>({ text: '', lang: '', busy: false, error: null });
  const [tgt, setTgt] = useState<SideState>({ text: '', lang: '', busy: false, error: null });
  const [step, setStep] = useState<1 | 2>(1);

  const srcParas = splitParagraphs(src.text);
  const tgtParas = splitParagraphs(tgt.text);
  const tooLong = [...srcParas, ...tgtParas].some((p) => p.length > MAX_PARA_CHARS);
  const tooMany = srcParas.length > MAX_PARAS || tgtParas.length > MAX_PARAS;
  const srcLang = src.lang.trim();
  const tgtLang = tgt.lang.trim();
  const sameLang = !!srcLang && srcLang.toLowerCase() === tgtLang.toLowerCase();
  const canNext = !!title.trim() && !!src.text.trim() && !!tgt.text.trim()
    && !!srcLang && !!tgtLang && !sameLang && !tooLong && !tooMany && !src.busy && !tgt.busy;

  const problems = [
    sameLang && 'Source and target languages must differ',
    tooMany && `At most ${MAX_PARAS} paragraphs per side`,
    tooLong && `A paragraph exceeds ${MAX_PARA_CHARS} characters — split it`,
  ].filter(Boolean) as string[];

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') closeUploadModal();
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [closeUploadModal]);

  return (
    <div className="va-popover-backdrop va-modal-backdrop" onClick={closeUploadModal}>
      <div className="va-modal-wide" onClick={(e) => e.stopPropagation()}>
        {step === 1 ? (
          <>
            <div className="va-modal-title">New source–translation pair</div>
            <input className="va-modal-title-input" placeholder="Title"
                   value={title} onChange={(e) => setTitle(e.target.value)} />
            <div className="va-upload-panels">
              <SidePanel id="source" label="Source" langPlaceholder="Russian" state={src}
                         onChange={(p) => setSrc((s) => ({ ...s, ...p }))} />
              <SidePanel id="target" label="Translation" langPlaceholder="English" state={tgt}
                         onChange={(p) => setTgt((s) => ({ ...s, ...p }))} />
            </div>
            {problems.map((p) => <div key={p} className="va-upload-error">⚠ {p}</div>)}
            {(!srcLang || !tgtLang) && (
              <div className="va-upload-hint" data-testid="upload-lang-hint">
                Enter source and target languages to continue
              </div>
            )}
            <div className="va-modal-actions">
              <button onClick={closeUploadModal}>Cancel</button>
              <button className="va-primary" disabled={!canNext} onClick={() => setStep(2)}>
                Next →
              </button>
            </div>
          </>
        ) : (
          <Step2 title={title} srcLang={srcLang} tgtLang={tgtLang}
                 srcParas={srcParas} tgtParas={tgtParas} onBack={() => setStep(1)} />
        )}
      </div>
    </div>
  );
}

export function mergeUp(list: string[], i: number): string[] {
  if (i === 0) return list;
  const next = [...list];
  next[i - 1] = `${next[i - 1]}\n${next[i]}`;
  next.splice(i, 1);
  return next;
}

export function Step2(props: {
  title: string; srcLang: string; tgtLang: string;
  srcParas: string[]; tgtParas: string[]; onBack: () => void;
}) {
  const createDoc = useDemoStore((s) => s.createDoc);
  const [src, setSrc] = useState(props.srcParas);
  const [tgt, setTgt] = useState(props.tgtParas);
  const [precompute, setPrecompute] = useState(true);        // default ON (spec decision #5)
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  // Synchronous re-entry guard: `submitting` state updates only on re-render,
  // so rapid double/triple-clicks can fire several real (paid-precompute)
  // createDoc calls before React disables the button. Same pattern as the
  // model Test button fix in SettingsTab.
  const inFlight = useRef(false);

  const criteriaCount = useDemoStore((s) => s.criteria.filter((c) => c.enabled).length);
  const n = Math.max(src.length, tgt.length);
  const aligned = src.length === tgt.length && src.length > 0;
  const precomputePlanned = Math.min(src.length, PRECOMPUTE_MAX_PARAS);
  const precomputeCostUsd = Math.round(precomputePlanned * criteriaCount * PRECOMPUTE_COST_PER_CALL * 100) / 100;

  const submit = async () => {
    if (inFlight.current) return;
    inFlight.current = true;
    setSubmitting(true);
    setSubmitError(null);
    try {
      await createDoc({
        title: props.title, sourceLang: props.srcLang, targetLang: props.tgtLang,
        precompute, paragraphs: src.map((s, i) => ({ source: s, target: tgt[i] })),
      });
    } catch (e) {
      setSubmitError(String(e));
      setSubmitting(false);
    } finally {
      inFlight.current = false;
    }
  };

  return (
    <>
      <div className="va-modal-title">Paragraph alignment</div>
      <div className="va-step2-counts">
        Source: {src.length} ¶ · Translation: {tgt.length} ¶
        {!aligned && <span className="va-upload-error"> ⚠ counts do not match</span>}
      </div>
      <table className="va-step2-table">
        <tbody>
          {Array.from({ length: n }, (_, i) => (
            <tr key={i} className={src[i] === undefined || tgt[i] === undefined ? 'orphan' : ''}>
              <td>{i + 1}</td>
              <td dir="auto">
                {src[i] ?? '— (no pair)'}
                {i > 0 && src[i] !== undefined && (
                  <button className="va-btn-secondary" data-testid={`step2-merge-src-${i}`} onClick={() => setSrc(mergeUp(src, i))}>
                    ⇧ merge with previous
                  </button>
                )}
              </td>
              <td dir="auto">
                {tgt[i] ?? '— (no pair)'}
                {i > 0 && tgt[i] !== undefined && (
                  <button className="va-btn-secondary" data-testid={`step2-merge-tgt-${i}`} onClick={() => setTgt(mergeUp(tgt, i))}>
                    ⇧ merge with previous
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <label className="va-step2-precompute">
        <input type="checkbox" data-testid="precompute-checkbox"
               checked={precompute} onChange={(e) => setPrecompute(e.target.checked)} />
        Score the document and warm the cache fallback after creation
        (first {precomputePlanned} ¶, ~${precomputeCostUsd.toFixed(2)}, in background)
      </label>
      {submitError && <div className="va-upload-error">{submitError}</div>}
      <div className="va-modal-actions">
        <button onClick={props.onBack}>← Back</button>
        <button className="va-primary" data-testid="upload-submit"
                disabled={!aligned || submitting} onClick={() => void submit()}>
          Create document
        </button>
      </div>
    </>
  );
}
