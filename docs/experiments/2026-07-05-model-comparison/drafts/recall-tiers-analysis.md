> ⚠️ **SUPERSEDED** by [docs/paper/sections/](../../../paper/sections/) (protocol v3, 2026-07-10). Kept for
> historical reference only. The tier concept this analysis motivated survives as
> `data/eval/wiki/tier_assignment.json`, now consumed directly by
> `metrics.aggregate_corpus_v3` — see [docs/stages/wiki-eval.md](../../../stages/wiki-eval.md).

# Reference-annotation noise analysis — deterministic recall tiers

**Question (owner hypothesis).** Many lowercase ("term") reference links in the
Wikipedia-hyperlink GT are noise for a *terminology* task — plain dictionary
words, generic concepts, meta pages. Design a **deterministic** filter of GT
tuples by Wikidata properties of the *target QID* that defines 2–3 nested metric
tiers, revealing recall "as the junk is progressively cut away".

**Data.** `data/eval/wiki/gt_v2.jsonl` (100 RU ancient-history articles, 7959
reference tuples, 3868 unique target QIDs). Matched/unmatched split via
`palimpsest.terminology.evaluation.matching.match_m3` **per article** (document-
level: a GT tuple is matched iff its QID appears anywhere in that article's
predictions). Predictions: gemini-3.1-flash-lite and deepseek-v4-flash runs.
Claims for all 3868 target QIDs loaded from the shared cache
`reports/terminology/wikidata_cache.jsonl` — **0 network calls** (the GT build
already cached every `props=claims,en|ru` single-QID lookup). Labels fetched
fresh (103 batched calls, no 429s).

---

## 1. Headline reproduction (sanity)

| Metric | value | GT check |
|---|---|---|
| total tuples | 7959 | ✓ |
| unique target QIDs | 3868 | ✓ |
| gemini M3 recall (doc-level) | **0.690** | matches 0.690 ✓ |
| deepseek M3 recall (doc-level) | **0.614** | matches 0.614 ✓ |
| gemini named / term | 0.828 / **0.414** | — |
| deepseek named / term | 0.733 / **0.376** | — |

named = surface first char uppercase (`surface[:1].isupper()`, the harness's own
rule, `scripts/wiki_eval.py:1155`); term = lowercase. Split: 5312 named / 2647 term.

> **Note on the 0.291/0.786 quoted in the brief.** The `metrics.json` `type`
> slice reports term recall 0.343 (gemini), *not* the 0.414 above, because the
> slice filters *predictions* by the GT token-index map before matching — an
> artifact of index-keyed slicing that under-counts M3 (which is meant to credit
> a QID found *anywhere*). The instructed `match_m3`-per-article gives 0.414; I
> use that throughout. The exact 0.291/0.786 pair is from neither current
> `metrics.json`, so it is likely an older snapshot/averaged figure. Direction
> is identical: a large named/term gap.

---

## 2. What ARE the unmatched-lowercase targets?

Unmatched-term population (gemini): **1551 tuples / 1025 unique QIDs**. Categorized
by target-QID Wikidata properties:

| n | verdict | category | 5 examples (surface → QID → label) |
|---:|---|---|---|
| 398 | **NOISE** | drop@T2 (generic concept) | генетико-генеалогической→Q913584 genetic genealogy · финик.→Q36734 Phoenician · слоновую кость→Q82001 ivory · клён→Q42292 maple · самшит→Q158703 Buxus |
| 124 | **NOISE** | drop@T1 (meta / calendar) | царь Сидона→Q48963279 *list of kings of Sidon* · ассирийского царя→Q217762 *list of kings of Assyria* · тишриту→Q217782 Tishrei(month) · царю Тира→Q887629 *list of kings of Tyre* |
| 2 | **NOISE** | drop@T2 (writing system) | критские письменности→Q4241360 Aegean scripts |
| 292 | real | class-concept, no P31 | мумия→Q43616 mummy · историческим источником→Q3750478 historical source · артефактов→Q220659 archaeological artefact · геммы→Q1501187 engraved gem · грифонов→Q130223 griffin |
| 250 | real | other concept | оратора→Q12859263 orator · моистов→Q720866 Mohism · рельефах→Q245117 relief sculpture · митохондриальная гаплогруппа K→Q1544376 Haplogroup K |
| 116 | real | polity / dynasty | персами→Q389688 Achaemenid Empire · афиняне→Q844930 Classical Athens · греко-бактрийского→Q488880 Greco-Bactrian Kingdom |
| 95 | real | religion / deity / rite | быку→Q208150 Apis · зороастрийского→Q9601 Zoroastrianism · авестийская→Q83426 Avesta |
| 93 | real | place w/ coords | киликиец→Q620864 Cilicia · нубийцев→Q135028 Nubia · битвы при Пелузии→Q544239 Battle of Pelusium |
| 59 | real | people / ethnic group | ассирийцев→Q377085 Assyrians · иранские племена→Q1672477 Iranian peoples · индо-сакский→Q240123 Indo-Scythians |
| 50 | real | culture / period / style | спартанцам→Q5690 Sparta · неолита→Q36422 Neolithic · средним векам→Q12554 Middle Ages |
| 37 | real | event (battle/war) | войне→Q2116320 Final War of the Roman Republic · дорийского вторжения→Q987129 Dorian invasion |
| 30 | real | title / office / rank | император→Q39018 emperor · монарха→Q116 monarch · ванов→Q12087706 wang |
| 5 | real | person (Q5) | ассирийского наместника→Q273514 Nabopolassar · малолетним сыном Александра→Q207847 Alexander IV |

**Key structural facts about the unmatched-term QIDs (n=1025):** no P31 at all
20.7%; has P279 (class-like) 59.3%; has coords 15.2%; has inception/date 29.8%;
is human 0.5%. **64% have no identity-bearing property (no coord / no date / not
human).**

**The decisive finding.** The "no-P31 / P279-only" mass (mummy, papyrus,
ziggurat, cylinder seal, harem, caste, engraved gem, griffin, satrapy, iwan,
stucco) is **the core domain terminology**, not noise — precisely the terms a
translator of ancient-history text needs grounded. So any *structural* filter
("keep only identity-bearing", "drop all P279 class-concepts") deletes the real
vocabulary. The separable noise is **specific P31 categories**, not a structural
property.

Of the 1551 unmatched-lowercase tuples: **~524 (34%) are filterable noise;
~1027 (66%) are real domain terms the model genuinely fails to ground.**

---

## 3. Tier design (deterministic, target-QID P31 only)

Rule shape (reproducible, no LLM): a target is dropped at a tier iff **every** one
of its P31 classes maps to a noise bucket for that tier. Targets with no P31, or
with any non-noise P31, are kept (protects multi-typed real entities). Noise
buckets are assigned to each distinct P31 class by keyword rules over its
English label + a small override set (`tiers.py`).

- **T0 — R-T0 (raw):** all 7959. Baseline = current M3.
- **T1 — R-T1 (clean):** drop **META** (Wikimedia disambiguation / list /
  category / duplicate / name-convention pages) + **CALENDAR** (year, decade,
  century, millennium, calendar month, temporal entity). Indisputable structural junk.
- **T2 — R-T2 (terminology):** additionally drop **generic lexical concept**
  classes: **LANGUAGE_WRITING** (languages + writing/transcription/romanization
  systems, phonemes, letters, part-of-speech), **TAXON_SCIENCE** (taxa, chemical
  elements, materials, minerals), **UNIT_STANDARD** (units of measurement, ISO/SI
  standards), **ACADEMIC_ABSTRACT** (academic discipline, field of study,
  aspect-of-history, history-of-X, form-of-government, concept, quality, activity).

### Tier evaluation

| tier | n tuples | named / term | gemini M3 | (named / term) | deepseek M3 | (named / term) |
|---|---:|---:|---:|---|---:|---|
| **T0 raw** | 7959 | 5312 / 2647 | **0.690** | 0.828 / 0.414 | **0.614** | 0.733 / 0.376 |
| **T1 clean** | 7796 | 5274 / 2522 | **0.704** | 0.834 / 0.434 | **0.627** | 0.738 / 0.395 |
| **T2 terminology** | 7174 | 5221 / 1953 | **0.741** | 0.841 / 0.474 | **0.663** | 0.745 / 0.444 |

Per-bucket tuple removal: META 74, CALENDAR 89 (→T1 removes 163); LANGUAGE_WRITING
462, TAXON_SCIENCE 61, UNIT_STANDARD 19, ACADEMIC_ABSTRACT 99 (→T2 removes 785 total).
QID-level: 108 QIDs removed at T1, 210 more at T2 (3550 of 3868 survive).

### Rejected alternative — owner's literal "identity-bearing only"

keep iff (coords ∨ inception/date ∨ birth/death ∨ P31=Q5):

| | n tuples | named / term | gemini | deepseek |
|---|---:|---:|---:|---:|
| identity-only | 5599 | 4548 / 1051 | 0.773 | 0.687 |

Higher headline recall — but **wrong**: it removes 2360 tuples (30%), and its
**term recall (0.436) is BELOW T2's (0.474)** on less than half the term tuples.
It discards *correct matches*, not noise. Verified casualties (all
`drop_level` would be dropped): ziggurat Q170153, papyrus Q125576, satrapy
Q15649504, priesthood Q1560314, cylinder seal Q1123756, harem Q165853, caste
Q484416 — plus high-recall class terms (historical ethnic group 0.93, title 0.80,
military rank 1.00). Do **not** use it.

---

## 4. Sanity — 3 articles, dropped links inspected

**KV35YL** (44 tuples, 3 dropped): T1 Тутмос→Q1320491 (*Wikimedia disambiguation
page* — correct); T2 англ.→Q1860 English (gloss), генетико-генеалогической→Q913584
genetic genealogy. All correct. Kept term: мумия(mummy), KV35(tomb). ✓

**Ахеменидские сатрапии** (52, 4 dropped): T1 Оронтобат→Q124761490 (disambiguation
— correct); T2 Клинописная→Q401 cuneiform (**debatable — see §5**), Египет→Q5774882
*history of Achaemenid Egypt* (history-of meta-topic — correct). Kept term:
сатрапами(satrap), метрополия(metropole), державы Ахеменидов(Achaemenid Empire). ✓

**Ашшурбанапал** (272, 15 dropped): T1 царь Ассирии→*list of kings of Assyria*,
иудейский царь→*list of kings of Israel and Judah*, Куту→disambiguation (all
correct). T2 аккад./шумерском/по-арамейски/егип./урарт./др.-греч. → language
glosses (correct noise); клинописью→cuneiform, электрума→electrum, талантов→talent
(**debatable**). Kept term: Library of Ashurbanipal, annals, oracle, Chaldea,
Phoenicia, Philistines, Arameans, Cimmerians. ✓

**Verdict:** T1 drops are unambiguously correct (list/disambiguation/name pages).
T2 correctly kills the large language-gloss noise mass (аккад., шумерском,
по-арамейски, англ.) and generic words, and does **not** touch pharaoh, ziggurat,
satrapy, mummy, deity, ethnic groups, polities.

---

## 5. Surprises & the one risk to flag

1. **The noise hypothesis is confirmed but only partial.** Filtering lifts
   gemini +5.1pp (0.690→0.741) and term recall +6.0pp (0.414→0.474). But the
   named/term gap *survives* T2 almost intact (0.841 vs 0.474). ~2/3 of the term
   miss is genuine model weakness on domain concept-terms (ziggurat, papyrus,
   cylinder seal, harem, caste, relief sculpture, griffin), **not** annotation
   noise. Filtering cannot explain the gap away.

2. **Biggest single noise bucket is LANGUAGES (462 tuples)** — dominated by
   translator-gloss notations (`англ.`, `аккад.`, `др.-греч.`, `по-арамейски`)
   and language names. Model recall on languages is ~0.42, below corpus average;
   removing them is the main lever of T2.

3. **RISK — debatable T2 casualties (~93 tuples, 12% of T2 drops):** cuneiform &
   hieroglyphs (part of 82 "script" tuples — but that bucket also holds true
   noise like IPA vowels, Cyrillic), materials (electrum, gold, ivory — 5), and
   ancient units (talent, stadion, yojana — 6). These are legitimately domain
   terminology yet caught by the generic filter, because Wikidata classes them
   identically to generic materials/scripts/units. A deterministic P31 rule
   cannot separate "cuneiform the subject" from "Akkadian the gloss" — same class.
   **Owner decision:** ship T2-strict (current, drops them) or T2-lenient (exempt
   `writing system`/`material`/`unit of mass|length` → ~+90 tuples back). I lean
   strict: the retained-noise (IPA, Cyrillic, modern regional units) outweighs
   the few real terms, and cuneiform/hieroglyph/talent still appear elsewhere as
   *named* mentions in most articles.

4. **Regex false-positives found & fixed:** "Boeotia/Argolida/Achaea Regional
   Unit" (real places) matched `unit of`; "standard language" matched `standard`.
   Tightened UNIT rule to `unit of (mass|length|area|...)`; those 7 place-tuples
   are correctly retained now (T2 unchanged at 0.741).

---

## 6. Recommendation

Report **three nested M3 recalls** per model:

- **R-M3-T0 (raw)** — the current, un-filtered number (comparable to prior runs).
- **R-M3-T1 (clean)** — after removing structural meta/calendar junk. *Minimal,
  fully defensible cut; report this as the honest baseline.*
- **R-M3-T2 (term)** — after also removing generic lexical concepts
  (languages/taxa/units/academic). *The "terminology-relevant" recall.*

gemini **0.690 → 0.704 → 0.741**; deepseek **0.614 → 0.627 → 0.663**.

Name suggestion for the paper: **R@M3 (raw / clean / term)** or
**R@M3⁰ / R@M3¹ / R@M3²**. State plainly that even at the term tier the
named/term gap persists — that is a model finding, not an artifact.

Machine-readable outputs: `tier_assignment.json` ({qid: 0|1|2}, 3868 QIDs),
`tier_defs.json` (tier names/rules/properties + rejected alt).
