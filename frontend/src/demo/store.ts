/**
 * store.ts — Zustand store for the Glossa-MT demo.
 *
 * Replaces mock data.ts as the data source for VariantA and sub-components.
 * On mount, fetches the document list (no auto-open — see DocumentPicker).
 * All mutations call the backend and update state in place.
 */

import { create } from 'zustand';
import type {
  Document,
  DocumentSummary,
  Paragraph,
  Criterion,
  ModelRegistryEntryPublic,
  Issue,
  EvaluateResponse,
  TestModelResult,
  CreateDocumentBody,
  GroundingConfig,
  TranslatorConfig,
  RefinerConfig,
} from './api-client';
import {
  getDocuments,
  getDocument,
  getCriteria,
  getModels,
  evaluate as apiEvaluate,
  applyEdit as apiApplyEdit,
  resetDocument as apiResetDocument,
  patchParagraph as apiPatchParagraph,
  createCriterion,
  updateCriterion,
  deleteCriterion,
  createModel,
  updateModel,
  deleteModel,
  testModel as apiTestModel,
  createDocument as apiCreateDocument,
  deleteDocument as apiDeleteDocument,
  patchIssueStatus,
  refineParagraph as apiRefineParagraph,
  getGroundingConfig,
  updateGroundingConfig,
  getTranslatorConfig,
  updateTranslatorConfig,
  getRefinerConfig,
  updateRefinerConfig,
  getHealth,
  translateDocument as apiTranslateDocument,
  restoreRevision as apiRestoreRevision,
} from './api-client';
import type { CriterionId, ModelRegistryEntry } from './api-client';
import { applyLimits } from './limits';

// ─── UI state ─────────────────────────────────────────────────────────────────

export interface ParaEvalState {
  loading: boolean;
  cached: boolean;
  cachedAt: string | null;
  failedCriterionIds: CriterionId[];
  /** last /evaluate failure (network/5xx/budget cut-off); null = no error */
  error: string | null;
  /** true when the paragraph text changed since these scores were computed */
  stale: boolean;
  /** Refine-in-flight phase (InspectorPanel's "Refine paragraph ✦" button);
   *  undefined outside a refine flow. Optional so existing literals across the
   *  test suite that predate this field don't all need updating. */
  refineStage?: 'refining' | 'rescoring';
}

export interface DemoStore {
  // ── data ────────────────────────────────────────────────────────────────────
  document: Document | null;
  documents: DocumentSummary[];
  criteria: Criterion[];
  models: ModelRegistryEntryPublic[];
  groundingConfig: GroundingConfig | null;
  translatorConfig: TranslatorConfig | null;
  refinerConfig: RefinerConfig | null;

  // ── loading states ──────────────────────────────────────────────────────────
  documentLoading: boolean;
  documentError: string | null;
  /** per-paragraph evaluate in-flight state */
  paraEvalState: Record<number, ParaEvalState>;

  // ── UI state ────────────────────────────────────────────────────────────────
  selectedParaIdx: number;
  inspectorTab: 'issues' | 'scores';
  inspectorCollapsed: boolean;
  /** criteria chips that are "on" (by criterionId) */
  activeCriteria: Set<CriterionId>;
  showTerms: boolean;
  hoveredTermId: string | null;
  uploadModalOpen: boolean;
  /** Read once by UploadModal on mount to pre-select AI-translate mode
   *  (picker's "Blank document" card, S? landing picker). */
  uploadModalAiTranslateDefault: boolean;

  // ─── actions ────────────────────────────────────────────────────────────────

  /** Load documents + criteria + models on mount. Does NOT auto-open a
   *  document — the landing picker (docId=null) is the initial view; the user
   *  explicitly picks a document or starts a blank one. */
  init: () => Promise<void>;

  /** UI selection / navigation */
  setSelectedParaIdx: (idx: number) => void;
  setInspectorTab: (tab: 'issues' | 'scores') => void;
  setInspectorCollapsed: (v: boolean) => void;
  toggleCriterion: (id: CriterionId) => void;
  setShowTerms: (v: boolean) => void;
  setHoveredTermId: (id: string | null) => void;
  openUploadModal: (opts?: { aiTranslateDefault?: boolean }) => void;
  closeUploadModal: () => void;

  /** Clear the loaded document and return to the landing picker (brand click). */
  backToPicker: () => void;

  /** Refresh the document summary list (after create/delete) */
  refreshDocuments: () => Promise<void>;

  /** Switch the active document (top-bar dropdown) */
  switchDocument: (id: number) => Promise<void>;

  /** Create a user-uploaded document, refresh the list, switch to it */
  createDoc: (body: CreateDocumentBody) => Promise<void>;

  /** Delete a user-uploaded document, refresh the list, switch to the first remaining */
  deleteDoc: (id: number) => Promise<void>;

  /** Re-fetch the current document in place (precompute badge polling) */
  refreshDocument: () => Promise<void>;

  /** Accept an issue: apply-edit, then mark the paragraph stale (no re-judge) */
  acceptIssue: (paraId: number, paraIdx: number, issueId: string) => Promise<void>;

  /** Apply one issue's suggestion (apply-edit) WITHOUT the re-judge.
   * 'outdated' = any server 422 (fragment_not_found: overlapped by an earlier edit;
   * advice_suggestion: a legacy pre-guard row whose suggestion reads as advice;
   * no_suggestion: defense-in-depth, client already pre-checks this). */
  applyIssueEdit: (
    paraId: number,
    paraIdx: number,
    issueId: string,
  ) => Promise<'applied' | 'outdated' | 'failed'>;

  /** Dismiss an issue: optimistic UI + PATCH /api/issues/{id}; rollback on failure */
  dismissIssue: (issueId: string) => Promise<void>;

  /** Accept all visible open issues in a paragraph; returns per-outcome counts */
  acceptAllIssues: (
    paraId: number,
    paraIdx: number,
    issueIds: string[],
  ) => Promise<{ applied: number; outdated: number }>;

  /** Re-evaluate a paragraph (without apply-edit first) */
  evaluateParagraph: (paraId: number, paraIdx: number, criterionIds?: CriterionId[]) => Promise<void>;

  /** Refiner pass (paper's "refiner"): aggregate all open findings into one
   *  LLM rewrite, apply the returned paragraph, then re-score it. Replaces
   *  the old per-paragraph "Accept all" batch-splice flow (InspectorPanel). */
  refineParagraph: (paraId: number, paraIdx: number) => Promise<void>;

  /** Persist a target edit (on blur / text change) */
  saveParagraphTarget: (paraId: number, target: string) => Promise<void>;

  /** Reset document to seed state */
  resetDoc: () => Promise<void>;

  // ─── criteria CRUD ──────────────────────────────────────────────────────────
  addCriterion: (c: Criterion) => Promise<void>;
  saveCriterion: (c: Criterion) => Promise<void>;
  removeCriterion: (id: CriterionId) => Promise<void>;

  // ─── models CRUD ────────────────────────────────────────────────────────────
  addModel: (entry: ModelRegistryEntry) => Promise<void>;
  saveModel: (name: string, entry: Partial<ModelRegistryEntry>) => Promise<void>;
  removeModel: (name: string) => Promise<void>;
  testModel: (name: string) => Promise<TestModelResult>;

  // ─── grounding config ───────────────────────────────────────────────────────
  saveGroundingConfig: (cfg: GroundingConfig) => Promise<void>;

  // ─── translator config (S4 §3.4) ─────────────────────────────────────────────
  saveTranslatorConfig: (cfg: TranslatorConfig) => Promise<void>;

  // ─── refiner config (EMNLP sprint — mirrors translator/grounding config) ────
  saveRefinerConfig: (cfg: RefinerConfig) => Promise<void>;

  /** Re-POST /translate for the current document (S4 §3.3 Retry after a failed run). */
  retryTranslate: () => Promise<void>;

  /** Evaluate the first N (min(paragraphs, 12)) paragraphs of the current
   * document sequentially — the "Evaluate first paragraphs?" [Run] CTA after
   * a translation completes (S4 §3.3). There is no standalone server-side
   * precompute-trigger endpoint (precompute only runs at document creation),
   * so this reuses the existing per-paragraph /evaluate path instead of
   * inventing a new backend route (see webapp-ui-design.md doc-parity note). */
  runFirstParagraphsEvaluate: () => Promise<void>;

  /** Restore a paragraph to a past revision's text (S5 §3.3), then replace it
   * in the loaded document with the server's fresh paragraph DTO. */
  restoreParagraphRevision: (paraId: number, paraIdx: number, revisionId: number) => Promise<void>;

  /** Start polling GET /documents/{id} every 2.5s while terminology is being
   *  extracted (or while translation is still filling targets, since terms
   *  extraction follows it). Idempotent — at most one interval ever runs.
   *  Stop is called by the owning effect on done/failed/unmount/doc-switch. */
  startTermsPolling: () => void;
  stopTermsPolling: () => void;
}

// ─── helpers ──────────────────────────────────────────────────────────────────

function defaultParaEval(): ParaEvalState {
  return {
    loading: false,
    cached: false,
    cachedAt: null,
    failedCriterionIds: [],
    error: null,
    stale: false,
  };
}

/** Patch a paragraph in the document paragraphs array by index */
function patchParaInDoc(
  doc: Document,
  paraIdx: number,
  updater: (p: Paragraph) => Paragraph,
): Document {
  const paragraphs = doc.paragraphs.map((p, i) => (i === paraIdx ? updater(p) : p));
  return { ...doc, paragraphs };
}

/** Merge evaluate response scores/issues back into a paragraph */
function applyEvalToParag(para: Paragraph, ev: EvaluateResponse): Paragraph {
  // ev.issues already carries accepted/dismissed history from the server, so
  // concatenating local nonOpen would duplicate them (→ React key collision).
  // Keep local nonOpen first (preserves local-only dismissals) and dedupe by id.
  const nonOpen = para.issues.filter((i) => i.status !== 'open');
  const seen = new Set<string>();
  const issues = [...nonOpen, ...ev.issues].filter((i) =>
    seen.has(i.id) ? false : seen.add(i.id),
  );
  return {
    ...para,
    scores: ev.scores,
    scoresPrev: ev.scoresPrev,
    scoresBaseline: ev.scoresBaseline,
    aggregate: ev.aggregate,
    aggregatePrev: ev.aggregatePrev,
    aggregateBaseline: ev.aggregateBaseline,
    issues,
  };
}

/** Compute doc-level aggregate as mean of paragraph aggregates */
function computeDocAggregate(paragraphs: Paragraph[]): number | null {
  const vals = paragraphs.map((p) => p.aggregate).filter((v): v is number => v !== null);
  if (vals.length === 0) return null;
  return Math.round((vals.reduce((a, b) => a + b, 0) / vals.length) * 10) / 10;
}

// ─── store ────────────────────────────────────────────────────────────────────

export const useDemoStore = create<DemoStore>((set, get) => {
  // Single-flight interval handle for the terms-status poll — module-closure
  // scoped (one store instance app-wide), guarded by start/stop below so a
  // re-render or a second effect firing never stacks a duplicate interval.
  let termsPollTimer: ReturnType<typeof setInterval> | null = null;

  const markStale = (paraIdx: number) =>
    set((s) => ({
      paraEvalState: {
        ...s.paraEvalState,
        [paraIdx]: { ...(s.paraEvalState[paraIdx] ?? defaultParaEval()), stale: true },
      },
    }));

  const setIssueStatus = (paraIdx: number, issueId: string, status: Issue['status']) =>
    set((s) => {
      const doc = s.document;
      if (!doc) return {};
      const updatedDoc = patchParaInDoc(doc, paraIdx, (p) => ({
        ...p,
        issues: p.issues.map((iss) => (iss.id === issueId ? { ...iss, status } : iss)),
      }));
      return { document: updatedDoc };
    });

  return {
  document: null,
  documents: [],
  criteria: [],
  models: [],
  groundingConfig: null,
  translatorConfig: null,
  refinerConfig: null,
  documentLoading: false,
  documentError: null,
  paraEvalState: {},
  selectedParaIdx: 0,
  inspectorTab: 'issues',
  inspectorCollapsed: false,
  activeCriteria: new Set<CriterionId>(),
  showTerms: true,
  hoveredTermId: null,
  uploadModalOpen: false,
  uploadModalAiTranslateDefault: false,

  // ── init ──────────────────────────────────────────────────────────────────

  init: async () => {
    set({ documentLoading: true, documentError: null });
    // Server-side limits sync (S3 §2.3) — best-effort, independent of the
    // main document load below; a failure here just keeps the client fallback
    // constants from limits.ts and must not block the rest of init.
    getHealth().then((h) => applyLimits(h.limits)).catch(() => {});

    // Auxiliary Settings-tab configs — best-effort, independent of the
    // boot-critical load below. Kicked off (not awaited) here so the
    // isolating .catch() is attached immediately, before either promise has a
    // chance to reject unobserved. A single misconfigured/missing endpoint
    // (e.g. a table absent on a not-yet-migrated prod DB — 2026-07-06 incident,
    // see docs/reports/e2e/prod-wave5-run.md) must never blank the whole app;
    // on failure the store keeps its null default and the Settings tab shows
    // that config as unavailable instead of crashing.
    const groundingConfigPromise = getGroundingConfig().catch((e) => {
      console.warn('init: getGroundingConfig failed, falling back to null', e);
      return null;
    });
    const translatorConfigPromise = getTranslatorConfig().catch((e) => {
      console.warn('init: getTranslatorConfig failed, falling back to null', e);
      return null;
    });
    // Refiner config — same best-effort, degrade-to-null pattern (EMNLP sprint).
    const refinerConfigPromise = getRefinerConfig().catch((e) => {
      console.warn('init: getRefinerConfig failed, falling back to null', e);
      return null;
    });

    try {
      // Boot-critical: without these there is nothing to show at all (not even
      // the picker). No per-document GET here — the landing picker (docId=null)
      // is the initial view; zero documents is a valid picker state (just the
      // blank-document card), not an error.
      const [summaries, criteria, models] = await Promise.all([
        getDocuments(),
        getCriteria(),
        getModels(),
      ]);
      const [groundingConfig, translatorConfig, refinerConfig] = await Promise.all([
        groundingConfigPromise,
        translatorConfigPromise,
        refinerConfigPromise,
      ]);

      // Initialise active criteria to all enabled
      const activeCriteria = new Set(criteria.filter((c) => c.enabled).map((c) => c.id));

      set({
        document: null,
        documents: summaries,
        criteria,
        models,
        groundingConfig,
        translatorConfig,
        refinerConfig,
        activeCriteria,
        documentLoading: false,
      });
    } catch (e) {
      set({ documentLoading: false, documentError: String(e) });
    }
  },

  // ── UI ────────────────────────────────────────────────────────────────────

  setSelectedParaIdx: (idx) => set({ selectedParaIdx: idx }),
  setInspectorTab: (tab) => set({ inspectorTab: tab }),
  setInspectorCollapsed: (v) => set({ inspectorCollapsed: v }),
  setShowTerms: (v) => set({ showTerms: v }),
  setHoveredTermId: (id) => set({ hoveredTermId: id }),
  openUploadModal: (opts) =>
    set({ uploadModalOpen: true, uploadModalAiTranslateDefault: !!opts?.aiTranslateDefault }),
  closeUploadModal: () => set({ uploadModalOpen: false }),

  backToPicker: () => {
    set({ document: null });
    void get().refreshDocuments();   // picker cards reflect fresh termsStatus on return
  },

  toggleCriterion: (id) =>
    set((s) => {
      const next = new Set(s.activeCriteria);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return { activeCriteria: next };
    }),

  // ── multi-document ────────────────────────────────────────────────────────

  refreshDocuments: async () => {
    const documents = await getDocuments();
    set({ documents });
  },

  switchDocument: async (id) => {
    set({ documentLoading: true, documentError: null });
    try {
      const doc = await getDocument(id);
      set({
        document: doc,
        selectedParaIdx: 0,
        documentLoading: false,
        paraEvalState: Object.fromEntries(doc.paragraphs.map((_, i) => [i, defaultParaEval()])),
      });
    } catch (e) {
      set({ documentLoading: false, documentError: String(e) });
    }
  },

  createDoc: async (body) => {
    const doc = await apiCreateDocument(body);          // errors propagate to the modal
    await get().refreshDocuments();
    set({ uploadModalOpen: false });
    await get().switchDocument(doc.id);
  },

  deleteDoc: async (id) => {
    try {
      await apiDeleteDocument(id);
    } catch (e) {
      window.alert(String(e));
      await get().refreshDocuments();          // resync UI with server truth
      return;
    }
    await get().refreshDocuments();
    const first = get().documents[0];
    if (first) await get().switchDocument(first.id);
  },

  refreshDocument: async () => {
    const cur = get().document;
    if (!cur) return;
    try {
      const doc = await getDocument(cur.id);
      // Stale-fetch guard: this action is polled every 2.5-3s (precompute /
      // translation / terms-status pollers below all funnel through it). If
      // the user switched documents (or backed out to the picker) while this
      // request was in flight, a slow response for the no-longer-active
      // document must never clobber whatever is loaded now.
      if (get().document?.id !== cur.id) return;
      set({ document: doc });                           // paraEvalState is preserved
    } catch (e) {
      // The document was deleted server-side while a poller was still
      // hitting it — every poller above would otherwise 404 forever. Stop
      // the store-owned terms-status interval directly (idempotent); the two
      // setInterval-based pollers in VariantA.tsx clear themselves on their
      // own next render once `document` goes null (their effect deps
      // include `doc?.id`). Guarded by the same stale-fetch check so a
      // late-arriving 404 for a document the user already left never blanks
      // whatever they've since switched to.
      if (String(e).includes('→ 404') && get().document?.id === cur.id) {
        get().stopTermsPolling();
        set({ document: null });                        // → falls back to the picker
        void get().refreshDocuments();                   // drop the deleted doc from the list
        return;
      }
      // Any other error (network blip / 5xx): leave state untouched —
      // pollers retry on their next tick; refreshDocument has never
      // surfaced errors to the UI.
    }
  },

  // ── evaluate helpers ──────────────────────────────────────────────────────

  evaluateParagraph: async (paraId, paraIdx, criterionIds) => {
    // Spreads the previous per-paragraph state (not a fresh literal) so a
    // refineStage set by refineParagraph's chained call survives this pass —
    // otherwise "Re-scoring…" would flash back to the idle label instantly.
    set((s) => ({
      paraEvalState: {
        ...s.paraEvalState,
        [paraIdx]: {
          ...(s.paraEvalState[paraIdx] ?? defaultParaEval()),
          loading: true,
          cached: false,
          cachedAt: null,
          failedCriterionIds: [],
          error: null,
          stale: false,
        },
      },
    }));
    try {
      const ev = await apiEvaluate(paraId, criterionIds);
      set((s) => {
        const doc = s.document;
        if (!doc) return {};
        const updatedDoc = patchParaInDoc(doc, paraIdx, (p) => applyEvalToParag(p, ev));
        const docAggregate = computeDocAggregate(updatedDoc.paragraphs);
        return {
          document: { ...updatedDoc, aggregate: docAggregate },
          paraEvalState: {
            ...s.paraEvalState,
            [paraIdx]: {
              ...(s.paraEvalState[paraIdx] ?? defaultParaEval()),
              loading: false,
              cached: ev.cached,
              cachedAt: ev.cachedAt,
              failedCriterionIds: ev.failedCriterionIds,
              error: null,
              stale: false,
            },
          },
        };
      });
    } catch (e) {
      set((s) => ({
        paraEvalState: {
          ...s.paraEvalState,
          [paraIdx]: {
            ...(s.paraEvalState[paraIdx] ?? defaultParaEval()),
            loading: false,
            error: String(e),
          },
        },
      }));
    }
  },

  // ── refine (paper's "refiner") ────────────────────────────────────────────

  refineParagraph: async (paraId, paraIdx) => {
    const setStage = (stage: 'refining' | 'rescoring' | undefined) =>
      set((s) => ({
        paraEvalState: {
          ...s.paraEvalState,
          [paraIdx]: { ...(s.paraEvalState[paraIdx] ?? defaultParaEval()), refineStage: stage },
        },
      }));

    setStage('refining');
    try {
      // Server returns the full updated paragraph dict (fresh target + issues
      // flipped to 'accepted', new revision origin='refine') — same merge
      // pattern as restoreParagraphRevision/saveParagraphTarget below.
      const updated = await apiRefineParagraph(paraId);
      set((s) => {
        const doc = s.document;
        if (!doc) return {};
        const paragraphs = doc.paragraphs.map((p) => (p.id === paraId ? { ...p, ...updated } : p));
        return { document: { ...doc, paragraphs } };
      });
      setStage('rescoring');
      await get().evaluateParagraph(paraId, paraIdx);   // scores/aggregate on `updated` are pre-refine
    } catch (e) {
      // 409 = no open issues. The button is already client-gated on this
      // (activeIssueCount === 0), so this only fires on a genuine race —
      // nothing to refine, no error banner needed.
      if (!String(e).includes('→ 409')) {
        set((s) => ({
          paraEvalState: {
            ...s.paraEvalState,
            [paraIdx]: { ...(s.paraEvalState[paraIdx] ?? defaultParaEval()), error: String(e) },
          },
        }));
      }
    } finally {
      setStage(undefined);
    }
  },

  // ── accept / dismiss ──────────────────────────────────────────────────────

  applyIssueEdit: async (paraId, paraIdx, issueId) => {
    // Only the empty-suggestion pre-check stays client-side; fragment matching
    // is the server's call now (whitespace-tolerant, see webapp.md).
    const para0 = get().document?.paragraphs.find((p) => p.id === paraId);
    const iss0 = para0?.issues.find((i) => i.id === issueId);
    if (!iss0 || !iss0.suggestion) return 'failed';

    // Optimistically mark status=accepted in UI
    setIssueStatus(paraIdx, issueId, 'accepted');

    try {
      const result = await apiApplyEdit(paraId, issueId);
      set((s) => {
        const doc = s.document;
        if (!doc) return {};
        const siblingById = new Map((result.siblingIssues ?? []).map((i) => [i.id, i]));
        const updatedDoc = patchParaInDoc(doc, paraIdx, (p) => ({
          ...p,
          target: result.target,
          issues: p.issues.map((iss) => {
            if (iss.id === issueId) return result.issue;
            // Only apply the sibling's server-pushed status if the local copy is
            // still 'open' — mirrors the server's own `WHERE status='open'` guard
            // (app.py apply_edit) so a concurrent local dismiss/accept on this
            // sibling is never silently reverted to 'outdated'.
            const sib = siblingById.get(iss.id);
            return sib && iss.status === 'open' ? sib : iss;
          }),
        }));
        return { document: updatedDoc };
      });
      return 'applied';
    } catch (e) {
      if (String(e).includes('not_open')) {
        // Issue was already accepted/dismissed/outdated server-side (stale local
        // state, e.g. a concurrent action) — leave local status exactly as it
        // was; the optimistic 'accepted' flip above must be undone, not turned
        // into 'outdated' (that would misreport why the accept didn't apply).
        setIssueStatus(paraIdx, issueId, iss0.status);
        return 'failed';
      }
      if (String(e).includes('→ 422')) {
        // Any guard 422 (fragment_not_found / advice_suggestion / no_suggestion) is
        // handled the same graceful way: mark outdated (optimistic) and persist;
        // Evaluate ↻ regenerates issues. See webapp.md "Advice-text guard".
        setIssueStatus(paraIdx, issueId, 'outdated');
        try {
          await patchIssueStatus(issueId, 'outdated');
        } catch {
          // keep the optimistic status; a re-judge will rebuild issue state anyway
        }
        return 'outdated';
      }
      // Network/5xx: revert to open so the user can retry
      setIssueStatus(paraIdx, issueId, 'open');
      return 'failed';
    }
  },

  dismissIssue: async (issueId) => {
    const setStatus = (status: 'open' | 'dismissed') =>
      set((s) => {
        const doc = s.document;
        if (!doc) return {};
        const paragraphs = doc.paragraphs.map((p) => ({
          ...p,
          issues: p.issues.map((iss) => (iss.id === issueId ? { ...iss, status } : iss)),
        }));
        return { document: { ...doc, paragraphs } };
      });
    setStatus('dismissed');                       // optimistic
    try {
      await patchIssueStatus(issueId, 'dismissed');
    } catch (e) {
      setStatus('open');                          // server did not confirm → rollback
      const paraIdx = get().document?.paragraphs.findIndex((p) =>
        p.issues.some((iss) => iss.id === issueId)) ?? -1;
      if (paraIdx >= 0) {
        set((s) => ({
          paraEvalState: {
            ...s.paraEvalState,
            [paraIdx]: {
              ...(s.paraEvalState[paraIdx] ?? defaultParaEval()),
              error: `Dismiss failed: ${String(e)}`,
            },
          },
        }));
      }
    }
  },

  acceptIssue: async (paraId, paraIdx, issueId) => {
    const outcome = await get().applyIssueEdit(paraId, paraIdx, issueId);
    if (outcome === 'applied') markStale(paraIdx);   // no auto re-judge — owner: LLM calls only on explicit Evaluate
  },

  acceptAllIssues: async (paraId, paraIdx, issueIds) => {
    let applied = 0;
    let outdated = 0;
    for (const id of issueIds) {
      // Re-read status right before each call: an earlier accept in this same
      // batch may have flipped this queued issue to 'outdated' via a sibling
      // merge (overlapping fragment). Skip the now-pointless HTTP round trip
      // — it would only 422 not_open — and count it as outdated directly.
      const para = get().document?.paragraphs.find((p) => p.id === paraId);
      const current = para?.issues.find((i) => i.id === id);
      if (current && current.status !== 'open') {
        if (current.status === 'outdated') outdated += 1;
        continue;
      }
      const outcome = await get().applyIssueEdit(paraId, paraIdx, id);
      if (outcome === 'applied') applied += 1;
      else if (outcome === 'outdated') outdated += 1;
    }
    if (applied > 0) markStale(paraIdx);
    return { applied, outdated };
  },

  // ── save paragraph text ───────────────────────────────────────────────────

  saveParagraphTarget: async (paraId, target) => {
    try {
      const updated = await apiPatchParagraph(paraId, target);
      set((s) => {
        const doc = s.document;
        if (!doc) return {};
        const paragraphs = doc.paragraphs.map((p) =>
          p.id === paraId ? { ...p, ...updated } : p,
        );
        return { document: { ...doc, paragraphs } };
      });
      const paraIdx = get().document?.paragraphs.findIndex((p) => p.id === paraId) ?? -1;
      if (paraIdx >= 0) markStale(paraIdx);   // manual edits outdate scores exactly like accepts
    } catch {
      // Silently ignore; user's edit stays locally
    }
  },

  // ── reset ────────────────────────────────────────────────────────────────

  resetDoc: async () => {
    const doc = s().document;
    if (!doc) return;
    set({ documentLoading: true });
    try {
      const fresh = await apiResetDocument(doc.id);
      const activeCriteria = new Set(
        get().criteria.filter((c) => c.enabled).map((c) => c.id),
      );
      set({
        document: fresh,
        documentLoading: false,
        paraEvalState: Object.fromEntries(
          fresh.paragraphs.map((_, i) => [i, defaultParaEval()]),
        ),
        activeCriteria,
      });
    } catch {
      set({ documentLoading: false });
    }
  },

  // ── criteria CRUD ─────────────────────────────────────────────────────────

  addCriterion: async (c) => {
    const created = await createCriterion(c);
    set((s) => ({ criteria: [...s.criteria, created] }));
  },

  saveCriterion: async (c) => {
    const updated = await updateCriterion(c.id, c);
    set((s) => ({ criteria: s.criteria.map((x) => (x.id === c.id ? updated : x)) }));
  },

  removeCriterion: async (id) => {
    await deleteCriterion(id);
    set((s) => ({ criteria: s.criteria.filter((x) => x.id !== id) }));
  },

  // ── models CRUD ───────────────────────────────────────────────────────────

  addModel: async (entry) => {
    const created = await createModel(entry);
    set((s) => ({ models: [...s.models, created] }));
  },

  saveModel: async (name, entry) => {
    const updated = await updateModel(name, entry);
    set((s) => ({ models: s.models.map((m) => (m.name === name ? updated : m)) }));
  },

  removeModel: async (name) => {
    await deleteModel(name);
    set((s) => ({ models: s.models.filter((m) => m.name !== name) }));
  },

  testModel: async (name) => apiTestModel(name),

  // ── grounding config ──────────────────────────────────────────────────────

  saveGroundingConfig: async (cfg) => {
    const updated = await updateGroundingConfig(cfg);
    set({ groundingConfig: updated });
  },

  // ── translator config ─────────────────────────────────────────────────────

  saveTranslatorConfig: async (cfg) => {
    const updated = await updateTranslatorConfig(cfg);
    set({ translatorConfig: updated });
  },

  // ── refiner config ────────────────────────────────────────────────────────

  saveRefinerConfig: async (cfg) => {
    const updated = await updateRefinerConfig(cfg);
    set({ refinerConfig: updated });
  },

  retryTranslate: async () => {
    const doc = get().document;
    if (!doc) return;
    await apiTranslateDocument(doc.id);
    await get().refreshDocument();
  },

  runFirstParagraphsEvaluate: async () => {
    const doc = get().document;
    if (!doc) return;
    const PRECOMPUTE_MAX_PARAS = 12;
    const targets = doc.paragraphs.slice(0, PRECOMPUTE_MAX_PARAS);
    for (const [idx, para] of targets.entries()) {
      await get().evaluateParagraph(para.id, idx);
    }
  },

  // ── revision history (S5 §3.3) ────────────────────────────────────────────

  restoreParagraphRevision: async (paraId, paraIdx, revisionId) => {
    const updated = await apiRestoreRevision(paraId, revisionId);
    set((s) => {
      const doc = s.document;
      if (!doc) return {};
      const paragraphs = doc.paragraphs.map((p) => (p.id === paraId ? { ...p, ...updated } : p));
      return { document: { ...doc, paragraphs } };
    });
    markStale(paraIdx);   // restored text has no fresh score yet — Evaluate ↻ will re-judge it honestly
  },

  // ── terms-status polling (S? live terminology UX) ────────────────────────

  startTermsPolling: () => {
    if (termsPollTimer !== null) return;   // single-interval invariant
    termsPollTimer = setInterval(() => void get().refreshDocument(), 2500);
  },

  stopTermsPolling: () => {
    if (termsPollTimer === null) return;
    clearInterval(termsPollTimer);
    termsPollTimer = null;
  },
  };
});

// Convenience selector helpers

/** All paragraphs from the loaded document (stable reference) */
export function selectParagraphs(s: DemoStore): Paragraph[] {
  return s.document?.paragraphs ?? [];
}

/** All issues across all paragraphs */
export function selectAllIssues(s: DemoStore): Issue[] {
  return s.document?.paragraphs.flatMap((p) => p.issues) ?? [];
}

export function scoreBand(v: number): 'green' | 'yellow' | 'red' {
  if (v >= 8) return 'green';
  if (v >= 6) return 'yellow';
  return 'red';
}

// Private reference for use inside store actions
function s(): DemoStore {
  return useDemoStore.getState();
}
