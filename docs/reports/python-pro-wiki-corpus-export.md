# python-pro: wiki-corpus-export

## Scope

Build the wiki-corpus export for Danil's translation pipeline per
[docs/superpowers/specs/2026-07-07-wiki-llm-judge-eval.md](../superpowers/specs/2026-07-07-wiki-llm-judge-eval.md)
Sec.2/4 (Ph-1 item 1): a new `scripts/export_wiki_corpus.py` that reads the
100-article wiki corpus the same way the wiki-eval harness does, emits
`wiki_original.json` (flat paragraph array, Danil's pipeline input shape),
`wiki_index.json` (sidecar for per-article analysis), and `pilot_articles.json`
(10-article stratified pilot selection, spec Sec.4 Ph1). Nothing under
`external/` was modified; nothing was committed — all four new files are left
untracked in the working tree per the task's instructions.

## Files changed

- **New**: [scripts/export_wiki_corpus.py](../../scripts/export_wiki_corpus.py)
  — argparse CLI, type-hinted, `ruff check` clean at line-length 100
  (rules `E,F,I,B,UP`, the project's own `pyproject.toml` config).
- **New (untracked, not committed)**: `data/eval/wiki/wiki_original.json`,
  `data/eval/wiki/wiki_index.json`, `data/eval/wiki/pilot_articles.json`.

## Decisions & rationale

- **Loading matches the harness exactly.** Cache-filename resolution reuses
  `wiki_gt._safe_filename` verbatim (imported, not reimplemented); paragraph
  extraction reuses `tokenize.flatten` + `str.split("\n")`, identical to what
  `docs/stages/wiki-eval.md`'s "Subtleties" section documents `run` doing when
  it re-derives paragraphs from cached HTML. "Non-empty" paragraph = `if p`
  (no `.strip()`) — verified empirically that this gives the exact same 2 553
  count as `.strip()`-filtering would on this corpus (no whitespace-only
  paragraphs exist), so no silent behavior difference either way.
- **Hard asserts, not soft warnings**, per the task: 100 titles in
  `titles_v2.txt`, 100 articles resolved (a missing cache file raises
  `FileNotFoundError` rather than being silently skipped — unlike
  `wiki_gt.build_gt`'s tolerant fetch-failure counting, this script has no
  network fallback path, so a miss is a hard corpus-integrity bug, not a
  transient), and exactly 2 553 total non-empty paragraphs. All three passed
  on this run with zero anomalies — this reproduces the numbers already
  established by the prior read-only audit
  ([python-pro-wiki-corpus-cleanliness-check.md](python-pro-wiki-corpus-cleanliness-check.md)):
  2 553 paragraphs, 160 836 tokens, max paragraph 392 tokens (article "Ишува").
- **Serialization matches `bouquet_original.json`'s style**: inspected it
  directly (`json.dumps(data, ensure_ascii=False, indent=2)` — readable
  Cyrillic, not `\uXXXX` escapes, 2-space indent, no trailing newline). Both
  `wiki_original.json` and `wiki_index.json` use the identical
  `write_json_bouquet_style` helper so downstream tooling sees one
  consistent shape.
- **Pilot decile selection — rank-based, not value-midpoint.** The spec says
  "one per decile of total article token length ... take the article closest
  to each decile midpoint." Two readings exist: (a) partition the
  rank-sorted 100 articles into 10 equal-count bins and take each bin's
  middle-ranked article (standard statistical meaning of "decile"), or (b)
  compute the 11 percentile *boundary values* and pick the article closest to
  each inter-boundary midpoint *value*. I tested both against the real data —
  they diverge sharply in the long tail (decile 9 pick: "Пергамский алтарь"
  3 653 tokens under (a) vs. "Древняя Греция" 7 018 tokens under (b), 0
  overlap between the two 10-article sets). I went with (a) — it is the
  standard meaning of "decile" (equal-frequency partition of ranked data,
  the same sense `docs/stages/wiki-eval.md`'s own p10/p50/p90 paragraph-length
  stats use) and is simpler/more reproducible (disjoint bins, no
  without-replacement bookkeeping needed for the initial 10 picks).
  **Flagging this as a judgment call** in case Danil's pipot intent was
  value-based; the alternative (b) picks are cheap to recompute from the same
  script if wanted.
- **Force-include replacement**: for each forced article, if it already
  matches an existing decile pick's title, only its `reason` is annotated (no
  slot replacement, keeps exactly 10); otherwise the nearest decile pick *by
  token-count distance*, excluding any slot already used by a prior forced
  article, is replaced. This nearest-not-yet-forced exclusion mattered in
  practice (see anomaly below).
- **`n_paragraphs`/`paragraph_indices` size (274, not exactly ~250)**: the
  task's "expect roughly ~250" was a rough estimate (10 × mean 25.5
  paragraphs/article ≈ 255); the actual 10 picked articles (skewed toward the
  upper deciles by design, since deciles are by token count and longer
  articles have more paragraphs) sum to 274. Within "roughly" range, not
  treated as a failure.
- **Smoke-subset definitions** (short/medium/long/max-paragraph/marker-paragraph,
  5 distinct global paragraph indices, not restricted to the 10 pilot
  articles): short = global-minimum `n_tokens`; medium = paragraph closest to
  the corpus median; long = paragraph closest to p90 (kept distinct from the
  literal max, which is its own bucket); max-paragraph = the literal 392-token
  paragraph; marker-paragraph = the first paragraph (global order) actually
  containing `[источник не указан`. Collision-safe via a `used` set with
  fallback to the next-closest index — not triggered on this corpus (all 5
  came out distinct on the first pick).

## Critical findings & shortcomings

- **Anomaly (flagged, handled): "Ишува" is simultaneously the corpus-max-paragraph
  owner AND one of the 8 `[источник не указан]`-carrying articles.** A naive
  force-include of both criteria would have collapsed to one article (9
  distinct pilot articles instead of 10). Handled by explicitly choosing a
  *different* marker-carrying article ("Эллинистический Египет", the first
  other marker owner in corpus order) for the marker force-include, so the
  two force-includes add genuinely distinct coverage. This is a deliberate
  design choice, not a bug, but it means the "marker" pilot article does not
  double as evidence about the max-paragraph/truncation risk — that risk is
  only covered by "Ишува".
- **"Short" smoke paragraph is a 1-token fragment** (`"Периодизация:"`, from
  article "XXX династия" — a section-heading-like fragment, not a full
  sentence). It is legitimately the shortest of all 2 553 paragraphs, so it
  answers the literal spec ask, but it is a weak smoke case for translation
  quality (nothing to translate meaningfully). Worth a manual eyeball before
  using it in the actual smoke translate run — did not substitute a different
  "short-but-more-representative" paragraph since the spec's ask was the
  literal shortest, not a curated one.
- **Decile-pick interpretation is a judgment call** (see above) — not
  verified against Danil's or the owner's actual intent; flagged rather than
  silently assumed.
- The 119-vs-100 cached-HTML-file discrepancy noted in the prior cleanliness
  report (pilot-corpus leftovers under `data/eval/wiki/pages/`) is irrelevant
  here — this script only ever resolves the 100 titles in `titles_v2.txt` and
  never enumerates the cache directory.

## Run artifacts (evidence)

```
$ uv run ruff check scripts/export_wiki_corpus.py
All checks passed!

$ uv run python scripts/export_wiki_corpus.py
articles: 100, paragraphs: 2553, tokens: 160836

schema comparison (wiki_original.json vs bouquet_original.json):
  wiki_original.json: count=2553 mean=446.5 median=384.0 max=2695
  bouquet_original.json: count=198 mean=318.5 median=306.5 max=834

pilot: 10 stratified articles
  decile-pick 'Данайцы' (greece): 7 paragraphs, 303 tokens -- decile 0
  decile-pick 'Первая династия Ура' (sumer): 13 paragraphs, 558 tokens -- decile 1
  decile-pick 'Древнегреческая религия' (greece): 26 paragraphs, 684 tokens -- decile 2
  decile-pick 'Сокровища Сеусо' (rome): 19 paragraphs, 862 tokens -- decile 3
  decile-pick 'Камарупа' (india): 31 paragraphs, 1024 tokens -- decile 4
  decile-pick 'Цальпува' (hittite): 20 paragraphs, 1217 tokens -- decile 5
  decile-pick 'Ишува' (hittite): 15 paragraphs, 1545 tokens -- max-paragraph article (replaces decile 6 pick, was decile 6)
  decile-pick 'Тель-Абу-Хавам' (phoenicia): 42 paragraphs, 1965 tokens -- decile 7
  decile-pick 'Эллинистический Египет' (egypt): 39 paragraphs, 2446 tokens -- editorial-marker article (replaces decile 8 pick, was decile 8)
  decile-pick 'Пергамский алтарь' (greece): 62 paragraphs, 3653 tokens -- decile 9

pilot paragraphs covered: 274
smoke indices: {'short': 238, 'medium': 32, 'long': 17, 'max_paragraph': 782, 'marker_paragraph': 278}
```

Determinism check: ran the script twice, `md5sum` of all three output JSON
files identical across runs (no timestamp/random/hash-order nondeterminism).

Schema check: both `wiki_original.json` and `bouquet_original.json` load as a
flat JSON array of non-empty strings (asserted in code, not just observed).

Git status confirms nothing under `external/` touched and nothing committed:

```
$ git status --porcelain
?? data/eval/wiki/pilot_articles.json
?? data/eval/wiki/wiki_index.json
?? data/eval/wiki/wiki_original.json
?? scripts/export_wiki_corpus.py
```

## Open questions

- Whether the rank-based ("standard decile") vs. value-midpoint reading of
  "decile midpoint" was the intended one — flagged above with both option's
  numbers available.
- Whether the 1-token "short" smoke paragraph should be swapped for a more
  representative (but not-literally-shortest) short paragraph before the
  actual pilot translate/judge run consumes `smoke_indices`.

## NOT done (explicit)

- Did not touch anything under `external/` (task constraint).
- Did not commit any file — all four new files (`scripts/export_wiki_corpus.py`,
  `wiki_original.json`, `wiki_index.json`, `pilot_articles.json`) are left
  untracked in the working tree per the task's instruction.
- Did not run the actual pilot translate/judge/refine pipeline (Ph1 in the
  spec) — this task was scoped to the corpus export + pilot selection only
  (Ph-1 item 1).
- Did not investigate or resolve the pre-existing 119-vs-100 cached-HTML-file
  discrepancy (out of scope, noted in the prior cleanliness report).
