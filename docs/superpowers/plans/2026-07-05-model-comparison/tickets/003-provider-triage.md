---
status: ready
agent: python-pro
model: sonnet
depends_on: []
files:
  - scripts/probe_providers.py
  - docs/experiments/2026-07-05-model-comparison/triage/
---

## Scope

Route triage per model (methodology of the 2026-07-05 report). New
`scripts/probe_providers.py`: for a model id, probe `auto` + `provider-1..12`
via `palimpsest.llm.client.LLMClient` (UA fix, timeout 30, no temperature field),
10 tiny calls per live route (`max_tokens=8`, prompt "Reply with exactly: ok"),
0.2 s spacing; up to 4 model-sweeps in parallel, each sequential inside.
Classify per route: 2xx share, med/p90 latency, prompt-token honesty
(>100 tokens on a ~10-token prompt = reseller padding → disqualify), `cost_usd`
surfaced?, error classes. Selection rule: success ≥9/10 ∧ honest tokens →
min cost/call → min latency. Models: `openai/gpt-5.5`,
`deepseek/deepseek-v4-flash`, `qwen/qwen3.7-plus`; for
`google/gemini-3.1-flash-lite` only re-verify provider-9 + auto (20 calls).
For the chosen route of each model, 1 extra call with `temperature=0` to check
acceptance (extractor uses it). Write `triage/<model>.json` + a summary
`triage/summary.md` table with the chosen route per model. Budget ≤ $2.
NO git operations (committed later).

## Acceptance Criteria

1. `docs/experiments/2026-07-05-model-comparison/triage/summary.md` — table: route × {success, med, p90, ptok, cost/call, verdict} per model + chosen route with the rule applied.
2. gpt-5.5 choice explicitly justified as "cheapest stable" (owner wording).
3. Reported total triage spend (from `cost_usd` where surfaced, else token-price estimate).

## Out of scope

Full eval runs (ticket 004) — this ticket never calls the NER prompt.
