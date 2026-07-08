/**
 * Cache-aware GPT/OpenAI savings math.
 *
 * This is deliberately separate from src/core/baseline.ts (Anthropic): OpenAI
 * has no `count_tokens`, no explicit cache_control breakpoints, no cache-create
 * premium, and images are billed by OpenAI's vision-token formula rather than
 * text tokens. The transform path records two GPT-specific facts per imaged
 * request:
 *
 *   imageTokens           = what the rendered images actually cost as input
 *   baselineImagedTokens  = o200k text tokens the imaged/stripped content would
 *                           have cost if left as plain text
 *
 * OpenAI usage then tells us how many prompt tokens were served from prompt
 * cache (`cached_tokens`, a subset of input_tokens). For the gpt-5 family, cached
 * input is billed at ~0.1× the normal input rate; there is no 1.25× write
 * premium like Anthropic's ephemeral cache.
 */
/** gpt-5 cached input list ratio: $0.125 / $1.25 per 1M tokens. */
export declare const OPENAI_GPT5_CACHE_READ_RATE = 0.1;
/** gpt-5 output/input list ratio: $10 / $1.25 per 1M tokens. */
export declare const OPENAI_GPT5_OUTPUT_RATE = 8;
/** Older OpenAI families use a less aggressive cached-input discount. pxpipe's
 * GPT compression gate is currently gpt-5.x-only, but keep the helper explicit
 * so passthrough telemetry does not accidentally get priced at Anthropic rates. */
export declare function openAICacheReadRate(model: string | undefined): number;
export declare function openAIOutputRate(model: string | undefined): number;
/** Weighted input tokens actually paid to OpenAI this turn. `cachedTokens` is a
 * subset of `inputTokens`, not an additive bucket. */
export declare function computeOpenAIActualInputEff(inputTokens: number, cachedTokens: number, model?: string): number;
/** Raw token count for the unproxied GPT counterfactual: replace the rendered
 * images with the o200k text they stood in for. */
export declare function computeOpenAIBaselineRawTokens(inputTokens: number, imageTokens: number, baselineImagedTokens: number): number;
/** Weighted input tokens for the unproxied GPT text counterfactual.
 *
 * We cannot ask OpenAI `count_tokens`, and the API does not expose per-block
 * cache accounting. The only honest observable is whether this request had a
 * prompt-cache hit at all (`cached_tokens > 0`). The imaged slab sits in the
 * stable prefix; when OpenAI reports cached tokens, that slab would have been
 * cached as text too, so the text↔image delta is discounted by the same cached
 * input rate. On a cold/no-cache turn, the delta is paid at the full input rate.
 */
export declare function computeOpenAIBaselineInputEff(inputTokens: number, cachedTokens: number, imageTokens: number, baselineImagedTokens: number, model?: string): number;
//# sourceMappingURL=openai-savings.d.ts.map