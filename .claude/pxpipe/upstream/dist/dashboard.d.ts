/**
 * Live dashboard for the Node host. Serves the main HTML page and JSON
 * polling endpoints. All "/api/*.json" endpoints recompute from disk on
 * every request — pxpipe doesn't have a query layer, but a 1.5 MB JSONL
 * streams in well under 100 ms.
 *
 * Legacy live-poll endpoints (left in place, the existing tick() loop uses
 * them):
 *
 *   GET  /, /dashboard               → main HTML page
 *   GET  /proxy-stats                → JSON aggregate over the in-mem ring
 *   GET  /proxy-recent               → JSON ring buffer of recent requests
 *   GET  /proxy-latest-png[?crop=N]  → raw PNG of the latest rendered image
 *
 * Session endpoints (read-only telemetry — no destructive operations):
 *
 *   GET  /api/sessions.json          → grouped sessions (sha8 + project + counts)
 *   GET  /api/stats.json             → full-history aggregate (formerly `pxpipe stats`)
 *
 * Metric formulas and HTML shell originally ported from the Python reference
 * implementation (deleted after live cache-rate validation hit 98.7% by tokens).
 *
 * Node-only by design. Workers host has no dashboard; use Workers Logs.
 *
 * Memory bound: ring buffer cap 50 events + a parallel ring of the last 50
 * rendered PNGs (images are never persisted to disk, so this ring is the
 * only place to view them). At a typical 75 KB PNG that's ~3-4 MB resident;
 * a process restart starts the image ring empty.
 */
import type { ProxyEvent } from './core/proxy.js';
import { type ClaudeCodeSessionRef, type ListOptions, type SessionsPaths } from './sessions.js';
/** One row in the dashboard's "recent requests" table. Compact on purpose —
 *  this lives in memory and gets serialized on every poll.
 *
 *  The "input" numbers (`actual_input`, `baseline_input`) are input-side
 *  only — input + cache_create×1.25 + cache_read×0.10 — because that's
 *  the slice the proxy can move. `output_tokens` is reported separately so
 *  the operator can see what fraction of the bill is unaffected by
 *  compression (and decide whether the headline % makes sense for their
 *  workload). */
export interface RecentRow {
    ts: number;
    method: string;
    path: string;
    model?: string;
    status: number;
    size_in?: number;
    compressed: boolean;
    cc_added?: number;
    input_tokens?: number;
    /** From /v1/messages `usage.output_tokens`. Identical with/without
     *  compression — shown so the operator can see why an output-heavy
     *  turn moves the headline less than a cache-create-heavy one. */
    output_tokens?: number;
    cache_create?: number;
    cache_read?: number;
    /** input + cache_create×1.25 + cache_read×0.10, from the upstream usage
     *  block. Missing when the request 4xx'd or wasn't /v1/messages. */
    actual_input?: number;
    /** /v1/messages/count_tokens(originalBody).input_tokens. Missing when the
     *  side-probe failed or the request body wasn't an Anthropic Messages payload. */
    baseline_input?: number;
    /** How much the running "saved" total moved on this request. */
    session_saved_so_far_delta?: number;
    /** Id of the image rendered for this request, if any — resolves against
     *  the image ring via /proxy-latest-png?id=${img_id}. Absent when the
     *  request rendered no image, or once the image has been evicted from the
     *  ring (the id stays on the row but no longer fetches). */
    img_id?: number;
    img_ids?: number[];
}
/** Per-million-token input rate ASSUMED for the headline dollar figure.
 *  Source: https://docs.claude.com/en/docs/about-claude/pricing — Opus 4.7
 *  input is $5/Mtok (same as Opus 4.5 / 4.6; the previous "$2.50" value
 *  here was a regression). Cache-write 5m = $6.25/Mtok (1.25×),
 *  cache-read = $0.50/Mtok (0.10×).
 *
 *  This is exposed on /proxy-stats as `pricing_assumptions.input_per_mtok`
 *  so the operator can see what we assumed and override if they're
 *  running against a non-default deployment (Bedrock/Vertex add a 10%
 *  premium; Sonnet would be $3/Mtok, etc.).
 *
 *  NOTE: Opus 4.7 uses a different tokenizer than 4.5/4.6 (per
 *  docs.claude.com/en/docs/about-claude/pricing), so even at the same
 *  $/Mtok rate, the same string maps to a different token count. The
 *  honest oracle for "tokens in this body" is `count_tokens` against the
 *  actual target model; do not trust hardcoded chars-per-token or
 *  tokens-per-image constants on 4.7 without verifying against the
 *  upstream probe. */
export declare const ASSUMED_INPUT_USD_PER_MTOK = 10;
export declare class DashboardState {
    private recent;
    /** Per-session dollar-weighted totals, keyed by `info.firstUserSha8`. The
     *  dashboard surfaces ONLY the most-recently-active session via the
     *  `serveCurrentSessionJson` endpoint — older sessions linger in the Map
     *  so a tab refresh during a brief lull still finds the previous session,
     *  but get evicted at `SESSION_CAP` to bound memory in long-running hosts. */
    private sessions;
    /** sha8 of the most-recently-active session id. null when no events have
     *  ever carried a `firstUserSha8` (e.g. a cold start with only passthrough
     *  hits that the upstream probe never tagged). */
    private currentSessionId;
    /** Per-session prior prefix size for the cache-aware TEXT baseline. Warm/cold
     *  comes only from the server-observed cache_read on the actual request; this
     *  map is used only after cr>0 to split the text counterfactual into reused vs
     *  grown prefix tokens. Reconstructed identically in replay() from persisted
     *  timestamps, so live and restored numbers agree. Capped with sessions. */
    private baselineWarmth;
    /** Max age for reusing a prior prefix size after cr>0 has proved warmth. */
    private static readonly CACHE_TTL_SEC;
    /** Hard cap on `sessions` Map entries. Keeps memory bounded in
     *  long-running deployments. 50 sessions × ~13 numeric fields each is
     *  comfortably under a MB even with fat bucket/passthrough histograms. */
    private static readonly SESSION_CAP;
    private totals;
    /** Bounded ring of the most recently rendered images (last IMAGE_RING_CAP).
     *  Each request that rendered an image pushes one entry; the matching
     *  RecentRow carries `img_id` so the dashboard can pull any image still in
     *  the ring via /proxy-latest-png?id=N. In-memory only — images are never
     *  persisted, so a restart starts this empty. */
    private images;
    /** Monotonic image id source. Never reset, never reused — an evicted id
     *  stays dangling on its RecentRow rather than pointing at a new image. */
    private nextImageId;
    /** Runtime kill switch for compression. When false, the proxy forwards
     *  /v1/messages unchanged to upstream — pure passthrough, no images,
     *  no transforms. Controlled by the dashboard "passthrough" toggle so
     *  the operator can toggle the proxy's transform instantly.
     *
     *  Defaults to TRUE since 2026-06-09: scope is Fable 5 only, which reads
     *  renders at 100/100 (no Opus read tax) with the same image billing, and
     *  the live proxy record measured ~68% real input-token savings on dense
     *  traffic — the old off-default rationale ("cache-illusory savings")
     *  cited the superseded dead verdict. Verbatim recall is still lossy;
     *  the dashboard toggle remains the kill switch. See FINDINGS.md. */
    private compressionEnabled;
    /** Recent requests' transform breakdowns, for the Context Map panel + its
     *  history selector. In-memory ring, newest last. */
    private contextHistory;
    setCompressionEnabled(on: boolean): void;
    getCompressionEnabled(): boolean;
    /** Resolved disk paths for the events.jsonl + 4xx-bodies sidecar dir. The
     *  new sessions / cleanup endpoints need this; legacy callers that don't
     *  pass `paths` opt out of those endpoints by returning 503. */
    private readonly paths;
    /** Test hook: when set, /api/sessions.json and /api/sessions/${id}.json
     *  call this instead of `claudeCodeMap()` with the real `~/.claude/projects/`
     *  path. Lets unit tests run in tens of ms instead of scanning hundreds of
     *  the developer's actual Claude Code session files. */
    private readonly ccMapFn;
    constructor(paths?: SessionsPaths, ccMapFn?: () => Promise<Map<string, ClaudeCodeSessionRef>>);
    /** Stash every rendered image into the ring (called from onRequest with the
     *  raw ProxyEvent before info.firstImagePng is dropped by toTrackEvent).
     *  Returns the assigned image ids in render order; empty array when there
     *  are no images. The caller stamps ids[0] onto the RecentRow as `img_id`
     *  for back-compat and the full list as `img_ids`. */
    captureImage(info: NonNullable<ProxyEvent['info']>): number[];
    /** Fold one event into the running totals + ring buffer.
     *
     *  Savings math is gated on a per-request `baseline_tokens` measurement
     *  from the parallel count_tokens probe AND an upstream usage block.
     *  When either is missing, we still count the request but skip its
     *  savings contribution — no estimation. */
    update(ev: ProxyEvent): void;
    /** On startup, fold the last N entries from the JSONL events file back
     *  into the ring buffer so a process restart doesn't show an empty table.
     *  Cumulative totals are *not* restored (the file may have rotated, and
     *  double-counting is worse than starting fresh). */
    replay(filePath: string): Promise<void>;
    /**
     * Per-session "what's happening right now" payload backing the
     * `SessionSummary` panel. Scopes the dollar-weighted savings ratio + the
     * per-bucket char attribution + the passthrough-reason histogram to the
     * most-recently-active session (tracked via `info.firstUserSha8`) so the
     * top-of-dashboard headline reflects the live session rather than stale
     * lifetime aggregates from a previous run.
     *
     * Returns `{ sessionId: null, message: 'no active session yet' }` when no
     * events have been received yet (or the first events were all untagged —
     * cold start, probe failures) — `update()` only sets `currentSessionId`
     * when a `firstUserSha8`-tagged event lands. The client renders a stale
     * panel rather than zeroes when a session goes idle (NO `lastSeen >
     * threshold` check here; see comment in `update()` for the rationale).
     */
    serveCurrentSessionJson(): Response;
    serveStats(): Response;
    serveRecent(): Response;
    /** GET /proxy-latest-png[?id=N] — raw PNG from the image ring. With no id
     *  (or an unknown id) the latest render is returned; ?id=N pulls that
     *  specific image while it's still in the ring. 404 once evicted. */
    servePng(id?: number): Response;
    /** GET /api/image-source[?id=N] — the source text the PNG was rendered
     *  from, so the operator can see the text → image conversion side by side.
     *  Falls back to the latest image; 404 if evicted or text wasn't captured. */
    serveImageSource(id?: number): Response;
    serveHtml(port: number): Response;
    /** GET /fragments/<name> — server-rendered htmx fragments. Each one reuses
     *  the corresponding JSON endpoint's payload (via Response.json()) so the
     *  HTML and JSON surfaces can't drift apart. */
    serveFragment(name: string, url: URL, port: number): Promise<Response>;
    /** GET /api/sessions.json — grouped sessions enriched with the Claude Code
     *  cross-reference. The body is the top-level `sessions` array; the client
     *  renders a bar chart of the top savers. */
    serveSessionsJson(opts?: ListOptions): Promise<Response>;
    /** GET /api/stats.json — full-history aggregate. Migrated from the
     *  former `pxpipe stats` CLI. */
    serveApiStats(): Promise<Response>;
    /** POST /api/compression — flip the runtime kill switch.
     *  Body: { enabled: boolean }. Returns the new state. In-memory only;
     *  restart resets to the default (on). */
    handleCompressionToggle(body: {
        enabled?: unknown;
    }): Response;
    /** POST /fragments/models — add/remove ONE model (Claude or GPT) from the
     *  runtime compress scope. In-memory only; restart resets to the PXPIPE_MODELS
     *  env / built-in default. The model checks read this live. */
    handleModelsToggle(model: string, on: boolean): void;
}
/** Result of route-matching a dashboard URL. The legacy `kind` values
 *  (html/stats/recent/png) stay alongside the `/api/*` JSON endpoints. */
export type DashboardRoute = {
    kind: 'html';
} | {
    kind: 'stats';
} | {
    kind: 'recent';
} | {
    kind: 'png';
} | {
    kind: 'api-sessions';
} | {
    kind: 'api-stats';
} | {
    kind: 'current-session';
} | {
    kind: 'api-compression';
} | {
    kind: 'api-image-source';
} | {
    kind: 'fragment';
    name: string;
};
/** Match dashboard paths (handle query strings on /proxy-latest-png). */
export declare function dashboardPath(pathname: string): DashboardRoute | null;
//# sourceMappingURL=dashboard.d.ts.map