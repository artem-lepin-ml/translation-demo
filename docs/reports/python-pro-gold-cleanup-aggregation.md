# Gold-cleanup campaign aggregation — draft anchor exclusions

## Scope

Aggregate the completed 10-wave LLM gold-cleanup campaign (`data/eval/wiki/cleanup/removals-wave{1,2-4,5-7,8-10}/`,
`overrides_wave1.json`, `overrides_wave2.json`) into a single reviewable DRAFT
exclusions file, `data/eval/wiki/anchor_exclusions_draft.json`. Every removal
file and override numbers its anchors (`n`) against the **pre**-parser-fix
`gt.jsonl` (commit `4c77b7c~1`); the current, committed `gt.jsonl` has shifted
tuple indices in 4 articles (017, 051, 057, 081) because commit `4c77b7c`
dropped 56 single-char IPA-template tuples. The task required resolving every
`n` to a stable identity `(token_index, anchor_text, qid, span_len)` in the
pre-fix gold and reconciling that identity against the current gold — never
by index.

`data/eval/wiki/gt.jsonl` was explicitly out of scope for modification and
was not touched (semantic exclusions are pending owner approval).

## Files changed

- **Created** `data/eval/wiki/cleanup/tools/aggregate_exclusions.py` — stdlib-only,
  PEP-8, typed aggregation script. Loads the manifest, pre-fix gold (via
  `--prefix-gold`), current gold, all 100 removal files, and both override
  files; resolves identities; applies restores/add_removals; applies two
  hardcoded cross-wave rules; reconciles against current gold; runs a regex
  sweep; writes the draft JSON; prints a summary table.
- **Created** `data/eval/wiki/anchor_exclusions_draft.json` — the aggregated
  draft: 842 live exclusions, 56 dropped-by-parser-fix entries, 1 restored
  entry, 1 sweep candidate, 3 open questions. `note` field embeds the current
  git rev of `gt.jsonl` (`4c77b7c`).
- **Not changed**: `data/eval/wiki/gt.jsonl` (verified via `git diff HEAD~1 --
  data/eval/wiki/gt.jsonl` — empty).

Commit: `8239357bd93cd281107c032b7171b24ad2712c24` on branch
`claude/ner-translation-config-b0ozsc`. Not pushed.

## Decisions & rationale

- **Identity-based reconciliation, not index-based.** Every flag resolves to
  `(token_index, anchor_text, qid, span_len)` in the pre-fix gold, then
  membership in current gold is checked by identity presence (`Counter` per
  article), never by re-using the shifted index. This is the load-bearing
  correctness requirement of the whole task.
- **Sanity gate before doing any work.** Manifest `n_anchors` vs. pre-fix
  `len(gt_tuples)` was checked per article (in manifest order) before
  building any exclusion; all 100 matched, so the run proceeded without
  needing to stop.
- **Hard-error philosophy applied broadly, not just where explicitly listed.**
  Beyond the required checks (`n` out of range; `dropped` outside the 4 known
  articles; override anchor mismatch), the script also hard-errors on: a
  `remove` entry missing its `reasons` key; a `restore`/`add_removals`
  referencing an (article, n) not in (respectively: already in) the base
  flagged set; and an override `add_removals` colliding with an existing
  flag. None of these fired on the real data — verified empirically, not
  assumed — but they exist so a future re-run over dirtier data fails loud
  rather than silently double-counting.
- **`provenance: "wave"` is a single literal, not per-directory.** Per the
  spec's exact enum `"wave|override-wave1|override-wave2|cross-wave"`, all
  four `removals-wave*` directories collapse to the one `"wave"` value; the
  wave-directory breakdown itself is only surfaced in the printed summary
  (`per-wave-dir flag counts`), not in the JSON schema.
- **Cross-wave rule 6a (`«исторический источник»`) scoped to article 004 only**,
  matched via a stem regex `^истор\w*\s+источник\w*$` covering inflected
  forms (`историческим источником`, `историческому источнику`), per the
  spec's explicit example. Scanned only article 004's pre-fix tuples, per the
  spec ("Article 004: ..."), not the whole corpus — found exactly one match
  (n=3), added with `provenance: "cross-wave"`.
- **Pinyin sweep (6b) and regex sweep (7) both scan CURRENT gold**, for
  consistency (7 explicitly says "over CURRENT gold anchors"; 6b doesn't say
  either way, so the same convention was applied). Since none of the pinyin
  occurrences fall in the 4 parser-fix-affected articles, prefix vs. current
  made no practical difference here, but the choice is principled rather
  than incidental.
- **Regex sweep order matters and is documented in-line.** `bare-number` is
  checked before `year` so a plain digit string is tagged once, not twice
  (the `year` regex's marker groups are optional and would otherwise also
  match bare digits); `catalog-code` and `scripture-abbrev` follow. Only the
  first matching rule is recorded per anchor.
- **Duplicate-identity handling (spec point 5) computed against the
  PRE-fix gold, not current.** The one real duplicate phenomenon in this
  corpus (6 identity groups / 12 flagged `n`'s, all in article 081, all
  single-char IPA tuples) exists only pre-fix — current gold has **zero**
  duplicate-identity groups anywhere (verified by a full-corpus scan), since
  both copies of each duplicate got dropped by the parser fix. This is
  reported (count + list) in the script's stdout, not as a JSON field (the
  spec's JSON schema has no field for it).
- **`resolve()` is the single point of `n`→identity mapping**, reused
  identically for base removal files, both override files, and the
  cross-wave rule — avoids three subtly different implementations of the
  same lookup.
- Followed the provenance-comment header style and `ROOT = Path("/home/user/translation-demo")`
  hardcoding convention already used by the sibling tools in
  `data/eval/wiki/cleanup/tools/` (`build_lists.py`, `enumerate_misses.py`,
  `replay_analysis.py`).

## Open questions

Carried into the draft JSON's own `open_questions` array (not resolved by
this script — for owner review):

1. `overrides_wave1.pending_owner` verbatim: ancient-language abbreviated
   tags in article 010 (хетт., аккад., урарт., ассир., арм., хеттск.,
   ассирийск.) — final bucket undecided.
2. Modern political institutions kept with KEEP-bias in 072 (Согдиана) / 073
   (Сокровища Сеусо).
3. Article 089 «золото» removed as generic material while электрум/лазурит
   kept as specialized — generic-vs-specialized material line needs
   confirming.

Additionally, for the calling agent/owner: the single sweep candidate
(article 094, «пиньинь», token_index=5) is a genuine gap in wave 8-10's
coverage — worth a quick owner/agent look before the draft is approved, since
its 8 sibling occurrences across the corpus were all flagged consistently.

## NOT done

- **gt.jsonl was not modified** — by design; this was an explicit
  out-of-scope constraint, not an oversight.
- **The draft exclusions were not applied anywhere** — no consumer of
  `anchor_exclusions_draft.json` was wired up; this task only produces the
  file for owner review.
- **The 3 open questions were not resolved** — they are surfaced, not
  answered; resolving them requires an owner ruling.
- **The 1 sweep candidate (article 094 «пиньинь») was not auto-excluded** —
  per spec, sweep candidates are listed for review, never auto-applied.
- **No test suite was added.** The task specified a one-shot aggregation
  script with inline hard-error validation as its correctness mechanism
  (verified via two full runs: hard-error checks all passed, and the two
  runs produced byte-identical output). No `pytest` coverage was requested
  or added; if this script is expected to be re-run routinely (e.g. after a
  future wave), it would be worth adding a small regression test pinned to
  the current `data/eval/wiki/cleanup/` inputs.
- **Not pushed** — commit `8239357` stays local on
  `claude/ner-translation-config-b0ozsc` per the task instructions (no push
  requested).
