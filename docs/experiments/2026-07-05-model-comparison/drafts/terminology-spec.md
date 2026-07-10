> ⚠️ **SUPERSEDED** by [docs/paper/sections/](../../../paper/sections/) (protocol v3, 2026-07-10). Binds
> terminology for the retired M1/M2/M3/P1/P2/P3 mention-level protocol only — kept for historical reference.

# Terminology spec (approved by orchestrator, 2026-07-06)

Binding for ALL documents (RU report, EN paper section, tables, tex, artifact).
Standard EMNLP/NER/EL community terms. Old internal codes (M1/M2/M3, P1/P2/P3,
R-T0/T1/T2, n) must not appear anywhere except one parenthetical mapping note
in the RU report's methodology-evolution section.

## Recall (matching granularity)

| Old | New name (EN, tables & paper) | Short | RU usage |
|---|---|---|---|
| M3 | **Document-level Recall** | R_doc | Recall по спискам QID документа (R_doc) |
| M2 | **Span-overlap Recall** | R_span | Recall по пересечению спанов (R_span) |
| M1 | **Strict-match Recall** | R_strict | строгий Recall (R_strict) |

R_doc is THE primary metric. R_strict/R_span appear only in the matching-strictness ablation table.
Invariant: R_strict ≤ R_span ≤ R_doc.

## Precision (denominator granularity; positional span-overlap matching)

| Old | New name | Short |
|---|---|---|
| P1 | **Mention-level Precision** (every predicted mention counts once) | P_mention |
| P2 | **Type-level Precision** (unique (surface form, QID) pairs) | P_type |
| P3 | **Label-verified Precision** (unmatched predictions credited when their surface is a Wikidata label; reported excluding the deterministic exact-label path where it is 1 by construction) | P_label |

Mention/type distinction is the standard NER/EL usage.

## Gold-annotation filtering tiers

| Old | New name | Short |
|---|---|---|
| R-T0 | Recall on **all gold mentions** | R_all ≡ R_doc |
| R-T1 | Recall after removing **structural noise** (meta pages, calendar leftovers) | R_clean |
| R-T2 | Recall on **domain terminology** (also removes generic lexical classes: languages/scripts, taxa/materials, units, academic-abstract concepts) | R_term |

## Other renames

- n → **gold mentions** (EN table header: "Gold mentions"; RU text: «число эталонных упоминаний»).
- "reference tuple" → **gold mention** (EN; "gold" is the standard EMNLP term for human annotations). RU: «эталонное упоминание» (never «золотой»).
- coverage × conditional accuracy → **extraction coverage** × **grounding accuracy** (stated as conditional on extraction once, then used bare).
- Ablation configs 000..111 → rows labeled by enabled components: "none", "+aliases", "+fallbacks", "+lemma", "all", etc. (bit codes may appear in one footnote for reproducibility).
- resolved_by paths keep code names in code contexts; in paper prose: "the deterministic exact-label path" / "the judge path".

## Style rules

- RU report: NO semicolons anywhere. Minimize em-dashes: prefer separate short sentences. Plain meaning-first prose, English calques allowed (NER, Wikidata-grounding, recall, precision, ablation, span).
- ALL tables and their captions in English, in both RU and EN parts.
- EN section: EMNLP register, native idiom, narrative focus. Minor technical caveats (off-period residue, failure accounting) go to a compact limitations note at the END of the section, never in opening paragraphs.
