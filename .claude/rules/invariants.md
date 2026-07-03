# Hard invariants (never violate)

These are durable rules distilled from the owner's standing feedback. They do not
expire with a task. (Auto-memory does not rehydrate in cloud sessions — this file
is its portable home.)

## Data & predictions
- **Never delete LLM predictions.** No user-facing path may `DELETE` from the `score`
  or `issue` tables (judge scores, issues, evaluations) — they are irreproducible and
  feed future metrics. Mark status / archive (`superseded`, `archived`) and exclude from
  active views instead. Re-eval **appends** score rows, never overwrites. Deploys never
  swap the prod DB file wholesale.
- **Never edit anything in `data/raw/`.** Pilot artifacts live under `data/pilot/`.
- **`factowl/` is a read-only design reference.** Do not edit it.
- **Glossary `glossary/main.json` is the single source of truth** for RU→EN terminology.
  Stage 3 reads it and writes back via `Glossary.upsert`.

## Code & access
- **LLM access only through `palimpsest.llm.client.LLMClient`.** No direct `openai`
  imports outside that module. Never log/print secrets (`OPENROUTER_API_KEY`, etc.).
- **Idiomatic-first.** Prefer standard language/library idioms; neither clever
  one-liners nor verbose hand-rolls are the target.
- **Product/demo UI copy is English-only.** Russian only in owner-facing docs/reports.

## Git & process
- **Conventional Commits in English**, subject in the imperative, scope = module/concern.
  **Never add a `Co-Authored-By` trailer** — this repo's commits have never had one.
- **Branch + PR mandatory.** New work in a `feat/<topic>` branch off the trunk; never
  push directly to the project/trunk branch.
- **Never `--no-verify`, `--no-gpg-sign`, or any hook bypass.** A hook fails → fix the
  root cause.
- **Doc-parity in the same commit** as the contract/code change. Single source of truth:
  every fact lives in one file; others link, never copy.
