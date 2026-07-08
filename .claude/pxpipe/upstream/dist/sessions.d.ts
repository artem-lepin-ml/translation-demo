/**
 * Shared data layer for the dashboard's session views. Node-only (filesystem
 * I/O) — never imported from `src/core/`.
 *
 * ## Why we group by first_user_sha8 (Path B)
 *
 * Every TrackEvent carries `first_user_sha8` (see src/core/tracker.ts), an
 * sha256 prefix of the conversation's first user message. Within a single
 * Claude Code session that hash is stable across every turn; across two
 * different sessions it is virtually never the same. That makes it a
 * better-than-good-enough session key without coupling pxpipe to Claude
 * Code's internal file layout for *correctness*.
 *
 * We *do* read `~/.claude/projects/` opportunistically (see `claudeCodeMap`)
 * to enrich the dashboard with real Claude Code session IDs + project
 * paths — but it's best-effort: missing or unreadable files just leave the
 * synthetic ID standing alone.
 *
 * ## File layout we manage
 *
 * - `~/.pxpipe/events.jsonl` — append-only JSONL written by FileTracker
 * - `~/.pxpipe/4xx-bodies/${iso-ts}-${sha8}.json.gz` — gzipped failure
 *   bodies referenced from JSONL rows via `req_body_sample_path`
 */
import type { TrackEvent } from './core/tracker.js';
export interface SessionSummary {
    /** The synthetic session ID = first_user_sha8 (or '<unknown>' if missing). */
    id: string;
    /** Working directory of the first event in the session, if any. */
    project: string | undefined;
    /** ISO timestamp of the first event we saw for this session. */
    firstSeen: string;
    /** ISO timestamp of the last event we saw for this session. */
    lastSeen: string;
    /** Number of events recorded against this session. */
    requestCount: number;
    /** `tokensSavedEst × 4` — a coarse byte-equivalent of the token savings,
     *  useful only as a rough "we shaved X kB off the wire" callout. Not
     *  load-bearing math; the real number is `tokensSavedEst`. */
    charsSaved: number;
    /** Real input-side tokens saved: sum of `baseline_tokens − (input +
     *  cache_create×1.25 + cache_read×0.10)` across events that carry both
     *  a /v1/messages/count_tokens probe and an upstream usage block.
     *  Events missing either side contribute to requestCount but not here.
     *  No estimation — can go negative when a compression net-lost. */
    tokensSavedEst: number;
    /** Sum of cache_read_input_tokens — actual prompt-cache hits. */
    cacheReadTokens: number;
    /** Bytes attributable to this session in events.jsonl (sum of line lengths
     *  including the trailing newline). */
    jsonlBytes: number;
    /** Bytes attributable to this session in 4xx-bodies/ sidecars. */
    sidecarBytes: number;
}
export interface DiskUsage {
    eventsJsonlBytes: number;
    sidecarsBytes: number;
    sidecarCount: number;
    totalBytes: number;
}
/** Resolved paths a sessions invocation will touch. Single source of truth so
 *  tests can point the whole module at a tmpdir. */
export interface SessionsPaths {
    eventsFile: string;
    sidecarDir: string;
}
export declare function defaultPaths(): SessionsPaths;
/** Lazily stream events.jsonl line by line. Yields parsed TrackEvents plus
 *  the raw line (we need byte length for jsonlBytes accounting). Malformed
 *  lines are silently dropped — matches `pxpipe stats` behavior. */
export declare function readEvents(eventsFile: string): AsyncGenerator<{
    ev: TrackEvent;
    rawBytes: number;
}>;
export declare const UNKNOWN_SESSION = "<unknown>";
export interface AggregateResult {
    sessions: Map<string, SessionSummary>;
    /** sessionId -> set of absolute sidecar paths referenced by its events. */
    sidecarsBySession: Map<string, Set<string>>;
}
/** Build a map of sessionId -> SessionSummary by scanning every event. Also
 *  tracks which sidecars belong to which session so prune can clean them. */
export declare function aggregateSessions(paths: SessionsPaths): Promise<AggregateResult>;
export interface ListOptions {
    /** Substring or basename match against `cwd`. */
    project?: string;
    /** ISO timestamp; only sessions whose lastSeen >= since survive. */
    since?: string;
}
/** Sort SessionSummary entries most-recent-first and apply optional filters.
 *  Pure: the dashboard maps query-string params straight into ListOptions. */
export declare function filterSessions(sessions: Map<string, SessionSummary>, opts: ListOptions): SessionSummary[];
export interface PruneOptions {
    /** Drop sessions whose lastSeen is older than N days. */
    olderThanDays?: number;
    /** Keep only the N most-recently-active sessions. */
    keepLast?: number;
    /** Drop a single session by ID. */
    sessionId?: string;
    /** Drop multiple sessions in one atomic pass — bulk-delete from the
     *  dashboard's checkbox UI. Unknown IDs are silently ignored (the
     *  caller may have raced a concurrent prune). Coexists with
     *  `sessionId` (single) — both contribute to the removal set. */
    sessionIds?: string[];
    /** When true, actually delete. When false (the default), report only. */
    force: boolean;
}
export interface PruneReport {
    sessionsRemoved: string[];
    eventsRemoved: number;
    eventsKept: number;
    jsonlBytesFreed: number;
    sidecarsRemoved: number;
    sidecarBytesFreed: number;
    /** True when this was a real run (force=true). False for dry-run. */
    applied: boolean;
}
/** Decide which sessions to remove based on the prune options. Pure — no
 *  I/O — so it's easy to unit-test against a synthetic aggregation. */
export declare function selectSessionsToRemove(sessions: Map<string, SessionSummary>, opts: PruneOptions, now?: Date): Set<string>;
/**
 * Rewrite events.jsonl with rows from `toRemove` sessions stripped out, and
 * delete the matching 4xx-body sidecars. Atomic: writes to a sibling `.tmp`
 * file with fsync, then renames over the original.
 *
 * Concurrency note: if the live proxy appends during prune, those new lines
 * will be lost (the proxy holds an fd to the pre-rename inode and keeps
 * writing to it). For a single-user dev tool that's an acceptable tradeoff;
 * the dashboard's confirm dialog warns the user before the destructive op.
 */
export declare function prune(paths: SessionsPaths, opts: PruneOptions, now?: Date): Promise<PruneReport>;
export declare function diskUsage(paths: SessionsPaths): DiskUsage;
export interface ClaudeCodeSessionRef {
    /** The Claude Code session ID (file basename without .jsonl). */
    sessionId: string;
    /** The decoded project path. Encoded form: `-Users-me-code-foo` →
     *  `/Users/me/code/foo`. Best-effort: dashes in actual path segments
     *  (e.g. `my-project`) round-trip as slashes, so this is for display
     *  only — don't `fs.existsSync` against it. */
    projectPath: string;
    /** First user message text, truncated for display. */
    firstUserPreview: string;
}
/** Path where Claude Code stores per-session JSONL transcripts. */
export declare function claudeProjectsDir(): string;
/**
 * Compute the sha256 prefix the proxy uses for `first_user_sha8` (see
 * src/core/transform.ts:firstUserText + sha8). Crucially this must match
 * exactly — same 4 KiB cap, same first-8-hex-char prefix — or the map will
 * silently miss every entry.
 */
export declare function fingerprintFirstUser(text: string): string;
/** Pull the first user message text out of a single Claude Code session
 *  JSONL file. Walks the file line by line and stops at the first row with
 *  `type === 'user'` that has parseable user content. */
export declare function readFirstUserFromClaudeSession(filePath: string): Promise<string | undefined>;
/** Convert Claude Code's project directory encoding back to a path. The
 *  encoding is lossy (every `/`, `_`, and original `-` all become `-` in the
 *  directory name) so this is display-only. */
export declare function decodeClaudeProjectDir(name: string): string;
/**
 * Best-effort scan of `~/.claude/projects/*.jsonl`. Returns a map keyed by
 * the same `first_user_sha8` the proxy emits. If `~/.claude/projects/` is
 * missing, returns an empty map without throwing — pxpipe must keep
 * working for non-Claude-Code clients.
 *
 * This is O(number_of_sessions) file opens. On a heavy user's machine
 * that's a few hundred small reads — well under a second on an SSD. We
 * don't poll continuously; the dashboard re-invokes this on each refresh.
 */
export declare function claudeCodeMap(rootDir?: string): Promise<Map<string, ClaudeCodeSessionRef>>;
//# sourceMappingURL=sessions.d.ts.map