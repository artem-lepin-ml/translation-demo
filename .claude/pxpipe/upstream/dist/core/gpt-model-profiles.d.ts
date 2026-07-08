/**
 * Per-model GPT rendering + vision-cost profiles.
 *
 * One place to retune when a new model ships with different image tokenization,
 * a different downscale threshold (max safe portrait-strip width), or a different
 * max image height. Every built-in profile is BEHAVIOR-IDENTICAL to the old
 * hardcoded `resolveVisionCost` + `GPT_STRIP_COLS` + `MAX_HEIGHT_PX`, so existing
 * cost numbers (1190 / 1445 / 2372 / 1464 / 630 …) are unchanged.
 *
 * Retune without a code change via the PXPIPE_GPT_PROFILES env var (JSON map of
 * model-id PREFIX -> partial profile; longest matching prefix wins, checked
 * BEFORE the built-in table). Partial fields fall back to the built-in match, so
 * you can override just one knob:
 *
 *   PXPIPE_GPT_PROFILES='{"gpt-5.6":{"vision":{"regime":"patch","multiplier":1,"patchCap":12000},"stripCols":200,"maxHeightPx":2400}}'
 *   PXPIPE_GPT_PROFILES='{"gpt-5.6":{"stripCols":176}}'   # widen only
 */
/**
 * GPT strip height, DECOUPLED from render.ts's MAX_HEIGHT_PX (which is Anthropic's
 * 1568-edge / ~1.15 MP clamp). OpenAI's pre-tokenize resize is different: fit within
 * 2048×2048, then shortest side → 768. A 768-px-wide portrait strip up to 2048 px tall
 * survives un-resampled, so GPT keeps the taller page. Every built-in cost number below
 * (1190 / 1445 / 2372 / 1464 / 630 …) was calibrated at this height — do not re-link to
 * the Anthropic constant.
 */
export declare const GPT_MAX_HEIGHT_PX = 1932;
/** Image-token cost model (mirrors OpenAI's mandatory pre-tokenize resize). */
export type GptVisionCost = {
    regime: 'tile';
    base: number;
    perTile: number;
} | {
    regime: 'patch';
    multiplier: number;
    patchCap: number;
};
export interface GptModelProfile {
    /** How OpenAI bills the rendered images as input tokens. */
    vision: GptVisionCost;
    /** Max portrait-strip width in COLUMNS before the API downscales (destroying
     *  5px glyphs). 152 cols x 5px + 8px pad = 768px = OpenAI's shortest-side floor. */
    stripCols: number;
    /** Max rendered image height in px. Threaded into the renderer so the gate's
     *  cost estimate and the actual page split agree. */
    maxHeightPx: number;
}
/** Default downscale-safe strip width (768px). Exported as the global cols default. */
export declare const DEFAULT_GPT_STRIP_COLS = 152;
/**
 * Conservative fallback for unrecognized models: tile 85/170 over-states cost,
 * which biases the gate toward pass-through (safe). Matches gpt-4o/4.1/4.5.
 */
export declare const DEFAULT_GPT_PROFILE: GptModelProfile;
/**
 * Resolve the full rendering + vision-cost profile for a model id. Env overrides
 * (longest matching prefix) win over the built-in table; unknown models get the
 * conservative `DEFAULT_GPT_PROFILE`.
 */
export declare function resolveGptProfile(model: string | null | undefined): GptModelProfile;
//# sourceMappingURL=gpt-model-profiles.d.ts.map