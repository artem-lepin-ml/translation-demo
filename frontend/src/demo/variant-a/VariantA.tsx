/**
 * Variant A — "Reader" layout wired to the live backend via Zustand store.
 *
 * Data source: useDemoStore (replaces mock data.ts).
 * Loop: Accept → applyEdit → evaluate; loading state; cached badge; failedCriterionIds.
 * Reset: POST /api/documents/{id}/reset.
 * Terminology: two signals (difficulty on RU, pairAccuracy on EN pair).
 * Settings: params bag editor; model picker by name from registry.
 */

import { useState, useCallback, useMemo, useEffect, useRef } from 'react';
import './variant-a.css';

import { useDemoStore, scoreBand } from '../store';
import { langLabel } from '../lang';
import { exportUrl } from '../api-client';
import type { Document, Issue, Term } from '../api-client';

import IssuePopover from './IssuePopover';
import TermPopover from './TermPopover';
import GlossaryTab, { termsStatusEmptyMessage } from './GlossaryTab';
import RankingTab from './RankingTab';
import SettingsTab from './SettingsTab';
import EditorParagraph, { ScoreChip, computeChipDelta } from './EditorParagraph';
import InspectorPanel from './InspectorPanel';
import UploadModal from './upload/UploadModal';
import DocumentPicker from './DocumentPicker';

type TabId = 'document' | 'glossary' | 'ranking' | 'settings';

/** Precompute ran to completion but produced zero scored paragraphs (e.g. every
 * judge call failed on a missing API key) — the score chips would otherwise
 * just sit at "—" forever with no indication anything went wrong (BUG-5). */
export function precomputeFailed(precompute: Document['precompute']): boolean {
  return precompute?.status === 'done' && precompute.planned > 0 && precompute.succeeded === 0;
}

/** Human-readable cause for the precompute-failed notice (S1 §2.6) — replaces
 * the old unconditional "something's wrong" text with the server's own
 * error_reason where available. */
export function precomputeFailedMessage(precompute: Document['precompute']): string {
  switch (precompute?.errorReason) {
    case 'no_api_key':
      return 'Precompute skipped: no API key configured';
    case 'budget_exhausted':
      return 'Precompute skipped: budget cap reached';
    default:
      return 'Precompute failed — scores unavailable; use Evaluate ↻ on a paragraph';
  }
}

/** Download glyph matching UploadIcon's style (S6 §5) — tray + arrow-down. */
function DownloadIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
         strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M12 4v11M12 15l-4.5-4.5M12 15l4.5-4.5" />
      <path d="M4 16v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2" />
    </svg>
  );
}

const TABS: { id: TabId; label: string }[] = [
  { id: 'document', label: 'Document' },
  { id: 'glossary', label: 'Glossary' },
  { id: 'ranking', label: 'Ranking' },
  { id: 'settings', label: 'Settings' },
];

/** The popover shows OPEN issues only: accepted/dismissed cards must not linger
 *  with live Accept/Dismiss buttons, and the popover's own empty-list effect
 *  (see handleSegmentClick's caller) auto-closes once none remain. Pure —
 *  unit-tested directly. */
export function selectPopoverIssues(
  paraIssues: Issue[],
  issueIds: string[],
  activeCriteria: Set<string>,
): Issue[] {
  const byId = new Map(paraIssues.map((i) => [i.id, i]));
  return issueIds
    .map((id) => byId.get(id))
    .filter((i): i is Issue => !!i && i.status === 'open' && activeCriteria.has(i.criterionId));
}

export default function VariantA() {
  // ── Store ─────────────────────────────────────────────────────────────────

  const {
    document: doc,
    documents,
    criteria,
    models,
    groundingConfig,
    translatorConfig,
    refinerConfig,
    documentLoading,
    documentError,
    paraEvalState,
    selectedParaIdx,
    inspectorTab,
    inspectorCollapsed,
    activeCriteria,
    showTerms,
    hoveredTermId,
    init,
    setSelectedParaIdx,
    setInspectorTab,
    setInspectorCollapsed,
    toggleCriterion,
    setShowTerms,
    setHoveredTermId,
    acceptIssue,
    dismissIssue,
    acceptAllIssues,
    evaluateParagraph,
    refineParagraph,
    resetDoc,
    saveCriterion,
    addCriterion,
    removeCriterion,
    saveModel,
    addModel,
    removeModel,
    testModel,
    saveGroundingConfig,
    saveTranslatorConfig,
    saveRefinerConfig,
    retryTranslate,
    runFirstParagraphsEvaluate,
    restoreParagraphRevision,
    switchDocument,
    deleteDoc,
    openUploadModal,
    uploadModalOpen,
    refreshDocument,
    backToPicker,
    startTermsPolling,
    stopTermsPolling,
  } = useDemoStore();

  // ── Local UI state ────────────────────────────────────────────────────────

  const [activeTab, setActiveTab] = useState<TabId>('document');
  const [issuePopover, setIssuePopover] =
    useState<{ paraId: number; issueIds: string[]; rect: DOMRect } | null>(null);
  const [termPopover, setTermPopover] = useState<{ term: Term; rect: DOMRect } | null>(null);
  const [resetting, setResetting] = useState(false);
  // Translation-done badge fades after 5s (S4 §3.3) — tracked per doc so
  // switching documents doesn't leave a stale fade timer running.
  const [translationDoneVisible, setTranslationDoneVisible] = useState(true);
  const [exportMenuOpen, setExportMenuOpen] = useState(false);
  const [runningFirstEvaluate, setRunningFirstEvaluate] = useState(false);
  const [retryingTranslate, setRetryingTranslate] = useState(false);

  // Debounce target text PATCH
  const pendingTextRef = useRef<Map<number, ReturnType<typeof setTimeout>>>(new Map());

  // ── Init on mount ─────────────────────────────────────────────────────────

  useEffect(() => {
    void init();
  }, [init]);

  // Precompute badge polling — owned by the top bar, survives tab switches,
  // tears down on doc switch, resumes on switch-back while still running.
  useEffect(() => {
    if (!doc || doc.origin !== 'upload') return;
    if (doc.precompute?.status !== 'running') return;
    const t = setInterval(() => void refreshDocument(), 3000);
    return () => clearInterval(t);
  }, [doc?.id, doc?.precompute?.status, refreshDocument]);

  // Translation badge polling — mirrors the precompute effect above exactly
  // (S4 §3.3: "poll every 3s while running").
  useEffect(() => {
    if (!doc || doc.origin !== 'upload') return;
    if (doc.translation?.status !== 'running') return;
    const t = setInterval(() => void refreshDocument(), 3000);
    return () => clearInterval(t);
  }, [doc?.id, doc?.translation?.status, refreshDocument]);

  // Terms-status polling — the store owns the single interval (idempotent
  // start/stop); this effect only decides WHEN to poll: while terminology is
  // running, or while translation is still filling targets (terms extraction
  // follows it, so the chip should keep refreshing through both phases).
  // Cleared on done/failed (condition goes false → cleanup), unmount (React
  // cleanup) and doc switch (doc?.id in the deps re-runs the effect).
  useEffect(() => {
    if (!doc) return;
    const running = doc.termsStatus === 'running' || doc.translation?.status === 'running';
    if (!running) return;
    startTermsPolling();
    return () => stopTermsPolling();
  }, [doc?.id, doc?.termsStatus, doc?.translation?.status, startTermsPolling, stopTermsPolling]);

  // "Translated N¶" badge fades 5s after the run completes (S4 §3.3).
  useEffect(() => {
    if (doc?.translation?.status !== 'done') return;
    setTranslationDoneVisible(true);
    const t = setTimeout(() => setTranslationDoneVisible(false), 5000);
    return () => clearTimeout(t);
  }, [doc?.id, doc?.translation?.status, doc?.translation?.done]);

  // ── Derived data ──────────────────────────────────────────────────────────

  const paragraphs = useMemo(() => doc?.paragraphs ?? [], [doc]);

  const selectedPara = paragraphs[selectedParaIdx] ?? null;

  const showPrecomputeFailedNotice = precomputeFailed(doc?.precompute);

  const allOpenIssues = useMemo(
    () =>
      paragraphs.flatMap((p) =>
        p.issues.filter((i) => i.status === 'open' && activeCriteria.has(i.criterionId)),
      ),
    [paragraphs, activeCriteria],
  );

  const inspectorIssues = useMemo(
    () => selectedPara?.issues.filter((i) => activeCriteria.has(i.criterionId)) ?? [],
    [selectedPara, activeCriteria],
  );

  const closedIssueIds = useMemo(() => {
    const s = new Set<string>();
    paragraphs.forEach((p) =>
      p.issues.forEach((i) => {
        if (i.status !== 'open') s.add(i.id);
      }),
    );
    return s;
  }, [paragraphs]);

  const isDocRescoring = useMemo(
    () => Object.values(paraEvalState).some((s) => s.loading),
    [paraEvalState],
  );

  const docAggregate = useMemo(() => {
    const vals = paragraphs.map((p) => p.aggregate).filter((v): v is number => v !== null);
    if (vals.length === 0) return null;
    return Math.round((vals.reduce((a, b) => a + b, 0) / vals.length) * 10) / 10;
  }, [paragraphs]);

  const docAggBaseline = useMemo(() => {
    const vals = paragraphs.map((p) => p.aggregateBaseline).filter((v): v is number => v !== null);
    if (vals.length === 0) return null;
    return Math.round((vals.reduce((a, b) => a + b, 0) / vals.length) * 10) / 10;
  }, [paragraphs]);

  const aggBand = docAggregate !== null ? scoreBand(docAggregate) : 'yellow';

  const allTerms = useMemo(() => paragraphs.flatMap((p) => p.terms), [paragraphs]);

  const popoverIssues = useMemo(() => {
    if (!issuePopover) return [];
    const para = paragraphs.find((p) => p.id === issuePopover.paraId);
    if (!para) return [];
    return selectPopoverIssues(para.issues, issuePopover.issueIds, activeCriteria);
  }, [issuePopover, paragraphs, activeCriteria]);

  // ── Handlers ──────────────────────────────────────────────────────────────

  const handleSegmentClick = useCallback((info: { issues: Issue[]; rect: DOMRect }) => {
    if (info.issues.length === 0) return;
    setIssuePopover({
      paraId: info.issues[0].paragraphId,
      issueIds: info.issues.map((i) => i.id),
      rect: info.rect,
    });
  }, []);

  // Close the popover once its derived card list runs dry (all accepted/dismissed/
  // filtered out or paragraph gone). Explicit close (✕, backdrop) already calls
  // setIssuePopover(null) directly.
  useEffect(() => {
    if (issuePopover && popoverIssues.length === 0) setIssuePopover(null);
  }, [issuePopover, popoverIssues.length]);

  const handleTermClick = useCallback((term: Term, rect: DOMRect) => {
    setTermPopover({ term, rect });
  }, []);

  const pendingScrollRef = useRef(false);

  const handleRankingRowClick = useCallback(
    (idx: number) => {
      setSelectedParaIdx(idx);
      setInspectorTab('issues');
      pendingScrollRef.current = true;
      setActiveTab('document');
    },
    [setSelectedParaIdx, setInspectorTab],
  );

  // Scroll the Document view to the paragraph picked in Ranking. The Document
  // tab has just been re-mounted, so wait one frame for layout before scrolling.
  useEffect(() => {
    if (activeTab !== 'document' || !pendingScrollRef.current) return;
    pendingScrollRef.current = false;
    requestAnimationFrame(() => {
      window.document
        .querySelector('.va-para-row.selected')
        ?.scrollIntoView({ block: 'center', behavior: 'smooth' });
    });
  }, [activeTab, selectedParaIdx]);

  function handleAcceptIssue(issue: Issue) {
    const paraIdx = paragraphs.findIndex((p) => p.id === issue.paragraphId);
    if (paraIdx === -1) return;
    void acceptIssue(issue.paragraphId, paraIdx, issue.id);
  }

  function handleDismissIssue(issue: Issue) {
    void dismissIssue(issue.id);
  }

  // Synchronous re-entry guard: the buttons' `disabled={isLoading}` derives
  // from Zustand state and only reaches the DOM on the next React render, so
  // a rapid double/triple-click fires several real (paid) LLM calls before
  // React disables it — Refine is a rewrite+rescore pair, so a triple-click
  // can mean up to 6 paid calls. Same idiom as SettingsTab's handleTest guard
  // and UploadModal's submit guard. Keyed by paraIdx (Set, not a single bool)
  // so an in-flight call on one paragraph never blocks a click on another;
  // shared between Refine and Evaluate so either one in flight blocks both,
  // mirroring the combined `isLoading` the buttons already render against.
  const inFlightEvalRef = useRef<Set<number>>(new Set());

  async function handleRefine() {
    if (!selectedPara) return;
    if (inFlightEvalRef.current.has(selectedParaIdx)) return;
    inFlightEvalRef.current.add(selectedParaIdx);
    try {
      await refineParagraph(selectedPara.id, selectedParaIdx);
    } finally {
      inFlightEvalRef.current.delete(selectedParaIdx);
    }
  }

  async function handleEvaluate() {
    if (!selectedPara) return;
    if (inFlightEvalRef.current.has(selectedParaIdx)) return;
    inFlightEvalRef.current.add(selectedParaIdx);
    try {
      await evaluateParagraph(selectedPara.id, selectedParaIdx);
    } finally {
      inFlightEvalRef.current.delete(selectedParaIdx);
    }
  }

  function handleRetryFailed(criterionIds: string[]) {
    if (!selectedPara || criterionIds.length === 0) return;
    void evaluateParagraph(selectedPara.id, selectedParaIdx, criterionIds);
  }

  function handleAcceptAllDoc() {
    const byPara = new Map<number, { paraId: number; idx: number; ids: string[] }>();
    for (const iss of allOpenIssues) {
      if (!iss.suggestion) continue;            // nothing to apply
      const idx = paragraphs.findIndex((p) => p.id === iss.paragraphId);
      if (idx === -1) continue;
      if (!byPara.has(iss.paragraphId)) byPara.set(iss.paragraphId, { paraId: iss.paragraphId, idx, ids: [] });
      byPara.get(iss.paragraphId)!.ids.push(iss.id);
    }
    if (byPara.size === 0) return;
    const nIssues = [...byPara.values()].reduce((n, g) => n + g.ids.length, 0);
    const ok = window.confirm(
      `Accept ${nIssues} issues across ${byPara.size} paragraphs?\n` +
      `All suggestions are applied; scores go stale until you press Evaluate.`,
    );
    if (!ok) return;
    for (const { paraId, idx, ids } of byPara.values()) {
      void acceptAllIssues(paraId, idx, ids);
    }
  }

  async function handleReset() {
    const resetTarget = doc?.origin === 'upload' ? 'its originally uploaded state' : 'its seed state';
    const ok = window.confirm(
      `Reset the document to ${resetTarget}?\n` +
      'Live scores and issues will be archived (hidden, not deleted); ' +
      'every paragraph reverts to its seed text.',
    );
    if (!ok) return;
    setResetting(true);
    await resetDoc();
    setResetting(false);
  }

  async function handleRunFirstEvaluate() {
    setRunningFirstEvaluate(true);
    try {
      await runFirstParagraphsEvaluate();
    } finally {
      setRunningFirstEvaluate(false);
    }
  }

  async function handleRetryTranslate() {
    setRetryingTranslate(true);
    try {
      await retryTranslate();
    } finally {
      setRetryingTranslate(false);
    }
  }

  function handleExport(format: 'xlsx' | 'md') {
    if (!doc) return;
    const a = window.document.createElement('a');
    a.href = exportUrl(doc.id, format);
    a.download = '';
    window.document.body.appendChild(a);
    a.click();
    a.remove();
    setExportMenuOpen(false);
  }

  function handleTextChange(paraId: number, text: string) {
    const existing = pendingTextRef.current.get(paraId);
    if (existing) clearTimeout(existing);
    const timer = setTimeout(() => {
      void useDemoStore.getState().saveParagraphTarget(paraId, text);
      pendingTextRef.current.delete(paraId);
    }, 800);
    pendingTextRef.current.set(paraId, timer);
  }

  // ── Loading / error states ────────────────────────────────────────────────

  if (documentLoading && !doc) {
    return (
      <div className="va-root" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100vh' }}>
        <span style={{ color: 'var(--va-text-muted)', fontSize: 16 }}>Loading document…</span>
      </div>
    );
  }

  if (documentError && !doc) {
    return (
      <div className="va-root" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100vh' }}>
        <span style={{ color: 'var(--va-red)', fontSize: 15 }}>Error: {documentError}</span>
      </div>
    );
  }

  // No document selected — landing picker (init() no longer auto-opens the
  // first document; brand click in the workspace chrome below also lands here
  // via backToPicker). The upload modal must be reachable from this branch
  // too (the picker's "Blank document" card opens it).
  if (!doc) {
    return (
      <div className="va-root">
        <DocumentPicker
          documents={documents}
          onSelect={(id) => void switchDocument(id)}
          onCreateBlank={() => openUploadModal({ aiTranslateDefault: true })}
        />
        {uploadModalOpen && <UploadModal />}
      </div>
    );
  }

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <div className="va-root">
      {/* ─── Top Chrome ─────────────────────────────────────────────────── */}
      <div className="va-chrome">
        <button
          type="button"
          className="va-brand va-brand-clickable"
          onClick={backToPicker}
          title="Back to documents"
        >
          Glossa-MT
        </button>

        <div className="va-tabs">
          {TABS.map((t) => (
            <button
              key={t.id}
              className={`va-tab${activeTab === t.id ? ' active' : ''}`}
              onClick={() => setActiveTab(t.id)}
            >
              {t.label}
            </button>
          ))}
        </div>

        <div className="va-doc-switcher">
          <select
            data-testid="doc-dropdown"
            value={doc.id}
            disabled={isDocRescoring}
            onChange={(e) => void switchDocument(Number(e.target.value))}
          >
            {documents.map((d) => (
              <option key={d.id} value={d.id}>
                {d.title} · {langLabel(d.sourceLang)} → {langLabel(d.targetLang)} · {d.nParagraphs}¶
              </option>
            ))}
          </select>
          {doc.origin === 'upload' && (
            <button
              className="va-icon-btn"
              title="Delete document"
              onClick={() => {
                if (window.confirm(`Delete "${doc.title}"?`)) void deleteDoc(doc.id);
              }}
            >
              🗑
            </button>
          )}
          <button className="va-chip" data-testid="upload-open" onClick={() => openUploadModal()}>
            + Upload pair
          </button>
          {doc.precompute?.status === 'running' && (
            <span className="va-precompute-badge">
              warming {doc.precompute.done}/{doc.precompute.planned} ¶…
            </span>
          )}
          {doc.translation?.status === 'running' && (
            <span className="va-translate-progress-wrap" data-testid="translation-badge">
              <span className="va-translating-badge">
                Translating {doc.translation.done}/{doc.translation.total}…
              </span>
              <div className="va-progress-track">
                <div
                  className="va-progress-fill"
                  style={{ width: `${doc.translation.total > 0 ? (doc.translation.done / doc.translation.total) * 100 : 0}%` }}
                />
              </div>
            </span>
          )}
          {doc.translation?.status === 'done' && translationDoneVisible && (
            <span className="va-translate-progress-wrap" data-testid="translation-done-badge">
              <span className="va-translating-badge" style={{ color: 'var(--va-green)' }}>
                Translated {doc.translation.total}¶
              </span>
              <span className="va-run-precompute-hint">
                Evaluate first paragraphs?{' '}
                <button className="va-link-btn" disabled={runningFirstEvaluate} onClick={() => void handleRunFirstEvaluate()}>
                  {runningFirstEvaluate ? 'Running…' : 'Run'}
                </button>
              </span>
            </span>
          )}
          {doc.translation?.status === 'failed' && (
            <span className="va-translate-progress-wrap" data-testid="translation-failed-badge">
              <span className="va-translating-badge" style={{ color: 'var(--va-red)' }}>
                Translation failed{doc.translation.errorReason ? `: ${doc.translation.errorReason}` : ''}
              </span>
              <button className="va-btn-secondary" disabled={retryingTranslate} onClick={() => void handleRetryTranslate()}>
                {retryingTranslate ? 'Retrying…' : 'Retry'}
              </button>
            </span>
          )}
        </div>

        <div className="va-chrome-right">
          {/* Reset button */}
          {activeTab === 'document' && (
            <button
              className="va-btn-secondary"
              disabled={resetting || isDocRescoring}
              onClick={() => void handleReset()}
              title="Reset document to seed state"
              style={{ marginRight: 8 }}
            >
              {resetting ? 'Resetting…' : 'Reset'}
            </button>
          )}

          {/* Export (S6 §5) */}
          {activeTab === 'document' && (
            <span className="va-export-wrap" style={{ marginRight: 8 }}>
              <button
                className="va-btn-secondary"
                data-testid="export-btn"
                disabled={paragraphs.length === 0}
                onClick={() => setExportMenuOpen((v) => !v)}
              >
                <DownloadIcon />Export
              </button>
              {exportMenuOpen && (
                <>
                  <div className="va-popover-backdrop" style={{ background: 'transparent' }} onClick={() => setExportMenuOpen(false)} />
                  <div className="va-export-menu" data-testid="export-menu">
                    <div className="va-export-menu-item" data-testid="export-xlsx" onClick={() => handleExport('xlsx')}>
                      <DownloadIcon />Excel (.xlsx)
                    </div>
                    <div className="va-export-menu-item" data-testid="export-md" onClick={() => handleExport('md')}>
                      <DownloadIcon />Markdown (.md)
                    </div>
                  </div>
                </>
              )}
            </span>
          )}

          {/* Doc-level Accept all */}
          {activeTab === 'document' && (
            <button
              className="va-accept-all-doc"
              disabled={isDocRescoring || allOpenIssues.length === 0}
              onClick={handleAcceptAllDoc}
              title="Accept all issues across all paragraphs"
            >
              Accept all
              {allOpenIssues.length > 0 && (
                <span className="va-accept-all-badge">{allOpenIssues.length}</span>
              )}
            </button>
          )}

          {/* Doc-level score */}
          <div className="va-doc-score">
            <span className="va-doc-score-label">Score</span>
            {isDocRescoring ? (
              <span className="va-doc-score-loading">…</span>
            ) : docAggregate !== null ? (
              <>
                <span className={`va-doc-score-value ${aggBand}`}>
                  {docAggregate.toFixed(1)}
                </span>
                {docAggBaseline !== null && (
                  <span className="va-doc-score-baseline" title="Baseline">
                    {' '}/ {docAggBaseline.toFixed(1)}
                  </span>
                )}
              </>
            ) : (
              <span className="va-doc-score-value">—</span>
            )}
          </div>
        </div>
      </div>

      {/* ─── Sub-toolbar (Document tab only) ────────────────────────────── */}
      {activeTab === 'document' && (
        <div className="va-subtoolbar">
          {criteria.map((c) => {
            const on = activeCriteria.has(c.id);
            return (
              <button
                key={c.id}
                className={`va-chip${on ? '' : ' off'}`}
                style={{
                  borderColor: on ? c.color : 'transparent',
                  background: on ? c.color + '18' : 'transparent',
                }}
                onClick={() => toggleCriterion(c.id)}
              >
                <span className="chip-dot" style={{ background: c.color }} />
                {c.name}
              </button>
            );
          })}

          {doc.termsStatus === 'running' ? (
            <span className="va-chip terms-chip running" data-testid="terms-chip-running">
              <span className="va-spinner" aria-hidden="true" />
              Extracting terminology…
            </span>
          ) : (
            <button
              className={`va-chip terms-chip${showTerms ? ' on' : ''}`}
              disabled={allTerms.length === 0}
              title={allTerms.length === 0 ? termsStatusEmptyMessage(doc.termsStatus) : undefined}
              onClick={() => setShowTerms(!showTerms)}
            >
              Terms
            </button>
          )}
        </div>
      )}

      {/* ─── Body ────────────────────────────────────────────────────────── */}
      <div className="va-body">
        {activeTab === 'document' && (
          <>
            {/* Left+center: two-column doc */}
            <div className="va-doc-wrapper">
              {showPrecomputeFailedNotice && (
                <div className="va-precompute-failed-notice" data-testid="precompute-failed-notice">
                  {precomputeFailedMessage(doc.precompute)}
                </div>
              )}
              <div className="va-col-headers">
                <div className="va-col-header">Source · {langLabel(doc.sourceLang)}</div>
                <div className="va-col-header">Translation · {langLabel(doc.targetLang)}</div>
              </div>

              <div className="va-paragraphs-area">
                {paragraphs.map((para, idx) => {
                  const paraActiveIssues = para.issues.filter((i) => activeCriteria.has(i.criterionId));
                  const es = paraEvalState[idx] ?? {
                    loading: false,
                    cached: false,
                    cachedAt: null,
                    failedCriterionIds: [],
                    error: null,
                    stale: false,
                  };
                  const agg = para.aggregate;
                  const chipDelta = computeChipDelta(agg, para.aggregatePrev, para.aggregateBaseline);
                  // Best-marker (S5 §3.1) composed alongside ScoreChip rather than
                  // inside it/EditorParagraph — those files belong to another lane.
                  const best = para.best;
                  const showBestMarker = !!best && !best.isCurrent && agg !== null && best.aggregate > agg + 0.05;

                  return (
                    <EditorParagraph
                      key={para.id}
                      paragraphIndex={idx}
                      initialText={para.target}
                      sourceText={para.source}
                      activeIssues={paraActiveIssues}
                      closedIssueIds={closedIssueIds}
                      terms={para.terms}
                      showTerms={showTerms}
                      criteria={criteria}
                      selected={selectedParaIdx === idx}
                      scoreChip={
                        <>
                          <ScoreChip
                            label={`§${para.idx + 1}`}
                            score={agg}
                            loading={es.loading}
                            delta={chipDelta}
                            cached={es.cached}
                            stale={es.stale}
                            criteria={criteria}
                            scores={para.scores}
                          />
                          {showBestMarker && (
                            <span
                              className="va-best-marker"
                              data-testid="best-marker"
                              title={`Best ${best!.aggregate.toFixed(1)} — click to review`}
                              onClick={() => {
                                setSelectedParaIdx(idx);
                                setInspectorTab('scores');
                              }}
                            >
                              ⭰
                            </span>
                          )}
                        </>
                      }
                      onSelect={() => {
                        setSelectedParaIdx(idx);
                        setInspectorTab('issues');
                      }}
                      onSegmentClick={handleSegmentClick}
                      onTextChange={(text) => handleTextChange(para.id, text)}
                      onTermClick={handleTermClick}
                      hoveredTermId={hoveredTermId}
                      onTermHover={setHoveredTermId}
                    />
                  );
                })}
              </div>
            </div>

            {/* Right: Inspector panel */}
            <InspectorPanel
              tab={inspectorTab}
              onTabChange={setInspectorTab}
              paragraph={selectedPara}
              activeCriteria={activeCriteria}
              evalState={
                paraEvalState[selectedParaIdx] ?? {
                  loading: false,
                  cached: false,
                  cachedAt: null,
                  failedCriterionIds: [],
                  error: null,
                  stale: false,
                }
              }
              criteria={criteria}
              isCollapsed={inspectorCollapsed}
              onToggleCollapse={() => setInspectorCollapsed(!inspectorCollapsed)}
              onAccept={handleAcceptIssue}
              onDismiss={handleDismissIssue}
              onRefine={handleRefine}
              onEvaluate={handleEvaluate}
              onRetryFailed={handleRetryFailed}
              visibleIssues={inspectorIssues}
              onRestoreRevision={async (revisionId) => {
                if (!selectedPara) return;
                await restoreParagraphRevision(selectedPara.id, selectedParaIdx, revisionId);
              }}
            />
          </>
        )}

        {activeTab === 'glossary' && (
          <GlossaryTab
            terms={allTerms}
            paragraphs={paragraphs}
            sourceLang={doc.sourceLang}
            targetLang={doc.targetLang}
            onMentionClick={handleRankingRowClick}
            termsStatus={doc.termsStatus}
          />
        )}

        {activeTab === 'ranking' && (
          <RankingTab
            paragraphs={paragraphs}
            criteria={criteria}
            onSelectParagraph={handleRankingRowClick}
          />
        )}

        {activeTab === 'settings' && (
          <SettingsTab
            criteria={criteria}
            models={models}
            onUpdateCriterion={saveCriterion}
            onAddCriterion={addCriterion}
            onRemoveCriterion={removeCriterion}
            onSaveModel={saveModel}
            onAddModel={addModel}
            onRemoveModel={removeModel}
            onTestModel={testModel}
            groundingConfig={groundingConfig}
            onSaveGroundingConfig={saveGroundingConfig}
            translatorConfig={translatorConfig}
            onSaveTranslatorConfig={saveTranslatorConfig}
            refinerConfig={refinerConfig}
            onSaveRefinerConfig={saveRefinerConfig}
          />
        )}
      </div>

      {/* ─── Popovers ────────────────────────────────────────────────────── */}
      {issuePopover && popoverIssues.length > 0 && (
        <IssuePopover
          issues={popoverIssues}
          criteria={criteria}
          rect={issuePopover.rect}
          onAccept={handleAcceptIssue}
          onDismiss={handleDismissIssue}
          onClose={() => setIssuePopover(null)}
        />
      )}

      {termPopover && (
        <TermPopover
          term={termPopover.term}
          rect={termPopover.rect}
          onClose={() => setTermPopover(null)}
        />
      )}

      {uploadModalOpen && <UploadModal />}
    </div>
  );
}
