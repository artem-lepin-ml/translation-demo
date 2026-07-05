---
status: ready
agent: python-pro
model: sonnet
depends_on: []
files:
  - scripts/wiki_eval.py
  - src/palimpsest/terminology/evaluation/predict.py
  - tests/
  - docs/stages/wiki-eval.md
---

## Scope

Make `wiki_eval.py run` fit for full-100 multi-model runs: (a) CLI `--model`,
`--provider`, `--max-judge-calls` (defaults = current env-driven values);
(b) parallel extraction bounded by `DEFAULT_MAX_CONCURRENCY=4` — per article,
phase 1 extracts all paragraphs concurrently, phase 2 grounds/judges sequentially
(identical output semantics; BudgetGuard gets a lock); (c) count extraction spend
in BudgetGuard (today only judge calls are counted — a real accounting hole),
settle with `usage.cost_usd` when surfaced; (d) write `meta.json` into the run dir
(model, provider, config, prices, spend split extract/judge, call counts,
wall-clock, started/finished); (e) output path becomes
`reports/terminology/wiki-eval/<model-slug>/<config>/<run_id>/` where model-slug =
model id with `/`→`--` plus `--<provider>` (keep dots: `openai--gpt-5.5--provider-3`);
`cmd_report` keeps working (config = parent dir of run_id, merges meta.json).
Doc-parity: update the CLI/Interface + Design-decisions bullets in
`docs/stages/wiki-eval.md` in the same commit.

## Acceptance Criteria

1. `uv run --extra dev python -m pytest tests/ -q` → green.
2. Live smoke: `run` on a 1-article GT slice with the baseline model
   (`google/gemini-3.1-flash-lite`, provider-9) → `pred.jsonl` + `meta.json` with a
   real nonzero extract-spend figure; `report` produces `metrics.json`/`report.html`.
3. `run --dry-run` still works and forecasts within `--max-usd`.
4. One commit (`feat(wiki-eval): ...`), only this ticket's files, no AI signatures; pushed.

## Out of scope

Provider probing/selection (ticket 003) and launching the model matrix (ticket 004).
