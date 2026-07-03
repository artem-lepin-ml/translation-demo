# Terminology Extract — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use `- [ ]`. Work ONLY inside `/Users/a1111/Projects/Work/worktrees/terminology-extract`; never `cd`/checkout elsewhere. Commits: Conventional Commits, **no Claude co-author trailer**.

**Goal:** Turn stage-1 `extract` into a real, reproducible term extractor that catches lowercase historical terms (peoples, titles, social classes), measured against a non-circular gold, and feeds a live-re-extract demo.

**Architecture:** `extract.py` gains `llm_surfaces` (subagent/OR-backed NER, validated against source) + improved `deterministic_surfaces` (caps + curated gazetteer + guarded suffixes) + `extract_key` (stable sha256) + `extract_paragraph_terms` (Term[] via `pipeline.run`). LLM only via injected `Extractor` (no `openai` in `terminology/`). Spec: [2026-07-01-terminology-extract-design.md](../specs/2026-07-01-terminology-extract-design.md).

**Tech Stack:** Python 3 (stdlib + existing `palimpsest.terminology`), pytest, existing `LLMClient` (in scripts only), Wikidata via existing `WikidataClient`.

---

## File structure

- Modify `src/palimpsest/terminology/base.py` — add `Extractor` type.
- Modify `src/palimpsest/terminology/extract.py` — `CATEGORIES`, `DEFAULT_NER_PROMPT`, `parse_surfaces`, `validate_surfaces`, `llm_surfaces`, `deterministic_surfaces`, refactor `deterministic_extract`, `extract_key`, `extract_paragraph_terms`.
- Create `src/palimpsest/terminology/gazetteer.py` — lexicon load + match (keeps `extract.py` focused).
- Create `data/seed/hist_term_lexicon.json` — curated domain lexicon (NOT copied from gold labels).
- Modify `tests/test_terminology.py` — new tests (or `tests/test_extract.py`).
- Create `scripts/eval_extraction.py` — recall/precision vs gold, case-split, micro-pool.
- Modify `scripts/term_pipeline.py` — `extract` subcommand (OR-backed + fallback + budget guards + credits-delta + correctness log).
- Modify `docs/stages/terminology.md`, `docs/known_issues.md`, `docs/README.md` — doc-parity.

Model-registry side (NOT built here — contract only): `/api/ner-config`, `POST /api/paragraphs/{id}/extract`, `extract_key`/`extracted_at` columns, Settings UI. They import `extract_key`, `extract_paragraph_terms`, `DEFAULT_NER_PROMPT`.

---

## Task 1: `Extractor` type + category set + prompt

**Files:** Modify `src/palimpsest/terminology/base.py`, `src/palimpsest/terminology/extract.py`; Test `tests/test_terminology.py`.

- [ ] **Step 1 — test:** add to `tests/test_terminology.py`:
```python
def test_categories_and_prompt_present():
    from palimpsest.terminology.extract import CATEGORIES, DEFAULT_NER_PROMPT
    assert {"people", "title", "social"} <= CATEGORIES
    assert "{{source}}" in DEFAULT_NER_PROMPT
    assert "<categories>" in DEFAULT_NER_PROMPT and "bad_example" in DEFAULT_NER_PROMPT
```
- [ ] **Step 2 — run, expect ImportError.** `pytest tests/test_terminology.py::test_categories_and_prompt_present -v`
- [ ] **Step 3 — implement.** In `base.py` after `Judge`:
```python
Extractor = Callable[[str], list[dict]]   # source text -> [{surface, category}]
```
In `extract.py` (module top, after imports):
```python
CATEGORIES = {"person", "place", "people", "title", "social", "institution", "dynasty", "culture", "event"}
DEFAULT_NER_PROMPT = """<paste §10.3 of the design spec verbatim; keep {{source}} placeholder>"""
```
Copy the prompt text from the spec §10.3 exactly (role / ## sections / <categories> / <do_not_extract> / good <example> / <bad_example> / output format / `<source>{{source}}</source>`).
- [ ] **Step 4 — run, expect PASS.**
- [ ] **Step 5 — commit:** `feat(terminology): add Extractor type, CATEGORIES, DEFAULT_NER_PROMPT`

---

## Task 2: `parse_surfaces` + `validate_surfaces`

**Files:** Modify `extract.py`; Test `tests/test_terminology.py`.

- [ ] **Step 1 — tests:**
```python
def test_parse_surfaces_tolerates_fence_and_bad_category():
    from palimpsest.terminology.extract import parse_surfaces
    raw = '```json\n[{"surface":"Лагаше","category":"place"},{"surface":"x","category":"nonsense"}]\n```'
    out = parse_surfaces(raw)
    assert out[0] == {"surface": "Лагаше", "category": "place"}
    assert out[1]["category"] is None            # unknown category -> None
    assert parse_surfaces("not json") == []

def test_validate_surfaces_drops_not_in_source_and_dedups():
    from palimpsest.terminology.extract import validate_surfaces
    src = "В Лагаше правил лугаль. Лагаше славился."
    surfaces = [{"surface":"Лагаше","category":"place"},{"surface":"Лагаше","category":"place"},
                {"surface":"Lagash","category":"place"},{"surface":"","category":None}]
    valid, dropped = validate_surfaces(src, surfaces)
    assert [v["surface"] for v in valid] == ["Лагаше"]   # deduped, only substring
    assert dropped == 1                                   # "Lagash" not in source
```
- [ ] **Step 2 — run, expect fail.**
- [ ] **Step 3 — implement** in `extract.py`:
```python
import json  # already imported

def parse_surfaces(raw: str) -> list[dict]:
    """Parse an LLM JSON reply into [{surface, category}]; tolerant of ``` fences."""
    text = (raw or "").strip()
    m = re.search(r"\[.*\]", text, re.DOTALL)
    if m:
        text = m.group(0)
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return []
    out: list[dict] = []
    for item in data if isinstance(data, list) else []:
        if not isinstance(item, dict):
            continue
        surface = (item.get("surface") or "").strip()
        category = (item.get("category") or "").strip()
        if surface:
            out.append({"surface": surface, "category": category if category in CATEGORIES else None})
    return out

def validate_surfaces(source: str, surfaces: list[dict]) -> tuple[list[dict], int]:
    """Keep only surfaces that are literal substrings of source; dedup; count drops."""
    seen: set[str] = set()
    valid: list[dict] = []
    dropped = 0
    for item in surfaces:
        s = (item.get("surface") or "").strip()
        if not s:
            continue
        if s not in source:
            dropped += 1
            continue
        if s in seen:
            continue
        seen.add(s)
        valid.append({"surface": s, "category": item.get("category")})
    return valid, dropped
```
- [ ] **Step 4 — run, expect PASS.**
- [ ] **Step 5 — commit:** `feat(terminology): add parse_surfaces + validate_surfaces (source-substring guard)`

---

## Task 3: `gazetteer.py` + lexicon data

**Files:** Create `src/palimpsest/terminology/gazetteer.py`, `data/seed/hist_term_lexicon.json`; Test `tests/test_terminology.py`.

Lexicon authored from **domain knowledge** (titles/social/peoples every ancient-history text uses), NOT copied from `terminology_gold.jsonl` labels — record this in the eval report to keep deterministic recall honest.

- [ ] **Step 1 — tests:**
```python
def test_gazetteer_matches_lowercase_forms_word_boundary():
    from palimpsest.terminology.gazetteer import gazetteer_surfaces
    src = "правитель-лугаль опирался на авилумов, а молодцы пировали"
    got = {s["surface"] for s in gazetteer_surfaces(src)}
    assert "лугаль" in got and "авилумов" in got
    assert "молодцы" not in got                 # suffix -цы guarded by stoplist/min-stem

def test_gazetteer_suffix_ethnonym_with_guard():
    from palimpsest.terminology.gazetteer import gazetteer_surfaces
    src = "на границе стояли иллирийцы, но бойцы бежали"
    got = {s["surface"] for s in gazetteer_surfaces(src)}
    assert "иллирийцы" in got                    # ethnonym via lexicon or suffix
    assert "бойцы" not in got                    # guarded
```
- [ ] **Step 2 — run, expect fail.**
- [ ] **Step 3 — data** `data/seed/hist_term_lexicon.json` (starter; executor may extend from domain knowledge, not from gold):
```json
[
  {"lemma": "лугаль", "category": "title", "forms": ["лугаль", "лугаля", "лугалем", "лугале"]},
  {"lemma": "энси", "category": "title", "forms": ["энси"]},
  {"lemma": "ном", "category": "title", "forms": ["ном", "нома", "номы", "номов", "номах"]},
  {"lemma": "патеси", "category": "title", "forms": ["патеси"]},
  {"lemma": "претор", "category": "title", "forms": ["претор", "преторы", "преторов"]},
  {"lemma": "авилум", "category": "social", "forms": ["авилум", "авилумы", "авилумов", "авилумам"]},
  {"lemma": "мушкенум", "category": "social", "forms": ["мушкенум", "мушкенумы", "мушкенумов"]},
  {"lemma": "вардум", "category": "social", "forms": ["вардум", "вардумы", "вардумов"]},
  {"lemma": "шумеры", "category": "people", "forms": ["шумеры", "шумеров", "шумерами"]},
  {"lemma": "аккадцы", "category": "people", "forms": ["аккадцы", "аккадцев", "аккадцами"]},
  {"lemma": "амореи", "category": "people", "forms": ["амореи", "амореев", "амореями"]},
  {"lemma": "касситы", "category": "people", "forms": ["касситы", "касситов", "касситским", "касситами"]},
  {"lemma": "кутии", "category": "people", "forms": ["кутии", "кутиев", "кутиями"]},
  {"lemma": "иллирийцы", "category": "people", "forms": ["иллирийцы", "иллирийцев"]},
  {"lemma": "клерухия", "category": "institution", "forms": ["клерухия", "клерухии"]}
]
```
- [ ] **Step 3b — implement** `gazetteer.py`:
```python
"""Curated domain lexicon of (often lowercase) historical terms + guarded ethnonym suffixes.
Recall hints only — never QIDs/notability; grounding remains the existence authority."""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

_LEXICON = Path(__file__).resolve().parents[3] / "data/seed/hist_term_lexicon.json"
_SUFFIXES = ("цы", "яне", "ане", "еи")          # ethnonym gentilic endings
_SUFFIX_STOPLIST = {"молодцы", "бойцы", "жрецы", "гонцы", "певцы", "borцы"}  # common non-terms
_MIN_STEM = 4                                    # чтобы -цы не ловило короткие обычные слова

@lru_cache(maxsize=1)
def _entries() -> list[dict]:
    return json.loads(_LEXICON.read_text(encoding="utf-8"))

def gazetteer_surfaces(source: str) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    # 1) exact lexicon forms as whole words
    for e in _entries():
        for form in e.get("forms", [e["lemma"]]):
            if form in seen:
                continue
            if re.search(rf"(?<![А-Яа-яЁё]){re.escape(form)}(?![А-Яа-яЁё])", source):
                seen.add(form)
                out.append({"surface": form, "category": e.get("category")})
    # 2) suffix ethnonyms (guarded)
    for w in re.findall(r"[а-яё][а-яё\-]+", source):     # lowercase-initial words only
        if w in seen or w in _SUFFIX_STOPLIST:
            continue
        if any(w.endswith(sfx) for sfx in _SUFFIXES) and len(w) >= _MIN_STEM + 2:
            seen.add(w)
            out.append({"surface": w, "category": "people"})
    return out
```
- [ ] **Step 4 — run, expect PASS.** (If `молодцы`/`бойцы` slip through, extend `_SUFFIX_STOPLIST`.)
- [ ] **Step 5 — commit:** `feat(terminology): add domain gazetteer + guarded ethnonym suffixes`

---

## Task 4: `deterministic_surfaces` + refactor `deterministic_extract`

**Files:** Modify `extract.py`; Test `tests/test_terminology.py` (existing tests must stay green).

- [ ] **Step 1 — tests:**
```python
def test_deterministic_surfaces_finds_lowercase_via_gazetteer():
    from palimpsest.terminology.extract import deterministic_surfaces
    surfs = {s["surface"] for s in deterministic_surfaces("В Лагаше правил лугаль над авилумами.")}
    assert "Лагаше" in surfs and "лугаль" in surfs and "авилумами" in surfs
```
Keep existing `test_deterministic_extract_finds_proper_nouns` and `test_deterministic_extract_drops_sentence_initial_single_word` — they must still pass.
- [ ] **Step 2 — run, expect the new one to fail.**
- [ ] **Step 3 — implement.** Extract the current `_PROPER`-loop body of `deterministic_extract` into `_capitalized_surfaces(source) -> list[dict]` (same sentence-initial-single drop, returns `[{"surface":.., "category":None}]`, dedup). Then:
```python
from .gazetteer import gazetteer_surfaces

def deterministic_surfaces(source: str) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for item in _capitalized_surfaces(source) + gazetteer_surfaces(source):
        s = item["surface"]
        if s and s not in seen:
            seen.add(s)
            out.append(item)
    return out

def deterministic_extract(source: str) -> list[TermMention]:
    return mentions_from_surfaces(source, deterministic_surfaces(source))
```
Move the sentence-initial-single-word drop into `_capitalized_surfaces` unchanged.
- [ ] **Step 4 — run FULL file:** `pytest tests/test_terminology.py -v` — all green.
- [ ] **Step 5 — commit:** `refactor(terminology): deterministic_extract over surfaces + gazetteer recall`

---

## Task 5: `llm_surfaces` + `extract_key`

**Files:** Modify `extract.py`; Test `tests/test_terminology.py`.

- [ ] **Step 1 — tests:**
```python
def test_llm_surfaces_none_degrades_to_deterministic():
    from palimpsest.terminology.extract import llm_surfaces, deterministic_surfaces
    src = "В Лагаше правил лугаль."
    assert llm_surfaces(src, extractor=None) == deterministic_surfaces(src)

def test_llm_surfaces_validates_against_source():
    from palimpsest.terminology.extract import llm_surfaces
    src = "В Лагаше правил лугаль."
    fake = lambda s: [{"surface":"лугаль","category":"title"},{"surface":"Lagash","category":"place"}]
    got = {v["surface"] for v in llm_surfaces(src, extractor=fake)}
    assert got == {"лугаль"}                     # hallucinated "Lagash" dropped

def test_extract_key_is_stable_and_canonical():
    from palimpsest.terminology.extract import extract_key
    a = extract_key("src", {"modelName":"m","prompt":"p","params":{"b":1,"a":2}})
    b = extract_key("src", {"modelName":"m","prompt":"p","params":{"a":2,"b":1}})
    assert a == b and len(a) == 64               # sha256 hex, key-order independent
```
- [ ] **Step 2 — run, expect fail.**
- [ ] **Step 3 — implement:**
```python
import hashlib

def llm_surfaces(source: str, *, extractor: "Extractor | None" = None) -> list[dict]:
    if extractor is None:
        return deterministic_surfaces(source)
    valid, _ = validate_surfaces(source, extractor(source) or [])
    return valid

def extract_key(source: str, ner_config: dict) -> str:
    canon = "|".join([
        source,
        ner_config.get("modelName", ""),
        ner_config.get("prompt", ""),
        json.dumps(ner_config.get("params", {}) or {}, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
    ])
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()
```
Import `Extractor` under `TYPE_CHECKING` or from `.base` at top.
- [ ] **Step 4 — run, expect PASS.**
- [ ] **Step 5 — commit:** `feat(terminology): add llm_surfaces (validated) + stable sha256 extract_key`

---

## Task 6: `extract_paragraph_terms` + no-openai guard test

**Files:** Modify `extract.py`; Test `tests/test_terminology.py`.

- [ ] **Step 1 — tests:**
```python
def test_extract_paragraph_terms_builds_terms_and_holds_null_rule():
    from palimpsest.terminology.extract import extract_paragraph_terms
    from tests.test_terminology import _Grounder, _Pairer   # reuse fakes in this file
    cfg = {"modelName":"m","prompt":"p","params":{}}
    fake = lambda s: [{"surface":"GOODterm","category":"people"},{"surface":"REDterm","category":"people"}]
    terms = extract_paragraph_terms("GOODterm and REDterm", "X here", cfg,
                                    grounder=_Grounder(), pairer=_Pairer(), extractor=fake)
    red = next(t for t in terms if t.source_surface == "REDterm")
    assert red.difficulty == "red" and red.grounded is None and red.candidates == []

def test_terminology_module_has_no_openai_import():
    import pathlib, re
    root = pathlib.Path(__file__).resolve().parents[1] / "src/palimpsest/terminology"
    for p in root.rglob("*.py"):
        assert not re.search(r"^\s*(import openai|from openai|import.*LLMClient|from .*llm.*import)", p.read_text(), re.M), p
```
(If `_Grounder`/`_Pairer` are module-level in the test file, import path is `tests.test_terminology`; else define local fakes.)
- [ ] **Step 2 — run, expect fail.**
- [ ] **Step 3 — implement:**
```python
def extract_paragraph_terms(source, target, ner_config, *, grounder, pairer, extractor=None):
    from . import pipeline
    surfaces = llm_surfaces(source, extractor=extractor)
    mentions = mentions_from_surfaces(source, surfaces)
    return pipeline.run(source, target, mentions, grounder=grounder, pairer=pairer)
```
- [ ] **Step 4 — run, expect PASS + full suite green.**
- [ ] **Step 5 — commit:** `feat(terminology): add extract_paragraph_terms (Term[] via pipeline.run)`

---

## Task 7: `scripts/eval_extraction.py` (measure vs non-circular gold)

**Files:** Create `scripts/eval_extraction.py`; run it.

- [ ] **Step 1 — implement.** Read `data/seed/terminology_gold.jsonl` → `{pid: {surface}}`; read `data/seed/seed_paragraphs.jsonl` → `{id: source}`. For each extractor (`old_caps` = current `_PROPER`-only via a local copy or `deterministic_extract` pre-gazetteer flag; `deterministic` = `deterministic_surfaces`; `llm` = from a persisted `extracted_surfaces.json` if present, else skip), collect per-paragraph surface sets, micro-pool, split by `surface[0].islower()`, call `extraction_prf(extracted, gold)`. Write `reports/terminology/extraction_metrics.json` with `{extractor: {overall, lowercase, uppercase, surfaces_dropped_not_in_source?}}`. Print a table.
```python
# key logic
from palimpsest.terminology.eval_harness import extraction_prf
def split(surfs): 
    low = {s for s in surfs if s[:1].islower()}; up = surfs - low; return low, up
# micro-pool: union across paragraphs of (surface) for extracted and gold, then prf on low/up/all
```
- [ ] **Step 2 — run:** `PYTHONPATH=src python scripts/eval_extraction.py` → prints recall by case; `deterministic` lowercase recall ≥ 0.5 target (SC1). Commit metrics.
- [ ] **Step 3 — commit:** `feat(eval): extraction recall/precision by case vs non-circular gold`

---

## Task 8: `scripts/term_pipeline.py extract` (OR-backed + guards)

**Files:** Modify `scripts/term_pipeline.py`.

- [ ] **Step 1 — implement** a `cmd_extract(args)` and `extract` subparser with flags `--real`, `--dry-run`, `--max-usd 0.20`, `--model` (else read live OR `/models` or `EXTRACT_MODEL`). Behavior:
  - load `.env` (manual parse into `os.environ`; never print).
  - build `Extractor`: `fake`/deterministic if not `--real`; else closure using `LLMClient` (from `LLMConfig(base_url=OR, api_key=os.environ["OPENROUTER_API_KEY"], model=..., temperature=0)`), calling `DEFAULT_NER_PROMPT` with `{{source}}` filled → `parse_surfaces`.
  - `--dry-run`: print prompts + estimate, spend $0.
  - guards: `N_CALLS`(first-attempts) ≤ 20, retries ≤ N_CALLS, abort if credits-delta > `--max-usd` (poll `GET /api/v1/credits` before/after; mid-batch check).
  - per-paragraph correctness log → `reports/terminology/extract_llm_calls.jsonl` (`{pid, model, finish_reason, n_surfaces, n_dropped_not_in_source, latency_ms}`); mask key tail in any echo.
  - persist validated surfaces → `data/seed/extracted_surfaces.json` (schema `{paragraph_id, surfaces:[{surface,category}]}`); extend `data/seed/lemmas.json` for new lowercase forms.
- [ ] **Step 2 — offline smoke:** `PYTHONPATH=src python scripts/term_pipeline.py extract --dry-run` (no key needed) — prints intended calls, spends $0.
- [ ] **Step 3 — commit:** `feat(pipeline): term_pipeline extract subcommand (OR-backed, budget-guarded)`

*(Real `--real` run + demo regen happen at Finish/e2e under the key + `--max-usd`.)*

---

## Task 9: Docs (doc-parity, same PR)

**Files:** Modify `docs/stages/terminology.md`, `docs/known_issues.md`, `docs/README.md`. Dispatch `docs-keeper`.

- [ ] Stage doc Interface: extract is now code (`llm_surfaces`/`deterministic_surfaces`/`extract_key`/`extract_paragraph_terms`); Subtleties: recall/precision by case, gazetteer=recall-hints, surface validation, `extract_key` sha256; Status: replace stale `0.81`/`19🟡9🔴`/red-rate with measured numbers from `extraction_metrics.json`; add `merge_goldens.py` as gold provenance.
- [ ] `known_issues.md:15` (“Extraction precision unmeasured”) → rewrite: measured now (cite metrics), E1 implemented; `:12` red-rate re-check; add residual soft-circularity note + “model-registry NerConfig/endpoint contract asserted, verify at merge”.
- [ ] `docs/README.md` routing: add row for this extract spec/plan.
- [ ] Commit each doc change alongside its code (or one `docs(...)` commit at end of the batch).

---

## Self-review notes
- Spec coverage: SC1→Task 7; SC2→Task 7; SC3→Task 5; SC4→Task 6; SC5→Finish (demo regen); SC6→Tasks 2–6 tests; SC7→Task 8 guards + Task 7 metrics; §10 contract (`extract_key`, `extract_paragraph_terms`, `DEFAULT_NER_PROMPT`)→Tasks 1/5/6.
- Not built here (contract only): `/api/ner-config`, `POST …/extract`, cache columns, Settings UI — model-registry.
- Real-OR run is deferred to Finish (needs key; capped `--max-usd 0.20`, expected <$0.01).
