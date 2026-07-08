/**
 * History-image compression (Variant C).
 *
 * Collapses the largest closed-tool-sequence prefix into one synthetic user message
 * containing 1-N PNG image blocks. The live tail (keepTail turns + any open tool
 * sequence) stays as text. thinking blocks are dropped from the collapsed range —
 * only the most-recent assistant-with-tool_use must round-trip bit-perfect, and
 * that turn is in the live tail by construction.
 *
 * Synthesized message uses role:'user' because Anthropic forbids image blocks inside
 * role:'assistant'. cache_control placement is left to the caller (transform.ts).
 */
import type { CacheControl, ContentBlock, Message } from './types.js';
/**
 * Banner text blocks that bracket the collapsed-history image(s) in the synthetic
 * user message. Exported as the SINGLE SOURCE OF TRUTH: transform.ts keys its
 * cache-anchor relocation off the intro text, so a literal copy there would
 * silently break relocation whenever this wording changes (it did exactly once —
 * the XML-framing reword left the matcher pointing at the old banner). Both the
 * emitter (here) and the matcher (transform.ts) must reference this constant.
 */
export declare const HISTORY_SYNTHETIC_INTRO = "[Earlier turns of THIS conversation, transcribed in the image(s) below. Each turn is wrapped in <user t=\"N\">...</user> or <assistant t=\"N\">...</assistant> tags, where N is an absolute turn index (larger N = more recent); attribute every turn strictly by its tag, and treat the highest-N turns as the most recent prior context, NOT the low-N opening turns. Earlier turns may contain questions or tasks that were already answered later in this same history; do not reopen low-N turns unless the live text after this block asks you to. This is prior context, NOT the current request.]";
export declare const HISTORY_SYNTHETIC_OUTRO = "[End of earlier conversation. The current request is the live text that follows below.]";
/** Break-even gate predicate. Injected by transform.ts to avoid a circular import.
 *  IMPORTANT: pass the full string, not text.length — the row-aware path in
 *  isCompressionProfitable must see actual newlines to budget images correctly.
 *  History text is newline-heavy (headers, JSON args, labels); chars-only
 *  under-predicts image count ~5-10× and lets net-losers through. */
export type ProfitableFn = (text: string, cols: number) => boolean;
/** Configuration for history collapse. */
export interface HistoryCollapseOptions {
    /** Turns at the tail to keep as text. Default 4. */
    keepTail: number;
    /** Minimum collapsible prefix turns — below this, cache-amortization math doesn't work. Default 10. */
    minCollapsePrefix: number;
    /** Soft-wrap columns for the renderer; should match host cols. Default 100. */
    cols: number;
    /** Advance the collapse boundary in steps of this many messages so the rendered PNG stays
     *  byte-identical for collapseChunk turns and keeps hitting Anthropic's prompt cache.
     *  Set to 0 for a per-turn moving boundary. Default 50. */
    collapseChunk: number;
    /** Append-only freeze granularity, in messages. The collapse range is rendered
     *  as independent image blocks on an ABSOLUTE grid anchored at protectedPrefix,
     *  in steps of this many messages. Each completed chunk's bytes are fixed by its
     *  message range alone, so old chunks stay byte-identical (cache_read forever) as
     *  the conversation grows — only the newest partial chunk re-renders. Caller
     *  cache_control marks force an extra split so a roaming breakpoint stays an
     *  aligned, independently-cacheable image boundary. Set to 0 to render the whole
     *  range as one paginated blob (legacy, non-append-only). Default 10. */
    freezeChunk: number;
    /** Leading messages to never collapse. Protects the slab-bearing first user message
     *  (system-prompt + tool-docs images) so its cache_control anchor stays at the front
     *  and isn't swept into the history image as [image] placeholders. Default 0. */
    protectedPrefix: number;
    /** Reflow the transcript before RENDERING: pack soft-wrapped lines and mark
     *  every hard newline with the ↵ sentinel — same treatment as the static slab.
     *  History text is newline-heavy (role headers, JSON args), so without this
     *  each short line wastes a full render row, inflating image count and shrinking
     *  the savings. Glyph size is unchanged (cols stays the same) so legibility is
     *  identical — it just removes the blank-row waste. `collapsedChars` still
     *  reports the ORIGINAL transcript length. Default true. */
    reflow: boolean;
}
export declare const HISTORY_DEFAULTS: HistoryCollapseOptions;
/** Per-request telemetry surfaced back to TransformInfo. */
export interface HistoryCollapseInfo {
    /** Number of turns collapsed into the history image. */
    collapsedTurns: number;
    /** Total chars of text that went into the history image. */
    collapsedChars: number;
    /** Number of PNG image blocks emitted for the history (≥1 if collapsed). */
    collapsedImages: number;
    /** Total PNG bytes emitted. */
    collapsedImageBytes: number;
    /** Total pixel area (Σ width×height) — pairs with cache_create tokens for px/token regression. */
    collapsedImagePixels: number;
    /** Raw PNG bytes of each emitted history image, in order. Lets the caller register
     *  them into the dashboard image ring (info.imagePngs) so colored history frames are
     *  visible, not merely counted — every other image path already feeds the ring. */
    collapsedPngs: Uint8Array[];
    /** Per-image pixel dims, parallel to collapsedPngs. The dashboard ring reads
     *  info.imageDims in lockstep with info.imagePngs, so these must be pushed together. */
    collapsedImageDims: {
        width: number;
        height: number;
    }[];
    /** Ordinal (0-based, into the emitted history images) of the last byte-stable
     *  history image — the carry-over cache anchor. The relocator pins the cache
     *  breakpoint here so it survives window advances (#11). Undefined when history is
     *  too short to have a fully grid-aligned chunk before collapseLen. */
    carryOverImageOrdinal?: number;
    /** Why we didn't collapse — populated only when no collapse happened. */
    reason?: 'no_history' | 'prefix_too_short' | 'no_closed_prefix' | 'not_profitable' | 'render_empty';
    /** Dropped codepoints from the history render, merged into the
     *  transform-wide map by the caller. */
    droppedChars: number;
    droppedCodepoints: Map<number, number>;
}
/**
 * Return the last index ≤ cutoffExclusive at which all tool_use_ids are matched
 * by tool_results in [0..i]. Returns -1 if no closed boundary exists.
 * Robust to interleaved/parallel tool calls via openSet tracking.
 */
export declare function findClosedPrefixBoundary(messages: Message[], cutoffExclusive: number): number;
export declare function staleFreshnessHints(text: string): string;
/**
 * Linearise content blocks to a single string. Drops thinking blocks (only the
 * most-recent assistant turn needs bit-perfect thinking, and it's in the live tail).
 * Inline images collapse to [image] to avoid double-encoding.
 */
export declare function blocksToText(content: string | ContentBlock[]): string;
/** Return the caller's cache_control marker on a message, if any block carries one.
 *  Used to align freeze-chunk boundaries to roaming breakpoints so a marked segment
 *  stays independently cacheable instead of being silently flattened into the image. */
export declare function messageCacheControl(m: Message): CacheControl | undefined;
/** Serialize messages [fromInclusive..upToExclusive) to a text blob with
 *  `<role>…</role>` XML wrappers. Open+close tags bracket each turn so a misread
 *  boundary self-corrects and the model attributes speakers reliably even off a
 *  lossy image — bare `--- role ---` start-dividers let one role bleed into the
 *  next when a divider is missed. */
export declare function messagesToHistoryText(messages: Message[], upToExclusive: number, fromInclusive?: number): string;
/** Like {@link messagesToHistoryText} but also returns the parallel slot string for
 *  colorByRole: a width-identical copy where each `<role>` tag is replaced by its
 *  role marker and the body is copied verbatim (slot 0). Role attribution is decided
 *  HERE, where the message role is known — never re-parsed out of flattened text.
 *  A tool_result block sits inside its user message and a tool_use block inside its
 *  assistant message, so each is owned by the turn that carries it. */
export declare function messagesToHistorySegments(messages: Message[], upToExclusive: number, fromInclusive?: number): {
    text: string;
    slotText: string;
};
/**
 * Collapse the closed-prefix run into one synthetic user message with 1+ history images.
 * Returns original messages unchanged on any no-collapse path (reason set in info).
 * Image blocks are returned with NO cache_control — caller decides placement.
 */
export declare function collapseHistory(messages: Message[], isProfitable: ProfitableFn, opts?: Partial<HistoryCollapseOptions>): Promise<{
    messages: Message[];
    info: HistoryCollapseInfo;
}>;
//# sourceMappingURL=history.d.ts.map