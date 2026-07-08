/**
 * Cloudflare Workers entrypoint. Identical proxy logic to the Node build,
 * just wired up through the Worker `fetch` export.
 *
 * Deploy:
 *   npx wrangler deploy
 *
 * Dev:
 *   npx wrangler dev
 *
 * Config lives in wrangler.toml.
 */
import { createProxy } from './core/proxy.js';
import { toTrackEvent, JsonLogTracker, noopTracker } from './core/tracker.js';
/** Compare SHA-256 digests instead of the raw strings so the comparison
 *  can't leak a prefix-match timing signal. */
async function secretsMatch(a, b) {
    const enc = new TextEncoder();
    const [da, db] = await Promise.all([
        crypto.subtle.digest('SHA-256', enc.encode(a)),
        crypto.subtle.digest('SHA-256', enc.encode(b)),
    ]);
    const va = new Uint8Array(da);
    const vb = new Uint8Array(db);
    let diff = 0;
    for (let i = 0; i < va.length; i++)
        diff |= (va[i] ?? 0) ^ (vb[i] ?? 0);
    return diff === 0;
}
const truthy = (v, fallback) => v == null ? fallback : v === '1' || v.toLowerCase() === 'true';
export default {
    async fetch(req, env, _ctx) {
        // ── Caller auth ────────────────────────────────────────────────────
        // If this deployment injects API keys, never serve anonymous callers:
        // workers.dev URLs are discoverable, and without this gate anyone who
        // finds the URL spends this deployment's API credits.
        if (env.ANTHROPIC_API_KEY || env.OPENAI_API_KEY) {
            if (!env.PXPIPE_WORKER_SECRET) {
                return new Response(JSON.stringify({
                    error: 'refusing to proxy: an API key override is configured but PXPIPE_WORKER_SECRET is not, ' +
                        'which would let anyone who finds this URL spend the configured key. ' +
                        'Run `npx wrangler secret put PXPIPE_WORKER_SECRET` and send the value as the x-pxpipe-secret header.',
                }), { status: 503, headers: { 'content-type': 'application/json' } });
            }
            const presented = req.headers.get('x-pxpipe-secret') ?? '';
            if (!(await secretsMatch(presented, env.PXPIPE_WORKER_SECRET))) {
                return new Response(JSON.stringify({ error: 'missing or invalid x-pxpipe-secret header' }), { status: 401, headers: { 'content-type': 'application/json' } });
            }
            // Don't forward the shared secret upstream.
            req = new Request(req);
            req.headers.delete('x-pxpipe-secret');
        }
        const transform = {
            compress: truthy(env.COMPRESS, true),
            compressTools: truthy(env.COMPRESS_TOOLS, true),
            compressReminders: truthy(env.COMPRESS_REMINDERS, true),
            compressToolResults: truthy(env.COMPRESS_TOOL_RESULTS, true),
            minCompressChars: env.MIN_COMPRESS_CHARS ? Number(env.MIN_COMPRESS_CHARS) : 2000,
            // 500 chars — CPU/latency floor only, not a correctness guard. The
            // No floors — the content-aware `isCompressionProfitable()` gate
            // decides per-block based on actual pixel cost vs text cost. Host
            // can still set a floor via env if they want observability buckets
            // (e.g. MIN_TOOL_RESULT_CHARS=200 to skip absurdly small dumps).
            minReminderChars: env.MIN_REMINDER_CHARS ? Number(env.MIN_REMINDER_CHARS) : 0,
            minToolResultChars: env.MIN_TOOL_RESULT_CHARS ? Number(env.MIN_TOOL_RESULT_CHARS) : 0,
            cols: env.COLS ? Number(env.COLS) : 100,
            // R2 multi-column ON (2 cols) — single-col drops below break-even on
            // real tool-doc slabs. Override via MULTI_COL=1 if OCR misreads layout.
            multiCol: env.MULTI_COL ? Math.max(1, Number(env.MULTI_COL) | 0) : 2,
        };
        const trackingOn = truthy(env.PXPIPE_TRACK, true);
        // Workers Logs ingests stdout as separate log lines. Emit one JSON line
        // per event so downstream (Logpush → R2/S3) reads the same JSONL shape
        // the Node host writes to disk.
        const tracker = trackingOn ? new JsonLogTracker((s) => console.log(s)) : noopTracker;
        const sharedUpstream = env.PXPIPE_UPSTREAM;
        const config = {
            upstream: env.ANTHROPIC_UPSTREAM ?? sharedUpstream ?? 'https://api.anthropic.com',
            apiKey: env.ANTHROPIC_API_KEY,
            openAIUpstream: env.OPENAI_UPSTREAM ?? sharedUpstream ?? 'https://api.openai.com',
            openAIApiKey: env.OPENAI_API_KEY,
            transform,
            onRequest: (e) => {
                // Terse human-readable line (separate from the JSON event below;
                // shows up in `wrangler tail`).
                const tag = e.info?.compressed
                    ? `compressed ${e.info.origChars}ch → ${e.info.imageCount}img/${e.info.imageBytes}B`
                    : (e.info?.reason ?? '');
                const cacheRead = e.usage?.cache_read_input_tokens ?? 0;
                console.log(`${e.method} ${e.path} → ${e.status} (${e.durationMs}ms) ${tag} cache_read=${cacheRead}`);
                if (e.info?.unknownStaticTags && e.info.unknownStaticTags.length > 0) {
                    console.warn(`[pxpipe warn] unknown tag(s) in static slab: ${e.info.unknownStaticTags.join(', ')}`);
                }
                tracker.emit(toTrackEvent(e));
            },
        };
        const handle = createProxy(config);
        return handle(req);
    },
};
//# sourceMappingURL=worker.js.map