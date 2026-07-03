import { describe, expect, it } from 'vitest';
import { decodeText, splitParagraphs } from '../file-ingest';

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
