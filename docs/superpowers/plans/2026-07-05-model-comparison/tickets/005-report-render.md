---
status: ready
agent: report-generator
model: sonnet
depends_on: [4]
files:
  - docs/reports/2026-07-05-model-comparison.html
---

## Scope

Render the final owner-facing HTML report (RU, dark Tokyo Night, tokens from
`.claude/rules/tokyo-night.css`) from the orchestrator's aggregated findings file
+ the 4 runs' `metrics.json`/`meta.json`: lead verdict, comparison table
(recall/precision + Wilson CI, cost per 1k GT tuples, wall-clock, error share),
per-section slice highlights, filled §5 tables, evidence block (run ids, spend,
commit hashes), next steps. Presentation only — no analysis of its own.

## Acceptance Criteria

1. `docs/reports/2026-07-05-model-comparison.html` self-contained (inline CSS, no CDN), dark theme.
2. Every number traceable to a `metrics.json`/`meta.json`/triage artifact (no invented cells).

## Out of scope

Publishing as a Claude Artifact (orchestrator does delivery).
