/**
 * pxpipe proxy as a single Web-standard fetch handler.
 * Adapted by src/node.ts and src/worker.ts; uses only Request/Response/URL/fetch.
 */
import { type TransformOptions, type TransformInfo } from './transform.js';
import type { Usage } from './types.js';
export interface ProxyConfig {
    /** 'cloudflare-ai-gateway': routes both families through gatewayBaseUrl;
     *  OpenAI paths drop the `/v1` prefix to match gateway shape. */
    provider?: 'cloudflare-ai-gateway';
    /** Gateway base URL (account/gateway-scoped). Required when provider is set. */
    gatewayBaseUrl?: string;
    /** Extra headers injected on every upstream request (e.g. gateway auth). */
    gatewayHeaders?: Record<string, string>;
    /** Anthropic API base, no trailing slash. Defaults to api.anthropic.com. */
    upstream?: string;
    /** Override or supply an API key. If unset, we forward whatever the client sent. */
    apiKey?: string;
    /** OpenAI API base for GPT chat completions, no trailing slash. */
    openAIUpstream?: string;
    /** Override or supply an OpenAI API key. If unset, we forward Authorization. */
    openAIApiKey?: string;
    /** Pass a function to inject dynamic values per-request (e.g. live charsPerToken);
     *  static object for Workers/tests. */
    transform?: TransformOptions | (() => TransformOptions);
    /** Called after every request — useful for logging / metrics in the host. */
    onRequest?: (event: ProxyEvent) => void | Promise<void>;
}
export interface ProxyEvent {
    method: string;
    path: string;
    /** Top-level request model when present. Used for telemetry/dashboard labels only. */
    model?: string;
    status: number;
    /** Wall-clock ms from request start to event fire (≈ end of upstream body). */
    durationMs: number;
    /** Wall-clock ms from request start to upstream response headers. */
    firstByteMs?: number;
    info?: TransformInfo;
    /** Usage block from Anthropic's response — input/output/cache tokens. */
    usage?: Usage;
    /** Model stop reason from the response ("end_turn", "tool_use", "max_tokens",
     *  "refusal", …). "refusal" = safety classifier fired on the transformed request —
     *  scorers must fail cost comparisons on refusal rows (refusals emit almost no
     *  output and would otherwise look "cheaper"). OpenAI finish_reason ("stop",
     *  "length", "content_filter", …) is normalized into the same field. */
    stopReason?: string;
    error?: string;
    /** First ~2 KiB of the upstream 4xx body (not captured on 2xx or 5xx). */
    errorBody?: string;
    /** sha256[0..8] of the transformed outgoing body — set on every /v1/messages POST for correlation. */
    reqBodySha8?: string;
    /** Gzipped transformed body, populated only on 4xx. Node may write to sidecar (see reqBodySamplePath). */
    reqBodyGz?: Uint8Array;
    /** Set by the Node host instead of reqBodyGz when the body was written to a sidecar file. */
    reqBodySamplePath?: string;
    /** Ground-truth char counts from the response stream, independent of usage.output_tokens.
     *  Absent when the body couldn't be scanned (5xx, unknown content-type). See OutputMeasurement. */
    measurement?: OutputMeasurement;
}
/**
 * Ground-truth char counts from the response stream, independent of usage.output_tokens.
 * redactedBlockCount blocks are opaque server bytes — no char count available for those.
 */
export interface OutputMeasurement {
    textChars: number;
    thinkingChars: number;
    toolUseChars: number;
    redactedBlockCount: number;
}
/** Resolve upstream URLs from config. Pure — unit-testable. */
export declare function resolveUpstreams(config: ProxyConfig): {
    anthropic: string;
    openai: string;
    stripOpenAIV1: boolean;
};
/** Parse PXPIPE_GATEWAY_HEADERS — JSON object or `k=v;k2=v2`. */
export declare function parseGatewayHeaders(spec: string | undefined): Record<string, string>;
/** Build the proxy fetch handler. */
export declare function createProxy(config?: ProxyConfig): (req: Request) => Promise<Response>;
//# sourceMappingURL=proxy.d.ts.map