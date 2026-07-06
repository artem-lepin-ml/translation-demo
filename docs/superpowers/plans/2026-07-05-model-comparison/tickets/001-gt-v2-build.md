---
status: ready
agent: python-pro
model: sonnet
depends_on: []
files:
  - data/eval/wiki/gt_v2.jsonl
  - data/eval/wiki/gt_v2.jsonl.summary.json
  - data/eval/wiki/pages/
---

## Scope

Build the ground-truth file for the v2 corpus: run `wiki_eval.py build-gt` over
`data/eval/wiki/titles_v2.txt` (100 titles, 10 sections) into
`data/eval/wiki/gt_v2.jsonl`. Free (Wikipedia/Wikidata APIs only), long
(rate-limited) — run in background. Before fetching, seed the HTML cache from the
session scratchpad `pages/` dir (same Parsoid snapshots, saves ~1 h of refetch).
No git operations in this ticket — the data is committed later with the run matrix.

## Acceptance Criteria

1. `wc -l data/eval/wiki/gt_v2.jsonl` → ≥95 (fetch failures documented per title).
2. `gt_v2.jsonl.summary.json` exists; malformed/failed share < 10% (fail-loud otherwise).
3. Spot-check 3 records: `stratum` is a section slug (e.g. `sumer`), no `hardness` key, counters present, `gt_tuples` non-empty.
4. Reported: per-section article count (10×10 expected) and total GT-tuple count.

## Out of scope

Any paid LLM call (extraction/judge) — this ticket is GT only.
