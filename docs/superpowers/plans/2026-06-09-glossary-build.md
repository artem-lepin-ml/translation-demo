# Plan — Glossary build (overnight, 2026-06-09)

Up-link: [docs/superpowers/specs/2026-06-09-glossary-build.md](../specs/2026-06-09-glossary-build.md). Goal: [docs/goals/2026-06-09-glossary-overnight.md](../../goals/2026-06-09-glossary-overnight.md).

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` to execute this plan phase-by-phase. Each phase has explicit exit criteria with auto-check commands. Pin every subagent prompt to absolute worktree path per goal §6.4: `/Users/a1111/Projects/Work/gse-translation/worktrees/glossary-overnight`.

---

## 1. Goal recap

Build a fully automatic RU→EN terminology glossary pipeline, run it on pages 774–832 of `data/raw/vol01_source.pdf`, and conduct an R&D experiment comparing four lookup strategies (S1 Wikipedia langlinks, S2 +Wikidata aliases, S3 +LLM fallback, S4 LLM-only baseline) with numeric metrics. Deliverables `glossary/main.json` + `glossary/audit/*` + HTML report `docs/reports/2026-06-09-glossary.html` are ready for Artem's morning review. All design decisions in goal §2 are frozen — do not re-litigate. Budget ~8 hours wall-clock (goal §9), executed autonomously without questions per scenario B.

---

## 2. Phase overview

| Phase | Name | Duration | Exit criteria summary | Depends on |
|-------|------|----------|----------------------|------------|
| P0 | Worktree + scaffolding | 15 min | `feat/glossary-overnight` worktree exists; skeleton modules + test files; `uv sync` green | — |
| P1 | Parser core (chronology) — TDD | 75 min | `parse_seed_pages` extracts chronology pages 774–795; tests on 3 chronology fixtures green | P0 |
| P2 | Parser name-index — TDD | 45 min | `_parse_name_index_page` extracts pages 801–832; types 8–14 covered; tests green | P0 |
| P3 | Corrective script — TDD | 30 min | `correct_seed_artifacts` applies 9 rules idempotently; `seed_corrections.jsonl` schema-valid | P1, P2 |
| P4 | Glossary schema + Glossary + Matcher + form-cache — TDD | 60 min | `tests/test_glossary.py` and `tests/test_glossary_matcher.py` green; round-trip JSON works | P0 |
| P5 | Lookup S1+S2 — TDD | 30 min | `lookup_english_wikipedia` + `enrich_with_wikidata` pass respx-mocked tests; batching ≤50 | P4 |
| P6 | Lookup S3 LLM fallback — TDD | 25 min | `lookup_english_llm` + `populate` orchestration test green; confidence capped at medium | P5 |
| P7 | Lookup S4 + `disable_tools` kwarg — TDD | 30 min | `LLMClient.complete(disable_tools=True)` short-circuits tool injection; S4 hard-fail test green | P4 |
| P8 | Golden-set construction | 60 min | `glossary/audit/golden_set.jsonl` has 50 stratified rows; `golden_set_audit.jsonl` has ≥45 WebFetch rows with matching html_title | P3 |
| P9 | Metrics module | 50 min | `metrics.json` has coverage×4, pairwise×6 (primary+lenient), accuracy×4, per-category, matcher_recall | P6, P7, P8 |
| P10 | HTML report templates | 50 min | `parser_audit.html`, `strategies_report.html`, `matcher_report.html` render; smoke tests green; no CDN | P9 |
| P11 | Matcher run on pilot + report | 25 min | `matcher_coverage.json` + populated `matcher_report.html` with 20 paragraphs; SHA256 embedded | P4, P9, P10 |
| P12 | Self-screenshot e2e via chrome-devtools | 30 min | ≥10 PNG in `glossary/audit/screenshots/` (timestamp filenames, ≥5KB each); ≥1 with browser console visible | P10, P11 |
| P13 | Docs (stage doc + pipeline.md + CLAUDE.md routing) | 25 min | `docs/stages/glossary.md` exists; `docs/pipeline.md` has new section; `CLAUDE.md` routing row added | P11 |
| P14 | Final report HTML + PR body + verify loop | 45 min | `docs/reports/2026-06-09-glossary.html` rendered with 360 radar chart; `docs/reports/2026-06-09-glossary-pr-body.md` ready; all §5 acceptance auto-checks pass | P12, P13 |
| Reserve | Verify loop + fixes | 60 min | Adversarial-verify 8-axis sweep; iterate §6.6–7 of goal | — |

Total: ~9.5h (incl. reserve, parallel groups absorb ~1.5h → on budget).

---

## 3. Phases (detailed)

### P0 — Worktree + scaffolding

**Inputs:**
- Goal §6.4 (worktree creation + isolation rule).
- Repo state on `feat/project`.

**Tasks:**
1. Verify clean tree on `feat/project`: `git -C /Users/a1111/Projects/Work/gse-translation status -s` → empty (or stashed).
2. Create worktree: `git -C /Users/a1111/Projects/Work/gse-translation worktree add ../worktrees/glossary-overnight -b feat/glossary-overnight feat/project`.
3. **Pin worktreePath in every subagent prompt** with the boilerplate from goal §6.4: `[ISOLATION] Work ONLY in worktree at absolute path: /Users/a1111/Projects/Work/gse-translation/worktrees/glossary-overnight. All git commits MUST originate from this tree. Before any bash/git command, verify $PWD starts with this path; otherwise abort.`
4. Scaffold module skeletons (empty docstring stubs):
   - `src/palimpsest/glossary.py`
   - `src/palimpsest/glossary_build.py`
   - `src/palimpsest/glossary_metrics.py`
   - `src/palimpsest/templates/glossary/__init__.py`
5. Scaffold script entry-points:
   - `scripts/parse_glossary_seed.py`
   - `scripts/build_glossary.py`
   - `scripts/build_golden_set.py`
   - `scripts/glossary_audit.py`
6. Scaffold prompt stubs:
   - `prompts/glossary/lookup_fallback.md`
   - `prompts/glossary/llm_only_batch.md` (first line per spec §2: `Use ONLY your training knowledge. Do not search the internet, call tools, or consult reference works. If you do not know, return null.`)
7. Scaffold test files (empty `pytest` files): `tests/test_glossary.py`, `tests/test_glossary_matcher.py`, `tests/test_glossary_build.py`, `tests/test_glossary_metrics.py`, `tests/test_glossary_audit.py`, `tests/test_build_golden_set.py`.
8. Scaffold `glossary/` top-level directory; add `.gitkeep` until first artifact lands; check `.gitattributes` already covers it under LFS (or add).
9. `uv sync` to ensure deps available; if `pdfplumber`, `pymorphy3`, `respx`, `jinja2`, `beautifulsoup4`, `httpx[http2]` are missing, add to `pyproject.toml` `[project.optional-dependencies] dev`/runtime as appropriate.
10. Commit: `chore(glossary): scaffold module + script skeletons`.

**Outputs:**
- Worktree at `/Users/a1111/Projects/Work/gse-translation/worktrees/glossary-overnight`.
- Empty module/script/test/prompt files.
- `pyproject.toml` with new deps added.

**Exit criteria:**
- `git -C /Users/a1111/Projects/Work/gse-translation/worktrees/glossary-overnight branch --show-current` returns `feat/glossary-overnight`.
- `uv run python -c "import palimpsest.glossary, palimpsest.glossary_build, palimpsest.glossary_metrics"` exits 0.
- `uv run pytest tests/test_glossary.py tests/test_glossary_build.py tests/test_glossary_metrics.py -q --collect-only` collects (even if 0 tests yet).
- `ls prompts/glossary/llm_only_batch.md` exists and first line matches spec §2.

**Estimated time:** 15 min.

---

### P1 — Parser core (chronology) — TDD

**Inputs:**
- `data/raw/vol01_source.pdf` (pages 774–795 — chronology Egypt, Mesopotamia, Antiquity).
- Spec §3 (parser design D1–D9, layout types 1–7).
- Goal §8 (bracket/slash semantics).

**Tasks:**
1. **TDD: write `tests/fixtures/chrono_egypt_p774.json` first.** Generate via one-shot script: open PDF, dump `page.chars` for page 774 (PDF index resolved per D7) to JSON array of `{x0, x1, top, text, fontname}` records. Commit the fixture; never regenerate.
2. **TDD: write `tests/test_glossary_build.py::test_parse_chrono_egypt_p774`** — load fixture, call `_chars_to_seed_terms(chars, source_page=774)`, assert ≥1 of each layout type 1–5 present, sample assertions on specific terms (`Хуфу`, `Хеопс` as alias).
3. **TDD: write `tests/test_glossary_build.py::test_parse_brackets_*`** — pure-Python tests for every bracket pattern enumerated in spec §3 D5: `(= Мина)`, `(греч. Хеопс)`, `(лат. ...)`, `(англ. ...)`, `[царица]`, `(царица)`, `(?)`, `(в Бубастисе)`, `(в Бубастисе/Танисе)`, `(1-й персидский период)`. Add slash tests: `Небра/Ранеб`, `Хети I/Хети II`, `Шабатака/Шабтика`, `Тахо (Теос, Джедхор)`.
4. Implement `LayoutType` enum (14 values per spec §3 interface).
5. Implement `SeedTerm` frozen dataclass (spec §3 interface, fields: `ru_lemma`, `ru_aliases`, `category`, `scope`, `notes`, `confidence`, `source_page`, `layout_type`).
6. Implement `_parse_brackets(surface) -> _BracketResult` per D5 decision tree (10 rules, ordered).
7. Implement `_classify_line(text, indent, has_date_suffix, font_flags) -> LayoutType` predicate chain (14 entries, first-match-wins).
8. Implement `_reconstruct_wrapped_lines(lines) -> list[str]` per D4.
9. Implement `_detect_pdf_offset(pdf) -> int` per D7 (probe footer; WARN + fallback to 0-based if no recognisable number).
10. Implement `_parse_chronology_page(page, source_page) -> list[SeedTerm]` (column-split + line reconstruction + classification + bracket parse).
11. Implement public `parse_seed_pages(pdf_path, page_range=(774, 832)) -> list[SeedTerm]`.
12. Add fixtures `tests/fixtures/chrono_mesopotamia_p781.json` and `tests/fixtures/chrono_antiquity_p793.json`; add corresponding tests covering types 6–7 (multiline throne, multiline period).
13. Wire `scripts/parse_glossary_seed.py` Typer CLI calling `parse_seed_pages` → emits `glossary/seed_terms.jsonl` (chronology subset for now).
14. Commit: `feat(glossary): chronology PDF parser with bracket/slash semantics`.

**Outputs:**
- `src/palimpsest/glossary_build.py` (parser core + helpers).
- `tests/fixtures/chrono_egypt_p774.json`, `chrono_mesopotamia_p781.json`, `chrono_antiquity_p793.json`.
- `tests/test_glossary_build.py` (parser sections).

**Exit criteria:**
- `uv run pytest tests/test_glossary_build.py -k "chrono or brackets or slash" -q` → all green.
- `uv run python scripts/parse_glossary_seed.py --pages 774-795 --output glossary/seed_terms.jsonl` produces ≥600 chronology entries (goal §5.1 lower bound `~600` for chronology).
- Auto-check: `python -c "import json; rows=[json.loads(l) for l in open('glossary/seed_terms.jsonl')]; assert len(rows)>=600, f'{len(rows)}'; types=set(r['layout_type'] for r in rows); assert {'period_header','dynasty_header','ruler_row'} <= types"`.

**Estimated time:** 75 min.

---

### P2 — Parser name-index — TDD

**Inputs:**
- `data/raw/vol01_source.pdf` (pages 801–832).
- Spec §3 D6 (name-index parser).
- Goal §8 (layout types 8–14).

**Tasks:**
1. **TDD: write `tests/fixtures/name_index_p810.json`** — dump page 810 `page.chars`.
2. **TDD: write `tests/test_glossary_build.py::test_parse_name_index_p810`** — assert layout types 8 (alpha header), 9 (entry+pages), 10 (parenthetical), 11 (cross-ref → no SeedTerm), 12 (see-also → SeedTerm with `confidence="low"`), 13 (range), 14 (multiline) all detected.
3. Implement `_parse_name_index_page(page, source_page) -> list[SeedTerm]` per D6.
4. Implement alpha-header detection via `char["fontname"]` matching `"Bold"|"Heavy"`.
5. Implement multiline reconstruction (type 14) via indent threshold +20–30pt.
6. Wire `parse_seed_pages` dispatcher: pages 774–795 → chronology, 796–800 → skip (bibliography), 801–832 → name-index.
7. Run end-to-end CLI: `uv run python scripts/parse_glossary_seed.py --pages 774-832 --output glossary/seed_terms.jsonl`; assert ≥1500 rows per goal §5.1.
8. Commit: `feat(glossary): name-index parser with cross-ref semantics`.

**Outputs:**
- `_parse_name_index_page` implementation in `glossary_build.py`.
- `tests/fixtures/name_index_p810.json`.
- Updated `glossary/seed_terms.jsonl` covering all pages 774–832.

**Exit criteria:**
- `uv run pytest tests/test_glossary_build.py -k "name_index" -q` → green.
- `python -c "import json; rows=[json.loads(l) for l in open('glossary/seed_terms.jsonl')]; assert len(rows)>=1500, f'{len(rows)}'"`.
- Stratified sample: ≥1 row each from page-buckets `{774..780, 781..795, 801..820, 821..832}`.

**Estimated time:** 45 min.

**Parallel with:** P1 (independent — different page ranges, different fixtures).

---

### P3 — Corrective script — TDD

**Inputs:**
- `glossary/seed_terms.jsonl` (output of P1+P2).
- Spec §3 D8 + goal §8 (9 rules, sequential).

**Tasks:**
1. **TDD:** write `tests/test_glossary_build.py::test_correct_seed_artifacts_*` — one synthetic input per rule:
   - `dedup`: duplicate term from name-index already in chronology → merged, log row.
   - `alias_merge`: alias-only entry merged into primary.
   - `char_normalize`: `'`/`'`, `–`/`—`/`‒` → unified.
   - `footer_remove`: stray "778" appended to entry → stripped.
   - `wordwrap_fix`: dangling continuation → joined.
   - `prose_intro_skip`: long paragraph on page 774 → dropped.
   - `bibliography_skip`: pages 796–800 → dropped at dispatcher (assert no rows from those pages survive).
   - `footnote_skip`: leading `*` line on page 778 → dropped.
   - `categorize`: dynasty header → `category="dynasty"`; battle → `event`; place → `place`; queen → `ruler` with `notes="queen"`.
2. **TDD:** idempotency test — run `correct_seed_artifacts(out, log)` twice on same input; second run produces zero new log rows.
3. Implement `CorrectionRecord` frozen dataclass per spec §3 interface.
4. Implement each rule as pure function `(terms, log) -> terms` with cheap pre-check.
5. Implement `correct_seed_artifacts(raw_seeds, log_path) -> list[SeedTerm]` as ordered pipeline 1→9.
6. Wire into `scripts/parse_glossary_seed.py` (run corrective after parse; emit `glossary/seed_corrections.jsonl`).
7. Commit: `feat(glossary): nine-rule corrective pipeline with audit log`.

**Outputs:**
- `correct_seed_artifacts` implementation.
- `glossary/seed_corrections.jsonl` (real run output).
- Updated `glossary/seed_terms.jsonl` (post-correction).

**Exit criteria:**
- `uv run pytest tests/test_glossary_build.py -k "correct" -q` → green.
- `python -c "import json; rows=[json.loads(l) for l in open('glossary/seed_corrections.jsonl')]; assert len(rows)>0; rules={r['rule_applied'] for r in rows}; assert {'categorize','char_normalize'} <= rules"`.
- Idempotency: run script twice; second run adds 0 rows to corrections log.

**Estimated time:** 30 min.

---

### P4 — Glossary schema + Glossary + Matcher + form-cache — TDD

**Inputs:**
- Spec §4 (schema), §6 (Matcher).
- Goal §2 row 3 (`pymorphy3` for forms).

**Tasks:**
1. **TDD:** `tests/test_glossary.py` — Pydantic round-trip (Cyrillic stays Cyrillic), `lemma_index` homonym list, `forms_index` build, `fingerprint()` stability under field reorder, validator rejects `en.primary=None` without `source="manual"`+notes, `upsert` invalidates caches.
2. **TDD:** `tests/test_glossary_matcher.py` — 6 cases per spec §10:
   - single-word nominative match;
   - single-word genitive (pymorphy3-derived form);
   - homonym `Фивы` EG vs GR resolved by paragraph scope/category cues;
   - multi-word 2-gram (`битва при кадеше`);
   - multi-word 3-gram;
   - overlapping spans (longest-wins);
   - skip `[TRANSLATION FAILED]` + picture markers (reuse `_is_picture_or_dinkus` from `translate.py`);
   - `ambiguous=True` on score ties;
   - empty-forms entry falls back to lemma.
3. Implement enums: `FormsMethod`, `Source`, `Confidence`, `Category`, `Scope` (`str, enum.Enum`).
4. Implement `RuFields`, `EnFields`, `Refs`, `GlossaryEntry` (Pydantic BaseModel, `extra="forbid"`, `model_validator`).
5. Implement `Glossary` class: `__init__`, `load`, atomic `save`, `upsert` (with cache invalidation), `get`, `all`, `lemma_index` (cached_property), `forms_index` (cached_property), `fingerprint`.
6. Implement `Match` dataclass + `Matcher` class per spec §6 interface.
7. Implement helpers `_tokenize_with_offsets`, `_resolve_homonyms`.
8. Implement `generate_forms(lemma)` in `glossary_build.py` per spec §5 D13 (multi-word cartesian, missing fallback, `\w+` tokenisation).
9. Add `tests/conftest.py` shared fixture: minimal two-entry `Glossary` for Фивы homonym.
10. Commit: `feat(glossary): pydantic schema, glossary container, runtime matcher`.

**Outputs:**
- `src/palimpsest/glossary.py` complete.
- `generate_forms` helper in `glossary_build.py`.
- `tests/test_glossary.py`, `tests/test_glossary_matcher.py` green.

**Exit criteria:**
- `uv run pytest tests/test_glossary.py tests/test_glossary_matcher.py -q` → all green.
- `uv run python -c "from palimpsest.glossary import Glossary, Matcher, GlossaryEntry; print('ok')"` → ok.
- Spec §6 invariants verified via tests (longest-wins, homonym disambig, offsets).

**Estimated time:** 60 min.

**Parallel with:** P1+P2+P3 — independent module (no PDF dependency).

---

### P5 — Lookup strategies S1+S2 — TDD

**Inputs:**
- `glossary/seed_terms.jsonl` (from P3).
- Spec §5 D1–D3, D8, D12 (S1+S2 design).
- `palimpsest.llm.client.LLMClient` (existing).

**Tasks:**
1. **TDD:** `tests/test_glossary_build.py::test_lookup_english_wikipedia_*` via `respx` — normal hit, disambig hit (`pageprops.disambiguation` set), missing title, batching: 55 titles → 2 HTTP calls.
2. **TDD:** `tests/test_glossary_build.py::test_enrich_with_wikidata_*` via `respx` — one normal QID, one with `P31=Q4167410` (disambig); assert `wbgetentities&ids=Q1|Q2|...` form.
3. **TDD:** `populate` idempotence — 3 pre-filled entries → 0 HTTP calls.
4. Implement `CandidateEnglish` frozen dataclass.
5. Implement `BuildLogRow` dataclass + JSONL append helper (single helper used by S1/S2/S3/S4).
6. Implement `_batch(iterable, size=50)` helper.
7. Implement `lookup_english_wikipedia(ru_titles, *, http_client)` (langlinks + pageprops, batched, redirect-aware, User-Agent header).
8. Implement `enrich_with_wikidata(qids, *, http_client)` using `wbgetentities&ids=...&props=labels|aliases|claims&languages=en`.
9. Implement orchestrator skeleton `populate(seeds, *, glossary, http_client, llm_client, s3_prompt_text, log_path)` — S1 path + S2 enrichment path (S3 placeholder until P6).
10. Wire `scripts/build_glossary.py --strategy s1` and `--strategy s2` Typer commands; smoke-run on first 50 seeds.
11. Commit: `feat(glossary): S1 wikipedia langlinks + S2 wikidata enrichment`.

**Outputs:**
- S1+S2 lookup functions + log rows.
- `glossary/build_log.jsonl` (initial entries from smoke-run).

**Exit criteria:**
- `uv run pytest tests/test_glossary_build.py -k "lookup_english_wikipedia or enrich_with_wikidata or populate_idempotence" -q` → green.
- Smoke run on 50 seeds: ≥30 S1 hits; corresponding S2 enrichment fires.
- `python -c "import json; rows=[json.loads(l) for l in open('glossary/build_log.jsonl')]; assert all('strategy' in r for r in rows)"`.

**Estimated time:** 30 min.

---

### P6 — Lookup strategy S3 LLM fallback — TDD

**Inputs:**
- S1+S2 misses/disambigs from P5.
- Spec §5 D3, D4, D11 (S3 design).
- `prompts/glossary/lookup_fallback.md`.

**Tasks:**
1. **TDD:** `tests/test_glossary_build.py::test_lookup_english_llm_*` — stub `LLMClient` returning canned JSON `{"primary": "...", "alternatives": [...], "source_hint": "..."}`; parse error → returns `None`; null primary → returns `None`.
2. **TDD:** `populate` orchestration path — S1 miss → S3 hit → entry has `confidence="medium"`, `source="s3"` (cap enforced at orchestrator). Note: `disable_tools` kwarg testing deferred to P7 integration test; S3 itself does NOT use this kwarg.
3. Author `prompts/glossary/lookup_fallback.md` with JSON-mode schema per spec §2 ("must output JSON with schema `{primary: str|null, alternatives: list[str], source_hint: str}`").
4. Implement `lookup_english_llm(ru, *, category, aliases, scope, client, prompt_text)`.
5. Extend `populate` to chain S1 → S2 → S3 for misses/disambig/low-confidence, with `asyncio.Semaphore(8)` gate.
6. Add resume invariant per spec §5 D7: skip seeds whose `main.json` entry has non-null `en.primary`.
7. Commit: `feat(glossary): S3 LLM fallback for wiki misses with medium-cap`.

**Outputs:**
- `lookup_english_llm` + S3 integration in `populate`.
- `prompts/glossary/lookup_fallback.md` finalised.

**Exit criteria:**
- `uv run pytest tests/test_glossary_build.py -k "lookup_english_llm or populate_s3" -q` → green.
- Smoke run continues prior run: S3 fires for ≥1 S1-miss; resulting entry has `confidence="medium"`.
- Auto-check: `python -c "import json; rows=[json.loads(l) for l in open('glossary/build_log.jsonl')]; s3_rows=[r for r in rows if r['strategy']=='s3']; assert len(s3_rows)>=5, f'only {len(s3_rows)} S3 rows'"`.

**Estimated time:** 25 min.

---

### P7 — Lookup S4 + `disable_tools` kwarg — TDD

**Inputs:**
- All seeds from P3.
- Spec §5 D5, D10 (S4 isolation + LLMClient kwarg).
- `prompts/glossary/llm_only_batch.md`.

**Tasks:**
1. **TDD:** `tests/test_llm_client.py::test_complete_disable_tools` — Anthropic path: monkeypatch SDK call; assert `tools` kwarg absent when `disable_tools=True`, present otherwise (when `tool_schema` passed). OpenAI path: assert behavioural no-op but kwarg accepted.
2. **TDD HARD:** `tests/test_glossary_build.py::test_s4_no_wiki_calls` per spec §10 — `respx` configured to FAIL on any `wikipedia.org` or `wikidata.org` request; `httpx` mock raises on any other web call; assert `lookup_llm_only_batch` completes without raising and every `LLMClient.complete` call carries `disable_tools=True`.
3. **TDD:** `test_build_log_s4_rows` — every S4 row in `build_log.jsonl` has `tools_disabled: true` AND `retrieval_disabled: true` AND `model: <id>`.
4. **TDD:** batch ordering — `lookup_llm_only_batch([term1, term2, term3], batch_size=2)` chunks into [t1,t2],[t3]; canned response preserves input order; mismatched-order response raises.
5. Modify `src/palimpsest/llm/client.py::complete` — add `disable_tools: bool = False` kwarg per spec §5 D10. In `_complete_anthropic`: `input_schema = None` guard BEFORE the existing `if input_schema is not None: kwargs["tools"] = ...` block. In `_complete_openai`: no-op but accept kwarg.
6. Author `prompts/glossary/llm_only_batch.md` with mandated first line + `[BATCH_TERMS]` placeholder; instruct JSON array output `[{primary, alternatives}|null]` preserving input order.
7. Implement `lookup_llm_only_batch(seeds, *, client, prompt_text, batch_size=20)` per spec §5 D5.
8. Wire `scripts/build_glossary.py --strategy s4` — writes to `glossary/s4_results.jsonl` (NOT merged into `main.json` per D6).
9. Add idempotence: skip seeds with existing row in `s4_results.jsonl`.
10. Commit: `feat(glossary): S4 LLM-only baseline with tool suppression`.

**Outputs:**
- `LLMClient.complete(disable_tools=...)` kwarg.
- `lookup_llm_only_batch` + `glossary/s4_results.jsonl` (NOT merged into `main.json` per spec §5 D6; independent R&D artifact. Ensure `.gitattributes` covers `glossary/*.jsonl` under LFS per goal §2 row 7).
- `prompts/glossary/llm_only_batch.md`.

**Exit criteria:**
- `uv run pytest tests/test_llm_client.py tests/test_glossary_build.py -k "disable_tools or s4_no_wiki or s4_rows or batch_order" -q` → all green.
- Smoke run S4 on 50 seeds: `s4_results.jsonl` has 50 rows; `build_log.jsonl` S4 rows all carry `tools_disabled=true, retrieval_disabled=true`.

**Estimated time:** 30 min.

**Parallel with:** P5+P6 — depends only on P4 (Glossary + LLMClient stub); the `disable_tools` change is additive.

---

### P8 — Golden-set construction

**Inputs:**
- `glossary/seed_terms.jsonl` from P3.
- Goal §4 ("Golden-set: как агент строит") + §7 anti-халтура.
- WebFetch tool available.

**Tasks:**
1. **TDD:** `tests/test_build_golden_set.py::test_stratified_sample` — assert `_stratified_sample` returns 10 per category (50 total), with required hand-picked names per goal §4.
2. **TDD:** `tests/test_build_golden_set.py::test_golden_set_audit_row_schema` — fixture `GoldenSetAuditRow` round-trips; all 7 fields present (`term`, `source_url`, `webfetch_timestamp_iso`, `http_status`, `html_title`, `notes`, `all_strategies_agreed`).
3. Implement `_stratified_sample(seed_terms, targets)` with hardcoded targets from goal §4 (10 rulers, 10 places, 10 events, 10 dynasties, 10 culture/people/institutions).
4. Implement `_fetch_wikipedia_en(ru_lemma) -> dict` using WebFetch (sequential, ~50 calls).
5. Implement `_cross_check_viaf(term)` for ruler+place categories (≥10 cross-checks per goal §7).
6. Implement `_cross_check_pleiades(term)` for place category.
7. Implement `build()` Typer command — sequential WebFetch per term, write `glossary/audit/golden_set.jsonl` AND `glossary/audit/golden_set_audit.jsonl` (one row per attempt).
8. Run `uv run python scripts/build_golden_set.py build` — produces 50 golden + 50 audit rows.
9. Include sanity-probe entry (mark `"sanity_probe": true`) — one term with Wikipedia EN update post-model-training-cutoff per goal §4.
10. Hand-fill `golden.primary`, `golden.alternatives`, `golden.notes` from WebFetch results (model judgment, NOT cross-validated by lookups).
11. Verification: count rows where `html_title` contains the expected EN-name; assert ≥45 per goal §7.
12. Commit: `feat(glossary): golden-set with WebFetch audit trail`.

**Outputs:**
- `glossary/audit/golden_set.jsonl` (50 hand-labelled entries with `golden.primary`, `golden.alternatives`, `golden.source_url`, `golden.notes`).
- `glossary/audit/golden_set_audit.jsonl` (50 WebFetch audit rows, schema: `term`, `source_url`, `webfetch_timestamp_iso`, `http_status`, `html_title[:50]`, `notes`, `all_strategies_agreed`). **CRITICAL:** this is the audit trail; ≥45/50 rows must have `html_title` containing the expected EN primary term (goal §7 anti-халтура bullet 4). Failure on this gate blocks PR.
- `scripts/build_golden_set.py` complete.

**Exit criteria:**
- `python -c "import json; rows=[json.loads(l) for l in open('glossary/audit/golden_set.jsonl')]; assert len(rows)==50; cats=[r['category'] for r in rows]; from collections import Counter; c=Counter(cats); assert all(v>=8 for v in c.values()), c"` → ok.
- `python -c "import json; rows=[json.loads(l) for l in open('glossary/audit/golden_set_audit.jsonl')]; ok=sum(1 for r in rows if r.get('http_status')==200 and r.get('html_title')); assert ok>=45, f'{ok}/50'"` — validates http_status==200 and non-empty html_title as proof of successful fetch.
- Sanity probe entry present: `python -c "import json; assert any(r.get('sanity_probe') for r in [json.loads(l) for l in open('glossary/audit/golden_set.jsonl')])"`.

**Estimated time:** 60 min.

**Parallel with:** P5+P6+P7 — only requires P3 output.

---

### P9 — Metrics module

**Inputs:**
- `glossary/main.json` after S1+S2+S3 populate (from P6).
- `glossary/s4_results.jsonl` (from P7).
- `glossary/audit/golden_set.jsonl` (from P8).

**Tasks:**
1. **TDD:** `tests/test_glossary_metrics.py::test_compute_coverage` — synthetic 4-strategy dict; assert exact ratios.
2. **TDD:** `test_compute_pairwise_agreement_*` — all 6 pairs returned (underscore keys `S1_S2`, `S1_S3`, `S1_S4`, `S2_S3`, `S2_S4`, `S3_S4`); raises `AssertionError` when a strategy missing; primary/lenient exact values; `both_count=0` → null.
3. **TDD:** `test_compute_accuracy_*` — case/whitespace normalised via `_norm`; lenient checks `Sn.primary ∈ {golden.primary} ∪ golden.alternatives`.
4. **TDD:** `test_compute_per_category_insufficient_samples` — when N<3, leaf is `{"value": None, "reason": "insufficient_samples", "count": N}`.
5. **TDD:** `test_compute_matcher_metrics` — synthetic matches list; recall + per-category breakdown.
6. **TDD:** `test_write_metrics_json_round_trip` — `tmp_path` round-trip; all top-level keys present.
7. Implement `StrategyEntry` dataclass + projection helper from `CandidateEnglish`.
8. Implement `_norm`, `compute_coverage`, `compute_pairwise_agreement` (with 6-pair assertion), `compute_accuracy`, `compute_per_category`, `compute_matcher_metrics`.
9. Implement `write_metrics_json(strategy_results, golden_path, matches, total_entries, entries_by_id, output_path)` — single write point.
10. Wire CLI step in `scripts/build_glossary.py --metrics` — emits `glossary/audit/metrics.json`.
11. Commit: `feat(glossary): metrics module with pairwise + accuracy + matcher recall`.

**Outputs:**
- `src/palimpsest/glossary_metrics.py` complete.
- `glossary/audit/metrics.json` produced (post-pipeline run).

**Exit criteria:**
- `uv run pytest tests/test_glossary_metrics.py -q` → green.
- `python -c "import json; m=json.load(open('glossary/audit/metrics.json')); pairs={('S1','S2'),('S1','S3'),('S1','S4'),('S2','S3'),('S2','S4'),('S3','S4')}; got={tuple(k.split('_')) for k in m['pairwise_agreement_primary']}; assert pairs <= got, f'missing {pairs-got}'"` → ok (goal §5.3).
- All 4 strategies present in `m['coverage']` and `m['accuracy_primary']`. Auto-check: `python -c "import json; m=json.load(open('glossary/audit/metrics.json')); assert len(m['coverage'])==4 and all(s in m['coverage'] for s in ['S1','S2','S3','S4']), 'missing strategies in coverage'; assert len(m['accuracy_primary'])==4 and all(s in m['accuracy_primary'] for s in ['S1','S2','S3','S4']), 'missing strategies in accuracy'"`.

**Estimated time:** 50 min.

---

### P10 — HTML report templates

**Inputs:**
- `glossary/audit/metrics.json` (from P9).
- `glossary/seed_terms.jsonl`, `glossary/audit/parser_audit_validation.jsonl` (to be generated by audit run).
- Spec §7 D7 (Jinja2 + inline SVG + CSS-grid, no CDN).

**Tasks:**
1. **TDD:** `tests/test_glossary_audit.py::test_render_parser_audit` — render minimal fixture; parse with BeautifulSoup; assert table, thumbnail `<img>`, validation-row link.
2. **TDD:** `test_render_strategies_report` — assert `<svg>` bar chart, 4×4 heatmap grid, accuracy table, per-category expandable section, 3-5 divergence examples, tooltip `<script>`.
3. **TDD:** `test_render_matcher_report` — assert SHA256 header, `<mark>` spans with tooltips, paragraph_id list.
4. **TDD:** `test_no_cdn_references` — grep rendered HTML for `<script src="http`, `<link href="http` → none.
5. Create Jinja2 templates under `src/palimpsest/templates/glossary/`:
   - `parser_audit.html`
   - `strategies_report.html`
   - `matcher_report.html`
   - Shared inline CSS partial (`_styles.html`) + inline JS partial (`_tooltip.html`).
6. Implement helpers in `scripts/glossary_audit.py`: `_render_parser_audit`, `_render_strategies_report`, `_render_matcher_report`, `_emit_screenshot_instructions`.
7. Wire `scripts/glossary_audit.py audit` Typer CLI.
8. Implement `glossary/audit/pdf_pages/` generation: `pdftoppm` per goal §3 (pages 774, 778, 781, 793, 810, 831 → PNG).
9. Build `glossary/audit/parser_audit_validation.jsonl` (multi-step):
   9a. Implement builder in `scripts/glossary_audit.py` (function `_build_parser_audit_validation`):
       - Load `glossary/seed_terms.jsonl` (from P3).
       - Stratified sample: ≥20 from each of 4 layout buckets (Egypt chrono, Mesopotamia chrono, Antiquity chrono, name-index).
       - For each row: extract surface, category, scope, source_page; heuristic verdict = `correct` if `raw_pdf_text.strip().lower() == extracted_ru_lemma.strip().lower()`, else `wrong`; emit 100-row JSONL.
   9b. Manual review pass (agent task after 9a): load JSONL; for each `wrong` row, inspect raw_pdf_text + fixture image side-by-side; reclassify to `correct` or justify as genuinely wrong; rewrite JSONL with final `manual_verdict` field.
   9c. Acceptance gate: ≥95/100 final `correct` (auto-check in exit criteria).
10. Commit: `feat(glossary): jinja2 HTML reports + audit assets`.

**Outputs:**
- `src/palimpsest/templates/glossary/*.html`.
- `scripts/glossary_audit.py` complete.
- `glossary/audit/parser_audit.html`, `strategies_report.html`, `matcher_report.html` rendered.
- `glossary/audit/pdf_pages/*.png` (6 PNGs from pdftoppm).
- `glossary/audit/parser_audit_validation.jsonl` (100 rows).

**Exit criteria:**
- `uv run pytest tests/test_glossary_audit.py -q` → green.
- `test -f glossary/audit/parser_audit.html && test -f glossary/audit/strategies_report.html && test -f glossary/audit/matcher_report.html` — three files exist (rendering validation deferred to P12).
- `python -c "import json; rows=[json.loads(l) for l in open('glossary/audit/parser_audit_validation.jsonl')]; ok=sum(1 for r in rows if r['manual_verdict']=='correct'); assert len(rows)==100 and ok>=95, f'{ok}/100'"` per goal §5.1.
- `grep -c 'http://\|https://' glossary/audit/strategies_report.html` returns 0 (or only same-origin file paths).

**Estimated time:** 50 min.

---

### P11 — Matcher run on pilot_original.md + matcher_report

**Inputs:**
- `data/pilot/pilot_original.md`.
- `glossary/main.json` (from P6).
- `Matcher` class (from P4).
- `glossary/audit/metrics.json` (from P9 — provides `compute_matcher_metrics` reference values consumed here for `matcher_recall`).
- Templates from P10.

**Tasks:**
1. **TDD:** `tests/test_glossary_matcher.py::test_matcher_on_pilot_smoke` — load pilot, run on 10 sampled paragraphs; assert `len(matches) > 0`; skip cleanly if file absent.
2. Implement runner in `scripts/glossary_audit.py`: read 20 random paragraphs (deterministic seed for repro), run `Matcher.find` on each, render with `<mark>` spans + tooltips.
3. Compute SHA256 of `data/pilot/pilot_original.md` → embed in `matcher_report.html` header AND in `glossary/audit/matcher_coverage.json`.
4. Compute `matcher_recall` + per-category via `compute_matcher_metrics`; write to `matcher_coverage.json`.
5. Test rare-name case (`Хетепсехемуи` or similar) per goal §5.4; document in report.
6. Commit: `feat(glossary): matcher run on pilot with coverage report`.

**Outputs:**
- `glossary/audit/matcher_coverage.json`.
- `glossary/audit/matcher_report.html` populated.

**Exit criteria:**
- `python -c "import json; m=json.load(open('glossary/audit/matcher_coverage.json')); assert 'matcher_recall' in m and 'sha256' in m and 'paragraph_ids' in m"`.
- `python -c "import hashlib, pathlib, json; h=hashlib.sha256(pathlib.Path('data/pilot/pilot_original.md').read_bytes()).hexdigest(); m=json.load(open('glossary/audit/matcher_coverage.json')); assert m['sha256']==h, 'sha256 mismatch'"` per goal §5.4.
- `grep -c '<mark' glossary/audit/matcher_report.html` returns ≥1.
- Rare-name probe: `python -c "html=open('glossary/audit/matcher_report.html').read(); assert 'Хетепсехемуи' in html or 'хетепсехемуи' in html.lower(), 'rare-name test case not found or not documented'"` per goal §5.4.

**Estimated time:** 25 min.

---

### P12 — Self-screenshot e2e via chrome-devtools

**Inputs:**
- Three HTML reports (P10, P11).
- PDF page PNGs (P10).
- `mcp__chrome-devtools__*` tool family.
- Goal §6.8 (≥10 screenshots, timestamp filenames, ≥1 with browser console).

**Tasks:**
1. For each report HTML, issue `mcp__chrome-devtools__new_page` → `navigate_page(file://...)` → `take_screenshot` at multiple viewport scrolls (top, mid, bottom).
2. `parser_audit.html`: ≥3 screenshots (different table viewports).
3. `strategies_report.html`: ≥3 screenshots (bar chart, heatmap, golden-set diff).
4. `matcher_report.html`: ≥2 screenshots (marked paragraphs).
5. PDF page comparison: ≥2 screenshots placing PDF PNG next to parsed JSON.
6. **≥1 screenshot with browser console visible** (goal §6.8 — proof of real Chrome, not headless stub). Toggle DevTools panel via `mcp__chrome-devtools__evaluate_script` opening console.
7. Name each PNG `YYYY-MM-DD_HH-MM-SS_<report>_<viewport>.png`; timestamp = MCP call time.
8. Save to `glossary/audit/screenshots/`.
9. Record textual description of each screenshot in `glossary/audit/screenshots/notes.md` per goal §6.8.
10. Commit: `chore(glossary): e2e chrome-devtools screenshots + notes`.

**Outputs:**
- `glossary/audit/screenshots/*.png` (≥10).
- `glossary/audit/screenshots/notes.md`.

**Exit criteria:**
- `python -c "import glob, os; shots=sorted(glob.glob('glossary/audit/screenshots/*.png')); assert len(shots)>=10, f'only {len(shots)}'; sizes=[os.path.getsize(s) for s in shots]; assert all(s>5000 for s in sizes), 'suspiciously small PNG'"` per goal §6.8.
- `ls glossary/audit/screenshots/ | grep -c '^20'` ≥ 10 (all start with date prefix).
- `cat glossary/audit/screenshots/notes.md | wc -l` ≥ 10 (one description line per screenshot minimum).
- `ls -1 glossary/audit/screenshots/*.png | grep '_console_' | wc -l` ≥ 1 (at least one screenshot filename contains the `_console_` marker).

**Estimated time:** 30 min.

---

### P13 — Docs (stage doc + pipeline.md + CLAUDE.md routing)

**Inputs:**
- Final pipeline run outputs.
- CLAUDE.md conventions (four-level docs tree).

**Tasks:**
1. Write `docs/stages/glossary.md` per CLAUDE.md stage-doc fields: Title (`# Glossary build`), Up-link (`Up-link: [docs/pipeline.md](../pipeline.md)`), Purpose, Design decisions (referencing spec §3–§7), Interface (Python signatures for `parse_seed_pages`, `correct_seed_artifacts`, `populate`, `Matcher.find`), Subtleties, Status (`Implemented 2026-06-09`).
2. Update `docs/pipeline.md`: insert "Glossary build" section between Stage 03 and future Stage 04; cross-link to `docs/stages/glossary.md`.
3. Update `CLAUDE.md` routing table: add row `| Терминологический словарь | docs/stages/glossary.md |`.
4. Append `docs/known_issues.md` if any pdfplumber/Wikipedia API/pymorphy3 gotchas surfaced during P1–P11.
5. Commit (same-commit sync rule): `docs(glossary): stage doc + pipeline + routing` — group with any code touchups required for doc accuracy.

**Outputs:**
- `docs/stages/glossary.md`.
- Updated `docs/pipeline.md`, `CLAUDE.md`, optionally `docs/known_issues.md`.

**Exit criteria:**
- `test -f docs/stages/glossary.md`.
- `grep -c "Glossary build\|glossary" docs/pipeline.md` ≥ 1.
- `grep -c "docs/stages/glossary.md" CLAUDE.md` ≥ 1.
- Doc validates link integrity: `grep -oE '\[.*\]\(.*\.md.*\)' docs/stages/glossary.md` → all targets exist.

**Estimated time:** 25 min.

---

### P14 — Final report HTML + PR body + verify loop

**Inputs:**
- All artifacts (P0–P13).
- Goal §5 (acceptance criteria), §5.7 (final report format), §7 (anti-халтура).
- Goal §6.6 (Adversarial-verify 8-axis loop).

**Tasks:**
1. Compose `docs/reports/2026-06-09-glossary.html`:
   - TL;DR (3-5 lines per goal §5.7).
   - 360 radar chart (inline SVG) across 8 axes: correctness, edge-cases, documentation, architecture, unit-tests, e2e-tests, security, UI/UX. Each axis 1–5 with tooltip rationale.
   - Brief overview of each artifact (link to `glossary/main.json`, `glossary/audit/*`, screenshots).
   - All §4 numeric metrics in tables.
   - 3-5 R&D insights (per-strategy divergence examples).
   - "What remains / what Artem should do" section.
   - Stretch goals list (done/skipped from goal §11).
2. Compose `docs/reports/2026-06-09-glossary-pr-body.md` (Russian, per user memory `feedback_pr_body_style`): grouped, concise, table of coverage/accuracy metrics, lead with key idea.
3. Run all goal §5 auto-checks in sequence; any FAIL → enter verify loop §6.6–7 and fix.
4. Run goal §7 anti-халтура verifications:
   - `git -C ... diff feat/project -- factowl/` empty.
   - `git -C ... diff feat/project -- data/raw/ data/pilot/pilot_original.md` empty.
   - `git log feat/project..HEAD --format=%B | grep -i 'co-authored' && exit 1 || echo ok`.
   - `grep -rn "import openai\|from openai" src/` returns only `llm/client.py`.
5. Run Adversarial-verify via `superpowers:verification-before-completion` OR invoke 5 parallel sub-agents via `superpowers:dispatching-parallel-agents` with these spec prompts (each must be pinned to worktreePath per goal §6.4):
   - Agent 1 — correctness+edge-cases: specs §3–§8 coverage, rare-name handling, bracket semantics, S4 sanity probe.
   - Agent 2 — architecture+unit-tests: module isolation, spec §2 dependencies, test strategy coverage, test file count.
   - Agent 3 — e2e-tests+UI/UX: chrome-devtools screenshots real (not fake), file sizes >5KB, timestamp format, console-visible PNG present.
   - Agent 4 — documentation: CLAUDE.md format, routing table updated, pipeline.md updated, all links valid.
   - Agent 5 — security: LLM import isolation (`grep -rn "import openai" src/` returns only `llm/client.py`), no `--no-verify`, no `Co-Authored-By: Claude` in commits.
   Each agent emits a numeric score (5=PASS, 4=minor, 3=moderate, 2=critical, 1=blocker). Aggregate into the 360 radar chart in the final HTML report. If any agent scores ≤2 → re-enter fix loop (goal §6.6–7).
6. Final report: include the prepared `git push` + `gh pr create` command for Artem to run (per goal §7 — no remote push from Claude).
7. Commit: `docs(glossary): final report + PR body for review`.

**Outputs:**
- `docs/reports/2026-06-09-glossary.html`.
- `docs/reports/2026-06-09-glossary-pr-body.md`.
- All goal §5 acceptance criteria verified.

**Exit criteria:**
- Every checkbox in goal §5.1–§5.7 has a passing auto-check (inline `python -c` snippets from this plan: P1 line 116, P2 line 146, P5/P6/P7 build_log assertions, P8 golden-set audit gate, P9 metrics gate, P10 parser validation gate, P11 SHA256 gate, P12 screenshot gate). Aggregate results into the final-report HTML.
- `open docs/reports/2026-06-09-glossary.html` (manual) renders radar chart + tables.
- Final report explicitly lists the morning hand-off command per goal §7 (`git push -u origin feat/glossary-overnight && gh pr create ...`).
- Anti-халтура §7 list all green.

**Estimated time:** 45 min.

---

## 4. Task DAG

```
                        P0 (worktree+scaffold)
                            │
       ┌────────────────────┼─────────────────────┐
       │                    │                     │
       ▼                    ▼                     ▼
   P1 (chrono)          P2 (name-idx)         P4 (schema+matcher)
       │                    │                     │
       └──────┬─────────────┘                     │
              ▼                                   │
          P3 (corrective)                         │
              │                                   │
              ├──────────────────────►  P8 (golden-set)
              │                                   │
              └─────────┐                         │
                        ▼                         │
                    P5 (S1+S2) ◄──────────────────┤
                        │                         │
                        ▼                         │
                    P6 (S3) ◄─────────────────────┤
                        │                         │
                        │           P7 (S4 + disable_tools) ◄─┘
                        │                         │
                        └────────┬────────────────┘
                                 ▼
                            P9 (metrics) ◄────── P8
                                 │
                                 ▼
                           P10 (HTML templates)
                                 │
                                 ▼
                       P11 (matcher on pilot)
                                 │
                                 ▼
                  P12 (chrome-devtools screenshots)
                                 │
                                 ▼
                   P13 (docs: stage + pipeline + routing)
                                 │
                                 ▼
                  P14 (final report + PR body + verify)
```

---

## 5. Parallel execution groups (step 5 execute)

Each subagent prompt MUST include the isolation boilerplate:

```
[ISOLATION] Work ONLY in worktree at absolute path:
  /Users/a1111/Projects/Work/gse-translation/worktrees/glossary-overnight
All git commits MUST originate from this tree. Before any bash/git command,
verify $PWD starts with this path; otherwise abort.
```

**Group G1 — parser fan-out (after P0):**
- Agent A1: P1 chronology parser + tests + chronology fixtures.
- Agent A2: P2 name-index parser + tests + name-index fixture.
- Agent A3: P4 glossary schema + Matcher + tests (fully independent — no PDF).

Wait for G1 → run P3 (corrective, depends on P1+P2 outputs).

**Group G2 — lookup fan-out + golden-set (after P3 + P4):**
- Agent B1: P5 S1+S2 lookups + tests (consumes seeds, exercises Glossary.upsert).
- Agent B2: P7 S4 + `disable_tools` kwarg + tests (must execute AFTER P6 finishes its S3 integration test to avoid LLMClient signature conflict; can be TDD-ed independently on the P4 stub, but the live S3 integration test in P6 must complete first).
- Agent B3: P8 golden-set construction (only consumes seeds; WebFetch is independent).

Wait for B1 → run P6 (S3 fallback, chains onto S1+S2 results).

**Group G3 — reports + matcher (after P6+P7+P8):**
- Agent C1: P9 metrics module + tests. P9 is a pure-function layer; P10 (HTML templates) can develop in parallel using synthetic metric dicts (mocked JSON). P9's output `metrics.json` is consumed by P11 (matcher metrics computation).
- Wait for C1 → Agent C2: P10 HTML templates + tests + audit fixtures.
- Wait for C2 → Agent C3: P11 matcher on pilot + report fill-in.

**Group G4 — finalisation (sequential, single agent):**
- P12 chrome-devtools screenshots (MCP tool calls, not parallelisable).
- P13 docs.
- P14 final report + verify loop (verify loop itself uses 5-agent dynamic workflow per goal §6.6).

Total parallel groups: **4** (G1, G2, G3, G4); within each group, **3 independent subagents** for G1+G2, **sequential pipeline** for G3+G4.

---

## 6. Test strategy

Reference: spec §10 (unified test strategy). Five test files, all under `tests/`, all mocked (no network). Pre-commit hook is the gate per goal §5.6 — pytest exit 0 required.

| File | Module | Coverage target | When it runs |
|------|--------|----------------|--------------|
| `tests/test_glossary.py` | schema + container | round-trip, lemma_index, fingerprint, validator, upsert cache invalidation | P4 |
| `tests/test_glossary_matcher.py` | Matcher | 6 case classes (single/multi-word/homonym/overlap/skip/ambiguous), pilot smoke skip-if-absent | P4, P11 |
| `tests/test_glossary_build.py` | parser + corrective + lookups | 4 fixtures (3 chrono + 1 name-index covering 14 LayoutType values), bracket/slash unit tests, corrective idempotency, respx-mocked S1/S2, stub S3, S4 hard-fail (no wiki calls) | P1, P2, P3, P5, P6, P7 |
| `tests/test_glossary_metrics.py` | metrics | exact-value coverage/pairwise/accuracy, 6-pair assertion, per-category null sentinel, write_metrics_json round-trip, golden-set audit validation, S4 sanity probe | P9 |
| `tests/test_glossary_audit.py` | HTML templates | smoke render via BeautifulSoup, no CDN, required elements present | P10 |
| `tests/test_build_golden_set.py` | golden-set | stratified sample correctness, audit row schema | P8 |
| `tests/test_llm_client.py` (extend) | LLMClient | new `disable_tools` kwarg behaviour on Anthropic + OpenAI paths | P7 |
| Final gate | All test suites | Unified check | `uv run pytest -q` must exit 0 before any commit; pre-commit hook blocks on pytest failure (Hard Invariant #1, goal §5.6 / §7 bullet 17). |

Final integration: `uv run pytest -q` (full suite) at end of P14. Must exit 0 per goal §5.6.

Manual / E2E smoke: covered by P12 (chrome-devtools) and P14 (acceptance auto-checks). Verification gate per goal §6.8.

---

## 7. Risk register

| # | Risk | Likelihood | Impact | Mitigation |
|---|------|-----------|--------|------------|
| R1 | Parser only works on Egypt; Mesopotamia/Antiquity/name-index break (goal §7 first bullet "ленишься тестировать") | High | Critical | TDD with 4 distinct page fixtures (P1+P2); auto-check enforces layout-type diversity (P2 exit); stratified 100-row manual validation (P10 step 9) gates ≥95% accuracy per goal §5.1. |
| R2 | S4 secretly uses tools/RAG (goal §4 sanity probe, §7 "Strategy S4 реально БЕЗ доступа к wiki") | Medium | Critical (research-invalidating) | Three-level isolation per spec §5 D5: API kwarg `disable_tools=True`, prompt first-line hard instruction, `tools_disabled+retrieval_disabled` in every log row. Hard-fail test in P7 step 2 (respx FAILS on any wiki call). Sanity-probe term in golden-set (P8 step 9) detects post-cutoff knowledge leak. |
| R3 | Golden-set is circular (S1=S2=S3=S4 self-validation; goal §4 explicit) | Medium | High | Goal §7: ≥10 cross-checks via VIAF/Pleiades/Britannica WebFetch; `all_strategies_agreed` flag triggers third-source check; audit log proves WebFetch happened (≥45/50 html_title match). |
| R4 | `pymorphy3` returns empty/trivial forms for rare proper names (e.g. `Хетепсехемуи`) | High | Medium | Spec §5 D13 fallback: `forms_method="missing"` indexes lemma only; matcher (§6 Subtleties) gracefully degrades; acceptance threshold (goal §5.2) is ≥90% `pymorphy3` not 100%. |
| R5 | Screenshots faked (goal §7 "≥10 кринов на PR") — files exist but show blank/error pages | Medium | High | Goal §6.8 auto-check: file size >5KB filter; timestamp filename pattern; ≥1 screenshot with browser console visible (proof of real Chrome); textual description per screenshot in `notes.md`. |
| R6 | Wikipedia API rate-limit / soft-block | Low | Medium | Spec §5 D8 mandatory User-Agent; batching ≤50 per request (D2); idempotent populate (D7) allows resume after partial failure. |
| R7 | LLMClient changes break existing tests | Low | Medium | New kwarg defaults to `False` (no-op for existing callers); P7 step 1 dedicated test verifies non-regression on both Anthropic and OpenAI paths. |
| R8 | Manual verdict on 100-row parser validation is itself low quality | Medium | Medium | Goal §5.1 stratification: ≥20 from each layout bucket; auto-check enforces. P10 step 9 explicitly: agent uses heuristic for first-pass, then reviews `wrong` rows. |
| R9 | Pairwise agreement incomplete — only S1↔S2 computed, missing the other 5 pairs (goal §7 bullet 6) | Medium | High | Spec §5 D3 + plan P9 enforce all 6 pairs via `compute_pairwise_agreement` assertion; `write_metrics_json` is gated by this assertion; P9 exit auto-check validates 6 underscore-keyed pairs present. |
| R10 | Matcher validation only on synthetic data — no real pilot_original.md integration (goal §7 bullet 8) | Medium | High | Plan P11 runs Matcher on 20 random paragraphs from `data/pilot/pilot_original.md`; P12 screenshots capture real matches; `test_matcher_on_pilot_smoke` skips cleanly if file absent but reports coverage when present. |
| R11 | Parser validation accuracy gate poorly specified — unclear who creates the 100-row `parser_audit_validation.jsonl` | High | Medium | P10 step 9 split into 9a (heuristic builder), 9b (agent manual review of `wrong` rows), 9c (auto-check `≥95/100 correct`). Phase P10 owns 9a; same agent finishes 9b before exit. |
| R12 | Hard Invariants (goal §7 bullets 10–16) not monitored in risk register — file integrity, pre-commit, imports, commits, docs-sync | Medium | High | P14 task 4 runs anti-халтура verifications: `git diff feat/project -- factowl/ data/raw/ data/pilot/pilot_original.md` must be empty; grep `openai` imports (only `llm/client.py`); grep `co-authored` in commits (must be absent); verify `CLAUDE.md` routing updated; `uv run pytest -q` exits 0. Each subcommand sequential; FAIL on any. |

Top-5 (R1, R2, R3, R4, R5) per task requirement; R6–R12 included for completeness.

---

## 8. Time budget allocation

Maps plan phases to goal §9 budget rows (~8h total).

| Goal §9 row | Plan phase(s) | Goal time | Plan time | Delta |
|-------------|---------------|-----------|-----------|-------|
| §9.1 Brainstorm + verify spec | (already done) | 30 min | — | — |
| §9.2 Plan | (this document) | 20 min | — | — |
| §9.3 Worktree + scaffolding | P0 | 15 min | 15 min | 0 |
| §9.4 Parser chronology + corrective | P1 + part of P3 | 75 min | 75 min (P1) + 15 min (P3 share) | +15 (P3 split) |
| §9.5 Parser name-index | P2 + part of P3 | 45 min | 45 min (P2) + 15 min (P3 share) | +15 (P3 split) |
| §9.6 Glossary core + Matcher + form-cache | P4 | 60 min | 60 min | 0 |
| §9.7 Lookup S1+S2 | P5 | 30 min | 30 min | 0 |
| §9.8 Lookup S3 | P6 | 25 min | 25 min | 0 |
| §9.9 Lookup S4 baseline batches | P7 | 30 min | 30 min | 0 |
| §9.10 Golden-set hand-labelling | P8 | 60 min | 60 min | 0 |
| §9.11 Metrics + HTML reports | P9 + P10 | 50 min | 50 min (P9) + 50 min (P10) | +50 (split out templating) |
| §9.12 Matcher on pilot_original.md | P11 | 25 min | 25 min | 0 |
| §9.13 Self-screenshot e2e | P12 | 30 min | 30 min | 0 |
| §9.14 Docs + final report + PR | P13 + P14 | 45 min | 25 min (P13) + 45 min (P14) | +25 (verify loop more explicit) |
| Reserve | (verify+fixes loop within P14) | 60 min | absorbed | — |

**Total plan time (post-parallelisation):**
- Sequential critical path through G1 → P3 → G2 (longest = P5+P6) → P9 → P10 → P11 → P12 → P13 → P14:
  - max(P1=75, P2=45, P4=60) = 75 (P1 dominates)
  - + P3 = 30
  - + max(P5+P6 chain = 55, P7=30, P8=60) = 60 (P8 dominates). Note: P7 can run in parallel with P6 if P7 completes before P6's integration tests; otherwise the dependency on P7's `disable_tools` kwarg sequences them and extends critical path to P5(30) + P7(30) + P6(25) = 85.
  - + P9 = 50
  - + P10 = 50
  - + P11 = 25
  - + P12 = 30
  - + P13 = 25
  - + P14 = 45
  - = **~390 min ≈ 6.5h critical path**, leaving **~90 min reserve** for verify-loop iterations (matches goal §9 reserve row).

If parallelisation underperforms (subagent coordination overhead), absorb into reserve. If finished early per goal §11, run stretch goals in priority order.
