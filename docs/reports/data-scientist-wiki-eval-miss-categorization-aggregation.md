# data-scientist — aggregate 5-agent miss-categorization wave (gemini 10-article slice)

## Scope

Aggregate a finished 5-agent categorization wave (74 misses from the gemini
`google--gemini-3.1-flash-lite--Google-AI-Studio` wiki-eval run, first 10 articles) into
one committed deliverable: merge + validate the 5 chunk files against the source harness
output, build the 4 required tables (category distributions, rescue-mode breakdown, NER
category distribution, search-stage uplift projection), write the two repo artifacts, and
commit + push. Read-only inputs were in the session scratchpad
(`/tmp/claude-0/-home-user-translation-demo/d94abddc-f105-576c-b81a-a51a1ca3f0ff/scratchpad/miss-analysis/`);
no analysis/categorization was redone by hand — this task was purely aggregation,
validation and reporting of work already produced by the 5-agent wave.

## Files changed

Both committed in `6db3107` on branch `claude/ner-translation-config-b0ozsc` (pushed,
fast-forward, no reject):

- `data/eval/wiki/cleanup/miss_categorization_gemini10.json` — merged 74-entry list +
  `tables` object (2a/2b/2c/2d) + provenance header (source run dir, harness tool path,
  5-agent wave description, date).
- `docs/reports/wiki-eval-miss-categorization-2026-07-10.md` — the owner/team-facing
  English report: method, all 4 tables, the explicit gold-noise/metric-artifact list
  with QIDs, the uplift projection, and an explicit "What was NOT done" section.

Nothing else was touched. `git status` before staging showed only these two new paths
plus a separate concurrent agent's untracked files under `reports/terminology/wiki-eval/`
and `reports/terminology/wikidata_cache_*.jsonl` — left alone per the task's explicit
instruction (staged only my two files by name, never `-A`).

## Decisions & rationale

1. **Validation approach**: cross-checked merged `(gold_qid, article)` keys 1:1 against
   `gemini_misses_10.json`'s 74 `misses` entries (set difference both directions empty,
   no duplicate keys on either side), plus checked every merged `surface` appears in the
   corresponding source entry's `gold_mentions[*].anchor_text` (handles multi-mention
   misses where agents used the first mention's anchor text as `surface`). Result: 74/74,
   zero discrepancies — reported as fact, not asserted without the check.

2. **rescue_by normalization (semantic, not spelling)**: `primary_category` and
   `outcome_class` had zero spelling drift across the 5 chunks (clean small value sets).
   `rescue_by` however had a *semantic* inconsistency: 3 entries (Q7209, Q1023301,
   Q1790257) were labelled `none` by their originating agents despite their own evidence
   text stating the correct real-world entity was already present among the harness's
   returned candidates — objectively the same situation as Q373521 (Псамметих III),
   which a different agent correctly labelled `already-hit-in-reality`. I verified this
   claim independently against `overlapping_pred_mentions` in the source JSON for all 4
   entries before normalizing (confirmed the "already surfaced" QID is genuinely present
   in each candidate list), then relabeled the 3 for consistency and documented the
   normalization explicitly in both artifacts rather than silently overwriting.

3. **`alt-names` = 0 finding**: none of the 74 entries carry `rescue_by=alt-names`. I
   verified this wasn't an artifact of my normalization (it was 0 before and after) and
   is a real property of this slice — flagged as a notable finding rather than treated as
   a missing category to paper over. Three agents (chunks 4-5) explicitly noted in their
   evidence that alt-names was considered and rejected for specific entries (Вашуканни,
   Айраратское царство, Гузана), which corroborates it's a genuine null result, not an
   oversight.

4. **Metric-artifact bucket for table 2d**: defined as the union of `gold-noise`-category
   entries within the 58 search-stage misses (5 entries: 4 `already-hit-in-reality` + 1
   `none`/mis-annotated-no-hit). Verified no double-counting against the 52 `label-guess`
   entries (disjoint by construction — no gold-noise entry has `rescue_by=label-guess`).
   Listed each of the 5 explicitly by QID pair (gold/correct) in the report per the task
   instruction, flagged FOR OWNER DECISION, `gt.jsonl`/`anchor_exclusions.json` untouched.

5. **Did not touch gold data.** Per explicit task instruction and CLAUDE.md's "never
   delete/silently alter irreproducible eval artifacts" spirit — this task was scoped as
   categorization + reporting, gold corrections are an owner call.

## Open questions

- Whether the owner wants the 5 flagged gold-noise/metric-artifact rows (Псамметих III
  Q373521→Q316278 relabel; Западная Хань Q7209→Q1072949; Куммух Q1023301→Q1792017; Кумме
  Q1790257→Q1792004; скифский звериный стиль Q131802→Q1092377) actually corrected in
  `gt.jsonl`/`anchor_exclusions.json` — left as a decision, not actioned.
- Whether `alt-names` as a rescue mode is worth keeping in the schema going forward given
  it scored 0/74 on this slice, or whether that's slice-specific (only 10 articles, one
  model) and should be re-tested on a larger/different sample before being deprioritized
  in any future search-stage design.
- The Q12087706 ("ванов"/"Ван") irreducible homograph case implies a ranking/disambiguation
  gap distinct from label-naming; not investigated further here (out of scope — this was
  an aggregation task, not a fix task).

## NOT done

- No implementation/fix work for the `morphology-gap`/`label-guess`-rescuable misses
  (this was categorization + reporting only, explicitly out of scope per the task).
- No gold-data corrections (`gt.jsonl`, `anchor_exclusions.json`) — flagged only.
- Deepseek and gemma wiki-eval runs (present as untracked dirs from a concurrent agent)
  were not analyzed — only the gemini 10-article slice was in scope.
- Did not re-derive or second-guess the 5 agents' individual Wikidata-API verifications
  (`checked_wikidata=true` on all 74) beyond the specific cross-checks described above
  (candidate-list presence checks for the 4 normalized entries); took their empirical
  `wbsearchentities` replications as given, as instructed.
