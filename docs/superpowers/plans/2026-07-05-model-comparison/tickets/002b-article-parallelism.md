---
status: ready
agent: python-pro
model: sonnet
depends_on: [2]
files:
  - scripts/wiki_eval.py
  - src/palimpsest/terminology/wikidata.py
  - tests/
  - docs/stages/wiki-eval.md
---

## Scope

Ticket 002's live smoke measured ~14 min wall-clock for ONE article (113 extract
calls parallel, then a sequential grounding/judge phase dominated by Wikidata
lookups + judge latency) → a full-100 run would take 13-23 h per model. Add
**article-level parallelism** to `wiki_eval.py run`: process N articles
concurrently (CLI `--article-workers`, default 3), each article keeping its own
`judge_cache` and its internal two-phase flow. Hard constraints: (a) the owner
cap of ≤4 concurrent in-flight LLM calls per run process stays — enforce ONE
global semaphore (size `DEFAULT_MAX_CONCURRENCY`) shared by ALL extract and
judge calls across article workers; the speedup comes from overlapping Wikidata
I/O across articles, not from more LLM concurrency; (b) Wikidata calls get their
own bounded parallelism (semaphore ≈3, politeness) — inspect `WikidataClient`
for thread safety first and add the minimal locking (in-memory cache dict +
cache-file appends must be race-free; network calls must NOT be serialized by
one big lock); (c) `pred_records` order stays deterministic (collect per-article
results, extend in `gt_records` input order); (d) BudgetGuard is already
thread-safe — just gets more concurrent callers; (e) `meta.json` records worker
params. Doc-parity: stage-doc bullet in the same commit.

## Acceptance Criteria

1. `uv run --extra dev python -m pytest tests/ -q` green; new tests: output order determinism with shuffled completion, global LLM semaphore actually bounds concurrency (regression test with a counting fake), Wikidata cache race test.
2. Live smoke: 3-article slice of `data/eval/wiki/gt.jsonl`, baseline model, `--article-workers 3 --max-usd 2` → wall-clock materially below 3× the single-article baseline (~14 min); report actual timings + spend split.
3. One commit (`perf(wiki-eval): ...`), explicit paths only (another agent's files are in flight in this checkout); pushed with retries.

## Out of scope

Cross-process concerns of running 4 model runs at once (ticket 004 handles staggering and per-run Wikidata cache copies).
