/**
 * Runtime-agnostic event sink for pxpipe.
 * Per-request JSONL record — same shape on Node (file) and Workers (console.log).
 * Never emits raw text; only sizes, counts, durations, env fields, and sha256 prefixes.
 */
import type { ProxyEvent } from './proxy.js';
/** Flat record persisted per request. Adding a field is non-breaking for readers. */
export interface TrackEvent {
    ts: string;
    method: string;
    path: string;
    /** Top-level request model when present. */
    model?: string;
    status: number;
    duration_ms: number;
    first_byte_ms?: number;
    compressed?: boolean;
    reason?: string;
    orig_chars?: number;
    /** Text-chars replaced by image blocks (slab + reminders + tool_results).
     *  Compare with image_count: textTokens(n/4) vs imageTokens(n×2500). */
    compressed_chars?: number;
    image_count?: number;
    image_bytes?: number;
    /** Total pixel area across all rendered images; pairs with cache_create_tokens for px/token regression. */
    image_pixels?: number;
    /** GPT only: vision tokens billed for rendered images. */
    image_tokens?: number;
    /** GPT only: o200k text tokens the imaged/stripped content would have cost. */
    baseline_imaged_tokens?: number;
    /** TEXT chars in the outgoing body (all text blocks, incl. non-compressed tool_results).
     *  With image_pixels, a regression over cold-miss events solves chars_per_token (α) and pixels_per_token (β). */
    outgoing_text_chars?: number;
    static_chars?: number;
    dynamic_chars?: number;
    dynamic_block_count?: number;
    /** Images from compressing <system-reminder> blocks in the first user message. */
    reminder_imgs?: number;
    /** Images from compressing tool_result content. */
    tool_result_imgs?: number;
    /** Chars of tool docs moved to the system-text Tool Reference (not imaged). */
    tool_docs_chars?: number;
    /** tool_result blocks where text exceeded the per-result image budget and was truncated. */
    truncated_tool_results?: number;
    /** Chars elided by paging across all tool_results this request. */
    omitted_chars?: number;
    /** History-image: messages collapsed into the synthetic prepended user message. */
    collapsed_turns?: number;
    /** Total chars serialized into history image(s) before render. */
    collapsed_chars?: number;
    /** PNG blocks emitted for the history; also folded into image_count. */
    collapsed_images?: number;
    /** Why history collapse didn't run (or did). Diagnostic. */
    history_reason?: string;
    /** Codepoints not in the glyph atlas. A spike means users type glyphs we don't ship — widen ATLAS_PROFILE. */
    dropped_chars?: number;
    /** Top-20 dropped codepoints (U+HHHH keys) by frequency. Only present when dropped_chars > 0. */
    dropped_codepoints_top?: Record<string, number>;
    /** Blocks that weren't image-compressed this request; only emitted when at least one counter > 0. */
    passthrough_reasons?: {
        below_threshold?: number;
        not_profitable?: number;
    };
    /** Unrecognized tag names in the static slab — canary for Claude Code releases adding new dynamic tags. */
    unknown_static_tags?: string[];
    /** Slab tags whose content changed within a session — proven per-turn dynamics busting the image cache. */
    churning_static_tags?: string[];
    /** Per-bucket TEXT chars through each gate call site (static_slab, reminder, tool_result_*, history).
     *  Undefined on uncompressed requests; enables per-bucket cpt regression. */
    bucket_chars?: Partial<Record<'static_slab' | 'reminder' | 'tool_result_structured' | 'tool_result_log' | 'tool_result_prose' | 'history', number>>;
    /** TEXT chars that fed the history-image renderer; separate from bucket_chars because it credits a synthetic message. */
    history_text_chars?: number;
    /** sha8 of the collapsed history image. Unchanged across turns proves the prompt cache is hitting (cache_read).
     *  A drifting hash means the collapse boundary is unstable. Absent on no-collapse turns. */
    history_image_sha8?: string;
    /** sha8 of the exact cacheable prefix sent (tools+system+imaged prefix, live
     *  tail excluded). Changes turn-over-turn within a session ⇒ pxpipe-side cache
     *  bust; stable while cache_create spikes ⇒ upstream eviction. See #11. */
    cache_prefix_sha8?: string;
    /** Approx chars in that pinned prefix (growth vs pure-invalidation split). */
    cache_prefix_bytes?: number;
    cwd?: string;
    is_git_repo?: boolean;
    git_branch?: string;
    platform?: string;
    os_version?: string;
    today?: string;
    system_sha8?: string;
    claude_md_sha8?: string;
    first_user_sha8?: string;
    input_tokens?: number;
    output_tokens?: number;
    cache_create_tokens?: number;
    cache_read_tokens?: number;
    /** OpenAI prompt-cache hits (subset of input_tokens), from input/prompt_tokens_details.cached_tokens. */
    cached_tokens?: number;
    /** Cache_create split by tier — 1.25x (5-min) and 2x (1-hour) input rates.
     *  Their sum equals `cache_create_tokens` when both fields are present. */
    cache_create_5m_tokens?: number;
    cache_create_1h_tokens?: number;
    /** Server-side web search calls billed per-request (not per-token). */
    web_search_requests?: number;
    /** Model stop reason ("end_turn", "tool_use", "max_tokens", "refusal", …).
     *  OpenAI finish_reason ("stop", "length", "content_filter", …) lands in the same field. */
    stop_reason?: string;
    /** True when the stop reason indicates a safety classifier fired ("refusal" /
     *  "content_filter"). Refusal rows emit almost no output and would otherwise
     *  read as "cheap" — scorers MUST fail cost comparisons on these rows, and a
     *  cluster of them after a transform change means the imaged prompt itself is
     *  tripping the classifier (see transform.ts reasoning_extraction notes). */
    safety_flagged?: boolean;
    /** Ground-truth output chars measured by streaming the response body ourselves — independent of
     *  usage.output_tokens. redacted_block_count_measured counts opaque server-encrypted blocks;
     *  dashboard applies a low/mid/high estimate for those. Absent on non-scannable responses. */
    text_chars_measured?: number;
    thinking_chars_measured?: number;
    tool_use_chars_measured?: number;
    redacted_block_count_measured?: number;
    /** count_tokens on the ORIGINAL body (free endpoint). Absent on probe failure; excluded from savings rollup. */
    baseline_tokens?: number;
    /** count_tokens on the original body truncated at the last cache_control marker — gives cacheable_prefix_tokens.
     *  With baseline_tokens, decomposes unproxied cost into (cacheable_prefix, cold_tail). Absent when no markers. */
    baseline_cacheable_tokens?: number;
    /** Probe outcome. Dashboards must only attribute "$ saved" to rows where status === 'ok'. */
    baseline_probe_status?: 'ok' | 'partial' | 'failed';
    error?: string;
    /** First ~2 KiB of the upstream 4xx response body. */
    error_body?: string;
    /** sha256[0..8] of the TRANSFORMED outgoing body — correlates payloads without persisting them. */
    req_body_sha8?: string;
    /** Gzipped+base64 TRANSFORMED body for 4xx, inlined when ≤ TRACK_BODY_INLINE_MAX. Node host writes sidecar for larger bodies. */
    req_body_sample_b64?: string;
    /** Node host only: path to gzipped sidecar when inline cap exceeded. Workers drop oversized samples. */
    req_body_sample_path?: string;
}
/** Max inline base64 body per JSONL row (32 KiB). Larger goes to sidecar (Node) or is dropped (Workers). */
export declare const TRACK_BODY_INLINE_MAX: number;
/** Hosts implement this to persist events. */
export interface Tracker {
    emit(ev: TrackEvent): void | Promise<void>;
    /** Optional: flush any buffered writes (file rotation, etc.). */
    flush?(): void | Promise<void>;
}
/** Convert a ProxyEvent to its flat persisted shape. Shared in core so Node/Worker hosts stay in sync. */
export declare function toTrackEvent(ev: ProxyEvent): TrackEvent;
/** Writes one JSON line per event. Worker host uses console.log; Node host uses a file-backed variant. */
export declare class JsonLogTracker implements Tracker {
    private readonly sink;
    constructor(sink?: (line: string) => void);
    emit(ev: TrackEvent): void;
}
/** Tracker that drops everything. Used when PXPIPE_TRACK=0. */
export declare const noopTracker: Tracker;
//# sourceMappingURL=tracker.d.ts.map