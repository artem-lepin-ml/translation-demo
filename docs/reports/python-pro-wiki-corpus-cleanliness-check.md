# python-pro: wiki-corpus-cleanliness-check

## Scope

Verify the cleanliness of the 100-article Russian Wikipedia corpus used by
the NER+grounding eval ([docs/stages/wiki-eval.md](../stages/wiki-eval.md)):
confirm every cached Parsoid HTML file resolves via the exact filename
convention used by `wiki_gt.py` / `scripts/wiki_eval.py`, confirm
`tokenize.tokens(flatten(html))` is byte-identical to the corresponding
`gt_v2.jsonl` `tokens` field for all 100 titles, scan the flattened text for
HTML/wiki-markup residue (10 named flag categories), flag suspicious
statistical outliers, and compute corpus-wide paragraph-token-length
distribution stats. Read-only audit against `data/eval/wiki/` — no eval
code, tokenizer, or corpus data file was modified; the only write is this
report plus scratch analysis artifacts kept outside the repo.

## Files changed

None under `src/`, `data/`, or `scripts/` — this was a read-only audit of
existing corpus/eval assets. Only this report was added to the repo.

Analysis artifacts (script + raw JSON outputs) were written to the session
scratchpad, not the repo, per the dispatching task's instruction to keep
audit outputs out of `data/`/`src/`:
`/tmp/claude-0/-home-user-translation-demo/05920843-8f24-5b25-91be-a7e269c94143/scratchpad/corpus_check/`
(`check_corpus.py`, `dump_flags.py`, `report.json` — 100 per-article records,
`summary.json` — corpus totals/flags/distribution). These are ephemeral and
not part of the repo's durable state; reproducing them only requires
re-running `check_corpus.py` against the same corpus.

## Decisions & rationale

- **Cache-filename convention**: replicated `wiki_gt._safe_filename(title)`
  (`re.sub(r"[^\w\-.]", "_", title, flags=re.UNICODE)`) + `.html`, joined to
  `data/eval/wiki/pages/`, confirmed at both call sites —
  [wiki_gt.py:107](../../src/palimpsest/terminology/evaluation/wiki_gt.py#L107)
  and
  [scripts/wiki_eval.py:917](../../scripts/wiki_eval.py#L917) /
  `:964` (`Path(cache_dir) / f"{wiki_gt._safe_filename(title)}.html"`).
  Grepped both usages before trusting the convention rather than
  reconstructing one from priors.
- **GT token field**: `gt_v2.jsonl` records carry the token list in the
  `"tokens"` key, confirmed by reading `build_gt()` in
  [wiki_gt.py:443-454](../../src/palimpsest/terminology/evaluation/wiki_gt.py#L443)
  (`"tokens": flat_tokens`).
- **Environment**: used the repo's own `uv run python` (first invocation
  built the `.venv`, ~90s) rather than falling back to system pip — `uv.lock`
  was present and `uv` resolved cleanly. Confirmed `bs4` 4.14.3 / `lxml`
  6.1.0 inside that venv.
- **GT-keying sanity check**: before joining on `title`, diffed the title
  sets of `titles_v2.txt` and `gt_v2.jsonl` — 0 titles on either side only, 0
  duplicates in either file. Confirmed `gt_v2_sub20.jsonl` was ignored per
  the task's instruction (a 20-row subset, not used in this check).
- **Flag pattern set**: implemented the 10 named categories from the task
  (raw tags, HTML entities, wiki templates, wiki links, math residue, CSS/JS
  leakage, footnote brackets, editorial markers, control chars, replacement
  char) as compiled regexes; `control_chars` handled separately via
  `unicodedata.category(ch) == "Cc"` (excluding `\n`) since it's a
  category-based scan, not a fixed-string/regex match like the others.
- **Percentile method**: hand-rolled linear-interpolation percentile
  (numpy-equivalent) rather than adding a `numpy`/`scipy` dependency to a
  one-off script, per the project's "idiomatic-first, no speculative
  dependencies" convention.
- **Non-Cyrillic ratio**: computed over Unicode "letter" characters only
  (`[^\W\d_]`, excluding digits/punctuation/underscore) against the literal
  Cyrillic block `U+0400`–`U+04FF`, per the task's "letters only" qualifier.

## Findings summary

- 100/100 titles resolved via the cache convention; 100/100
  `tokens(flatten(html)) == gt_v2["tokens"]` exact match; zero token
  mismatches.
- Corpus totals: 160,836 tokens, 2,553 non-empty paragraphs; per-paragraph
  token-length distribution p10=14, p50=54, p90=123, max=392, mean=63.0.
- 9/100 titles flagged or suspicious: 8 carry the `editorial_markers` flag
  (Wikipedia's own inline `[источник не указан N дней]` maintenance markup —
  real article-body text, not an extraction artifact, since `flatten()` only
  drops `infobox`/`navbox`/`reference`/`mw-editsection`-classed tags plus
  `table`/`style`/`script` elements, not inline maintenance templates
  rendered as plain text); 1 (`Калинга (государство)`) trips
  `total_text_lt_1000_chars` at 854 chars / 124 tokens — manually inspected
  the full extracted text and confirmed it is a genuine short Wikipedia
  stub, not truncated/garbled content.
- Zero occurrences anywhere in the 100-article corpus of: raw HTML tags,
  HTML entities, `{{ }}` template braces, `[[ ]]` wiki-link brackets,
  LaTeX/math residue, `style=`/`class=`/`function(` leakage, `[N]` footnote
  brackets, stray Unicode control chars, or U+FFFD replacement chars. No
  paragraph exceeds 8000 chars, no article exceeds 30% empty paragraphs, no
  non-Cyrillic-ratio breach.

Full per-title flag detail (title, count, verbatim ±60-char excerpt) was
delivered in chat to the dispatching orchestrator; not duplicated here to
respect single-source-of-truth — see `summary.json` /`report.json` in the
scratchpad path above for the machine-readable version.

## Open questions

- Whether the 8 `[источник не указан ...]` occurrences (and any similar
  inline Wikipedia maintenance-template text surviving `flatten()`) should be
  stripped before this corpus is used for paragraph-level translation eval —
  `flatten()` currently only drops `infobox`/`navbox`/`reference`/
  `mw-editsection`-classed tags and `table`/`style`/`script` elements, not
  this class of inline marker. Design question for whoever owns
  `wiki-eval.md`; out of scope for this read-only audit to decide or fix.
- Not investigated: `data/eval/wiki/pages/` holds 119 cached HTML files
  against 100 titles in `titles_v2.txt` — plausibly pilot-corpus leftovers
  (`titles_pilot20.txt` / `gt_pilot.jsonl` reference a smaller, likely
  overlapping set), but unconfirmed. Irrelevant to the 100-title check
  requested since all 100 needed files were found regardless.

## NOT done (explicit)

- Did not modify `flatten()`, `wiki_gt.py`, `tokenize.py`, or any corpus data
  file — audit was read-only against the eval subject matter by design.
- Did not investigate the 19 extra cached files noted above beyond flagging
  the count mismatch.
- Did not propose or make a code change to strip `editorial_markers`
  residue — flagged as a finding only, per the task's ask to detect (not
  remediate) HTML/markup garbage.
- Did not commit this report or any other change — file is left as an
  untracked addition for the dispatching orchestrator/owner to review and
  commit if desired.
