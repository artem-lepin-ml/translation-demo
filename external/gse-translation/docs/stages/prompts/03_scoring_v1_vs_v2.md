# Stage 03 Scoring Prompts — v1 vs v2

Up-link: [docs/stages/03_scoring.md](../03_scoring.md). Source files: [prompts/03_scoring/v1/](../../../prompts/03_scoring/v1/), [prompts/03_scoring/v2/](../../../prompts/03_scoring/v2/). MGIMO reviewer feedback that drove the v2 rules: [references/mgimo_reviews_raw_llm_translation.md](../../../references/mgimo_reviews_raw_llm_translation.md).

Six per-criterion rubrics were rewritten. Each section below: **What changed** (bullets) + **Why** (1–2 sentences). For colleagues reviewing the changes.

Cross-cutting v2 changes (apply to all 6):

- **Common Instructions block** — single-paragraph scope, score independence (don't bleed in other criteria), mandatory grounding (≥2 specific issues if `final_score < 7`), self-check, primary-source quote carve-out.
- **Anchored 1–10 scale** — score bands are defined by counts of minor vs major issues, not prose descriptors. Severity definitions are explicit per critère.
- **JSON-sanitation boilerplate removed** — collapsed to one line under structured output.
- **Marker-tokens line removed** — `* * *` and `picture` are filtered at the dispatcher level, not at the judge level.
- **Few-shot ✅/❌ examples added** in every Critical Rules section.

---

## Accuracy

### What changed

- **New "Critical Rules" section** codifies *meaning over literal form, not over English quality*: restructured renderings that preserve meaning are correct, but Russian-pulled syntax (Runglish) is now an accuracy issue, not just a fluency one.
- **Proper-noun rule relaxed to plausibility over canonicity** — non-canonical but unambiguous transliterations (e.g. `Hammurabi` vs `Hammurapi`) no longer count as errors; flag only on wrong referent or unrecognizability.
- **Primary-source quotations carved out** — embedded ancient/archival quotes are judged separately; preserved archaic syntax is not an error.
- **`terminological_accuracy` criterion removed** (5 → 4 criteria); terminology is delegated to its own rubric. Criteria block and JSON `criteria_assessment` schema both updated.
- **Few-shot examples added** — 4 cases: acceptable restructuring, meaning shift, plausible proper noun, Runglish calque.

### Why

v1 conflated accuracy with terminology and fluency, and gave no anchored mapping from issue counts to scores — judges drifted. v2 narrows accuracy to semantic fidelity vs the source, adds the Runglish signal MGIMO flagged as an accuracy concern, and forces low scores to be grounded in concrete fragments.

---

## Fluency

### What changed

- **MT-Calque Catalogue added.** v2 enumerates concrete Russian-shadow patterns to flag as the highest-priority failures: heavy relative clauses (`с расселением которых...`), hedge/introductory calques (`from all this, it would appear to follow`, `it can be thought that`), idiom calques (`идти в кабалу` → `condemn themselves to bondage`), calque prepositions (`on the territory of X`, `in even greater scale`), and mechanical SOV/inverted word order. Each pattern ships with a ❌ → ✅ pair sourced from MGIMO reviewer feedback.
- **Active-voice rule promoted to its own criterion.** v2 makes "prefer active, passive only where warranted" an explicit rule with positive examples (agent unknown, rhetorical backgrounding, method descriptions) and negative examples (agentive-passive chains, impersonal `утверждается` / `считается`). Criteria count grows from 5 to 6, and `criteria_assessment` gains a `voice` field.
- **Source-Structure NON-Issues codified.** A dedicated section lists what NOT to flag: matched density, sentence-length parity, legitimate splits of long Russian periods, archaic syntax in primary-source quotes, and standardized academic connectors.

### Why

v2 operationalizes MGIMO reviewer feedback: vague "naturalness" gave too much latitude, so calques are now named explicitly and the scale is anchored on countable severity. The grounding rule and self-check tighten low-score justifications.

---

## Style

### What changed

- **Modality Mapping table** — v2 introduces an explicit RU→EN hedge table (`можно полагать`, `представляется`, `вероятно`, `по-видимому`, `возможно`, `как известно`) with idiomatic English equivalents and concrete anti-patterns to penalize (e.g. `it is presented that`, `by appearance`, `as is known`). v1 had no such mapping.
- **Three modality anti-patterns** — *flatten* (strip all hedges), *over-hedge* (pile hedges on a confident claim), and *calqued hedge* (`from our point of view`, `it can be thought that`). Cross-references fluency's MT-Calque Catalogue.
- **Few-shot ✅/❌ pairs** — inline examples for `можно полагать`, `представляется`, and `расцвет цивилизации`, anchoring the rules in concrete decisions.
- **`source_structure_note` field added** — new top-level JSON field mirroring fluency, so dense list-like sources are not penalized for lacking flowing prose.
- **"Tone consistency" criterion folded into "Modality balance"** — the latter is the harder, more diagnostic check.

### Why

v1 evaluated style impressionistically; v2 operationalizes the MGIMO Reviewer 1 finding that Russian academic prose lives or dies by hedge calibration, making the criterion auditable and aligning its schema and instruction shape with the other v2 rubrics.

---

## Terminology

### What changed

- **Tradition-mismatch rule (new).** v2 explicitly flags terms that are canonical in one historical tradition but wrong in another — e.g. «служилая знать» → `service nobility` is correct for Russian-history scholarship but wrong for an Ancient Near East passage (preferred: `official elite` / `palace bureaucracy`). v1 had no such concept.
- **Plausibility-over-canonicity (new).** v2 tells the judge not to impose a single canonical equivalent: a defensible alternative is not an error. Only flag wrong-domain terms, meaning-distorting choices, or invented English forms (e.g. `nomial state`, `military-service stratum`). v1 instead rewarded matching "established English equivalents," pushing the judge toward canonicity.
- **Period-and-context appropriateness sharpened.** v1 listed it as one of five criteria; v2 promotes it to a Critical Rule with concrete anachronism examples (`vassal`, `liege`, `knight` for a Sumerian official).
- **Consistency scope narrowed.** v2 limits the criterion to in-paragraph term consistency and delegates cross-document consistency to the dedicated consistency critère. v1 mixed both.

### Why

v1 over-penalised defensible non-canonical choices and under-penalised tradition-mismatch — both flagged by MGIMO Reviewer 2. v2 retargets the criterion at the failures that actually matter for our ANE / Roman-law corpus.

---

## Consistency

### What changed

- **Scope realigned to the dispatcher's reality.** v1 told the judge to "read the English translation in full" and audit recurring elements "across paragraphs and sections", but the dispatcher only feeds one paragraph per call. v2 reframes the role as an **internal-uniformity auditor** of the supplied text, with cross-paragraph and document-level concerns explicitly out of scope.
- **Single-occurrence guard added.** v2 states that a term, name, or pattern appearing only once CANNOT generate a consistency issue — directly blocking the most common v1 hallucination mode.
- **Critical Rules with paired ✅/❌ examples** replace v1's abstract criteria list, covering term consistency, proper-name uniformity, register stability, structural consistency, and formatting.
- **"Handling Difficult Cases" compressed** from ~30 lines of prose to an 8-line bullet list with a shared example.
- **`source_structure_note` field added** — calibrates the judge: a dense list with parallel structure is the source's register, not register drift.
- **No-recurring-elements default** — if the paragraph has nothing to audit (no repeats, single short sentence), score is 10 with empty issues.

### Why

v1's document-scope framing was impossible to execute on a single-paragraph input, so judges fabricated cross-paragraph inconsistencies to fill the schema. v2 matches the prompt to what the dispatcher actually delivers and adds explicit guards against the failure modes observed in the pilot.

---

## Cultural Adaptation

### What changed

- **Foreignization-vs-domestication rule with worked examples.** «верста» → `verst (about 1.07 km)` ✅, → `mile` ❌ (major, factually wrong), bare `verst` without gloss ⚠️ (minor). v1 only mentioned the verst case in passing in the instructions.
- **Period-marker rule for realia.** v2 explicitly forbids period-stripping substitutions (`Roman patron` → `boss`, «храмовое государство» → `theocracy`) and rewards period-aware renderings (`Sumerian temple-state`, `Roman patron-client`). v1 had no such rule.
- **Idiom calques scoped against fluency.** v2 clarifies the boundary: fluency handles generic MT-awkwardness, cultural handles calques that distort institutional register (e.g. «идти в кабалу» → `condemn themselves to bondage`). v1 left this overlap implicit.
- **Cultural neutralization named as an anti-pattern.** Systematic flattening of markers («древневосточная деспотия» → `government`) is a major issue, with an example.
- **Inherent-Challenges carve-out hardened.** A reasonable approximation + gloss for an untranslatable concept is correct, not an error, and goes in `inherent_challenges[]` rather than `identified_issues[]`.
- **No-cultural-content default → 10** if the paragraph is purely abstract / numeric / generic.

### Why

v1 left the foreignization/domestication call and the realia-vs-idiom-vs-neutralization taxonomy to the judge's intuition, which produced inconsistent scoring across paragraphs with little cultural content and across over-domesticated renderings. v2 fixes the rubric with few-shots, severity tiers, and a no-content default so scores compare across runs and judges.
