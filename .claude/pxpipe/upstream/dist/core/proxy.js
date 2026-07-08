/**
 * pxpipe proxy as a single Web-standard fetch handler.
 * Adapted by src/node.ts and src/worker.ts; uses only Request/Response/URL/fetch.
 */
import { transformRequest } from './transform.js';
import { transformOpenAIChatCompletions, transformOpenAIResponses } from './openai.js';
import { isPxpipeSupportedGptModel, isPxpipeSupportedModel } from './applicability.js';
import { buildBaselineCountTokensBody, buildCacheablePrefixCountTokensBody, } from './measurement.js';
/** Max chars of 4xx error body captured on ProxyEvent — enough for Anthropic's full error JSON. */
const ERROR_BODY_MAX = 2048;
/** Read the top-level `model` field from a /v1/messages body without parsing the full JSON.
 *  Returns null when not found — callers treat null as outside supported scope (fail-closed). */
function readModelField(body) {
    try {
        const head = new TextDecoder().decode(body.subarray(0, 8192));
        const m = /"model"\s*:\s*"([^"]{1,80})"/.exec(head);
        return m ? m[1] : null;
    }
    catch {
        return null;
    }
}
/** Gzip via CompressionStream — available in Node 18+ and Cloudflare Workers. */
async function gzipBytes(body) {
    // Cast: TS doesn't model Response(Uint8Array) even though it works in both runtimes.
    const stream = new Response(body).body.pipeThrough(new CompressionStream('gzip'));
    const buf = await new Response(stream).arrayBuffer();
    return new Uint8Array(buf);
}
/** sha256[0..8] hex of a byte buffer. */
async function sha8Bytes(body) {
    // Cast: Web Crypto accepts Uint8Array at runtime despite the BufferSource type.
    const digest = await crypto.subtle.digest('SHA-256', body);
    const bytes = new Uint8Array(digest);
    let hex = '';
    for (let i = 0; i < 4; i++)
        hex += bytes[i].toString(16).padStart(2, '0');
    return hex;
}
/** Parse one SSE block into the running usage + measurement accumulators. Silent on malformed input. */
function processSseEvent(block, m, state) {
    // Parse `event:` + `data:` lines; continuation data: lines concatenate per SSE spec.
    let event = '';
    let data = '';
    for (const line of block.split('\n')) {
        if (line.startsWith('event:'))
            event = line.slice(6).trim();
        else if (line.startsWith('data:'))
            data += line.slice(5).replace(/^\s/, '');
    }
    if (!data)
        return;
    let j;
    try {
        j = JSON.parse(data);
    }
    catch {
        return;
    }
    const obj = j;
    // OpenAI chunks have no `event:` line; usage only present when stream_options.include_usage is set.
    const openAIUsage = normalizeUsage(obj.usage);
    if (openAIUsage)
        state.usage = openAIUsage;
    // OpenAI Responses API streams usage nested under `response` on the terminal
    // `response.completed` (or `.incomplete`) event — not at the top level.
    if (event === 'response.completed' || event === 'response.incomplete') {
        const resp = obj.response;
        const respUsage = normalizeUsage(resp?.usage);
        if (respUsage)
            state.usage = respUsage;
        // Responses API has no stop_reason; normalize the terminal status/reason instead.
        const reason = resp?.incomplete_details?.reason;
        state.stopReason = typeof reason === 'string' ? reason
            : event === 'response.incomplete' ? 'incomplete' : 'stop';
    }
    measureOpenAIChoices(obj, m);
    // OpenAI chat chunks: the final chunk carries choices[].finish_reason (earlier chunks ship null).
    const choices = obj.choices;
    if (Array.isArray(choices)) {
        for (const c of choices) {
            const fr = c?.finish_reason;
            if (typeof fr === 'string')
                state.stopReason = fr;
        }
    }
    if (event === 'message_start') {
        const msg = obj.message;
        const usage = normalizeUsage(msg?.usage);
        if (usage)
            state.usage = usage;
    }
    else if (event === 'content_block_start') {
        const cb = obj.content_block;
        if (cb?.type === 'redacted_thinking')
            m.redactedBlockCount += 1;
    }
    else if (event === 'content_block_delta') {
        const d = obj.delta;
        if (d?.type === 'text_delta' && typeof d.text === 'string') {
            m.textChars += d.text.length;
        }
        else if (d?.type === 'thinking_delta' && typeof d.thinking === 'string') {
            m.thinkingChars += d.thinking.length;
        }
        else if (d?.type === 'input_json_delta' && typeof d.partial_json === 'string') {
            m.toolUseChars += d.partial_json.length;
        }
    }
    else if (event === 'message_delta') {
        // Anthropic ships the final stop_reason here ("end_turn", "refusal", …).
        const d = obj.delta;
        if (typeof d?.stop_reason === 'string')
            state.stopReason = d.stop_reason;
        // Authoritative final output_tokens; merge over message_start (which ships output_tokens: 1).
        const u = obj.usage;
        if (u) {
            if (!state.usage)
                state.usage = {};
            const cur = state.usage;
            if (typeof u.output_tokens === 'number')
                cur.output_tokens = u.output_tokens;
            if (typeof u.input_tokens === 'number' && cur.input_tokens === undefined) {
                cur.input_tokens = u.input_tokens;
            }
            if (typeof u.cache_creation_input_tokens === 'number') {
                cur.cache_creation_input_tokens = u.cache_creation_input_tokens;
            }
            if (typeof u.cache_read_input_tokens === 'number') {
                cur.cache_read_input_tokens = u.cache_read_input_tokens;
            }
        }
    }
}
function normalizeUsage(raw) {
    if (!raw || typeof raw !== 'object')
        return undefined;
    const u = raw;
    const out = {};
    if (typeof u.input_tokens === 'number')
        out.input_tokens = u.input_tokens;
    if (typeof u.output_tokens === 'number')
        out.output_tokens = u.output_tokens;
    if (typeof u.cache_creation_input_tokens === 'number') {
        out.cache_creation_input_tokens = u.cache_creation_input_tokens;
    }
    if (typeof u.cache_read_input_tokens === 'number') {
        out.cache_read_input_tokens = u.cache_read_input_tokens;
    }
    if (typeof u.cache_creation === 'object' && u.cache_creation !== null) {
        out.cache_creation = u.cache_creation;
    }
    if (typeof u.server_tool_use === 'object' && u.server_tool_use !== null) {
        out.server_tool_use = u.server_tool_use;
    }
    // OpenAI field aliases.
    if (typeof u.prompt_tokens === 'number')
        out.input_tokens = u.prompt_tokens;
    if (typeof u.completion_tokens === 'number')
        out.output_tokens = u.completion_tokens;
    // OpenAI prompt-cache hits live in a details sub-object: Responses uses
    // `input_tokens_details.cached_tokens`, Chat uses `prompt_tokens_details`.
    const details = u.input_tokens_details ??
        u.prompt_tokens_details;
    if (details && typeof details.cached_tokens === 'number') {
        out.cached_tokens = details.cached_tokens;
    }
    return Object.keys(out).length > 0 ? out : undefined;
}
function measureOpenAIChoices(obj, m) {
    const choices = obj.choices;
    if (!Array.isArray(choices))
        return;
    for (const choice of choices) {
        if (!choice || typeof choice !== 'object')
            continue;
        const c = choice;
        const payload = (c.delta ?? c.message);
        if (!payload || typeof payload !== 'object')
            continue;
        if (typeof payload.content === 'string')
            m.textChars += payload.content.length;
        const toolCalls = payload.tool_calls;
        if (Array.isArray(toolCalls)) {
            for (const tc of toolCalls) {
                const fn = tc?.function;
                const args = fn?.arguments;
                if (typeof args === 'string')
                    m.toolUseChars += args.length;
            }
        }
    }
}
/** Measure non-streaming messages.content[] — same OutputMeasurement shape as the SSE accumulator. */
function measureFromMessageJson(j) {
    const m = { textChars: 0, thinkingChars: 0, toolUseChars: 0, redactedBlockCount: 0 };
    if (j && typeof j === 'object')
        measureOpenAIChoices(j, m);
    const content = j?.content;
    if (!Array.isArray(content))
        return m;
    for (const block of content) {
        const b = block;
        if (b?.type === 'text' && typeof b.text === 'string') {
            m.textChars += b.text.length;
        }
        else if (b?.type === 'thinking' && typeof b.thinking === 'string') {
            m.thinkingChars += b.thinking.length;
        }
        else if (b?.type === 'redacted_thinking') {
            m.redactedBlockCount += 1;
        }
        else if (b?.type === 'tool_use') {
            try {
                m.toolUseChars += JSON.stringify(b.input ?? {}).length;
            }
            catch {
                /* circular / unserialisable input — leave the counter as-is */
            }
        }
    }
    return m;
}
/** Stop reason from a non-streaming response JSON: Anthropic `stop_reason`,
 *  OpenAI chat `choices[].finish_reason`, Responses `incomplete_details.reason`. */
function readStopReasonFromJson(j) {
    if (!j || typeof j !== 'object')
        return undefined;
    const obj = j;
    if (typeof obj.stop_reason === 'string')
        return obj.stop_reason;
    if (Array.isArray(obj.choices)) {
        for (const c of obj.choices) {
            const fr = c?.finish_reason;
            if (typeof fr === 'string')
                return fr;
        }
    }
    if (obj.status === 'incomplete') {
        const reason = obj.incomplete_details?.reason;
        return typeof reason === 'string' ? reason : 'incomplete';
    }
    return undefined;
}
/**
 * Tee the response body to extract usage + output measurement without blocking the client.
 * Streams are scanned to EOF (final output_tokens is in message_delta; redacted_thinking
 * blocks can appear anywhere). 4xx bodies are capped at ERROR_BODY_MAX. 5xx is skipped.
 */
function teeForUsage(res) {
    // No body at all: nothing to extract on either path.
    if (!res.body) {
        return {
            response: res,
            usagePromise: Promise.resolve(undefined),
            errorBodyPromise: Promise.resolve(undefined),
            measurementPromise: Promise.resolve(undefined),
            stopReasonPromise: Promise.resolve(undefined),
        };
    }
    // 4xx: tee for the error body but skip usage scanning entirely.
    if (res.status >= 400 && res.status < 500) {
        const [forClient, forUs] = res.body.tee();
        const errorBodyPromise = (async () => {
            const reader = forUs.getReader();
            const decoder = new TextDecoder();
            let out = '';
            try {
                while (out.length < ERROR_BODY_MAX) {
                    const { done, value } = await reader.read();
                    if (done)
                        break;
                    out += decoder.decode(value, { stream: true });
                }
                out += decoder.decode();
                // Drain the rest so the tee buffer doesn't hold the stream open.
                while (true) {
                    const { done } = await reader.read();
                    if (done)
                        break;
                }
            }
            catch {
                /* client may have aborted */
            }
            return out.length > ERROR_BODY_MAX ? out.slice(0, ERROR_BODY_MAX) : out;
        })();
        return {
            response: new Response(forClient, {
                status: res.status,
                statusText: res.statusText,
                headers: res.headers,
            }),
            usagePromise: Promise.resolve(undefined),
            errorBodyPromise,
            measurementPromise: Promise.resolve(undefined),
            stopReasonPromise: Promise.resolve(undefined),
        };
    }
    // 5xx: skip both (the host already synthesizes an error message).
    if (res.status >= 500) {
        return {
            response: res,
            usagePromise: Promise.resolve(undefined),
            errorBodyPromise: Promise.resolve(undefined),
            measurementPromise: Promise.resolve(undefined),
            stopReasonPromise: Promise.resolve(undefined),
        };
    }
    const ct = (res.headers.get('content-type') ?? '').toLowerCase();
    const [forClient, forUs] = res.body.tee();
    // Single read loop resolves all three; exposed as separate promises for call-site readability.
    const scanResult = (async () => {
        const reader = forUs.getReader();
        const decoder = new TextDecoder();
        let buf = '';
        try {
            if (ct.includes('text/event-stream')) {
                // Walk every SSE event to EOF — message_delta (final output_tokens) is last.
                const m = {
                    textChars: 0,
                    thinkingChars: 0,
                    toolUseChars: 0,
                    redactedBlockCount: 0,
                };
                const state = {
                    usage: undefined,
                    stopReason: undefined,
                };
                while (true) {
                    const { done, value } = await reader.read();
                    if (done)
                        break;
                    buf += decoder.decode(value, { stream: true });
                    // SSE events are terminated by a blank line.
                    let evEnd;
                    while ((evEnd = buf.indexOf('\n\n')) >= 0) {
                        const block = buf.slice(0, evEnd);
                        buf = buf.slice(evEnd + 2);
                        processSseEvent(block, m, state);
                    }
                }
                buf += decoder.decode();
                if (buf.trim().length > 0)
                    processSseEvent(buf, m, state); // trailing partial event
                return { usage: state.usage, measurement: m, stopReason: state.stopReason };
            }
            if (ct.includes('application/json')) {
                // Buffer fully, capped at 4 MiB.
                const MAX = 4 * 1024 * 1024;
                while (buf.length < MAX) {
                    const { done, value } = await reader.read();
                    if (done)
                        break;
                    buf += decoder.decode(value, { stream: true });
                }
                try {
                    const j = JSON.parse(buf);
                    return {
                        usage: normalizeUsage(j?.usage),
                        measurement: measureFromMessageJson(j),
                        stopReason: readStopReasonFromJson(j),
                    };
                }
                catch {
                    return { usage: undefined, measurement: undefined, stopReason: undefined };
                }
            }
        }
        catch {
            /* tee released early (client abort) */
        }
        // Unknown content-type: drain to release the tee buffer.
        try {
            while (true) {
                const { done } = await reader.read();
                if (done)
                    break;
            }
        }
        catch {
            /* ignore */
        }
        return { usage: undefined, measurement: undefined, stopReason: undefined };
    })();
    return {
        response: new Response(forClient, {
            status: res.status,
            statusText: res.statusText,
            headers: res.headers,
        }),
        usagePromise: scanResult.then((s) => s.usage),
        errorBodyPromise: Promise.resolve(undefined),
        measurementPromise: scanResult.then((s) => s.measurement),
        stopReasonPromise: scanResult.then((s) => s.stopReason),
    };
}
const DEFAULT_UPSTREAM = 'https://api.anthropic.com';
const DEFAULT_OPENAI_UPSTREAM = 'https://api.openai.com';
/** Headers we strip on the way out — they're hop-by-hop or proxy-injected. */
const STRIP_REQ_HEADERS = new Set([
    'host',
    'connection',
    'keep-alive',
    'proxy-connection',
    'transfer-encoding',
    'upgrade',
    'content-length', // we recompute
    'expect',
    'accept-encoding', // let upstream choose
]);
const STRIP_RES_HEADERS = new Set([
    'connection',
    'keep-alive',
    'transfer-encoding',
    'content-encoding', // we don't re-encode
    'content-length', // body may differ after streaming
]);
function filterHeaders(src, strip) {
    const out = new Headers();
    src.forEach((v, k) => {
        if (!strip.has(k.toLowerCase()))
            out.append(k, v);
    });
    return out;
}
const PASSTHROUGH_PREFIXES = [
    '/anthropic/',
    '/openai/',
    '/google-ai-studio/',
    '/compat/',
];
function isProviderPrefixedPath(pathname) {
    return PASSTHROUGH_PREFIXES.some((prefix) => pathname.startsWith(prefix));
}
function isAnthropicMessagesPath(pathname) {
    return pathname === '/v1/messages'
        || pathname === '/anthropic/v1/messages'
        || pathname === '/anthropic/messages';
}
function isOpenAIChatPath(pathname) {
    return pathname === '/v1/chat/completions' || pathname === '/openai/v1/chat/completions';
}
function isOpenAIResponsesPath(pathname) {
    return pathname === '/v1/responses'
        || pathname === '/openai/v1/responses'
        || pathname === '/openai/responses';
}
function isCanonicalOpenAIPath(pathname, headers, hasOpenAIKey) {
    const isModelsPath = pathname === '/v1/models' || pathname.startsWith('/v1/models/');
    const looksOpenAIAuth = hasOpenAIKey || (headers.has('authorization') && !headers.has('x-api-key'));
    return pathname === '/v1/chat/completions'
        || pathname === '/v1/responses'
        || pathname.startsWith('/v1/responses/')
        || (isModelsPath && looksOpenAIAuth);
}
/** POST /v1/messages/count_tokens with the given body. Returns the upstream's
 *  `input_tokens` number or null on any failure. count_tokens is documented
 *  as a free endpoint (no input-token billing) — we use it once per request
 *  on the PRE-COMPRESSION body to get the ground-truth baseline. Actual
 *  post-compression tokens already come back free in the /v1/messages usage
 *  block (input_tokens + cache_create + cache_read), so no second probe. */
async function countTokensUpstream(countTokensUrl, body, headers) {
    try {
        const res = await fetch(countTokensUrl, {
            method: 'POST',
            headers,
            body: body,
        });
        if (!res.ok)
            return null;
        const json = (await res.json());
        return typeof json.input_tokens === 'number' ? json.input_tokens : null;
    }
    catch {
        return null;
    }
}
/** Resolve upstream URLs from config. Pure — unit-testable. */
export function resolveUpstreams(config) {
    if (config.provider === 'cloudflare-ai-gateway') {
        const base = (config.gatewayBaseUrl ?? '').replace(/\/+$/, '');
        if (!base) {
            throw new Error("provider 'cloudflare-ai-gateway' requires gatewayBaseUrl (PXPIPE_GATEWAY_BASE_URL)");
        }
        return { anthropic: `${base}/anthropic`, openai: `${base}/openai`, stripOpenAIV1: true };
    }
    return {
        anthropic: (config.upstream ?? DEFAULT_UPSTREAM).replace(/\/+$/, ''),
        openai: (config.openAIUpstream ?? DEFAULT_OPENAI_UPSTREAM).replace(/\/+$/, ''),
        stripOpenAIV1: false,
    };
}
/** Parse PXPIPE_GATEWAY_HEADERS — JSON object or `k=v;k2=v2`. */
export function parseGatewayHeaders(spec) {
    if (!spec)
        return {};
    const trimmed = spec.trim();
    if (trimmed.startsWith('{')) {
        const obj = JSON.parse(trimmed);
        const out = {};
        for (const [k, v] of Object.entries(obj))
            out[k] = String(v);
        return out;
    }
    const out = {};
    for (const pair of trimmed.split(';')) {
        const i = pair.indexOf('=');
        if (i <= 0)
            continue;
        out[pair.slice(0, i).trim()] = pair.slice(i + 1).trim();
    }
    return out;
}
/** Build the proxy fetch handler. */
export function createProxy(config = {}) {
    const routes = resolveUpstreams(config);
    const upstream = routes.anthropic;
    const openAIUpstream = routes.openai;
    const passthroughUpstream = config.provider === 'cloudflare-ai-gateway'
        ? (config.gatewayBaseUrl ?? '').replace(/\/+$/, '')
        : upstream;
    const gatewayHeaders = config.gatewayHeaders ?? {};
    const applyGatewayHeaders = (h) => {
        for (const [k, v] of Object.entries(gatewayHeaders))
            h.set(k, v);
        return h;
    };
    return async function handle(req) {
        const t0 = Date.now();
        const url = new URL(req.url);
        const path = url.pathname + url.search;
        // reqBodyBytes: kept for lazy gzip on 4xx. reqBodySha8: computed eagerly for correlation.
        let reqBodyBytes;
        let reqBodySha8;
        const fire = (status, info, error, firstByteMs, usage, errorBody, measurement, stopReason) => {
            const is4xx = status >= 400 && status < 500;
            // Gzip body lazily (only on 4xx). Async IIFE keeps fire() synchronous.
            const finalize = async () => {
                let reqBodyGz;
                if (is4xx && reqBodyBytes && reqBodyBytes.byteLength > 0) {
                    try {
                        reqBodyGz = await gzipBytes(reqBodyBytes);
                    }
                    catch {
                        // Non-fatal — drop body sample.
                    }
                }
                // Await both count_tokens probes so baseline numbers land on the same event row.
                // Each probe is independent; null leaves the field absent and dashboard math degrades cleanly.
                if (info && baselineStatusApplies) {
                    // Track both halves so the dashboard can gate on probe completeness (partial vs ok).
                    // A missing cacheable-prefix probe must NOT be treated as cacheable=0 — that fabricates savings.
                    let baselineResolved = null;
                    let cacheableExpected = false;
                    let cacheableResolved = null;
                    if (baselinePromise) {
                        try {
                            baselineResolved = await baselinePromise;
                            if (baselineResolved !== null)
                                info.baselineTokens = baselineResolved;
                        }
                        catch {
                            /* probe threw — drop */
                        }
                    }
                    if (baselineCacheablePromise) {
                        cacheableExpected = true;
                        try {
                            cacheableResolved = await baselineCacheablePromise;
                            if (cacheableResolved !== null)
                                info.baselineCacheableTokens = cacheableResolved;
                        }
                        catch {
                            /* probe threw */
                        }
                    }
                    if (baselineResolved === null) {
                        info.baselineProbeStatus = 'failed';
                    }
                    else if (cacheableExpected && cacheableResolved === null) {
                        info.baselineProbeStatus = 'partial'; // dashboard excludes row; must not treat as cacheable=0
                    }
                    else {
                        info.baselineProbeStatus = 'ok';
                    }
                }
                await config.onRequest?.({
                    method: req.method,
                    path: url.pathname,
                    model: requestModel,
                    status,
                    durationMs: Date.now() - t0,
                    firstByteMs,
                    info,
                    usage,
                    error,
                    errorBody,
                    reqBodySha8,
                    reqBodyGz,
                    measurement,
                    stopReason,
                });
            };
            void finalize();
        };
        // Transform only known shapes; everything else passes through.
        const providerPrefixed = isProviderPrefixedPath(url.pathname);
        const isMessages = req.method === 'POST' && isAnthropicMessagesPath(url.pathname);
        const isOpenAIChat = req.method === 'POST' && isOpenAIChatPath(url.pathname);
        const isOpenAIResponses = req.method === 'POST' && isOpenAIResponsesPath(url.pathname);
        const isOpenAIPath = isCanonicalOpenAIPath(url.pathname, req.headers, config.openAIApiKey !== undefined);
        const upstreamBase = providerPrefixed ? passthroughUpstream : isOpenAIPath ? openAIUpstream : upstream;
        let bodyOut = null;
        let info;
        let requestModel;
        // Two count_tokens probes on the pre-compression body (see docs/HISTORY_CACHE_MODEL.md):
        //   baselinePromise          → full-body input_tokens
        //   baselineCacheablePromise → input_tokens truncated at last cache_control marker
        // Dashboard combines them for cache-aware baseline. Both run in parallel with the main forward.
        let baselinePromise;
        let baselineCacheablePromise;
        let baselineStatusApplies = false;
        if (isMessages || isOpenAIChat || isOpenAIResponses) {
            const bodyIn = new Uint8Array(await req.arrayBuffer());
            try {
                const transformOpts = typeof config.transform === 'function' ? config.transform() : config.transform;
                // Fail-closed: unreadable model → no compression, not a risky guess.
                const model = readModelField(bodyIn);
                requestModel = model ?? undefined;
                const modelOk = isMessages
                    ? isPxpipeSupportedModel(model)
                    : isPxpipeSupportedGptModel(model);
                // Unsupported model → a true passthrough: no break-even compression
                // (a text-only model may not accept injected image blocks at all).
                const effectiveOpts = modelOk
                    ? transformOpts
                    : { ...transformOpts, compress: false };
                const r = isMessages
                    ? await transformRequest(bodyIn, effectiveOpts)
                    : isOpenAIChat
                        ? await transformOpenAIChatCompletions(bodyIn, effectiveOpts)
                        : await transformOpenAIResponses(bodyIn, effectiveOpts);
                if (!modelOk)
                    r.info.reason = 'unsupported_model';
                bodyOut = r.body; // TS narrows Uint8Array away from BodyInit
                info = r.info;
                reqBodyBytes = r.body;
                if (r.body.byteLength > 0) {
                    reqBodySha8 = await sha8Bytes(r.body);
                }
                if (isMessages) {
                    baselineStatusApplies = true;
                    // Probes fire on the ORIGINAL body before the main forward so all three overlap.
                    // count_tokens is not billed; ~30-80ms latency is hidden by the main forward.
                    const ctBody = buildBaselineCountTokensBody(bodyIn);
                    if (ctBody) {
                        const ctHeaders = applyGatewayHeaders(filterHeaders(req.headers, STRIP_REQ_HEADERS));
                        ctHeaders.set('content-type', 'application/json');
                        if (config.apiKey)
                            ctHeaders.set('x-api-key', config.apiKey);
                        // Mirror the actual outbound request base+path: count_tokens lives at
                        // `<messages-path>/count_tokens`, so provider-prefixed routes like
                        // `/anthropic/messages` probe `/anthropic/messages/count_tokens`.
                        const ctBase = providerPrefixed ? passthroughUpstream : upstream;
                        const ctUrl = ctBase + url.pathname + '/count_tokens';
                        baselinePromise = countTokensUpstream(ctUrl, ctBody, ctHeaders);
                        // Null = no markers → cacheable=0 by definition, no probe needed.
                        const ctCacheableBody = buildCacheablePrefixCountTokensBody(bodyIn);
                        if (ctCacheableBody) {
                            baselineCacheablePromise = countTokensUpstream(ctUrl, ctCacheableBody, new Headers(ctHeaders));
                        }
                    }
                }
            }
            catch (e) {
                fire(502, undefined, `transform_error: ${e.message}`);
                return new Response(JSON.stringify({ error: 'pxpipe transform failed' }), {
                    status: 502,
                    headers: { 'content-type': 'application/json' },
                });
            }
        }
        else {
            bodyOut = req.body; // pass through unchanged
        }
        const outHeaders = filterHeaders(req.headers, STRIP_REQ_HEADERS);
        if (isOpenAIPath) {
            if (config.openAIApiKey)
                outHeaders.set('authorization', `Bearer ${config.openAIApiKey}`);
        }
        else if (config.apiKey && (!providerPrefixed || url.pathname.startsWith('/anthropic/'))) {
            outHeaders.set('x-api-key', config.apiKey);
        }
        applyGatewayHeaders(outHeaders);
        // Gateway OpenAI routes drop the `/v1` prefix; provider-prefixed passthrough
        // routes keep their full path so ocproxy-style upstreams see `/openai/*`,
        // `/google-ai-studio/*`, etc. exactly as the client sent them.
        const outPath = isOpenAIPath && routes.stripOpenAIV1 ? path.replace(/^\/v1(?=\/)/, '') : path;
        const upstreamUrl = upstreamBase + outPath;
        let upstreamRes;
        try {
            upstreamRes = await fetch(upstreamUrl, {
                method: req.method,
                headers: outHeaders,
                body: bodyOut,
                // duplex is required by spec when sending a stream as body
                ...(bodyOut instanceof ReadableStream ? { duplex: 'half' } : {}),
            });
        }
        catch (e) {
            fire(502, info, `upstream_error: ${e.message}`);
            return new Response(JSON.stringify({ error: 'pxpipe upstream unreachable' }), {
                status: 502,
                headers: { 'content-type': 'application/json' },
            });
        }
        const firstByteMs = Date.now() - t0;
        // Tee: client gets one side; scanner reads the other for usage/measurement/error body.
        const { response: teed, usagePromise, errorBodyPromise, measurementPromise, stopReasonPromise } = teeForUsage(upstreamRes);
        // Fire event in background once all four resolve (all share the same stream read).
        void Promise.all([
            usagePromise.catch(() => undefined),
            errorBodyPromise.catch(() => undefined),
            measurementPromise.catch(() => undefined),
            stopReasonPromise.catch(() => undefined),
        ]).then(([usage, errorBody, measurement, stopReason]) => fire(upstreamRes.status, info, undefined, firstByteMs, usage, errorBody, measurement, stopReason));
        return new Response(teed.body, {
            status: upstreamRes.status,
            statusText: upstreamRes.statusText,
            headers: filterHeaders(upstreamRes.headers, STRIP_RES_HEADERS),
        });
    };
}
//# sourceMappingURL=proxy.js.map