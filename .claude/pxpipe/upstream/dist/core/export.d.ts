/**
 * Core logic for `pxpipe export` — renders a source text to PNG pages, extracts
 * a verbatim factsheet, builds a manifest and paste-ready prompt, and returns a
 * token-cost report + list of artifacts to write.
 *
 * Pure-ish: no argv, no stdout, no process.exit, no fs calls — all I/O is
 * delegated to the thin CLI runner in src/node.ts.
 */
export declare const DEFAULT_EXPORT_MODEL = "claude-sonnet-4-5";
/** Default column width — dense content mode (312 cols = 1568 px). */
export declare const DEFAULT_EXPORT_COLS: number;
/**
 * Match a relative file path against a glob pattern.
 * Supported wildcards: `*` (non-separator), `**` (any including `/`), `?` (single non-sep).
 * When the pattern contains no `/`, matching is against the basename only
 * (e.g. `*.ts` matches `src/foo.ts`).
 */
export declare function matchGlob(pattern: string, filePath: string): boolean;
/**
 * Decide whether a relative file path should be included given include/exclude glob lists.
 * - Exclude patterns are checked first; any match → exclude.
 * - If include patterns are given, at least one must match.
 * - If no include patterns are given, everything passes (unless excluded).
 */
export declare function shouldIncludeFile(filePath: string, include: string[], exclude: string[]): boolean;
export interface ExportParsed {
    targets: string[];
    include: string[];
    exclude: string[];
    git: boolean;
    diff: string | undefined;
    stdin: boolean;
    cols: number;
    out: string;
    model: string;
    json: boolean;
    open: boolean;
}
export type ExportArgvResult = {
    kind: 'opts';
    parsed: ExportParsed;
} | {
    kind: 'help';
} | {
    kind: 'error';
    message: string;
};
/**
 * Parse the argv array for the `export` subcommand.
 * Returns a discriminated union so the caller (node.ts) decides
 * whether to exit, print help, or proceed.
 *
 * @param defaultOut  Base output directory (default: $TMPDIR or /tmp).
 */
export declare function parseExportArgv(argv: string[], defaultOut?: string): ExportArgvResult;
/**
 * Per-image vision-token cost for a rendered PNG at the given pixel dimensions.
 *
 * - **Claude / Anthropic models** (`model.startsWith('claude')` or
 *   `model.includes('anthropic')`): uses Anthropic's billing formula
 *   `ceil(width × height / 750 × 1.10)` (the same formula and constants as
 *   `imageTokensForRows` in transform.ts, reusing the exported
 *   `ANTHROPIC_PIXELS_PER_TOKEN` / `IMAGE_COST_SAFETY_MARGIN` consts).
 * - **GPT / o-series models**: delegates to `openAIVisionTokens` which uses the
 *   GPT-4o tile-pricing formula (85 + 170 × tiles after scaling).
 */
export declare function exportImageTokens(model: string, width: number, height: number): number;
export interface ExportTokenReport {
    textTokens: number;
    imageTokens: number;
    percentSaved: number;
    /** Count of unique identifier strings extracted across all pages (paths, SHAs, ids, …).
     *  This is a count of items, not an LLM token count. */
    factsheetItemCount: number;
    /** Identifiers extracted across all pages that did not fit within the 64-item
     *  factsheet budget. Zero when all extracted items were kept. */
    factsheetDropped: number;
}
/**
 * Estimate text vs image token cost for `sourceText` without rendering.
 * Uses the same formula as the internal gate:
 *   stripW = 2·PAD_X + cols·CELL_W
 *   imageTokens = estimateImageCount(text, cols) × exportImageTokens(model, stripW, MAX_HEIGHT_PX)
 *   textTokens = sourceText.length / REPORT_CHARS_PER_TOKEN
 *
 * `exportImageTokens` routes to the Anthropic billing formula (width×height/750×1.10)
 * for Claude models, and to the GPT tile-pricing formula for GPT/o-series models.
 *
 * `factsheetItemCount` is the number of unique precision-critical identifier strings
 * extracted across all pages (paths, SHAs, ids, …); it is NOT an LLM token count.
 * `factsheetDropped` is the count of extracted identifiers that did not fit within
 * the 64-item per-export budget.
 */
export declare function computeTokenReport(sourceText: string, cols: number, model: string): ExportTokenReport;
export interface ExportPageInfo {
    filename: string;
    bytes: number;
    width: number;
    height: number;
}
export interface ExportManifest {
    sourceChars: number;
    files: string[];
    pages: ExportPageInfo[];
    cols: number;
    model: string;
    generatedAt: string;
    tokenReport: ExportTokenReport;
}
export interface ExportArtifact {
    filename: string;
    data: Uint8Array;
}
export interface ExportResult {
    manifest: ExportManifest;
    artifacts: ExportArtifact[];
}
export interface ExportCoreOptions {
    /** Relative file paths listed in the manifest and prompt (display only). */
    sourceFiles: string[];
    cols: number;
    model: string;
}
export declare function buildPromptText(pageCount: number, factsheet: string, files: string[], droppedItems?: number): string;
/** 8-char hex hash of the first 512 chars + length of `text`. */
export declare function sourceShortHash(text: string): string;
export declare function runExportCore(sourceText: string, opts: ExportCoreOptions): Promise<ExportResult>;
//# sourceMappingURL=export.d.ts.map