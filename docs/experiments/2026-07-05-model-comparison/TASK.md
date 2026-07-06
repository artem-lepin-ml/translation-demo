# TASK — 2026-07-05-model-comparison

## Goal
Measure wiki-eval metrics (recall M1/M2/M3, precision P1/P2, slices, Wilson CI) + cost/speed/reliability
for 4 models via CloseRouter on the full v2 corpus (100 articles, 10 thematic sections), and recommend
the working extractor+judge model. Models: `openai/gpt-5.5` (cheapest stable route per owner),
`deepseek/deepseek-v4-flash`, `qwen/qwen3.7-plus`, baseline `google/gemini-3.1-flash-lite@provider-9`.

## Acceptance
1. `metrics.json` + `report.html` per model on full `gt_v2.jsonl` (or an explicit documented drop-out).
2. Comparison table with CIs, cost per 1k GT tuples, wall-clock, transient-error share; a reasoned recommendation.
3. Total spend ≤ $60; no run silently killed by a cap.
4. Final report delivered as a Claude Artifact; §5 template tables filled with real numbers.

## Scope
- In: provider triage per model, runner upgrade (parallel extraction, cost accounting, model args), 4 full runs (config 111), comparison report.
- Out: 8-config ablation (later, on the winner only), prompt changes, grounding-code changes.

Spec (RU, owner-reviewed): [docs/superpowers/specs/2026-07-05-model-comparison-wiki-eval.md](../../superpowers/specs/2026-07-05-model-comparison-wiki-eval.md)
