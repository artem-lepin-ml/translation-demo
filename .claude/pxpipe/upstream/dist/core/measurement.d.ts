/**
 * Pure body-shaping utilities for the uncompressed count_tokens counterfactual.
 * No fetch, auth, or Node APIs — hosts supply their own transport.
 */
export interface CountTokensBodies {
    /** Full original body, filtered to count_tokens-accepted fields. */
    readonly fullBody: Uint8Array | null;
    /** Original body truncated at the latest cache_control marker; null when none exists. */
    readonly cacheablePrefixBody: Uint8Array | null;
}
type BytesLike = Uint8Array | ArrayBuffer | ArrayBufferView;
export declare function buildCountTokensBodies(bytes: BytesLike): CountTokensBodies;
export declare function buildBaselineCountTokensBody(bytes: BytesLike): Uint8Array | null;
/** Build a body containing only the longest cacheable prefix (everything up to and including the last
 *  cache_control marker). count_tokens on this body gives cacheable_prefix_tokens.
 *  Walk order (latest-first in cache order): messages → system → tools.
 *  Returns null when no markers exist (cacheable_prefix_tokens = 0). */
export declare function buildCacheablePrefixCountTokensBody(bytes: BytesLike): Uint8Array | null;
/** Count cache_control markers anywhere in an Anthropic Messages body. */
export declare function countCacheControlMarkers(bytes: BytesLike): number;
export {};
//# sourceMappingURL=measurement.d.ts.map