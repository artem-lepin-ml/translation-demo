import { describe, expect, it } from 'vitest';
import { decodeText, normalizeLineEndings, splitParagraphs } from '../file-ingest';

describe('decodeText', () => {
  it('falls back to windows-1251 on U+FFFD', () => {
    const cp1251 = new Uint8Array([0xcf, 0xf0, 0xe8, 0xe2, 0xe5, 0xf2]); // «Привет»
    expect(decodeText(cp1251.buffer)).toBe('Привет');
  });
  it('keeps valid utf-8', () => {
    expect(decodeText(new TextEncoder().encode('Привет').buffer)).toBe('Привет');
  });
  it('throws on random binary bytes (mojibake, not a text file)', () => {
    const bytes = new Uint8Array(2000);
    for (let i = 0; i < bytes.length; i++) bytes[i] = Math.floor(Math.random() * 256);
    expect(() => decodeText(bytes.buffer)).toThrow();
  });
});

describe('splitParagraphs', () => {
  it('splits on blank lines, trims, drops empties', () => {
    expect(splitParagraphs('a\n\n  \n\nb\nc\n\n')).toEqual(['a', 'b\nc']);
  });
});

describe('normalizeLineEndings (T1-F3: CRLF byte-counting bug)', () => {
  it('converts CRLF to LF', () => {
    expect(normalizeLineEndings('a\r\nb\r\nc')).toBe('a\nb\nc');
  });

  it('converts a lone CR (old Mac style) to LF', () => {
    expect(normalizeLineEndings('a\rb\rc')).toBe('a\nb\nc');
  });

  it('leaves LF-only text untouched', () => {
    expect(normalizeLineEndings('a\nb\nc')).toBe('a\nb\nc');
  });

  it('is idempotent', () => {
    const once = normalizeLineEndings('a\r\nb\r\nc');
    expect(normalizeLineEndings(once)).toBe(once);
  });

  it('makes the reported length match the real (LF-normalized) content on a CRLF file, ' +
    'the exact counter/create-time parity the fix requires', () => {
    // 3 lines of 5 chars joined by CRLF: raw length 5+2+5+2+5=19, real (LF) length 5+1+5+1+5=17.
    const crlf = 'aaaaa\r\nbbbbb\r\nccccc';
    const normalized = normalizeLineEndings(crlf);
    expect(crlf.length).toBe(19);
    expect(normalized.length).toBe(17);
    expect(normalized).toBe('aaaaa\nbbbbb\nccccc');
  });
});
