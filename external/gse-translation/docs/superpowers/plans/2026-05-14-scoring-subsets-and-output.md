# Scoring — subsets, output redesign, consistency legacy, factcheck off

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Реализовать четыре связанных изменения в stage 03 (paragraph subset, consistency в `_legacy/`, factcheck off by default, variant-scoped output с двумя derived-артефактами) согласно спеке [2026-05-14-scoring-subsets-and-output-design.md](../specs/2026-05-14-scoring-subsets-and-output-design.md).

**Architecture:**
1. Subset loader — отдельный модуль `src/palimpsest/scoring_subsets.py`, pydantic-модель `Subset` + `load_subset()`.
2. paths.py получает `variant` параметр на judge-уровне; новые helpers для `comparison.jsonl` и `reports/<judge>.jsonl`; удаляются `merged_jsonl`, `scores_json`.
3. scoring.py — pairs фильтруются по subset перед циклом; новые `build_comparison_jsonl()` + `build_judge_reports()` заменяют `build_merged_jsonl()` + `build_aggregate_scores()`.
4. consistency.md переезжает в `prompts/03_scoring/_legacy/`. Existing JSONL не трогаем.
5. Migration через one-shot `scripts/03_migrate_evaluation_to_variant.py` со списком ран'ов в аргументах.

**Tech Stack:** Python 3.12 + pydantic + asyncio + tqdm. pytest для тестов. yaml для конфигов.

**Branch:** работаем на текущей `artem`. PR → `feat/chunking-format`.

---

## File structure

**Create:**
- `src/palimpsest/scoring_subsets.py` — Subset pydantic + load_subset()
- `prompts/03_scoring/_legacy/consistency.md` — git mv from v1/
- `scripts/03_migrate_evaluation_to_variant.py` — one-shot migration

**Modify:**
- `src/palimpsest/paths.py` — variant param + new helpers
- `src/palimpsest/config.py` — FactcheckConfig.enabled default + ScoringConfig.paragraph_subset
- `src/palimpsest/scoring.py` — subset filter, variant, new derived builders
- `configs/scoring/*.yaml` — drop factcheck section (9 files)
- `docs/stages/03_scoring.md` — new layout + subset documentation
- `docs/pipeline.md` — minor wording if any
- `docs/known_issues.md` — добавить запись про non-atomic write fix (закроем C7 из analysis.md)

**Test:**
- `tests/test_scoring_subsets.py` — Subset pydantic
- `tests/test_scoring_subset_filter.py` — pairs filter в dispatcher
- `tests/test_comparison_jsonl.py` — multi-judge derived
- `tests/test_reports_jsonl.py` — full reports derived
- `tests/test_scoring_dispatcher.py` — update for v1/ subpath
- `tests/test_scoring_resume.py` — update for v1/ subpath
- `tests/conftest.py` — variant-aware fixtures

**Delete (after migration applied):**
- `scripts/03_migrate_evaluation_to_variant.py` (one-shot)
- `scripts/03_cleanup_minus_one.py` (legacy from previous migration)

---

## Task dependency graph

```
T1 (subset module) ─┐
T2 (consistency mv)  │
T3 (config)         ─┼─► T7 (scoring subset filter)
T4 (paths)          ─┘    T8 (scoring variant wiring)
                          │
                          ├─► T9 (build_comparison)
                          └─► T10 (build_judge_reports)
                                  │
                                  └─► T11 (run_scoring wires both, removes old)
                                          │
                                          ├─► T12 (update dispatcher tests)
                                          ├─► T13 (update resume tests)
                                          ├─► T14 (YAML cleanup)
                                          ├─► T15 (migration script)
                                          ├─► T16 (run migration)
                                          ├─► T17 (delete migration script)
                                          └─► T18 (smoke)
                                                  │
                                                  └─► T19 (docs sync)
                                                          │
                                                          └─► T20 (commit + PR-ready)
```

**Parallelizable groups** (swarm dispatch hint):
- Group A (foundation, independent): T1, T2, T3, T4 — могут идти параллельно
- Group B (depends on A): T7, T8 — могут идти параллельно
- Group C (depends on T4): T9, T10 — могут идти параллельно (но дешевле — последовательно)
- Group D (sequential от T11 до T18)
- Group E (T19, T20 — docs + PR)

---

## Task 1: Subset pydantic model + loader

**Files:**
- Create: `src/palimpsest/scoring_subsets.py`
- Test: `tests/test_scoring_subsets.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_scoring_subsets.py
from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from palimpsest.scoring_subsets import Subset, load_subset


def test_subset_parses_minimal():
    s = Subset.model_validate(
        {"name": "complex_150", "description": "x", "paragraph_ids": [1, 2, 3]}
    )
    assert s.name == "complex_150"
    assert s.description == "x"
    assert s.paragraph_ids == [1, 2, 3]


def test_subset_allows_extra_metadata():
    s = Subset.model_validate(
        {
            "name": "complex_150",
            "paragraph_ids": [1],
            "source_runs": ["large/foo"],
            "created_at": "2026-05-14",
        }
    )
    assert s.name == "complex_150"
    # extra fields tolerated (free-form metadata)
    dumped = s.model_dump()
    assert "source_runs" in dumped


def test_subset_description_defaults_empty():
    s = Subset.model_validate({"name": "x", "paragraph_ids": []})
    assert s.description == ""


def test_subset_paragraph_ids_required():
    with pytest.raises(ValidationError):
        Subset.model_validate({"name": "x", "description": ""})


def test_load_subset_reads_json(tmp_path: Path):
    subsets_dir = tmp_path / "scoring_subsets"
    subsets_dir.mkdir()
    (subsets_dir / "complex_150.json").write_text(
        json.dumps({"name": "complex_150", "paragraph_ids": [3, 12, 47]}),
        encoding="utf-8",
    )

    s = load_subset("complex_150", tmp_path)
    assert s.name == "complex_150"
    assert s.paragraph_ids == [3, 12, 47]


def test_load_subset_missing_file_raises_with_path(tmp_path: Path):
    with pytest.raises(FileNotFoundError) as exc:
        load_subset("nonexistent", tmp_path)
    assert "scoring_subsets" in str(exc.value)
    assert "nonexistent" in str(exc.value)


def test_load_subset_malformed_json_raises(tmp_path: Path):
    subsets_dir = tmp_path / "scoring_subsets"
    subsets_dir.mkdir()
    (subsets_dir / "bad.json").write_text("not json", encoding="utf-8")

    with pytest.raises(Exception):  # json.JSONDecodeError or ValidationError
        load_subset("bad", tmp_path)
```

- [ ] **Step 2: Run tests, verify they fail**

```
uv run pytest tests/test_scoring_subsets.py -v
```
Expected: ImportError or ModuleNotFoundError on `palimpsest.scoring_subsets`.

- [ ] **Step 3: Implement the module**

```python
# src/palimpsest/scoring_subsets.py
"""Paragraph subset loader for stage 03 scoring (spec S1–S4)."""
from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict


class Subset(BaseModel):
    """A named list of paragraph ids to evaluate.

    Lives at `<base_dir>/scoring_subsets/<name>.json`. Free-form metadata
    keys (`source_runs`, `created_at`, etc.) are tolerated for human use.
    """

    name: str
    description: str = ""
    paragraph_ids: list[int]

    model_config = ConfigDict(extra="allow")


def load_subset(name: str, base_dir: Path) -> Subset:
    """Load `<base_dir>/scoring_subsets/<name>.json` into a Subset."""
    path = base_dir / "scoring_subsets" / f"{name}.json"
    if not path.is_file():
        raise FileNotFoundError(
            f"scoring subset {name!r} not found at {path}"
        )
    return Subset.model_validate_json(path.read_text(encoding="utf-8"))
```

- [ ] **Step 4: Run tests, verify they pass**

```
uv run pytest tests/test_scoring_subsets.py -v
```
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add src/palimpsest/scoring_subsets.py tests/test_scoring_subsets.py
git commit -m "feat(scoring): subset pydantic model + loader (S1-S4)"
```

---

## Task 2: Move consistency.md → _legacy/

**Files:**
- Move: `prompts/03_scoring/v1/consistency.md` → `prompts/03_scoring/_legacy/consistency.md`

- [ ] **Step 1: Create _legacy/ directory and git mv**

```bash
mkdir -p prompts/03_scoring/_legacy
git mv prompts/03_scoring/v1/consistency.md prompts/03_scoring/_legacy/consistency.md
```

- [ ] **Step 2: Verify v1/ now has 5 files, _legacy/ has 1**

```bash
ls prompts/03_scoring/v1/
ls prompts/03_scoring/_legacy/
```
Expected v1: accuracy.md cultural.md fluency.md style.md terminology.md (5 files)
Expected _legacy: consistency.md (1 file)

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "refactor(prompts): move consistency.md to _legacy (S5)"
```

---

## Task 3: Config — FactcheckConfig default + ScoringConfig.paragraph_subset

**Files:**
- Modify: `src/palimpsest/config.py`
- Test: `tests/test_config_scoring.py` (create if absent; otherwise extend)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_config_scoring.py` (create file if it doesn't exist):

```python
# tests/test_config_scoring.py
from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from palimpsest.config import FactcheckConfig, ScoringConfig


def test_factcheck_default_disabled():
    fc = FactcheckConfig()
    assert fc.enabled is False
    assert fc.judge == "gpt-5.4-mini-low"


def test_factcheck_explicit_enable():
    fc = FactcheckConfig(enabled=True)
    assert fc.enabled is True


def test_scoring_paragraph_subset_defaults_none(tmp_path: Path):
    (tmp_path / "v1").mkdir()
    (tmp_path / "v1" / "fluency.md").write_text("dummy", encoding="utf-8")
    cfg = ScoringConfig(
        base_dir=tmp_path,
        prompts_root=tmp_path,
        judges=[{"model": "gpt-5.5-low"}],
        runs=["bucket/run"],
    )
    assert cfg.paragraph_subset is None


def test_scoring_paragraph_subset_accepts_name(tmp_path: Path):
    (tmp_path / "v1").mkdir()
    (tmp_path / "v1" / "fluency.md").write_text("dummy", encoding="utf-8")
    cfg = ScoringConfig(
        base_dir=tmp_path,
        prompts_root=tmp_path,
        paragraph_subset="complex_150",
        judges=[{"model": "gpt-5.5-low"}],
        runs=["bucket/run"],
    )
    assert cfg.paragraph_subset == "complex_150"
```

- [ ] **Step 2: Run tests, verify they fail**

```
uv run pytest tests/test_config_scoring.py -v
```
Expected: test_factcheck_default_disabled FAILS (current default True);
`test_scoring_paragraph_subset_*` FAILS (field not defined).

- [ ] **Step 3: Edit `src/palimpsest/config.py`**

Change FactcheckConfig.enabled default:

```python
class FactcheckConfig(BaseModel):
    """Factcheck stage — single fixed judge, independent of `judges` list."""

    enabled: bool = False   # was True
    judge: str = "gpt-5.4-mini-low"
```

Add `paragraph_subset` field to ScoringConfig:

```python
class ScoringConfig(BaseModel):
    """Stage 03 scoring pipeline configuration."""

    base_dir: Path
    translations_subdir: str = "translating"
    evaluation_subdir: str = "evaluation"
    prompts_root: Path = Path("prompts/03_scoring")
    prompts_variant: str = "v1"
    paragraph_subset: str | None = None   # NEW (spec S3)
    max_concurrency: int = 64
    factcheck: FactcheckConfig = FactcheckConfig()
    judges: list[JudgeConfig] = Field(..., min_length=1)
    runs: list[str] = Field(..., min_length=1)

    # ... existing _warn_if_variant_dir_missing validator stays as is
```

- [ ] **Step 4: Run tests, verify they pass**

```
uv run pytest tests/test_config_scoring.py -v
```
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/palimpsest/config.py tests/test_config_scoring.py
git commit -m "feat(config): paragraph_subset field + factcheck default off (S3, S6)"
```

---

## Task 4: paths.py — variant subpath + new helpers + remove old

**Files:**
- Modify: `src/palimpsest/paths.py`
- Test: `tests/test_paths.py` (create if absent)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_paths.py
from __future__ import annotations

from pathlib import Path

from palimpsest.paths import (
    comparison_jsonl,
    criterion_jsonl,
    evaluation_run_dir,
    factcheck_dir,
    factcheck_jsonl,
    judge_dir,
    parse_failures_jsonl,
    report_jsonl,
    reports_dir,
    variant_dir,
)


BASE = Path("/tmp/test_base")


def test_variant_dir():
    assert variant_dir(BASE, "evaluation", "large/foo", "v1") == BASE / "evaluation" / "foo" / "v1"


def test_judge_dir_has_variant():
    assert judge_dir(BASE, "evaluation", "large/foo", "v1", "gpt-5.5-low") == (
        BASE / "evaluation" / "foo" / "v1" / "gpt-5.5-low"
    )


def test_criterion_jsonl_has_variant():
    assert criterion_jsonl(BASE, "evaluation", "large/foo", "v1", "gpt-5.5-low", "accuracy") == (
        BASE / "evaluation" / "foo" / "v1" / "gpt-5.5-low" / "accuracy_scores.jsonl"
    )


def test_parse_failures_jsonl_has_variant():
    assert parse_failures_jsonl(BASE, "evaluation", "large/foo", "v1", "gpt-5.5-low") == (
        BASE / "evaluation" / "foo" / "v1" / "gpt-5.5-low" / "parse_failures.jsonl"
    )


def test_reports_dir():
    assert reports_dir(BASE, "evaluation", "large/foo", "v1") == (
        BASE / "evaluation" / "foo" / "v1" / "reports"
    )


def test_report_jsonl():
    assert report_jsonl(BASE, "evaluation", "large/foo", "v1", "gpt-5.5-low") == (
        BASE / "evaluation" / "foo" / "v1" / "reports" / "gpt-5.5-low.jsonl"
    )


def test_comparison_jsonl():
    assert comparison_jsonl(BASE, "evaluation", "large/foo", "v1") == (
        BASE / "evaluation" / "foo" / "v1" / "comparison.jsonl"
    )


def test_factcheck_outside_variant():
    assert factcheck_dir(BASE, "evaluation", "large/foo") == (
        BASE / "evaluation" / "foo" / "factcheck"
    )
    assert factcheck_jsonl(BASE, "evaluation", "large/foo") == (
        BASE / "evaluation" / "foo" / "factcheck" / "factcheck_scores.jsonl"
    )


def test_evaluation_run_dir_unchanged():
    assert evaluation_run_dir(BASE, "evaluation", "large/foo") == (
        BASE / "evaluation" / "foo"
    )
```

- [ ] **Step 2: Run tests, verify they fail**

```
uv run pytest tests/test_paths.py -v
```
Expected: ImportError on `comparison_jsonl`, `report_jsonl`, etc.

- [ ] **Step 3: Edit `src/palimpsest/paths.py`**

Replace the file body with:

```python
"""Canonical filesystem paths for the project."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = ROOT

DATA = ROOT / "data"
RAW = DATA / "raw"
INTERIM = DATA / "interim"
PROCESSED = DATA / "processed"

PROMPTS = ROOT / "prompts"
CONFIGS = ROOT / "configs"
REPORTS = ROOT / "reports"
REFERENCES = ROOT / "references"


def chapter_dir(volume: int, chapter: int, stage: str | None = None) -> Path:
    base = PROCESSED / f"vol{volume:02d}" / f"ch{chapter:02d}"
    return base / stage if stage else base


def _split_run(run: str) -> tuple[str, str]:
    """`<bucket>/<run_name>` -> ('bucket', 'run_name'). Raises if malformed."""
    parts = run.split("/")
    if len(parts) != 2:
        raise ValueError(f"run must be '<bucket>/<run_name>', got {run!r}")
    return parts[0], parts[1]


def translation_md(base_dir: Path, translations_subdir: str, run: str) -> Path:
    bucket, run_name = _split_run(run)
    return base_dir / translations_subdir / bucket / run_name / "translation.md"


def evaluation_run_dir(base_dir: Path, evaluation_subdir: str, run: str) -> Path:
    """data/pilot/evaluation/<run_name>/   (bucket dropped — run_name globally unique)"""
    _, run_name = _split_run(run)
    return base_dir / evaluation_subdir / run_name


def variant_dir(base_dir: Path, evaluation_subdir: str, run: str, variant: str) -> Path:
    return evaluation_run_dir(base_dir, evaluation_subdir, run) / variant


def judge_dir(
    base_dir: Path, evaluation_subdir: str, run: str, variant: str, judge: str
) -> Path:
    return variant_dir(base_dir, evaluation_subdir, run, variant) / judge


def criterion_jsonl(
    base_dir: Path,
    evaluation_subdir: str,
    run: str,
    variant: str,
    judge: str,
    criterion: str,
) -> Path:
    return judge_dir(base_dir, evaluation_subdir, run, variant, judge) / f"{criterion}_scores.jsonl"


def parse_failures_jsonl(
    base_dir: Path, evaluation_subdir: str, run: str, variant: str, judge: str
) -> Path:
    """Diagnostic log for criterion-prompt parse failures. Append-only."""
    return judge_dir(base_dir, evaluation_subdir, run, variant, judge) / "parse_failures.jsonl"


def reports_dir(base_dir: Path, evaluation_subdir: str, run: str, variant: str) -> Path:
    return variant_dir(base_dir, evaluation_subdir, run, variant) / "reports"


def report_jsonl(
    base_dir: Path, evaluation_subdir: str, run: str, variant: str, judge: str
) -> Path:
    """Per-judge full-report jsonl: one line per paragraph with full llm_report
    by criterion. Derived from criterion_jsonl files. Spec artefact (4)."""
    return reports_dir(base_dir, evaluation_subdir, run, variant) / f"{judge}.jsonl"


def comparison_jsonl(
    base_dir: Path, evaluation_subdir: str, run: str, variant: str
) -> Path:
    """Side-by-side judge comparison jsonl: per paragraph all judges × all criteria,
    plus factcheck if enabled. Derived. Spec artefact (5)."""
    return variant_dir(base_dir, evaluation_subdir, run, variant) / "comparison.jsonl"


def factcheck_dir(base_dir: Path, evaluation_subdir: str, run: str) -> Path:
    """Outside variant scope — factcheck is shared across variants."""
    return evaluation_run_dir(base_dir, evaluation_subdir, run) / "factcheck"


def factcheck_jsonl(base_dir: Path, evaluation_subdir: str, run: str) -> Path:
    return factcheck_dir(base_dir, evaluation_subdir, run) / "factcheck_scores.jsonl"
```

Note: `merged_jsonl` and `scores_json` are REMOVED.

- [ ] **Step 4: Run tests, verify they pass**

```
uv run pytest tests/test_paths.py -v
```
Expected: PASS (9 tests).

- [ ] **Step 5: Commit**

```bash
git add src/palimpsest/paths.py tests/test_paths.py
git commit -m "refactor(paths): add variant subpath + derived artefact helpers (S7, S8)"
```

---

## Task 5: scoring.py — accept variant param + subset filter

**Files:**
- Modify: `src/palimpsest/scoring.py`
- Test: `tests/test_scoring_subset_filter.py` (create)

This task is the most complex. We do it in three sub-passes: (a) thread `variant` through path helpers (mechanical), (b) wire subset loader filter, (c) update meta.json schema.

- [ ] **Step 1: Write the failing test for subset filter**

```python
# tests/test_scoring_subset_filter.py
from __future__ import annotations

import json
from pathlib import Path

import pytest

from palimpsest.scoring_subsets import Subset


def test_subset_filters_pairs():
    # Simulate the filter logic that will live in _score_run_for_judge.
    pairs = [(i, f"src_{i}", f"tr_{i}") for i in range(50)]
    subset = Subset(name="x", paragraph_ids=[3, 7, 12])
    keep = set(subset.paragraph_ids)
    filtered = [p for p in pairs if p[0] in keep]
    assert [p[0] for p in filtered] == [3, 7, 12]


def test_subset_out_of_range_detection():
    # Logic that detects bad subset before evaluation starts.
    pairs_ids = list(range(10))  # run has 10 paragraphs (ids 0..9)
    subset = Subset(name="x", paragraph_ids=[3, 15])
    ids_in_run = set(pairs_ids)
    bad = [pid for pid in subset.paragraph_ids if pid not in ids_in_run]
    assert bad == [15]
```

These are smoke-tests of the algorithm; the actual integration test lives in `test_scoring_dispatcher.py` (Task 12).

- [ ] **Step 2: Run tests, verify they pass**

These tests don't require code changes — they test pure Python set operations. Should PASS immediately.

```
uv run pytest tests/test_scoring_subset_filter.py -v
```

- [ ] **Step 3: Update scoring.py — variant param threading**

In `src/palimpsest/scoring.py`:

**3a.** Update imports:
```python
from .paths import (
    _split_run,
    comparison_jsonl,
    criterion_jsonl,
    evaluation_run_dir,
    factcheck_dir,
    factcheck_jsonl,
    judge_dir,
    parse_failures_jsonl,
    report_jsonl,
    reports_dir,
    translation_md,
    variant_dir,
)
from .scoring_subsets import load_subset
```

**3b.** Update `_score_run_for_judge` signature to accept `variant: str`:
```python
async def _score_run_for_judge(
    cfg: ScoringConfig,
    run: str,
    judge: JudgeConfig,
    prompts: dict[str, str],
    variant: str,
) -> None:
    ...
```

All internal `criterion_jsonl(...)`, `parse_failures_jsonl(...)`, `judge_dir(...)` calls inside this function now pass `variant`.

**3c.** Add subset filter at the start (after pairs loading):
```python
async def _score_run_for_judge(cfg, run, judge, prompts, variant):
    # ... existing pair-loading ...
    pairs = list(zip(ids, sources, translations))  # or however it's currently built

    if cfg.paragraph_subset:
        subset = load_subset(cfg.paragraph_subset, cfg.base_dir)
        ids_in_run = {pid for pid, _, _ in pairs}
        bad = [pid for pid in subset.paragraph_ids if pid not in ids_in_run]
        if bad:
            raise ValueError(
                f"subset {subset.name!r} contains ids missing in run {run!r}: "
                f"first 5 = {bad[:5]}"
            )
        keep = set(subset.paragraph_ids)
        pairs = [p for p in pairs if p[0] in keep]

    # ... existing dispatch loop ...
```

**3d.** Update `meta.json` payload (in the same function, where meta is written at the end):
```python
meta = {
    "judge": judge.model,
    "variant": variant,
    "paragraph_subset": cfg.paragraph_subset,   # None or string
    "criteria": list(prompts.keys()),
    "ts_start": ts_start,
    "ts_end": _utcnow_iso(),
}
```

**3e.** Update `_score_factcheck_for_run` — it does NOT receive variant (factcheck is outside variant scope). But it DOES need subset filtering (same logic as judges):
```python
async def _score_factcheck_for_run(cfg, run):
    # ... pairs loading ...
    if cfg.paragraph_subset:
        subset = load_subset(cfg.paragraph_subset, cfg.base_dir)
        keep = set(subset.paragraph_ids)
        pairs = [p for p in pairs if p[0] in keep]
    # ... existing dispatch ...
```

**3f.** Update `run_scoring(cfg)` — pass `cfg.prompts_variant` into `_score_run_for_judge`:
```python
async def run_scoring(cfg: ScoringConfig) -> None:
    prompts = load_prompts(cfg.prompts_root, cfg.prompts_variant)
    variant = cfg.prompts_variant

    for run in cfg.runs:
        if cfg.factcheck.enabled:
            await _score_factcheck_for_run(cfg, run)
        for judge in cfg.judges:
            await _score_run_for_judge(cfg, run, judge, prompts, variant)
        # build_comparison + build_judge_reports will be wired in Task 11
```

- [ ] **Step 4: Run all scoring tests to catch regressions in signatures**

```
uv run pytest tests/ -k scoring -v 2>&1 | head -60
```
Expected: existing tests in `test_scoring_dispatcher.py` and `test_scoring_resume.py` will FAIL because their `criterion_jsonl(...)` calls don't pass `variant`. That's fine — they'll be updated in Task 12/13.

- [ ] **Step 5: Commit**

```bash
git add src/palimpsest/scoring.py tests/test_scoring_subset_filter.py
git commit -m "feat(scoring): subset filter + variant in path helpers (S3, S7)"
```

---

## Task 6: build_comparison_jsonl — derived artefact (1)

**Files:**
- Modify: `src/palimpsest/scoring.py` (add new function)
- Test: `tests/test_comparison_jsonl.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_comparison_jsonl.py
from __future__ import annotations

import json
from pathlib import Path

import pytest

from palimpsest.config import FactcheckConfig, JudgeConfig, ScoringConfig
from palimpsest.scoring import build_comparison_jsonl


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


def _make_cfg(tmp_path: Path, judges: list[str], factcheck_enabled: bool = False) -> ScoringConfig:
    (tmp_path / "prompts_root" / "v1").mkdir(parents=True)
    (tmp_path / "prompts_root" / "v1" / "accuracy.md").write_text("x", encoding="utf-8")
    return ScoringConfig(
        base_dir=tmp_path,
        evaluation_subdir="evaluation",
        prompts_root=tmp_path / "prompts_root",
        prompts_variant="v1",
        factcheck=FactcheckConfig(enabled=factcheck_enabled),
        judges=[JudgeConfig(model=m) for m in judges],
        runs=["bucket/run"],
    )


def test_comparison_two_judges_same_criterion(tmp_path: Path):
    cfg = _make_cfg(tmp_path, judges=["judge_a", "judge_b"])
    run = "bucket/run"
    base = tmp_path / "evaluation" / "run" / "v1"
    _write_jsonl(
        base / "judge_a" / "accuracy_scores.jsonl",
        [
            {"id": 0, "score": 8, "llm_report": {}, "ts": "t"},
            {"id": 1, "score": 9, "llm_report": {}, "ts": "t"},
        ],
    )
    _write_jsonl(
        base / "judge_b" / "accuracy_scores.jsonl",
        [
            {"id": 0, "score": 7, "llm_report": {}, "ts": "t"},
            {"id": 1, "score": 10, "llm_report": {}, "ts": "t"},
        ],
    )
    # provide source/translated
    (tmp_path / "translating" / "bucket" / "run").mkdir(parents=True)
    (tmp_path / "translating" / "bucket" / "run" / "translation.md").write_text(
        "## 0\n\nsrc0\n\n## translated\n\ntr0\n\n## 1\n\nsrc1\n\n## translated\n\ntr1\n",
        encoding="utf-8",
    )

    # NOTE: this test stubs source/translated lookup — actual impl reads from
    # translation.md or from raw row fields. Adapt according to chosen impl.
    build_comparison_jsonl(cfg, run, ["accuracy"])

    out = base / "comparison.jsonl"
    assert out.is_file()
    rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 2
    assert rows[0]["id"] == 0
    assert rows[0]["scores"]["judge_a"]["accuracy"] == 8
    assert rows[0]["scores"]["judge_b"]["accuracy"] == 7
    assert "factcheck" not in rows[0] or rows[0]["factcheck"] is None


def test_comparison_null_for_missing_criterion(tmp_path: Path):
    cfg = _make_cfg(tmp_path, judges=["judge_a"])
    run = "bucket/run"
    base = tmp_path / "evaluation" / "run" / "v1"
    _write_jsonl(
        base / "judge_a" / "accuracy_scores.jsonl",
        [{"id": 0, "score": 8, "llm_report": {}, "ts": "t"}],
    )
    # fluency JSONL absent for judge_a
    (tmp_path / "translating" / "bucket" / "run").mkdir(parents=True)
    (tmp_path / "translating" / "bucket" / "run" / "translation.md").write_text(
        "## 0\n\nsrc0\n\n## translated\n\ntr0\n", encoding="utf-8",
    )

    build_comparison_jsonl(cfg, run, ["accuracy", "fluency"])

    out = base / "comparison.jsonl"
    rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["scores"]["judge_a"]["accuracy"] == 8
    assert rows[0]["scores"]["judge_a"]["fluency"] is None


def test_comparison_sorted_by_id(tmp_path: Path):
    cfg = _make_cfg(tmp_path, judges=["judge_a"])
    run = "bucket/run"
    base = tmp_path / "evaluation" / "run" / "v1"
    _write_jsonl(
        base / "judge_a" / "accuracy_scores.jsonl",
        [
            {"id": 5, "score": 8, "llm_report": {}, "ts": "t"},
            {"id": 1, "score": 9, "llm_report": {}, "ts": "t"},
            {"id": 3, "score": 7, "llm_report": {}, "ts": "t"},
        ],
    )
    (tmp_path / "translating" / "bucket" / "run").mkdir(parents=True)
    (tmp_path / "translating" / "bucket" / "run" / "translation.md").write_text(
        "## 1\n\ns1\n\n## translated\n\nt1\n## 3\n\ns3\n\n## translated\n\nt3\n## 5\n\ns5\n\n## translated\n\nt5\n",
        encoding="utf-8",
    )

    build_comparison_jsonl(cfg, run, ["accuracy"])

    out = base / "comparison.jsonl"
    rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert [r["id"] for r in rows] == [1, 3, 5]


def test_comparison_with_factcheck_enabled(tmp_path: Path):
    cfg = _make_cfg(tmp_path, judges=["judge_a"], factcheck_enabled=True)
    run = "bucket/run"
    base_variant = tmp_path / "evaluation" / "run" / "v1"
    base_run = tmp_path / "evaluation" / "run"
    _write_jsonl(
        base_variant / "judge_a" / "accuracy_scores.jsonl",
        [{"id": 0, "score": 8, "llm_report": {}, "ts": "t"}],
    )
    _write_jsonl(
        base_run / "factcheck" / "factcheck_scores.jsonl",
        [{"id": 0, "score": 0.95, "errors": []}],
    )
    (tmp_path / "translating" / "bucket" / "run").mkdir(parents=True)
    (tmp_path / "translating" / "bucket" / "run" / "translation.md").write_text(
        "## 0\n\ns0\n\n## translated\n\nt0\n", encoding="utf-8",
    )

    build_comparison_jsonl(cfg, run, ["accuracy"])
    rows = [json.loads(l) for l in (base_variant / "comparison.jsonl").read_text(encoding="utf-8").splitlines()]
    assert rows[0]["factcheck"] == {"id": 0, "score": 0.95, "errors": []}
```

The exact API of source/translated extraction depends on the existing `translation.md` parser — adapt these tests against the real parser shape used in `_score_run_for_judge`.

- [ ] **Step 2: Run tests, verify they fail**

```
uv run pytest tests/test_comparison_jsonl.py -v
```
Expected: ImportError on `build_comparison_jsonl`.

- [ ] **Step 3: Implement `build_comparison_jsonl` in `src/palimpsest/scoring.py`**

```python
def build_comparison_jsonl(
    cfg: ScoringConfig,
    run: str,
    criteria: list[str],
) -> None:
    """Rebuild <run>/<variant>/comparison.jsonl from raw criterion-JSONLs.

    Per-paragraph row: {id, source, translated, scores: {judge: {criterion: int|null}},
    factcheck: dict|null}. Sort by id ascending. Atomic write via tmp+rename.
    """
    variant = cfg.prompts_variant
    judges = [j.model for j in cfg.judges]

    # Collect per-judge per-criterion id→score map.
    per_judge_scores: dict[str, dict[str, dict[int, int | None]]] = {}
    all_ids: set[int] = set()
    for judge in judges:
        per_judge_scores[judge] = {}
        for crit in criteria:
            path = criterion_jsonl(
                cfg.base_dir, cfg.evaluation_subdir, run, variant, judge, crit
            )
            id_to_score: dict[int, int | None] = {}
            if path.is_file():
                with path.open("r", encoding="utf-8") as f:
                    for line in f:
                        row = json.loads(line)
                        id_to_score[row["id"]] = row.get("score")
                        all_ids.add(row["id"])
            per_judge_scores[judge][crit] = id_to_score

    # Factcheck rows by id (if enabled).
    fc_by_id: dict[int, dict] = {}
    if cfg.factcheck.enabled:
        fc_path = factcheck_jsonl(cfg.base_dir, cfg.evaluation_subdir, run)
        if fc_path.is_file():
            with fc_path.open("r", encoding="utf-8") as f:
                for line in f:
                    row = json.loads(line)
                    fc_by_id[row["id"]] = row

    # Source/translated pairs.
    pairs_map = _load_pairs_map(cfg, run)  # helper: id -> (source, translated)

    out_path = comparison_jsonl(cfg.base_dir, cfg.evaluation_subdir, run, variant)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for pid in sorted(all_ids):
            source, translated = pairs_map.get(pid, ("", ""))
            row: dict = {
                "id": pid,
                "source": source,
                "translated": translated,
                "scores": {
                    j: {c: per_judge_scores[j][c].get(pid) for c in criteria}
                    for j in judges
                },
            }
            if cfg.factcheck.enabled:
                row["factcheck"] = fc_by_id.get(pid)
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    tmp.replace(out_path)
```

You may need to extract the existing source/translated loader into `_load_pairs_map(cfg, run) -> dict[int, tuple[str, str]]` — it likely already exists in another form (used by `_score_run_for_judge`); refactor into a reusable helper if needed.

- [ ] **Step 4: Run tests, verify they pass**

```
uv run pytest tests/test_comparison_jsonl.py -v
```
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/palimpsest/scoring.py tests/test_comparison_jsonl.py
git commit -m "feat(scoring): build_comparison_jsonl derived artefact (S8)"
```

---

## Task 7: build_judge_reports — derived artefact (2)

**Files:**
- Modify: `src/palimpsest/scoring.py`
- Test: `tests/test_reports_jsonl.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_reports_jsonl.py
from __future__ import annotations

import json
from pathlib import Path

from palimpsest.config import FactcheckConfig, JudgeConfig, ScoringConfig
from palimpsest.scoring import build_judge_reports


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


def _make_cfg(tmp_path: Path) -> ScoringConfig:
    (tmp_path / "prompts_root" / "v1").mkdir(parents=True)
    (tmp_path / "prompts_root" / "v1" / "accuracy.md").write_text("x", encoding="utf-8")
    return ScoringConfig(
        base_dir=tmp_path,
        evaluation_subdir="evaluation",
        prompts_root=tmp_path / "prompts_root",
        prompts_variant="v1",
        judges=[JudgeConfig(model="judge_a")],
        runs=["bucket/run"],
    )


def test_reports_full_payload(tmp_path: Path):
    cfg = _make_cfg(tmp_path)
    run = "bucket/run"
    base = tmp_path / "evaluation" / "run" / "v1"
    full_report = {"summary": "good", "final_score": 8, "criteria_assessment": {"x": "y"}}
    _write_jsonl(
        base / "judge_a" / "accuracy_scores.jsonl",
        [{"id": 0, "score": 8, "llm_report": full_report, "ts": "t"}],
    )
    (tmp_path / "translating" / "bucket" / "run").mkdir(parents=True)
    (tmp_path / "translating" / "bucket" / "run" / "translation.md").write_text(
        "## 0\n\ns0\n\n## translated\n\nt0\n", encoding="utf-8",
    )

    build_judge_reports(cfg, run, ["accuracy"])
    out = base / "reports" / "judge_a.jsonl"
    rows = [json.loads(l) for l in out.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["id"] == 0
    assert rows[0]["accuracy"]["final_score"] == 8


def test_reports_null_on_skip(tmp_path: Path):
    cfg = _make_cfg(tmp_path)
    run = "bucket/run"
    base = tmp_path / "evaluation" / "run" / "v1"
    _write_jsonl(
        base / "judge_a" / "accuracy_scores.jsonl",
        [{"id": 0, "score": None, "llm_report": "skipped: marker", "ts": "t"}],
    )
    (tmp_path / "translating" / "bucket" / "run").mkdir(parents=True)
    (tmp_path / "translating" / "bucket" / "run" / "translation.md").write_text(
        "## 0\n\ns0\n\n## translated\n\nt0\n", encoding="utf-8",
    )

    build_judge_reports(cfg, run, ["accuracy"])
    out = base / "reports" / "judge_a.jsonl"
    rows = [json.loads(l) for l in out.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["accuracy"] is None
```

- [ ] **Step 2: Run tests, verify they fail**

```
uv run pytest tests/test_reports_jsonl.py -v
```
Expected: ImportError.

- [ ] **Step 3: Implement `build_judge_reports`**

```python
def build_judge_reports(
    cfg: ScoringConfig,
    run: str,
    criteria: list[str],
) -> None:
    """Rebuild <run>/<variant>/reports/<judge>.jsonl per judge from raw JSONLs.

    Per-paragraph row: {id, source, translated, <criterion>: full_llm_report|null}.
    null when score == null (skip / persistent fail). Sort by id. Atomic write.
    """
    variant = cfg.prompts_variant
    pairs_map = _load_pairs_map(cfg, run)

    for judge in cfg.judges:
        judge_slug = judge.model
        # per-criterion id -> (score, llm_report) map
        per_crit: dict[str, dict[int, tuple[int | None, object]]] = {}
        all_ids: set[int] = set()
        for crit in criteria:
            path = criterion_jsonl(
                cfg.base_dir, cfg.evaluation_subdir, run, variant, judge_slug, crit
            )
            per_crit[crit] = {}
            if path.is_file():
                with path.open("r", encoding="utf-8") as f:
                    for line in f:
                        row = json.loads(line)
                        per_crit[crit][row["id"]] = (row.get("score"), row.get("llm_report"))
                        all_ids.add(row["id"])

        out_path = report_jsonl(
            cfg.base_dir, cfg.evaluation_subdir, run, variant, judge_slug
        )
        out_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = out_path.with_suffix(".jsonl.tmp")
        with tmp.open("w", encoding="utf-8") as f:
            for pid in sorted(all_ids):
                source, translated = pairs_map.get(pid, ("", ""))
                row: dict = {"id": pid, "source": source, "translated": translated}
                for crit in criteria:
                    entry = per_crit[crit].get(pid)
                    if entry is None:
                        row[crit] = None  # not evaluated
                    else:
                        score, llm_report = entry
                        row[crit] = llm_report if score is not None else None
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        tmp.replace(out_path)
```

- [ ] **Step 4: Run tests, verify they pass**

```
uv run pytest tests/test_reports_jsonl.py -v
```
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/palimpsest/scoring.py tests/test_reports_jsonl.py
git commit -m "feat(scoring): build_judge_reports derived artefact (S8)"
```

---

## Task 8: run_scoring — wire new builders, remove old

**Files:**
- Modify: `src/palimpsest/scoring.py`

- [ ] **Step 1: Edit `run_scoring`**

Replace the existing end-of-run hooks (which called `build_merged_jsonl` + `build_aggregate_scores`) with:

```python
async def run_scoring(cfg: ScoringConfig) -> None:
    prompts = load_prompts(cfg.prompts_root, cfg.prompts_variant)
    variant = cfg.prompts_variant
    criteria = list(prompts.keys())

    for run in cfg.runs:
        if cfg.factcheck.enabled:
            await _score_factcheck_for_run(cfg, run)
        for judge in cfg.judges:
            await _score_run_for_judge(cfg, run, judge, prompts, variant)
        build_comparison_jsonl(cfg, run, criteria)
        build_judge_reports(cfg, run, criteria)
```

- [ ] **Step 2: Remove `build_merged_jsonl` and `build_aggregate_scores`**

Delete these functions from `src/palimpsest/scoring.py` entirely. Remove any imports/exports of them.

- [ ] **Step 3: Run scoring-related tests**

```
uv run pytest tests/ -k 'scoring' -v 2>&1 | tail -40
```
Expected: most tests now pass; dispatcher/resume may still fail until Task 12/13. New comparison/reports tests should pass.

- [ ] **Step 4: Commit**

```bash
git add src/palimpsest/scoring.py
git commit -m "refactor(scoring): wire comparison+reports builders, drop merged/aggregate"
```

---

## Task 9: Update test_scoring_dispatcher for variant subpath

**Files:**
- Modify: `tests/test_scoring_dispatcher.py`

- [ ] **Step 1: Read existing test file**

Use `Read` tool on `tests/test_scoring_dispatcher.py` to understand current shape.

- [ ] **Step 2: Update all path constructions**

Find every call like `criterion_jsonl(base, sub, run, judge, crit)` and change to `criterion_jsonl(base, sub, run, "v1", judge, crit)`. Same for `judge_dir`, `parse_failures_jsonl`.

Find `merged_jsonl(...)` references — replace with `comparison_jsonl(...)` (now includes `variant`).

Find `scores_json(...)` references — remove the tests entirely (artefact no longer exists).

Update any assertion that walks `<run>/<judge>/` paths to walk `<run>/v1/<judge>/`.

- [ ] **Step 3: Add a new test that exercises the subset filter end-to-end**

```python
async def test_dispatcher_respects_paragraph_subset(tmp_path: Path, monkeypatch):
    """When cfg.paragraph_subset is set, only listed ids end up in criterion JSONL."""
    # Setup translation.md with 10 paragraphs, write subset {3, 7}.
    subsets_dir = tmp_path / "scoring_subsets"
    subsets_dir.mkdir()
    (subsets_dir / "tiny.json").write_text(
        json.dumps({"name": "tiny", "paragraph_ids": [3, 7]}),
        encoding="utf-8",
    )
    # ... build cfg with paragraph_subset="tiny", stub LLMClient, run_scoring ...
    # ... assert that <judge>/accuracy_scores.jsonl has only ids 3 and 7 ...
```

(Use existing fixtures and LLMClient stub from the test file.)

- [ ] **Step 4: Run tests**

```
uv run pytest tests/test_scoring_dispatcher.py -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_scoring_dispatcher.py
git commit -m "test(scoring): update dispatcher tests for v1 subpath + subset filter"
```

---

## Task 10: Update test_scoring_resume for variant subpath

**Files:**
- Modify: `tests/test_scoring_resume.py`

- [ ] **Step 1: Update path constructions**

Same as Task 9 — every `criterion_jsonl`, `judge_dir`, `parse_failures_jsonl` call gains a `variant="v1"` arg.

- [ ] **Step 2: Add a resume test for subset → full transition**

```python
async def test_resume_compact_then_full_does_not_duplicate(tmp_path: Path, monkeypatch):
    """First run with paragraph_subset=tiny scores ids [3,7].
    Second run with paragraph_subset=None scores remaining ids.
    No id is scored twice."""
    # ... compose two configs, run both, assert criterion JSONL has each id exactly once ...
```

- [ ] **Step 3: Run tests**

```
uv run pytest tests/test_scoring_resume.py -v
```
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/test_scoring_resume.py
git commit -m "test(scoring): update resume tests + add subset→full transition"
```

---

## Task 11: Remove factcheck sections from YAML configs

**Files:**
- Modify: `configs/scoring/01-top-vs-baseline.yaml`
- Modify: `configs/scoring/02-large-chunking.yaml`
- Modify: `configs/scoring/03-small-anchor.yaml`
- Modify: `configs/scoring/04-small-chunking.yaml`
- Modify: `configs/scoring/05-family-and-alt.yaml`
- Modify: `configs/scoring/06-reasoning-low.yaml`
- Modify: `configs/scoring/large-low.yaml`
- Modify: `configs/scoring/small-low.yaml`
- Modify: `configs/scoring/smoke.yaml`

- [ ] **Step 1: For each YAML, drop the `factcheck:` block**

Before:
```yaml
factcheck:
  enabled: true
  judge: gpt-5.4-mini-low
```
After: section removed entirely. (Default is now `enabled: false`, so absence == disabled.)

For `smoke.yaml`, keep `factcheck: {enabled: true}` if you want to exercise the factcheck path during smoke; otherwise drop too.

- [ ] **Step 2: Verify configs still parse**

```
uv run python -c "from palimpsest.config import load_scoring; from pathlib import Path
for p in Path('configs/scoring').glob('*.yaml'):
    cfg = load_scoring(p); print(p.name, 'OK', cfg.factcheck.enabled)"
```
Expected: all parse, factcheck.enabled=False except smoke (your choice).

- [ ] **Step 3: Commit**

```bash
git add configs/scoring/
git commit -m "config(scoring): drop factcheck sections, default off (S6)"
```

---

## Task 12: Migration script

**Files:**
- Create: `scripts/03_migrate_evaluation_to_variant.py`

- [ ] **Step 1: Implement**

```python
#!/usr/bin/env python3
"""One-shot migration: <run>/<judge>/ → <run>/v1/<judge>/.

Usage:
    python scripts/03_migrate_evaluation_to_variant.py \
        --evaluation-dir data/pilot/evaluation \
        --run large/claude-opus-4.7-low_par_by_par \
        --run large/gemini-3.1-pro-low_par_by_par \
        --run large/gpt-5.5-low_par_by_par \
        ...

For each <run>, moves every judge subdir (anything not factcheck/v1/v2) into
<run>/v1/. Also removes <run>/merged_scores.jsonl and evaluation/scores.json.

This script is one-shot. After applying, DELETE it from the repo (S9).
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

SKIP = {"factcheck", "v1", "v2"}


def migrate_run(eval_dir: Path, run: str) -> int:
    _, run_name = run.split("/", 1)
    run_dir = eval_dir / run_name
    if not run_dir.is_dir():
        print(f"warning: run dir not found, skipping: {run_dir}", file=sys.stderr)
        return 0
    v1_dir = run_dir / "v1"
    moved = 0
    for child in run_dir.iterdir():
        if not child.is_dir() or child.name in SKIP:
            continue
        target = v1_dir / child.name
        if target.exists():
            print(f"warning: target already exists, skipping: {target}", file=sys.stderr)
            continue
        v1_dir.mkdir(exist_ok=True)
        print(f"git mv {child} {target}")
        shutil.move(str(child), str(target))
        moved += 1
    merged = run_dir / "merged_scores.jsonl"
    if merged.is_file():
        print(f"rm {merged}")
        merged.unlink()
    return moved


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--evaluation-dir", required=True, type=Path)
    ap.add_argument("--run", action="append", required=True, dest="runs")
    args = ap.parse_args()

    total = 0
    for run in args.runs:
        total += migrate_run(args.evaluation_dir, run)
    scores_json = args.evaluation_dir / "scores.json"
    if scores_json.is_file():
        print(f"rm {scores_json}")
        scores_json.unlink()
    print(f"\nmoved {total} judge dirs across {len(args.runs)} runs")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Test on a tmp tree first**

```bash
mkdir -p /tmp/test_eval/run1/judge_a /tmp/test_eval/run1/factcheck
touch /tmp/test_eval/run1/merged_scores.jsonl
uv run python scripts/03_migrate_evaluation_to_variant.py \
    --evaluation-dir /tmp/test_eval --run bucket/run1
ls /tmp/test_eval/run1/
```
Expected: `factcheck/  v1/`. `judge_a` is gone. `merged_scores.jsonl` is gone. `v1/judge_a/` exists.

- [ ] **Step 3: Commit**

```bash
git add scripts/03_migrate_evaluation_to_variant.py
git commit -m "feat(scripts): one-shot evaluation→variant migration (S9)"
```

---

## Task 13: Run migration on real evaluation data

**Files:**
- Mutates: `data/pilot/evaluation/<run>/` for explicit list of runs

- [ ] **Step 1: List target runs**

Inspect `data/pilot/evaluation/` and pick runs that need migrating (everything except Danil's archive `qwen_par_by_par/` and `qwen_pilot/`):

```bash
ls data/pilot/evaluation/
```

Expected listings might include: `claude-opus-4.7-low_par_by_par`, `gemini-3.1-pro-low_par_by_par`, `gpt-5.5-low_par_by_par`, `qwen_par_by_par` (Danil's — SKIP), `qwen_pilot` (Danil's — SKIP), `qwen_edited_par_by_par`, `gemma_par_by_par`, `claude-opus-4.7-high_par_by_par`, `gemini-3.1-pro-high_par_by_par`, `gpt-5.5-high_par_by_par`.

- [ ] **Step 2: Run migration with explicit --run list**

Adapt the list to actual content of `data/pilot/evaluation/`, excluding `qwen_par_by_par` and `qwen_pilot`:

```bash
uv run python scripts/03_migrate_evaluation_to_variant.py \
    --evaluation-dir data/pilot/evaluation \
    --run large/claude-opus-4.7-low_par_by_par \
    --run large/gemini-3.1-pro-low_par_by_par \
    --run large/gpt-5.5-low_par_by_par \
    --run local/qwen_edited_par_by_par \
    --run local/gemma_par_by_par \
    --run large/claude-opus-4.7-high_par_by_par \
    --run large/gemini-3.1-pro-high_par_by_par \
    --run large/gpt-5.5-high_par_by_par
```

- [ ] **Step 3: Verify with git status**

```bash
git status -s | head -40
git diff --stat
```

- [ ] **Step 4: Commit the data migration**

```bash
git add data/pilot/evaluation/
git commit -m "data(pilot): migrate evaluation tree to v1/ subpath (S9)"
```

---

## Task 14: Delete one-shot migration scripts

**Files:**
- Delete: `scripts/03_migrate_evaluation_to_variant.py`
- Delete: `scripts/03_cleanup_minus_one.py`

- [ ] **Step 1: Remove**

```bash
git rm scripts/03_migrate_evaluation_to_variant.py
git rm scripts/03_cleanup_minus_one.py
```

- [ ] **Step 2: Commit**

```bash
git commit -m "chore(scripts): drop one-shot migrators after applying (S9)"
```

---

## Task 15: Smoke verification

**Files:**
- Run: `scripts/03_scoring_smoke.sh`

- [ ] **Step 1: Confirm smoke.yaml is current**

```bash
cat configs/scoring/smoke.yaml
```

Make sure `prompts_variant: v1`. If you kept factcheck enabled for smoke, expect factcheck JSONL to appear.

- [ ] **Step 2: Run smoke**

```bash
bash scripts/03_scoring_smoke.sh
```

Expected stdout: progress bars for factcheck (if enabled) + 1 judge × 5 criteria × 50 paragraphs. No parse failures.

- [ ] **Step 3: Inspect output layout**

```bash
ls data/pilot/evaluation_smoke/qwen_par_by_par/
ls data/pilot/evaluation_smoke/qwen_par_by_par/v1/
ls data/pilot/evaluation_smoke/qwen_par_by_par/v1/gpt-5.5-low/
head -1 data/pilot/evaluation_smoke/qwen_par_by_par/v1/comparison.jsonl
head -1 data/pilot/evaluation_smoke/qwen_par_by_par/v1/reports/gpt-5.5-low.jsonl
```

Expected:
- `v1/` directory exists
- `v1/gpt-5.5-low/` contains 5 criterion JSONLs (not 6 — consistency removed)
- `v1/comparison.jsonl` exists with proper schema
- `v1/reports/gpt-5.5-low.jsonl` exists with full llm_report blocks

- [ ] **Step 4: Commit smoke artefacts**

```bash
git add data/pilot/evaluation_smoke/
git commit -m "data(smoke): post-redesign smoke verification (5 criteria, v1 layout)"
```

---

## Task 16: Update docs

**Files:**
- Modify: `docs/stages/03_scoring.md`
- Modify: `docs/pipeline.md`
- Modify: `docs/known_issues.md`

- [ ] **Step 1: Rewrite `docs/stages/03_scoring.md`**

Update sections:
- **Purpose**: 5 critеria (no consistency), factcheck off by default
- **Design decisions**: добавить S1–S10 кратко
- **Interface**: новый layout с `<run>/<variant>/...`
- **Subtleties**: subset filter, terminal-null, parse_failures, atomic write
- **Status**: refactor 2026-05-14

- [ ] **Step 2: Sync `docs/pipeline.md`**

Per-stage status block для stage 03 — обновить с новыми артефактами (`comparison.jsonl`, `reports/<judge>.jsonl`).

- [ ] **Step 3: Add entry to `docs/known_issues.md`**

Запись о том, что derived-артефакты пишутся через `tmp + os.replace` (atomic), не через построчный `"w"` — это закрывает C7 из docs/analysis.md.

- [ ] **Step 4: Commit**

```bash
git add docs/stages/03_scoring.md docs/pipeline.md docs/known_issues.md
git commit -m "docs(scoring): sync to v1 layout + comparison/reports artefacts"
```

---

## Task 17: Final verification + PR readiness

**Files:**
- No files modified — verification only

- [ ] **Step 1: Run full test suite**

```bash
uv run pytest tests/ -v 2>&1 | tail -30
```
Expected: all green.

- [ ] **Step 2: Check git log**

```bash
git log --oneline -20
```

Expected: ~17 commits from this plan, conventional commits style.

- [ ] **Step 3: Check working tree clean**

```bash
git status -s
```

- [ ] **Step 4: PR-ready check**

Branch is `artem`. User needs to push to GitLab (you cannot — SSH:8022 hangs in this session). Output the suggested push command for the user:

```bash
echo "READY TO PUSH:"
echo "  cd $(pwd)"
echo "  git push origin artem"
```

PR target: `feat/chunking-format` (per user's workflow).

---

## Self-review (skill checklist applied)

**Spec coverage:**
- S1 (subset file path under `data/pilot/scoring_subsets/`) → covered in T1.
- S2 (subset shape with free-form metadata) → T1.
- S3 (paragraph_subset config field, name not path) → T3.
- S4 (no builder script) → not implemented = correctly absent.
- S5 (consistency → `_legacy/`, existing JSONL untouched) → T2.
- S6 (FactcheckConfig.enabled = False default) → T3 + T11.
- S7 (variant subpath, factcheck outside) → T4 + T5.
- S8 (two derived artefacts, drop merged + scores.json) → T6 + T7 + T8.
- S9 (one-shot migration script) → T12 + T13 + T14.
- S10 (subset OOR hard error + soft validator warning) → T5 (hard error in dispatcher); soft validator on missing subset file deferred — keep current behaviour where FileNotFoundError surfaces at dispatch time. ✓ acceptable.

**Placeholder scan:** No TBDs; every code block contains actual implementable code. Test fixtures match the implementation shapes.

**Type consistency:** `comparison_jsonl(base, sub, run, variant)` signature consistent in paths.py (T4), scoring.py (T6), tests (T6, T9). `report_jsonl(base, sub, run, variant, judge)` consistent. `Subset(name, description, paragraph_ids)` consistent across T1, T5.

**Known fragile area** — Task 6 + 7 mention `_load_pairs_map(cfg, run)` as a helper extracted from existing `_score_run_for_judge` source/translated parsing code. The subagent executing Task 6 should first locate the current source/translated extraction in scoring.py and decide whether to (a) inline the lookup or (b) extract a helper. Either is acceptable; helper is preferred for DRY (used in 3 places: factcheck dispatch, judge dispatch, both derived builders).

---

## Execution plan summary

**Subagent-Driven (user pre-selected via "автономно через subagent driven и swarm").**

Dispatch order with parallelism hints:

- **Wave 1 (parallel)**: T1, T2, T3, T4 — 4 independent foundation tasks.
- **Wave 2 (parallel after Wave 1)**: T5 — depends on T1+T3+T4.
- **Wave 3 (parallel after T5)**: T6, T7 — comparison + reports builders.
- **Wave 4 (sequential)**: T8 → T9 → T10 → T11.
- **Wave 5 (sequential)**: T12 → T13 → T14.
- **Wave 6 (sequential)**: T15 → T16 → T17.

Total ~17 commits. Estimated wall time with parallel waves: 30-45 min for subagents + verification.
