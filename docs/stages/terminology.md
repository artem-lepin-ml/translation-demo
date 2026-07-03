# Stage — Terminology (difficulty + pairAccuracy)

Up-link: [docs/README.md](../README.md). Design: [terminology e2e spec](../superpowers/specs/2026-07-01-terminology-e2e-design.md) · [consolidation design](../superpowers/specs/2026-07-01-terminology-consolidation-design.md). Contract: [demo contracts §1](../superpowers/specs/2026-06-30-demo-contracts.md).

## Purpose

Turn a `(RU source, EN translation)` paragraph into the full `Term[]` the demo shows, filling **both** terminology signals of the `Term` contract:

- **difficulty** (`ground`) — is the source term a groundable Wikidata entity? 🟢 confirmed / 🟡 ambiguous (notable homonym) / 🔴 not found.
- **pairAccuracy** (`pair`) — did the translation render it with the canonical English equivalent? 🟢 / 🟡 / 🔴 + `recommended`. `null` when difficulty=🔴.

Flow: `extract` (RU term mentions) → `ground` (Wikidata QID + difficulty) → `pair` (locate canonical EN in the translation) → assemble `Term[]`.

This module **consolidates** three earlier parallel efforts (a merged end-to-end module plus two overnight cycles, one per signal). It keeps the unified architecture and folds in the overnight cycles' better strategy, edge cases and golden data — see the [consolidation design](../superpowers/specs/2026-07-01-terminology-consolidation-design.md).

## Design decisions

- **Frozen interface first** ([base.py](../../src/palimpsest/terminology/base.py)): `GroundingStrategy.ground(mention, *, judge=None) -> GroundingResult` and `PairingStrategy.pair(req, *, judge=None) -> PairResult`. The judge is injected at **call time**, so one strategy instance serves the whole tournament and a hybrid can pass a judge to one sub-strategy but not another.
- **Shared candidate generation** ([grounding/candidates.py](../../src/palimpsest/terminology/grounding/candidates.py)): every grounding strategy uses one path, so api_first / llm_judge / hybrid see identical candidates and the tournament is a fair 1:1 comparison. Search widens only when thin: `wbsearchentities` (prefix) → **CirrusSearch** full-text on a total miss → Wikipedia RU-title as a last resort. QIDs are redirect-canonicalised (built from the enriched `entity["id"]`).
- **Swappable strategies, one verdict.** Verdict logic ([verdict.py](../../src/palimpsest/terminology/verdict.py)) is shared; strategies differ only in candidate generation / QID choice / locate.
  - Grounding: **G1 `api_first`** (default, deterministic) · **G3 `llm_judge`** (subagent picks QID + rates difficulty) · **G5 `hybrid`** (api_first difficulty + judge-picked QID) · **G2 `mgenre`** (GPU, code-only, not run).
  - Pairing: **P1 `link_locate`** (default) · **P3 `llm_judge`** · **P2 `neural_align`** (GPU, code-only).
- **Notability-based ambiguity** ([verdict.py](../../src/palimpsest/terminology/verdict.py)): difficulty is 🟡 only when ≥2 candidates that both exact-match the name have an enwiki sitelink (real homonyms); a single notable match is 🟢. Every candidate now carries the `notable` flag (a prior bug where G3's candidates lacked it — collapsing the deterministic yellow path — is fixed).
- **Anachronism blocklist** ([wikidata.py](../../src/palimpsest/terminology/wikidata.py)): a football club / band / film cannot appear in a Bronze-Age text, so those P31 types are dropped — this removes the classic "Спарта → AC Sparta Prague" error. (The overnight grounding cycle had no such list.)
- **Head-token guard on pairing** ([verdict.py](../../src/palimpsest/terminology/verdict.py)): a sub-0.95 fuzzy match must share the form's head content-word, so "town of Akkad" never matches "Sargon of Akkad". This is strictly safer than a plural-suffix normaliser alone (which mis-merges "herms"/"Hermes").
- **Russian is inflected** → grounding searches the **nominative lemma** first, then the surface. Lemmas ([lemmas.json](../../data/seed/lemmas.json)) also key the golden merge, so `Аккаде` (pairing) and `Аккад` (grounding) dedup to one term instead of surviving as two rows with conflicting labels; applying them cut the golden's zero-candidate rate to 10/99.
- **LLM only through subagents.** Strategies take an injected `judge`; `src/palimpsest/terminology/` imports no `openai`/`LLMClient` (other stages legitimately use `palimpsest.llm.client`). The overnight harness backs `judge` with a Sonnet subagent (`temperature=0`, structured output).

## Interface

```python
def ground(mention: TermMention, *, judge: Judge | None = None) -> GroundingResult
def pair(req: PairRequest, *, judge: Judge | None = None) -> PairResult
def pipeline.run(source, target, mentions, *, grounder, pairer) -> list[Term]
```

Extract ([extract.py](../../src/palimpsest/terminology/extract.py)) is now real code, not a stub:

```python
def llm_surfaces(source: str, *, extractor: Extractor | None = None) -> list[dict]
def deterministic_surfaces(source: str) -> list[dict]
def extract_key(source: str, ner_config: dict) -> str
def extract_paragraph_terms(source, target, ner_config, *, grounder, pairer, extractor=None) -> list[Term]
def parse_surfaces(raw: str) -> list[dict]
def validate_surfaces(source: str, surfaces: list[dict]) -> tuple[list[dict], int]
DEFAULT_NER_PROMPT: str
CATEGORIES: set[str]
```

`llm_surfaces` is the real extractor ("E1"): an injected `Extractor` (`base.py`) turns source text into `[{surface, category}]`; every surface is `validate_surfaces`-guarded as a literal substring of `source` (drops hallucinated/translated surfaces). `extractor=None` degrades to `deterministic_surfaces` (capitalised-proper-noun runs + [gazetteer.py](../../src/palimpsest/terminology/gazetteer.py) + guarded ethnonym suffixes), so the module stays importable/testable without a model. `DEFAULT_NER_PROMPT` is the editable NER prompt (Settings-configurable via `NerConfig`, see model-registry contract below). `terminology/` still imports no `openai` — the LLM call lives in the injected `Extractor`, same subagent-injection pattern as `Judge`.

`Term` columns mirror the `term` DDL exactly. CLI: [scripts/term_pipeline.py](../../scripts/term_pipeline.py) (`extract` subcommand, OR-backed, budget-guarded). Golden merge: [scripts/merge_goldens.py](../../scripts/merge_goldens.py) — merges [data/seed/terminology_gold.jsonl](../../data/seed/terminology_gold.jsonl) from three independent, non-circular sources ([data/seed/gold_sources/](../../data/seed/gold_sources/)). Extraction eval: [scripts/eval_extraction.py](../../scripts/eval_extraction.py) → `reports/terminology/extraction_metrics.json`. Grounding/pairing eval: [scripts/eval_strategies.py](../../scripts/eval_strategies.py) → `reports/terminology/metrics.json`. Demo rebuild: [scripts/rebuild_demo.py](../../scripts/rebuild_demo.py).

## Subtleties

- **Contract null rule** is enforced in `pipeline.run`: `difficulty='red'` ⇒ `grounded=None`, `candidates=[]`, `pair_accuracy=None`, `recommended=None`. `candidates_json` is always `'[]'`, never NULL.
- **Per-occurrence.** One `Term` row per occurrence; identical surfaces ground identically (context-embedding disambiguation is **future work**).
- **Canonical EN forms** drop non-Latin aliases (cuneiform) and add a person short form (`Sargon of Akkad` → `Sargon`); the head-token guard stops a shared tail matching.
- **Recall floor.** 10/99 golden terms yield no Wikidata search candidates even after lemmatisation + CirrusSearch — thin items with no RU label / no sitelink (Chinese neolithic sites, Akkadian social classes). These are the honest ceiling of search-based grounding.
- **Difficulty macro-F1 is dominated by the rare yellow class** (9/99) — the headline grounding number is **QID accuracy on groundable terms**, not difficulty-F1.
- **Ancient vs modern sense.** The judge can pick the modern-city sense of an ancient place (e.g. Тадмор → Tadmur Q938457, the modern town, not ancient Palmyra) — flagged 🟡, so honest, but see [known_issues](../known_issues.md).
- **Extraction recall/precision are measured by case** (lowercase vs capitalised), not as one blended number — Russian capitalises sentence starts, so capitalised-only extractors trivially miss all lowercase terms (nouns, ethnonyms, titles) while scoring well on capitalised names; case-split metrics expose that split honestly (see Status).
- **Gazetteer entries are recall-hints only** ([gazetteer.py](../../src/palimpsest/terminology/gazetteer.py)) — no QIDs, no notability claim. Grounding remains the sole existence authority; the gazetteer only widens what gets *proposed* as a candidate surface.
- **`extract_key`** is a stable cache key, not a Python `hash()`: `sha256(source + "|" + modelName + "|" + prompt + "|" + json.dumps(params, sort_keys=True))`. `hash()` is per-process salted (`PYTHONHASHSEED`) and would go stale on every uvicorn restart.

## Status

Runnable end-to-end on the 15 seed paragraphs against live Wikidata. **Unified golden = 99 hand-verified terms** (82🟢/9🟡/8🔴), merged from three source goldens ([data/seed/gold_sources/](../../data/seed/gold_sources/)), deduped by nominative lemma, with 14 QID/difficulty conflicts resolved by direct Wikidata verification (non-circular; 94/99 rows carry a `source_url` — the 5 without are from the v1 source, which had none).

The term counts below (269 terms, 🟢157/🟡29/🔴83) predate the [seed-refresh](../superpowers/plans/2026-07-02-seed-refresh.md) rebuild and were measured against the old 16-paragraph seed. **Superseded** — seed-refresh Phase C reran extraction/grounding/pairing on the new 15-paragraph slice; current demo numbers are 204 terms, 🟢62/🟡31/🔴111 (see the seed-refresh paragraph below).

Tournament (vs golden, comparable on one set):

| grounding | QID acc | difficulty macro-F1 | | pairing | verdict macro-F1 |
|---|---|---|---|---|---|
| G1 api_first | 0.67 | 0.48 | | P1 link_locate | 0.38 |
| **G3 llm_judge** | **0.78** | 0.56 | | **P3 llm_judge** | **0.84** |
| G5 hybrid | 0.78 | 0.48 (coverage 0.90) | | | |

**Winners: G3 grounding + P3 pairing.** This revises both earlier conclusions: the merged module's "P1 pairing wins" was an artefact of an all-green golden (no hard cases — P3 scores yellow-F1 **0.89** vs P1's **0.0**); the overnight cycle's "hybrid grounding wins" was specific to its score-based difficulty (0.47) — with a judge that rates difficulty directly, G3 wins outright and hybrid ties it on QID accuracy (0.78) at higher coverage (0.90).

Demo uses the winners: **G3 grounding + P1/P3 pairing** (P1 baseline, P3 verdicts overlaid on the curated hard cases). G3 + the homonym audit keep grounding precise; the demo's difficulty mix is governed by the E1 extractor (see the Extraction section below). Current demo mix, on the seed-refresh 15-paragraph slice: 204 terms, 🟢62 / 🟡31 / 🔴111 (see the seed-refresh paragraph below; the 🟢157/🟡29/🔴83 figure here was the pre-seed-refresh 16-paragraph mix and is superseded). G2/P2 (GPU) implemented but not run.

**Extraction (E1) — measured recall AND precision** ([reports/terminology/extraction_metrics.json](../../reports/terminology/extraction_metrics.json)), by case, against the unified gold [data/seed/terminology_gold.jsonl](../../data/seed/terminology_gold.jsonl) (merged non-circularly from three independent sources by [scripts/merge_goldens.py](../../scripts/merge_goldens.py)):

| extractor | lowercase recall | all recall | all precision |
|---|---|---|---|
| old_caps (pre-this-change) | 0.00 | 0.57 | 0.39 |
| deterministic (caps + gazetteer) | 0.50 | 0.73 | 0.41 |
| **llm (E1, claude-haiku-4.5 via OpenRouter, temperature 0)** | **0.906** | **0.909** | **0.437** |

Precision is now measured — this closes the earlier "precision unmeasured (future work)" gap.

**Model choice (2026-07-02 tournament).** A 7-model real-OpenRouter tournament + adversarial LLM-judge panel picked **`anthropic/claude-haiku-4.5`** as the E1 default: it ties the top lowercase recall (0.906) but with ~half the noise of `gemini-2.5-flash-lite` (judge noise ≈12% vs 30%) and far fewer misses of easy named entities. No model *beat* the baseline recall; frontier **reasoning** models (gpt-5-mini) were excluded as cost/latency-prohibitive (~$0.26 for a partial run). Budget alternative with equal recall + more noise: `gemini-2.5-flash-lite`. Full evidence: [docs/reports/2026-07-02-ner-model-tournament.html](../reports/2026-07-02-ner-model-tournament.html). Tournament OR spend (7 models × 16 paragraphs, credits-delta): **~$0.39 total**.

Demo regenerated on the winner (real OR extract → live-Wikidata candidates → G3 LLM-judge grounding with a homonym audit → `rebuild_demo`) on the pre-seed-refresh 16-paragraph seed: **269 terms**, difficulty 🟢157 / 🟡29 / 🔴83. The fresh G3 pass with the audit collapsed the old mislink-yellows (99→29; e.g. `номов`→*Nome, Alaska* is fixed to the Egyptian nome Q223706) and grounded new entities (клерухии, принципат, неолит, гермокопидов). Red-rate `red/(red+green)` = **0.346** (< 0.35 SC7, thin margin: haiku's residual generic-noun over-capture — царя/титулов/полисов — correctly falls to red, as do obscure entities Wikidata lacks).

Demo seed regenerated from gemma_par_by_par via [scripts/rebuild_seed_texts.py](../../scripts/rebuild_seed_texts.py) (15 body paragraphs, replacing the 16-paragraph seed above); baselines via local `/evaluate`, terminology via haiku extract + subagent G3/P3 grounding/pairing (`scripts/rebuild_demo.py` → `data/seed/terminology_out.json`: 204 terms, difficulty 🟢62/🟡31/🔴111) loaded into the seed JSONL by [scripts/load_terms_into_seed.py](../../scripts/load_terms_into_seed.py) — see the [seed-refresh plan](../superpowers/plans/2026-07-02-seed-refresh.md). This JSONL adapter only carries `identified_terms` surfaces into the mock-path seed data; the live `term` table's real `difficulty`/`pairAccuracy` verdicts come from a separate load step, `scripts/load_terms.py`, run after seeding — see [webapp.md](../subsystems/webapp.md) `seed.py` row.
