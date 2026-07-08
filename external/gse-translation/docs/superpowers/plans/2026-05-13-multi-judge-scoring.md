# Multi-judge scoring pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor `src/palimpsest/scoring.py` into a config-driven dispatcher that runs N judge models over M translation runs with three prompt-variant strategies (legacy / consolidated / factcheck), produces per-judge raw JSONL plus one wide `merged_scores.jsonl` per run, and is verified end-to-end on a 5-paragraph smoke config.

**Architecture:** Single-stage rewrite — one module (`src/palimpsest/scoring.py`) holds the public `run_scoring(cfg: ScoringConfig)` dispatcher plus internal helpers (sentinel classifier, JSON response parser, three strategy functions, idempotent JSONL IO, merged builder, aggregator). LLM access through existing `palimpsest.llm.client.LLMClient`. Factcheck integrates via `palimpsest.factcheck.FactExtractor` + `FactOverlap`. Config via new pydantic `ScoringConfig` in `src/palimpsest/config.py`.

**Tech Stack:** Python 3.13, pydantic 2.8+, pytest 8 with `asyncio_mode = "auto"`, AsyncOpenAI/AsyncAnthropic via `LLMClient`, `pyyaml`, `typer` for CLI.

**Spec:** [docs/superpowers/specs/2026-05-13-multi-judge-scoring-design.md](../specs/2026-05-13-multi-judge-scoring-design.md)

---

## Task 1: New pydantic config models

**Files:**
- Modify: `src/palimpsest/config.py`
- Test: `tests/test_scoring_config.py` (create)

- [ ] **Step 1: Write failing tests for `JudgeConfig`, `FactcheckConfig`, `ScoringConfig`**

Create `tests/test_scoring_config.py`:

```python
from pathlib import Path

import pytest
from pydantic import ValidationError

from palimpsest.config import FactcheckConfig, JudgeConfig, ScoringConfig


def test_judge_config_minimal():
    j = JudgeConfig(model="claude-opus-4.7-low")
    assert j.model == "claude-opus-4.7-low"
    assert j.variant is None
    assert j.max_concurrency is None


def test_judge_config_with_overrides():
    j = JudgeConfig(model="qwen3.6-plus", variant="compact", max_concurrency=8)
    assert j.variant == "compact"
    assert j.max_concurrency == 8


def test_judge_config_rejects_unknown_variant():
    with pytest.raises(ValidationError):
        JudgeConfig(model="x", variant="medium")


def test_factcheck_config_defaults():
    f = FactcheckConfig()
    assert f.enabled is True
    assert f.judge == "gpt-5.4-mini-low"


def test_scoring_config_defaults_and_required():
    cfg = ScoringConfig(
        base_dir=Path("data/pilot"),
        judges=[JudgeConfig(model="claude-opus-4.7-low")],
        runs=["large/claude-opus-4.7-low_par_by_par"],
    )
    assert cfg.translations_subdir == "translating"
    assert cfg.evaluation_subdir == "evaluation"
    assert cfg.prompts_root == Path("prompts/03_scoring")
    assert cfg.prompts_variant == "full"
    assert cfg.max_concurrency == 64
    assert cfg.factcheck.enabled is True


def test_scoring_config_rejects_empty_judges():
    with pytest.raises(ValidationError):
        ScoringConfig(
            base_dir=Path("data/pilot"),
            judges=[],
            runs=["large/x"],
        )


def test_scoring_config_rejects_empty_runs():
    with pytest.raises(ValidationError):
        ScoringConfig(
            base_dir=Path("data/pilot"),
            judges=[JudgeConfig(model="x")],
            runs=[],
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_scoring_config.py -v`
Expected: `ImportError` (FactcheckConfig / JudgeConfig / ScoringConfig not defined).

- [ ] **Step 3: Implement new pydantic models in `src/palimpsest/config.py`**

Find the existing `class ScoringConfig` (`src/palimpsest/config.py:47-55`) and REPLACE it. Also delete the old `load_scoring()` function — we'll add the new loader in a later task.

```python
from typing import Literal


class JudgeConfig(BaseModel):
    """One judge entry in a ScoringConfig — model_key from configs/models.yaml."""

    model: str
    variant: Literal["old", "compact", "full"] | None = None
    max_concurrency: int | None = None


class FactcheckConfig(BaseModel):
    """Factcheck stage — single fixed judge, independent of `judges` list."""

    enabled: bool = True
    judge: str = "gpt-5.4-mini-low"


class ScoringConfig(BaseModel):
    """Stage 04 scoring pipeline configuration."""

    base_dir: Path
    translations_subdir: str = "translating"
    evaluation_subdir: str = "evaluation"
    prompts_root: Path = Path("prompts/03_scoring")
    prompts_variant: Literal["old", "compact", "full"] = "full"
    max_concurrency: int = 64
    factcheck: FactcheckConfig = FactcheckConfig()
    judges: list[JudgeConfig] = Field(..., min_length=1)
    runs: list[str] = Field(..., min_length=1)
```

Add `from pydantic import Field` to imports if not present.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_scoring_config.py -v`
Expected: all 7 tests PASS.

- [ ] **Step 5: Verify nothing else broke**

Run: `pytest tests/ -v`
Expected: all tests pass except any that depend on old `load_scoring()` — those go in Task 2. If `tests/test_config.py` references `ScoringConfig` with old fields, update them to use the new schema.

- [ ] **Step 6: Commit**

```bash
git add src/palimpsest/config.py tests/test_scoring_config.py
git commit -m "feat(config): new ScoringConfig with judges, runs, variant, factcheck"
```

---

## Task 2: Config loader for new schema

**Files:**
- Modify: `src/palimpsest/config.py`
- Test: `tests/test_scoring_config.py` (extend)

- [ ] **Step 1: Write failing test for `load_scoring(path)`**

Append to `tests/test_scoring_config.py`:

```python
def test_load_scoring_from_yaml(tmp_path):
    from palimpsest.config import load_scoring

    cfg_path = tmp_path / "scoring.yaml"
    cfg_path.write_text(
        "base_dir: data/pilot\n"
        "prompts_variant: compact\n"
        "max_concurrency: 16\n"
        "factcheck:\n"
        "  enabled: false\n"
        "  judge: gpt-5.4-mini-low\n"
        "judges:\n"
        "  - model: claude-opus-4.7-low\n"
        "  - model: qwen3.6-plus\n"
        "    variant: compact\n"
        "runs:\n"
        "  - large/claude-opus-4.7-low_par_by_par\n"
    )
    cfg = load_scoring(cfg_path)
    assert cfg.prompts_variant == "compact"
    assert cfg.max_concurrency == 16
    assert cfg.factcheck.enabled is False
    assert cfg.judges[1].variant == "compact"
    assert cfg.judges[0].variant is None
    assert cfg.runs == ["large/claude-opus-4.7-low_par_by_par"]
```

- [ ] **Step 2: Run test to verify failure**

Run: `pytest tests/test_scoring_config.py::test_load_scoring_from_yaml -v`
Expected: FAIL with `TypeError: load_scoring() missing positional argument` OR import error.

- [ ] **Step 3: Reimplement `load_scoring` in `src/palimpsest/config.py`**

The old `load_scoring()` reads `configs/scoring.yaml` from a fixed path. The new one accepts an explicit Path:

```python
def load_scoring(path: Path) -> ScoringConfig:
    """Load Stage 04 scoring config from an explicit YAML path."""
    with path.open("r", encoding="utf-8") as f:
        return ScoringConfig(**yaml.safe_load(f))
```

Make sure `from pathlib import Path` and `import yaml` are present.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_scoring_config.py -v`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/palimpsest/config.py tests/test_scoring_config.py
git commit -m "feat(config): load_scoring accepts explicit YAML path"
```

---

## Task 3: Path helpers for evaluation layout

**Files:**
- Modify: `src/palimpsest/paths.py`
- Test: `tests/test_paths_eval.py` (create)

- [ ] **Step 1: Write failing tests**

Create `tests/test_paths_eval.py`:

```python
from pathlib import Path

from palimpsest.paths import (
    evaluation_run_dir,
    judge_dir,
    criterion_jsonl,
    factcheck_dir,
    factcheck_jsonl,
    merged_jsonl,
    scores_json,
    translation_md,
)


def test_translation_md(tmp_path):
    base = tmp_path / "pilot"
    p = translation_md(base, "translating", "large/opus_par_by_par")
    assert p == base / "translating" / "large" / "opus_par_by_par" / "translation.md"


def test_evaluation_run_dir_strips_bucket(tmp_path):
    base = tmp_path / "pilot"
    p = evaluation_run_dir(base, "evaluation", "large/opus_par_by_par")
    assert p == base / "evaluation" / "opus_par_by_par"


def test_judge_dir(tmp_path):
    base = tmp_path / "pilot"
    p = judge_dir(base, "evaluation", "large/opus_par_by_par", "claude-opus-4.7-low")
    assert p == base / "evaluation" / "opus_par_by_par" / "claude-opus-4.7-low"


def test_criterion_jsonl(tmp_path):
    base = tmp_path / "pilot"
    p = criterion_jsonl(
        base, "evaluation", "large/opus_par_by_par", "claude-opus-4.7-low", "accuracy"
    )
    assert p.name == "accuracy_scores.jsonl"
    assert p.parent.name == "claude-opus-4.7-low"


def test_factcheck_dir_and_jsonl(tmp_path):
    base = tmp_path / "pilot"
    d = factcheck_dir(base, "evaluation", "large/opus_par_by_par")
    j = factcheck_jsonl(base, "evaluation", "large/opus_par_by_par")
    assert d.name == "factcheck"
    assert j == d / "factcheck_scores.jsonl"


def test_merged_and_aggregate(tmp_path):
    base = tmp_path / "pilot"
    m = merged_jsonl(base, "evaluation", "large/opus_par_by_par")
    s = scores_json(base, "evaluation")
    assert m.name == "merged_scores.jsonl"
    assert s.name == "scores.json"
    assert s == base / "evaluation" / "scores.json"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_paths_eval.py -v`
Expected: ImportError (helpers not defined).

- [ ] **Step 3: Implement helpers in `src/palimpsest/paths.py`**

Append to `src/palimpsest/paths.py`:

```python
def _split_run(run: str) -> tuple[str, str]:
    """`<bucket>/<run_name>` -> ('bucket', 'run_name'). Raises if malformed."""
    parts = run.split("/")
    if len(parts) != 2:
        raise ValueError(f"run must be '<bucket>/<run_name>', got {run!r}")
    return parts[0], parts[1]


def translation_md(base_dir: Path, translations_subdir: str, run: str) -> Path:
    """data/pilot/translating/<bucket>/<run_name>/translation.md"""
    bucket, run_name = _split_run(run)
    return base_dir / translations_subdir / bucket / run_name / "translation.md"


def evaluation_run_dir(base_dir: Path, evaluation_subdir: str, run: str) -> Path:
    """data/pilot/evaluation/<run_name>/   (bucket is dropped — run_name is unique globally)"""
    _, run_name = _split_run(run)
    return base_dir / evaluation_subdir / run_name


def judge_dir(base_dir: Path, evaluation_subdir: str, run: str, judge_slug: str) -> Path:
    return evaluation_run_dir(base_dir, evaluation_subdir, run) / judge_slug


def criterion_jsonl(
    base_dir: Path, evaluation_subdir: str, run: str, judge_slug: str, criterion: str
) -> Path:
    return judge_dir(base_dir, evaluation_subdir, run, judge_slug) / f"{criterion}_scores.jsonl"


def factcheck_dir(base_dir: Path, evaluation_subdir: str, run: str) -> Path:
    return evaluation_run_dir(base_dir, evaluation_subdir, run) / "factcheck"


def factcheck_jsonl(base_dir: Path, evaluation_subdir: str, run: str) -> Path:
    return factcheck_dir(base_dir, evaluation_subdir, run) / "factcheck_scores.jsonl"


def merged_jsonl(base_dir: Path, evaluation_subdir: str, run: str) -> Path:
    return evaluation_run_dir(base_dir, evaluation_subdir, run) / "merged_scores.jsonl"


def scores_json(base_dir: Path, evaluation_subdir: str) -> Path:
    return base_dir / evaluation_subdir / "scores.json"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_paths_eval.py -v`
Expected: all 6 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/palimpsest/paths.py tests/test_paths_eval.py
git commit -m "feat(paths): helpers for evaluation layout (judge/criterion/factcheck/merged)"
```

---

## Task 4: Sentinel classifier

**Files:**
- Modify: `src/palimpsest/scoring.py` (this is the start of the rewrite — old code stays for now)
- Test: `tests/test_scoring_sentinel.py` (create)

- [ ] **Step 1: Write failing tests**

Create `tests/test_scoring_sentinel.py`:

```python
import pytest

from palimpsest.scoring import classify_paragraph


@pytest.mark.parametrize(
    "source, expected",
    [
        ("Hello world", "normal"),
        ("* * *", "marker"),
        ("  * * *  ", "marker"),
        ("==> picture [232 x 108] <==", "marker"),
        ("PICTURE here", "marker"),
        ("[TRANSLATION FAILED]", "translation_failed"),
        ("normal text with picture word inside", "marker"),
    ],
)
def test_classify_paragraph(source: str, expected: str):
    assert classify_paragraph(source) == expected
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_scoring_sentinel.py -v`
Expected: ImportError (`classify_paragraph` not defined).

- [ ] **Step 3: Add `classify_paragraph` to `src/palimpsest/scoring.py`**

Insert at the top of the module (after imports, BEFORE the existing legacy code):

```python
from typing import Literal

ParagraphKind = Literal["normal", "marker", "translation_failed"]


def classify_paragraph(source: str) -> ParagraphKind:
    """Classify a paragraph before dispatch.

    Markers (`* * *`, `picture`) → skipped, score null.
    `[TRANSLATION FAILED]` → skipped with warning, score null.
    """
    stripped = source.strip()
    if stripped == "[TRANSLATION FAILED]":
        return "translation_failed"
    if stripped == "* * *":
        return "marker"
    if "picture" in source.lower():
        return "marker"
    return "normal"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_scoring_sentinel.py -v`
Expected: all 7 parametric cases pass.

- [ ] **Step 5: Commit**

```bash
git add src/palimpsest/scoring.py tests/test_scoring_sentinel.py
git commit -m "feat(scoring): sentinel classifier (marker / translation_failed / normal)"
```

---

## Task 5: JSON response parser

**Files:**
- Modify: `src/palimpsest/scoring.py`
- Test: `tests/test_scoring_parser.py` (create)

- [ ] **Step 1: Write failing tests**

Create `tests/test_scoring_parser.py`:

```python
from palimpsest.scoring import parse_judge_response


def test_parser_strips_markdown_fence():
    raw = '```json\n{"final_score": 7, "summary": "ok"}\n```'
    out = parse_judge_response(raw)
    assert out == {"final_score": 7, "summary": "ok"}


def test_parser_handles_bare_json():
    out = parse_judge_response('{"final_score": 8}')
    assert out == {"final_score": 8}


def test_parser_handles_prose_before_json():
    raw = 'Sure! Here is the evaluation:\n```json\n{"final_score": 6}\n```'
    out = parse_judge_response(raw)
    assert out == {"final_score": 6}


def test_parser_returns_error_sentinel_on_bad_json():
    out = parse_judge_response("not json at all")
    assert out["final_score"] == -1
    assert "not json at all" in out["llm_report"]


def test_parser_returns_error_sentinel_on_empty():
    out = parse_judge_response("")
    assert out["final_score"] == -1
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/test_scoring_parser.py -v`
Expected: ImportError.

- [ ] **Step 3: Add `parse_judge_response` to `src/palimpsest/scoring.py`**

Replace the existing `_split_llm_report` with a public, well-tested version (or add new one and delete the old one once the legacy path is rewired):

```python
import json
import re


_JSON_FENCE = re.compile(r"```json\s*(.*?)```", re.DOTALL)


def parse_judge_response(raw: str) -> dict:
    """Extract a JSON object from a judge response.

    Handles markdown ```json fences and prose before/after the JSON.
    Returns {"final_score": -1, "llm_report": <raw>} on parse failure.
    """
    if not raw or not raw.strip():
        return {"final_score": -1, "llm_report": raw or ""}
    match = _JSON_FENCE.search(raw)
    candidate = match.group(1) if match else raw
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        return {"final_score": -1, "llm_report": raw}
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_scoring_parser.py -v`
Expected: all 5 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/palimpsest/scoring.py tests/test_scoring_parser.py
git commit -m "feat(scoring): public parse_judge_response with stripped markdown fence handling"
```

---

## Task 6: Prompt loader and routing

**Files:**
- Modify: `src/palimpsest/scoring.py`
- Test: `tests/test_scoring_prompts.py` (create)

- [ ] **Step 1: Write failing tests**

Create `tests/test_scoring_prompts.py`:

```python
from pathlib import Path

import pytest

from palimpsest.scoring import LEGACY_CRITERIA, CONSOLIDATED_PROMPTS, load_prompts


@pytest.fixture
def prompts_dir(tmp_path):
    """Build a fake prompts/03_scoring tree under tmp_path."""
    root = tmp_path / "prompts" / "03_scoring"
    for variant in ("full", "compact"):
        d = root / variant
        d.mkdir(parents=True)
        (d / "faithfulness.md").write_text(f"FAITH {variant}")
        (d / "english_quality.md").write_text(f"ENG {variant}")
    old = root / "old"
    old.mkdir(parents=True)
    for c in LEGACY_CRITERIA:
        (old / f"{c}.md").write_text(f"OLD {c}")
    return root


def test_legacy_criteria_order():
    assert LEGACY_CRITERIA == [
        "accuracy",
        "terminology",
        "cultural",
        "fluency",
        "style",
        "consistency",
    ]


def test_consolidated_prompts_mapping():
    assert CONSOLIDATED_PROMPTS == {
        "faithfulness": ["accuracy", "terminology", "cultural"],
        "english_quality": ["fluency", "style", "consistency"],
    }


def test_load_prompts_full_variant(prompts_dir):
    p = load_prompts(prompts_dir, "full")
    assert p == {
        "faithfulness": "FAITH full",
        "english_quality": "ENG full",
    }


def test_load_prompts_compact_variant(prompts_dir):
    p = load_prompts(prompts_dir, "compact")
    assert p["faithfulness"] == "FAITH compact"


def test_load_prompts_old_variant(prompts_dir):
    p = load_prompts(prompts_dir, "old")
    assert set(p.keys()) == set(LEGACY_CRITERIA)
    assert p["accuracy"] == "OLD accuracy"


def test_load_prompts_missing_file_raises(prompts_dir):
    (prompts_dir / "full" / "faithfulness.md").unlink()
    with pytest.raises(FileNotFoundError):
        load_prompts(prompts_dir, "full")
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/test_scoring_prompts.py -v`
Expected: ImportError.

- [ ] **Step 3: Add `LEGACY_CRITERIA`, `CONSOLIDATED_PROMPTS`, and `load_prompts` to `src/palimpsest/scoring.py`**

```python
LEGACY_CRITERIA: list[str] = [
    "accuracy",
    "terminology",
    "cultural",
    "fluency",
    "style",
    "consistency",
]

CONSOLIDATED_PROMPTS: dict[str, list[str]] = {
    "faithfulness": ["accuracy", "terminology", "cultural"],
    "english_quality": ["fluency", "style", "consistency"],
}


def load_prompts(prompts_root: Path, variant: str) -> dict[str, str]:
    """Load prompt files for a given variant.

    variant=="old" → returns {criterion: text} for all 6 legacy criteria.
    variant=="full"|"compact" → returns {"faithfulness": ..., "english_quality": ...}.
    """
    variant_dir = prompts_root / variant
    if variant == "old":
        return {c: (variant_dir / f"{c}.md").read_text(encoding="utf-8") for c in LEGACY_CRITERIA}
    return {
        name: (variant_dir / f"{name}.md").read_text(encoding="utf-8")
        for name in CONSOLIDATED_PROMPTS
    }
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_scoring_prompts.py -v`
Expected: all 6 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/palimpsest/scoring.py tests/test_scoring_prompts.py
git commit -m "feat(scoring): prompt loader for old/compact/full variants"
```

---

## Task 7: Legacy strategy (one paragraph → 6 criterion scores)

**Files:**
- Modify: `src/palimpsest/scoring.py`
- Test: `tests/test_scoring_strategy_legacy.py` (create)

- [ ] **Step 1: Write failing test**

Create `tests/test_scoring_strategy_legacy.py`:

```python
from unittest.mock import AsyncMock

import pytest

from palimpsest.scoring import score_legacy


@pytest.fixture
def fake_client():
    c = AsyncMock()
    c.complete.return_value = '```json\n{"final_score": 8, "summary": "ok", "identified_issues": []}\n```'
    return c


async def test_score_legacy_returns_one_dict_per_criterion(fake_client):
    prompts = {c: f"PROMPT {c}" for c in [
        "accuracy", "terminology", "cultural", "fluency", "style", "consistency"
    ]}
    out = await score_legacy(fake_client, "Привет.", "Hi.", prompts)
    assert set(out.keys()) == set(prompts.keys())
    for criterion, payload in out.items():
        assert payload["final_score"] == 8
        assert payload["summary"] == "ok"


async def test_score_legacy_invokes_client_once_per_criterion(fake_client):
    prompts = {c: f"P {c}" for c in [
        "accuracy", "terminology", "cultural", "fluency", "style", "consistency"
    ]}
    await score_legacy(fake_client, "ru", "en", prompts)
    assert fake_client.complete.call_count == 6


async def test_score_legacy_propagates_parse_error():
    client = AsyncMock()
    client.complete.return_value = "this is not json"
    prompts = {"accuracy": "P"}
    out = await score_legacy(client, "ru", "en", prompts)
    assert out["accuracy"]["final_score"] == -1
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/test_scoring_strategy_legacy.py -v`
Expected: ImportError.

- [ ] **Step 3: Add `score_legacy` to `src/palimpsest/scoring.py`**

```python
import asyncio

from .llm.client import LLMClient


_USER_MSG_TEMPLATE = (
    "**Source text (Russian)** — for reference when identifying recurring "
    "elements:\n{source}\n\n**Translation (English)** — this is what you are "
    "evaluating:\n{translated}"
)


async def score_legacy(
    client: LLMClient,
    source: str,
    translated: str,
    prompts: dict[str, str],
) -> dict[str, dict]:
    """Run one paragraph through the 6 legacy single-criterion prompts.

    Returns {criterion: parsed_response_dict} for every criterion in `prompts`.
    """
    user_msg = _USER_MSG_TEMPLATE.format(source=source, translated=translated)

    async def _one(criterion: str, prompt: str) -> tuple[str, dict]:
        raw = await client.complete(system=prompt, user=user_msg)
        return criterion, parse_judge_response(raw)

    results = await asyncio.gather(*(_one(c, p) for c, p in prompts.items()))
    return dict(results)
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_scoring_strategy_legacy.py -v`
Expected: 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/palimpsest/scoring.py tests/test_scoring_strategy_legacy.py
git commit -m "feat(scoring): legacy strategy — 6 parallel LLM calls per paragraph"
```

---

## Task 8: Consolidated strategy (one paragraph → 2 LLM calls → 6 criteria routed)

**Files:**
- Modify: `src/palimpsest/scoring.py`
- Test: `tests/test_scoring_strategy_consolidated.py` (create)

- [ ] **Step 1: Write failing test**

Create `tests/test_scoring_strategy_consolidated.py`:

```python
from unittest.mock import AsyncMock

import pytest

from palimpsest.scoring import score_consolidated


def _faith_response() -> str:
    return (
        '```json\n'
        '{"accuracy":   {"final_score": 8, "summary": "a"},'
        ' "terminology":{"final_score": 7, "summary": "t"},'
        ' "cultural":   {"final_score": 9, "summary": "c"}}\n'
        '```'
    )


def _engq_response() -> str:
    return (
        '```json\n'
        '{"source_structure_note": "n",'
        ' "fluency":     {"final_score": 8, "summary": "f"},'
        ' "style":       {"final_score": 7, "summary": "s"},'
        ' "consistency": {"final_score": 6, "summary": "k"}}\n'
        '```'
    )


@pytest.fixture
def fake_client():
    c = AsyncMock()
    async def _complete(system, user, **kwargs):
        if "faithfulness" in system.lower() or "FAITH" in system:
            return _faith_response()
        return _engq_response()
    c.complete.side_effect = _complete
    return c


async def test_consolidated_makes_two_calls(fake_client):
    prompts = {"faithfulness": "FAITH text", "english_quality": "ENGQ text"}
    out = await score_consolidated(fake_client, "ru", "en", prompts)
    assert fake_client.complete.call_count == 2


async def test_consolidated_routes_all_six_criteria(fake_client):
    prompts = {"faithfulness": "FAITH text", "english_quality": "ENGQ text"}
    out = await score_consolidated(fake_client, "ru", "en", prompts)
    assert set(out.keys()) == {
        "accuracy", "terminology", "cultural", "fluency", "style", "consistency"
    }
    assert out["accuracy"]["final_score"] == 8
    assert out["consistency"]["final_score"] == 6


async def test_consolidated_marks_missing_criterion_as_minus_one():
    client = AsyncMock()
    async def _complete(system, user, **kwargs):
        if "FAITH" in system:
            return '```json\n{"accuracy": {"final_score": 8}}\n```'  # missing terminology, cultural
        return '```json\n{"fluency": {"final_score": 7}, "style": {"final_score": 7}, "consistency": {"final_score": 7}}\n```'
    client.complete.side_effect = _complete
    prompts = {"faithfulness": "FAITH text", "english_quality": "ENGQ text"}
    out = await score_consolidated(client, "ru", "en", prompts)
    assert out["accuracy"]["final_score"] == 8
    assert out["terminology"]["final_score"] == -1
    assert out["cultural"]["final_score"] == -1
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/test_scoring_strategy_consolidated.py -v`
Expected: ImportError.

- [ ] **Step 3: Add `score_consolidated` to `src/palimpsest/scoring.py`**

```python
async def score_consolidated(
    client: LLMClient,
    source: str,
    translated: str,
    prompts: dict[str, str],
) -> dict[str, dict]:
    """Run 2 consolidated prompts and route 3+3 criteria into a flat dict.

    `prompts` must contain exactly "faithfulness" and "english_quality".
    """
    user_msg = _USER_MSG_TEMPLATE.format(source=source, translated=translated)

    async def _one(prompt_name: str) -> tuple[str, dict]:
        raw = await client.complete(system=prompts[prompt_name], user=user_msg)
        return prompt_name, parse_judge_response(raw)

    pairs = await asyncio.gather(_one("faithfulness"), _one("english_quality"))
    parsed = dict(pairs)

    out: dict[str, dict] = {}
    for prompt_name, criteria in CONSOLIDATED_PROMPTS.items():
        block = parsed[prompt_name]
        for criterion in criteria:
            payload = block.get(criterion)
            if not isinstance(payload, dict):
                out[criterion] = {
                    "final_score": -1,
                    "llm_report": f"missing criterion {criterion} in {prompt_name} response",
                }
            else:
                out[criterion] = payload
    return out
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_scoring_strategy_consolidated.py -v`
Expected: 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/palimpsest/scoring.py tests/test_scoring_strategy_consolidated.py
git commit -m "feat(scoring): consolidated strategy — 2 prompts route to 6 criteria"
```

---

## Task 9: Factcheck strategy adapter

**Files:**
- Modify: `src/palimpsest/scoring.py`
- Test: `tests/test_scoring_strategy_factcheck.py` (create)

- [ ] **Step 1: Inspect factcheck API first**

Read `src/palimpsest/factcheck/__init__.py` (or wherever public exports live) to confirm the exact import path for `FactExtractor`, `FactOverlap`, and `OverlapReport`. If exports differ, adjust the imports in Step 3.

- [ ] **Step 2: Write failing test**

Create `tests/test_scoring_strategy_factcheck.py`:

```python
from unittest.mock import AsyncMock

import pytest

from palimpsest.scoring import score_factcheck


@pytest.fixture
def fake_factcheck_pipeline(monkeypatch):
    """Patch FactExtractor.run and FactOverlap.run with AsyncMock stand-ins."""
    extractor_run = AsyncMock(side_effect=[
        [{"index": 0, "text": "ru fact 1", "language": "ru"}],
        [{"index": 0, "text": "en fact 1", "language": "en"}],
    ])
    overlap_run = AsyncMock(return_value={
        "matches": [{"ru_index": 0, "en_index": 0}],
        "unmatched_ru": [],
        "unmatched_en": [],
        "precision": 1.0,
        "recall": 1.0,
        "f1": 1.0,
    })
    monkeypatch.setattr("palimpsest.scoring._extractor_run", extractor_run)
    monkeypatch.setattr("palimpsest.scoring._overlap_run", overlap_run)
    return extractor_run, overlap_run


async def test_factcheck_returns_f1_p_r(fake_factcheck_pipeline):
    client = AsyncMock()
    out = await score_factcheck(client, "Привет.", "Hi.")
    assert out["score"] == pytest.approx(1.0)
    assert out["precision"] == pytest.approx(1.0)
    assert out["recall"] == pytest.approx(1.0)
    assert "unmatched_ru" in out
    assert "unmatched_en" in out
```

- [ ] **Step 3: Add `score_factcheck` to `src/palimpsest/scoring.py`**

Open `src/palimpsest/factcheck/extractor.py` and `src/palimpsest/factcheck/overlap.py` to confirm the constructor signatures and method names. Then:

```python
from .factcheck.extractor import FactExtractor
from .factcheck.overlap import FactOverlap


# Indirection so tests can patch the call sites independently
async def _extractor_run(client: LLMClient, text: str, language: str) -> list:
    return await FactExtractor(client).run(text, language)


async def _overlap_run(client: LLMClient, facts_ru: list, facts_en: list) -> dict:
    report = await FactOverlap(client).run(facts_ru, facts_en)
    # OverlapReport is a pydantic model; convert for jsonl
    return report.model_dump() if hasattr(report, "model_dump") else dict(report)


async def score_factcheck(client: LLMClient, source: str, translated: str) -> dict:
    """Two-sided atomic-fact overlap. Returns dict ready for factcheck_scores.jsonl."""
    facts_ru, facts_en = await asyncio.gather(
        _extractor_run(client, source, "ru"),
        _extractor_run(client, translated, "en"),
    )
    report = await _overlap_run(client, facts_ru, facts_en)
    return {
        "score": report["f1"],
        "precision": report["precision"],
        "recall": report["recall"],
        "matches": report.get("matches", []),
        "unmatched_ru": report.get("unmatched_ru", []),
        "unmatched_en": report.get("unmatched_en", []),
        "llm_report": (
            f"P={report['precision']:.2f} R={report['recall']:.2f} "
            f"F1={report['f1']:.2f} |RU|={len(facts_ru)} |EN|={len(facts_en)}"
        ),
    }
```

If `FactExtractor.__init__` or `FactOverlap.__init__` requires more than `client` (e.g., `few_shot_k`, `temperature`), pass defaults from the constructor signature you saw in Step 1.

- [ ] **Step 4: Run test to verify pass**

Run: `pytest tests/test_scoring_strategy_factcheck.py -v`
Expected: 1 test passes.

- [ ] **Step 5: Commit**

```bash
git add src/palimpsest/scoring.py tests/test_scoring_strategy_factcheck.py
git commit -m "feat(scoring): factcheck strategy wrapping FactExtractor + FactOverlap"
```

---

## Task 10: Idempotent JSONL IO

**Files:**
- Modify: `src/palimpsest/scoring.py`
- Test: `tests/test_scoring_jsonl_io.py` (create)

- [ ] **Step 1: Write failing tests**

Create `tests/test_scoring_jsonl_io.py`:

```python
import json
from pathlib import Path

from palimpsest.scoring import load_existing_ids, append_jsonl_row


def test_load_existing_ids_empty_file(tmp_path):
    p = tmp_path / "x.jsonl"
    p.write_text("")
    assert load_existing_ids(p) == set()


def test_load_existing_ids_missing_file(tmp_path):
    assert load_existing_ids(tmp_path / "nope.jsonl") == set()


def test_load_existing_ids_skips_error_rows(tmp_path):
    p = tmp_path / "x.jsonl"
    p.write_text(
        json.dumps({"id": 0, "score": 8}) + "\n"
        + json.dumps({"id": 1, "score": -1}) + "\n"   # error → don't count as completed
        + json.dumps({"id": 2, "score": None}) + "\n"  # sentinel → counted (do not re-run)
    )
    assert load_existing_ids(p) == {0, 2}


def test_append_jsonl_row(tmp_path):
    p = tmp_path / "out.jsonl"
    append_jsonl_row(p, {"id": 0, "x": 1})
    append_jsonl_row(p, {"id": 1, "x": 2})
    lines = p.read_text().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["x"] == 1
    assert json.loads(lines[1])["x"] == 2


def test_append_jsonl_row_creates_parent_dir(tmp_path):
    p = tmp_path / "deep" / "nested" / "out.jsonl"
    append_jsonl_row(p, {"id": 0})
    assert p.exists()
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/test_scoring_jsonl_io.py -v`
Expected: ImportError.

- [ ] **Step 3: Add IO helpers to `src/palimpsest/scoring.py`**

```python
def load_existing_ids(path: Path) -> set[int]:
    """Return set of ids already written. Rows with score == -1 are NOT counted
    (so we retry them). Rows with score is None (sentinel skip) ARE counted."""
    if not path.exists():
        return set()
    ids: set[int] = set()
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "id" not in row:
                continue
            if row.get("score") == -1:
                continue
            ids.add(row["id"])
    return ids


def append_jsonl_row(path: Path, row: dict) -> None:
    """Append one JSON row to `path`, creating parent directories if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_scoring_jsonl_io.py -v`
Expected: 5 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/palimpsest/scoring.py tests/test_scoring_jsonl_io.py
git commit -m "feat(scoring): idempotent JSONL IO with skip-existing semantics"
```

---

## Task 11: Main dispatcher `run_scoring(cfg)`

**Files:**
- Modify: `src/palimpsest/scoring.py` (replace old `run_scoring`)
- Test: `tests/test_scoring_dispatcher.py` (create)

- [ ] **Step 1: Write failing integration test**

Create `tests/test_scoring_dispatcher.py`:

```python
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from palimpsest.config import FactcheckConfig, JudgeConfig, ScoringConfig
from palimpsest.scoring import run_scoring


@pytest.fixture
def repo_layout(tmp_path):
    """Build a fake data/pilot tree + prompts tree + translation files."""
    base = tmp_path / "pilot"
    # translating/large/run_x/translation.md
    (base / "translating" / "large" / "run_x").mkdir(parents=True)
    (base / "translating" / "large" / "run_x" / "translation.md").write_text(
        "Hi.\nWorld.\n* * *\n"
    )
    # pilot_original.md (3 lines aligned)
    (base / "pilot_original.md").write_text("Привет.\nМир.\n* * *\n")

    # prompts/03_scoring/full/{faithfulness,english_quality}.md
    pr = tmp_path / "prompts" / "03_scoring" / "full"
    pr.mkdir(parents=True)
    (pr / "faithfulness.md").write_text("FAITH_PROMPT")
    (pr / "english_quality.md").write_text("ENGQ_PROMPT")
    return base, tmp_path / "prompts"


@pytest.fixture
def mock_llm_client(monkeypatch):
    """Patch _build_client so we don't hit any real API."""
    client = AsyncMock()
    async def _complete(system, user, **kwargs):
        if "FAITH" in system:
            return (
                '```json\n'
                '{"accuracy":   {"final_score": 8, "summary": "a", "identified_issues": []},'
                ' "terminology":{"final_score": 7, "summary": "t", "identified_issues": []},'
                ' "cultural":   {"final_score": 9, "summary": "c", "identified_issues": []}}\n'
                '```'
            )
        return (
            '```json\n'
            '{"source_structure_note": "n",'
            ' "fluency":     {"final_score": 8, "summary": "f", "identified_issues": []},'
            ' "style":       {"final_score": 7, "summary": "s", "identified_issues": []},'
            ' "consistency": {"final_score": 6, "summary": "k", "identified_issues": []}}\n'
            '```'
        )
    client.complete.side_effect = _complete
    monkeypatch.setattr("palimpsest.scoring._build_client", lambda model_key: client)
    return client


async def test_dispatcher_writes_six_criterion_jsonls(repo_layout, mock_llm_client):
    base, prompts_root = repo_layout
    cfg = ScoringConfig(
        base_dir=base,
        prompts_root=prompts_root / "03_scoring",
        prompts_variant="full",
        max_concurrency=4,
        factcheck=FactcheckConfig(enabled=False),
        judges=[JudgeConfig(model="claude-opus-4.7-low")],
        runs=["large/run_x"],
    )
    await run_scoring(cfg)
    judge_dir = base / "evaluation" / "run_x" / "claude-opus-4.7-low"
    for criterion in ["accuracy", "terminology", "cultural", "fluency", "style", "consistency"]:
        assert (judge_dir / f"{criterion}_scores.jsonl").exists(), f"missing {criterion}"


async def test_dispatcher_skips_sentinel_paragraph(repo_layout, mock_llm_client):
    base, prompts_root = repo_layout
    cfg = ScoringConfig(
        base_dir=base,
        prompts_root=prompts_root / "03_scoring",
        prompts_variant="full",
        factcheck=FactcheckConfig(enabled=False),
        judges=[JudgeConfig(model="claude-opus-4.7-low")],
        runs=["large/run_x"],
    )
    await run_scoring(cfg)
    import json
    jsonl = base / "evaluation" / "run_x" / "claude-opus-4.7-low" / "accuracy_scores.jsonl"
    rows = [json.loads(line) for line in jsonl.read_text().splitlines()]
    assert len(rows) == 3
    assert rows[0]["score"] == 8
    assert rows[1]["score"] == 8
    assert rows[2]["score"] is None
    assert "marker" in rows[2]["llm_report"].lower()


async def test_dispatcher_resume_skips_existing(repo_layout, mock_llm_client):
    base, prompts_root = repo_layout
    cfg = ScoringConfig(
        base_dir=base,
        prompts_root=prompts_root / "03_scoring",
        prompts_variant="full",
        factcheck=FactcheckConfig(enabled=False),
        judges=[JudgeConfig(model="claude-opus-4.7-low")],
        runs=["large/run_x"],
    )
    await run_scoring(cfg)
    first_count = mock_llm_client.complete.call_count

    await run_scoring(cfg)   # second run — should skip everything
    assert mock_llm_client.complete.call_count == first_count
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/test_scoring_dispatcher.py -v`
Expected: ImportError or assertion failure (old `run_scoring` signature mismatch).

- [ ] **Step 3: Replace `run_scoring` in `src/palimpsest/scoring.py`**

DELETE the existing old `run_scoring(ru_md, en_md, output, max_concurrency)` function and the helper `get_completion()`. Replace with:

```python
from .config import JudgeConfig, ScoringConfig, load_models, ModelConfig
from .llm.client import LLMConfig
from .paths import (
    criterion_jsonl,
    evaluation_run_dir,
    factcheck_jsonl,
    judge_dir,
    translation_md,
)
from . import paths as _paths


def _build_client(model_key: str) -> LLMClient:
    """Build an LLMClient for a model_key in configs/models.yaml.

    Module-level indirection so tests can monkeypatch."""
    models = load_models()
    if model_key not in models:
        raise KeyError(f"model {model_key!r} not found in models.yaml")
    return LLMClient(LLMConfig.from_model_config(models[model_key]))


def _resolve_variant(judge: JudgeConfig, default: str) -> str:
    return judge.variant or default


def _judge_max_concurrency(judge: JudgeConfig, cfg: ScoringConfig) -> int:
    if judge.max_concurrency is not None:
        return judge.max_concurrency
    return max(1, cfg.max_concurrency // len(cfg.judges))


def _criteria_for_variant(variant: str) -> list[str]:
    return LEGACY_CRITERIA  # same 6 in every variant; routing handled in strategies


def _read_aligned_lines(
    ru_md: Path, en_md: Path, limit: int | None = None
) -> list[tuple[str, str]]:
    ru_lines = ru_md.read_text(encoding="utf-8").splitlines()
    en_lines = en_md.read_text(encoding="utf-8").splitlines()
    if len(ru_lines) != len(en_lines):
        raise ValueError(
            f"line-count mismatch: {ru_md.name}={len(ru_lines)} vs {en_md.name}={len(en_lines)}"
        )
    pairs = list(zip(ru_lines, en_lines))
    return pairs[:limit] if limit else pairs


async def _score_paragraph(
    *,
    client: LLMClient,
    variant: str,
    prompts: dict[str, str],
    source: str,
    translated: str,
) -> dict[str, dict]:
    if variant == "old":
        return await score_legacy(client, source, translated, prompts)
    return await score_consolidated(client, source, translated, prompts)


def _skip_payload(reason: str) -> dict:
    return {"final_score": None, "summary": "", "identified_issues": [], "llm_report": f"skipped: {reason}"}


async def _score_run_for_judge(
    *,
    cfg: ScoringConfig,
    run: str,
    judge: JudgeConfig,
    max_paragraphs: int | None = None,
) -> None:
    """Run one (run × judge) pair: produce 6 *_scores.jsonl files in judge_dir."""
    variant = _resolve_variant(judge, cfg.prompts_variant)
    prompts = load_prompts(cfg.prompts_root, variant)

    client = _build_client(judge.model)
    sem = asyncio.Semaphore(_judge_max_concurrency(judge, cfg))

    ru_md = cfg.base_dir / "pilot_original.md"
    en_md = translation_md(cfg.base_dir, cfg.translations_subdir, run)
    pairs = _read_aligned_lines(ru_md, en_md, limit=max_paragraphs)

    target_paths = {
        c: criterion_jsonl(cfg.base_dir, cfg.evaluation_subdir, run, judge.model, c)
        for c in LEGACY_CRITERIA
    }
    existing = {c: load_existing_ids(p) for c, p in target_paths.items()}

    async def _process(i: int, source: str, translated: str) -> None:
        # if every criterion already has this id, skip entirely
        if all(i in existing[c] for c in LEGACY_CRITERIA):
            return
        async with sem:
            kind = classify_paragraph(source)
            if kind == "translation_failed":
                print(f"warning: [TRANSLATION FAILED] at id={i} for {run}", flush=True)
            if kind in ("marker", "translation_failed"):
                reason = "marker" if kind == "marker" else "translation_failed"
                for criterion in LEGACY_CRITERIA:
                    if i in existing[criterion]:
                        continue
                    payload = _skip_payload(reason)
                    row = {
                        "id": i,
                        "source": source,
                        "translated": translated,
                        "judge": judge.model,
                        "variant": variant,
                        "score": None,
                        "llm_report": payload["llm_report"],
                    }
                    append_jsonl_row(target_paths[criterion], row)
                return
            results = await _score_paragraph(
                client=client, variant=variant, prompts=prompts,
                source=source, translated=translated,
            )
            for criterion, payload in results.items():
                if i in existing[criterion]:
                    continue
                row = {
                    "id": i,
                    "source": source,
                    "translated": translated,
                    "judge": judge.model,
                    "variant": variant,
                    "score": payload.get("final_score"),
                    "llm_report": json.dumps(payload, ensure_ascii=False),
                }
                append_jsonl_row(target_paths[criterion], row)

    await asyncio.gather(*(_process(i, ru, en) for i, (ru, en) in enumerate(pairs)))

    # meta.json with prompt snapshot
    meta = {
        "judge": judge.model,
        "variant": variant,
        "prompts": prompts,
    }
    (judge_dir(cfg.base_dir, cfg.evaluation_subdir, run, judge.model) / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2)
    )


async def _score_factcheck_for_run(
    *,
    cfg: ScoringConfig,
    run: str,
    max_paragraphs: int | None = None,
) -> None:
    if not cfg.factcheck.enabled:
        return
    client = _build_client(cfg.factcheck.judge)
    sem = asyncio.Semaphore(cfg.max_concurrency)

    ru_md = cfg.base_dir / "pilot_original.md"
    en_md = translation_md(cfg.base_dir, cfg.translations_subdir, run)
    pairs = _read_aligned_lines(ru_md, en_md, limit=max_paragraphs)

    target = factcheck_jsonl(cfg.base_dir, cfg.evaluation_subdir, run)
    existing = load_existing_ids(target)

    async def _process(i: int, source: str, translated: str) -> None:
        if i in existing:
            return
        async with sem:
            kind = classify_paragraph(source)
            if kind in ("marker", "translation_failed"):
                row = {
                    "id": i, "source": source, "translated": translated,
                    "score": None, "llm_report": f"skipped: {kind}",
                }
            else:
                fc = await score_factcheck(client, source, translated)
                row = {"id": i, "source": source, "translated": translated, **fc}
            append_jsonl_row(target, row)

    await asyncio.gather(*(_process(i, ru, en) for i, (ru, en) in enumerate(pairs)))


async def run_scoring(cfg: ScoringConfig, *, max_paragraphs: int | None = None) -> None:
    """Main entry. Orchestrates all (run × judge) pairs + factcheck."""
    tasks = []
    labels: list[str] = []
    for run in cfg.runs:
        for judge in cfg.judges:
            tasks.append(
                _score_run_for_judge(cfg=cfg, run=run, judge=judge, max_paragraphs=max_paragraphs)
            )
            labels.append(f"{run} × {judge.model}")
        tasks.append(
            _score_factcheck_for_run(cfg=cfg, run=run, max_paragraphs=max_paragraphs)
        )
        labels.append(f"{run} × factcheck")
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for label, result in zip(labels, results):
        if isinstance(result, Exception):
            print(f"warning: task failed: {label}: {result!r}", flush=True)
```

Also wrap `_process` body inside `_score_run_for_judge` with try/except so per-paragraph errors don't propagate:

```python
        async with sem:
            try:
                # ... existing body (classify, _score_paragraph, write rows) ...
            except Exception as exc:
                print(f"warning: paragraph {i} failed for {judge.model}: {exc!r}", flush=True)
                for criterion in LEGACY_CRITERIA:
                    if i in existing[criterion]:
                        continue
                    row = {
                        "id": i, "source": source, "translated": translated,
                        "judge": judge.model, "variant": variant,
                        "score": -1, "llm_report": f"exception: {exc!r}",
                    }
                    append_jsonl_row(target_paths[criterion], row)
```

And before writing `meta.json`, ensure the directory exists:

```python
    j_dir = judge_dir(cfg.base_dir, cfg.evaluation_subdir, run, judge.model)
    j_dir.mkdir(parents=True, exist_ok=True)
    (j_dir / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2)
    )
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_scoring_dispatcher.py -v`
Expected: 3 tests pass.

- [ ] **Step 5: Run full test suite**

Run: `pytest tests/ -v`
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/palimpsest/scoring.py tests/test_scoring_dispatcher.py
git commit -m "feat(scoring): config-driven dispatcher for judges x runs x paragraphs"
```

---

## Task 12: Merged builder (`merged_scores.jsonl`)

**Files:**
- Modify: `src/palimpsest/scoring.py`
- Test: `tests/test_scoring_merged.py` (create)

- [ ] **Step 1: Write failing test**

Create `tests/test_scoring_merged.py`:

```python
import json
from pathlib import Path

from palimpsest.scoring import build_merged_jsonl


def _write_jsonl(p: Path, rows: list[dict]) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n")


def test_merged_aggregates_two_judges(tmp_path):
    run_dir = tmp_path / "run_x"
    # Judge A
    for c, score in [("accuracy", 8), ("terminology", 7), ("cultural", 9),
                     ("fluency", 8), ("style", 7), ("consistency", 6)]:
        _write_jsonl(run_dir / "judge_a" / f"{c}_scores.jsonl", [
            {"id": 0, "source": "ru", "translated": "en", "score": score, "llm_report": "..."},
        ])
    # Judge B
    for c, score in [("accuracy", 7), ("terminology", 8), ("cultural", 8),
                     ("fluency", 9), ("style", 8), ("consistency", 7)]:
        _write_jsonl(run_dir / "judge_b" / f"{c}_scores.jsonl", [
            {"id": 0, "source": "ru", "translated": "en", "score": score, "llm_report": "..."},
        ])
    build_merged_jsonl(run_dir, judges=["judge_a", "judge_b"], include_factcheck=False)
    merged = run_dir / "merged_scores.jsonl"
    rows = [json.loads(l) for l in merged.read_text().splitlines()]
    assert len(rows) == 1
    r = rows[0]
    assert r["id"] == 0
    assert r["accuracy"]["by_judge"] == {"judge_a": 8, "judge_b": 7}
    assert r["accuracy"]["avg"] == 7.5
    assert r["consistency"]["by_judge"] == {"judge_a": 6, "judge_b": 7}


def test_merged_excludes_minus_one_and_null(tmp_path):
    run_dir = tmp_path / "run_x"
    for c in ["accuracy", "terminology", "cultural", "fluency", "style", "consistency"]:
        _write_jsonl(run_dir / "judge_a" / f"{c}_scores.jsonl", [
            {"id": 0, "source": "ru", "translated": "en", "score": -1, "llm_report": "err"},
        ])
        _write_jsonl(run_dir / "judge_b" / f"{c}_scores.jsonl", [
            {"id": 0, "source": "ru", "translated": "en", "score": 8, "llm_report": "ok"},
        ])
    build_merged_jsonl(run_dir, judges=["judge_a", "judge_b"], include_factcheck=False)
    rows = [json.loads(l) for l in (run_dir / "merged_scores.jsonl").read_text().splitlines()]
    assert rows[0]["accuracy"]["avg"] == 8.0
    assert "judge_a" not in rows[0]["accuracy"]["by_judge"]
    assert rows[0]["accuracy"]["by_judge"]["judge_b"] == 8


def test_merged_includes_factcheck(tmp_path):
    run_dir = tmp_path / "run_x"
    for c in ["accuracy", "terminology", "cultural", "fluency", "style", "consistency"]:
        _write_jsonl(run_dir / "judge_a" / f"{c}_scores.jsonl", [
            {"id": 0, "source": "ru", "translated": "en", "score": 8, "llm_report": "ok"},
        ])
    _write_jsonl(run_dir / "factcheck" / "factcheck_scores.jsonl", [
        {"id": 0, "source": "ru", "translated": "en", "score": 0.85,
         "precision": 0.9, "recall": 0.8, "llm_report": "..."},
    ])
    build_merged_jsonl(run_dir, judges=["judge_a"], include_factcheck=True, factcheck_judge="gpt-x")
    rows = [json.loads(l) for l in (run_dir / "merged_scores.jsonl").read_text().splitlines()]
    fc = rows[0]["factcheck"]
    assert fc["f1"] == 0.85
    assert fc["judge"] == "gpt-x"
    assert fc["p"] == 0.9
```

- [ ] **Step 2: Run test to verify failure**

Run: `pytest tests/test_scoring_merged.py -v`
Expected: ImportError.

- [ ] **Step 3: Add `build_merged_jsonl` to `src/palimpsest/scoring.py`**

```python
def _read_jsonl(path: Path) -> dict[int, dict]:
    """Read a JSONL file into a {id: row} dict. Returns {} if missing."""
    if not path.exists():
        return {}
    out: dict[int, dict] = {}
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "id" in row:
                out[row["id"]] = row
    return out


def _avg_excluding_nulls(values: list) -> float | None:
    valid = [v for v in values if v is not None and v != -1]
    if not valid:
        return None
    return sum(valid) / len(valid)


def build_merged_jsonl(
    run_dir: Path,
    *,
    judges: list[str],
    include_factcheck: bool,
    factcheck_judge: str | None = None,
) -> None:
    """Build run_dir/merged_scores.jsonl from per-judge JSONLs."""
    # collect per-judge per-criterion data: {criterion: {judge: {id: row}}}
    by_criterion: dict[str, dict[str, dict[int, dict]]] = {
        c: {j: _read_jsonl(run_dir / j / f"{c}_scores.jsonl") for j in judges}
        for c in LEGACY_CRITERIA
    }
    factcheck_rows: dict[int, dict] = {}
    if include_factcheck:
        factcheck_rows = _read_jsonl(run_dir / "factcheck" / "factcheck_scores.jsonl")

    # union of all paragraph ids seen
    all_ids = set()
    for c_data in by_criterion.values():
        for j_rows in c_data.values():
            all_ids.update(j_rows.keys())
    all_ids.update(factcheck_rows.keys())

    out_path = run_dir / "merged_scores.jsonl"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # write fresh — merged is always rebuilt
    with out_path.open("w", encoding="utf-8") as f:
        for i in sorted(all_ids):
            row: dict = {"id": i}
            source = None
            translated = None
            for criterion in LEGACY_CRITERIA:
                by_judge: dict[str, int | float | None] = {}
                for j in judges:
                    j_rows = by_criterion[criterion].get(j, {})
                    if i not in j_rows:
                        continue
                    sample = j_rows[i]
                    source = source or sample.get("source")
                    translated = translated or sample.get("translated")
                    s = sample.get("score")
                    if s != -1:  # skip parse errors from `by_judge`
                        by_judge[j] = s
                row[criterion] = {
                    "avg": _avg_excluding_nulls(list(by_judge.values())),
                    "by_judge": by_judge,
                }
            if include_factcheck and i in factcheck_rows:
                fc = factcheck_rows[i]
                row["factcheck"] = {
                    "f1": fc.get("score"),
                    "p": fc.get("precision"),
                    "r": fc.get("recall"),
                    "judge": factcheck_judge,
                }
            if source is not None:
                row["source"] = source
            if translated is not None:
                row["translated"] = translated
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_scoring_merged.py -v`
Expected: 3 tests pass.

- [ ] **Step 5: Wire `build_merged_jsonl` into `run_scoring`**

In `src/palimpsest/scoring.py`, modify `run_scoring` to call `build_merged_jsonl` after all per-judge JSONLs are written:

```python
async def run_scoring(cfg: ScoringConfig, *, max_paragraphs: int | None = None) -> None:
    """Main entry. Orchestrates all (run × judge) pairs + factcheck + merge."""
    tasks = []
    labels: list[str] = []
    for run in cfg.runs:
        for judge in cfg.judges:
            tasks.append(
                _score_run_for_judge(cfg=cfg, run=run, judge=judge, max_paragraphs=max_paragraphs)
            )
            labels.append(f"{run} × {judge.model}")
        tasks.append(
            _score_factcheck_for_run(cfg=cfg, run=run, max_paragraphs=max_paragraphs)
        )
        labels.append(f"{run} × factcheck")
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for label, result in zip(labels, results):
        if isinstance(result, Exception):
            print(f"warning: task failed: {label}: {result!r}", flush=True)

    # Rebuild merged_scores.jsonl per run
    for run in cfg.runs:
        run_dir = evaluation_run_dir(cfg.base_dir, cfg.evaluation_subdir, run)
        build_merged_jsonl(
            run_dir,
            judges=[j.model for j in cfg.judges],
            include_factcheck=cfg.factcheck.enabled,
            factcheck_judge=cfg.factcheck.judge if cfg.factcheck.enabled else None,
        )
```

- [ ] **Step 6: Run dispatcher tests to verify merged is built**

Add to `tests/test_scoring_dispatcher.py`:

```python
async def test_dispatcher_builds_merged_jsonl(repo_layout, mock_llm_client):
    base, prompts_root = repo_layout
    cfg = ScoringConfig(
        base_dir=base,
        prompts_root=prompts_root / "03_scoring",
        prompts_variant="full",
        factcheck=FactcheckConfig(enabled=False),
        judges=[JudgeConfig(model="claude-opus-4.7-low")],
        runs=["large/run_x"],
    )
    await run_scoring(cfg)
    merged = base / "evaluation" / "run_x" / "merged_scores.jsonl"
    assert merged.exists()
    rows = [json.loads(l) for l in merged.read_text().splitlines()]
    assert len(rows) == 3
    assert rows[0]["accuracy"]["by_judge"] == {"claude-opus-4.7-low": 8}
```

Add `import json` at the top of the file.

Run: `pytest tests/test_scoring_dispatcher.py -v`
Expected: all 4 tests pass.

- [ ] **Step 7: Commit**

```bash
git add src/palimpsest/scoring.py tests/test_scoring_merged.py tests/test_scoring_dispatcher.py
git commit -m "feat(scoring): build merged_scores.jsonl after dispatch"
```

---

## Task 13: `scores.json` aggregator

**Files:**
- Modify: `src/palimpsest/scoring.py`
- Test: `tests/test_scoring_aggregate.py` (create)

- [ ] **Step 1: Write failing test**

Create `tests/test_scoring_aggregate.py`:

```python
import json
from pathlib import Path

from palimpsest.scoring import build_aggregate_scores


def _write_merged(run_dir: Path, rows: list[dict]) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "merged_scores.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")


def test_aggregate_two_runs(tmp_path):
    eval_dir = tmp_path / "evaluation"
    _write_merged(eval_dir / "run_a", [
        {"id": 0, "accuracy": {"avg": 8.0, "by_judge": {"j1": 8}},
         "terminology": {"avg": 7.0, "by_judge": {"j1": 7}},
         "cultural": {"avg": 9.0, "by_judge": {"j1": 9}},
         "fluency": {"avg": 8.0, "by_judge": {"j1": 8}},
         "style": {"avg": 7.0, "by_judge": {"j1": 7}},
         "consistency": {"avg": 6.0, "by_judge": {"j1": 6}}},
        {"id": 1, "accuracy": {"avg": 6.0, "by_judge": {"j1": 6}},
         "terminology": {"avg": 7.0, "by_judge": {"j1": 7}},
         "cultural": {"avg": 9.0, "by_judge": {"j1": 9}},
         "fluency": {"avg": 8.0, "by_judge": {"j1": 8}},
         "style": {"avg": 7.0, "by_judge": {"j1": 7}},
         "consistency": {"avg": 6.0, "by_judge": {"j1": 6}}},
    ])
    build_aggregate_scores(
        eval_dir,
        run_to_path={"large/run_a": "run_a"},
        judges=["j1"],
        include_factcheck=False,
    )
    out = json.loads((eval_dir / "scores.json").read_text())
    assert "large/run_a" in out
    assert out["large/run_a"]["accuracy"]["avg"] == 7.0
    assert out["large/run_a"]["accuracy"]["by_judge"]["j1"] == 7.0
```

- [ ] **Step 2: Run test to verify failure**

Run: `pytest tests/test_scoring_aggregate.py -v`
Expected: ImportError.

- [ ] **Step 3: Add `build_aggregate_scores` to `src/palimpsest/scoring.py`**

```python
def build_aggregate_scores(
    evaluation_dir: Path,
    *,
    run_to_path: dict[str, str],
    judges: list[str],
    include_factcheck: bool,
) -> None:
    """Build evaluation_dir/scores.json by averaging merged_scores.jsonl per run.

    `run_to_path` maps `<bucket>/<run_name>` -> `<run_name>` (the on-disk dir).
    Existing scores.json is loaded; runs in `run_to_path` are overwritten.
    """
    out_path = evaluation_dir / "scores.json"
    if out_path.exists():
        existing = json.loads(out_path.read_text(encoding="utf-8"))
    else:
        existing = {}

    for full_run_key, run_dirname in run_to_path.items():
        merged = evaluation_dir / run_dirname / "merged_scores.jsonl"
        if not merged.exists():
            continue
        rows = []
        for line in merged.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                rows.append(json.loads(line))
        if not rows:
            continue

        run_summary: dict = {}
        for criterion in LEGACY_CRITERIA:
            avg_values = [r[criterion]["avg"] for r in rows if r.get(criterion, {}).get("avg") is not None]
            by_judge: dict[str, list] = {j: [] for j in judges}
            for r in rows:
                for j in judges:
                    s = r.get(criterion, {}).get("by_judge", {}).get(j)
                    if s is not None and s != -1:
                        by_judge[j].append(s)
            run_summary[criterion] = {
                "avg": (sum(avg_values) / len(avg_values)) if avg_values else None,
                "by_judge": {j: (sum(v)/len(v) if v else None) for j, v in by_judge.items()},
            }
        if include_factcheck:
            f1s = [r["factcheck"]["f1"] for r in rows if r.get("factcheck", {}).get("f1") is not None]
            run_summary["factcheck"] = {"f1_avg": (sum(f1s) / len(f1s)) if f1s else None}
        existing[full_run_key] = run_summary

    out_path.write_text(json.dumps(existing, ensure_ascii=False, indent=2))
```

- [ ] **Step 4: Run test to verify pass**

Run: `pytest tests/test_scoring_aggregate.py -v`
Expected: 1 test passes.

- [ ] **Step 5: Wire into `run_scoring`**

Update `run_scoring` to call `build_aggregate_scores` at the end:

```python
async def run_scoring(cfg: ScoringConfig, *, max_paragraphs: int | None = None) -> None:
    # ... existing dispatch + per-run merged build ...

    # Top-level aggregate
    run_to_path = {}
    for run in cfg.runs:
        _, run_name = run.split("/")
        run_to_path[run] = run_name
    build_aggregate_scores(
        cfg.base_dir / cfg.evaluation_subdir,
        run_to_path=run_to_path,
        judges=[j.model for j in cfg.judges],
        include_factcheck=cfg.factcheck.enabled,
    )
```

- [ ] **Step 6: Run all tests to confirm**

Run: `pytest tests/ -v`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add src/palimpsest/scoring.py tests/test_scoring_aggregate.py
git commit -m "feat(scoring): build top-level scores.json aggregate"
```

---

## Task 14: CLI script rewrite

**Files:**
- Modify: `scripts/03_translation_scoring.py`
- Test: manual smoke test

- [ ] **Step 1: Rewrite `scripts/03_translation_scoring.py`**

REPLACE the entire file with:

```python
"""Stage 04 scoring CLI: run multi-judge evaluation from a YAML config."""

from __future__ import annotations

import asyncio
from pathlib import Path

import typer

from palimpsest.config import load_scoring
from palimpsest.scoring import run_scoring

app = typer.Typer(add_completion=False)


@app.command()
def main(
    config: Path = typer.Option(..., "--config", "-c", help="Path to scoring config YAML."),
    force: bool = typer.Option(False, "--force", help="Re-run paragraphs that already have non-error rows."),
    max_paragraphs: int = typer.Option(
        0, "--max-paragraphs", "-n",
        help="If > 0, score only the first N paragraphs of every run (smoke).",
    ),
) -> None:
    """Run multi-judge scoring as defined in CONFIG."""
    cfg = load_scoring(config)
    if force:
        # Wipe JSONL outputs in the relevant evaluation paths.
        # User opted-in explicitly; idempotent skip behavior is the default.
        from palimpsest.paths import evaluation_run_dir
        for run in cfg.runs:
            d = evaluation_run_dir(cfg.base_dir, cfg.evaluation_subdir, run)
            if d.exists():
                for jsonl in d.rglob("*.jsonl"):
                    jsonl.unlink()
    asyncio.run(run_scoring(cfg, max_paragraphs=max_paragraphs or None))
    typer.echo(f"Done. Outputs in {cfg.base_dir / cfg.evaluation_subdir}")


if __name__ == "__main__":
    app()
```

- [ ] **Step 2: Verify import works**

Run: `python -c "from scripts.03_translation_scoring import app; print(app)"`

(Likely fails because of the leading-digit module name. The fix: invoke as `python scripts/03_translation_scoring.py --help` instead.)

Run: `python scripts/03_translation_scoring.py --help`
Expected: typer prints usage with `--config` and `--force`.

- [ ] **Step 3: Commit**

```bash
git add scripts/03_translation_scoring.py
git commit -m "feat(scripts): rewrite scoring CLI to load config and dispatch"
```

---

## Task 15: Scoring config files (smoke / large-low / small-low)

**Files:**
- Create: `configs/scoring/smoke.yaml`
- Create: `configs/scoring/large-low.yaml`
- Create: `configs/scoring/small-low.yaml`
- Delete: `configs/scoring.yaml` (old, broken)

- [ ] **Step 1: Create `configs/scoring/smoke.yaml`**

```yaml
# Smoke config: 1 run x 1 judge x compact variant, factcheck off.
# Used for end-to-end validation before final runs.
base_dir: data/pilot
prompts_variant: compact
max_concurrency: 8
factcheck:
  enabled: false
judges:
  - model: claude-haiku-4.5
runs:
  - large/claude-opus-4.7-low_par_by_par
```

- [ ] **Step 2: Create `configs/scoring/large-low.yaml`**

```yaml
# Large-low profile: 3 large judges in -low effort, full variant prompts.
base_dir: data/pilot
prompts_variant: full
max_concurrency: 32
factcheck:
  enabled: true
  judge: gpt-5.4-mini-low
judges:
  - model: claude-opus-4.7-low
  - model: gemini-3.1-pro-low
  - model: gpt-5.5-low
runs:
  - large/claude-opus-4.7-low_par_by_par
  - large/gpt-5.5-low_par_by_par
  - large/gemini-3.1-pro-low_par_by_par
```

- [ ] **Step 3: Create `configs/scoring/small-low.yaml`**

```yaml
# Small-low profile: 3 small judges in -low effort, compact variant prompts.
base_dir: data/pilot
prompts_variant: compact
max_concurrency: 32
factcheck:
  enabled: true
  judge: gpt-5.4-mini-low
judges:
  - model: claude-sonnet-4.6-low
  - model: gemini-3.1-flash-lite-low
  - model: gpt-5.4-mini-low
runs:
  - small/claude-haiku-4.5_par_by_par
  - small/gemini-3.1-flash-lite-low_par_by_par
  - small/gpt-5.4-mini-low_par_by_par
  - small/qwen3.6-flash_par_by_par
```

- [ ] **Step 4: Delete old `configs/scoring.yaml`**

```bash
rm configs/scoring.yaml
```

- [ ] **Step 5: Verify pydantic parses each new config**

```bash
python -c "
from pathlib import Path
from palimpsest.config import load_scoring
for name in ['smoke', 'large-low', 'small-low']:
    cfg = load_scoring(Path(f'configs/scoring/{name}.yaml'))
    print(name, '->', len(cfg.judges), 'judges,', len(cfg.runs), 'runs')
"
```

Expected output:
```
smoke -> 1 judges, 1 runs
large-low -> 3 judges, 3 runs
small-low -> 3 judges, 4 runs
```

- [ ] **Step 6: Commit**

```bash
git add configs/scoring/ -A
git rm configs/scoring.yaml
git commit -m "feat(configs): scoring profiles (smoke, large-low, small-low); drop legacy yaml"
```

---

## Task 16: End-to-end smoke validation

**Files:**
- Manual run + verification

- [ ] **Step 1: Confirm prerequisites**

Make sure `OPENROUTER_API_KEY` is set in `.env` (the smoke config uses `claude-haiku-4.5` via OpenRouter):

```bash
grep -E "^OPENROUTER_API_KEY=" .env > /dev/null && echo "key present" || echo "MISSING — abort"
```

Expected: `key present`. If missing, ask the user — do not commit a key.

- [ ] **Step 2: Check that the run referenced in smoke config actually exists**

```bash
ls data/pilot/translating/large/claude-opus-4.7-low_par_by_par/translation.md
```

Expected: file exists. If not, replace the `runs:` entry in `configs/scoring/smoke.yaml` with an existing run (check `find data/pilot/translating -maxdepth 2 -mindepth 2 -type d`).

- [ ] **Step 3: Run smoke (limit to 5 paragraphs via temporary script edit OR honour the spec by full run)**

The spec mentions `--max-paragraphs 5` but we didn't add that flag (YAGNI — single-judge smoke is fast). Run it whole:

```bash
python scripts/03_translation_scoring.py --config configs/scoring/smoke.yaml
```

Expected:
- Prints `Done. Outputs in data/pilot/evaluation`.
- Completes in <2 minutes (1 judge × 1 run × ~549 paragraphs × 2 LLM calls ≈ 1100 calls at high concurrency).

If completion takes much longer, narrow the smoke to fewer paragraphs by adding a `--max-paragraphs` typer option to the script.

- [ ] **Step 4: Inspect the output layout**

```bash
find data/pilot/evaluation/claude-opus-4.7-low_par_by_par -maxdepth 3
```

Expected:
```
data/pilot/evaluation/claude-opus-4.7-low_par_by_par
data/pilot/evaluation/claude-opus-4.7-low_par_by_par/claude-haiku-4.5
data/pilot/evaluation/claude-opus-4.7-low_par_by_par/claude-haiku-4.5/accuracy_scores.jsonl
data/pilot/evaluation/claude-opus-4.7-low_par_by_par/claude-haiku-4.5/terminology_scores.jsonl
data/pilot/evaluation/claude-opus-4.7-low_par_by_par/claude-haiku-4.5/cultural_scores.jsonl
data/pilot/evaluation/claude-opus-4.7-low_par_by_par/claude-haiku-4.5/fluency_scores.jsonl
data/pilot/evaluation/claude-opus-4.7-low_par_by_par/claude-haiku-4.5/style_scores.jsonl
data/pilot/evaluation/claude-opus-4.7-low_par_by_par/claude-haiku-4.5/consistency_scores.jsonl
data/pilot/evaluation/claude-opus-4.7-low_par_by_par/claude-haiku-4.5/meta.json
data/pilot/evaluation/claude-opus-4.7-low_par_by_par/merged_scores.jsonl
data/pilot/evaluation/scores.json
```

- [ ] **Step 5: Inspect one row of merged_scores.jsonl**

```bash
head -3 data/pilot/evaluation/claude-opus-4.7-low_par_by_par/merged_scores.jsonl | python -m json.tool --json-lines
```

Expected: each row has `id`, `source`, `translated`, and 6 criterion objects with `avg` + `by_judge: {"claude-haiku-4.5": <int>}`. No `factcheck` field (smoke disabled it).

- [ ] **Step 6: Confirm resume is idempotent**

Run the smoke a second time:

```bash
python scripts/03_translation_scoring.py --config configs/scoring/smoke.yaml
```

Expected: completes in seconds (all paragraphs already in JSONLs, no new LLM calls). File contents should be identical (sizes unchanged).

```bash
md5sum data/pilot/evaluation/claude-opus-4.7-low_par_by_par/claude-haiku-4.5/accuracy_scores.jsonl
```

Compare with the post-Step-3 hash; should match.

- [ ] **Step 7: Commit smoke artifacts opt-in**

Smoke output goes under `data/pilot/evaluation/` which is LFS-tracked. Do NOT auto-commit. Ask the user if they want to keep these artifacts:

```bash
git status data/pilot/evaluation/
```

If user says keep: `git add data/pilot/evaluation/ && git commit -m "data(eval): smoke run output for claude-opus-4.7-low_par_by_par × claude-haiku-4.5"`.
If user says discard: `git checkout -- data/pilot/evaluation/` (or `rm -r` the specific subdir).

---

## Task 17: Documentation sync

**Files:**
- Create: `docs/stages/03_scoring.md`
- Modify: `docs/pilot_interfaces_agreement.md`

- [ ] **Step 1: Check whether stage doc already exists**

```bash
ls docs/stages/
```

If `03_scoring.md` exists, modify in place. If not, create it.

- [ ] **Step 2: Write `docs/stages/03_scoring.md`** (or update existing)

```markdown
# Stage 04 — Scoring (Оценка)

Up-link: [docs/pipeline.md](../pipeline.md). Контракт путей: [pilot_interfaces_agreement.md](../pilot_interfaces_agreement.md).

## Purpose

Оценить переводы из Stage 03 одновременно несколькими LLM-судьями. На один параграф — 2 консолидированных промпта (faithfulness, english_quality) на каждого судью плюс один factcheck-вызов фиксированной моделью.

## Design decisions

- **Config-driven**: список судей, список run'ов, вариант промптов (`old`/`compact`/`full`), параметры factcheck'а — всё в YAML. CLI вызывает `palimpsest.scoring.run_scoring(cfg)`.
- **Output layout**: `evaluation/<run_name>/<judge>/<criterion>_scores.jsonl` (сырые, idempotent) + `merged_scores.jsonl` (сводный per-paragraph) + `evaluation/scores.json` (top-level агрегат).
- **Idempotent resume**: повторный запуск пропускает `id`'ы, уже записанные в JSONL (кроме `score == -1`).
- **Sentinel handling**: `* * *` / `picture` / `[TRANSLATION FAILED]` → skip, `score: null`, в average не идут.
- **Factcheck**: отдельный шаг с одной фиксированной моделью (default `gpt-5.4-mini-low`); промпты живут в `src/palimpsest/factcheck/`.

## Interface

```python
from palimpsest.config import load_scoring
from palimpsest.scoring import run_scoring

cfg = load_scoring(Path("configs/scoring/large-low.yaml"))
await run_scoring(cfg)
```

CLI:

```bash
python scripts/03_translation_scoring.py --config configs/scoring/large-low.yaml
python scripts/03_translation_scoring.py --config configs/scoring/large-low.yaml --force
```

## Subtleties

- `merged_scores.jsonl` всегда пересобирается из сырых JSONL — это derived view.
- `scores.json` мёрджится: при перезапуске только указанные в config'е runs обновляются; остальные ключи сохраняются.
- Промпты `prompts/03_scoring/{full,compact}/{faithfulness,english_quality}.md` возвращают JSON с 3 блоками `criteria_assessment` — диспатчер раскладывает их по 3 criterion-JSONL.
- При переходе на `prompts_variant: old` — диспатчер вызывает 6 промптов из `prompts/03_scoring/old/<criterion>.md`.

## Status

Реализован. Smoke на `configs/scoring/smoke.yaml` зелёный.
```

- [ ] **Step 3: Update `docs/pilot_interfaces_agreement.md`**

Find the section under `## 03 Оценка` → `### data/pilot/evaluation/<run_name>/<criterion>_scores.jsonl` (around `docs/pilot_interfaces_agreement.md:236`).

REPLACE the existing path text and example block to reflect the new judge-nested layout. Specifically update:

```
### `data/pilot/evaluation/<run_name>/<criterion>_scores.jsonl`
```

to:

```
### `data/pilot/evaluation/<run_name>/<judge>/<criterion>_scores.jsonl`

Сырые per-judge оценки. Один файл на каждую пару (judge, criterion). Каждая строка:

```json
{"id": 0, "source": "...", "translated": "...",
 "judge": "claude-opus-4.7-low", "variant": "full",
 "score": 8, "llm_report": "...markdown report..."}
```

`score`: целое от 0 до 10 для 6 промптовых критериев, F1 (float 0..1) для factcheck. Значения `null` (sentinel skip) и `-1` (ошибка парсинга/LLM) исключаются из средних.

### `data/pilot/evaluation/<run_name>/merged_scores.jsonl`

Сводная per-paragraph wide-форма (все судьи в `by_judge`, плюс factcheck). Пересобирается из сырых JSONL после каждого прогона. Пример строки:

```json
{
  "id": 0, "source": "...", "translated": "...",
  "accuracy": {"avg": 7.5, "by_judge": {"claude-opus-4.7-low": 8, "gpt-5.5-low": 7}},
  "terminology": {...}, ..., "consistency": {...},
  "factcheck": {"f1": 0.91, "p": 0.95, "r": 0.87, "judge": "gpt-5.4-mini-low"}
}
```
```

- [ ] **Step 4: Update `scores.json` schema in the same doc**

Find the `### data/pilot/evaluation/scores.json` section (around `docs/pilot_interfaces_agreement.md:252`). REPLACE the JSON example block:

```json
{
  "large/claude-opus-4.7-low_par_by_par": {
    "accuracy":    {"avg": 7.6, "by_judge": {"claude-opus-4.7-low": 7.5, "gemini-3.1-pro-low": 7.4, "gpt-5.5-low": 7.9}},
    "terminology": {"avg": 8.0, "by_judge": {...}},
    "cultural":    {"avg": 7.2, "by_judge": {...}},
    "fluency":     {"avg": 8.4, "by_judge": {...}},
    "style":       {"avg": 7.8, "by_judge": {...}},
    "consistency": {"avg": 7.6, "by_judge": {...}},
    "factcheck":   {"f1_avg": 0.89}
  }
}
```

Ключ — `<bucket>/<run_name>`. По-судейные средние внутри `by_judge`. `factcheck.f1_avg` — среднее F1 по параграфам run'а от factcheck-judge'а.

- [ ] **Step 5: Update dirtree in `Общие соглашения` section of the same doc**

Find the `evaluation/` block in the tree (around `docs/pilot_interfaces_agreement.md:35-44`):

```
└── evaluation/
    ├── <run_name>/
    │   ├── accuracy_scores.jsonl
    │   ├── ...
    │   └── factcheck_scores.jsonl
    └── scores.json
```

REPLACE with:

```
└── evaluation/
    ├── <run_name>/
    │   ├── <judge>/
    │   │   ├── accuracy_scores.jsonl
    │   │   ├── terminology_scores.jsonl
    │   │   ├── cultural_scores.jsonl
    │   │   ├── fluency_scores.jsonl
    │   │   ├── style_scores.jsonl
    │   │   ├── consistency_scores.jsonl
    │   │   └── meta.json
    │   ├── factcheck/
    │   │   ├── factcheck_scores.jsonl
    │   │   └── meta.json
    │   └── merged_scores.jsonl
    └── scores.json
```

- [ ] **Step 6: Commit docs**

```bash
git add docs/stages/03_scoring.md docs/pilot_interfaces_agreement.md
git commit -m "docs(stages,pilot): document multi-judge scoring layout"
```

---

## Task 18: Final verification

**Files:**
- No file changes — only verification commands

- [ ] **Step 1: Run full test suite**

```bash
pytest tests/ -v
```

Expected: all tests pass. Note pass count for the commit message.

- [ ] **Step 2: Confirm no `import openai` leak**

```bash
grep -rn "import openai\|from openai" src/palimpsest/ --include="*.py" | grep -v "llm/client.py"
```

Expected: no output. CLAUDE.md Hard Invariant #6 — LLM access only through `palimpsest.llm.client.LLMClient`.

- [ ] **Step 3: Confirm CLI works**

```bash
python scripts/03_translation_scoring.py --help
```

Expected: typer usage page printed.

- [ ] **Step 4: Run smoke once more from scratch**

Discard previous smoke output if any:

```bash
rm -rf data/pilot/evaluation/claude-opus-4.7-low_par_by_par
rm -f data/pilot/evaluation/scores.json
python scripts/03_translation_scoring.py --config configs/scoring/smoke.yaml
```

Expected:
- Completes without errors.
- `data/pilot/evaluation/claude-opus-4.7-low_par_by_par/merged_scores.jsonl` exists.
- `data/pilot/evaluation/scores.json` exists and contains key `large/claude-opus-4.7-low_par_by_par`.

- [ ] **Step 5: Final commit if anything changed**

```bash
git status
```

If anything is uncommitted, commit it. If clean, just record verification result in the next message.

---

## After implementation

When all tasks above are complete and committed, surface the branch state to the user (commit count, file count, test result) and offer the next step from `superpowers:finishing-a-development-branch` — most likely PR `feat/multi-judge-scoring` → `feat/chunking-format`.
