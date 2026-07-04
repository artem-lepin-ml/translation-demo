# G6 `label_first` Grounding — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `.claude/skills/superpowers/subagent-driven-development/SKILL.md` (recommended) or executing-plans (not vendored) to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace all grounding strategies (G1/G2/G3/G5) with a single deterministic-first strategy G6 `label_first`: exact-label match resolves without a model call; LLM judge escalates only genuine ambiguity; every decision is traced (`GroundingTrace v1`) and ablatable via three independent toggles.

**Architecture:** Deterministic candidate generation (unchanged Wikidata search ladder, parameterized by `GroundingConfig`) → exact-label match against `norm()`-folded label/alias set → judge escalation only on ambiguous/inexact/empty-but-present cases → full per-decision trace written to `term.trace_json` (demo) and `traces.jsonl` (eval). Settings gets a new `grounding_config` single-row table + `GET/PUT /api/grounding-config` + a Grounding card mirroring the Evaluator card pattern.

**Tech Stack:** Python (stdlib + existing `WikidataClient`), FastAPI/SQLite webapp, pytest, existing `LLMClient` injection pattern (no direct `openai` imports in `terminology/`).

## Up-link

Spec (contract): [2026-07-03-grounding-label-first-design.md](../specs/2026-07-03-grounding-label-first-design.md) · Mockup: [2026-07-03-glossary-redesign-mockup.html](../specs/2026-07-03-glossary-redesign-mockup.html) · DDL/contract SSOT: [2026-06-30-demo-contracts.md](../specs/2026-06-30-demo-contracts.md) · Stage doc: [docs/stages/terminology.md](../../stages/terminology.md).

**Baseline:** test suite was 298 passed on `feat/grounding-label-first`. Verify live before Task 1 and after every task — treat 298 as the reference floor, not a hardcoded assertion.

**Branch/worktree:** all work happens in `/Users/a1111/Projects/Work/worktrees/grounding-label-first` (branch `feat/grounding-label-first`). One commit per task, Conventional Commits, English, imperative subject. **No `Co-Authored-By` trailer** (repo convention).

**Test command in this worktree:** `PYTHONPATH=src /Users/a1111/Projects/Work/worktrees/grounding-label-first/.venv/bin/python -m pytest tests/ -q` (dedicated venv — editable install points at THIS worktree, not term-consolidated).

---

## Ordering hazards (read before dispatching)

| # | Hazard | Mitigation |
|---|---|---|
| H1 | `grounding/candidates.py` is imported by **both** legacy G1/G3/G5 AND the new G6 candidate generator | Task 2 removes `api_first.py`, `llm_judge.py`, `hybrid.py`, `mgenre.py` + their `__init__.py` exports; it does **not** touch `candidates.py` (rewritten in Task 3, not removed). |
| H2 | `merge_goldens.py` reads `data/seed/lemmas.json` directly, kept (D4 golden-tooling exception) | Removal sweeps grep every `lemmas.json`/`LEMMAS` ref and explicitly exclude `scripts/merge_goldens.py`; the file `data/seed/lemmas.json` is **not deleted**. |
| H3 | `demo-contracts.md` is the **SSOT for DDL** (CLAUDE.md routing) | Task 1 touches `db.py` DDL AND `demo-contracts.md` (DDL + null-rule amendment) in one commit. |
| H4 | `scripts/rebuild_demo_g3.py`, `scripts/emit_judge_inputs.py` are legacy G3-only, dead after removal | Task 2 deletes both (verify no other importers first). |
| H5 | `docs/pipeline.md` (spec up-link target) **does not exist** in the repo | Task 11 **creates** it (spec §7 "rewrite" = create here). |
| H6 | `reports/terminology/**/*.jsonl` not covered by any `.gitattributes` LFS rule | Task 10 adds the LFS rule in the **same commit** that first writes `traces.jsonl`. |

---

## Task sequence (dependency-ordered)

| Task | Depends on | Summary |
|---|---|---|
| 1 | — | Schema: `term.trace_json` + `grounding_config` table + demo-contracts.md amendment |
| 2 | 1 | Archive tag `archive/grounding-g-strategies` + legacy G1/G3/G5/G2 removal sweep |
| 3 | 2 | `candidates.py` rewrite: `GroundingConfig`-parameterized, `queries[]` tracking, no type filter |
| 4 | 3 | `norm()` + exact-label match core (`grounding/match.py`) |
| 5 | 3,4 | `grounding/label_first.py` — G6 strategy, decision table, error policy, trace v1 |
| 6 | 5 | `base.py`/`verdict.py`/`wikidata.py` cleanup per spec file-fate table |
| 7 | 1 | Settings backend: `grounding_config` GET/PUT + judge wiring |
| 7b | 5,7 | **Judge-decision cache** ("one sense per discourse") — see Addendum |
| 8 | 7 | Settings frontend: Grounding card (mirrors Evaluator card); parallel-safe with 9 |
| 9 | 5 | Extractor: `{surface, lemma, category}` schema + prompt update |
| 10 | 5,9 | Eval/ablation harness `scripts/eval_grounding.py`, 8 configs, `metrics.json` v1, Wilson CI |
| 11 | 5,6,7,9,10 | Docs sync: stage-doc, create `docs/pipeline.md`, supersession notes; parallel-safe with 12 |
| 12 | 5,6 | Unit tests: decision table, toggle matrix, trace completeness, error policy |
| 13 | 10,12 | Integration + `pipeline.run` judge-threading + demo reseed |
| 14 | 13 | HTML report + Definition-of-Done sign-off + verify-pr handoff |

Full step-by-step for each task follows. This plan is dispatched via subagent-driven-development: **one sonnet subagent per task**, pinned to the worktree absolute path, committing its own slice, verifying with the test command above before handing back.

---

## Task 1 — Schema: `term.trace_json` + `grounding_config`

Files: `src/palimpsest/webapp/db.py`, `docs/superpowers/specs/2026-06-30-demo-contracts.md` (same commit, H3).

- [ ] Add `trace_json TEXT NOT NULL DEFAULT '{}'` to `CREATE TABLE term` (after `note TEXT,`, before the `UNIQUE` line).
- [ ] Add singleton table:
```sql
CREATE TABLE grounding_config (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  model_name TEXT REFERENCES model(name),
  prompt TEXT,
  params_json TEXT
);
```
- [ ] Amend `demo-contracts.md` DDL block: same two changes.
- [ ] Amend `demo-contracts.md` null-rule: `difficulty='yellow'` with `resolved_by='judge_unavailable'` also yields `grounded=null` — a documented extension of the `difficulty='red' → grounded=null` rule, not a violation; frontend `term.grounded && …` truthiness treats `null` as "no node" regardless of `difficulty`.
- [ ] Verify: `PYTHONPATH=src .venv/bin/python -c "from palimpsest.webapp import db; db.init_db(reset=True); print('ok')"` → `ok`.
- [ ] Commit: `feat(db): add term.trace_json and grounding_config table (G6 schema)`.

## Task 2 — Archive tag + legacy strategy removal

Files: delete `grounding/{api_first,llm_judge,hybrid,mgenre}.py`, `scripts/{rebuild_demo_g3,emit_judge_inputs}.py`; modify `grounding/__init__.py`, `tests/test_terminology.py`. Do NOT touch `candidates.py`, `merge_goldens.py`, `data/seed/lemmas.json`.

- [ ] `git tag archive/grounding-g-strategies` BEFORE deleting (only archive per D1).
- [ ] Grep-confirm importers: `grep -rn "ApiFirstGrounding\|HybridGrounding\|LlmJudgeGrounding\|MGenreGrounding" src/ scripts/ tests/`. Expected hits only in files being deleted + `__init__.py` + tests + `term_pipeline.py`/`eval_strategies.py` (fixed in Task 6/10).
- [ ] `git rm` the 4 strategy files + 2 scripts.
- [ ] `grounding/__init__.py` → empty `__all__` + docstring (Task 5 adds the G6 export).
- [ ] Remove now-dead tests: `test_hybrid_*`, `test_type_filter_*`, `test_difficulty_*`, the deleted-class import line. Leave a NOTE comment for Task 12's author.
- [ ] Expected mid-sequence breakage: `term_pipeline.py`/`eval_strategies.py` won't import until Task 6/10 — do not chase.
- [ ] Verify surviving tests: `pytest tests/test_terminology.py -k "not hybrid and not type_filter and not difficulty_" -q`.
- [ ] Commit: `refactor(grounding): remove G1/G3/G5/G2 strategies (archived at archive/grounding-g-strategies)`.

## Task 3 — `candidates.py` rewrite (`GroundingConfig`)

- [ ] Add `GroundingConfig` dataclass to `base.py` (spec §3.3): `use_lemma=True, use_fallbacks=True, match_aliases=True, search_limit=7, enrich_top=5` (frozen).
- [ ] Rewrite `generate_candidates(wd, mention, config) -> {candidates, canon_by_qid, source, n_hits, queries}`:
  - query order: `wbsearchentities(lemma)` (only if `use_lemma` and lemma≠surface) → `wbsearchentities(surface)` → if 0 hits and `use_fallbacks`: CirrusSearch both forms → if still 0 and `use_fallbacks`: `wikipedia_wikibase_item`.
  - append `{q, kind, mechanism, n_hits}` to `queries` per call (feeds trace).
  - **remove** `passes_type_filter`/type/notable fields (D3/Q1 — judge disambiguates by description).
  - keep `label_ru` **separate** from aliases; candidate dict `{qid, label_ru, label_en, description, aliases_ru, aliases_en}`.
  - `search_limit`/`enrich_top` from config.
  - preserve insertion-order dedup (no set-only dedup) — documented invariant, not luck.
- [ ] Update the 3 surviving candidate tests to `config=GroundingConfig()` positional arg + new dict shape.
- [ ] Verify: `pytest tests/test_terminology.py -k candidates -q` → 3 passed.
- [ ] Commit: `refactor(grounding): parameterize candidate generation with GroundingConfig`.

## Task 4 — `norm()` + exact-label match (`grounding/match.py`)

- [ ] TDD tests first (fail): `norm` folds ё/е + whitespace + Unicode dashes (U+2010–U+2015, U+2212 → `-`); `exact_match` records `matched.kind` (label_ru/alias_ru/alias_en) and respects `match_aliases`.
- [ ] Implement `norm(s)` = NFC → dash-fold → ё→е → collapse ws → casefold; `exact_match(queries, candidates, *, match_aliases)` returns candidates + `matched={kind,value,query}`, label before alias, respects the toggle.
- [ ] Verify: `pytest tests/test_terminology.py -k "norm or exact_match" -q`.
- [ ] Commit: `feat(grounding): add norm() and exact_match() for G6 label matching`.

## Task 5 — `grounding/label_first.py` (G6 core)

Decision table (spec §3.2): 1 exact → green, no judge call; ≥2 exact OR (candidates but 0 exact) → judge; judge picks qid∈candidates → yellow/llm_disambiguation; judge qid=null → red/judge_rejected; judge qid∉candidates OR malformed → yellow/judge_unavailable (NEVER top-1 fallback); no candidates → red/no_candidates; candidate-gen RuntimeError → red/wikidata_unavailable; judge=None on escalation → yellow/judge_unavailable.

- [ ] TDD: 4 happy-path decision-table tests (exact-one green no-call; two-exact escalate; no-exact judge-reject; no-candidates red no-call).
- [ ] Implement `LabelFirstGrounding(client, config=None).ground(mention, *, judge=None) -> GroundingResult` emitting full trace v1: `{v, config, queries, search_source, candidates[].matched, exact_matches, resolved_by, judge, chosen_qid, n_api_calls, latency_ms}`.
- [ ] Retry semantics live in the caller (Task 7 `_judge_live`-style), not in the strategy — the injected `judge` returns a dict or raises; the strategy only classifies the outcome.
- [ ] Extract the judge prompt into a module-level `DEFAULT_GROUNDING_JUDGE_PROMPT` constant (Task 7 Settings displays/edits it).
- [ ] `grounding/__init__.py` → `from .label_first import LabelFirstGrounding`.
- [ ] Verify: `pytest tests/test_terminology.py -k label_first -q`.
- [ ] Commit: `feat(grounding): implement G6 label_first strategy with GroundingTrace v1`.

## Task 6 — `verdict.py`/`wikidata.py`/`base.py` cleanup

- [ ] Grep-confirm no importers of `ANACHRONISTIC_TYPES`/`DISAMBIGUATION`/`SCHOLARLY_ARTICLE`/`instance_and_subclass_of`/`passes_type_filter`/`difficulty_from_candidates`/`TYPE_DROP`.
- [ ] `verdict.py`: keep only `_norm`, `GREEN_SIM`, `YELLOW_SIM`, `pair_from_forms`.
- [ ] `wikidata.py`: remove the 3 constants + `instance_and_subclass_of` if zero callers; keep client + pairing helpers.
- [ ] `term_pipeline.py`: `ApiFirstGrounding` → `LabelFirstGrounding` (minimal import fix).
- [ ] Verify: full `pytest tests/test_terminology.py -q`.
- [ ] Commit: `refactor(terminology): drop type-filter and notability verdict (G6 supersedes)`.

## Task 7 — Settings backend (`grounding_config` GET/PUT)

- [ ] Grep the webapp test file for the `/api/criteria` GET/PUT pattern; mirror it exactly (`_require_admin`, `_guard_params`).
- [ ] TDD: GET default, PUT updates + reflects, PUT requires admin, params must be a JSON object.
- [ ] Implement `GroundingConfigBody` + `GET/PUT /api/grounding-config` with `ON CONFLICT(id) DO UPDATE` upsert.
- [ ] Add `_grounding_judge_live(...)` mirroring `_judge_live`: `budget.reserve()/settle()`, retry only on `is_transient_error` (429/5xx/timeout, max 2 backoff), **malformed JSON terminal (no retry)**, `max_tokens=512`, `temperature=0`, reasoning param omitted per-model via existing `model_matrix.py`. Wire into the live-grounding call site if one exists; else implement + `# TODO(wired when live re-grounding endpoint exists)` (do NOT invent an endpoint — spec scopes Settings surface only).
- [ ] Seed a default `grounding_config` row in `seed.py` (model = registry default, prompt = `DEFAULT_GROUNDING_JUDGE_PROMPT`, params `{max_tokens:512, temperature:0}`).
- [ ] Verify + commit: `feat(webapp): add grounding_config GET/PUT settings endpoint`.

## Task 7b — Judge-decision cache ("one sense per discourse") — see Addendum for the design decision

- [ ] Implement per-run in-memory cache keyed by `(scope_id, lemma, tuple(sorted(candidates_qids)), model, prompt_hash)`, upsert last-write-wins, sequential grounding (spec §4). `scope_id` = `paragraph_id` (demo) / document id (eval). **In-memory dict, NOT a DB table** (Addendum rationale). Inject the cache into `LabelFirstGrounding` via the judge wrapper (the cache wraps the `judge` callable, so the strategy stays cache-agnostic).
- [ ] Test: same (scope_id, lemma, candidates) hits the wrapped judge once across repeated calls; different scope_id calls it again.
- [ ] Verify + commit: `feat(grounding): add one-sense-per-discourse judge cache`.

## Task 8 — Settings frontend Grounding card (parallel-safe with 9)

- [ ] Grep the store for `saveCriterion`/`saveModel`/`getModels` and mirror exactly.
- [ ] `api-client.ts`: `GroundingConfig` type + `getGroundingConfig`/`updateGroundingConfig` (verify the real `apiGet`/`apiPut` helper names first).
- [ ] `SettingsTab.tsx`: Grounding section after Model Registry — model select + editable prompt + params, reusing `EvaluatorEditor`'s exact `va-*` classNames/markup (copy, don't invent tokens — invariant #3). UI strings **English only** (project invariant).
- [ ] Thread `groundingConfig`/`onSaveGroundingConfig` through `Props` + `VariantA.tsx`.
- [ ] Test in `SettingsTab.test.tsx` mirroring existing Evaluator tests.
- [ ] Verify (`npm test -- SettingsTab`) + commit: `feat(settings): add Grounding config card (model, prompt, params)`.

## Task 9 — Extractor `{surface, lemma, category}` (parallel-safe with 8)

- [ ] TDD: `parse_surfaces` reads `lemma`; empty/>80-char/newline lemma → falls back to surface.
- [ ] `DEFAULT_NER_PROMPT`: require nominative lemma; multi-word → agreed nominative form («династии Цин» → «династия Цин»); surface already nominative → lemma==surface. Update example JSON + output format.
- [ ] `parse_surfaces`/`validate_surfaces`/`deterministic_surfaces` carry `lemma` (deterministic fallback: lemma=surface).
- [ ] `term_pipeline.py cmd_mentions`: drop `lemmas.json` read, use extractor-emitted lemma; remove `LEMMAS` constant + `cmd_extract`'s lemma-file write (D4: pipeline no longer uses static lemmas.json; `merge_goldens.py` still does).
- [ ] Verify: `pytest tests/test_terminology.py -k "extract or parse_surfaces or deterministic" -q`.
- [ ] Commit: `feat(extract): emit {surface, lemma, category} from the NER extractor`.

## Task 10 — Eval/ablation harness (`scripts/eval_grounding.py`)

- [ ] `wilson_ci(correct, total, z=1.96)` in `eval_harness.py` (total=0 → (0.0,1.0)); TDD.
- [ ] `scripts/eval_grounding.py`: 8 configs = `itertools.product("01", repeat=3)` (covers both ladders); `--dry-run` (cost estimate, $0, nothing written, ABORT if forecast>cap), `--max-usd` (default 5), `--configs` subset. Reconstruct golden context when null (`n_context_reconstructed` counter). Exclude `wikidata_unavailable` rows from metrics (`n_excluded_wikidata_unavailable`). Emit `metrics.json` v1: config, golden meta, `qid_accuracy_groundable{correct,total,value,ci95}`, red_split, difficulty_distribution, resolved_by_distribution, escalation_rate, n_api_calls, n_judge_calls, judge_cost_usd, latency p50/p95. Output `reports/terminology/g6/<bits>/<run_id ISO>/`.
- [ ] Live judge builder inside `main()` (lazy import, `.env` load, `OPENROUTER_API_KEY`, `LLMClient(temperature=0, max_tokens=512)`); `judge=None` degrades every escalation to `judge_unavailable` and still runs offline end-to-end. **Provider-agnostic per E-D12 of the wiki-eval spec** — cost from usage, conservative fallback price.
- [ ] `.gitattributes`: `reports/terminology/**/*.jsonl filter=lfs diff=lfs merge=lfs -text` (same commit, H6).
- [ ] Verify: `--dry-run` smoke (no network) passes; if `OPENROUTER_API_KEY` present + owner-approved, run `--max-usd 5` for real and compare config `111` qid_accuracy vs reference 0.78 (drop >2 terms → flag, investigate before closing).
- [ ] Commit: `feat(eval): add G6 ablation harness (8 configs, Wilson CI, LFS traces)`.

## Task 11 — Docs sync (parallel-safe with 12)

- [ ] Rewrite `docs/stages/terminology.md` Design decisions for G6 only; supersession note block (archive tag, G3=0.78 reference); ablation table from Task 10; Subtleties gains norm()/resolved_by; append `## Methodology (article draft, EN)` verbatim from spec §9.
- [ ] **Create** `docs/pipeline.md` (H5) — thin pointer doc, up-link to docs/README.md, link to stage docs. Verify the G6 spec's `../../pipeline.md` up-link resolves.
- [ ] Mark grounding sections LEGACY in `2026-07-01-terminology-consolidation-design.md` + `2026-07-01-terminology-e2e-design.md` (pairing sections remain in force; don't delete history).
- [ ] Commit: `docs(terminology): sync stage-doc and pipeline overview to G6 label_first`.

## Task 12 — Unit tests full coverage (parallel-safe with 11)

- [ ] Toggle matrix (each toggle changes exactly its algorithm point); trace v1 completeness on every `resolved_by` path (`_REQUIRED_TRACE_KEYS ⊆ trace.keys()`); error policy (wikidata_unavailable distinct from no_candidates; malformed JSON terminal not retried; qid∉candidates → judge_unavailable not top-1; candidate order stable across replay).
- [ ] If a trace path is missing a key, fix `label_first.py` — don't weaken the test.
- [ ] Commit: `test(grounding): full G6 decision-table, toggle-matrix, and error-policy coverage`.

## Task 13 — Integration + `pipeline.run` judge-threading + demo reseed

- [ ] Thread `judge=None` through `pipeline.run(..., grounder, pairer, judge=None)` → `grounder.ground(m, judge=judge)`; regression test confirms it reaches the grounder.
- [ ] Add `trace: dict = field(default_factory=dict)` to `base.Term`; `db_tuple()` appends `json.dumps(self.trace)`; both `pipeline.run` branches set `trace=gr.trace`.
- [ ] `seed.py`/`load_terms.py` INSERTs add `trace_json`; **update positional `db_tuple()` index assertions** in tests (spec flags this).
- [ ] Rewrite `scripts/rebuild_demo.py` to call `LabelFirstGrounding` via `pipeline.run(..., judge=<live judge>)`, overlay curated P3 pairing verdicts. Delete `scripts/emit_demo_grounding.py` if grep confirms it's dead.
- [ ] Reseed: `seed` → `term_pipeline.py mentions` → `rebuild_demo.py` → `load_terms.py`; spot-check `trace_json` non-`{}` on a pipeline row.
- [ ] Full suite `pytest tests/ -q` green; investigate any drop vs 298 floor.
- [ ] Commit: `feat(terminology): wire G6 through pipeline.run and reseed the demo`.

## Task 14 — HTML report + DoD + verify-pr handoff

- [ ] `docs/reports/2026-07-03-grounding-label-first.html` (house dark-theme format): G6 vs legacy summary, 8-config ablation table + Wilson CIs, 9-golden-🟡 qualitative validation, G6(111) vs 0.78 reference verdict, links to metrics.json/traces.jsonl, Settings card screenshot, DoD checklist.
- [ ] Run the DoD checklist (spec §13); `grep -rn "lemmas.json" scripts/ src/` returns only `merge_goldens.py`.
- [ ] Hand off to `/verify-pr` (orchestrator runs aspect agents + e2e-tester on the Settings card).
- [ ] Commit: `docs(reports): add G6 label_first block report`.

---

## Orchestrator addendum — resolving the 3 flagged gaps

The planning pass surfaced three gaps. Resolutions (decided by the orchestrator, since the owner is asleep and these follow from the spec):

1. **Judge-decision cache (§4) → Task 7b, in-memory not a DB table.** The spec's "one sense per discourse" cache is keyed by `(scope_id, lemma, candidates_qids, model, prompt_hash)`. Both consumers — the demo reseed and the golden/ablation eval — run in a **single process**, so an in-memory dict wrapping the `judge` callable is sufficient and correct. A `grounding_judge_cache` DB table would be a speculative abstraction (no cross-run-persistence caller exists) — violates the repo's "no speculative abstractions" rule. If the owner later wants cross-run persistence, promoting the dict to a table is a localized change. The cache wraps the judge callable, so `LabelFirstGrounding` stays cache-agnostic (clean boundary).

2. **e2e browser verification → handled at verify-pr, not in the plan.** This plan's scope is backend/data correctness. The Settings Grounding card (Task 8) and the demo reseed (Task 13) get a real browser pass when the orchestrator runs `/verify-pr` after Task 14 (e2e-tester agent on opus, per the routing override). Not a plan task — a post-plan gate.

3. **`docs/pipeline.md` absent → Task 11 creates it.** Spec §7's "rewrite docs/pipeline.md" is interpreted as "create" since the file doesn't exist. Confirmed in H5.

## Self-review — spec coverage

Every spec section maps to a task: §3.1→T3, §3.2/norm/error-enum→T4/T5/T12, §3.3→T3, §4 judge+Settings+budget→T5/T7, §4 judge-cache→T7b, §5 trace/metrics→T5/T10, §6 extractor→T9, §7 file-fate→T1/T2/T3/T6/T7/T8/T9/T10/T11/T13, §8 eval/ablation/Wilson/budget→T10, §9 methodology draft→T11, §10 Glossary redesign→**design-only, out of scope (separate UI PR)**, §11 risks→T4/T12 (R7/R1/R2/R6) + process (R3/R4/R5), §12 testing→T4/T5/T12/T13 + e2e at verify-pr, §13 DoD→T14.
