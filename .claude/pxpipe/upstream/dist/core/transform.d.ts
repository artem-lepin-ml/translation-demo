/**
 * Request-body transformer. Extracts the static system prompt + tool definitions,
 * renders them as PNG image blocks, and rewrites the body to reference those images —
 * saving 65-73% input tokens while preserving reasoning quality.
 */
import type { ImageBlock, MessagesRequest } from './types.js';
import type { GptHistoryOptions } from './openai-history.js';
/** Per-block descriptor passed to `TransformOptions.keepSharp`. */
export interface KeepSharpBlock {
    /** Which live-region path is asking: `reminder`, `tool_result`, or `tool_result_part`. */
    readonly kind: 'reminder' | 'tool_result' | 'tool_result_part';
    /** The block's text exactly as the caller produced it (pre-render, pre-compaction). */
    readonly text: string;
    /** `tool_use_id` of the owning tool_result, when applicable. */
    readonly toolUseId?: string;
}
/** A block pxpipe rendered to image(s), returned in `TransformInfo.recoverable`
 *  when the caller sets `emitRecoverable`. Lets a stateful harness restore
 *  byte-exact content if the model needs the imaged region verbatim. */
export interface RecoverableBlock {
    /** `rec_` + 8 hex SHA-256 over kind + toolUseId + original text. */
    readonly id: string;
    readonly kind: 'reminder' | 'tool_result' | 'tool_result_part';
    readonly toolUseId?: string;
    /** Original text before compaction/reflow/paging — the bytes to restore. */
    readonly text: string;
    readonly imageCount: number;
}
export interface TransformOptions {
    /** Master switch — false makes this a no-op pass-through. */
    compress?: boolean;
    /** Move tool descriptions into the same image (and stub the originals). */
    compressTools?: boolean;
    /** Compress large `<system-reminder>` text blocks in the first user message. */
    compressReminders?: boolean;
    /** Compress large tool_result text content across all user messages. */
    compressToolResults?: boolean;
    /** Don't compress if total compressible chars below this. */
    minCompressChars?: number;
    /** Per-block threshold for compressReminders (chars). */
    minReminderChars?: number;
    /** Per-block threshold for compressToolResults (chars). */
    minToolResultChars?: number;
    /** Soft-wrap column count. */
    cols?: number;
    /** Hard upper bound on images per tool_result; source text truncated with a paging
     *  marker above this to stay under Anthropic's 100-image/request cap. Default 10. */
    maxImagesPerToolResult?: number;
    /** Pack N text columns side-by-side per image. Default 1. Auto-clamped to stay
     *  under 2000 px wide. OCR ordering risk at N≥2: model must read col 1 top-to-bottom
     *  before col 2. */
    multiCol?: number;
    /** Chars-per-token assumption for `isCompressionProfitable()`. Default 4. */
    charsPerToken?: number;
    /** Multi-turn amortization horizon for the history-collapse gate. N≥2 evaluates as
     *  if N future turns share the prefix (worst-case-warm-image vs best-case-warm-text).
     *  Default 1 (per-turn cold gate). See docs/HISTORY_CACHE_MODEL.md. */
    historyAmortizationHorizon?: number;
    /** Tokens the un-rewritten path would have cache-hit on. Adds a one-time burn
     *  penalty `priorWarmTokens × (CC − CR)` to the image side so the gate accounts
     *  for invalidating a warm text cache. Default 0 (cold-start). ≤0 clamped to 0. */
    priorWarmTokens?: number;
    /** Symmetric counterpart: tokens the image path would have cache-hit on. Adds the
     *  same burn formula to the TEXT side, preventing the gate from flipping out of
     *  image mode when the image prefix is already warm. Default 0. ≤0 clamped to 0. */
    priorWarmImageTokens?: number;
    /** GPT only: collapse the OLD closed-tool-call conversation prefix into history
     *  image(s), keeping the recent tail as text. Independent of the static slab.
     *  Default on. See src/core/openai-history.ts. */
    collapseHistory?: boolean;
    /** GPT only: history-collapse tuning overrides (keepTail / collapseChunk / …). */
    gptHistory?: Partial<GptHistoryOptions>;
    /** Re-pack image-bound text into a ↵-delimited stream to fill `cols` (~29%→75-80%
     *  glyph-fill). ON by default (98.95% char accuracy at L1 OCR eval, +1pp vs baseline).
     *  Hard newlines become visible ↵ glyphs — tell the model via system prompt. */
    reflow?: boolean;
    /** Caller fidelity hint: return `true` for a block that must stay as text (IDs,
     *  hashes, file paths — content where mis-OCR would be silent and wrong). Only
     *  consulted on per-block live-region paths (reminders, tool_results). A throwing
     *  or non-boolean return is treated as `false`. */
    keepSharp?: (block: KeepSharpBlock) => boolean;
    /** When true, populate `TransformInfo.recoverable` with original text + provenance
     *  for every block rendered to images. Off by default (entries inflate `info`;
     *  only a stateful harness can use them). */
    emitRecoverable?: boolean;
}
/** Empirical cpt for the system-slab path (Opus 4.7 tokenizer, N=391, observed 1.91).
 *  Slab-specific because reminders/tool_results have unknown shape; those stay at 4. */
export declare const SLAB_CHARS_PER_TOKEN = 2;
/** Empirical cpt for the history-collapse path (same Opus 4.7 telemetry as SLAB_CHARS_PER_TOKEN).
 *  History is even denser (tool_use JSON dominates), so 2.0 is doubly conservative. */
export declare const HISTORY_CHARS_PER_TOKEN = 2;
/** Chars-per-token for the `pxpipe export` *reporting* estimate (factsheet & savings %).
 *  Less conservative than the gate's CHARS_PER_TOKEN=4: reporting wants an accurate
 *  figure (~3.7 for source/prose text), not a safe-side under-estimate. Single source
 *  of truth — src/core/export.ts imports this rather than redefining it. */
export declare const REPORT_CHARS_PER_TOKEN = 3.7;
/** Anthropic image-billing formula: `tokens ≈ width × height / 750`.
 *  https://docs.anthropic.com/en/docs/build-with-claude/vision#image-tokens
 *  Accurate to ~5% on dense glyph PNGs (N=14 empirical calibration). The renderer
 *  sizes height to content, so per-block images cost far less than full-canvas.
 *  Exported so the export pipeline can reuse the same constant rather than hardcoding. */
export declare const ANTHROPIC_PIXELS_PER_TOKEN = 750;
/** Conservative 10% upward bias on Anthropic image token estimates — keeps the gate
 *  on the safe (pass-through) side when the true cost is near the break-even point.
 *  Exported so the export pipeline reuses the same value. */
export declare const IMAGE_COST_SAFETY_MARGIN = 1.1;
/** Visual rows per image: `floor((MAX_HEIGHT_PX − 2·PAD_Y) / CELL_H)`. Derived
 *  from render.ts constants so break-even math auto-tracks cell geometry changes. */
export declare const LINES_PER_IMAGE: number;
export declare function maxCharsPerImage(cols: number): number;
/** Lossless pre-render whitespace compactor (each `\n` costs ≥1 visual row):
 *  1. Strip trailing whitespace per line (preserves leading indent).
 *  2. Collapse 3+ consecutive newlines to 2. Typically saves 10-25% rows on
 *     markdown/tool-doc slabs, enough to flip borderline gates to profitable. */
export declare function compactSlabWhitespace(text: string): string;
/** Decompose the break-even gate into components for telemetry. Returns the
 *  imageTokens, textTokens, and symmetric burn terms the gate uses internally,
 *  or `null` for empty/non-finite input. */
export declare function evalCompressionProfitability(text: string, cols: number, imageCountCap?: number | undefined, numCols?: number, charsPerToken?: number, priorWarmTokens?: number, priorWarmImageTokens?: number, shrinkWidth?: boolean): {
    imageTokens: number;
    textTokens: number;
    burnImageSide: number;
    burnTextSide: number;
    profitable: boolean;
} | null;
export declare function isCompressionProfitable(text: string, cols?: number, imageCountCap?: number, numCols?: number, charsPerToken?: number, priorWarmTokens?: number, priorWarmImageTokens?: number, shrinkWidth?: boolean, maxCharsPerImage?: number): boolean;
/**
 * Horizon-aware variant of `isCompressionProfitable` for history-collapse.
 *
 * Evaluates expected lifetime cost over N turns: worst-case-warm for image
 * (cache_create turn 1, cache_read turns 2..N) vs best-case-warm for text
 * (cache_read all N). Gate condition: I×(CC + CR×(N-1)) < T×CR×N.
 * Examples: N=5 → I < 0.30×T; N=10 → I < 0.47×T.
 * Falls back to cold per-turn gate when `horizon <= 1`. See docs/HISTORY_CACHE_MODEL.md.
 */
export declare function isCompressionProfitableAmortized(text: string, cols: number, imageCountCap: number | undefined, numCols: number, charsPerToken: number, horizon: number, priorWarmTokens?: number, priorWarmImageTokens?: number, shrinkWidth?: boolean, maxCharsPerImage?: number): boolean;
/** Logical bucket for per-gate-call char attribution. Used by the rolling-cpt
 *  regression to derive per-bucket marginal cpt from production telemetry. */
export type BucketName = 'static_slab' | 'reminder' | 'tool_result_json' | 'tool_result_log' | 'tool_result_prose' | 'history';
/** Pre-compaction TEXT char totals per bucket. Absent when no bucket fired. */
export type BucketChars = Partial<Record<BucketName, number>>;
/** Parsed contents of Claude Code's <env> + git status blocks. All optional —
 *  fields are only populated if the corresponding line is present. */
export interface EnvFields {
    /** Working directory at the time `claude` was launched. */
    cwd?: string;
    isGitRepo?: boolean;
    /** Current git branch, parsed from <git_status> or a "Branch:" line. */
    gitBranch?: string;
    platform?: string;
    osVersion?: string;
    /** "Today's date" as Claude Code reported it (YYYY-MM-DD). */
    today?: string;
}
export interface TransformInfo {
    compressed: boolean;
    reason?: string;
    origChars: number;
    /** Total source chars image-encoded this request (static slab + reminders + tool_results).
     *  Unlike `origChars` (static slab + tool docs only), reflects what `imageCount` replaced. */
    compressedChars: number;
    imageCount: number;
    imageBytes: number;
    /** Σ width×height across all rendered images. Pairs with upstream token count for
     *  empirical px/token regression: `tokens ≈ α·outgoingTextChars + β·imagePixels`. */
    imagePixels?: number;
    /** GPT only. Vision tokens the rendered images actually cost as input
     *  (Σ openAIVisionTokens over real image dims). The "Sent as image" basis. */
    imageTokens?: number;
    /** GPT only. o200k_base text tokens of the content pxpipe imaged/stripped —
     *  the would-have-paid "as plain text" baseline. Compared against imageTokens
     *  for the per-request saving. See src/core/openai-savings.ts. */
    baselineImagedTokens?: number;
    /** Total TEXT chars in the outgoing body (system + messages, excluding image base64).
     *  Denominator for empirical chars-per-token regression on cold-miss events. */
    outgoingTextChars?: number;
    /** Length of the static (cacheable) slab rendered into the image. */
    staticChars: number;
    /** Length of the dynamic (per-turn) slab kept as plain text. */
    dynamicChars: number;
    /** Chars of volatile env/context text relocated from system to the tail of
     *  the last user message (absent when kept in system fallback). */
    envRelocatedChars?: number;
    dynamicBlockCount: number;
    /** Tag-shaped blocks in the static slab not in DYNAMIC_BLOCK_TAGS.
     *  Canary: a new per-turn Claude Code tag would appear here before cache rate collapses. */
    unknownStaticTags?: string[];
    /** Static-slab tags whose content changed within a session — proven dynamic,
     *  busting the image cache each turn. The real alert signal. */
    churningStaticTags?: string[];
    env?: EnvFields;
    /** sha8 of static slab + tool docs (what goes in the image). Repeats across turns → cache hits. */
    systemSha8?: string;
    /** sha8 of the CLAUDE.md section, for bucketing by project when cwd is absent. */
    claudeMdSha8?: string;
    /** sha8 of first user message text (first 4 KiB). Rough thread/session id. */
    firstUserSha8?: string;
    /** Raw bytes of the first rendered image. Dashboard preview only; NOT persisted to JSONL. */
    firstImagePng?: Uint8Array;
    firstImageWidth?: number;
    firstImageHeight?: number;
    /** All rendered PNGs this request. Dashboard only; NOT persisted to JSONL. */
    imagePngs?: Uint8Array[];
    imageDims?: Array<{
        width: number;
        height: number;
    }>;
    /** Source text rendered to images (slab + header), capped at 64 KiB. NOT persisted. */
    imageSourceText?: string;
    reminderImgs?: number;
    toolResultImgs?: number;
    /** Chars of tool docs moved to the system-text Tool Reference (not imaged). */
    toolDocsChars?: number;
    /** Codepoints missing from the atlas (rendered as blank cells). Telemetry for atlas tuning. */
    droppedChars?: number;
    /** Top dropped codepoints by frequency (`U+HHHH` → count), at most 20 entries. */
    droppedCodepointsTop?: Record<string, number>;
    /** Why blocks passed through without compression. Only present when count > 0. */
    passthroughReasons?: {
        below_threshold?: number;
        not_profitable?: number;
        kept_sharp?: number;
    };
    /** Slab gate diagnostics — imageTokens, textTokens, burn terms, and verdict.
     *  Lets hosts measure flap-prevention efficacy and tune amortization horizon. */
    gateEval?: {
        readonly site: 'slab';
        readonly imageTokens: number;
        readonly textTokens: number;
        /** `priorWarmTokens × (CC − CR)` added to image side. */
        readonly burnImageSide: number;
        /** `priorWarmImageTokens × (CC − CR)` added to text side (anti-flapping anchor). */
        readonly burnTextSide: number;
        readonly profitable: boolean;
    };
    /** Pre-compaction TEXT char totals per gate-call bucket. Rolling-cpt regression denominator. */
    bucketChars?: BucketChars;
    /** Chars fed into the history-image renderer. Folded into `bucketChars.history` too. */
    historyTextChars?: number;
    /** Blocks pinned as text by the caller's `keepSharp` predicate this request. */
    keptSharpBlocks?: number;
    /** Imaged live-region blocks with original text + provenance, when `emitRecoverable`. */
    recoverable?: RecoverableBlock[];
    truncatedToolResults?: number;
    omittedChars?: number;
    /** History-collapse: messages collapsed into the synthetic prepended user message. */
    collapsedTurns?: number;
    collapsedChars?: number;
    /** History-collapse images. Also folded into `info.imageCount`. */
    collapsedImages?: number;
    /** sha8 of concatenated history-image base64. Stable across the collapse window →
     *  proves Anthropic's prompt cache can `cache_read` (0.1×) instead of `cache_create`.
     *  A changing hash means cache-key drift is back. Only set when collapse produced images. */
    historyImageSha?: string;
    /** sha8 of the ACTUAL cacheable prefix sent this turn (tools + system +
     *  message blocks through the imaged history/slab boundary; the live tail is
     *  excluded). Read-only measurement. A change turn-over-turn within a session
     *  ⇒ pxpipe serialized different prefix bytes (we busted our own cache,
     *  pxpipe-side); STABLE while cache_create spikes / cache_read collapses ⇒ the
     *  prefix was evicted upstream. Decisive attribution signal (see #11). */
    cachePrefixSha8?: string;
    /** Approx size (chars) of that cached prefix — pairs with cachePrefixSha8 so a
     *  bust reads as growth (size up) vs pure invalidation (size unchanged). */
    cachePrefixBytes?: number;
    /** Why the history collapse didn't run (or did). Diagnostic only. */
    historyReason?: 'no_history' | 'prefix_too_short' | 'no_closed_prefix' | 'below_min_chars' | 'below_min_tokens' | 'not_profitable' | 'too_many_images' | 'render_empty' | 'collapsed';
    /** Token count of the pre-compression body from /v1/messages/count_tokens (free).
     *  Absent when probe failed — event excluded from savings rollup. */
    baselineTokens?: number;
    /** Token count of the pre-compression body truncated at the last cache_control marker.
     *  Absent when the original body has no cache_control markers (cacheable=0 exactly). */
    baselineCacheableTokens?: number;
    /** 'ok': both probes resolved. 'partial': full-body resolved but cacheable-prefix
     *  didn't (exclude from rollup — cacheable=0 fallback is dishonest). 'failed': no
     *  baseline. undefined: no probe attempted. */
    baselineProbeStatus?: 'ok' | 'partial' | 'failed';
}
/** sha256[0..8] hex via Web Crypto (works in Node 18+ and Workers). 32-bit collision-safe. */
export declare function sha8(text: string): Promise<string>;
/** Best-effort extraction of the CLAUDE.md slab from a system text (heuristic).
 *  Returns empty string if nothing CLAUDE.md-shaped is detected. */
export declare function extractClaudeMdSlab(staticText: string): string;
/** First user message text, capped at 4 KiB (stable thread id; hashing large pastes is wasteful). */
export declare function firstUserText(req: MessagesRequest): string;
/** Parse structured fields from the dynamic slab for telemetry. Read-only. */
export declare function extractEnvFields(dynamicText: string): EnvFields;
/** Estimate how many images `text` will render to at the given column width.
 *  Counts soft-wrapped visual rows, which is what render.ts actually budgets
 *  against. Exported for tests + the paging gate.
 *
 *  `numCols` (default 1) packs that many text columns side-by-side per
 *  image — must match the `multiCol` setting wired through to the renderer
 *  for the math to predict the actual image count. */
export declare function estimateImageCount(textOrLen: string | number, cols: number, numCols?: number, maxCharsPerImage?: number): number;
/** Classify content so we can pick a truncation strategy. Cheap heuristics on
 *  the first ~4 KiB. Returns:
 *    - `'structured'`: JSON/YAML/diff markers at the top. Truncate tail.
 *    - `'log'`: ≥30% of lines start with a log level or timestamp. Truncate middle.
 *    - `'other'`: prose, file dumps, etc. Truncate middle.
 *  Exported for tests. */
export declare function classifyContent(text: string): 'structured' | 'log' | 'other';
/** Truncate `text` so it renders to roughly `maxImages` images at the given
 *  `cols`. Picks head/tail split based on `classifyContent`. Budget measured
 *  in visual rows (what render.ts actually slices on). Returns the truncated
 *  text (with paging marker embedded) and the count of chars omitted. If
 *  `text` already fits, returns unchanged with `omittedChars: 0`. Exported
 *  for tests. */
export declare function truncateForBudget(text: string, maxImages: number, cols: number, numCols?: number, maxCharsPerImage?: number): {
    text: string;
    omittedChars: number;
    truncated: boolean;
};
/**
 * Render text → Anthropic image blocks for the proxy. The column-selection rule below
 * (shrink, then single-col unless the content fills the width) is mirrored exactly by
 * the public SDK primitive `renderTextToImages` (library.ts), so the proxy and the
 * `pxpipe export` CLI emit byte-identical PNGs for the same text. Exported so
 * export-proxy-align.test.ts can pin that invariant against the real proxy code.
 */
export declare function textToImageBlocks(text: string, cols: number, numCols?: number, 
/** Shrink canvas to the longest wrapped line. `false` for the slab path
 *  (fills full `cols` for multi-col packing). Default `true`. */
shrinkWidth?: boolean): Promise<{
    blocks: ImageBlock[];
    /** Raw PNG bytes parallel to `blocks` (avoids re-decoding base64 for dashboard). */
    pngs: Uint8Array[];
    /** Pixel dimensions parallel to `pngs`. */
    dims: Array<{
        width: number;
        height: number;
    }>;
    droppedChars: number;
    droppedCodepoints: Map<number, number>;
    /** Σ width×height — caller accumulates into `info.imagePixels` for px/token regression. */
    pixels: number;
}>;
/**
 * Rewrite a Messages API request body. Returns the new body (still JSON
 * bytes) plus diagnostic info. On any error, returns the original bytes
 * unchanged.
 */
export declare function transformRequest(body: Uint8Array, opts?: TransformOptions): Promise<{
    body: Uint8Array;
    info: TransformInfo;
}>;
//# sourceMappingURL=transform.d.ts.map