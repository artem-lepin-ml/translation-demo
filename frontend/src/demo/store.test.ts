import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Document, EvaluateResponse, Issue, Paragraph } from './api-client';

vi.mock('./api-client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./api-client')>();
  return {
    ...actual,
    patchIssueStatus: vi.fn(),
    applyEdit: vi.fn(),
    evaluate: vi.fn(),
    createCriterion: vi.fn(),
    deleteCriterion: vi.fn(),
    patchParagraph: vi.fn(),
    translateDocument: vi.fn(),
    restoreRevision: vi.fn(),
    updateTranslatorConfig: vi.fn(),
    getDocument: vi.fn(),
    getDocuments: vi.fn(),
    getCriteria: vi.fn(),
    getModels: vi.fn(),
    getGroundingConfig: vi.fn(),
    getTranslatorConfig: vi.fn(),
    getHealth: vi.fn(),
  };
});

import {
  applyEdit,
  createCriterion,
  deleteCriterion,
  evaluate,
  patchIssueStatus,
  patchParagraph,
  translateDocument,
  restoreRevision,
  updateTranslatorConfig,
  getDocument,
  getDocuments,
  getCriteria,
  getModels,
  getGroundingConfig,
  getTranslatorConfig,
  getHealth,
} from './api-client';
import type {
  Criterion, DocumentSummary, GroundingConfig, ModelRegistryEntryPublic, TranslatorConfig,
} from './api-client';
import { useDemoStore } from './store';

function issue(id: string, over: Partial<Issue> = {}): Issue {
  return {
    id, paragraphId: 1, criterionId: 'accuracy', targetFragment: '', sourceFragment: '',
    explanation: 'x', suggestion: '', severity: 'minor', mqmCategory: null, status: 'open',
    ...over,
  };
}

function makeDoc(issues: Issue[]): Document {
  const para: Paragraph = {
    id: 1, idx: 0, source: 'ru', target: 'aaa bbb', scores: [], scoresPrev: null,
    scoresBaseline: null, aggregate: null, aggregateBaseline: null, best: null, issues, terms: [],
  };
  return {
    id: 1, title: 't', sourceLang: 'ru', targetLang: 'en', nParagraphs: 1,
    sourceModel: 'm', aggregate: null, origin: 'seed', paragraphs: [para],
  };
}

const evalResponse: EvaluateResponse = {
  scores: [], scoresPrev: null, scoresBaseline: null, aggregate: 7, aggregateBaseline: null, aggregatePrev: null,
  issues: [], failedCriterionIds: [], cached: false, cachedAt: null, docVersion: 1,
};

beforeEach(() => {
  vi.clearAllMocks();
  useDemoStore.setState({
    document: makeDoc([
      issue('1', { targetFragment: 'aaa', suggestion: 'xxx' }),
      issue('2', { targetFragment: 'bbb', suggestion: 'yyy' }),
    ]),
    paraEvalState: {
      0: {
        loading: false, cached: false, cachedAt: null, failedCriterionIds: [], error: null,
        stale: false,
      },
    },
  });
});

describe('dismissIssue (H2)', () => {
  it('persists via PATCH and keeps status=dismissed', async () => {
    vi.mocked(patchIssueStatus).mockResolvedValue(issue('1', { status: 'dismissed' }));
    await useDemoStore.getState().dismissIssue('1');
    expect(patchIssueStatus).toHaveBeenCalledWith('1', 'dismissed');
    expect(useDemoStore.getState().document!.paragraphs[0].issues[0].status).toBe('dismissed');
  });

  it('rolls back to open when the PATCH fails', async () => {
    vi.mocked(patchIssueStatus).mockRejectedValue(new Error('HTTP 500'));
    await useDemoStore.getState().dismissIssue('1');
    expect(useDemoStore.getState().document!.paragraphs[0].issues[0].status).toBe('open');
  });
});

describe('evaluateParagraph (H3)', () => {
  it('exposes the failure via paraEvalState.error', async () => {
    vi.mocked(evaluate).mockRejectedValue(new Error('boom'));
    await useDemoStore.getState().evaluateParagraph(1, 0);
    const st = useDemoStore.getState().paraEvalState[0];
    expect(st.loading).toBe(false);
    expect(st.error).toContain('boom');
  });

  it('passes only the given criterionIds to the API (retry-failed path)', async () => {
    vi.mocked(evaluate).mockResolvedValue(evalResponse);
    await useDemoStore.getState().evaluateParagraph(1, 0, ['style', 'cultural']);
    expect(evaluate).toHaveBeenCalledWith(1, ['style', 'cultural']);
  });

  it('omits criterionIds for a full re-evaluate', async () => {
    vi.mocked(evaluate).mockResolvedValue(evalResponse);
    await useDemoStore.getState().evaluateParagraph(1, 0);
    expect(evaluate).toHaveBeenCalledWith(1, undefined);
  });

  it('clears a prior failedCriterionIds banner when a retry succeeds', async () => {
    useDemoStore.setState({
      paraEvalState: {
        0: { loading: false, cached: false, cachedAt: null,
             failedCriterionIds: ['style', 'cultural'], error: 'timeout', stale: true },
      },
    });
    vi.mocked(evaluate).mockResolvedValue(evalResponse);   // failedCriterionIds: []
    await useDemoStore.getState().evaluateParagraph(1, 0, ['style', 'cultural']);
    const st = useDemoStore.getState().paraEvalState[0];
    expect(st.failedCriterionIds).toEqual([]);
    expect(st.error).toBeNull();
  });

  it('clears stale=true once the re-judge resolves', async () => {
    useDemoStore.setState({
      paraEvalState: {
        0: { loading: false, cached: false, cachedAt: null, failedCriterionIds: [], error: null, stale: true },
      },
    });
    vi.mocked(evaluate).mockResolvedValue(evalResponse);
    await useDemoStore.getState().evaluateParagraph(1, 0);
    expect(useDemoStore.getState().paraEvalState[0].stale).toBe(false);
  });
});

describe('acceptIssue (explicit re-eval)', () => {
  it('applies the edit but does not call evaluate, and marks the paragraph stale', async () => {
    vi.mocked(applyEdit).mockResolvedValueOnce({
      target: 'xxx bbb', issue: issue('1', { status: 'accepted' }), siblingIssues: [],
    });
    await useDemoStore.getState().acceptIssue(1, 0, '1');
    expect(applyEdit).toHaveBeenCalledTimes(1);
    expect(evaluate).not.toHaveBeenCalled();
    expect(useDemoStore.getState().paraEvalState[0].stale).toBe(true);
  });

  it('flips overlapping siblings to outdated from the apply response', async () => {
    vi.mocked(applyEdit).mockResolvedValueOnce({
      target: 'xxx bbb',
      issue: issue('1', { status: 'accepted' }),
      siblingIssues: [issue('2', { status: 'outdated' })],
    });
    await useDemoStore.getState().acceptIssue(1, 0, '1');
    const issues = useDemoStore.getState().document!.paragraphs[0].issues;
    expect(issues.find((i) => i.id === '1')!.status).toBe('accepted');
    expect(issues.find((i) => i.id === '2')!.status).toBe('outdated');
  });

  it('does not mark stale when the edit application fails (network error)', async () => {
    vi.mocked(applyEdit).mockRejectedValueOnce(new Error('POST /paragraphs/1/apply-edit → 500'));
    await useDemoStore.getState().acceptIssue(1, 0, '1');
    expect(evaluate).not.toHaveBeenCalled();
    expect(useDemoStore.getState().paraEvalState[0].stale).toBe(false);
    // network failure reverts the issue to open so the user can retry
    expect(useDemoStore.getState().document!.paragraphs[0].issues[0].status).toBe('open');
  });

  it('marks the issue outdated (and PATCHes it) on a server 422', async () => {
    vi.mocked(applyEdit).mockRejectedValueOnce(
      new Error('POST /paragraphs/1/apply-edit → 422: {"error":"fragment_not_found"}'),
    );
    vi.mocked(patchIssueStatus).mockResolvedValue(issue('1', { status: 'outdated' }));
    await useDemoStore.getState().acceptIssue(1, 0, '1');
    expect(useDemoStore.getState().document!.paragraphs[0].issues[0].status).toBe('outdated');
    expect(patchIssueStatus).toHaveBeenCalledWith('1', 'outdated');
    expect(useDemoStore.getState().paraEvalState[0].stale).toBe(false);   // nothing applied
  });

  it('handles a 422 advice_suggestion (legacy row) the same graceful way as fragment_not_found', async () => {
    vi.mocked(applyEdit).mockRejectedValueOnce(
      new Error('POST /paragraphs/1/apply-edit → 422: {"error":"advice_suggestion"}'),
    );
    vi.mocked(patchIssueStatus).mockResolvedValue(issue('1', { status: 'outdated' }));
    await useDemoStore.getState().acceptIssue(1, 0, '1');
    expect(useDemoStore.getState().document!.paragraphs[0].issues[0].status).toBe('outdated');
    expect(patchIssueStatus).toHaveBeenCalledWith('1', 'outdated');
    expect(useDemoStore.getState().paraEvalState[0].stale).toBe(false);   // nothing applied
  });

  it('reverts to the prior status (not outdated) on a server 422 not_open', async () => {
    useDemoStore.setState({
      document: makeDoc([
        issue('1', { targetFragment: 'aaa', suggestion: 'xxx', status: 'dismissed' }),
        issue('2', { targetFragment: 'bbb', suggestion: 'yyy' }),
      ]),
    });
    vi.mocked(applyEdit).mockRejectedValueOnce(
      new Error('POST /paragraphs/1/apply-edit → 422: {"error":"not_open"}'),
    );
    await useDemoStore.getState().acceptIssue(1, 0, '1');
    expect(useDemoStore.getState().document!.paragraphs[0].issues[0].status).toBe('dismissed');
    expect(patchIssueStatus).not.toHaveBeenCalled();
    expect(useDemoStore.getState().paraEvalState[0].stale).toBe(false);
  });

  it('does not revert a concurrently-dismissed sibling to outdated from siblingIssues', async () => {
    useDemoStore.setState({
      document: makeDoc([
        issue('1', { targetFragment: 'aaa', suggestion: 'xxx' }),
        issue('2', { targetFragment: 'bbb', suggestion: 'yyy', status: 'dismissed' }),
      ]),
    });
    vi.mocked(applyEdit).mockResolvedValueOnce({
      target: 'xxx bbb',
      issue: issue('1', { status: 'accepted' }),
      // Server computed this before learning about the local dismiss race.
      siblingIssues: [issue('2', { status: 'outdated' })],
    });
    await useDemoStore.getState().acceptIssue(1, 0, '1');
    const issues = useDemoStore.getState().document!.paragraphs[0].issues;
    expect(issues.find((i) => i.id === '2')!.status).toBe('dismissed');
  });

  it('applies the sibling status when the local sibling is still open', async () => {
    vi.mocked(applyEdit).mockResolvedValueOnce({
      target: 'xxx bbb',
      issue: issue('1', { status: 'accepted' }),
      siblingIssues: [issue('2', { status: 'outdated' })],
    });
    await useDemoStore.getState().acceptIssue(1, 0, '1');
    const issues = useDemoStore.getState().document!.paragraphs[0].issues;
    expect(issues.find((i) => i.id === '2')!.status).toBe('outdated');
  });
});

describe('acceptAllIssues (M3, explicit re-eval)', () => {
  it('applies every edit, never calls evaluate, marks stale, returns counts', async () => {
    vi.mocked(applyEdit)
      .mockResolvedValueOnce({ target: 'xxx bbb', issue: issue('1', { status: 'accepted' }), siblingIssues: [] })
      .mockResolvedValueOnce({ target: 'xxx yyy', issue: issue('2', { status: 'accepted' }), siblingIssues: [] });
    const res = await useDemoStore.getState().acceptAllIssues(1, 0, ['1', '2']);
    expect(applyEdit).toHaveBeenCalledTimes(2);
    expect(evaluate).not.toHaveBeenCalled();
    expect(useDemoStore.getState().paraEvalState[0].stale).toBe(true);
    expect(res).toEqual({ applied: 2, outdated: 0 });
  });

  it('counts a 422 fragment collision as outdated (no alert, no evaluate)', async () => {
    const alertSpy = vi.spyOn(window, 'alert').mockImplementation(() => {});
    vi.mocked(applyEdit)
      .mockResolvedValueOnce({ target: 'xxx bbb', issue: issue('1', { status: 'accepted' }), siblingIssues: [] })
      .mockRejectedValueOnce(
        new Error('POST /paragraphs/1/apply-edit → 422: {"error":"fragment_not_found"}'),
      );
    vi.mocked(patchIssueStatus).mockResolvedValue(issue('2', { status: 'outdated' }));
    const res = await useDemoStore.getState().acceptAllIssues(1, 0, ['1', '2']);
    expect(res).toEqual({ applied: 1, outdated: 1 });
    expect(useDemoStore.getState().document!.paragraphs[0].issues[1].status).toBe('outdated');
    expect(patchIssueStatus).toHaveBeenCalledWith('2', 'outdated');
    expect(evaluate).not.toHaveBeenCalled();
    expect(alertSpy).not.toHaveBeenCalled();
    expect(useDemoStore.getState().paraEvalState[0].stale).toBe(true);   // one edit landed
    alertSpy.mockRestore();
  });

  it('skips empty-suggestion issues client-side (neither applied nor outdated)', async () => {
    useDemoStore.setState({
      document: makeDoc([
        issue('1', { targetFragment: 'aaa', suggestion: 'xxx' }),
        issue('2', { targetFragment: 'bbb', suggestion: '' }),
      ]),
    });
    vi.mocked(applyEdit).mockResolvedValueOnce({
      target: 'xxx bbb', issue: issue('1', { status: 'accepted' }), siblingIssues: [],
    });
    const res = await useDemoStore.getState().acceptAllIssues(1, 0, ['1', '2']);
    expect(applyEdit).toHaveBeenCalledTimes(1);
    expect(res).toEqual({ applied: 1, outdated: 0 });
  });

  it('skips the HTTP call for queued issues already invalidated by an earlier sibling merge, counting them as outdated', async () => {
    useDemoStore.setState({
      document: makeDoc([
        issue('1', { targetFragment: 'aaa', suggestion: 'xxx' }),
        issue('2', { targetFragment: 'bbb', suggestion: 'yyy' }),
        issue('3', { targetFragment: 'ccc', suggestion: 'zzz' }),
      ]),
    });
    // Accepting '1' invalidates '2' and '3' as overlapping siblings.
    vi.mocked(applyEdit).mockResolvedValueOnce({
      target: 'xxx bbb ccc',
      issue: issue('1', { status: 'accepted' }),
      siblingIssues: [
        issue('2', { status: 'outdated' }),
        issue('3', { status: 'outdated' }),
      ],
    });
    const res = await useDemoStore.getState().acceptAllIssues(1, 0, ['1', '2', '3']);
    // Only the first queued issue triggers an apply-edit call — '2' and '3'
    // are already 'outdated' locally by the time their turn comes up.
    expect(applyEdit).toHaveBeenCalledTimes(1);
    expect(res).toEqual({ applied: 1, outdated: 2 });
    const issues = useDemoStore.getState().document!.paragraphs[0].issues;
    expect(issues.find((i) => i.id === '2')!.status).toBe('outdated');
    expect(issues.find((i) => i.id === '3')!.status).toBe('outdated');
    expect(useDemoStore.getState().paraEvalState[0].stale).toBe(true);
  });
});

describe('saveParagraphTarget (explicit re-eval)', () => {
  it('marks the paragraph stale on a successful manual edit, without calling evaluate', async () => {
    vi.mocked(patchParagraph).mockResolvedValue({
      id: 1, idx: 0, source: 'ru', target: 'edited text', scores: [], scoresPrev: null,
      scoresBaseline: null, aggregate: null, aggregateBaseline: null, issues: [], terms: [],
    });
    await useDemoStore.getState().saveParagraphTarget(1, 'edited text');
    expect(evaluate).not.toHaveBeenCalled();
    expect(useDemoStore.getState().paraEvalState[0].stale).toBe(true);
  });

  it('does not mark stale when the PATCH fails', async () => {
    vi.mocked(patchParagraph).mockRejectedValue(new Error('HTTP 500'));
    await useDemoStore.getState().saveParagraphTarget(1, 'edited text');
    expect(useDemoStore.getState().paraEvalState[0].stale).toBe(false);
  });
});

describe('dismissIssue failure surfaces paraEvalState.error (M4)', () => {
  it('sets an error on the owning paragraph when the PATCH fails', async () => {
    vi.mocked(patchIssueStatus).mockRejectedValue(new Error('HTTP 500'));
    await useDemoStore.getState().dismissIssue('1');
    const st = useDemoStore.getState().paraEvalState[0];
    expect(st.error).toContain('Dismiss failed');
    expect(st.error).toContain('500');
  });

  it('does not set an error when the PATCH succeeds', async () => {
    vi.mocked(patchIssueStatus).mockResolvedValue(issue('1', { status: 'dismissed' }));
    await useDemoStore.getState().dismissIssue('1');
    const st = useDemoStore.getState().paraEvalState[0];
    expect(st.error).toBeNull();
  });
});

describe('criteria CRUD — add/remove (H-frontend)', () => {
  function makeCriterion(over: Partial<Criterion> = {}): Criterion {
    return {
      id: 'crit-1', name: 'New criterion', modelName: 'openai/gpt-5.4-mini', prompt: '',
      scaleMin: 1, scaleMax: 10, weight: 0.1, color: '#a3e635', enabled: false,
      ...over,
    };
  }

  it('addCriterion posts and appends the created criterion to state', async () => {
    const created = makeCriterion();
    vi.mocked(createCriterion).mockResolvedValue(created);
    useDemoStore.setState({ criteria: [] });
    await useDemoStore.getState().addCriterion(created);
    expect(createCriterion).toHaveBeenCalledWith(created);
    expect(useDemoStore.getState().criteria).toContainEqual(created);
  });

  it('removeCriterion propagates a 409 (history conflict) instead of swallowing it', async () => {
    vi.mocked(deleteCriterion).mockRejectedValue(new Error('DELETE /criteria/accuracy → 409'));
    useDemoStore.setState({ criteria: [makeCriterion({ id: 'accuracy' })] });
    await expect(useDemoStore.getState().removeCriterion('accuracy')).rejects.toThrow('409');
    // criterion must remain in state — the failed delete did not mutate it
    expect(useDemoStore.getState().criteria).toHaveLength(1);
  });
});

describe('saveTranslatorConfig (S4 §3.4)', () => {
  it('PUTs the config and replaces translatorConfig in state', async () => {
    const cfg: TranslatorConfig = { modelName: 'openai/gpt-5.4-mini', prompt: 'p', params: { temperature: 0 } };
    vi.mocked(updateTranslatorConfig).mockResolvedValue(cfg);
    await useDemoStore.getState().saveTranslatorConfig(cfg);
    expect(updateTranslatorConfig).toHaveBeenCalledWith(cfg);
    expect(useDemoStore.getState().translatorConfig).toEqual(cfg);
  });
});

describe('retryTranslate (S4 §3.3)', () => {
  it('re-POSTs /translate for the current document then refreshes it', async () => {
    vi.mocked(translateDocument).mockResolvedValue({ status: 'started', total: 3 });
    const refreshed = makeDoc([]);
    vi.mocked(getDocument).mockResolvedValue(refreshed);
    useDemoStore.setState({ document: makeDoc([]) });

    await useDemoStore.getState().retryTranslate();

    expect(translateDocument).toHaveBeenCalledWith(1);
    expect(getDocument).toHaveBeenCalledWith(1);
    expect(useDemoStore.getState().document).toEqual(refreshed);
  });

  it('is a no-op when no document is loaded', async () => {
    useDemoStore.setState({ document: null });
    await useDemoStore.getState().retryTranslate();
    expect(translateDocument).not.toHaveBeenCalled();
  });
});

describe('runFirstParagraphsEvaluate (S4 §3.3 — reuses the existing per-paragraph evaluate path)', () => {
  it('evaluates each paragraph of the document in order', async () => {
    const doc = makeDoc([]);
    doc.paragraphs = [
      { ...doc.paragraphs[0], id: 1, idx: 0 },
      { ...doc.paragraphs[0], id: 2, idx: 1 },
    ];
    useDemoStore.setState({ document: doc, paraEvalState: {} });
    vi.mocked(evaluate).mockResolvedValue(evalResponse);

    await useDemoStore.getState().runFirstParagraphsEvaluate();

    expect(evaluate).toHaveBeenCalledTimes(2);
    expect(evaluate).toHaveBeenNthCalledWith(1, 1, undefined);
    expect(evaluate).toHaveBeenNthCalledWith(2, 2, undefined);
  });
});

describe('restoreParagraphRevision (S5 §3.3)', () => {
  it('restores via POST and replaces the paragraph, marking it stale', async () => {
    const restored: Paragraph = {
      ...makeDoc([]).paragraphs[0],
      target: 'restored text',
    };
    vi.mocked(restoreRevision).mockResolvedValue(restored);
    useDemoStore.setState({ document: makeDoc([]), paraEvalState: { 0: {
      loading: false, cached: false, cachedAt: null, failedCriterionIds: [], error: null, stale: false,
    } } });

    await useDemoStore.getState().restoreParagraphRevision(1, 0, 42);

    expect(restoreRevision).toHaveBeenCalledWith(1, 42);
    expect(useDemoStore.getState().document?.paragraphs[0].target).toBe('restored text');
    expect(useDemoStore.getState().paraEvalState[0].stale).toBe(true);
  });
});

describe('init (boot sequence) — auxiliary config isolation (2026-07-06 prod incident, prod-wave5-run.md)', () => {
  const summaries: DocumentSummary[] = [
    { id: 1, title: 'Doc', sourceLang: 'ru', targetLang: 'en', nParagraphs: 1, origin: 'seed' },
  ];
  const criteriaList: Criterion[] = [
    { id: 'accuracy', name: 'Accuracy', modelName: 'openai/gpt-5.4-mini', prompt: '',
      scaleMin: 1, scaleMax: 10, weight: 0.3, color: '#4d8dff', enabled: true },
  ];
  const modelsList: ModelRegistryEntryPublic[] = [
    { name: 'openai/gpt-5.4-mini', baseUrl: '', apiKeyMasked: '****', params: {}, effectiveParams: {} },
  ];
  const groundingCfg: GroundingConfig = { modelName: 'openai/gpt-5.4-mini', prompt: 'g', params: {} };
  const translatorCfg: TranslatorConfig = { modelName: 'openai/gpt-5.4-mini', prompt: 't', params: {} };
  const doc = makeDoc([]);

  beforeEach(() => {
    useDemoStore.setState({ document: null, documentError: null, documentLoading: false });
    vi.mocked(getDocuments).mockResolvedValue(summaries);
    vi.mocked(getCriteria).mockResolvedValue(criteriaList);
    vi.mocked(getModels).mockResolvedValue(modelsList);
    vi.mocked(getDocument).mockResolvedValue(doc);
    vi.mocked(getHealth).mockResolvedValue({ service: 's', status: 'ok', limits: { maxParagraphs: 100, maxParaChars: 5000 } });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('a rejected grounding-config fetch does not block the document from loading; fallback recorded as null', async () => {
    vi.mocked(getGroundingConfig).mockRejectedValue(new Error('GET /grounding-config → 500'));
    vi.mocked(getTranslatorConfig).mockResolvedValue(translatorCfg);
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});

    await useDemoStore.getState().init();

    const state = useDemoStore.getState();
    expect(state.documentError).toBeNull();
    expect(state.document).toEqual(doc);
    expect(state.documents).toEqual(summaries);
    expect(state.groundingConfig).toBeNull();
    expect(state.translatorConfig).toEqual(translatorCfg);
    expect(warnSpy).toHaveBeenCalled();
  });

  it('a rejected translator-config fetch does not block the document from loading; fallback recorded as null', async () => {
    vi.mocked(getGroundingConfig).mockResolvedValue(groundingCfg);
    vi.mocked(getTranslatorConfig).mockRejectedValue(new Error('GET /translator-config → 500'));
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});

    await useDemoStore.getState().init();

    const state = useDemoStore.getState();
    expect(state.documentError).toBeNull();
    expect(state.document).toEqual(doc);
    expect(state.groundingConfig).toEqual(groundingCfg);
    expect(state.translatorConfig).toBeNull();
    expect(warnSpy).toHaveBeenCalled();
  });

  it('a boot-critical fetch (getDocuments) rejecting surfaces documentError, not an unhandled rejection', async () => {
    vi.mocked(getGroundingConfig).mockResolvedValue(groundingCfg);
    vi.mocked(getTranslatorConfig).mockResolvedValue(translatorCfg);
    vi.mocked(getDocuments).mockRejectedValue(new Error('GET /documents → 500'));

    await expect(useDemoStore.getState().init()).resolves.toBeUndefined();

    const state = useDemoStore.getState();
    expect(state.documentError).toContain('500');
    expect(state.document).toBeNull();
    expect(state.documentLoading).toBe(false);
  });
});
