import type { StatsPayload, RecentPayload, SessionsPayload, FullStatsPayload } from './types.js';
export declare function escapeHtml(s: string | null | undefined): string;
export declare function renderToggleFragment(enabled: boolean): string;
export declare function renderModelsFragment(active: string[], configured: string[], enabled: boolean): string;
export declare function renderSessionSummaryFragment(s: StatsPayload): string;
export declare function renderHeaderFragment(s: StatsPayload, port: number): string;
export interface ContextMapData {
    id: number;
    baselineTokens: number;
    realInput: number;
    baselineInputEff: number;
    actualInputEff: number;
    haveBaseline: boolean;
    cacheRead: number;
    warm: boolean;
    output: number;
    imageCount: number;
    buckets: Partial<Record<string, number>>;
    imageIds: number[];
    compressed: boolean;
    restored?: boolean;
}
/** Image-vs-text breakdown for one request. */
export declare function renderContextMapFragment(c: ContextMapData | undefined, history?: ContextMapData[], notFound?: boolean): string;
export declare function renderRecentFragment(p: RecentPayload): string;
export interface LatestFragmentInput {
    payload: RecentPayload;
    pin: number | null;
    showSource: boolean;
    sourceText: string | null;
}
export declare function renderLatestFragment(inp: LatestFragmentInput): string;
export declare function renderSessionsFragment(p: SessionsPayload): string;
export declare function renderStatsTableFragment(p: FullStatsPayload): string;
export declare function renderPage(port: number): string;
//# sourceMappingURL=fragments.d.ts.map