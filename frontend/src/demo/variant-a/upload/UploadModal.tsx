import { useEffect, useRef, useState } from 'react';
import { useDemoStore } from '../../store';
import { MAX_PARAGRAPHS, MAX_PARA_CHARS } from '../../limits';
import { ACCEPT, errorMessage, ingestFile, splitParagraphs } from './file-ingest';
import UploadIcon from './UploadIcon';

// Mirrors precompute.py: PRECOMPUTE_PARAS (first 12 ¶) x one judge call per
// enabled criterion x ~$0.004/call (default seed model). Independent of the
// upload paragraph/char limits (limits.ts) — this is a pricing estimate, not
// an input cap.
const PRECOMPUTE_MAX_PARAS = 12;
const PRECOMPUTE_COST_PER_CALL = 0.004;

interface SideState { text: string; lang: string; busy: boolean; error: string | null }

/** Translation-panel-only AI-translate wiring (S4 §3.2): present only on the
 * target SidePanel. `eligible` gates the "Translate with AI" CTA row;
 * `active` swaps the textarea for the placeholder card. */
interface AiTranslateProps {
  eligible: boolean;
  active: boolean;
  modelName: string | null;
  onEnable: () => void;
  onDisable: () => void;
}

export function SidePanel(props: {
  id: 'source' | 'target';
  label: string;
  langPlaceholder: string;
  state: SideState;
  onChange: (patch: Partial<SideState>) => void;
  aiTranslate?: AiTranslateProps;
}) {
  const { id, label, langPlaceholder, state, onChange, aiTranslate } = props;
  const fileRef = useRef<HTMLInputElement>(null);
  const [dragActive, setDragActive] = useState(false);
  const paras = splitParagraphs(state.text);
  const active = !!aiTranslate?.active;

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
    <div
      className={`va-upload-panel${dragActive ? ' va-upload-drop-active' : ''}`}
      data-testid={`panel-${id}`}
    >
      <div className="va-upload-panel-head">
        <span>
          {label}
          {dragActive && <span className="va-drop-flag">drop to load</span>}
        </span>
        <input
          className="va-lang-input"
          data-testid={`panel-${id}-lang`}
          placeholder={langPlaceholder}
          value={state.lang}
          onChange={(e) => onChange({ lang: e.target.value })}
        />
      </div>

      {active ? (
        <div className="va-ai-translate-card" data-testid="ai-translate-card">
          <span className="glyph">✦</span>
          <div className="msg">
            Will be translated by <b>{aiTranslate!.modelName ?? 'the configured model'}</b> after upload
          </div>
          <button className="va-link-btn" onClick={aiTranslate!.onDisable}>
            ↩ Paste translation instead
          </button>
        </div>
      ) : (
        <textarea
          data-testid={`panel-${id}-textarea`}
          dir="auto"
          disabled={state.busy}
          placeholder={dragActive ? 'Drop file to load' : 'Paste text\nor drop a file here (.docx, .md, .txt)'}
          value={state.text}
          onChange={(e) => onChange({ text: e.target.value, error: null })}
          onDragEnter={(e) => { e.preventDefault(); setDragActive(true); }}
          onDragOver={(e) => e.preventDefault()}
          onDragLeave={() => setDragActive(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragActive(false);
            const warning = e.dataTransfer.files.length > 1 ? 'Only the first file was loaded' : null;
            void loadFile(e.dataTransfer.files[0], warning);
          }}
        />
      )}

      {state.busy && <div className="va-upload-busy">Extracting text…</div>}

      <div className="va-upload-panel-foot" style={active ? { opacity: 0.4 } : undefined}>
        <button
          className="va-upload-file-btn"
          data-testid={`panel-${id}-file-btn`}
          disabled={active}
          onClick={() => fileRef.current?.click()}
        >
          <UploadIcon />Upload file
        </button>
        <span className="va-upload-file-hint">{ACCEPT.split(',').join(' · ')}</span>
        <input ref={fileRef} type="file" accept={ACCEPT} hidden disabled={active}
               onChange={(e) => void loadFile(e.target.files?.[0])} />
        {!active && <span className="va-upload-counter">{paras.length} ¶ · {state.text.length} chars</span>}
      </div>

      {aiTranslate?.eligible && (
        <div className="va-upload-panel-foot va-ai-translate-cta-row">
          <button
            className="va-btn-secondary va-ai-translate-cta"
            data-testid="ai-translate-cta"
            onClick={aiTranslate.onEnable}
          >
            ✦ No translation? Translate with AI
          </button>
        </div>
      )}

      {state.error && <div className="va-upload-error" data-testid={`panel-${id}-error`}>{state.error}</div>}
    </div>
  );
}

/** Explains why Next/Create is disabled with the REAL blocking reason (S3
 * §2.3) — a single string|null slot, rendered in one place, instead of the
 * old always-about-languages hint. */
export function nextBlockReason(
  srcLang: string,
  tgtLang: string,
  srcText: string,
  tgtText: string,
  aiTranslateMode: boolean,
): string | null {
  if (!srcLang || !tgtLang) return 'Enter source and target languages to continue';
  if (aiTranslateMode) {
    if (!srcText.trim()) return 'Add source text to continue';
    return null;
  }
  if (!srcText.trim() || !tgtText.trim()) return 'Add source and translation text to continue';
  return null;
}

export default function UploadModal() {
  const closeUploadModal = useDemoStore((s) => s.closeUploadModal);
  const createDoc = useDemoStore((s) => s.createDoc);
  const translatorModelName = useDemoStore((s) => s.translatorConfig?.modelName ?? null);
  const [title, setTitle] = useState('');
  const [src, setSrc] = useState<SideState>({ text: '', lang: '', busy: false, error: null });
  const [tgt, setTgt] = useState<SideState>({ text: '', lang: '', busy: false, error: null });
  const [step, setStep] = useState<1 | 2>(1);
  const [aiTranslateMode, setAiTranslateMode] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  // Synchronous re-entry guard — see Step2's submit comment for why `submitting`
  // state alone is too slow to stop a rapid double/triple-click.
  const inFlight = useRef(false);

  const srcParas = splitParagraphs(src.text);
  const tgtParas = splitParagraphs(tgt.text);
  // AI-translate mode never submits the target side, so leftover pasted text
  // there (from before the toggle) must not spuriously block Next.
  const relevantParas = aiTranslateMode ? srcParas : [...srcParas, ...tgtParas];
  const tooLong = relevantParas.some((p) => p.length > MAX_PARA_CHARS);
  const tooMany = srcParas.length > MAX_PARAGRAPHS || (!aiTranslateMode && tgtParas.length > MAX_PARAGRAPHS);
  const srcLang = src.lang.trim();
  const tgtLang = tgt.lang.trim();
  const sameLang = !!srcLang && srcLang.toLowerCase() === tgtLang.toLowerCase();
  const canNext = !!title.trim() && !!src.text.trim() && (aiTranslateMode || !!tgt.text.trim())
    && !!srcLang && !!tgtLang && !sameLang && !tooLong && !tooMany && !src.busy
    && (aiTranslateMode || !tgt.busy);

  const problems = [
    sameLang && 'Source and target languages must differ',
    tooMany && `At most ${MAX_PARAGRAPHS} paragraphs per side`,
    tooLong && `A paragraph exceeds ${MAX_PARA_CHARS} characters — split it`,
  ].filter(Boolean) as string[];

  const blockReason = problems.length === 0
    ? nextBlockReason(srcLang, tgtLang, src.text, tgt.text, aiTranslateMode)
    : null;

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') closeUploadModal();
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [closeUploadModal]);

  async function submitTranslate() {
    if (inFlight.current) return;
    inFlight.current = true;
    setSubmitting(true);
    setSubmitError(null);
    try {
      await createDoc({
        title: title.trim(),
        sourceLang: srcLang,
        targetLang: tgtLang,
        precompute: false,
        translate: true,
        paragraphs: srcParas.map((s) => ({ source: s, target: '' })),
      });
    } catch (e) {
      setSubmitError(String(e));
      setSubmitting(false);
    } finally {
      inFlight.current = false;
    }
  }

  return (
    <div className="va-popover-backdrop va-modal-backdrop" onClick={closeUploadModal}>
      <div className="va-modal-wide" onClick={(e) => e.stopPropagation()}>
        {step === 1 ? (
          <>
            <div className="va-modal-title">
              {aiTranslateMode ? 'New document' : 'New source–translation pair'}
            </div>
            <input className="va-modal-title-input" placeholder="Title"
                   value={title} onChange={(e) => setTitle(e.target.value)} />
            <div className="va-upload-panels">
              <SidePanel id="source" label="Source" langPlaceholder="Russian" state={src}
                         onChange={(p) => setSrc((s) => ({ ...s, ...p }))} />
              <SidePanel id="target" label="Translation" langPlaceholder="English" state={tgt}
                         onChange={(p) => setTgt((s) => ({ ...s, ...p }))}
                         aiTranslate={{
                           eligible: !aiTranslateMode && !!src.text.trim() && !tgt.text.trim(),
                           active: aiTranslateMode,
                           modelName: translatorModelName,
                           onEnable: () => setAiTranslateMode(true),
                           onDisable: () => setAiTranslateMode(false),
                         }} />
            </div>
            {problems.map((p) => <div key={p} className="va-upload-error">⚠ {p}</div>)}
            {blockReason && (
              <div className="va-upload-hint" data-testid="upload-lang-hint">
                {blockReason}
              </div>
            )}
            {submitError && <div className="va-upload-error">{submitError}</div>}
            <div className="va-modal-actions">
              <button onClick={closeUploadModal}>Cancel</button>
              {aiTranslateMode ? (
                <button className="va-primary" data-testid="upload-submit-translate"
                        disabled={!canNext || submitting} onClick={() => void submitTranslate()}>
                  {submitting ? '…' : 'Create & translate'}
                </button>
              ) : (
                <button className="va-primary" disabled={!canNext} onClick={() => setStep(2)}>
                  Next →
                </button>
              )}
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
