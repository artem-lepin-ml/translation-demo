# python-pro report — IPA per-phoneme gold-anchor fix

## Scope

Apply the diagnosed fix from `docs/reports/debugger-ipa-parser-gold-anchors.md` (full
technical write-up in scratch: `.../scratchpad/gold_cleanup/ipa_parser_diagnosis.md`):
add a single-char symbol-fragment guard to `extract_gt()` so ru-wiki IPA/transcription
template hyperlinks (one `<a>` per phoneme glyph) stop being counted as gold mentions;
re-derive the already-committed `data/eval/wiki/gt.jsonl` via an offline post-filter
(no network); add regression tests; doc-parity; commit and push to
`claude/ner-translation-config-b0ozsc`. No LLM API calls; git push was the only network use.

## Files changed

- `src/palimpsest/terminology/evaluation/wiki_gt.py` — added `_ATTACHING_BRACKETS`,
  `_attaches()`, `_is_symbol_fragment()` (module-level helpers); `n_excluded_symbol`
  field on `GtCounters` (+ `as_dict()`); guard call inserted in `extract_gt()`'s anchor
  loop right after the `char_pos == -1` skip, before `_is_main_namespace_href`.
- `data/eval/wiki/gt.jsonl` — 4 of 100 records rewritten (Тронное имя фараона 79→27,
  Веды 198→196, Микенская цивилизация 500→499, Нур-Адад 38→37 tuples; 56 removed
  total); each rewritten record's `counters.n_anchors -= removed`,
  `counters.n_excluded_symbol += removed`. Other 96 records byte-identical
  (`git diff` confirms only 8 changed lines = 4 old + 4 new).
- `data/eval/wiki/gt.jsonl.summary.json` — inspected, has no total-tuple-count field;
  left untouched (not staged, no diff).
- `tests/test_wiki_gt.py` — 4 new regression tests: IPA-template glyphs dropped +
  `n_excluded_symbol` count; legit `V век`/`У` kept; no embedded single-char anchor
  survives (checked across 3 fixtures incl. the pre-existing `FIXTURE_HTML`); direct
  `_is_symbol_fragment` edge cases (bracket-glued `(ə)`, em-dash `X—XII` non-attachment,
  whole-token `У`).
- `tests/test_wiki_metrics_v3.py` — **deviation, not in the original file list** (see
  Decisions below): updated 3 pinned "regression anchor" assertions
  (`test_regression_anchor_run_a_gemini`, `test_regression_anchor_run_b_deepseek`,
  `test_gold_named_plus_term_invariant`) from the pre-fix numbers to numbers recomputed
  live against the corrected `gt.jsonl` (`5562 → 5551` named+term gold units,
  `n_gold_mentions_dropped_by_tier` `785 → 765`, per-class tp/fn/fp/gold_units updated
  and internally cross-checked `tp+fn == gold_units`).
- `docs/stages/wiki-eval.md` — tuple count `7 959 → 7 903` in two places (Corpus section
  + Status section); new Design-decisions bullet describing `_is_symbol_fragment`.
- `docs/known_issues.md` — new `RESOLVED 2026-07-10` entry: root cause, blast radius,
  fix, and a forward-looking gotcha note for future corpus additions that hit the same
  IPA-template pattern.
- `docs/reports/debugger-ipa-parser-gold-anchors.md` — was untracked from the prior
  diagnosis-only session; committed as-is (evidence), unedited.

Not committed (scratchpad only, by design): the offline post-filter script
(`apply_ipa_fix.py`) and the pre-fix `gt.jsonl` backup, both under
`/tmp/claude-0/-home-user-translation-demo/d94abddc-f105-576c-b81a-a51a1ca3f0ff/scratchpad/gold_cleanup/`.

## Decisions & rationale

- **Guard placement and predicate exactly as diagnosed** — no deviation from the
  diagnosis's diff sketch; it is authoritative per the task brief.
- **Offline post-filter over `build_gt` re-run** — re-running `build_gt` needs a live
  `titles_to_qids` network call (no QID cache available); the guard decision itself
  (`_is_symbol_fragment`) doesn't depend on QID at all, so applying it directly to the
  already-built `gt_tuples` is provably equivalent to what the fixed builder would emit
  (per the diagnosis's own proof), and stays inside the no-network constraint.
- **Reconstructing char-level neighbours from `gt.jsonl`'s own `tokens` list** — the
  gold records don't retain the flattened article text or per-`<a>` char offsets, only
  `tokens` (the whitespace-split list). Since token boundaries in the original text are
  always whitespace, a token padded with one space on each side (`" " + token + " "`)
  is behaviourally equivalent to the real surrounding text for the guard's neighbour
  check — verified this holds for every one of the 55 non-trivial single-char tuples in
  the 4 affected articles by dumping and inspecting them before writing the filter.
  Duplicate `(token_index, surface)` occurrences (e.g. `i` appearing twice in
  `[nijˈsiːwat`) are matched to their token-internal occurrence positions in list order
  via a per-key counter, so no ambiguity remains even in the (unobserved in this
  dataset) case of mixed keep/drop verdicts within one token.
- **Shared predicate, not duplicated logic** — the post-filter script imports
  `_is_symbol_fragment` directly from the fixed `wiki_gt` module rather than
  re-implementing the neighbour-attachment rule.
- **Updating `test_wiki_metrics_v3.py`'s pinned numbers (out-of-scope file, done anyway)**
  — these "regression anchor" tests recompute `aggregate_corpus_v3` live against the
  *full* committed `gt.jsonl` (not just the pilot) and two real prediction runs; they
  broke immediately after the (correct) gold fix because they were pinned to the buggy
  gold's output. The task instruction "expect all pass" and the standing rule against
  leaving tests red made fixing this the only honest option; I recomputed every number
  from the actual aggregator output (not guessed) and cross-checked internal consistency
  (`tp + fn == gold_units` for every changed row) before writing them in.
- **`docs/superpowers/specs/2026-07-10-wiki-eval-experiment-v2.md:320` left untouched**
  — it states "5562 = 4032 + 1530 — инвариант эталона", now stale, but design-plan specs
  are dated/frozen decision records per CLAUDE.md conventions and this file wasn't named
  in the task's Step 4 doc list; flagged below instead of edited unilaterally.

## Open questions

- Should `docs/superpowers/specs/2026-07-10-wiki-eval-experiment-v2.md:320`'s stale
  `5562` invariant be corrected to `5551`, and by whom (spec owner vs. this task)?
- The diagnosis's "Interaction with the in-flight gold-cleanup campaign" section flags
  that positional indices in `data/eval/wiki/cleanup/{017,051,057,081}-*.json` shift
  after this fix (the parser-fix-eliminated rows overlap with some of those files'
  manual semantic-removal indices). Not re-indexed here — out of this task's explicit
  scope, needs its own pass before those removal files are next applied.
- Are any cached `reports/terminology/wiki-eval/.../metrics.json` artifacts from past
  full runs now silently inconsistent with the corrected gold? Not investigated —
  those are historical run archives (Hard Invariant: never overwrite/delete prior
  results), left alone by design, but worth an inventory pass if anyone re-reads old
  metrics.json files expecting them to match a freshly-recomputed corpus.

## NOT done (explicit)

- `gt_pilot.jsonl`/pilot-specific artifacts were not touched — confirmed by direct
  inspection that none of the 4 affected articles appears in the pilot title set, so
  nothing there needed re-deriving.
- Gold-cleanup campaign removal files (017/051/057/081) not re-indexed against the new
  `gt.jsonl` (see Open questions).
- `docs/superpowers/specs/2026-07-10-wiki-eval-experiment-v2.md` not amended.
- No network calls beyond `git push`; no LLM calls; predictions (`pred.jsonl` files)
  were never read for writing, only read-only by the (already-existing)
  `test_wiki_metrics_v3.py` regression tests to recompute expected numbers.
