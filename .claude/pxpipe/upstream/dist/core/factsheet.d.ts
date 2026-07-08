/**
 * Verbatim fact-sheet for imaged content.
 *
 * When pxpipe renders a block (system slab, history, tool_result, reminder) to a PNG,
 * the precision-critical, hard-to-OCR strings inside it — file paths, URLs, SHAs/UUIDs,
 * version numbers, CLI flags, large numbers, CONST_IDS — are exactly what a model is
 * most likely to misread off the image yet most likely to need quoted verbatim. This
 * module extracts those tokens so they ride next to the image as plain text: the model
 * quotes them without re-reading the PNG, and they stay in the cached prefix.
 *
 * Deterministic by construction (fixed pattern order, length-desc/lexical sort, no
 * Date/random) → the emitted text is byte-stable across turns and never busts the
 * Anthropic prompt cache. Empirically ~5% of source chars on production history
 * (median 4.9%, max 12.1%, N=10), which preserves the imaging token win.
 */
/** Budget cap: highest-priority tokens kept first. Exported so consumers can report drops. */
export declare const MAX_TOKENS = 64;
/**
 * Extract deduped, precision-critical tokens from `text`. Substrings of a longer kept
 * token are dropped (so `/github.com` inside the full URL, `lib/x.ts` inside
 * `src/lib/x.ts`, etc. collapse to the most specific form); the 64-token budget is then
 * filled by priority tier (see `priorityTier`) so short, high-consequence tokens are never
 * evicted by long low-risk URLs.
 *
 * Every token class is whitespace-free, so we split on whitespace first and skip
 * blob-length chunks. That bounds each regex to a short chunk and keeps extraction
 * strictly O(n) — no quadratic backtracking on delimiter-heavy input like base64 or
 * minified bundles (which embed `/` and would otherwise make the path patterns blow up).
 */
export declare function extractFactSheetTokens(text: string): string[];
/** A kept fact-sheet token plus how many times it occurs in the scanned text.
 *  Counts are advisory (occurrences, not lines) but deterministic → cache-stable. */
export interface FactSheetEntry {
    readonly token: string;
    readonly count: number;
}
/**
 * Like `extractFactSheetTokens`, but each kept token carries its occurrence count.
 * Counts make the fact sheet a *quantitative* index: tally questions over imaged
 * content ("how many lines mention CODE-X?") become answerable from text instead
 * of from counting rows of 5×8 px glyphs — the one operation page images are worst
 * at. The kept-token SET and its order are byte-identical to the pre-count
 * behaviour; only counts are new. Same-token spans matched by two patterns are
 * deduped by offset so a token is never double-counted.
 */
export declare function extractFactSheetEntries(text: string): FactSheetEntry[];
/**
 * Page-aware variant of `extractFactSheetTokens` for large source texts.
 *
 * Splits `text` into chunks of `charsPerPage` (use `DENSE_CONTENT_CHARS_PER_IMAGE`
 * from render.ts for the export pipeline), calls `extractFactSheetTokens` on each
 * chunk (each chunk is smaller than MAX_SCAN so no truncation occurs), merges the
 * results across all chunks with first-seen deduplication, then applies a single
 * global priority-budget pass to select the best MAX_TOKENS identifiers.
 *
 * Returns `{ kept, dropped }` where `dropped` is the count of identifiers that
 * survived extraction across all pages but did not fit in the MAX_TOKENS budget.
 *
 * Does NOT mutate the behaviour of `extractFactSheetTokens` or `factSheetText`.
 */
export declare function extractFactSheetTokensAllPages(text: string, charsPerPage: number): {
    kept: string[];
    dropped: number;
};
/** Entry-carrying variant of `extractFactSheetTokensAllPages`: same kept set and
 *  order, with per-token occurrence counts summed across all pages. */
export declare function extractFactSheetEntriesAllPages(text: string, charsPerPage: number): {
    kept: FactSheetEntry[];
    dropped: number;
};
/** Build the one-line fact-sheet string from a pre-extracted token list. */
export declare function factSheetTextFromTokens(tokens: string[]): string;
/** Build the one-line fact-sheet string from token+count entries. Byte-identical to
 *  `factSheetTextFromTokens` when no token repeats, so existing sheets stay cache-stable. */
export declare function factSheetTextFromEntries(entries: readonly FactSheetEntry[]): string;
/** One-line fact-sheet string for `text`, or `''` when nothing notable was found. */
export declare function factSheetText(text: string): string;
//# sourceMappingURL=factsheet.d.ts.map