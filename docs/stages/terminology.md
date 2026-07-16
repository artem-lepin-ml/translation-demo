# Stage — Terminology (difficulty + pairAccuracy)

Up-link: [docs/README.md](../README.md) · [docs/pipeline.md](../pipeline.md). Design: [G6 label_first design](../superpowers/specs/2026-07-03-grounding-label-first-design.md) · [terminology e2e spec](../superpowers/specs/2026-07-01-terminology-e2e-design.md) (pairing sections only — grounding sections LEGACY) · [consolidation design](../superpowers/specs/2026-07-01-terminology-consolidation-design.md) (grounding sections LEGACY). Contract: [demo contracts §1/§4](../superpowers/specs/2026-06-30-demo-contracts.md).

> **Supersession note (2026-07-03).** Grounding strategies G1 `api_first`, G2 `mgenre`, G3 `llm_judge`, G5 `hybrid` are removed and archived at tag `archive/grounding-g-strategies`. The single grounding strategy is now **G6 `label_first`** (below). The former G3 reference number, **QID accuracy 0.78**, was scored on an older, smaller gold set (78 groundable terms) and is kept here only as a historical baseline — it is **not** directly comparable to the G6 ablation table in this doc (measured on 91 groundable terms; see Status). Pairing strategies (P1/P3) are unaffected by this change.

## Purpose

Turn a `(RU source, EN translation)` paragraph into the full `Term[]` the demo shows, filling **both** terminology signals of the `Term` contract:

- **difficulty** (`ground`) — is the source term a groundable Wikidata entity? 🟢 confirmed / 🟡 ambiguous / 🔴 not found.
- **pairAccuracy** (`pair`) — did the translation render it with the canonical English equivalent? 🟢 / 🟡 / 🔴 + `recommended`. `null` when difficulty=🔴 (also 🟡 with `resolved_by='judge_unavailable'`, see Subtleties).

Flow: `extract` (RU term mentions) → `ground` (Wikidata QID + difficulty) → `pair` (locate canonical EN in the translation) → assemble `Term[]`.

## Design decisions

- **Frozen interface first** ([base.py](../../src/palimpsest/terminology/base.py)): `GroundingStrategy.ground(mention, *, judge=None) -> GroundingResult` and `PairingStrategy.pair(req, *, judge=None) -> PairResult`. The judge is injected at **call time**.
- **Deterministic candidate generation, unchanged ladder** ([grounding/candidates.py](../../src/palimpsest/terminology/grounding/candidates.py)): `generate_candidates(wd, mention, config) -> {candidates, canon_by_qid, source, n_hits, queries}`, parameterized by `GroundingConfig`. Query order: `wbsearchentities(lemma)` (if `use_lemma` and lemma≠surface) → `wbsearchentities(surface)` → if 0 hits and `use_cirrus`: CirrusSearch full-text on both forms → if still 0 and `use_sitelink`: RU-Wikipedia title → wikibase item. Every query call appends `{q, kind, mechanism, strategy, n_hits}` to `queries` (feeds the trace). `strategy` (added 2026-07-16, owner UI review) labels which of the up to 3 escalating Wikidata backends produced the call — `"prefix"` (`wbsearchentities`, rungs 1-2 AND the `search_mode="alt-names"/"label-guess"` widening tiers, since they hit the same backend with a derived form), `"cirrus"` (rung 3), `"sitelink"` (rung 4) — so a trace UI can render "5 calls for 2 words" as a labeled escalation ladder instead of undifferentiated repetition; values are exactly `prefix|cirrus|sitelink`, 1:1 with `mechanism` (`mechanism` is the low-level API method name, `strategy` is the UI-facing tier label — added as a new key alongside `mechanism` rather than replacing it, so existing `mechanism`-based assertions in tests/eval tooling are untouched). Dedup by QID, enrich top-`enrich_top` via `wbgetentities` (labels/descriptions/aliases ru+en), redirects canonicalized from the enriched `entity["id"]`. Candidate order is a **documented invariant**: insertion-order dedup, stable across cache replays — not incidental. No type filter (see below).
- **G6 `label_first` — one strategy, deterministic-first** ([grounding/label_first.py](../../src/palimpsest/terminology/grounding/label_first.py)): exact label/alias match resolves without any model call; the LLM judge is escalated only on genuine ambiguity (≥2 exact matches) or inexactness (candidates exist, none match). Decision table:

  | Exact label-match outcome | Action | difficulty | `resolved_by` |
  |---|---|---|---|
  | Exactly 1 exact match | QID taken deterministically, no LLM call | 🟢 | `exact_label` |
  | ≥2 exact matches | judge disambiguates over candidate label+description+context | 🟡 | `llm_disambiguation` |
  | 0 exact, candidates exist | judge; picks → 🟡, rejects all → 🔴 | 🟡/🔴 | `llm_disambiguation` / `judge_rejected` |
  | 0 candidates after fallbacks | red, no LLM | 🔴 | `no_candidates` |

  Exact match: `norm(query) == norm(label_ru)` for `query` ∈ {lemma, surface}, extended to aliases when `match_aliases` is on. Every candidate records `matched` — which label/alias it hit and via which query form — the basis of trace transparency.

  **Error policy (full):** Wikidata unavailable (client exhausted retries, `RuntimeError`) → 🔴 `wikidata_unavailable`, distinct from `no_candidates` (excluded from eval metrics, counted separately — a network failure must never masquerade as an honest red). Judge unavailable (unconfigured, or transient error after retries) on a required escalation → 🟡 `judge_unavailable`, `chosen_qid = null`, `grounded = null` — an honest "unresolved ambiguity", never a silent top-1 fallback. Malformed judge JSON is **terminal, not retried** (blind retries burn budget); only transient 429/5xx/timeout retry, max 2 backoffs. A judge QID outside the candidate list is a contract violation → `judge_unavailable`, never a silent top-1 fallback (the old G3 anti-pattern).

  Full `resolved_by` enum: `exact_label · llm_disambiguation · judge_rejected · judge_unavailable · wikidata_unavailable · no_candidates`.
- **No type filter, no anachronism blocklist** ([grounding/candidates.py](../../src/palimpsest/terminology/grounding/candidates.py)): the previous P31/P279 *type* filter and the anachronism blocklist (e.g. "Спарта → AC Sparta Prague") are both removed. The judge disambiguates by candidate description instead — a football club's one-line description makes the mismatch obvious without a hand-maintained list. Trade-off: the deterministic branch alone has no defense against a club/band being the *sole* exact label match; tracked as risk R1 in the design spec (previously mis-cited here as R7, which is actually the unrelated ё/е-folding risk — corrected 2026-07-16), watched via `known_issues.md`, not silently reintroduced.
- **Non-entity P31 blocklist + near-duplicate dedup** ([grounding/candidates.py](../../src/palimpsest/terminology/grounding/candidates.py), owner fix 2026-07-16): candidates are dropped when their P31 (instance of) claim — already fetched by `get_entities`'s `props`, zero extra network calls — is one of `Q17633526` (Wikinews article), `Q4167410` (Wikimedia disambiguation page), `Q4167836` (Wikimedia category), `Q11266439` (Wikimedia template), `Q13406463` (Wikimedia list article); falls back to a description-text match ("wikinews article") only when an entity carries no P31 claim at all. Root cause: CirrusSearch's full-text tier (rung 3) surfaced Wikinews-article items for «Египтяне» because it searches the whole item body, not just labels. This is **not** a reintroduction of the removed type filter above (D3/Q1 in the design spec) — that filter tried to pick the right entity *type* (city vs club vs person), which is the judge's job; this one drops Wikidata items that are wiki-maintenance structure and can never be a valid referent under *any* context, regardless of type. Candidates additionally deduped on an identical `(label_ru, label_en, description)` signature — i.e. render 100% identically to the judge (see `_format_judge_prompt`) — keeping the first; deliberately requires the *full* signature (not just `label_ru`+`description`) because two distinct entities legitimately sharing a Russian label is exactly the `>=2 exact matches` homonym case the judge escalation exists to disambiguate, and a looser key was caught silently collapsing that case to 1 candidate by this module's own test suite.
- **Judge prompt: temporal-context caveat** ([grounding/label_first.py](../../src/palimpsest/terminology/grounding/label_first.py) `DEFAULT_GROUNDING_JUDGE_SYSTEM_PROMPT`, owner fix 2026-07-16): root-caused from a real prod trace (document 10, term «Париж», context "Конец XXIII в. до н.э. Париж, Лувр") — the judge rejected the correct exact-match candidate Q90 (modern Paris) with reason *"the provided candidates refer to modern entities [...] whereas the context mentions Paris in the 23rd century BC"*, i.e. it treated a date describing the artifact/narrative as a constraint the referent itself must satisfy. Not a candidate-list problem (Q90 was present and exact-matched; the 5-candidate list was mostly legitimate near-homonyms — 2 football clubs, a Texas city, a surname — not junk the P31 filter above would remove). The system prompt now explicitly tells the judge that context can mix an ancient narrated period with a modern fact about the same subject (an artifact's current location), and that an enduring real-world referent must not be rejected merely for an era mismatch — only for a genuine identity mismatch. General mechanism, not a "Париж" special case.
- **`norm()` folding** ([grounding/match.py](../../src/palimpsest/terminology/grounding/match.py)): NFC normalize → fold Unicode dashes (U+2010–U+2015, U+2212 → `-`) → ё→е → collapse whitespace → casefold. Motivation: Wikidata RU labels are inconsistent on ё/е, and transliterated names ("Кадашман-Харбе") arrive with different dash codepoints from OCR/translation — without folding, honest exact matches fall into unnecessary escalation. The ё/е fold carries a theoretical risk of conflating two distinct entities that differ only by that letter; accepted consciously (the recall win on real label inconsistency clearly outweighs it), covered by a unit test, and any real occurrence goes to `known_issues.md` rather than reverting the fold silently.
- **Config: four independent, ablatable toggles** (`GroundingConfig`, frozen dataclass): `use_lemma` (search lemma before surface), `use_cirrus` (CirrusSearch full-text on zero hits), `use_sitelink` (RU-Wikipedia title → Wikidata item on zero hits, split off `use_cirrus` 2026-07-06 — it shares its title→QID mapping with the wiki-eval reference annotations and creates evaluation circularity when scored together, see [wiki-eval.md](wiki-eval.md) Subtleties), `match_aliases` (extend exact-match set to aliases ru/en). `search_limit=7`/`enrich_top=5` are fixed constants, not ablation axes. Each toggle acts at exactly one point in the algorithm, so its contribution is isolated and interpretable (see the ablation table below). **Deprecated compat:** the constructor still accepts `use_fallbacks=<bool>` (sets both `use_cirrus` and `use_sitelink`); reading it back returns `True` only when both are `True` — existing call sites and the 3-bit ablation bit-configs below keep working unchanged.
- **Judge-decision cache — "one sense per discourse".** Keyed by `(scope_id, lemma, candidates_qids, model, prompt_hash)`; `scope_id` = paragraph (demo) / document (eval). In-memory, upsert last-write-wins, sequential grounding — not a DB table (no cross-run-persistence caller exists yet; promoting to a table is a localized change if one appears). The cache wraps the injected `judge` callable, so `LabelFirstGrounding` itself stays cache-agnostic.
- **Swappable pairing, shared verdict logic** ([verdict.py](../../src/palimpsest/terminology/verdict.py)) is unchanged by this revision: **P1 `link_locate`** (default) · **P3 `llm_judge`** · **P2 `neural_align`** (GPU, code-only, not run).
- **Head-token guard on pairing** ([verdict.py](../../src/palimpsest/terminology/verdict.py)): a sub-0.95 fuzzy match must share the form's head content-word, so "town of Akkad" never matches "Sargon of Akkad".
- **Russian is inflected → the extractor emits the lemma.** Grounding searches the nominative lemma (extractor-emitted `{surface, lemma, category}`) before the surface — see [extract.py](../../src/palimpsest/terminology/extract.py) and the NER prompt. The static `lemmas.json` file no longer feeds the pipeline; it survives **only** as an input to [scripts/merge_goldens.py](../../scripts/merge_goldens.py) (golden-tooling exception, unrelated to the live extract→ground path).
- **LLM only through subagents.** Strategies take an injected `judge`; `src/palimpsest/terminology/` imports no `openai`/`LLMClient`.

## Interface

```python
def ground(mention: TermMention, *, judge: Judge | None = None) -> GroundingResult
def pair(req: PairRequest, *, judge: Judge | None = None) -> PairResult
def pipeline.run(source, target, mentions, *, grounder, pairer, judge=None) -> list[Term]
```

Grounding config:

```python
@dataclass(frozen=True)
class GroundingConfig:
    use_lemma: bool = True
    use_cirrus: bool = True
    use_sitelink: bool = True
    match_aliases: bool = True
    search_limit: int = 7
    enrich_top: int = 5
    # use_fallbacks: bool | None = None  -- deprecated constructor-only compat
    # alias (not a stored field): sets both use_cirrus/use_sitelink; reading
    # it back is True only when both are True.
```

Extract ([extract.py](../../src/palimpsest/terminology/extract.py)):

```python
def llm_surfaces(source: str, *, extractor: Extractor | None = None) -> list[dict]
def deterministic_surfaces(source: str) -> list[dict]
def extract_key(source: str, ner_config: dict) -> str
def extract_paragraph_terms(source, target, ner_config, *, grounder, pairer, extractor=None) -> list[Term]
def parse_surfaces(raw: str) -> list[dict]
def validate_surfaces(source: str, surfaces: list[dict]) -> tuple[list[dict], int]
def ner_user(source: str) -> str
NER_SYSTEM_PROMPT: str
NER_CATEGORIES: tuple[str, ...]
```

`llm_surfaces` ("E1"): an injected `Extractor` turns source text into `[{surface, lemma, category}]` — the lemma is the nominative form (multi-word: agreed nominative, e.g. «династии Цин» → «династия Цин»); an empty/>80-char/newline-containing lemma falls back to `lemma = surface`. Every surface is `validate_surfaces`-guarded as a literal substring of `source`. `extractor=None` degrades to `deterministic_surfaces` (capitalised-proper-noun runs + [gazetteer.py](../../src/palimpsest/terminology/gazetteer.py) + guarded ethnonym suffixes; `lemma = surface`), so the module stays importable/testable without a model. `NER_SYSTEM_PROMPT` is the FROZEN NER system prompt (2026-07-10, see the file's own docstring — do not edit without an owner-approved spec amendment); `ner_user(source)` wraps the per-call source text. `category` (2026-07-10) is one of `NER_CATEGORIES` or `"other"`; an unrecognized raw value is normalized to `"other"` with the original preserved as `category_raw` — never a parse failure. *(Renamed 2026-07-11 from the pre-pin `DEFAULT_NER_PROMPT`/`CATEGORIES` names some offline scripts, e.g. `scripts/term_pipeline.py`, still reference — see § Live trigger below.)*

`Term` columns mirror the `term` DDL exactly, including `trace_json` (GroundingTrace v1, see below). CLI: [scripts/term_pipeline.py](../../scripts/term_pipeline.py) (`extract` subcommand, OR-backed, budget-guarded). Golden merge: [scripts/merge_goldens.py](../../scripts/merge_goldens.py) — merges [data/seed/terminology_gold.jsonl](../../data/seed/terminology_gold.jsonl) from three independent, non-circular sources ([data/seed/gold_sources/](../../data/seed/gold_sources/)), still reading `data/seed/lemmas.json` (D4 golden-tooling exception — the live pipeline does not). Grounding ablation eval: [scripts/eval_grounding.py](../../scripts/eval_grounding.py) → `reports/terminology/g6/<config-bits>/<run_id>/{metrics.json,traces.jsonl}`. Extraction eval: [scripts/eval_extraction.py](../../scripts/eval_extraction.py) → `reports/terminology/extraction_metrics.json`. `scripts/eval_strategies.py` (pairing eval) is removed — it imported the archived `ApiFirstGrounding` and never ran after the G6 cutover; superseded by `eval_grounding.py`. Demo rebuild: [scripts/rebuild_demo.py](../../scripts/rebuild_demo.py).

## Subtleties

- **Contract null rule** is enforced in `pipeline.run`: `difficulty='red'` ⇒ `grounded=None`, `candidates=[]`, `pair_accuracy=None`, `recommended=None`. **Extended (G6):** `difficulty='yellow'` with `resolved_by='judge_unavailable'` also yields `grounded=None` — a documented extension of the null rule (see [demo-contracts.md](../superpowers/specs/2026-06-30-demo-contracts.md)), not a violation. Frontend `term.grounded && …` truthiness checks treat `null` as "no node" regardless of `difficulty`. `candidates_json` is always `'[]'`, never NULL.
- **Per-mention isolation (2026-07-16 fix).** `pipeline.run`'s mention loop wraps each `grounder.ground()` call in its own `try/except`: any exception a strategy still lets escape for one mention (e.g. a non-retryable `urllib.error.HTTPError`/`OSError` from Wikidata) drops only that mention (logged at `warning`) — it no longer aborts the whole paragraph's extraction. `FatalGroundingJudgeError` is explicitly excluded from this isolation and still propagates to halt the run (see below). `LabelFirstGrounding.ground()`'s own candidate-gen catch is broadened the same way, from `RuntimeError` alone to `(RuntimeError, urllib.error.HTTPError, OSError)`, so a bare non-retryable HTTPError degrades to `red`/`wikidata_unavailable` at the strategy level already — the pipeline-level catch is defense-in-depth for any strategy/exception that isn't.
- **`norm()` and `resolved_by`.** `norm()` folds NFC + Unicode dashes (U+2010–U+2015, U+2212 → `-`) + ё→е + whitespace + casefold (risk R7 — see Design decisions). The `resolved_by` enum (`exact_label · llm_disambiguation · judge_rejected · judge_unavailable · wikidata_unavailable · no_candidates`) is the authoritative record of how a term's difficulty was decided and drives both the eval `resolved_by_distribution` metric and the Glossary UI's grounding-path badge (design-only for now, see the G6 spec §10).
- **Per-occurrence.** One `Term` row per occurrence; identical surfaces ground identically within the judge-decision cache scope (paragraph/document); across scopes, decisions are not shared — this is the intended "one sense per discourse" semantics, not a limitation.
- **Canonical EN forms** drop non-Latin aliases (cuneiform) and add a person short form (`Sargon of Akkad` → `Sargon`); the head-token guard stops a shared tail matching.
- **`wikidata_unavailable` vs `no_candidates`.** A Wikidata client failure (exhausted retries) is not treated as an honest red — it is excluded from eval accuracy metrics and counted separately (`n_excluded_wikidata_unavailable`), so a network blip never masquerades as a genuine "term doesn't exist" result.
- **Difficulty macro-F1 is dominated by the rare yellow class** — the headline grounding number is **QID accuracy on groundable terms**, not difficulty-F1.
- **Extraction recall/precision are measured by case** (lowercase vs capitalised) — Russian capitalises sentence starts, so capitalised-only extractors trivially miss all lowercase terms while scoring well on capitalised names.
- **Gazetteer entries are recall-hints only** ([gazetteer.py](../../src/palimpsest/terminology/gazetteer.py)) — no QIDs, no notability claim. Grounding remains the sole existence authority.
- **`extract_key`** is a stable cache key, not a Python `hash()`: `sha256(source + "|" + modelName + "|" + prompt + "|" + json.dumps(params, sort_keys=True))`.

## Status

Runnable end-to-end on the seed paragraphs against live Wikidata. Golden = 99 hand-verified terms, 91 groundable (see `n_groundable` in `metrics.json`), merged from three source goldens ([data/seed/gold_sources/](../../data/seed/gold_sources/)).

**G6 ablation** (8 configs = `use_lemma / use_fallbacks / match_aliases`, `itertools.product("01", repeat=3)`; QID accuracy on 91 groundable golden terms, Wilson 95% CI, run `2026-07-03T00-50-56Z`, from the committed `reports/terminology/g6/<bits>/<run_id>/metrics.json`). This is a historical run predating the `use_fallbacks` split (2026-07-06, see Design decisions) — its `fallback` bit exercised `use_cirrus` and `use_sitelink` together (both toggles moved as one), not independently; the table's numbers are unaffected by the split (the compat alias reproduces the same combined behavior) but do not isolate the two rungs' individual contributions. Context provenance for this run: 65/99 golden terms carry their own sentence context, 34/99 have no available context (their source paragraphs are from the larger book corpus, not the shipped 15-paragraph seed) and are judged with empty context — honestly counted as `n_context_unavailable`, not falsely reported as reconstructed:

| config (lemma·fallback·alias) | QID accuracy | Wilson CI95 | escalation rate |
|---|---|---|---|
| 000 | 0.363 | [0.271, 0.465] | 0.343 |
| 001 | 0.363 | [0.271, 0.465] | 0.323 |
| 010 | 0.505 | [0.405, 0.606] | 0.566 |
| 011 | 0.505 | [0.405, 0.606] | 0.525 |
| 100 | 0.681 | [0.580, 0.768] | 0.515 |
| 101 | 0.681 | [0.580, 0.768] | 0.515 |
| 110 | 0.714 | [0.614, 0.797] | 0.586 |
| **111** | **0.714** | **[0.614, 0.797]** | **0.586** |

Config `111` (all toggles on, the shipped default) measures **0.714 [0.614, 0.797]** on 91 groundable golden terms — ~6.5pp under the old G3 reference **0.78**, which was scored on a different, smaller gold set (78 groundable). The gap is genuine hard cases (niche no-candidate terms, correct judge rejections, a few label-only false positives) plus the 34 context-unavailable terms judged blind — not a regression; flagged for owner review. Dominant-lever finding (leave-one-in from the all-off baseline `000`=0.363): `use_lemma` contributes **~+0.32** QID accuracy (`100`=0.681), `use_fallbacks` **~+0.14** (`010`=0.505), `match_aliases` is **negligible (+0.00**, `001`=`000`=0.363) — lemma search does almost all of the work. `match_aliases` never changes accuracy on this set (110≡111, 100≡101, 000≡001); it is kept on for label/UI transparency, not accuracy. Numbers are stable across two independent judge runs (±1 term from the earlier `00-01-18Z` run), confirming robustness to gpt-4o-mini nondeterminism at temperature 0.

Pairing tournament (unaffected by G6, historical numbers, comparable on the pre-G6 golden):

| pairing | verdict macro-F1 |
|---|---|
| P1 link_locate | 0.38 |
| **P3 llm_judge** | **0.84** |

Demo uses **G6 label_first** grounding + P1/P3 pairing (P1 baseline, P3 verdicts overlaid on curated hard cases). G2/P2 (GPU) implemented but not run, kept as documented stubs.

**Extraction (E1) — measured recall AND precision** ([reports/terminology/extraction_metrics.json](../../reports/terminology/extraction_metrics.json)), by case, against the unified gold [data/seed/terminology_gold.jsonl](../../data/seed/terminology_gold.jsonl):

| extractor | lowercase recall | all recall | all precision |
|---|---|---|---|
| old_caps (pre-consolidation) | 0.00 | 0.57 | 0.39 |
| deterministic (caps + gazetteer) | 0.50 | 0.73 | 0.41 |
| **llm (E1, claude-haiku-4.5 via OpenRouter, temperature 0)** | **0.906** | **0.909** | **0.437** |

**Model choice (2026-07-02 tournament).** A 7-model real-OpenRouter tournament + adversarial LLM-judge panel picked **`anthropic/claude-haiku-4.5`** as the E1 default. ⚠️ The tournament's full HTML report (`docs/reports/2026-07-02-ner-model-tournament.html`) was never committed to any branch in this repo (confirmed via `git log --all --diff-filter=A`) — this paragraph plus the recall/precision table above is the surviving evidence.

Demo seed: 15 body paragraphs ([scripts/rebuild_seed_texts.py](../../scripts/rebuild_seed_texts.py)); terminology regenerated via `scripts/rebuild_demo.py` (haiku extract → G6 grounding, live judge on the CloseRouter gateway → P1/P3 pairing) into `data/seed/terminology_out.json`, loaded by [scripts/load_terms_into_seed.py](../../scripts/load_terms_into_seed.py) / [scripts/load_terms.py](../../scripts/load_terms.py) (or `make reseed`, which chains seed + load) — see the [seed-refresh plan](../superpowers/plans/2026-07-02-seed-refresh.md) and [webapp.md](../subsystems/webapp.md) `seed.py` row. Current difficulty distribution (single source of truth): [docs/testing/e2e-data.md](../testing/e2e-data.md).

**Demo mention lemmas (2026-07-07).** The seed mentions in `data/seed/terminology_terms.jsonl` originally carried `lemma == surface` (the raw inflected form) for most entries, violating the "grounding searches the nominative lemma" invariant above — every non-nominative occurrence of the demo's own core entities (Mesopotamia, Babylon, Euphrates, Assyria, Sumer) missed its candidate on `wbsearchentities` and fell through to a judge rejection despite being trivially groundable. [scripts/fix_mention_lemmas.py](../../scripts/fix_mention_lemmas.py) corrects the `lemma` field only (surface/spans/context/category untouched), from `data/seed/lemmas.json` where it has a nominative and an LLM lemmatizer pass (same CloseRouter provider as the judge) for the gaps — run once before `rebuild_demo.py`; re-running it recomputes from the current file and is a no-op on an already-correct lemma. This is a seed-data fix, not a pipeline change — the golden-eval `lemmas.json` consumer (`merge_goldens.py`, D4 exception) and the live extractor's own lemma output are unaffected.

## Live trigger (webapp, 2026-07-11 EMNLP sprint)

The pipeline above is no longer offline-only: [`webapp/terminology_live.py`](../../src/palimpsest/webapp/terminology_live.py) runs it automatically in the background for a newly-created document (upload or AI-translate), unmodified — same `LabelFirstGrounding`, same `GroundingConfig()` plain defaults (`search_mode="baseline"`, pinned), same `LinkLocatePairing` (P1) the offline seed generator (`scripts/term_pipeline.py`'s `cmd_run`) used. Webapp wiring (launch points, `document.terms_status`, the async/sync bridge that lets the frozen synchronous `Judge` protocol reach the async budget-guarded live judge call) is documented in [webapp.md § Live terminology](../subsystems/webapp.md#live-terminology) — not duplicated here, single source of truth. Two corrections this wiring makes to code that predates it:

- `app._grounding_judge_live` previously sent an empty system-message string (`client.complete("", prompt)`) — dead code with no caller, per its own "TODO(wired when live re-grounding endpoint exists)" note. It now sends `DEFAULT_GROUNDING_JUDGE_SYSTEM_PROMPT` (this module's `grounding/label_first.py`) as the system message, matching the Role/output-contract every other caller of that prompt (`scripts/wiki_eval.py`'s `_build_judge`) already relies on.
- `scripts/term_pipeline.py` (the offline seed generator) imports `DEFAULT_NER_PROMPT`/`deterministic_surfaces`/`CATEGORIES`-era names from `extract.py` that no longer exist after the G6/wiki-eval-experiment pin (`extract.py` now exports `NER_SYSTEM_PROMPT`/`ner_user()`/`NER_CATEGORIES`, see § Interface above) — that CLI is currently unrunnable as committed; not touched here (out of scope for the live-trigger task), flagged so a future re-run of the offline seed pipeline doesn't silently fail on a stale import.

**Note on `scripts/enrich_seed_terms.py`.** Despite the name, this script is NOT the pairing reference — it only enriches the older `data/seed/seed_paragraphs.jsonl` mock structure with grounding (`qid`/`resolved_by`/`candidates`), has no pairing logic at all, and never writes to the `term` table. The actual seed generator that produced `data/seed/terminology_out.json` (loaded into `term` by `scripts/load_terms.py`) is `scripts/term_pipeline.py`'s `cmd_run`, using `LabelFirstGrounding` + `LinkLocatePairing` exactly as the live pipeline now does.

## Methodology (article draft, EN)

> Terms are grounded to Wikidata in two tiers. First, a **deterministic exact-label match**: we query `wbsearchentities` with the term's nominative lemma and surface form; if exactly one candidate's Russian label (or alias) equals the query, it is accepted without any model call. Second, only when the label is **ambiguous** (several exact matches) or **inexact** (candidates exist but none match exactly), an LLM disambiguates over the candidates' one-line Wikidata descriptions given the source sentence, returning a single entity or abstaining. Terms with no candidates after search fallbacks are marked ungroundable. This yields a natural transparency metric — the **share of terms resolved deterministically vs. via LLM** — and each decision carries a per-decision machine-readable trace (queries, candidates, match kind, judge model, rationale, token usage). We ablate the three components of the deterministic tier — two retrieval (lemma search, full-text fallback) and one matching (alias expansion) — in both leave-one-in and leave-one-out ladders. Within a document we cache disambiguation decisions per (lemma, candidate set) — the standard one-sense-per-discourse assumption.
