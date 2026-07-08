/**
 * GPT history-image compression.
 *
 * The static system+tool slab is small (~30k chars); the bulk of a GPT agent
 * request is the conversation transcript, which OpenCode resends in full every
 * turn — the Responses API is driven statelessly here (no `previous_response_id`),
 * so turns 1..N-1 are re-sent as plain text on turn N. pxpipe collapses the OLD
 * closed-tool-call prefix of that transcript into 1-N PNG images and keeps the
 * recent tail as text.
 *
 * OpenAI prompt-caching is automatic and prefix-based: no `cache_control`
 * breakpoints, no 1.25× write premium, cached reads at ~0.1×. The collapse
 * boundary is snapped to a chunk grid so the history image stays byte-identical
 * across turns and keeps hitting that automatic cache (the same flap-avoidance
 * trick src/core/history.ts uses for Anthropic).
 *
 * This mirrors src/core/history.ts but operates on Responses `input` items and
 * Chat `messages` rather than Anthropic Message blocks. The two formats differ
 * enough (function_call/function_call_output vs tool_calls/tool role) that a
 * shared block type isn't worth it; instead each format is lowered to a common
 * HistoryTurn list and the planner/renderer are shared.
 */
import { type RenderedImage } from './render.js';
/** Break-even gate predicate, injected to avoid a circular import with openai.ts.
 *  Receives the full string (not length) so the renderer's row-aware image-count
 *  estimate sees real newlines — history text is newline-heavy. */
export type GptProfitableFn = (text: string, cols: number) => boolean;
export interface GptHistoryOptions {
    /** Trailing items kept as live text (never collapsed). */
    keepTail: number;
    /** Minimum collapsible items in [protectedPrefix..boundary]; below this the
     *  cache-amortization math doesn't pay (imaging a tiny prefix is net cost). */
    minCollapsePrefix: number;
    /** Minimum collapsed-text size in o200k TOKENS (not chars). OpenAI caches the
     *  text transcript at ~0.1× already and bills images by vision tokens, so the
     *  break-even is a token comparison — 8000 chars of dense JSON tokenizes very
     *  differently from 8000 chars of prose. Below this, imaging a tiny prefix is
     *  net cost. */
    minCollapseTokens: number;
    /** Soft-wrap columns for the dense renderer. */
    cols: number;
    /** Advance the collapse boundary in steps of this many items so the rendered
     *  PNG stays byte-identical across turns and keeps hitting the prompt cache.
     *  0 = per-item moving boundary (cache-hostile; tests only). */
    collapseChunk: number;
    /** Render the collapse range as independent image chunks of this many turns on
     *  an ABSOLUTE grid anchored at protectedPrefix. A completed chunk's bytes are
     *  fixed by its turn range alone, so old chunks stay byte-identical (cache_read
     *  forever) as the conversation grows — only the newest partial chunk
     *  re-renders. 0 = render the whole range as one blob (legacy, non-append-only). */
    freezeChunk: number;
    /** Target size of one frozen image SECTION, in o200k tokens. The collapse range
     *  is cut into sections by walking turns from protectedPrefix and sealing a
     *  section each time its cumulative token count crosses this target. A sealed
     *  section's bytes are a pure function of its turn range (independent of where
     *  the conversation currently ends), so it stays byte-identical — and OpenAI
     *  prefix-cache-hits — as the conversation grows. Leftover tail turns that don't
     *  fill a whole section are left UNCOLLAPSED (live text) until they do. Chosen so
     *  each section renders to roughly one ≤6000px image, well under gpt-5.x's
     *  10,000-patch `detail:original` budget. Turn size, not turn count, drives this. */
    sectionTokens: number;
    /** Max rendered image height in px (per-model; from the GPT profile). Threaded
     *  into renderTextToPngs so history pages split at the same height the gate prices. */
    maxHeightPx: number;
    /** Hard cap on GPT history image count. This is a TRUE cap, not a threshold:
     *  collapse the oldest completed sections until the next section would exceed
     *  the cap, then leave the remaining history as ordinary text. Prevents 80+
     *  image gpt-5.5 requests without dropping context or live tool state. */
    maxImages: number;
    /** Reflow the transcript before rendering: pack soft-wrapped lines and mark
     *  every hard newline with the ↵ sentinel — same treatment as the static
     *  slab. History text is newline-heavy (role headers, JSON args), so without
     *  this each short line wastes a full render row and no ↵ marker appears.
     *  The returned `text` (o200k baseline + cache byte-stability) stays the
     *  ORIGINAL, un-reflowed transcript. */
    reflow: boolean;
}
export declare const GPT_HISTORY_DEFAULTS: GptHistoryOptions;
/** One conversation item lowered to a renderable unit. */
export interface HistoryTurn {
    /** Serialized text (with role header / tool markers). Empty = skip (e.g. reasoning). */
    text: string;
    /** Tool-call ids this item opens (function_call / assistant tool_calls). */
    openIds: string[];
    /** Tool-call ids this item closes (function_call_output / tool message). */
    closeIds: string[];
    /** Item we can't safely serialize (unknown kind, item_reference) — a hard
     *  barrier: never collapse across it, since dropping it could lose state. */
    opaque: boolean;
    /** Raw body when this item is a real USER request (role==='user', not a tool
     *  result). The planner pins the MOST RECENT such turn as legible text instead
     *  of imaging it, so the live ask is never OCR-only. undefined = not a user turn. */
    userText?: string;
}
export interface GptCollapsePlan {
    /** Rendered history images BEFORE the pinned user turn (or ALL images when no
     *  turn was pinned). Empty when no collapse happened. */
    images: RenderedImage[];
    /** Rendered history images AFTER the pinned user turn. Empty unless a pin split
     *  the range. Total imaged = images ∪ imagesAfter. */
    imagesAfter: RenderedImage[];
    /** Raw text of the most-recent user request, kept legible (NOT imaged) and
     *  spliced between `images` and `imagesAfter`. undefined = nothing pinned. */
    pinText?: string;
    /** The collapsed transcript text that was rendered (for o200k token counting). */
    text: string;
    /** Inclusive start index into the original item array. */
    start: number;
    /** Exclusive end index. Caller splices [start, endExclusive) → one synthetic item. */
    endExclusive: number;
    collapsedTurns: number;
    collapsedChars: number;
    reason?: 'prefix_too_short' | 'no_closed_prefix' | 'below_min_tokens' | 'not_profitable' | 'too_many_images' | 'render_empty';
    droppedChars: number;
    droppedCodepoints: Map<number, number>;
}
/**
 * Plan + render a history collapse over pre-lowered turns. Pure w.r.t. the input
 * (caller does the splice and builds the format-specific synthetic item).
 */
export declare function planGptCollapse(turns: HistoryTurn[], protectedPrefix: number, isProfitable: GptProfitableFn, opts?: Partial<GptHistoryOptions>): Promise<GptCollapsePlan>;
export declare function responsesItemsToTurns(items: unknown[]): HistoryTurn[];
export declare function chatMessagesToTurns(messages: unknown[]): HistoryTurn[];
//# sourceMappingURL=openai-history.d.ts.map