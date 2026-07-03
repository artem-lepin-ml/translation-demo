import { describe, expect, it } from 'vitest';
import { isBcp47Like, langLabel } from '../lang';

describe('isBcp47Like', () => {
  it('accepts 2-letter code', () => expect(isBcp47Like('ru')).toBe(true));
  it('accepts region-tagged code', () => expect(isBcp47Like('de-DE')).toBe(true));
  it('rejects free text with space', () => expect(isBcp47Like('New Guinea')).toBe(false));
  it('rejects malformed', () => expect(isBcp47Like('!!!')).toBe(false));
});

describe('langLabel', () => {
  it('dictionary code → full name (first lookup step)', () => {
    expect(langLabel('ru')).toBe('Russian');
    expect(langLabel('en')).toBe('English');
  });
  it('non-dictionary BCP-47 code → Intl display name', () => {
    expect(langLabel('de')).toBe('German');
  });
  it('free-text language name → passed through capitalized', () => {
    expect(langLabel('russian')).toBe('Russian');
    expect(langLabel('german')).toBe('German');
  });
  it("2-3 letter free text ('she') → no throw, non-empty (accepted boundary, spec §3)", () => {
    const out = langLabel('she');
    expect(typeof out).toBe('string');
    expect(out.length).toBeGreaterThan(0); // echo 'she' OR an ISO name — both accepted
  });
  it('garbage → passed through', () => {
    expect(langLabel('!!!')).toBe('!!!');
  });
});
