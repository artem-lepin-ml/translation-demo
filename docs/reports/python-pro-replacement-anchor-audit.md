# python-pro — WikiHist replacement-articles anchor-relevance audit

Report location note: the launching agent gave a STRICT CONSTRAINT for this task —
another agent was concurrently committing to `/home/user/translation-demo`, so this
agent was forbidden from any git write and from creating/modifying/deleting ANY file
inside the repo working tree; all writes had to stay under the session scratchpad.
That constraint overrides the standard `docs/reports/` reporting protocol, so this
report is filed under the scratchpad's own `.../audit/reports/` directory instead of
`docs/reports/`. No repo file was read-modified or written by this task.

## Scope

Run the same anchor-relevance audit the 10-wave WikiHist gold-cleanup campaign ran on
the original 100 articles, on 5 new replacement articles joining the gold corpus:
Библ, Древнеегипетский календарь, Публий Корнелий Лентул Кавдин (консул), Розеттский
камень, Триумф. Three steps: (1) adapt `build_lists.py` to build numbered per-article
anchor lists with reconstructed sentences for the 5 records in `new_records.jsonl`,
(2) apply `audit_prompt_v11.md` plus the campaign's post-prompt codified precedents
(language-tag vs full-language-name, generic-surface words, pop-culture, genetics/
chemistry, bare years/materials/disciplines) to every anchor, one article at a time,
(3) write per-article REMOVE decisions + a summary.

## Files changed

All under the session scratchpad, none inside the repo working tree:

- `SCRATCHPAD/gold_cleanup/replacements/audit/build_lists_replacements.py` — adapted
  copy of `data/eval/wiki/cleanup/tools/build_lists.py` (repo file was only *read*,
  never modified); reuses `_sentence_spans` from `palimpsest.terminology.extract`
  verbatim, reads `new_records.jsonl` (5 records, alphabetical R01..R05 numbering)
  instead of `gt.jsonl` (100, no article-count assert).
- `SCRATCHPAD/gold_cleanup/replacements/audit/articles/R0{1..5}-<slug>.json` — the 5
  numbered anchor lists (93/53/35/68/57 anchors, 306 total), each anchor with its
  reconstructed, marked sentence.
- `SCRATCHPAD/gold_cleanup/replacements/audit/manifest_replacements.json` — build
  manifest (article/file/anchor-count index + totals).
- `SCRATCHPAD/gold_cleanup/replacements/audit/removals/R0{1..5}.json` — per-article
  `{"remove": [...], "reasons": {...}}` in campaign format.
- `SCRATCHPAD/gold_cleanup/replacements/audit/summary.json` — per-article and
  per-category removal counts.
- This report.

## Decisions & rationale

**Build step**: the run was completely clean — 0 edge cases (no out-of-bounds
anchors, no missing sentence spans, no anchor-outside-sentence cases, no duplicate
tuples) across all 5 records. No `overrides_wave*.json`-style manual patch was needed
at build time.

**Audit step — calibration method**: rather than apply the prompt + precedent bullets
from first principles alone, I cross-checked every non-obvious call against the
original campaign's actual removal log (`SCRATCHPAD/gold_cleanup/all_removals_dump.tsv`,
491 lines) and its two owner-verified override files
(`overrides_wave1.json`, `overrides_wave2.json`). This surfaced several precedents
that changed my initial (prompt-only) reading:
- Common tree/wood species (кедр, кипарис) were REMOVED by the original campaign even
  in artifact/trade-specific contexts (047, 068 — cedar wood for a sacred barge, cedar
  import trade — both removed as "generic flora species"), which is stricter than a
  naive reading of "specialized materials in artifact-specific context = KEEP" would
  suggest. Applied the same to Библ's кедр/кипарис/смолу.
- Bare generic nouns get removed even when a proper name sits *immediately adjacent*
  but outside the anchored span (`всемирного наследия` removed despite "ЮНЕСКО"
  following in the same sentence; `войск` removed despite "Александра Македонского"
  following; `музея` removed with no proper name in span). Applied this to Библ's
  "Всемирного наследия ЮНЕСКО" (this one *does* include ЮНЕСКО in-span, but the
  underlying concept precedent still called for removal), Розеттский камень's
  "форта" (Сен-Жюльен just outside span), Триумф's "форум"/"Большой" (Maximus
  clarification just outside span).
- A full narrative clause containing 3 proper names (Sparta/Persia/Athens) was still
  removed as "full clause linked, not a term" (article 038) — established that
  verb-headed descriptive clauses get removed regardless of embedded proper names,
  distinct from noun-phrase appositives. Applied this distinction to separate REMOVE
  (verb-clauses: "занят французскими войсками", "потерпели в Александрии поражение",
  "идут справа налево", "добавили ещё один день", "возвращался к 1-му") from one
  KEEP-under-doubt noun phrase ("французских войск в Египте" — no finite verb, proper
  name inside the span).
- `жрецов` (bare "priests") was removed as "generic plural noun for priests" (article
  061) even though "titles/offices" is a KEEP category — this recalibrated my initial
  KEEP instinct for Триумф's "Жрецы" and "скоморохи" to REMOVE, since those KEEP
  examples are meant for formal political/administrative offices (консул, претор,
  диктатор, ликтор, легат — none of which the campaign ever removed), not generic
  occupational/performer nouns.
- The task's explicit note that Sirius/Sothis-related calendar realia are wanted
  terminology overrode the general verb-clause-removal pattern for two phrase-form
  anchors in the calendar article ("Сириус начинает появляться на утренней заре",
  "гелиакическое восхождение/восходом") — kept as a deliberate, task-directed
  exception, distinguished from the *modern* astronomy vocabulary in the same article
  ("сидерического", "обыкновенного" year-type terms) which was removed.

**Result**: 39 removals out of 306 anchors (12.7%), heavily concentrated in Триумф
(14/57, driven by 6 `лат.` template tags plus several generic-noun narrative words)
and Библ (14/93, driven by 5 language tags + 3 bare millennium dates + 3 generic
flora/material words). Публий Корнелий Лентул Кавдин is nearly pristine (1/35 — only
a `лат.` tag) since it is dense Roman prosopography (persons, gentes, offices,
peoples, places) that maps almost entirely onto explicit KEEP categories.

## Open questions

Two anchors were kept only via the doubt rule and are flagged to the orchestrator as
genuinely close calls (full list in the JSON return to the orchestrator, reproduced
here):
- R04 n15 «французских войск в Египте» (Q253684) — head noun "войск" is elsewhere
  always removed bare, but the proper name Египте sits *inside* this span (unlike the
  "форта"/"Большой" precedent pattern where the name sits outside), and it is a noun
  phrase, not a narrative clause.
- R05 n22 «пурпурную» — bare color adjective, but describing the *toga picta*'s
  status-marking Tyrian purple in a specific ceremonial-garment context, not an
  incidental color mention.

Two further REMOVE calls were made with lower confidence than the rest (not flipped
to KEEP, but worth a second look): R05 n49 «Большой» and n51 «форум» — both function
informally as short names for real specific places (Circus Maximus, the Roman Forum)
even though the anchor span itself is a bare common word, and no exact precedent for
either root word was found in the original campaign's removal log to confirm the call
either way.

No orchestrator/owner decision is required to proceed — all removal files are
complete and internally validated (see below). The above are flagged for awareness,
not blocking.

## NOT done

- No LLM calls were made for the audit itself — I (the dispatched agent) performed
  the KEEP/REMOVE judgment directly per the task's own instructions, which is exactly
  what step 2 of the task asked for; this is not a shortfall, just noting no separate
  "LLM cleanup pass" tool was invoked.
- Did not attempt a live Wikidata QID label lookup (`wikidata_cache_scratch.jsonl`
  only contains `claims`, not `labels`, for the QIDs I checked — Q21659116,
  Q2331837, Q29410, Q1073942, Q401, Q130842, Q4988656, Q9585, Q125576, Q10914750,
  Q1018471, Q52827, Q115439, Q29945, Q26257 all came back "NOT FOUND" in that cache).
  All decisions instead relied on sentence context + cross-QID consistency checks
  within the 5 articles (e.g. matching an anchor's QID to another anchor's QID with a
  known surface elsewhere in the same or a sibling article) + the original campaign's
  precedent log. This is a reasonable substitute given no network label-lookup tool
  was available to this agent, but it means QID-level disambiguation was inferential,
  not authoritative, for a handful of anchors (documented inline in the reasoning
  above, e.g. "морские суда" / Q21659116, "занят французскими войсками" / Q130842).
- Did not apply the removals to `new_records.jsonl` itself or to any gold corpus file
  — per the task's strict repo-write ban, and because the task asked only for the
  audit artifacts (numbered lists + removal decisions + summary), not for mutating the
  gold file. Applying the removals (producing a cleaned copy) is a follow-up the
  orchestrator can do once these decisions are reviewed.
- Did not verify item-by-item against a second LLM pass or against `docs-keeper`/
  `code-reviewer` — the task explicitly states "the orchestrator verifies your work
  item by item," so no independent verification pass was run here.
- Report was not placed at the canonical `docs/reports/` path (see note at top) due to
  the task's own strict no-repo-write constraint; this is a deliberate deviation, not
  an oversight.
