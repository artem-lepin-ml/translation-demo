# Terminology end-to-end module — design spec (merged grounding + pairing)

Up-link: [docs/stages/terminology.md](../../stages/terminology.md). Contract: [2026-06-30-demo-contracts.md](2026-06-30-demo-contracts.md) §1 (`Term`, `WikidataRef`). Merges the two goal-cycles [grounding](../../goals/2026-07-01-grounding-overnight.md) + [pairing](../../goals/2026-07-01-pairing-overnight.md) into ONE end-to-end module, executed autonomously on branch `feat/terminology`.

> **LEGACY (2026-07-03):** superseded by G6 label_first — see [2026-07-03-grounding-label-first-design.md](2026-07-03-grounding-label-first-design.md). Pairing sections remain in force.

## 1. Goal

One module that turns a `(RU source, EN translation)` paragraph into the full `Term[]` the demo needs — filling **both** signals of the `Term` contract:
`extract` (RU term mentions) → `ground` (difficulty 🟢🟡🔴 + Wikidata QID) → `pair` (targetSurface + pairAccuracy 🟢🟡🔴 + recommended) → assemble `Term[]`. It runs on the 16 seed paragraphs, writes real terms into the `term` table, and is visible in the demo UI — a complete artifact to show a director.

## 2. Environment reality (this session) — locked

| Fact | Consequence |
|---|---|
| Live Wikidata/Wikipedia API reachable (verified: Q11767 Mesopotamia) | API-first strategies run for real, here and now. |
| **No CUDA** (`torch.cuda=False`, macOS) | GPU strategies (mGENRE grounding, neural word-alignment pairing) are **code-only**: implemented behind the interface, guarded to `raise RuntimeError` when no GPU, and **not run** in this session. Documented, not hidden. |
| All LLM calls go through **subagents** (Haiku/Sonnet), never a paid external API; `src/` imports no `openai`/`LLMClient` | The Python module is pure and deterministic; LLM strategies receive an injected `judge` the orchestrator backs with a subagent. |
| Demo default path must be pure-Python + API (no LLM at demo time) | **G1(api_first) + P1(link_locate)** are the demo pipeline — deterministic, reproducible; extraction is done once and persisted. |

## 3. Module layout — `src/palimpsest/terminology/`

```
terminology/
  base.py          # TermMention, WikidataRef, GroundingResult, PairResult, Term; Protocols
  wikidata.py      # live API client (urllib, UA+maxlag+Retry-After), local JSONL cache
  verdict.py       # difficulty + pairAccuracy verdict logic; type filter (P31/P279)
  extract.py       # RU term mentions (persisted seed via subagent; deterministic fallback)
  grounding/
    api_first.py   # G1 (default, runnable)
    llm_judge.py   # G3 (injected judge → subagent; runnable via orchestrator)
    mgenre.py      # G2 (code-only; GPU-guarded)
  pairing/
    link_locate.py # P1 (default, runnable)
    llm_judge.py   # P3 (injected judge → subagent; runnable)
    neural_align.py# P2 (code-only; GPU-guarded)
  pipeline.py      # end-to-end: (source, target, mentions) → Term[]
  eval_harness.py  # metrics vs golden
scripts/term_pipeline.py   # CLI: run pipeline over seed → term_pairs.json + DB seeder hook
```

Interfaces (frozen before strategies):
- `GroundingStrategy.ground(TermMention, *, judge=None) -> GroundingResult`
- `PairingStrategy.pair(PairRequest, *, judge=None) -> list[PairResult]`
- `pipeline.run(source, target, mentions, *, grounder, pairer) -> list[Term]`

`Term` output matches the DDL columns exactly: `source_surface, source_lemma, context, char_start, char_end, difficulty, grounded(json), candidates(json), target_surface, pair_accuracy, recommended, note`. Null rule: `difficulty='red' ⇒ grounded=None, candidates=[], pair_accuracy=None, recommended=None`.

## 4. Strategies + verdict rules

**Grounding** (difficulty): G1 `wbsearchentities(lang=ru)` → `wbgetentities` enrich → P31/P279 type filter (drop Q4167410 disambiguation, Q13442814 scholarly-article) → Wikipedia langlinks fallback → verdict. Verdict: 🟢 = 1 confident typed candidate; 🟡 = ≥2 plausible (homonyms) or 1 weak; 🔴 = 0 after filter (grounded/candidates/pair all null).

**Pairing** (pairAccuracy): P1 canonical EN from QID (`labels.en` + `aliases.en` + enwiki sitelink) → locate in EN translation (exact → token Jaro-Winkler ≥0.9) → verdict. 🟢 = canonical form found; 🟡 = variant/transliteration 0.7–0.9; 🔴 = not found / wrong (<0.7) + `recommended` = canonical EN. Skipped (pairAccuracy=null) when difficulty=red.

G3/P3 = same shape, but candidate selection / adaptation judgment delegated to an injected `judge` (subagent, temperature 0, structured output). Tournament compares G1↔G3 and P1↔P3 on the golden set.

## 5. Golden set + metrics

Golden `data/seed/terminology_gold.jsonl` (~40+ terms hand-built from the 16 seed paragraphs, real QIDs cross-checked against Wikipedia/VIAF/Britannica/Pleiades, non-circular): `{surface, context, gold_qid, gold_difficulty, gold_target_surface, gold_pair_accuracy, gold_recommended, category}`.

Metrics (`reports/terminology/metrics.json`): grounding accuracy vs golden; difficulty confusion-matrix + macro-F1; pairAccuracy confusion + macro-F1; recommended correctness; coverage; latency p50/p95 + API-calls/term; per-category; tournament pairwise (G1↔G3, P1↔P3). Comparison vs `feat/glossary-overnight` glossary in `reports/terminology/vs_glossary.json`.

## 6. Acceptance (demoable state)

- Module imports; `pipeline.run` returns contract-valid `Term[]`.
- Pipeline runs on all 16 seed paragraphs → real QIDs, both signals, written to the `term` table.
- Webapp serves them; **browser e2e** shows 🟢🟡🔴 on RU terms + Wikidata links + pairAccuracy in `TermPopover`/Glossary; ≥6 screenshots.
- Golden ≥40; metrics.json complete; ≥1 independent adversarial audit = PASS (metrics recomputed, code, edge cases, docs).
- Docs (stage + pipeline + known_issues) synced; dark-theme HTML report served locally.
- Single `feat/terminology` commit, PR-ready, **not pushed**.

## 7. Edge cases (must handle)

Homonyms → yellow; entity absent from Wikidata → red without crash; QID redirects; somevalue/novalue; empty/noisy context; non-ASCII/diacritics; term dropped from translation → red + recommended; multiple occurrences → per-occurrence rows; transliteration vs translation → yellow; multi-word terms; difficulty=red forces pairAccuracy=null.

## 8. Model routing

Opus: this spec, decisions, golden-set, data inspection, aggregation, report, prune. Sonnet: strategy code, tests, docs. Haiku: extraction, recon. Independent audit: Sonnet, fresh context, ≠ author.

## 9. Rework after `/verify-spec` (2026-07-01, gate was REWORK: 2 CRITICAL + 12 HIGH)

Applied decisions (findings → resolution):

- **Extraction is a first-class stage, not orphan scope.** `extract.py` interface: `mentions_from_surfaces(source, surfaces) -> list[TermMention]` (one mention **per occurrence**, char spans) + `deterministic_extract(source)` (stdlib fallback: capitalised proper-noun runs). Default **E1** = LLM subagent, **proper nouns only** (PERSON/LOC/ORG + capitalised/hyphenated runs), high-precision; domain terms (лугаль/cuneiform) and common-noun terms are bonus/future work. Fallback **E0** = deterministic. Acceptance: extraction **P/R/F1** vs the golden term list; extraction is inside the audit scope.
- **Tournament honesty (CRITICAL).** Only **2 pairs actually run** here: G1↔G3 (grounding) and P1↔P3 (pairing). **G2 (mGENRE) and P2 (neural-align) are code-only and do NOT run in this no-CUDA session** — stated in metrics.json, the report, and to the director. No "6-pair tournament" claim.
- **Golden non-circular (CRITICAL).** The golden set is built from domain knowledge + independent corroboration (Wikipedia/VIAF/Britannica/Pleiades), **not** from any running strategy's output. Construction is disclosed in the report; G1 output is not a reference for the golden labels.
- **Metrics redefined (was conflated).** Grounding: QID accuracy + **macro-F1 over {green,yellow,red}**; report **groundable-coverage** (% difficulty∈{green,yellow}) and **red-accuracy** (% correctly red) as *separate* signals — never a single "coverage". Pairing: **verdict-F1 over {green,yellow,red} on difficulty≠red terms only** + **null-accuracy** for red terms reported separately; **recommended-form accuracy** scored only where the verdict is correct. Class distribution printed. Latency: p50/p95 split cache-hit vs cache-miss + 429/Retry-After counts.
- **Explicit selection rule.** Winner = higher golden accuracy; tie-break → higher macro-F1 → fewer API calls → lower latency. The applied numbers go in metrics.json.
- **UI already exists — no new UI.** The webapp renders the `term` table via `_term_dict` (snake DB → **camelCase** wire) into `TermPopover` + `GlossaryTab`. Data flow: `pipeline.Term[] → term-table seeder → GET /documents → React`. No new component; the demo is the existing Variant A.
- **Contract fields.** `id` (autoincrement) and `paragraphId` (FK) are **structural**, supplied by the DB; the module fills the 12 domain fields. `candidates_json` is always `'[]'` (never NULL), enforced by `pipeline.run` + `Term.db_tuple`.
- **Null rule owned by `pipeline.run`** (guard after grounding; red ⇒ grounded/candidates/pairAccuracy/recommended null) + unit test. Per-occurrence: identical surfaces produce independent Term rows (grounding by surface is deterministic; context-embedding disambiguation is **descoped** for the demo — difficulty uses the candidate exact-match-count heuristic, documented in known_issues).
- **Cache versioned.** Records carry a `schema_version`; `--cache-clear` supported; a cold-cache reproducibility run is part of acceptance.
- **Falsifiable acceptance.** Audit PASS = metrics recomputed match ±0, no `openai` import in `src/`, edge-case checklist (§7) all handled, docs match code. Docs "synced" = stage doc lists all strategies, pipeline.md has the end-to-end flow, known_issues.md has ≥5 §7 edge cases. HTML report served at a pinned localhost URL with ≥4 sections.
- **Down-ranked (not a defect):** "single commit" — multi-commit during dev on `feat/terminology` is fine; squashing at PR time optional.
