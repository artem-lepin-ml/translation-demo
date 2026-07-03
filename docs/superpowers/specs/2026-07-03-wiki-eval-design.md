# Wiki-evaluation of NER + Wikidata grounding — design (E1 + E2)

Up-link: [docs/superpowers/](../) · pipeline: [docs/pipeline.md](../../pipeline.md) · depends on [G6 label_first spec](2026-07-03-grounding-label-first-design.md). Owner-facing design report: `scratchpad/report-g6-design/eval-design.html`.

## 1. Goal & scope

**Goal (verifiable state).** A reproducible harness that measures our NER + Wikidata grounding (G6 `label_first`) against human link annotations on **100 full Russian Wikipedia history articles**, reporting **recall as the primary metric** plus three precision variants and three matching modes, sliced by strata / resolution-path / term-type, with raw counts and Wilson 95% CI. Output: `metrics.json`, an HTML report in the project palette, and a 0.5–1 page EN paper-draft section.

**Persistence scope (precise).** Everything expensive is persisted (traces, Wikidata cache, judge cache, GT, cached HTML). Two tiers of "re-derive without paying the model again":
- **Offline recompute (no run at all):** any new *scoring / slicing* metric over the already-materialized GT and prediction tuples (new matching mode, new precision denominator, new slice) — pure recomputation of `matching.py` + `metrics.py` over existing files.
- **Rebuild-from-cache (a `build-gt` re-run, still zero network):** any change to the *GT definition itself* (tokenization scheme, P31 exclusion set, hardness formula) re-derives from the cached HTML snapshot — no Wikipedia/Wikidata calls, but not a pure recompute.
This distinction is a DoD check: the harness must never require re-calling the paid LLM to produce a new metric.

**In scope.** Dataset builder (E1) + evaluation harness (E2), merged into one spec per owner decision (E1 is mostly deterministic and delegated to Claude).

**Non-goals.**
- E3 disambiguation-trap benchmark (100 sentences with Qing / Roman / Seal / May, LLM-generated + owner-annotated) — deferred; recorded as future work only.
- LLM-as-a-judge translation evaluation and the e2e site pipeline (points 1–2 of the supervisor summary) — different chat scope.
- COMET / fluency — out of scope.

**Success criteria.**
1. `wiki_eval build-gt` produces `data/eval/wiki/gt.jsonl` from 100 articles with per-page strata labels and a cached HTML snapshot, deterministically re-runnable from cache with zero network.
2. `wiki_eval run` grounds the same text through the unmodified G6 pipeline and writes traces; `wiki_eval report` computes recall (3 modes) + precision (3 variants) + slices + CI into `metrics.json` and HTML, all offline-recomputable.
3. Full 8-config ablation runs under a `--max-usd 40` cumulative cap with a mandatory `--dry-run` forecast.
4. Metrics interpret only differences beyond the noise floor (Wilson CI, ≥3-tuple rule inherited from G6).

## 2. Decision journal

| # | Decision | Rationale |
|---|---|---|
| E-D1 | **100 full articles, no 1k tier** | Owner. ~10–30k GT tuples → narrow CI; matches supervisor's 50–100. |
| E-D2 | **Stratified 50 hard + 50 typical**, metrics reported per stratum | Owner (variant C). Averages hide degradation on hard text; hard/typical split is the strong result for the paper. |
| E-D3 | **Hardness score without LLM** = share of ambiguous anchors on a page: piped links (`[[Цин (династия)\|Цин]]`, anchor ≠ target title) + anchor words that resolve to different QIDs across the pool. Supervisor's examples (Qing dynasty etc.) are forced seeds into the hard stratum; the report discloses **how many of the 50 hard pages are forced seeds vs. score-ranked**, and each seed's hardness percentile. | Determinism & interpretability. **Non-circularity note:** hardness measures the *intrinsic lexical ambiguity of the anchor surface* (is this word polysemous in the corpus?), **not** *system difficulty* (did we get it right?) — it never uses model output. It does read gold QIDs to detect "same surface → different QID across pages," so the report states this openly to preempt the label-leakage objection: a hard page is one whose surfaces are genuinely polysemous, chosen without any knowledge of whether the system succeeds. |
| E-D4 | **Pool domain** = world-history categories weighted to the book's period (ancient world, antiquity, middle ages) | Eval should measure the system on a distribution close to prod text (world history vol. 1). Delegated to Claude. |
| E-D5 | **Text & links source = Parsoid HTML** (`action=parse` / REST `/page/html`), body paragraphs only; no infoboxes / navboxes / references / tables | Wikitext parsing loses template text and needs custom normalization; HTML gives ready anchor offsets. Raw HTML cached in LFS → reproducibility, zero re-fetch. |
| E-D6 | **Tokenization — pinned algorithm.** (1) Flatten Parsoid HTML body paragraphs to text, joining paragraphs with a single `\n`; NBSP (U+00A0) and other Unicode spaces normalized to ASCII space *before* splitting. (2) Split on `re.split(r"\s+", text)` (Unicode-aware), dropping empty tokens; punctuation stays attached to its token (`"Рима,"` = one token) — matching relies on `norm()`/lemma, not on stripping punctuation. (3) Index = 0-based token position in the whole-article stream (continuous across paragraphs, no per-paragraph reset). A multi-word anchor → one tuple `(index of first token, anchor surface, QID, span_len)`; `span_len` (token count) drives M2 overlap. | A single fully-specified tokenizer removes the main determinism/ambiguity risk; multi-word handled by M2 overlap, not by complicating identity. Parser + regex are fixed constants of `wiki_gt`. |
| E-D7 | **Link→QID mapping** = `wiki_gt` implements its own batched pageprops fetcher (≤50 pipe-joined titles via `action=query&prop=pageprops&redirects=1`). *The existing `WikidataClient.wikipedia_wikibase_item` is single-title only — this batch fetcher is new eval-owned code, not a reuse.* Records BOTH `anchor_target_title` (as in the href) and `canonical_title` (post-redirect, from the response `redirects` map); P31 chronology filter (E-D8) operates on the canonical entity. | One cheap API path; redirects are the main source of false title mismatches, and recording both titles keeps the mapping auditable. |
| E-D8 | **GT filters**: main-namespace links only; exclude chronology by a **closed, versioned** target-`P31` set (`Q3186692` calendar year, `Q39911` decade, `Q578` century, `Q3311614` millennium, `Q29964144` year BC, and the explicit list in §11) → counter `n_excluded_chrono`. The P31-set version hash is stored in `gt.jsonl` metadata. | Chronology links are a Wikipedia convention, not terminology; deterministic. A closed+versioned set means a future change can't silently redefine GT (and the denominator of recall) without a visible version bump. |
| E-D9 | **3 matching modes** (§4): M1 strict index, M2 span-overlap (primary), M3 document-level | Closes the G6-inherited question (first-mention GT × "one sense per discourse" cache): the M2↔M3 gap directly prices "wrong mention". |
| E-D10 | **Full ablation 8×100**, two ladders (leave-one-in / leave-one-out) | Owner (variant A). Real cost ≈ ×2–3 of the base run (caches shared across configs), not ×8. |
| E-D11 | **Budget guard = in-process reservation, NOT credits polling.** The `--max-usd 40` cap sums per-call `cost_usd` (real-or-estimated, see E-D12) accumulated in-process and is enforced by a **pre-call `reserve()`/`settle()`** guard (the `webapp/budget.py` pattern), atomic under a lock — a call is only issued if the reservation fits under the remaining cap. Second tier = a concrete **call-count ceiling** `MAX_JUDGE_CALLS = 900` (worst case is 8×~99 ≈ 800; 900 leaves headroom, and at a conservative $0.05/call the count cap alone bounds spend ≈ $45). `--dry-run` computes the forecast and **aborts before the first paid call if forecast > cap**. | The inherited `term_pipeline.py --max-usd` polls the OpenRouter `_or_credits()` balance endpoint every N items — that endpoint does not exist for a generic provider and overshoots by up to N calls. A pre-call reservation on in-process cost is provider-agnostic and can't overshoot. |
| E-D12 | **Judge is provider-agnostic**: model/provider via `LLMClient` (base_url + key from config). Cost accounting: if the provider reports price, use it; else compute `cost_usd` from a **local price table** and tag `cost_source: estimated`. Any model **absent** from the table falls back to a deliberately **conservative (pessimistic) ceiling price** (mirroring `webapp/budget.py::_price`'s non-zero fallback) so the cap never underestimates; a zero/unset price is forbidden. The provider must always return token `usage` (prompt+completion+reasoning) so estimated cost is grounded in real token counts, not guessed lengths. | Owner plans a cheaper-than-OR provider. A conservative fallback means an unpriced/mispriced model can only *over*-estimate spend, never silently blow the cap. |
| E-D13 | **Surface comparison via G6 `norm()`** (casefold, ё→е, dashes); on surface mismatch, compare lemmas | Russian Wikipedia anchors are inflected ("Римской империи"); positional match + norm covers most, lemma the rest. One normalization source shared with G6. |
| E-D14 | **All runs persisted whole**: traces.jsonl, wikidata cache, judge cache, gt.jsonl, config, counters → `reports/terminology/wiki-eval/` (LFS) | Owner: expensive predictions never lost; every new metric is an offline recompute. |
| E-D15 | **E3 deferred**, one line as future work | Owner: nice addition, not directly part of evaluation. |
| E-D16 | **Predicted tuples come from a new eval-owned `predict.py`**, not from G6 unchanged. G6's extractor emits `{surface, lemma, category}` with **paragraph-local char offsets**; `predict.py` (a) feeds the article to the extractor paragraph-by-paragraph (native chunk unit), (b) tracks a running base offset so each mention maps to a **global** whole-article char position, (c) converts that char position to a whole-article **token index** using the exact E-D6 tokenizer, then (d) pairs it with the grounding `chosen_qid` to build predicted `(token index, surface, QID, span_len)` tuples. | The earlier "G6 consumed unmodified" claim was wrong: char-offset→global-token-index conversion and chunk-offset stitching are real (small) eval code and must be named, owned, and unit-tested. G6 grounding code itself is still untouched. |
| E-D17 | **Failure modes get distinct counters, never conflated.** GT side: `n_no_qid` (page exists, no wikibase_item) ≠ `n_redlink` (target page absent) ≠ `n_fetch_failed` (Parsoid/API network failure after retries) ≠ `n_malformed_html`. A network failure is transient (like G6 `wikidata_unavailable`); an absent QID is a permanent property of the data. `build-gt` **fails loud** if the fetch/parse failure rate exceeds 10 % rather than silently emitting a truncated GT. | Conflating transient network failure with permanent absence hides reproducibility risk and biases recall's denominator. |
| E-D18 | **Predicted QIDs are canonicalized through the same redirect path as GT QIDs** before matching; both GT and grounding draw from the same Wikidata snapshot/cache | Otherwise a genuinely-correct grounding can mismatch GT purely from redirect drift between snapshots. |

## 3. Architecture & data flow

Modules under `src/palimpsest/terminology/evaluation/`:

- `tokenize.py` — the single pinned E-D6 tokenizer: `flatten(html) -> str`, `tokens(text) -> list[str]`, `char_to_token_index(text, char_pos) -> int`. Shared by `wiki_gt` (GT side) and `predict` (prediction side) so both sides index identically.
- `wiki_gt.py` — article selection (strata + hardness), Parsoid-HTML fetch + cache, flat-text + GT-tuple extraction from anchors, batched title→QID mapping (own pageprops fetcher, E-D7), GT filters (E-D8), failure counters (E-D17).
- `predict.py` — **eval-owned bridge to G6 (E-D16):** paragraph-chunked extractor calls with global-offset stitching → char→token-index conversion → pair with grounding `chosen_qid` → predicted tuples; carries the G6 trace through for slicing.
- `matching.py` — set comparison of GT vs prediction tuples in the three modes (M1/M2/M3); pure functions, no I/O.
- `metrics.py` — recall / 3×precision / slices / Wilson CI aggregation → `metrics.json`.
- `report.py` — dark-theme HTML report (this palette) + EN paper-draft section emitter.

Thin CLI wrapper `scripts/wiki_eval.py`, subcommands (each independently re-runnable):

| Subcommand | Input | Output | Notes |
|---|---|---|---|
| `build-gt` | pool spec, cached HTML (or network first time) | `data/eval/wiki/gt.jsonl` + cached `pages/*.html` | free; deterministic from cache |
| `run --config <id>` | gt.jsonl, one grounding config | `reports/…/<config>/<run_id>/traces.jsonl` | the only paid stage (extractor + judge) |
| `ablate` | gt.jsonl, all 8 configs | 8 × `run` outputs under one run_id | **loops over `run`**, no duplicated logic; shares the judge cache across configs |
| `report [--config <id>\|--ablation]` | one or many trace dirs + gt.jsonl | `metrics.json` + `report.html` | pure offline recompute; no LLM |

Metrics recompute offline from persisted traces + GT (no LLM). Only `run`/`ablate` spend money and are gated by E-D11.

Data layout:
- `data/eval/wiki/pages/<title>.html` — cached Parsoid HTML (LFS).
- `data/eval/wiki/gt.jsonl` — one record per article: `{title, qid, stratum, hardness, tokens[], gt_tuples[], counters{n_excluded_chrono, n_no_qid, n_anchors}}`.
- `reports/terminology/wiki-eval/<config>/<run_id ISO-timestamp>/` — traces.jsonl, metrics.json, report.html, resolved config, caches (LFS; rule already added by the G6 spec).

The G6 grounding code is **not modified** — this eval writes no code inside `grounding/`. But it is not consumed "for free" either: `predict.py` is a real bridge (E-D16) that stitches paragraph-chunked extractor offsets into a global token stream and pairs mentions with grounding QIDs. The G6 contracts it depends on: extractor `{surface, lemma, category}` + char offsets, `label_first` grounding `chosen_qid`, GroundingTrace v1 (for `resolved_by` slicing).

### 3.1 Error policy (mirrors G6 §3.2)

| Failure | `build-gt` handling |
|---|---|
| Parsoid/REST fetch fails after retries | article excluded, `n_fetch_failed++`, logged — never silently dropped |
| title→QID batch call fails | treated as transient (like G6 `wikidata_unavailable`), counted separately, **not** folded into `n_no_qid` |
| target page absent (red link) | `n_redlink++` |
| page exists, no `wikibase_item` | `n_no_qid++` |
| malformed/empty Parsoid HTML (no body, no anchors) | article excluded, `n_malformed_html++` |
| **aggregate fetch/parse failure rate > 10 %** | `build-gt` **fails loud** — no truncated GT |

On the `run` side, the eval inherits G6's grounding error policy verbatim: rows with `resolved_by ∈ {wikidata_unavailable, judge_unavailable}` are **excluded from all metrics** and surfaced as separate counters in `metrics.json` (never counted as recall misses — a system that couldn't reach Wikidata didn't "miss" the term).

## 4. Metrics — every counting variant and why

### Matching modes (a tuple counts as matched if…)

| Mode | Rule | Measures / why |
|---|---|---|
| **M1 strict** | index equal + `norm(word)` equal + QID equal | Literal reading of the owner's set-of-tuples. Brittle to multi-word anchor boundaries → reported as a lower bound. |
| **M2 span-overlap** *(primary)* | token spans overlap + QID equal | Honest middle: "we found this entity here". Insensitive to boundary disputes ("Римской империи" vs "империи"). |
| **M3 document** | `(lemma, QID)` equal anywhere in the article | "Concept found and grounded correctly, even in a different mention". The **M2↔M3 gap = price of the first-mention convention + our "one sense per discourse" cache**. |

### Recall *(primary)*

R = |GT ∩ pred| / |GT|, in each of the three modes. Denominator = all GT tuples after the E-D8 filters. Human annotation is incomplete but **precise**, so a miss is worse than a spurious mark.

Two things kept distinct (a verify-spec finding conflated them): (1) **GT size** is not inflated by repeat mentions — by construction Wikipedia links only first mentions, so each linked entity contributes one GT tuple. (2) Whether a system's grounding of a *non-first* mention of the same entity counts as a recall hit is answered **per mode**, not "by construction": M1/M2 require the prediction to sit at the GT anchor's position (a far-away correct grounding is a recall *miss*); M3 credits it document-wide. The **M2↔M3 gap is exactly the price of the first-mention convention crossed with G6's "one sense per discourse" cache** (E-D9) — the inherited G6 open question, now a measured quantity.

**Precision caveat (paper-facing).** Precision here is a *lower bound with unknown bias*: the reference is Wikipedia's "don't over-link" editorial convention, not exhaustive annotation. P2/P3 partially correct for this but not fully; absolute precision numbers are not comparable across systems evaluated on differently-linked corpora.

### Precision — 3 variants

| Variant | Rule | Why |
|---|---|---|
| **P1 base** | \|pred ∩ GT\| / \|pred\| | Classic; deliberately pessimistic (humans don't link everything). |
| **P2 unique-word** | pred deduplicated by `(lemma, QID)` before counting | Compensates for Wikipedia's "repeat mentions unlinked" convention: our repeats are not penalized. |
| **P3 label-justified** | a prediction outside GT counts as "justified" if the word exists in Wikidata as a label | Upper bound: the term is linkable, the human just didn't. **Circularity guard (mandatory):** on the `exact_label` resolution path P3 is *tautological* — that path found the QID precisely because the surface matches a Wikidata label, so it satisfies P3 by construction. Therefore **P3 is never reported as an unsliced aggregate**; it is reported **only sliced by `resolved_by`**, and the headline paper number is P3 on the **non-`exact_label` paths** (LLM-disambiguated + fallback), where it is a genuine signal. |

### Slices (each metric additionally)

- **By stratum** hard / typical / all — the paper's main table.
- **By resolution path** (`resolved_by` from the G6 trace): exact_label vs llm_disambiguation vs rest — does precision degrade on the judge path (direct continuation of G6 transparency).
- **By type**: named entities vs lowercase terms — both classes required by the methodology. *Caveat:* GT side is classified by anchor capitalization, ours by extractor `category` — two different criteria on the same axis. Before using this slice as a headline number the harness cross-tabs the two criteria once and reports their agreement rate; if agreement is low the slice is labelled "measures classifier disagreement too" rather than presented as clean named-vs-term performance.
- **Ablation**: 8 configs × (R@M2, P1@M2, P2@M2), two ladders. Reported as *marginal* contribution per toggle (leave-one-in / leave-one-out), explicitly **not** causal isolation — toggles can interact (e.g. `match_aliases` × `use_fallbacks`), and shared-cache reuse across legs is correlational.
- **Per-cell CI, not a fixed threshold (supersedes the copied G6 "≥3-tuple" rule).** G6's ≥3-tuple noise rule was calibrated for ~78 terms; wiki-eval slices (stratum × resolution-path × type × config) can each be small even though the corpus total is ~10–30k. So: every reported cell carries **raw n + Wilson 95% CI computed on that cell's own n**; any cell with **n < 30** is **greyed-out / flagged "underpowered"** in the report and never interpreted as a difference. The central hard-vs-typical comparison must show its per-stratum n so a thin slice can't masquerade as signal.

## 5. Cost & time (pre-dry-run estimate)

| Component | Volume | Estimate |
|---|---|---|
| Scrape 100 articles + title→QID | ~100 pages + ~200 batch calls | minutes, $0 |
| Extractor (NER) on 100 full articles | ~1.5–5M input tokens | $1–3 (cheap G6 model) |
| Wikidata grounding, base config | ~5–10k unique queries after cache | 1–3 h polite API, $0 |
| Judge escalations, base config | ~20–40% of groundable | $5–15 |
| **Full 8-config ablation** | cache reuse depends on candidate-set overlap across configs (measured, not assumed) | **optimistic ×2–3 ≈ $15–35; worst case ×8 ≈ $40–120** |

**Judge call parameters (pinned):** `max_tokens = 512`, reasoning budget bounded by that same 512 (reasoning billed as output — the G6 risk, carried and capped here); **0 caller-level retries** — a transient failure marks the term `judge_unavailable` and is counted separately, never retried in a loop (no unaccounted spend); malformed JSON is terminal (G6 policy).

**Cap reconciliation (a verify-spec finding):** the earlier "$15–45 → cap $40" let the top of the range exceed the cap. Corrected stance: the ×2–3 estimate is *optimistic* and assumes high judge-cache reuse across ablation legs — but leave-one-out toggles that change candidate sets produce different `candidates_qids`, so those judge calls are cache **misses**. Therefore: (1) `--dry-run` **measures the actual cross-config cache-hit rate on a 5-article pilot** and extrapolates, rather than assuming ×2–3; (2) if the forecast exceeds `--max-usd`, the run **aborts before the first paid call**; (3) the live `reserve()` guard (E-D11) plus `MAX_JUDGE_CALLS = 900` bound spend even if the forecast is wrong. The $40 default cap is a floor the owner can raise; the guard, not the estimate, is what actually bounds cost.

## 6. Risks

| # | Risk | Mitigation |
|---|---|---|
| E-R1 | Extractor was designed for book paragraphs; a Wikipedia article is 10–30× longer — chunking may drop lemma/category recall, and per-chunk offsets must be stitched into a global index | `predict.py` (E-D16) chunks by paragraph (the extractor's native unit) and stitches global offsets with a dedicated unit test; out-of-domain lemma drift is the 2nd G6-inherited question, and this eval itself measures it (M2↔M3 gap + manual error sample). |
| E-R2 | GT noise: piped anchors with non-obvious targets, curiosity links, vandalism | Manual audit of a 50-tuple GT sample before the run; filter counters in metrics.json. |
| E-R3 | Pages without a QID (red links, fresh articles) | Dropped from GT with `n_no_qid`, mirroring G6 `wikidata_unavailable`. |
| E-R4 | Wikidata/Wikipedia drift between runs | HTML + wikidata cache in LFS pin a snapshot; report states the snapshot date. |
| E-R5 | Judge provider specifics (structured output, effort) on a non-OR provider | Project rule: capabilities per live provider catalog, not per model family; pre-flight in the harness. |

## 7. EN paper-draft section (draft — methodology for the article)

> **Evaluation against Wikipedia link annotations.** We evaluate the terminology extraction-and-grounding component against human hyperlink annotations on 100 full Russian Wikipedia history articles, stratified into 50 *hard* pages (top-ranked by a deterministic anchor-ambiguity score that measures intrinsic lexical polysemy, not system difficulty) and 50 *typical* pages sampled uniformly from the same history-category pool. Each internal link whose target carries a Wikidata item yields a gold tuple *(token index, surface, QID)*; chronology targets (years, centuries) are excluded by target *P31*. We compare gold and predicted tuple sets under three matching modes — strict index, span overlap (primary), and document-level *(lemma, QID)* — normalizing surfaces with a shared casefold/ё-е/dash normalizer; the strict mode is a deliberate lower bound sensitive to multi-word anchor boundaries. Because human annotation is precise but incomplete, we treat **recall** as the primary metric; precision, measured against Wikipedia's non-exhaustive "don't over-link" convention, is a conservative lower bound and is reported under three complementary denominators: raw, unique-word (to offset the convention of not linking repeat mentions), and label-justified (a prediction absent from gold is credited when its surface exists as a Wikidata label — reported only per resolution path, since on the deterministic exact-label path it holds by construction). Reporting is sliced by stratum, by the system's own resolution path (exact-label vs. LLM-disambiguated), and by entity type (named vs. lowercase term), each with per-cell Wilson 95 % confidence intervals; underpowered cells are flagged and differences within the interval are not interpreted. A full ablation over the three retrieval/matching toggles (lemma expansion, search fallbacks, alias matching) estimates each component's marginal contribution via leave-one-in / leave-one-out. This gives a transparent, reproducible measurement of a deterministic-first grounding system without recourse to a black-box entity linker as the reference.

*(This paragraph is the paper-ready formulation; keep it verbatim in the eval stage doc per the project's "preserve chat formulations" rule.)*

## 8. Dependencies & order

This spec **executes after G6** (needs extractor + `label_first` grounding + trace v1). Within the block, `build-gt` has no G6 dependency — the dataset can be built first (it is free). E3 deferred. Pipeline: spec → /verify-spec → gate → (later, on command) writing-plans → implementation. Implementation branch `feat/wiki-eval` off `feat/grounding-label-first` (so it carries the G6 code it consumes).

## 9. Tests

- `tokenize`: flatten+split on a fixture with **NBSP / multiple Unicode spaces / attached punctuation** → exact expected token list; `char_to_token_index` round-trips a known offset.
- `predict` (E-D16): multi-paragraph fixture where a mention sits in the 3rd paragraph → asserts the **global** token index is right (offset-stitching), not the paragraph-local one; mention with lemma ≠ surface pairs to the right grounding QID.
- `wiki_gt`: anchor extraction from a fixed HTML fixture → expected tuples; redirect **chain** canonicalization (anchor → redirect → QID, incl. double redirect); chronology filter by the §11 P31 set; hardness score on a crafted page; failure counters (E-D17) on fixtures for red-link / no-QID / malformed-HTML.
- `matching`: M1/M2/M3 on hand-built GT/pred sets incl. multi-word overlap (`span_len`) and inflected surfaces (norm + lemma paths); explicit case showing M2 does no surface comparison, only span+QID.
- `metrics`: recall/precision arithmetic + Wilson CI against known closed-form values; slice partitioning sums back to totals; **underpowered-cell (n<30) flagging**; P3 refuses to emit an unsliced aggregate.
- Determinism: `build-gt` twice from cache → byte-identical gt.jsonl — guarded by the invariant that no `set` iteration order reaches serialized output (sort before dump), and a **named HTML parser** (fixed constant) is used. Same invariant documented as in G6 §3.1.
- All offline, no network (fixtures + cached HTML).

## 10. Definition of done

- Modules + CLI implemented; unit tests green.
- `build-gt` produces gt.jsonl for 100 articles from cache; determinism test passes.
- `report` computes all metrics/slices/CI offline from a persisted trace fixture.
- Docs: eval stage doc + docs/pipeline.md entry + `docs/testing/` note; EN draft §7 preserved verbatim in the stage doc.
- `--dry-run` forecast implemented and shown before any paid path; `--max-usd` enforced.
- Paid ablation run is optional and gated: executed only if a key + budget are available; otherwise the harness is proven on the golden/fixture path and the paid run is documented as ready-to-launch.

## 11. Fixed constants (versioned)

- **HTML parser:** `lxml` via BeautifulSoup (`BeautifulSoup(html, "lxml")`) — one named parser so anchor-traversal order is stable.
- **Tokenizer:** `re.split(r"\s+", nfc_nbsp_normalized_text)`, empty tokens dropped, punctuation attached. NFC + NBSP→space normalization applied first.
- **Chronology P31 exclusion set (v1, `chrono_p31_v1`)** — closed set, hash stored in `gt.jsonl` metadata: `Q3186692` (calendar year), `Q39911` (decade), `Q578` (century), `Q3311614` (millennium), `Q29964144` (year BC), `Q14795564` (point in time / date), `Q18340514` (events in a specific year or time period). Extending the set = a new version id (`chrono_p31_v2`), never an in-place edit.
- **Underpowered-cell threshold:** n < 30 → flagged, not interpreted.
- **`MAX_JUDGE_CALLS = 900`; default `--max-usd = 40`; judge `max_tokens = 512`, 0 caller retries.**

## 12. Deferred (future work)

- **E3 — disambiguation-trap benchmark:** ~100 crafted sentences around known polysemous surfaces (Цин / Roman / Seal / May), LLM-generated + owner-annotated, measuring the judge (`llm_disambiguation`) path in isolation. Not built here; recorded so the idea isn't lost (owner decision E-D15).
