/** Applicability helpers for pxpipe's production-safe model scope. */
export type PxpipeApplicabilityReason = 'eligible' | 'unsupported_model' | 'unsupported_method' | 'unsupported_path' | 'empty_body';
export interface PxpipeApplicabilityInput {
    readonly model?: string | null;
    readonly method?: string | null;
    readonly path?: string | null;
    readonly bodyBytes?: number | null;
}
/** Current effective allowed-model scope (Claude + GPT). */
export declare function getAllowedModelBases(): string[];
/** PXPIPE_MODELS env / default scope, independent of runtime override.
 *  Dashboard unions this into its chip set so env-enabled models are always shown as toggles. */
export declare function getConfiguredModelBases(): string[];
/** Set the dashboard runtime override. Empty array = compress nothing; null = clear override. Not persisted. */
export declare function setAllowedModelBases(list: readonly string[] | null): void;
/** True when pxpipe may transform this Anthropic model. */
export declare function isPxpipeSupportedModel(model: string | null | undefined): boolean;
/** True when pxpipe may transform this GPT model. Shares the single PXPIPE_MODELS scope. */
export declare function isPxpipeSupportedGptModel(model: string | null | undefined): boolean;
export declare function shouldTransformAnthropicMessages(input: PxpipeApplicabilityInput): {
    eligible: boolean;
    reason: PxpipeApplicabilityReason;
};
//# sourceMappingURL=applicability.d.ts.map