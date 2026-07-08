/**
 * Text → PNG renderer. Blits atlas glyphs into a grayscale framebuffer, then PNG-encodes.
 * Iterates by codepoint so East Asian Wide chars (2-cell advance) and surrogate pairs handled correctly.
 * Pages capped at ~1932×1932 px: Fable/Opus 4.8 >20-image requests are held to ≤2000 px/side
 * (REJECTED if exceeded, not silently downscaled); ≤4784 token limit binds first at 1932 px.
 */
/** Page-height ceiling. Measured (2026-07-01, count_tokens sweep, claude-sonnet-4-5 — see
 *  /tmp/pxexp/LEVER1-findings.md): the API downscales any image to fit BOTH long-edge ≤1568
 *  AND ~1.15 MP (≈1,143,750 px), then bills ≈ px/750 (≈1525 tok cap, applied per-image).
 *  The old 1932×1932 page was billed at cap but resampled 0.555× → 5×8 glyphs reached the
 *  encoder at ~2.8×4.4 px. New page shape 1568×728 = 1,141,504 px fits both bounds →
 *  WYSIWYG for the vision encoder (also satisfies ≤2000 px/side for >20-image requests). */
export declare const MAX_HEIGHT_PX = 728;
/** Char budget for the static slab (system + tools + CLAUDE.md). Matches physical page
 *  capacity at 312 cols × 90 rows so image-count estimates track real pagination. */
export declare const READABLE_CHARS_PER_IMAGE = 28080;
/** Char budget for dense content (tool output, collapsed history). 312 cols × 90 rows = 28080
 *  chars fills the 1568×728 page. NOTE: verbatim recall of imaged text is unreliable at any size. */
export declare const DENSE_CONTENT_CHARS_PER_IMAGE = 28080;
export declare const DENSE_CONTENT_COLS = 312;
/** Bare 5×8 cell (no padding). A/B showed 5×8 beats 7×10 on dense JSON (4/5 vs 3/5 reads, 42% fewer tokens).
 *  Revert to {cellWBonus:2, cellHBonus:2} if misread rates rise. */
export declare const DENSE_RENDER_STYLE: RenderStyle;
/** Horizontal padding (left + right each), px. Exported for transform.ts token-cost math. */
export declare const PAD_X = 4;
/** Vertical padding (top + bottom each), px. Exported for transform.ts token-cost math. */
export declare const PAD_Y = 4;
/** Production ships bare 5×8 atlas cell (reflow+grayscale+inimage instruction band
 *  brought 5×8 to 98.95% OCR accuracy on Opus 4.7, matching or beating padded cells).
 *  RenderStyle.cellWBonus/cellHBonus override per-eval only. */
export declare const DEFAULT_CELL_W_BONUS = 0;
export declare const DEFAULT_CELL_H_BONUS = 0;
/** Effective cell pixel dimensions. transform.ts derives image-budget math from these. */
export declare const CELL_W: number;
export declare const CELL_H: number;
export interface RenderedImage {
    png: Uint8Array;
    width: number;
    height: number;
    /** Input codepoints rendered (wide chars count as 1, not 2). */
    charsRendered: number;
    /** Codepoints absent from atlas, rendered as blank cells. Surface as telemetry. */
    droppedChars: number;
    /** Per-codepoint drop histogram. Empty when droppedChars === 0; never undefined. */
    droppedCodepoints: Map<number, number>;
}
/** Optional render-time styling. All fields unset = production default 5×8 cell.
 *  Eval harness overrides per variant to A/B cell sizes and structure aids. */
export interface RenderStyle {
    /** Draw faint grey grid rules onto background pixels (zero pixel cost). */
    grid?: boolean;
    /** Draw a vertical grid rule every N columns. 0/unset = row rules only. */
    gridCols?: number;
    /** Horizontal size multiplier for the ↵ newline marker. 1 = off. */
    markerScale?: number;
    /** Render the ↵ marker in red (switches PNG to RGB truecolor). */
    markerRed?: boolean;
    /** Extra blank rows above the 8px glyph (cell height = 8 + this). Unset = DEFAULT_CELL_H_BONUS. */
    cellHBonus?: number;
    /** Extra blank columns beside the 5px glyph (cell width = 5 + this). Negative overlaps glyphs. Unset = DEFAULT_CELL_W_BONUS. */
    cellWBonus?: number;
    /** Use the AA grayscale atlas (atlas-gray.ts). EVAL-ONLY; default 1-bit path is unchanged. */
    aa?: boolean;
    /** Cycle palette colors per glyph for per-character boundary cues. Forces RGB output. Composes with aa. */
    colorCycle?: boolean;
    /** Tint only the structural <user>/<assistant> boundary tags (body stays black)
     *  so speakers are scannable without recoloring content. Forces RGB. Composes with aa. */
    colorByRole?: boolean;
}
/** Strip trailing whitespace per line and collapse 4+ consecutive \n to 3.
 *  Does NOT touch mid-line spaces or leading indent — structure is preserved. */
export declare function minifyForRender(text: string): string;
/** U+21B5 ↵ sentinel for original hard newlines in reflowed text. In full-bmp atlas via Unifont. */
export declare const NL_SENTINEL = "\u21B5";
/** Look-alike (U+23CE ⏎) for a ↵ that was ALREADY in the source content — distinct from
 *  the U+21B5 ↵ we insert for newlines. reflow() bails when its input already contains the
 *  sentinel; that's vanishingly rare for normal content but common when the content is about
 *  pxpipe itself (rendered dumps, OCR, this very transcript). {@link neutralizeSentinel}
 *  swaps pre-existing sentinels for this glyph in RENDER-PREP only, so reflow can pack
 *  newlines instead of bailing to a raw, unpacked render. Originals are preserved verbatim
 *  elsewhere (recordRecoverable / cache-stable history), and reflow()'s own round-trip
 *  contract — and its tests — are left untouched. */
export declare const NL_SENTINEL_LITERAL = "\u23CE";
export declare function neutralizeSentinel(text: string): string;
/** colorByRole palette, indexed by slot-1. Only the boundary TAGS are tinted;
 *  body content stays black. [<user> tags, <assistant> tags]. */
export declare const ROLE_PALETTE: [number, number, number][];
/**
 * Slot markers for the parallel "slot string" — the structure-through mechanism
 * that replaces the old parse-back. A slot string is a width-preserving copy of
 * the rendered text: every structural role-tag character is swapped for one of
 * these control codes, and every other codepoint is copied verbatim. Because the
 * markers are width-1 (exactly like the ASCII tag chars they stand in for), the
 * existing reflow / wrapLines / paging transforms mutate the slot string in lock-
 * step with the text — only whitespace/newlines move, and those are slot 0 in
 * both. The renderer then reads role attribution BY POSITION instead of trying to
 * re-find "<user>" in flattened text (which miscolors a body that literally quotes
 * a tag). The structure is known at serialize time and carried, never guessed.
 */
export declare const SLOT_MARK_USER: string;
export declare const SLOT_MARK_ASSISTANT: string;
/** Width-preserving slot-0 copy of body text: identical codepoints (so wrap math is
 *  unchanged) but with any literal slot-marker control char neutralized. These are rare in
 *  real content but DO occur (e.g. binary-ish tool output that gets collapsed into history),
 *  so the replacement is width- and strip-equivalent to the marker — never a space, which
 *  the minifier would strip and misalign. Guarantees body can't forge a role hue. */
export declare function slotCopyBody(body: string): string;
/** Build the slot-string segment for one role-wrapped turn, mirroring the text
 *  form `<${tag}>\n${body}\n</${tag}>`: marker chars over the open/close tags,
 *  a verbatim slot-0 copy of the body. `mark` is the role's slot marker. */
export declare function roleSlotSegment(tag: string, body: string, mark: string, attr?: string): string;
/** Minify + tab-expand + join lines with ↵ sentinel. Returns null if text already
 *  contains ↵ (caller falls back to non-reflow path; vanishingly rare in practice). */
export declare function reflow(text: string): string | null;
/** Inverse of reflow: ↵ → '\n'. dereflow(reflow(text)) === minifyForRender(text) with tabs expanded. */
export declare function dereflow(reflowed: string): string;
/** Expand \t to U+2192 → + padding to the next TAB_WIDTH stop. Visible marker lets the
 *  model distinguish indent-spaces from intentional-spaces. Wide CJK chars count as 2 cols.
 *  U+0009 is absent from the atlas (control codepoint), so without this every tab was a drop. */
export declare function expandTabsInLine(line: string): string;
/** Visual width of a line in cells. Wide CJK = 2; enlarged ↵ = markerScale. */
export declare function measureLineCols(line: string, markerScale?: number): number;
/** Always renders at full canvas width. Signature kept for transform.ts compatibility; returns cols unchanged. */
export declare function shrinkColsToContent(text: string, cols: number, markerScale?: number): number;
/**
 * Real content-width measurement (the capability `shrinkColsToContent` historically
 * stubbed out): the display width, in cols, of the widest line in `text`, capped at
 * `maxCols`. Lets a renderer size a narrow canvas to short-line content (e.g. code)
 * instead of padding every page to full width. Pure function of (text, maxCols) →
 * deterministic width → cache-prefix-safe. Tabs are expanded so the measured width
 * matches what the renderer actually lays out.
 */
export declare function measureContentCols(text: string, maxCols: number, markerScale?: number): number;
export declare function wrapLines(text: string, cols: number, markerScale?: number): string[];
/** Render text to a single PNG (≤ MAX_HEIGHT_PX tall). Wide glyphs occupy 2 consecutive cells. */
export declare function renderChunkToPng(text: string, cols?: number, style?: RenderStyle, maxHeightPx?: number, slotText?: string): Promise<RenderedImage>;
/** Reflow-aware variant of renderTextToPngs. Falls back to non-reflow on sentinel collision. */
export declare function renderTextToPngsReflow(text: string, cols?: number, style?: RenderStyle): Promise<RenderedImage[]>;
/** Split text into N PNGs each ≤ MAX_HEIGHT_PX tall, respecting per-image char budget. */
export declare function renderTextToPngsWithCharLimit(text: string, cols?: number, maxCharsPerImage?: number, style?: RenderStyle, maxHeightPx?: number, slotText?: string): Promise<RenderedImage[]>;
export declare function renderTextToPngs(text: string, cols?: number, style?: RenderStyle, maxHeightPx?: number, slotText?: string): Promise<RenderedImage[]>;
/** Pixel width of a multi-col canvas. */
export declare function multiColWidth(cols: number, numCols: number): number;
/** Largest numCols fitting within MAX_WIDTH_PX. Used to clamp over-large CLI flags. */
export declare function maxFittingCols(cols: number): number;
/** Split text into N multi-column PNGs. numCols <= 1 delegates to renderTextToPngs
 *  for byte-identical output (determinism/cache_control preserved when flag is off). */
export declare function renderTextToPngsMultiCol(text: string, cols?: number, numCols?: number): Promise<RenderedImage[]>;
/** Reflow-aware variant of renderTextToPngsMultiCol. Falls back to non-reflow on sentinel collision. */
export declare function renderTextToPngsReflowMultiCol(text: string, cols?: number, numCols?: number): Promise<RenderedImage[]>;
export interface RenderDensePagesOptions {
    /** Wrap-width cap in cols. Default DENSE_CONTENT_COLS (384). */
    readonly cols?: number;
    /** Shrink the canvas to the widest actual line (default true). `false` keeps the full
     *  `cols` width — the proxy's eval-backed full-canvas / slab behavior. */
    readonly shrink?: boolean;
    /** Columns to pack side-by-side. `'auto'` (default) packs as many as fit the width cap;
     *  a number forces that count. Collapses to 1 when the canvas shrinks below the cap. */
    readonly multiCol?: number | 'auto';
    /** Reflow (minify + join hard newlines with ↵) before rendering. Default false. Callers
     *  that pre-reflow (the proxy's maybeReflow / history lockstep) pass false; `pxpipe export`
     *  passes true so short lines pack into full-width rows. */
    readonly reflow?: boolean;
    /** Max source chars per page. Default DENSE_CONTENT_CHARS_PER_IMAGE. */
    readonly maxCharsPerImage?: number;
    /** Render style. Default DENSE_RENDER_STYLE. */
    readonly style?: RenderStyle;
    /** Max page height in px. Default MAX_HEIGHT_PX. */
    readonly maxHeightPx?: number;
}
/**
 * The single dense-page rendering decision shared by the public SDK primitive
 * `renderTextToImages` (library.ts → `pxpipe export`) AND the proxy's `textToImageBlocks`
 * (transform.ts): optionally reflow, measure the content width, pack as many side-by-side
 * columns as actually fit the width cap (or honor an explicit count, collapsing the wasted
 * divider column when the canvas shrinks), then render. Both callers route through HERE so
 * export PNGs and proxy image blocks are produced by the exact same code and cannot drift —
 * `shrinkColsToContent` is `measureContentCols`, so the proxy's old inline path was already
 * identical at the default 384 cols; this makes it identical at every cols. Returns the raw
 * rendered pages; each caller packages them (PNG files vs. base64 Anthropic ImageBlocks).
 *
 * History (history.ts) deliberately does NOT use this: it reflows a parallel role-slot string
 * in lockstep with the text and renders with `colorByRole`, which code export has no concept
 * of — wiring slots through this public surface would bloat it for one internal caller. It
 * still shares the underlying `reflow()` + `renderTextToPngsWithCharLimit` primitives.
 */
export declare function renderDensePages(text: string, opts?: RenderDensePagesOptions): Promise<RenderedImage[]>;
//# sourceMappingURL=render.d.ts.map