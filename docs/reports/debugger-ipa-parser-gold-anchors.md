# Debugger report — IPA per-phoneme spurious gold anchors

Read-only root-cause diagnosis. Full technical write-up (with diff sketch, per-article
counts, discriminator design notes) lives in scratch:
`…/scratchpad/gold_cleanup/ipa_parser_diagnosis.md`. This report is the process record.

## Scope

Diagnose why `data/eval/wiki/gt.jsonl` carries ~53 spurious single-glyph gold anchors on
«Тронное имя фараона» (Q1413565); locate the gold-builder, root-cause the mechanism,
quantify corpus-wide blast radius, recommend the simplest correct fix, define re-derivation
scope + regression guard. No code/data modified (read-only mandate).

## Files changed

None (diagnosis only). Files inspected:
- `src/palimpsest/terminology/evaluation/wiki_gt.py` — `extract_gt()` 159-255 (builder), the
  `find()` alignment 203-207, tuple emission 244-246, `build_gt()` 386-483.
- `src/palimpsest/terminology/evaluation/tokenize.py` — pinned tokenizer 53-88.
- `src/palimpsest/terminology/evaluation/metrics.py` — Tuple4 consumer 3, 49-50, 117-121.
- `data/eval/wiki/gt.jsonl` (scanned all 100 records); `data/eval/wiki/pages/*.html` (source
  HTML confirmation); `data/eval/wiki/cleanup/{manifest,removals-*}.json` (campaign overlap).

## Decisions & rationale

- **Root cause = mechanism (i):** ru-wiki IPA/transcription template hyperlinks every phoneme
  to its own article; `extract_gt` counts each `<a>` as a gold mention and single-char
  `find()` aliases the glyph onto the host token. Confirmed directly in the page HTML.
- **Blast radius:** 56 spurious tuples across 4 articles (Тронное 52, Веды 2 ➤, Микенская 1 ➤,
  Нур-Адад 1 D) out of 7959; concentrated ~93% in one article.
- **Recommended fix = single-char guard with a letter/digit/mark-or-bracket neighbour test**
  (Option b scoped to single chars). Chosen over pure single-char (kills legit `X/V/У`),
  glued-to-alnum (1 residual `ə` in `(ə)`), and whole-token (false-drops em-dash Roman
  numerals). Yields zero residual, zero false drops. ~10 lines + `n_excluded_symbol` counter.
- **Re-derivation:** offline post-filter of the 56 tuples == fixed-builder output (proven by
  replicating the exact cursor/`find` logic); avoids the no-network constraint. Predictions
  untouched; recompute metrics for the 4 articles only.
- **Campaign interaction:** parser fix makes 52 (081) + 1 (057, D) + ➤ removals redundant but
  shifts positional indices in removal files 017/051/057/081 → regenerate them after
  re-derivation, keeping only semantic removals.

## Open questions

- Should the offline post-filter (fast, no network) or a full `build_gt` re-run (needs a QID
  cache) be used to regenerate gt for the 4 articles? Recommended: post-filter.
- Is any downstream artifact pinning a gt row-count / hash that must be bumped after re-derivation?
- Confirm the 6 kept legit single-char links (esp. `Е→Ечэн`) are desired gold mentions.

## NOT done (explicit)

- No code, data, gt.jsonl, or cleanup file was edited (read-only mandate).
- No network / LLM calls (constraint honored); QID resolution not re-run.
- Fix not applied and no test written — only the diff sketch + regression-guard spec provided.
- Metrics not recomputed; cleanup removal files not re-indexed.
