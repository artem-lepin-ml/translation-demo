# python-pro: search-miss analysis harness (gold-entity outcome classifier)

## Scope

Task: build and validate an offline search-miss analysis harness for the wiki-eval NER+grounding
experiment — classify each effective-gold entity's pipeline outcome (`not_extracted` /
`no_candidates` / `retrieval_miss` / `candidates_hit`) against a run's per-mention `candidates`
field (predict.py/label_first.py, commit 64eb023), for the R_search downstream review. Pure
offline: no LLM calls, no network. Hard constraints observed throughout: nothing under `reports/`
staged or written (the `google--gemma-3-27b-it--Parasail/111/2026-07-10T18-22-43Z` run was live
and actively appending to `pred.partial.jsonl`/`calls.jsonl`/`progress.jsonl` during this session —
read-only access only); exact-path `git add`; branch `claude/ner-translation-config-b0ozsc` never
switched.

## Files changed

- `data/eval/wiki/cleanup/tools/search_miss_analysis.py` (new) — the CLI tool
  (`--run-dir --articles --out`). Reads `data/eval/wiki/gt.jsonl`'s first N articles (default 10,
  file order), builds effective gold = tier-filtered (`tier_assignment.json`, kept iff
  `drop_level == 0`, `aggregate_corpus`'s own gold-side filter reused verbatim) minus the live
  scoring-time exclusions in `anchor_exclusions.json` (identity
  `(token_index, anchor_text, qid, span_len)` scoped by title — confirmed `wiki_eval.py`'s own
  `cmd_report` never reads this file, so it's a scoring-time-only overlay every offline analysis
  script in this directory applies for itself, not part of the committed `metrics.json`). Unit of
  analysis = gold entity = distinct `(article, QID)` pair, same grouping `aggregate_corpus` uses.
  For each entity, pools all pred mentions overlapping ANY of its gold mentions (`overlaps()`,
  ported from the identical local formula already duplicated in `replay_analysis.py`/
  `enumerate_misses.py`/`span_ner_before_after.py` — `metrics.py`'s protocol-v3 `aggregate_corpus`
  has no span-overlap machinery of its own, it was retired with `matching.py`), then classifies:
  no overlap → `not_extracted`; overlap but all candidate lists empty → `no_candidates`; overlap
  with candidates but gold QID absent from all of them → `retrieval_miss`; gold QID present in
  ≥1 overlapping mention's candidates → `candidates_hit`. Sentence reconstruction for each
  non-`candidates_hit` entity's first (lowest `token_index`) gold mention ports
  `build_lists.py`'s `build_sentence_index`/`token_range_for_char_span`/anchor-marking algorithm
  verbatim (space-joined tokens, `extract.py`'s `_sentence_spans` reused, `⟪…⟫` markers,
  ±15-token window fallback on out-of-bounds/no-sentence-span edge cases). Reads
  `pred.jsonl` if present, else falls back to `pred.partial.jsonl` (in-flight checkpoint) —
  needed because the validation run's only pred file was still a partial checkpoint. Ruff-clean
  (`select = ["E","F","I","B","UP"]`, line-length 100).
- `docs/stages/wiki-eval.md` — added a new `## Analysis tools` section (didn't exist yet; the
  five pre-existing sibling scripts under `cleanup/tools/` were previously undocumented here,
  only referenced ad hoc inline in Design decisions/Protocol v3 prose) with one intro line
  pointing at `data/eval/wiki/README.md` for the rest, plus the one line for
  `search_miss_analysis.py` (doc-parity, Hard Invariant 2).
- Commit `dba0eb9` — `feat(wiki-eval): search-miss analysis harness (gold-entity outcome
  classifier)`, pushed to `origin/claude/ner-translation-config-b0ozsc` on the first attempt (no
  rebase/retry needed — branch was ahead by 1, no divergence).

## Decisions & rationale

- **`aggregate_corpus` (protocol v3, read at HEAD) has no span-overlap logic of its own** — a
  pure QID-set aggregator, span-level matching (`matching.py`, mention-level M1/M2/M3) was
  retired in the v3 rework. The task's "reuse metrics.py's overlap/classification helpers"
  instruction concretely meant: reuse its tier-filter + gold-unit-grouping *protocol*
  (`tier_assignment.get(qid,0) != 0` skip, group by `(article, QID)`), while `overlaps()` itself
  had to be a local port — same convention every sibling script in this exact directory already
  follows (each defines its own copy rather than importing a shared one, since none exists).
  Documented this explicitly in the new tool's module docstring so it doesn't read as
  reinventing something with a canonical home.
- **`metrics._classify` (named/term) deliberately NOT used** — this taxonomy classifies a
  pipeline *outcome* per entity (extraction/retrieval stage), orthogonal to the named/term split
  `aggregate_corpus` reports. Output schema requested by the task has no named/term field.
- **Effective-gold order = `gt.jsonl` file order → first N articles**, matching how
  `titles.txt`/`build-gt` produced the corpus; `--articles` guards against exceeding the corpus
  size (`SystemExit` if so, consistent with sibling tools' fail-loud style).
- **`pred.jsonl` preferred, `pred.partial.jsonl` fallback** — the only file available for the
  validation run at the time (live run still in flight); generalizes cleanly to later full runs
  where `pred.jsonl` will exist.
- **Determinism**: entities built in `gt.jsonl`/`gt_tuples` file order (dict insertion order,
  no filesystem/hash-set nondeterminism); `misses` list additionally sorted by
  `(selected-article order, qid)` for a stable diff between reruns. Verified byte-for-byte
  identical `totals` across two runs (before/after a ruff line-length cleanup pass).
- **Two independent sanity gates baked into the tool itself** (not just the validation pass):
  (1) `assert sum(outcome_counts.values()) == n_gold_entities` — every classified entity
  accounted for; (2) a hard `assert` that no excluded identity survived into the effective-gold
  set (defensive — should be structurally impossible given the filter, but fails loud if a future
  edit breaks it, matching `compute_dataset_stats.py`'s `assert not unmatched_ex` convention).
- **`## Analysis tools` section didn't pre-exist** in `docs/stages/wiki-eval.md` — grepped for
  "Analysis tool[s]" across `docs/` and found none; created a minimal section (one intro line +
  the one requested tool line) rather than retroactively documenting the five pre-existing
  sibling scripts there too, to avoid scope creep beyond what was asked and avoid duplicating
  facts already covered by `data/eval/wiki/README.md`'s `cleanup/` section (single source of
  truth, Hard Invariant 3).

## Validation (gemma, first 10 articles, VALIDATION ARTIFACT — real analysis runs on gemini later)

Run: `reports/terminology/wiki-eval/google--gemma-3-27b-it--Parasail/111/2026-07-10T18-22-43Z/pred.partial.jsonl`
(in-flight checkpoint, read-only). Output written only to the session scratchpad (never
committed, never under `reports/`):
`/tmp/claude-0/-home-user-translation-demo/d94abddc-f105-576c-b81a-a51a1ca3f0ff/scratchpad/search_miss_analysis/gemma_10_articles_validation.json`.

- `n_gold_entities = 358`; independently recomputed with a separate one-off script (tier +
  exclusion filter only, no outcome logic) → also 358, exact match.
- Outcome distribution: `not_extracted` 29 (8.1%), `no_candidates` 10 (2.8%), `retrieval_miss` 38
  (10.6%), `candidates_hit` 281 (78.5%). Sum 29+10+38+281 = 358 = `n_gold_entities` (assert
  passed, counts-sum sanity check satisfied).
- `anomalies: []` — no excluded identity leaked into effective gold, no sentence-reconstruction
  edge case (OUT_OF_BOUNDS/NO_SENTENCE_SPAN/ANCHOR_OUTSIDE_SENTENCE) hit for any of the 77 misses.
- Spot-checked 3 examples per non-hit outcome class (printed from the output JSON, not part of
  the CLI itself):
  - `not_extracted`: `KV35YL` / `Q1633253` "гробнице KV35" — zero overlapping pred mentions.
  - `no_candidates`: `Арслантепе (Мелид)` / `Q1149666` "Вашуканни" — extracted (`category=place`),
    Wikidata search returned an empty candidate list.
  - `retrieval_miss`: `XXVII династия` / `Q373521` "Псамметих III" — extracted correctly, but the
    only candidate returned was `Q316278` (same real-world referent under a different QID), not
    the gold `Q373521`.

## Open questions

- The `retrieval_miss` example above (`Q373521` vs `Q316278`, both apparently "Psamtik III")
  suggests some retrieval misses may be a Wikidata gold-QID/duplicate-item artifact rather than a
  genuine search failure — worth a light manual spot-check pass before drawing conclusions from
  the `retrieval_miss` rate on the real (gemini) run, but out of scope for this harness-building
  task.
- No dedicated pytest test file was added for `search_miss_analysis.py` — it is a `cleanup/tools/`
  one-off analysis script, matching the existing convention for every sibling script in that
  directory (none of `replay_analysis.py`/`enumerate_misses.py`/`span_ner_before_after.py`/
  `compute_dataset_stats.py`/`aggregate_exclusions.py`/`extend_tier_assignment.py` have unit
  tests either — they're validated by inline reconciliation asserts against known-good numbers,
  which this tool also does).

## NOT done

- Did NOT run the harness against the gemini run (explicitly deferred to "later" by the task).
- Did NOT write a docs/reports HTML report or Claude Artifact — the task's own Commit section
  said "no extra report file", only the chat-facing JSON summary; this `.md` file exists solely
  to satisfy the stop-hook's mandatory reporting protocol, not as an owner-facing deliverable.
- Did NOT modify `gt.jsonl`, `tier_assignment.json`, or `anchor_exclusions.json` — read-only.
- Did NOT touch anything under `reports/` — the live gemma/gemini/deepseek/gemma-4 runs' working-
  tree changes and untracked new run dirs were left exactly as found, unstaged.
