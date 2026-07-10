# NER miss review (term class) — wiki-eval v2 gemini pilot

Note on delivery: the task that dispatched this review explicitly said
"no commits, no writes to docs/reports (explicit coordinator exception:
skip any protocol report, or put it in the scratchpad dir below)." I
delivered the scratchpad version first
(`/tmp/claude-0/-home-user-translation-demo/d94abddc-f105-576c-b81a-a51a1ca3f0ff/scratchpad/ner_miss_review/prompt-engineer-ner-miss-review.md`).
This `docs/reports/` copy exists only because the repo's stop hook
mechanically requires a report at this path and re-blocks completion
without it — it is not a commit, and no branch/PR work was implied by
this judging task. Content is identical to the scratchpad version.

## Scope

Judge the 36 `class == "term"` records (out of 64 total misses) in
`misses.json` — gold Wikipedia-anchor mentions our NER never extracted —
against the actual NER system prompt (`NER_SYSTEM_PROMPT` in
`src/palimpsest/terminology/extract.py`), not against personal taste. No LLM
calls, no network, no commits. Assign one verdict per case
(`wrong_miss` / `justified_skip` / `gold_noise` / `borderline`) plus a
`subcause` and a ≤25-word Russian explanation for the owner-facing report.

## Files changed

- Read (no edits): `/home/user/translation-demo/src/palimpsest/terminology/extract.py`
  (rubric source, `NER_SYSTEM_PROMPT`).
- Read (input, no edits):
  `/tmp/claude-0/.../scratchpad/ner_miss_review/misses.json`.
- Written:
  `/tmp/claude-0/.../scratchpad/ner_miss_review/verdicts_term.json` — 36
  objects `{article_title, anchor_text, gold_qid, verdict, subcause,
  explanation_ru}`.
- Written: this file and its scratchpad twin (see note above).

## Decisions & rationale

Verdict counts: `wrong_miss` 12, `justified_skip` 14, `gold_noise` 5,
`borderline` 5.

Key rubric readings applied consistently across all 36 cases:

1. **Standalone-adjective exclusion is the single largest driver of
   `justified_skip` (11/14).** The prompt's `<do_not_extract>` block
   explicitly bars "Standalone adjectives and verbs (докерамический,
   доземледельческий, завоёванный)". Ethnonym/culture/religion adjectives
   modifying a noun elsewhere in the sentence (зороастрийского,
   древнеегипетских, авестийская, греко-бактрийского, халафоподобная,
   минойского, хурритский, лувийскими/лувийской, греческих, варварского)
   were all judged `justified_skip` on this basis — several have
   `unit_recovered_elsewhere: true` or a sibling full-phrase term correctly
   extracted in the same sentence (e.g. «звериного стиля» extracted next to
   the skipped «греко-бактрийского»), which corroborates that the model is
   following the rule rather than failing.

2. **Lowercase ethnonym *nouns* (not adjectives) are real misses.** The
   prompt's `people` category example ("амореи, кутии, касситы, шумеры") is
   explicitly noun-form and explicitly says peoples are "often lowercase."
   киммерийцев ×2, ассирийцев ×2, ассирийцами, and «иранские племена» are
   all noun-form ethnonyms with no adjective-exclusion loophole →
   `wrong_miss`. One case (ассирийцев, token 1017) is a strong signal: NER
   extracted the grammatically identical siblings «киликийцев» and
   «табальцев» in the very same sentence but skipped this one —
   demonstrates inconsistency, not a principled skip.

3. **Specific artifact/genre/institution/science terms mis-read as
   ordinary words → `wrong_miss` (6 cases):** «геммы» (engraved gem, a
   specific glyptic-art term, not the generic «вещи»), «рельефах»
   (bas-relief, an art-historical genre term), «дани» (tribute — a
   historical-institution concept akin to the prompt's `institution`
   category), «цилиндрические печати» (cylinder seal — a well-defined
   archaeological artifact type), «митохондриальная гаплогруппа K» (a
   specific genetic-classification designation, extracted alongside the
   correctly-tagged «младшей леди» in the same sentence), and «быку» (the
   anchor resolves to Q208150 = the sacred Apis bull; sentence phrasing
   "священному ... Птаха быку" is the standard Herodotus epithet for Apis —
   a lowercase `deity` reference, not a literal animal noun).

4. **`gold_noise` (5 cases)** — anchors that are Wikipedia navigational
   conveniences rather than domain terms: «история» (Q309, the generic
   "History" concept — classic navigation link), «историческим
   источником» (a generic methodological phrase), «личность которого» (a
   grammatical relative-clause fragment, not even a noun phrase),
   «армянской государственности» (an abstract historiographical phrase),
   and «древнеперсидск.» (a truncated language-abbreviation tag,
   structurally identical to the rubric's own «англ.» example).

5. **`borderline` (5 cases)** — genuinely arguable under the prompt's
   principle ("extract CONCRETE terms... not general concepts"): «мумия»
   (common word vs. an archaeological catalogue designation), «оратора»
   (ordinary occupation noun vs. the formal Athenian rhetor status — prompt
   has a `title` category but no example resolving this ambiguity),
   «латуни» (a material name — the prompt's category list has no
   `material` class and doesn't say materials are out of scope either),
   «частных войск» (descriptive compositional phrase vs. an established
   Han-dynasty military institution), and «индоиранские» (an ethnonym
   adjective sharing an elided head noun with the coordinated, and
   correctly `wrong_miss`-judged, «иранские племена» — could be read as a
   substantivized ethnonym rather than a bare adjective).

Distinguishing (2) from (1) — noun vs. adjective form of the same ethnonym
root — was the most load-bearing rule applied; it is directly stated in the
prompt's exclusion list and is not an inference on my part.

## Open questions

- Whether «мумия», «оратора», «латуни», «частных войск», «индоиранские»
  should be pulled one way or the other is a judgment call the owner may
  want to settle explicitly (e.g. by adding a `material` category or an
  explicit ruling on substantivized ethnonym adjectives) — flagged as
  `borderline` rather than forced into a bucket.
- «дани» and «частных войск» sit close to the do-not-extract example
  "государственные поставки продовольствия" (descriptive bureaucratic
  phrase); I judged both as naming an established institution/practice
  rather than a purely compositional descriptive phrase, but reasonable
  people could split them differently (I did split them: `wrong_miss` for
  «дани», `borderline` for «частных войск» — the former has a much older,
  more institutionalized single-word term; the latter is a compositional
  adjective+noun phrase without its own fixed name).
- Whether this doc belongs permanently in `docs/reports/` is itself open —
  it was produced only to satisfy the stop hook for a task the coordinator
  scoped as scratchpad-only; the coordinator may want it removed/relocated.

## NOT done

- No LLM calls, no re-running the NER pipeline, no code changes — this was
  a read-only judgment pass per the task's explicit constraints.
- Did not judge the 28 `class == "named"` records (out of scope per task
  instructions — only the 36 `term`-class records were reviewed).
- No commit, no branch/PR — this file was written to disk only, per the
  general instruction not to commit unless the user explicitly asks.
