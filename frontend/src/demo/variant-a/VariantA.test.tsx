import { readFileSync } from 'node:fs';
import path from 'node:path';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import VariantA, { selectPopoverIssues, precomputeFailedMessage } from './VariantA';
import { useDemoStore } from '../store';
import type { DemoStore } from '../store';
import type { Document, Issue, Paragraph, PrecomputeStatus } from '../api-client';

vi.mock('../store', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../store')>();
  return { ...actual, useDemoStore: vi.fn() };
});

function iss(id: string, over: Partial<Issue> = {}): Issue {
  return {
    id, paragraphId: 1, criterionId: 'accuracy', targetFragment: 'f', sourceFragment: '',
    explanation: 'why', suggestion: 'fix', severity: 'minor', mqmCategory: null, status: 'open',
    ...over,
  };
}

const allCriteria = new Set(['accuracy']);

describe('selectPopoverIssues (BUG-1: popover shows open issues only)', () => {
  it('keeps an open issue', () => {
    const paraIssues = [iss('1')];
    expect(selectPopoverIssues(paraIssues, ['1'], allCriteria)).toHaveLength(1);
  });

  it('drops an accepted issue from the popover list', () => {
    const paraIssues = [iss('1', { status: 'accepted' })];
    expect(selectPopoverIssues(paraIssues, ['1'], allCriteria)).toEqual([]);
  });

  it('drops a dismissed issue from the popover list', () => {
    const paraIssues = [iss('1', { status: 'dismissed' })];
    expect(selectPopoverIssues(paraIssues, ['1'], allCriteria)).toEqual([]);
  });

  it('drops an outdated issue from the popover list', () => {
    const paraIssues = [iss('1', { status: 'outdated' })];
    expect(selectPopoverIssues(paraIssues, ['1'], allCriteria)).toEqual([]);
  });

  it('mixed batch: only the still-open card survives, so accepting one member of a multi-issue popover shrinks it live', () => {
    const paraIssues = [iss('1', { status: 'accepted' }), iss('2', { status: 'open' })];
    const result = selectPopoverIssues(paraIssues, ['1', '2'], allCriteria);
    expect(result.map((i) => i.id)).toEqual(['2']);
  });

  it('returns empty once every issue in the popover has been actioned (drives auto-close)', () => {
    const paraIssues = [iss('1', { status: 'accepted' }), iss('2', { status: 'dismissed' })];
    expect(selectPopoverIssues(paraIssues, ['1', '2'], allCriteria)).toEqual([]);
  });

  it('still respects the activeCriteria filter alongside the open-status filter', () => {
    const paraIssues = [iss('1', { criterionId: 'fluency' })];
    expect(selectPopoverIssues(paraIssues, ['1'], allCriteria)).toEqual([]);
  });
});

function precompute(over: Partial<PrecomputeStatus>): PrecomputeStatus {
  return { status: 'done', done: 12, planned: 12, succeeded: 0, ...over };
}

describe('precomputeFailedMessage (S1 §2.6 — honest failure-reason banners)', () => {
  it('names a missing API key', () => {
    expect(precomputeFailedMessage(precompute({ errorReason: 'no_api_key' })))
      .toBe('Precompute skipped: no API key configured');
  });

  it('names an exhausted budget', () => {
    expect(precomputeFailedMessage(precompute({ errorReason: 'budget_exhausted' })))
      .toBe('Precompute skipped: budget cap reached');
  });

  it('falls back to the generic message for an unrecognized/absent reason', () => {
    expect(precomputeFailedMessage(precompute({ errorReason: 'all_failed' })))
      .toBe('Precompute failed — scores unavailable; use Evaluate ↻ on a paragraph');
    expect(precomputeFailedMessage(precompute({ errorReason: undefined })))
      .toBe('Precompute failed — scores unavailable; use Evaluate ↻ on a paragraph');
  });

  it('falls back to the generic message for a null/undefined precompute status', () => {
    expect(precomputeFailedMessage(null)).toBe('Precompute failed — scores unavailable; use Evaluate ↻ on a paragraph');
    expect(precomputeFailedMessage(undefined)).toBe('Precompute failed — scores unavailable; use Evaluate ↻ on a paragraph');
  });
});

// ─── Export menu (S6 §5 / audit-fix regression guard) ──────────────────────

function makeParagraph(id: number): Paragraph {
  return {
    id, idx: 0, source: 'src', target: 'tgt',
    scores: [], scoresPrev: null, scoresBaseline: null,
    aggregate: null, aggregateBaseline: null,
    issues: [], terms: [],
  };
}

function makeDoc(paragraphs: Paragraph[]): Document {
  return {
    id: 7,
    title: 'Doc',
    sourceLang: 'ru',
    targetLang: 'en',
    nParagraphs: paragraphs.length,
    origin: 'seed',
    sourceModel: 'm',
    aggregate: null,
    paragraphs,
  };
}

function makeStore(doc: Document): DemoStore {
  return {
    document: doc,
    documentResetNonce: 0,
    documents: [{ id: doc.id, title: doc.title, sourceLang: doc.sourceLang, targetLang: doc.targetLang, nParagraphs: doc.nParagraphs, origin: doc.origin }],
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
    activeCriteria: new Set(),
    showTerms: false,
    hoveredTermId: null,
    uploadModalOpen: false,
    uploadModalAiTranslateDefault: false,
    init: vi.fn().mockResolvedValue(undefined),
    backToPicker: vi.fn(),
    setSelectedParaIdx: vi.fn(),
    setInspectorTab: vi.fn(),
    setInspectorCollapsed: vi.fn(),
    toggleCriterion: vi.fn(),
    setShowTerms: vi.fn(),
    setHoveredTermId: vi.fn(),
    openUploadModal: vi.fn(),
    closeUploadModal: vi.fn(),
    refreshDocuments: vi.fn().mockResolvedValue(undefined),
    switchDocument: vi.fn().mockResolvedValue(undefined),
    createDoc: vi.fn().mockResolvedValue(undefined),
    deleteDoc: vi.fn().mockResolvedValue(undefined),
    refreshDocument: vi.fn().mockResolvedValue(undefined),
    acceptIssue: vi.fn().mockResolvedValue(undefined),
    applyIssueEdit: vi.fn().mockResolvedValue('applied'),
    dismissIssue: vi.fn().mockResolvedValue(undefined),
    acceptAllIssues: vi.fn().mockResolvedValue({ applied: 0, outdated: 0 }),
    evaluateParagraph: vi.fn().mockResolvedValue(undefined),
    refineParagraph: vi.fn().mockResolvedValue(undefined),
    saveParagraphTarget: vi.fn().mockResolvedValue(undefined),
    resetDoc: vi.fn().mockResolvedValue(undefined),
    addCriterion: vi.fn().mockResolvedValue(undefined),
    saveCriterion: vi.fn().mockResolvedValue(undefined),
    removeCriterion: vi.fn().mockResolvedValue(undefined),
    addModel: vi.fn().mockResolvedValue(undefined),
    saveModel: vi.fn().mockResolvedValue(undefined),
    removeModel: vi.fn().mockResolvedValue(undefined),
    testModel: vi.fn().mockResolvedValue({ ok: true, extracted: [], reference: [], matched: 0, total: 0, share: 0 }),
    saveGroundingConfig: vi.fn().mockResolvedValue(undefined),
    saveTranslatorConfig: vi.fn().mockResolvedValue(undefined),
    saveRefinerConfig: vi.fn().mockResolvedValue(undefined),
    retryTranslate: vi.fn().mockResolvedValue(undefined),
    runFirstParagraphsEvaluate: vi.fn().mockResolvedValue(undefined),
    restoreParagraphRevision: vi.fn().mockResolvedValue(undefined),
    startTermsPolling: vi.fn(),
    stopTermsPolling: vi.fn(),
  };
}

function renderVariantA(paragraphs: Paragraph[]) {
  vi.mocked(useDemoStore).mockReturnValue(makeStore(makeDoc(paragraphs)));
  return render(<VariantA />);
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('Export control (audit-fix HIGH: dropdown items were unclickable)', () => {
  it('disables the Export button when the document has no paragraphs', () => {
    renderVariantA([]);
    expect((screen.getByTestId('export-btn') as HTMLButtonElement).disabled).toBe(true);
  });

  it('opens the menu on click, with both formats present and correctly wired', () => {
    renderVariantA([makeParagraph(1)]);
    expect((screen.getByTestId('export-btn') as HTMLButtonElement).disabled).toBe(false);

    fireEvent.click(screen.getByTestId('export-btn'));
    expect(screen.getByTestId('export-menu')).toBeTruthy();
    expect(screen.getByTestId('export-xlsx')).toBeTruthy();
    expect(screen.getByTestId('export-md')).toBeTruthy();
  });

  it('clicking a menu item downloads the correct format for the current document', () => {
    renderVariantA([makeParagraph(1)]);
    fireEvent.click(screen.getByTestId('export-btn'));

    const hrefs: string[] = [];
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click')
      .mockImplementation(function (this: HTMLAnchorElement) { hrefs.push(this.getAttribute('href') ?? ''); });

    fireEvent.click(screen.getByTestId('export-xlsx'));
    expect(hrefs).toEqual(['/api/documents/7/export?format=xlsx']);

    fireEvent.click(screen.getByTestId('export-btn'));
    fireEvent.click(screen.getByTestId('export-md'));
    expect(hrefs).toEqual(['/api/documents/7/export?format=xlsx', '/api/documents/7/export?format=md']);

    clickSpy.mockRestore();
  });

  it('closes the menu on an outside (backdrop) click — click-outside-to-close still works', () => {
    const { container } = renderVariantA([makeParagraph(1)]);
    fireEvent.click(screen.getByTestId('export-btn'));
    expect(screen.getByTestId('export-menu')).toBeTruthy();

    fireEvent.click(container.querySelector('.va-popover-backdrop')!);
    expect(screen.queryByTestId('export-menu')).toBeNull();
  });

  it('regression guard: .va-export-menu must outrank .va-popover-backdrop in z-index, or the ' +
    'transparent click-outside layer intercepts real mouse clicks on the menu items (audit-fix HIGH)', () => {
    const css = readFileSync(path.join(import.meta.dirname, 'variant-a.css'), 'utf-8');
    const backdropZ = Number(/\.va-popover-backdrop\s*\{[^}]*z-index:\s*(\d+)/.exec(css)?.[1]);
    const menuZ = Number(/\.va-export-menu\s*\{[^}]*z-index:\s*(\d+)/.exec(css)?.[1]);
    expect(Number.isNaN(backdropZ)).toBe(false);
    expect(Number.isNaN(menuZ)).toBe(false);
    expect(menuZ).toBeGreaterThan(backdropZ);
  });
});

describe('VariantA Refine/Evaluate double-submit guard (paid-LLM-call race)', () => {
  it('fires evaluateParagraph exactly once for 3 synchronous clicks on Evaluate ↻', () => {
    const evaluateParagraph = vi.fn().mockResolvedValue(undefined);
    vi.mocked(useDemoStore).mockReturnValue({
      ...makeStore(makeDoc([makeParagraph(1)])),
      evaluateParagraph,
    });
    render(<VariantA />);

    // Raw DOM .click() (not RTL's act()-wrapped fireEvent) reproduces the real
    // race: 3 rapid clicks land before React commits the `loading` state that
    // disables the button — same repro shape as UploadModal Step2's submit guard.
    const btn = screen.getByTestId('evaluate-para') as HTMLButtonElement;
    btn.click();
    btn.click();
    btn.click();

    expect(evaluateParagraph).toHaveBeenCalledTimes(1);
  });

  it('fires refineParagraph exactly once for 3 synchronous clicks on Refine paragraph ✦', () => {
    const refineParagraph = vi.fn().mockResolvedValue(undefined);
    const paragraph = { ...makeParagraph(1), issues: [iss('1')] };
    vi.mocked(useDemoStore).mockReturnValue({
      ...makeStore(makeDoc([paragraph])),
      activeCriteria: new Set(['accuracy']),
      refineParagraph,
    });
    render(<VariantA />);

    const btn = screen.getByTestId('refine-paragraph') as HTMLButtonElement;
    btn.click();
    btn.click();
    btn.click();

    expect(refineParagraph).toHaveBeenCalledTimes(1);
  });
});

describe('Reset confirm dialog (BUG-4: truthful archive copy, frontend-developer-stability-wave1)', () => {
  it('tells the truth: live scores/issues are archived, not lost — and drops the old "will be lost" claim', () => {
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false);   // don't actually reset
    renderVariantA([makeParagraph(1)]);

    fireEvent.click(screen.getByText('Reset'));

    expect(confirmSpy).toHaveBeenCalledTimes(1);
    const message = confirmSpy.mock.calls[0][0] as string;
    expect(message).toContain('archived');
    expect(message).not.toContain('will be lost');
    confirmSpy.mockRestore();
  });
});

describe('Document delete button — double-DELETE guard (BUG-4, frontend-developer-stability-wave2)', () => {
  function makeUploadDoc() {
    return { ...makeDoc([makeParagraph(1)]), origin: 'upload' as const };
  }

  it('fires deleteDoc exactly once for 3 synchronous clicks (double-bound handler / ghost click after confirm())', () => {
    const deleteDoc = vi.fn().mockResolvedValue(undefined);
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);
    vi.mocked(useDemoStore).mockReturnValue({ ...makeStore(makeUploadDoc()), deleteDoc });
    render(<VariantA />);

    // Raw DOM .click() (not RTL's act()-wrapped fireEvent) — same repro shape
    // as the Evaluate/Refine double-submit guard tests above: 3 rapid clicks
    // land before React commits any state, so only the synchronous ref guard
    // can stop the second/third invocation.
    const btn = screen.getByTestId('delete-doc-btn') as HTMLButtonElement;
    btn.click();
    btn.click();
    btn.click();

    expect(confirmSpy).toHaveBeenCalledTimes(1);   // the guard also suppresses a second confirm() prompt
    expect(deleteDoc).toHaveBeenCalledTimes(1);
    confirmSpy.mockRestore();
  });

  it('does not call deleteDoc when the confirm dialog is declined', () => {
    const deleteDoc = vi.fn().mockResolvedValue(undefined);
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false);
    vi.mocked(useDemoStore).mockReturnValue({ ...makeStore(makeUploadDoc()), deleteDoc });
    render(<VariantA />);

    fireEvent.click(screen.getByTestId('delete-doc-btn'));

    expect(confirmSpy).toHaveBeenCalledTimes(1);
    expect(deleteDoc).not.toHaveBeenCalled();
    confirmSpy.mockRestore();
  });

  it('re-arms after the in-flight delete settles, so a later genuine second delete still works', async () => {
    const deleteDoc = vi.fn().mockResolvedValue(undefined);
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);
    vi.mocked(useDemoStore).mockReturnValue({ ...makeStore(makeUploadDoc()), deleteDoc });
    render(<VariantA />);

    const btn = screen.getByTestId('delete-doc-btn') as HTMLButtonElement;
    fireEvent.click(btn);
    await waitFor(() => expect(deleteDoc).toHaveBeenCalledTimes(1));

    fireEvent.click(btn);
    await waitFor(() => expect(deleteDoc).toHaveBeenCalledTimes(2));

    confirmSpy.mockRestore();
  });
});

describe('Refine button available from both inspector tabs (BUG-5, frontend-developer-stability-wave1)', () => {
  it('is present when the inspector is on the Scores tab, not just Issues', () => {
    const paragraph = { ...makeParagraph(1), issues: [iss('1')] };
    vi.mocked(useDemoStore).mockReturnValue({
      ...makeStore(makeDoc([paragraph])),
      activeCriteria: new Set(['accuracy']),
      inspectorTab: 'scores',
    });
    render(<VariantA />);

    expect(screen.getByTestId('refine-paragraph')).toBeTruthy();
  });
});

describe('Tab isolation (BUG-2: non-active tab content is unmounted, not merely hidden, ' +
  'frontend-developer-stability-wave1)', () => {
  it('unmounts the Document-tab body (paragraphs + inspector) when switching to another main tab', () => {
    renderVariantA([makeParagraph(1)]);
    expect(screen.getByTestId('evaluate-para')).toBeTruthy();       // Document tab active by default
    expect(screen.getByTestId('refine-paragraph')).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: 'Glossary' }));

    // A stray click on where these controls used to be must hit nothing —
    // the whole Document-tab subtree is gone from the DOM, not just hidden.
    expect(screen.queryByTestId('evaluate-para')).toBeNull();
    expect(screen.queryByTestId('refine-paragraph')).toBeNull();
  });

  it('unmounts the Glossary tab body when switching back to Document', () => {
    renderVariantA([makeParagraph(1)]);
    fireEvent.click(screen.getByRole('button', { name: 'Glossary' }));
    expect(screen.getByText('Terminology Glossary')).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: 'Document' }));

    expect(screen.queryByText('Terminology Glossary')).toBeNull();
    expect(screen.getByTestId('evaluate-para')).toBeTruthy();
  });
});
