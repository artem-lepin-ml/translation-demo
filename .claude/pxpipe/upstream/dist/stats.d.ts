/**
 * Aggregate metrics over a stream of TrackEvents. Pure data-layer module —
 * the dashboard's `/api/stats.json` endpoint imports `aggregateEventsFile`
 * + `summaryToJson` from here. There is no longer a CLI entrypoint; the
 * live dashboard at http://127.0.0.1:47821/ surfaces everything this used
 * to print.
 *
 * Node-only (uses node:fs). Streams the file line-by-line so a 100 MB log
 * doesn't blow the heap. The aggregator itself (`newSummary` / `fold`) is
 * pure — fed a sequence of TrackEvents and produces a Summary — so a
 * Workers-side dashboard could reuse it later by extracting it into core/.
 */
import type { TrackEvent } from './core/tracker.js';
export interface Summary {
    total: number;
    ok2xx: number;
    err4xx: number;
    err5xx: number;
    compressed: number;
    passthrough: number;
    /** Sum of orig_chars across compressed requests — the bytes we removed
     *  from the text path by rendering to PNG. */
    origCharsTotal: number;
    imageBytesTotal: number;
    /** Aggregated Anthropic token usage. */
    inputTokensTotal: number;
    outputTokensTotal: number;
    cacheCreateTokensTotal: number;
    cacheReadTokensTotal: number;
    /** Number of events whose cache_read_tokens > 0 — i.e. the prompt cache
     *  actually hit. */
    cacheHitEvents: number;
    /** Number of events that carried any usage data at all. Denominator for
     *  cacheHitEvents. */
    eventsWithUsage: number;
    durationMs: number[];
    firstByteMs: number[];
    skipReasons: Map<string, number>;
    byCwd: Map<string, {
        count: number;
        origChars: number;
        imageBytes: number;
    }>;
    /** system_sha8 → number of times seen. High repeat count = cache should
     *  be doing its job. */
    systemShaHist: Map<string, number>;
    unknownTags: Map<string, number>;
}
export declare function newSummary(): Summary;
export declare function fold(s: Summary, ev: TrackEvent): Summary;
export declare function renderTextReport(s: Summary): string;
/**
 * Stream an events JSONL file and fold every row into a Summary. Returns the
 * Summary plus a parsed/dropped tally so callers can detect empty/garbage
 * inputs. The dashboard wraps this for the /api/stats.json endpoint.
 *
 * Note: this is a full re-read on every call. The dashboard already has a
 * 50-event ring buffer of the *recent* slice; stats need the full history
 * to compute cache-hit-rate over thousands of requests. ~1.5 MB JSONL
 * streams in well under 100 ms on an SSD.
 */
export declare function aggregateEventsFile(file: string): Promise<{
    summary: Summary;
    parsed: number;
    dropped: number;
} | undefined>;
/**
 * Convert a Summary to a JSON-serializable shape for the dashboard's
 * /api/stats.json endpoint. JSON.stringify drops Map entries silently, so
 * we materialize the top-N entries of each map into plain [key, value]
 * tuples. Caps each map at 20 entries to keep the response bounded.
 */
export declare function summaryToJson(s: Summary): Record<string, unknown>;
//# sourceMappingURL=stats.d.ts.map