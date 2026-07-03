# Terminology consolidation — design & decisions

Up-link: [docs/README.md](../../README.md). Supersedes nothing; consolidates three parallel implementations into one best-of-breed terminology module on branch `feat/terminology-consolidated` (forked from `feat/terminology`).

## Goal

Merge the strongest parts of three independent implementations of the terminology `Term` module (difficulty + pairAccuracy over live Wikidata) into one module, keeping the unified end-to-end architecture and folding in the overnight cycles' better strategies, edge cases, and golden data. No GPU work (G2/P2 stay documented stubs). Delete nothing: all source branches stay intact.

## The three inputs

| Branch | Scope | Winner it found | Golden | Key strengths | Key defects |
|---|---|---|---|---|---|
| `feat/terminology` (mine) | end-to-end (extract→ground→pair→`Term[]`) | G3 grounding / P1 pairing | 38 (no hard pairs) | unified base/verdict/wikidata + pipeline; **anachronism blocklist**; **head-token guard**; notability difficulty; live demo | latent `notable`-key never built on G3 candidates; pairing golden all-green (metrics trivial) |
| `feat/term-grounding` | grounding only | **hybrid (G5)** — qid 0.87, 0 regressions | 65 (hand, `source_url`) | hybrid pattern; api_first recall boosters (CirrusSearch + wiki→qid); per-strategy audits | duplicated infra; QID redirect not canonicalised; dead category filter; G4 unratified deviation; no anachronism list |
| `feat/term-pairing` | pairing only | **llm_judge (P3)** — F1 0.76 vs 0.60 | **74 (57🟢/10🟡/3🔴/4∅)** | rich hard-case golden; `extract.py` dual-path + IoU P/R/F1; positional aligner; `similarity.py` (vendored jaro-winkler) | duplicated infra; **herms/Hermes** morph-key false-positive (no head guard); `neural_align` orphaned |

### Honest revision of my earlier conclusion
My chat demo claimed "G3 grounding + P1 pairing win." That is **golden-dependent and partly an artifact**:
- **Grounding:** pure-LLM over-greens homonyms when difficulty is computed from scores (term-grounding measured llm_judge verdict-F1 = 0.47). The robust winner is **hybrid** (api_first difficulty + judge-picked QID). My G3 scored well (0.86 diff-F1) only because *my* judge rates difficulty directly — a different mechanism. Both must be re-measured on one golden.
- **Pairing:** my golden had **zero yellow/red/null** pairing rows, so P1's 0.96 F1 was trivial. On term-pairing's hard golden, **P3 (LLM-judge) wins 0.76 vs 0.60**. The consolidated demo should reflect that (P3, or a P1→P3 escalation).

## Decisions

### D1 — Architecture: keep the unified skeleton
One `base.py` (frozen `Term` contract + protocols), one `verdict.py`, one `wikidata.py`, one `eval_harness.py`, one `extract.py`, one `pipeline.py`; `grounding/` and `pairing/` hold only strategies. The two overnight cycles' duplicated `base/verdict/wikidata` are **not** carried forward.

### D2 — Contract: call-time judge injection
Standard is `ground(mention, *, judge=None) -> GroundingResult` and `pair(req, *, judge=None) -> PairResult` (mine). The overnight cycles used constructor injection; folded-in strategies are adapted to the call-time kwarg. `Judge = Callable[[str], dict]`. `src/` never imports an LLM client.

Note: term-pairing returned `list[PairResult]` (per-occurrence). We keep per-occurrence at the **extraction** level (one `TermMention` per occurrence) and one `PairResult` per mention, so the single-result contract is preserved.

### D3 — Grounding: fold in hybrid (G5) as the default strategy
New `grounding/hybrid.py` under the call-time contract:
1. Run api_first → difficulty + candidates (deterministic, notability-based).
2. If not red, run llm_judge → grounded QID **and** difficulty; take the judge's QID when it resolved one, else fall back to api_first's pick; take the judge's difficulty when present, else api_first's.
3. Red short-circuits before any judge call (cost + correctness).
This combines term-grounding's robustness (api_first difficulty floor, no wasted judge calls on red) with my judge-rated-difficulty strength.

### D4 — Grounding: recall boosters + fixes
- api_first gains a **CirrusSearch fallback** (`wbsearchentities` is prefix-only) and a **Wikipedia RU-title → QID** generator when the primary search is thin, to cut the ~30% red rate.
- **Redirect canonicalisation**: build `WikidataRef` from the enriched `entity["id"]`, not the pre-redirect search-hit QID.
- **`notable` key** is built on every grounding candidate (enwiki sitelink present), so the deterministic notability→yellow branch actually fires. Fixes my latent bug.

### D5 — Pairing: keep my verdict, adopt the richer golden, re-pick the winner
- Keep `verdict.pair_from_forms` with the **head-token guard** (rejects "town of Akkad" vs "Sargon of Akkad"); this is strictly better than term-pairing's guard-less `morph_key` which produces the herms/Hermes false positive.
- Adopt term-pairing's **74-row golden** (merged with mine) so yellow/red/null are measured.
- Re-measure P1 vs P3; wire the demo to the empirical winner (expected P3, with a documented P1→P3 escalation to bound LLM cost at ~6.7s/term).

### D6 — Extraction: fold in the dual-path extractor + precision metric
Port term-pairing's `extract.py` care (judge+heuristic, sentence-initial-capital drop, span reconciliation) and `eval_harness` IoU≥0.5 P/R/F1 so extraction **precision** is finally measured (was an open gap: only recall 0.97 known).

### D7 — Golden: one unified non-circular set
Merge the three hand-built goldens (all over the same 16-paragraph pilot, same `paragraph_id` scheme, same EN translation — verified) into `data/seed/terminology_gold.jsonl`, keyed by `(paragraph_id, source_surface, char_start)` / `(surface, gold_qid)`, preferring the richest annotation and carrying `source_url` provenance. Non-circular by construction (hand-authored, third-source verified; never a strategy's output).

### D8 — Remove excess (YAGNI / "убрать лишнее")
- Drop the dead category-filter path (`expected`-parameter type narrowing that always ran with `expected=None` and burst into HTTP 429).
- Drop `refined_baseline` (G4): naive top-1, an unratified deviation from the locked spec, no analytic value beyond a floor already covered by api_first's own red rate.
- Keep `mgenre` (G2) and `neural_align` (P2) as **honest documented stubs** — GPU, out of scope, never run.
- Factor the duplicated `_exact_match` helper into one shared place.

## Success criteria
1. Unified module runs end-to-end on the pilot corpus against live Wikidata (or warm cache), CPU only.
2. One `metrics.json` with **comparable** numbers for G1/G3/hybrid grounding and P1/P3 pairing on the **same** unified golden, plus extraction P/R/F1.
3. Red rate on the demo corpus measurably lower than the previous ~30% (recall boosters), or the residual reds shown to be genuinely ungroundable.
4. Tests green (existing 17 + new coverage for hybrid, recall boosters, extractor, redirect/notable fixes).
5. Browser e2e of the consolidated demo + independent audit PASS.
6. Docs at parity in the same commits (stage doc, pipeline.md, known_issues); no dead code carried forward.

## Out of scope
GPU strategies (G2 mgenre, P2 neural_align) — code stays as documented stubs, not run. Pushing/merging to remote (owner does git). Touching the source branches (`feat/terminology`, `feat/term-grounding`, `feat/term-pairing`, `feat/glossary-overnight`) — all preserved.
