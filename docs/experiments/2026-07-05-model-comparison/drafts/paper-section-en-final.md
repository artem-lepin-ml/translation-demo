# 5 Evaluation

We ask one question that standard entity-linking benchmarks leave open: given
no task supervision, how well can a system find the domain terms in a Russian
text and ground each to the right Wikidata entity? The multilingual linking
suites that would seem to answer it do not. Mewsli-9 and its successors span a
hundred languages but not Russian, and every strong number on them comes from a
linker trained on millions of the same Wikipedia anchors it is scored against.
We are after the opposite regime: a zero-shot pipeline, run on Russian
historical prose, measured at the point where a mention is found and resolved
rather than through downstream translation quality. This section builds a
reference benchmark for that regime and reports where the difficulty actually
lies.

## 5.1 Benchmark construction

We derive the reference set from a resource Wikipedia editors have already
produced: the internal links they place by hand in article bodies. Each
body-paragraph link whose target resolves to a Wikidata item yields one *gold
mention*: a tuple of token index, surface form, QID, and span length.
Resolution follows redirect chains through the MediaWiki API with no learned
component, so the benchmark is deterministic and rebuilds bit-for-bit from a
cached HTML snapshot of each article. We remove links to chronology targets
(years, decades, centuries, identified by the target's *instance-of* class),
which annotate temporal navigation rather than terminology. The corpus of 100
articles yields 8,829 in-text links; 405 are chronology-filtered and 6 carry no
Wikidata item, leaving **7,959 gold mentions over 3,868 distinct QIDs**.

The 100 articles come in ten thematic sections of ten (Sumer, Egypt, Assyria,
the Hittite kingdom, Phoenicia, Achaemenid Iran, India, China, Greece, Rome).
Within each section we shuffle the category subtree under a fixed seed, walk it
in order, and admit an article only when it clears a deterministic gate: at
least thirty unique body links, an earliest Wikidata date before 500 CE
(undated pages kept), and a short *instance-of* blacklist for off-topic media.
We stop at ten admissions. The corpus is fixed by seed and gate, not curated by
hand.

One property of this reference set shapes every metric that follows.
Wikipedia's style guide asks editors to link an entity at its first mention and
not again, and it never guarantees that every term in a passage is linked at
all. The annotations are precise where they exist but systematically
incomplete; a missing link is not evidence that a mention is not a term. We
therefore treat **recall as the primary axis**, the share of genuinely
annotated concepts a system recovers, and read precision only as a conservative
lower bound: a prediction absent from the reference may be correct rather than
wrong.

## 5.2 Metrics

Our headline metric is **document-level recall** (R_doc): a gold mention counts
as recovered if its QID appears anywhere in the system's predictions for that
article. This states the task in its most transparent form: the article's
concept was found and grounded to the right entity. It is robust to
tokenisation and mention-boundary disagreements. Two positional variants bound
it from below and appear only in the matching-strictness ablation:
**strict-match recall** (R_strict) demands an equal first-token index,
normalised surface, and QID; **span-overlap recall** (R_span) requires
overlapping spans and an equal QID. R_strict ≤ R_span ≤ R_doc holds on every
run.

We report precision under span-overlap matching in three readings, each a
tighter lower bound than the last. **Mention-level precision** (P_mention)
scores every QID-bearing prediction. **Type-level precision** (P_type) first
deduplicates predictions by normalised surface and QID, which offsets the
do-not-relink convention; the gap between the two measures that convention
directly. **Label-verified precision** (P_label) further credits a prediction
absent from the reference when its surface exists as a Wikidata label; we
report it excluding the deterministic exact-label path, where the surface is a
label by construction. Every reported cell carries a Wilson 95% interval, and
cells with fewer than thirty gold mentions are flagged and never interpreted.

A large gap between capitalised and lowercase reference mentions, reported in
§6, raises a question about the reference itself: is some of it not terminology
at all? To answer it deterministically we define three nested **gold-filtering
tiers** on properties of each target QID. **R_all** is the unfiltered set.
**R_clean** removes structural noise: the meta and calendar pages that survive
earlier filters. **R_term** further removes generic lexical classes that a
terminology task should not reward: languages and scripts, taxa and materials,
units and standards, academic and abstract concepts. A target is dropped only
when *every* one of its *instance-of* classes maps to a noise bucket, which
protects multi-typed real entities.

## 5.3 System under test

The system under test is a deterministic-first grounding pipeline (Figure 1).
An LLM extractor proposes mentions paragraph by paragraph. A candidate ladder
then queries Wikidata by lemma, then by surface, with full-text and
title-sitelink fallbacks when a rung returns nothing. A single exact match
against a candidate's label or alias resolves the mention deterministically,
with no LLM involvement; genuine ambiguity escalates to an LLM judge that must
pick among the retrieved candidates or abstain. The pipeline never silently
falls back to a top-ranked guess. A three-component ablation over the ladder
(lemma search, search fallbacks, alias matching), run on a 20-article subset of
1,443 gold mentions and cross-checked against an independent 91-term set,
attributes +0.322 span-overlap recall to lemma search and +0.145 to search
fallbacks over the all-off baseline; alias matching adds no measurable accuracy
(+0.004) and is kept only for decision-trace transparency. The same candidate
model serves as both extractor and judge, and the ladder configuration is fixed
for the main runs.

# 6 Results and Analysis

**Table 1. Full-corpus results (100 articles, 7,959 gold mentions): recall in
three matching modes, precision under span-overlap matching, Wilson 95%
intervals on R_doc.**

| Model | R_doc [95% CI] | R_span | R_strict | P_mention | P_type | Gold mentions |
|---|---|---|---|---|---|---|
| gemini-3.1-flash-lite | **0.690** [0.680–0.700] | 0.630 | 0.610 | 0.300 | 0.451 | 7,959 |
| deepseek-v4-flash | **0.614** [0.604–0.625] | 0.524 | 0.509 | 0.305 | 0.458 | 7,959 |
| qwen3.7-plus[^qwen] | --- (invalidated) | --- | --- | --- | --- | 7,959 |

[^qwen]: Run invalidated by provider-side instability; scores withheld rather
than reported. See "Provider reliability as a validity threat" at the end of
this section.

On document-level recall, gemini-3.1-flash-lite reaches 0.690 and
deepseek-v4-flash 0.614, with narrow intervals over 7,959 gold mentions.
Precision sits near 0.30 at the mention level and near 0.45 at the type level
for both models; the type gain is exactly the do-not-relink convention made
visible. Label-verified precision, which credits a further class of
unmatched-but-valid predictions, reaches 0.526 for gemini-3.1-flash-lite and
0.530 for deepseek-v4-flash, about 0.07 above type-level precision for both
models and, like grounding accuracy, nearly identical across models.

**The recall gap has a single, clean cause.** We decompose recall at each gold
position into two factors: *extraction coverage*, whether the pipeline produced
any resolved prediction at that position, and *grounding accuracy*, whether
that prediction carried the right QID. Coverage separates the models sharply:
0.763 for gemini against 0.632 for deepseek. Grounding accuracy does not move:
**0.814 and 0.815, identical to the third decimal**. The entire recall
difference lives in the extraction stage. Given a mention, both models ground
it about equally well, and well in absolute terms: accuracy runs 0.92–0.93 on
the deterministic exact-label path and 0.85–0.86 on judge-disambiguated cases,
with the residual conditional loss concentrated in explicit abstentions,
roughly 7–8% of covered positions. This is the result to carry out of the
section. The bottleneck is finding the terms, not linking them.

**The mention-type slice points to the same place.** Document recall on
capitalised mentions reaches 0.828 for gemini but only **0.414 on lowercase
terminology** (type assigned by surface capitalisation). Common-noun terms, not
proper names, are where coverage fails. The gap is wide enough to ask whether
the lowercase reference is really terminology or partly annotation noise, and
we test that with the gold-filtering tiers (Table 3). The answer is: partly. Of
the 1,551 unmatched lowercase mentions, about **34% are filterable noise**
(language glosses such as *англ.* and *др.-греч.*, taxa, meta pages, academic
labels) and about **66% are genuine domain terms the model misses** (*мумия*,
*папирус*, *зиккурат*, cylinder seal, satrap). Cleaning the reference lifts
gemini's terminology recall from 0.414 to 0.474 and its overall recall from
0.690 to 0.741, yet the capitalised/lowercase gap barely narrows (0.841 against
0.474 at R_term). The deficit is a property of the extractor, not of the
annotation, and the model ranking is unchanged across all three tiers.

**Table 2. Candidate-ladder ablation (20-article subset, 1,443 gold
mentions).** Rows enable lemma search, search fallbacks, and alias matching;
bit codes in the footnote.[^bits]

| Components enabled | R_strict | R_span | R_doc |
|---|---|---|---|
| none | 0.280 | 0.286 | 0.416 |
| +aliases | 0.283 | 0.290 | 0.422 |
| +fallbacks | 0.419 | 0.431 | 0.545 |
| +fallbacks +aliases | 0.422 | 0.435 | 0.550 |
| +lemma | 0.593 | 0.608 | 0.683 |
| +lemma +aliases | 0.606 | 0.624 | 0.701 |
| +lemma +fallbacks | 0.608 | 0.624 | 0.699 |
| **all** | **0.622** | **0.640** | **0.717** |

[^bits]: Configurations 000–111 over (lemma, fallbacks, aliases); "all" = 111.

The ladder ablation explains where recall comes from. Lemma search is the
dominant lever: adding it alone lifts span-overlap recall from 0.286 to 0.608,
and removing it from the full configuration costs 0.204. Search fallbacks help
most in isolation (+0.145) but only marginally once lemma search is present
(+0.016), because lemma search already reaches most of the terms the full-text
fallback was there to recover. Alias matching moves nothing measurable and
earns its place only in the decision trace.

**Table 3. Gold-filtering tiers (R_doc).** The lowercase column gives gemini's
recall on the surviving lowercase mentions.

| Tier | Gold mentions | gemini R_doc | deepseek R_doc | gemini R_doc (lowercase) |
|---|---|---|---|---|
| R_all (raw) | 7,959 | 0.690 | 0.614 | 0.414 |
| R_clean | 7,796 | 0.704 | 0.627 | 0.434 |
| R_term | 7,174 | **0.741** | **0.663** | **0.474** |

**Table 4. Per-section recall (R_doc).**

| Section | gemini | deepseek | Gold mentions |
|---|---|---|---|
| sumer | 0.781 | 0.662 | 613 |
| assyria | 0.767 | 0.638 | 879 |
| hittite | 0.735 | 0.461 | 649 |
| achaemenid_iran | 0.719 | 0.684 | 713 |
| india | 0.689 | 0.649 | 843 |
| greece | 0.645 | 0.598 | 1,506 |
| rome | 0.633 | 0.605 | 683 |
| egypt | 0.584 | 0.499 | 579 |
| china | 0.581 | 0.467 | 458 |
| phoenicia | 0.551 | 0.488 | 1,036 |

Per-section recall shows the stronger model is also the steadier one. Gemini
ranges from 0.551 on Phoenicia to 0.781 on Sumer; deepseek swings wider, 0.461
to 0.684. Deepseek's worst section partly reflects paragraphs lost to transient
failures during its run (4.1% of the corpus, declared in run metadata and worth
about 0.02 recall if corrected), but the gap to gemini survives that
correction. The difference is genuine per-domain weakness, not an availability
artifact.

**Evaluation integrity.** One rung of the candidate ladder deserves explicit
scrutiny, because it reuses the exact mapping the reference is built from. The
title-sitelink fallback resolves a Russian Wikipedia title to a QID through the
same *pageprops* path that turns a human wikilink into a gold mention, so any
recall it contributes is partly circular by construction. We quantified it by
replaying the ladder offline from each run's own cache. The rung supplies about
1% of grounded predictions (1.22% for gemini, 1.04% for deepseek), and those
predictions match the reference at 52–60%, far above what a random 1% share
would yield: the circularity is real, not coincidental. Its net effect on the
headline is small. Removing the rung costs 0.5–0.8 recall points across both
models, both matching modes, and both tiers, and it does not explain the
gemini/deepseek gap, which both models pay about equally. The reported runs
predate this finding and include the rung; we disable it in the evaluation
protocol going forward.

**Limitations.** Two caveats bound these numbers. Wikipedia's category graph is
noisy, and roughly three of the 100 articles fall outside the target period; we
disclose them rather than curate the corpus to its result. We assign mention
type by surface capitalisation alone, without cross-tabulation against the
extractor's own category, so the capitalised/lowercase split is a proxy for
proper-noun versus common-noun terminology rather than a verified partition.

**Provider reliability as a validity threat.** qwen3.7-plus completed its run
mechanically, but we exclude it from Table 1: an overnight 429 storm at the
provider corrupted the run silently instead of failing it outright. The
run's own checkpoint reported 99 of 100 articles complete, while the
prediction file held only 36; a resume recovered 29 more, for a final
coverage of 65 of 100 articles. Judge-unavailability affected 735 groundings
in this run, against 12 for gemini-3.1-flash-lite. Per-article extraction
counts track the outage directly: a mean of 39.6 predictions per article over
the first 30 articles processed, against 136.9 over the last 30, and 1,168
predictions on the one article completed after the outage cleared, against
1,044 for gemini-3.1-flash-lite on that same article. Forensic document-level
recall over these corrupted predictions would read 0.164; we report that
figure only as diagnostic evidence of the failure, not as a result, and it is
not part of Table 1. gpt-5.5 is absent from the comparison for a related
reason: no route to the provider stayed stable for the length of the
experiment window, with both the pinned route and the automatic fallback
returning 429 for more than 16 hours despite continuous probing. The lesson
generalises beyond this run. Silent corruption under a provider outage is not
visible until someone checks article coverage against the prediction file, so
integrity gates on article-coverage completeness and on judge-availability
need to run before a score is read at all. Any entity-grounding evaluation
that re-queries live infrastructure at evaluation time inherits that
infrastructure's failure modes.

# 7 Related Work

Building reference annotations from Wikipedia's own hyperlinks is established
practice. Mewsli-9 [Botha et al. 2020] extracts anchor texts as linked mentions
and resolves them to Wikidata across nine languages; supervised multilingual
linkers reach 0.89–0.90 R@1 on it, with mGENRE [mGENRE 2022] reporting 90.2
micro-accuracy. Neither covers Russian, and both train on the very link
distribution they are scored against, so their numbers describe a supervised,
in-distribution regime rather than ours. The editorial convention behind these
anchors, linking an entity only at its first mention, is documented directly by
DaMuEL [DaMuEL 2023] and compounded across languages by cross-lingual link
sparsity [Gerlach et al. 2021]. That convention is exactly what makes the
reference precise but incomplete, and what motivates our recall-primary
protocol with precision as a lower bound. End-to-end linkers on curated English
data, GENRE [GENRE 2021] at 83.7 micro-F1 on AIDA among them, are not
comparable head-to-head: they report F1 on a complete annotation in another
language and domain.

Our task sits closest to entity-aware machine translation, where the grounding
stage is a means rather than the object of measurement. KG-MT [Conia et al.
2024] retrieves source entities from a multilingual knowledge graph to improve
name translation and scores that retrieval only through downstream translation
quality (M-ETA), a setting since institutionalised by SemEval-2025 Task 2
[EA-MT], whose best data-free system reaches 71.7 M-ETA. We measure the same
find-and-ground step those systems rely on, but directly and reproducibly,
against human annotations, on Russian, where no comparable baseline exists. The
contribution is complementary to that line of work, not competitive with it.
