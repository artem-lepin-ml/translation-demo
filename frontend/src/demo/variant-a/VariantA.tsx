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
import type { Document, Issue, Term } from '../api-client';

import IssuePopover from './IssuePopover';
import TermPopover from './TermPopover';
import GlossaryTab from './GlossaryTab';
import RankingTab from './RankingTab';
import SettingsTab from './SettingsTab';
import EditorParagraph, { ScoreChip, computeChipDelta } from './EditorParagraph';
import InspectorPanel from './InspectorPanel';
import UploadModal from './upload/UploadModal';

type TabId = 'document' | 'glossary' | 'ranking' | 'settings';

/** Precompute ran to completion but produced zero scored paragraphs (e.g. every
 * judge call failed on a missing API key) — the score chips would otherwise
 * just sit at "—" forever with no indication anything went wrong (BUG-5). */
export function precomputeFailed(precompute: Document['precompute']): boolean {
  return precompute?.status === 'done' && precompute.planned > 0 && precompute.succeeded === 0;
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
    resetDoc,
    saveCriterion,
    addCriterion,
    removeCriterion,
    saveModel,
    addModel,
    removeModel,
    testModel,
    saveGroundingConfig,
    switchDocument,
    deleteDoc,
    openUploadModal,
    uploadModalOpen,
    refreshDocument,
  } = useDemoStore();

  // ── Local UI state ────────────────────────────────────────────────────────

  const [activeTab, setActiveTab] = useState<TabId>('document');
  const [issuePopover, setIssuePopover] =
    useState<{ paraId: number; issueIds: string[]; rect: DOMRect } | null>(null);
  const [termPopover, setTermPopover] = useState<{ term: Term; rect: DOMRect } | null>(null);
  const [resetting, setResetting] = useState(false);
  /** Last accept-all outcome for the selected paragraph; cleared on selection change / evaluate */
  const [acceptAllSummary, setAcceptAllSummary] =
    useState<{ applied: number; outdated: number } | null>(null);

  useEffect(() => {
    setAcceptAllSummary(null);
  }, [selectedParaIdx]);

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

  const openInspectorIssues = useMemo(
    () => inspectorIssues.filter((i) => i.status === 'open'),
    [inspectorIssues],
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

  function handleAcceptAll() {
    if (!selectedPara) return;
    const ids = openInspectorIssues.filter((i) => i.suggestion).map((i) => i.id);
    if (ids.length === 0) return;
    const ok = window.confirm(
      `Accept ${ids.length} issue(s) in §${selectedPara.idx + 1}?\n` +
      `All suggestions are applied; scores go stale until you press Evaluate.`,
    );
    if (!ok) return;
    void acceptAllIssues(selectedPara.id, selectedParaIdx, ids).then(setAcceptAllSummary);
  }

  function handleEvaluate() {
    if (!selectedPara) return;
    setAcceptAllSummary(null);
    void evaluateParagraph(selectedPara.id, selectedParaIdx);
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
    const ok = window.confirm(
      'Reset the document to its seed state?\n' +
      'All accepted edits, dismissals and live scores will be lost.',
    );
    if (!ok) return;
    setResetting(true);
    await resetDoc();
    setResetting(false);
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

  if (!doc) return null;

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <div className="va-root">
      {/* ─── Top Chrome ─────────────────────────────────────────────────── */}
      <div className="va-chrome">
        <div className="va-brand">Palimpsest</div>

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
                if (window.confirm(`Delete “${doc.title}”?`)) void deleteDoc(doc.id);
              }}
            >
              🗑
            </button>
          )}
          <button className="va-chip" data-testid="upload-open" onClick={openUploadModal}>
            + Upload pair
          </button>
          {doc.precompute?.status === 'running' && (
            <span className="va-precompute-badge">
              warming {doc.precompute.done}/{doc.precompute.planned} ¶…
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

          <button
            className={`va-chip terms-chip${showTerms ? ' on' : ''}`}
            disabled={allTerms.length === 0}
            title={allTerms.length === 0
              ? 'Terminology signals are precomputed offline and available for the seeded pilot document'
              : undefined}
            onClick={() => setShowTerms(!showTerms)}
          >
            Terms
          </button>
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
                  Precompute failed — scores unavailable; use Evaluate ↻ on a paragraph
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
                        <ScoreChip
                          label={`§${para.idx + 1}`}
                          score={agg}
                          loading={es.loading}
                          delta={chipDelta}
                          cached={es.cached}
                          stale={es.stale}
                        />
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
              acceptAllSummary={acceptAllSummary}
              onAccept={handleAcceptIssue}
              onDismiss={handleDismissIssue}
              onAcceptAll={handleAcceptAll}
              onEvaluate={handleEvaluate}
              onRetryFailed={handleRetryFailed}
              visibleIssues={inspectorIssues}
            />
          </>
        )}

        {activeTab === 'glossary' && (
          <GlossaryTab
            terms={allTerms}
            paragraphs={paragraphs}
            sourceLang={doc.sourceLang}
            targetLang={doc.targetLang}
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
