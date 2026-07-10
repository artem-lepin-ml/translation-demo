# KG-MT applicability assessment — Wikidata retrieval for entity-aware MT vs. our wiki-eval pipeline

Research note (web-only; no LLM API calls). Scope: identify the "EMNLP 2025 KG-MT"
paper the owner recalls, deep-read its Wikidata retrieval internals, and assess what
transfers to our NER→Wikidata grounding pipeline
([2026-07-10-wiki-eval-experiment-v2.md](../superpowers/specs/2026-07-10-wiki-eval-experiment-v2.md),
[grounding/label_first.py](../../src/palimpsest/terminology/grounding/label_first.py)).

---

## 1. Paper identification

The recollection is one year off: the KG-MT paper is **EMNLP 2024 (main conference)**,
not 2025. There is no EMNLP 2025 paper named KG-MT (checked the EMNLP 2025 accepted-papers
list — no match on the title, the method, or any of the authors). The 2025 activity from
the same group is a shared task and a KG-completion paper, covered briefly below.

**Primary paper.**

- [Towards Cross-Cultural Machine Translation with Retrieval-Augmented Generation from Multilingual Knowledge Graphs](https://aclanthology.org/2024.emnlp-main.914/)
  — Conia, Lee, Li, Minhas, Potdar, Li. **EMNLP 2024 main**, pp. 16343–16360,
  DOI [10.18653/v1/2024.emnlp-main.914](https://doi.org/10.18653/v1/2024.emnlp-main.914).
  ACL Anthology page. Introduces **KG-MT** (the method) and **XC-Translate** (the benchmark).
- [arXiv:2410.14057](https://arxiv.org/abs/2410.14057) — preprint;
  [HTML render](https://arxiv.org/html/2410.14057v1) — the full-text source I read for the internals.
- [apple/ml-kg-mt](https://github.com/apple/ml-kg-mt) — official code + data release.
  Ships the **XC-Translate benchmark** (~57.6k rows, 10 language pairs, JSON/JSONL with
  source text, target references, entity mentions, **Wikidata QIDs**, entity types) and the
  **official m-ETA evaluation script**. Code is under Apple's license; the data is CC BY-SA
  (derived from Wikipedia/Wikidata). Does **not** ship the trained dense retriever, the
  entity embeddings, or the Wikidata index-build scripts.
- [Apple ML Research page](https://machinelearning.apple.com/research/cultural-translation)
  — lay summary + link hub.

**2025 follow-ups (same group), for related-work context only.**

- [SemEval-2025 Task 2: Entity-Aware Machine Translation](https://aclanthology.org/2025.semeval-1.326/)
  — Conia, Li, Navigli, Potdar. SemEval-2025, pp. 2535–2557. A shared task that **reuses
  XC-Translate** as its gold benchmark and m-ETA as the entity metric; the natural 2025
  extension of the KG-MT line and the likely source of the owner's "2025" memory. Many
  system papers (HausaNLP, Team ACK, CHILL) sit under it — a live external community around
  exactly our problem.
- [KG-TRICK](https://arxiv.org/abs/2501.03560) — Zhou, Conia et al., **COLING 2025**.
  Multilingual KG *completion* (text + relations), not MT; peripheral to us.
- Earlier ancestor: [Increasing Coverage and Precision of Textual Information in Multilingual Knowledge Graphs](https://aclanthology.org/2023.emnlp-main.100/)
  (EMNLP 2023) — the M-NTA / WikiKGE-10 work the same authors built on.

---

## 2. Their pipeline, focused on the Wikidata retrieval internals

KG-MT is an **end-to-end trained** system (a retriever + a fine-tuned NMT model), not an
LLM-prompting pipeline. Two components:

### 2.1 Knowledge retriever (the owner's main interest)

- **Mechanism: dense retrieval, not entity linking or label matching.** Source text `t`
  and each candidate entity `e_i` are embedded; relevance is cosine similarity
  `s(e_i, t) = (e_i · t)/(‖e_i‖‖t‖)`. Top-**k = 3** entities are retrieved (stated trade-off
  between coverage and compute). This is the opposite design choice from ours, which is
  symbolic label/alias/full-text search.
- **What is indexed:** each entity as a `⟨name, description⟩` tuple, embedded by the encoder.
  The **description is what carries disambiguation signal** — there is no separate
  disambiguation stage; picking the right same-named entity is folded into the dense score.
- **Encoder:** a contrastively-trained bi-encoder; the analysis identifies the base as
  **mContriever** (multilingual Contriever). Training objective is a contrastive loss that
  pulls the relevant entity toward the source and pushes irrelevant ones away.
- **Hard-negative mining is the key trick and it is homonym-based:** instead of random
  in-batch negatives, they sample *n* **homonymous entities that share the name of the
  positive entity but are not the referent**. This forces the retriever to disambiguate by
  description rather than by surface name. Reported effect: **+5.6 hits@1 / +4.2 hits@3** over
  a no-hard-negatives baseline.
- **Source KG:** Wikidata (they note the method is KG-agnostic). Scale stated only as
  "millions of entities."
- **Retriever quality on XC-Translate:** **85.9% hits@1, 92.1% hits@3.** Retrieval is *not*
  their bottleneck.
- **Reported failure mode:** not retrieval but **integration** — in a gold-knowledge ablation
  the fine-tuned translator "is not always capable of using the gold knowledge" (only ~11.6pp
  m-ETA gain even when handed gold entities), so the **generation/fusion step**, not
  retrieval, caps performance.

### 2.2 Knowledge-enhanced translator (how KG knowledge is injected)

Two fusion routes, used together:

- **Explicit** — build a knowledge-augmented input by appending mapped names after a special
  `[KG]` token: `t^{+kg} = ⟨w_1…w_n, [KG], n_1^s→n_1^t, …, n_k^s→n_k^t⟩`, where `n_i^t` is the
  **target-language Wikidata name** of the retrieved entity. The NMT model attends to these
  source→target name pairs.
- **Implicit** — prepend the retriever's **entity embeddings** to the encoder hidden states
  (`⟨e_1…e_k, h_1…⟩`), a Fusion-in-Decoder-style fuse across two encoders (retriever + MT),
  letting the decoder attend to entity vectors directly.
- **Base MT models:** mBART-50 (0.6B), M2M-100 (0.4B), NLLB-200 (0.6B), each fine-tuned;
  retriever + translator trained on **Mintaka**-derived multilingual, entity-linked data.

### 2.3 Evaluation protocol and metric

- **m-ETA (manual Entity Translation Accuracy):** checks whether the **automatic translation
  string contains a manually-curated correct target name** for each gold entity. Set-based at
  the entity level: `q(t', e_i) = min{1, Σ 𝟙(n_i^t ∈ t')}` (1 if *any* accepted name variant
  appears, capped at 1), averaged over the gold entities of the text. It rewards presence of a
  correct name variant, ignores position/count. Complemented by BLEU and COMET for overall
  quality.
- **XC-Translate:** first large manually-created benchmark for culturally-nuanced entity
  names. ~**58k** instances (~57.6k in the repo), **EN → {ar, de, es, fr, it, ja, ko, th, tr,
  zh}** (10 targets, source is English). Multi-reference (2 translations/sentence on average,
  >100k references). Entities selected to be **hard**: ≥50% Levenshtein distance between
  English and target names (i.e. transcreation, not transliteration) — films, books, food,
  places, people. Each row carries the entity's **Wikidata QID and type**.
- **Baselines:** GPT-3/3.5/**GPT-4**, mBART-50, M2M-100, **NLLB-200**.
- **Headline numbers (avg over 10 pairs):** m-ETA NLLB-200 **17.9%**, GPT-4 **25.3%**,
  **KG-MT(NLLB) 41.1%** → **+129%** vs NLLB, **+62%** vs GPT-4; COMET rises to ~84.6 with no
  degradation on general WMT translation. The large BLEU/COMET-vs-m-ETA gap (GPT-4: 50.9 BLEU
  but 25.3% m-ETA) is their motivating observation — standard metrics are near-blind to entity
  errors.
- **Error decomposition:** they do **not** decompose extraction vs disambiguation vs
  generation. Their only decomposition is the gold-knowledge ablation isolating retrieval
  (strong) from integration (weak).

---

## 3. Point-by-point comparison with our pipeline

| Dimension | KG-MT (EMNLP 2024) | Ours (wiki-eval v2) |
|---|---|---|
| Task object | End-to-end **translation** of entity names (EN→10 langs) | **Grounding** RU terms to Wikidata QIDs (upstream of RU→EN translation QA) |
| Retrieval method | **Dense** bi-encoder (mContriever), cosine, top-k=3, index of `⟨name, description⟩` embeddings | **Symbolic**: `wbsearchentities` on lemma+surface (label/alias prefix) → CirrusSearch full-text → sitelink; API search, no embeddings ([candidates.py](../../src/palimpsest/terminology/grounding/candidates.py)) |
| Extraction | Implicit — retriever runs on whole source text; no explicit mention list | **Explicit LLM NER** (surface+lemma) as a separate stage ([extract.py](../../src/palimpsest/terminology/extract.py)) |
| Disambiguation | **Folded into retrieval** — dense score + homonym hard-negative training picks the right same-name entity | **Separate**: deterministic exact-label short-circuit, else **LLM judge** over candidates with sentence context ([label_first.py](../../src/palimpsest/terminology/grounding/label_first.py)) |
| Multilingual labels/aliases | Names + aliases + descriptions embedded across languages | Aliases used in matching (`match_aliases`); EN+RU labels/descriptions shown to judge; canonical EN forms for pairing |
| Metric | **m-ETA** — is a correct target *name string* present in the output (translation-level, set-based per entity) | **R_doc / P_doc** — set overlap of unique **(article, QID)** (grounding-level, QID-based), split named/term, Wilson CI |
| Gold | **Manually created**, multi-reference target names + QIDs (expensive, high-precision) | **Automatic**: Wikipedia hyperlink anchors → QIDs (cheap; anchor coverage caps the recall ceiling) |
| Domain | Modern **culturally-nuanced** entities in general text | **Ancient-history** terminology (peoples, titles, deities, places) in Russian academic prose |
| Bottleneck (their finding vs ours) | **Integration/generation** is the cap; retrieval is strong (85.9 hits@1) | **Named** misses ← disambiguation ("judge chose a different QID", ~40% of named FN); **term** misses ← extraction coverage (~70% never extracted) — [pilot analysis](wiki-eval-v2-pilot-analysis.md) |

**In prose.** The two pipelines attack the same real problem — long-tail, culture-specific
entity names that Wikidata can ground — from opposite ends. KG-MT is a *trained* system that
buries disambiguation inside a dense retriever and then fights to make an NMT decoder actually
*use* the retrieved name; its gold is gold-standard and manual, its metric measures the final
translation. Ours is an *LLM-prompting* pipeline that separates extraction, symbolic candidate
generation, and an LLM disambiguation judge, evaluated against cheap anchor-derived QID gold at
the grounding layer. The most striking mirror: **their bottleneck is generation and their
retrieval/disambiguation is near-solved (85.9 hits@1); our bottleneck is precisely
disambiguation (for named) and extraction coverage (for terms).** Their homonym hard-negative
result is, in effect, a solution aimed at the exact failure mode that dominates our named-entity
misses.

---

## 4. Applicability verdict

### Directly borrowable

1. **Related-work positioning (highest value, near-zero cost).** KG-MT + XC-Translate +
   SemEval-2025 Task 2 are the canonical entity-aware-MT line and the perfect anchor for our
   paper's framing. Our distinct contribution reads cleanly against them: they show standard
   MT metrics are blind to entity errors and that *integration* caps end-to-end m-ETA, but they
   **do not decompose the grounding pipeline**; we do exactly that (extraction coverage vs
   disambiguation), which their gold-knowledge ablation motivates but stops short of.
2. **m-ETA as a comparison metric / metric-design reference.** Its set-based "any accepted name
   variant present, capped at 1" shape maps naturally onto our `canon_en` variant lists. We can
   report a downstream entity-name-accuracy number in the m-ETA style alongside R_doc/P_doc, and
   cite m-ETA as prior art for entity-level (not corpus-level) evaluation.
3. **Homonym-aware disambiguation.** Their hard-negative insight — the confusable candidates are
   *same-name homonyms*, disambiguated only by description — is directly reusable in our LLM
   judge *without training anything*: explicitly flag same-label homonym candidates and foreground
   their distinguishing descriptions in the judge prompt / candidate ordering. This targets our
   #1 named-entity failure ("judge chose a different QID") and is testable on existing pred data.
4. **Multilingual `⟨name, description⟩` signal.** Confirms our use of aliases + EN/RU
   descriptions and suggests weighting description text more in candidate ranking; a dense
   `⟨name, description⟩` rung is a plausible future supplement to `wbsearchentities`/CirrusSearch
   for the term-class coverage gap.

### Does NOT transfer (and why)

- **The trained architecture** (contrastive dense retriever + fine-tuned NLLB/mBART/M2M with
  explicit+implicit fusion). It needs Mintaka-style entity-linked parallel training data and MT
  fine-tuning — out of scope for a research-demo LLM pipeline that fine-tunes no MT model.
- **XC-Translate as a drop-in eval set.** Wrong direction (source = English; ours is Russian),
  wrong domain (modern cultural entities vs ancient history), and gold is **target-side name
  strings** vs our **source-side QIDs**. Usable as related work and as a metric reference, not as
  a swap-in corpus.
- **m-ETA as our *primary* metric.** It scores the final translation output; we score grounding
  (QID) correctness upstream. Different object — a complement, not a replacement for R_doc/P_doc.
- **"Retrieval is solved" conclusion.** Theirs is on manually-curated, QID-linked entities where
  dense retrieval hits 85.9@1; our retrieval/disambiguation over noisy ancient-history terms is
  demonstrably *not* solved. Their number is not a target we inherit.

### Concrete cheap next actions (ranked by value/cost)

1. **Cite the trio in related work** (KG-MT, XC-Translate, SemEval-2025 Task 2) and frame our
   decomposition as the gap they leave open. Cheapest, ships with the paper.
2. **Homonym-aware judge prompt tweak**: surface same-label homonyms with contrasting
   descriptions; A/B on existing pilot pred.jsonl for the "judge chose a different QID" units.
   Cheap prompt change, directly hits the dominant named-entity failure.
3. **Report an m-ETA-style entity-accuracy number** built from our `canon_en` variant lists as a
   secondary, comparable metric. Small aggregator addition.
4. **(Heavier, flag as speculative)** prototype a dense `⟨name, description⟩` retrieval rung
   (mContriever) as a supplement to symbolic candidate generation for the term-class coverage
   gap — a real experiment, not a cheap change; only if actions 1–3 leave coverage as the open
   problem.

---

## 5. Honest limitations of this read

- I read the **arXiv HTML v1** (open access; ACL Anthology, arXiv, Apple page, and GitHub are
  all public — **nothing paywalled**), extracted via a summarizing fetch rather than a
  line-by-line PDF read. The **architecture, metric definition, headline m-ETA numbers, hits@k,
  and benchmark shape are cross-checked across multiple sources and reliable.**
- Lower-confidence, verify against the PDF before citing verbatim: the **per-language Table 2
  cells**, the exact **Mintaka** training-data description, the precise **"~11.6pp gold-knowledge
  gain"** figure, and the exact equation typography. The mContriever base and the millions-of-
  entities scale are stated in the analysis text but not deeply corroborated.
- I did not run the repo's m-ETA script or inspect XC-Translate row-by-row; the format summary is
  from the README/paper, not a local checkout.
