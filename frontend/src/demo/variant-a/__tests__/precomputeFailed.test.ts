import { describe, expect, it } from 'vitest';
import { precomputeFailed } from '../VariantA';
import type { PrecomputeStatus } from '../../api-client';

describe('precomputeFailed (BUG-5 seam)', () => {
  it('true when status is done, planned > 0, and succeeded is 0', () => {
    const status: PrecomputeStatus = { status: 'done', done: 2, planned: 2, succeeded: 0 };
    expect(precomputeFailed(status)).toBe(true);
  });

  it('false when at least one paragraph succeeded', () => {
    const status: PrecomputeStatus = { status: 'done', done: 2, planned: 2, succeeded: 1 };
    expect(precomputeFailed(status)).toBe(false);
  });

  it('false while still running', () => {
    const status: PrecomputeStatus = { status: 'running', done: 1, planned: 2, succeeded: 0 };
    expect(precomputeFailed(status)).toBe(false);
  });

  it('false when skipped (precompute was never requested)', () => {
    const status: PrecomputeStatus = { status: 'skipped', done: 0, planned: 0, succeeded: 0 };
    expect(precomputeFailed(status)).toBe(false);
  });

  it('false when stopped (sub-cap hit, not a pure failure)', () => {
    const status: PrecomputeStatus = { status: 'stopped', done: 1, planned: 5, succeeded: 1 };
    expect(precomputeFailed(status)).toBe(false);
  });

  it('false when precompute is undefined (seed documents have no precompute field)', () => {
    expect(precomputeFailed(undefined)).toBe(false);
  });

  it('false when precompute is null', () => {
    expect(precomputeFailed(null)).toBe(false);
  });
});
