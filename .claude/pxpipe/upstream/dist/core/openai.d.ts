/**
 * OpenAI Chat Completions + Responses API transformer for the GPT-5 family.
 * Separate from the Anthropic path: no cache-control breakpoints,
 * images as image_url/input_image parts, system/developer messages in messages[]/input[].
 * OpenAI tools keep native names/descriptions/schema shape; verbose schema prose
 * is also rendered into images for token savings so calls do not depend only on OCR.
 */
import { type GptVisionCost } from './gpt-model-profiles.js';
import { type TransformInfo, type TransformOptions } from './transform.js';
type VisionCost = GptVisionCost;
export declare function resolveVisionCost(model: string): VisionCost;
export declare const HISTORY_TRANSCRIPT_INTRO = "[Earlier turns of THIS conversation, transcribed in the image(s) below. Each turn is wrapped in <user t=\"N\">...</user> or <assistant t=\"N\">...</assistant> tags, where N is an absolute turn index (larger N = more recent); attribute every turn strictly by its tag, and treat the highest-N turns as the most recent prior context, NOT the low-N opening turns. Earlier turns may contain questions or tasks that were already answered later in this same history; do not reopen low-N turns unless the live text after this block asks you to. This is prior context, NOT the current request.]";
export declare const HISTORY_TRANSCRIPT_OUTRO = "[End of earlier conversation. The current request is the live text that follows below.]";
export declare function openAIVisionTokens(model: string, w: number, h: number): number;
export declare function transformOpenAIChatCompletions(body: Uint8Array, opts?: TransformOptions): Promise<{
    body: Uint8Array;
    info: TransformInfo;
}>;
export declare function transformOpenAIResponses(body: Uint8Array, opts?: TransformOptions): Promise<{
    body: Uint8Array;
    info: TransformInfo;
}>;
export {};
//# sourceMappingURL=openai.d.ts.map