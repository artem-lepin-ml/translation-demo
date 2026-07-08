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
export interface Env {
    /** Optional single upstream base for every API family. Family-specific env vars override it. */
    PXPIPE_UPSTREAM?: string;
    ANTHROPIC_UPSTREAM?: string;
    /** Optional override — if set, replaces whatever x-api-key the client sent. */
    ANTHROPIC_API_KEY?: string;
    OPENAI_UPSTREAM?: string;
    /** Optional override — if set, replaces whatever Authorization the client sent. */
    OPENAI_API_KEY?: string;
    COMPRESS?: string;
    COMPRESS_TOOLS?: string;
    COMPRESS_REMINDERS?: string;
    COMPRESS_TOOL_RESULTS?: string;
    MIN_COMPRESS_CHARS?: string;
    MIN_REMINDER_CHARS?: string;
    MIN_TOOL_RESULT_CHARS?: string;
    COLS?: string;
    /** R2 multi-column packing — default 1 (off). 2 squeezes ~2× source rows
     *  per image; OCR-verify before flipping in production. */
    MULTI_COL?: string;
    /** When "0" / "false", disable per-request event JSON logs. Default-on.
     *  Cloudflare ingests console.log as Workers Logs; pipe via Logpush to
     *  R2/S3 for the same JSONL shape Node writes to disk. */
    PXPIPE_TRACK?: string;
    /** Shared secret callers must present via the `x-pxpipe-secret` header
     *  whenever an API-key override is configured. Without this gate a
     *  discovered workers.dev URL is an open key-spender: the Worker would
     *  attach your key to any stranger's request. Set with:
     *    npx wrangler secret put PXPIPE_WORKER_SECRET */
    PXPIPE_WORKER_SECRET?: string;
}
declare const _default: {
    fetch(req: Request, env: Env, _ctx: ExecutionContext): Promise<Response>;
};
export default _default;
//# sourceMappingURL=worker.d.ts.map