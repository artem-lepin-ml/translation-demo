import { readFileSync } from 'node:fs';
import path from 'node:path';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
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
