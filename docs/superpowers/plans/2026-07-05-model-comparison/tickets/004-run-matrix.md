---
status: ready
agent: backend-developer
model: sonnet
depends_on: [1, 2, 3]
files:
  - reports/terminology/wiki-eval/
  - data/eval/wiki/gt_v2.jsonl
---

## Scope

Execute the 4-model matrix on `gt_v2.jsonl`, config `111`: dry-run forecast each,
then launch 4 background `run`s in parallel (routes from ticket 003; per-run
`--max-usd 12 --max-judge-calls 5000`), monitor to completion, then `report` each.
On a deterministic failure (e.g. a model rejects `temperature=0`) adapt once
(drop the field), document, continue. Then one commit: gt_v2 data + new pages
cache + run outputs (pred/meta/metrics/report) + triage results + experiment docs
(spec, tickets, TASK/BUDGET/PLAN/APPROVED, ACTIVE) — `feat(wiki-eval): ...`,
no AI signatures; push.

## Acceptance Criteria

1. 4 run dirs `reports/terminology/wiki-eval/<model-slug>/111/<run_id>/` each with `pred.jsonl`, `meta.json`, `metrics.json`, `report.html` (or a documented drop-out per model).
2. Reported per model: recall m1/m2/m3, precision p1/p2, spend (extract/judge split), wall-clock, retry/error share.
3. Total matrix spend ≤ $48 (4 × $12); no silent cap kill — any `stopped_reason` surfaced.
4. Commit pushed; PR #3 branch updated.

## Out of scope

Cross-model analysis and the owner-facing report (orchestrator + ticket 005).
