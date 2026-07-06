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
- **Routing decisions (orchestrator, 2026-07-05, post-triage):** gpt-5.5 → `provider-8`
  (overrides the rule's `auto` pick: cost within noise, 10/10 vs 9/10, and the padded
  provider-6 is alive for this model — pin-explicit-route lesson); qwen3.7-plus → `auto`
  (overrides `provider-8`: 8/10 vs 6/10 raw success dominates an 11 % cost delta after 3× retries;
  **no clean route exists for qwen** — reliability finding for the report); deepseek-v4-flash →
  `provider-9`; gemini baseline → `provider-9` (re-verified).
- **Matrix run parameters (from 002/002b smokes):** `--max-judge-calls 30000` (smoke showed
  ~241 judge calls/article → ~24k per full run; the old 5000 plan would kill runs silently),
  `--max-usd 12`, `--llm-workers 16`, article-workers scaled to saturate; staggered starts;
  per-run Wikidata-cache copies (cross-process file-append race avoidance). Revised cost
  forecast: ≈ $26 total for the matrix.
- **Routing revision (2026-07-05 23:16 UTC):** the qwen `auto` pick was reverted to an explicit
  `provider-8` pin after CloseRouter's circuit-breaker turned `auto` into a hard 503
  (`no_available_provider`: the only upstream was auto-suppressed). All qwen relaunches run pinned.
