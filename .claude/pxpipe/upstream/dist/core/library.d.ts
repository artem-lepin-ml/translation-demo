import { type RenderStyle } from './render.js';
import { type TransformInfo, type TransformOptions, type KeepSharpBlock, type RecoverableBlock } from './transform.js';
export type { KeepSharpBlock, RecoverableBlock };
export type BytesLike = Uint8Array | ArrayBuffer | ArrayBufferView;
export interface PxpipeOptions extends Pick<TransformOptions, 'charsPerToken' | 'historyAmortizationHorizon' | 'keepSharp' | 'emitRecoverable'> {
    /** Test/debug-only bypass. Product hosts should prefer their dashboard setting. */
    readonly compress?: boolean;
}
export interface PxpipeTransformInput {
    readonly body: BytesLike;
    /** Resolved upstream model when available; aliases are accepted for applicability checks. */
    readonly model?: string | null;
    readonly requestId?: string;
    readonly options?: PxpipeOptions;
}
export type PxpipeReason = 'applied' | 'unsupported_model' | 'parse_error' | 'below_min_chars' | 'below_min_tokens' | 'not_profitable' | 'compress_disabled' | 'image_limit' | 'transform_error' | 'passthrough';
export interface PxpipeTransformResult {
    readonly body: Uint8Array;
    readonly applied: boolean;
    readonly reason: PxpipeReason;
    readonly detail?: string;
    readonly info: TransformInfo;
    readonly cache: {
        readonly ownsCacheControl: boolean;
        readonly markerCount: number;
    };
}
/**
 * Library wrapper for the Anthropic Messages transformer: model gate, machine-readable
 * reasons, and cache_control ownership flag (prevents hosts stacking a second injector).
 */
export declare function transformAnthropicMessages(input: PxpipeTransformInput): Promise<PxpipeTransformResult>;
export interface RenderTextToImagesOptions {
    /** Wrap-width cap in cols. Default DENSE_CONTENT_COLS (384). */
    readonly cols?: number;
    /** Shrink the canvas to the widest actual line (default true). `false` keeps the
     *  full `cols` width — the proxy's eval-backed full-canvas behavior. */
    readonly shrink?: boolean;
    /** Columns to pack side-by-side. `'auto'` (default) packs as many as fit the width
     *  cap; a number forces that count (clamped to what fits). */
    readonly multiCol?: number | 'auto';
    /** Reflow the text before rendering (minify + join hard newlines with the ↵ sentinel so
     *  short lines pack into full-width rows). This is the proxy's dense history format and is
     *  what `pxpipe export` uses. Default false (raw one-line-per-row). */
    readonly reflow?: boolean;
    /** Max source chars per page. Default DENSE_CONTENT_CHARS_PER_IMAGE. */
    readonly maxCharsPerImage?: number;
    /** Render style. Default DENSE_RENDER_STYLE (bare 5×8 cell, anti-aliased). */
    readonly style?: RenderStyle;
    /** Max page height in px. Default MAX_HEIGHT_PX (728 — Anthropic 1568-edge / ~1.15 MP safe). */
    readonly maxHeightPx?: number;
}
export interface RenderedTextImage {
    readonly png: Uint8Array;
    readonly width: number;
    readonly height: number;
}
export interface RenderTextToImagesResult {
    readonly pages: RenderedTextImage[];
    /** Codepoints absent from the glyph atlas (rendered as blank cells). */
    readonly droppedChars: number;
    /** Σ width×height across all pages. */
    readonly pixels: number;
}
/**
 * Render arbitrary text to dense PNG pages — the public, documented entry for the
 * renderer the proxy uses internally. Sizes a narrow canvas to the content (`shrink`)
 * and packs multiple columns (`multiCol`) so short-line content isn't priced at full
 * width. Returns raw PNG bytes + pixel dimensions, ready to write to disk or wrap in
 * image blocks. This is the surface SDK consumers should use instead of reaching into
 * the internal leaf renderers in `render.ts`.
 */
export declare function renderTextToImages(text: string, opts?: RenderTextToImagesOptions): Promise<RenderTextToImagesResult>;
//# sourceMappingURL=library.d.ts.map