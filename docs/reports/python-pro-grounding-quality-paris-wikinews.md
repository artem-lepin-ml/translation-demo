# Grounding quality: «Париж» judge_rejected + Wikinews junk candidates

Agent: `python-pro`. Work performed in worktree `/Users/a1111/Projects/Work/worktrees/emnlp-demo-sprint` (branch `feat/emnlp-demo-sprint`); this copy is filed at the main-repo report path per the reporting protocol, the authoritative worktree copy lives at `/Users/a1111/Projects/Work/worktrees/emnlp-demo-sprint/docs/reports/python-pro-grounding-quality-paris-wikinews.md` (task explicitly requested WORKTREE placement, since that's where the code changes live). Lane: `src/palimpsest/terminology/**` + tests only — webapp/frontend untouched.

## Scope

Two owner-reported grounding-quality defects, investigate-then-fix, no paid LLM calls (judge mocked in all tests):

1. **DEFECT 1** — document 10, term «Париж» (context: museum-attribution caption for an ancient artifact) got `judge_rejected` despite an obvious exact-match candidate (Q90, modern Paris).
2. **DEFECT 2** — «Египтяне» candidates included Wikinews-article Wikidata items via the CirrusSearch full-text tier.

### Investigation (DEFECT 1) — real trace pulled from prod

Read-only `GET https://glossa-mt.com/api/documents/10` (per `_term_dict` in `src/palimpsest/webapp/app.py:307-318`, `paragraphs[].terms[].traceJson`), found term id 401, paragraph 59:

- **Term**: surface/lemma `Париж`, context `"Конец XXIII в. до н.э. Париж, Лувр"` (a museum caption: an artifact dated to the 23rd century BC, now held in Paris, the Louvre).
- **Candidates** (5, all exact-label matches on `Париж`): Q90 "Paris — capital and most populous city in France", Q1051013 "Paris FC — football club in France", Q830149 "Paris, Texas" (alias match), Q18331346 "Париж — family name", Q48834322 "Paris FC — women's association football club".
- **Judge verdict** (the smoking gun, `trace.judge.response`):
  ```json
  {"qid": null, "reason": "The context mentions Paris in the 23rd century BC, whereas the provided candidates refer to modern entities, including the city in France, sports clubs, or a surname."}
  ```

**Root cause**: the judge correctly *saw* Q90 (modern Paris, the right answer) among the candidates, but rejected the whole set because it treated the date `"Конец XXIII в. до н.э."` in the context as a hard constraint the *referent itself* must satisfy — i.e. it read the caption as "this term must name something from the 23rd century BC" rather than recognizing the date describes the artifact being catalogued, while `"Париж, Лувр"` states the artifact's present-day location. This is a systemic prompt-reasoning gap, not a candidate-list-quality problem: the 5 candidates were mostly legitimate near-homonyms (2 football clubs, a Texas city, a surname), not junk a P31 filter would remove — confirmed by checking `label_first.py`'s judge-response parsing (`qid=null` → `judge_rejected`, working exactly as designed) and ruling out a parsing bug. It generalizes beyond "Париж": any museum/artifact-caption pattern (`<ancient date> <object>. <modern place>, <modern institution>`) risks the same false rejection for any location term.

Ruled out per the task's suspect list: not a >1-exact-matches parsing bug (the pipeline handled 5 exact matches correctly, escalating as designed); not primarily a candidate-noise problem (see DEFECT 2 below — even with the P31/dedup fix applied, none of the 5 Paris candidates are removed, since none carry a blocklisted P31 and none share an identical `(label_ru, label_en, description)` triple).

### Investigation (DEFECT 2)

`src/palimpsest/terminology/grounding/wikidata.py::search_cirrus` does full-text search (`list=search`) over the whole Wikidata item body, not just labels — it can surface Wikinews-article items (`Q99042315` etc. per the owner screenshot) whose title happens to match the query. `get_entities` already fetches `props="labels|aliases|descriptions|claims|sitelinks"`, so `claims.P31` is available for every candidate at zero extra network cost — it just wasn't being read.

## Files changed

- `src/palimpsest/terminology/grounding/label_first.py` — `DEFAULT_GROUNDING_JUDGE_SYSTEM_PROMPT` gained a `## Context notes` section (DEFECT 1 fix).
- `src/palimpsest/terminology/grounding/candidates.py` — `_NON_ENTITY_P31_BLOCKLIST`, `_p31_qids`, `_is_non_entity`, non-entity filtering + near-duplicate dedup in `generate_candidates`'s enrichment loop, module docstring updated (DEFECT 2 fix).
- `tests/test_terminology.py` — 11 new tests (junk-P31 filtering, dedup correctness + a safety regression, prompt-caveat marker, one full end-to-end mechanism test).
- `docs/stages/terminology.md` — doc-parity: two new Design-decisions bullets + a cross-reference bugfix (see Decisions & rationale).
- `docs/reports/python-pro-grounding-quality-paris-wikinews.md` (this report; worktree copy is authoritative, this is the main-repo-cwd filing).

Nothing else touched. `git status` in the worktree shows unrelated in-flight edits to `src/palimpsest/webapp/{app,db,migrate,precompute,terminology_live,translate}.py` by another agent — not mine, not modified.

## Decisions & rationale

**DEFECT 1 fix — general prompt caveat, not a "Париж" special case.** Added `## Context notes` to the judge system prompt: context can mix a narrated historical period with a modern fact about the same subject (an artifact's current location/caption); an enduring real-world referent (city, country, museum, institution) must not be rejected merely for an era mismatch, only for a genuine identity mismatch. Regression test: `test_grounding_judge_system_prompt_has_temporal_context_caveat`.

**DEFECT 2 fix — cross-checked against `docs/superpowers/specs/2026-07-03-grounding-label-first-design.md` D3/Q1 before writing any code.** That spec explicitly decided to remove the *entity-type* filter (P31/P279 disambiguating "city" vs "football club" vs "person") and explicitly *not* filter disambiguation pages, deferring all of that to the judge via description text. Blindly adding a P31 blocklist including `Q4167410` (Wikimedia disambiguation page) risked silently re-violating that decision. Resolution adopted: the new filter is narrower and orthogonal — it drops Wikidata items that are wiki-maintenance *structure* (a Wikinews article, a disambiguation *page as an object*, a category/template/list page) and can **never** be a valid referent under *any* context, vs. the removed filter's job of guessing which *type* of real-world entity is correct (the judge's actual disambiguation work). Documented explicitly in both the code docstring and `docs/stages/terminology.md` so this isn't misread as a silent reintroduction of the removed filter.

`_NON_ENTITY_P31_BLOCKLIST`: `Q17633526` (Wikinews article), `Q4167410` (Wikimedia disambiguation page), `Q4167836` (Wikimedia category), `Q11266439` (Wikimedia template), `Q13406463` (Wikimedia list article). `_p31_qids`/`_is_non_entity` read P31 from the already-fetched `claims` (zero extra network calls); fall back to a description-text match (`"wikinews article"`) only when an entity has no P31 claim at all. Filter applied before a candidate dict is ever built, so junk never reaches `exact_match`/the judge. Near-duplicate dedup on an identical `(label_ru, label_en, description)` signature (i.e. renders 100% identically to the judge — see `_format_judge_prompt`), keeping the first.

**Safety issue found and fixed during testing (worth flagging explicitly).** My first dedup attempt keyed on `(label_ru, description)` only. Running the full suite caught two real regressions: `test_label_first_two_exact_matches_escalates_to_judge_disambiguation` (and 6 related tests) collapsed a genuine Thutmose I / Thutmose II homonym pair down to 1 candidate, because both test fixtures share the same RU label and an empty description — exactly the `>=2 exact matches` scenario the judge escalation exists to disambiguate. A second full-suite run (after fixing that) then caught `test_terminology_live.py::test_run_disambiguation_judge_bridge_resolves_yellow` failing the same way for a different reason: that file's own `_entity()` fixture gives *every* entity an identical placeholder description (`"a test entity"`), so `(label_ru, description)` alone still collided. Both are realistic risks, not just fixture artifacts — real Wikidata items can legitimately share a generic description. Fixed by requiring the *full* displayed signature (`label_ru, label_en, description`, all non-empty) to match before deduping — this only fires on genuinely redundant duplicate content, never on same-label homonyms that differ in `label_en` or lack a description.

**Doc-parity decisions** (`docs/stages/terminology.md`): fixed a pre-existing cross-reference bug in the "No type filter" bullet — it cited risk **R7** (which is actually the design spec's ё/е-folding risk) for the "no anachronism blocklist" trade-off, corrected to **R1** (the design spec's actual label for that risk); fixed it now because I was already editing that exact bullet for doc-parity on this same decision. Added two new bullets under Design decisions documenting the P31 blocklist + dedup mechanism and the judge prompt's temporal-context caveat, both explicitly cross-referenced against the D3/Q1 decision they are — and are not — in tension with.

## Tests

Added to `tests/test_terminology.py` (all with mocked `WikidataClient`/judge, no network, no paid LLM calls):

- `test_candidates_filters_wikinews_article_via_p31` — reproduces the real «Египтяне» CirrusSearch shape.
- `test_candidates_filters_each_non_entity_p31_blocklist_value` — all 5 blocklist QIDs dropped.
- `test_candidates_wikinews_description_fallback_when_p31_missing` — fallback path.
- `test_candidates_legitimate_entity_with_no_p31_is_not_dropped` — filter isn't "reject anything without P31".
- `test_candidates_dedup_identical_label_and_description` / `test_candidates_dedup_keeps_distinct_descriptions_for_same_label` / `test_candidates_dedup_does_not_merge_candidates_without_a_label` / `test_candidates_dedup_does_not_merge_homonyms_with_empty_descriptions` — dedup correctness + the safety regression above, permanently guarded.
- `test_grounding_judge_system_prompt_has_temporal_context_caveat` — DEFECT 1 prompt-fix marker.
- `test_label_first_paris_class_scenario_filters_junk_and_judge_grounds_city` — full end-to-end mechanism test: 5 raw hits (real Paris + Wikinews junk + a synthetic literal-duplicate club pair + a legitimate Texas-city candidate) → junk filtered, duplicate deduped → 3 candidates reach the trace → 2 genuine exact matches (Q90, the club) still force judge escalation → mocked judge picks Q90 → `difficulty=yellow`, `resolved_by=llm_disambiguation`, `grounded.qid=Q90`. Proves the mechanism (clean candidate list reaching the judge) works; the actual real-world Paris candidate list is *not* shrunk by this fix (none of its 5 real candidates are junk or literal duplicates) — DEFECT 1's fix is carried entirely by the prompt change.

**Run results:**
- `tests/test_terminology.py` + `tests/test_wikidata_client.py`: **121 passed**.
- Full backend suite (`.venv/bin/python -m pytest -q`): **609 passed** at the point my changes were complete and isolated (verified run).
- A later re-run showed **1 unrelated failure**: `tests/test_model_registry_v2.py::test_owner_edited_api_key_not_clobbered_on_second_run`, caused by a concurrent in-progress edit to `src/palimpsest/webapp/migrate.py` by another agent in this shared worktree (`git status` shows `app.py`, `db.py`, `migrate.py`, `precompute.py`, `terminology_live.py`, `translate.py` modified, uncommitted, outside my `terminology/**` lane). Confirmed unrelated: deselecting that one test gives **608 passed, 1 deselected**; the failure is about model-registry API-key/params persistence, nothing terminology-related touches it.

## Open questions

- Whether the owner wants a live re-run of grounding on document 10 (or the canonical demo doc) to visually confirm «Париж» now grounds — explicitly deferred to the orchestrator per the task note ("your fixes apply to future extractions; the orchestrator will re-run terminology on the canonical doc afterwards").
- Whether risk R1 (deterministic branch has no defense if a club/band is the *sole* exact label match — unrelated, pre-existing, still open) should get any attention in this sprint; left untouched here since neither defect required it and it's a separate, already-tracked risk.

## NOT done

- **Live re-run on the canonical doc**: not run here, explicitly deferred to the orchestrator (see task note quoted above).
- **DB-seeded `grounding_config.prompt`** (webapp `migrate.py`/`seed.py` seed rows): not directly edited — those modules import `DEFAULT_GROUNDING_JUDGE_PROMPT` rather than embedding a copy, so they will pick up the new prompt automatically on the next re-seed/migration; webapp files are explicitly another agent's lane right now, so no edit was made there even though it would be a 0-line no-op.
- **`known_issues.md`**: not touched. The existing R1 risk entry (deterministic branch has no defense if a club/band is the *sole* exact label match) is unrelated to and unresolved by this fix; no new entry was added since both defects are fixed at the root here, not worked around.
- **Paris FC men's/women's dedup scenario**: present in the docs/tests as an *illustrative*, not load-bearing, example for DEFECT 1 — the real prod candidates for «Париж» have genuinely distinct descriptions for the two clubs, so the dedup fix does not shrink that specific real candidate list. DEFECT 1 is fixed entirely by the judge-prompt change (Decisions & rationale above), not by candidate-list cleanup.
- **No commit made** — per lane instructions, changes are left uncommitted in the worktree for the orchestrator to review/integrate.
