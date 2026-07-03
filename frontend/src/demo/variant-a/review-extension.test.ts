import { describe, expect, it } from 'vitest';
import type { Issue } from '../api-client';

// Mirrors review-extension.ts:116 — the visibility contract we must not regress.
function visibleForUnderline(activeIssues: Issue[], closed: Set<string>): Issue[] {
  return activeIssues.filter((iss) => !closed.has(iss.id) && iss.status === 'open');
}
const mk = (id: string, status: Issue['status']): Issue => ({
  id, paragraphId: 1, criterionId: 'accuracy', targetFragment: 'f', sourceFragment: '',
  explanation: '', suggestion: '', severity: 'minor', mqmCategory: null, status,
});

describe('review-extension underline visibility (regression)', () => {
  it('excludes outdated issues from underline spans', () => {
    const out = visibleForUnderline([mk('1', 'open'), mk('2', 'outdated')], new Set());
    expect(out.map((i) => i.id)).toEqual(['1']);
  });
  it('excludes accepted/dismissed and closedIssueIds', () => {
    const out = visibleForUnderline(
      [mk('1', 'open'), mk('2', 'accepted'), mk('3', 'dismissed')], new Set(['1']));
    expect(out).toEqual([]);
  });
});
