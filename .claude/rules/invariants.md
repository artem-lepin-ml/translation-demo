# Hard invariants — durable owner rules beyond CLAUDE.md

The canonical two-tier Hard Invariants list (general + project-specific) lives in
[CLAUDE.md](../../CLAUDE.md). This file carries only the durable owner rules NOT
covered there. They do not expire with a task. (Auto-memory does not rehydrate in
cloud sessions — this file is its portable home.)

## Data & predictions
- **Never delete LLM predictions.** No user-facing path may `DELETE` from the `score`
  or `issue` tables (judge scores, issues, evaluations) — they are irreproducible and
  feed future metrics. Mark status / archive (`superseded`, `archived`) and exclude from
  active views instead. Re-eval **appends** score rows, never overwrites. Deploys never
  swap the prod DB file wholesale.

## Secrets
- **Never log/print secrets** (`OPENROUTER_API_KEY`, `OPENAI_API_KEY`, etc.).
