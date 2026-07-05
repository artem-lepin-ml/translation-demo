# PLAN — 2026-07-05-model-comparison

## Approach
Phased (spec § Дизайн): Ф0 GT v2-100 build (free, background) ∥ Ф1 provider triage ∥ Ф2 runner upgrade →
Ф3 4 parallel background runs (config 111, per-run caps) → Ф4 aggregation + Artifact report.
Tickets: [docs/superpowers/plans/2026-07-05-model-comparison/tickets/](../../superpowers/plans/2026-07-05-model-comparison/tickets/).

## Solution paths
- **path-1..4:** one per model (gpt-5.5 / deepseek-v4-flash / qwen3.7-plus / gemini-baseline), identical harness, route chosen by triage rule: success ≥9/10 ∧ honest prompt tokens (no >100 padding) → min cost/call → min latency.

## Ratchet metric
Recall M2 (span-overlap, primary) on gt_v2 at comparable precision P1; decision weighs cost/1k tuples and reliability.

## Notes
- Lesson applied (2026-07-05 triage report): pin explicit provider route, never `auto`.
- Known trap: `MAX_JUDGE_CALLS=900` too low for 100 articles → CLI-arg, runs use 5000.
- Known gap fixed in Ф2: extraction spend was not counted by BudgetGuard (judge only).
- Owner approvals recorded in APPROVED.md.
