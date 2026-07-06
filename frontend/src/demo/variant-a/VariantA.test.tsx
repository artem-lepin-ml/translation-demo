import { describe, expect, it } from 'vitest';
import { selectPopoverIssues, precomputeFailedMessage } from './VariantA';
import type { Issue, PrecomputeStatus } from '../api-client';

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
