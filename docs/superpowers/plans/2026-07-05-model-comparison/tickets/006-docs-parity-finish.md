---
status: ready
agent: docs-keeper
model: sonnet
depends_on: [4, 5]
files:
  - docs/stages/wiki-eval.md
  - docs/experiments/LESSONS.md
  - docs/experiments/ACTIVE
---

## Scope

Final doc-parity pass for the experiment: update `docs/stages/wiki-eval.md`
§ Status (v2 GT built, 4-model matrix numbers, chosen model recommendation link),
append dated lessons to `docs/experiments/LESSONS.md` (one bullet per
generalizable lesson from this run), reset `docs/experiments/ACTIVE` to
"# no active experiment". One commit (`docs(wiki-eval): ...`), no AI signatures; push.

## Acceptance Criteria

1. Status section states real run ids + headline recall M2 per model.
2. LESSONS.md gains ≥1 dated bullet; ACTIVE reset.

## Out of scope

Any change to metrics/code — docs only.
