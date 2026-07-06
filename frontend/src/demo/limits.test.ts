import { afterEach, describe, expect, it } from 'vitest';
import * as limits from './limits';
import { applyLimits } from './limits';

describe('limits.ts (S3 §2.3 — server-synced upload limits)', () => {
  afterEach(() => {
    // Restore the module's fallback defaults so tests don't leak state into
    // each other (limits.ts intentionally has no reset export — tests are
    // the only caller that needs one).
    applyLimits({ maxParagraphs: 40, maxParaChars: 4000 });
  });

  it('defaults to the client fallback constants mirroring app.py', () => {
    expect(limits.MAX_PARAGRAPHS).toBe(40);
    expect(limits.MAX_PARA_CHARS).toBe(4000);
  });

  it('applyLimits updates the live bindings importers observe', () => {
    applyLimits({ maxParagraphs: 60, maxParaChars: 6000 });
    expect(limits.MAX_PARAGRAPHS).toBe(60);
    expect(limits.MAX_PARA_CHARS).toBe(6000);
  });
});
