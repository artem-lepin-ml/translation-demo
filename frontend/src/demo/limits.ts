/**
 * limits.ts — upload paragraph/char limits (S3 §2.3).
 *
 * SSOT is the server (`GET /api/health` → `limits`); these constants are only
 * the pre-init fallback so the modal renders sane values before `applyLimits`
 * runs once at store init. Mirrors `app.py` MAX_PARAGRAPHS/MAX_PARA_CHARS.
 */

export let MAX_PARAGRAPHS = 40;
export let MAX_PARA_CHARS = 4000;

export function applyLimits(limits: { maxParagraphs: number; maxParaChars: number }): void {
  MAX_PARAGRAPHS = limits.maxParagraphs;
  MAX_PARA_CHARS = limits.maxParaChars;
}
