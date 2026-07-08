# Translation Comparison Viewer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a web UI on a forked PAIR-code/llm-comparator that lets the expert compare two per-paragraph translations side by side with judge-LLM rationales, served by a FastAPI backend over `data/pilot/evaluation/`.

**Architecture:** Monorepo. Backend is a Python package under `viewer/backend/` exposing two endpoints (`/api/datasets`, `/api/dataset?a=&b=`); it reads JSONL written by Stage 03 Scoring and shapes them into the LLM Comparator JSON format. Frontend is a TypeScript+Lit+MobX fork under `viewer/frontend/` of the upstream tool, with the dataset selector, detail panel, and sidebar reworked. Caddy fronts the FastAPI process for HTTPS in production; locally FastAPI serves the built `dist/` directly.

**Tech Stack:**
- Python 3.12, FastAPI ≥0.115, uvicorn (already in root `pyproject.toml`)
- pytest, pytest-asyncio (already in `[project.optional-dependencies] dev`)
- Lit 3.1 + MobX 6 + esbuild (inherited from upstream llm-comparator)
- `marked` ≥12 for client-side markdown rendering (new npm dep)
- Playwright (Python) for E2E
- Caddy 2 + Docker compose for deployment
- Spec: [docs/superpowers/specs/2026-05-15-translation-viewer-design.md](../specs/2026-05-15-translation-viewer-design.md)

---

## File Structure

**Created**:
```
viewer/
├── backend/
│   ├── __init__.py
│   ├── paths.py        ← PathSpec parsing + validation
│   ├── adapter.py      ← JSONL → LLM-Comparator JSON
│   ├── catalog.py      ← scan EVAL_ROOT
│   └── main.py         ← FastAPI app, route handlers, dist/ static
├── frontend/           ← fork of PAIR-code/llm-comparator (snapshot)
│   ├── client/         ← Lit+MobX components, modified
│   ├── build.mjs
│   ├── package.json
│   └── …
├── Dockerfile          ← multi-stage: node build + python install
├── docker-compose.yml  ← viewer + caddy services
├── Caddyfile           ← reverse_proxy → viewer:8000 + auto-HTTPS
└── README.md           ← run / build / deploy

tests/viewer/
├── __init__.py
├── conftest.py         ← fixture-tree builders
├── test_paths.py
├── test_adapter.py
├── test_catalog.py
├── test_main.py        ← TestClient end-to-end
└── test_e2e.py         ← Playwright smoke (skip if `pw` not installed)
```

**Modified**:
- `pyproject.toml` — add `viewer` to `tool.hatch.build.targets.wheel.packages`; add playwright as dev-optional
- `docs/pipeline.md` — append cross-reference to viewer
- `README.md` — small paragraph + link

---

## Phase 0 — Scaffold

### Task 0.1: Configure hatchling to include `viewer/` package

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Read current packaging config**

Run: `grep -n "packages\|hatch\|setuptools" pyproject.toml`
Expected: locate the build-system block and any existing packages declaration.

- [ ] **Step 2: Add `viewer` to packages**

Edit `pyproject.toml`. Under `[tool.hatch.build.targets.wheel]`, set:
```toml
[tool.hatch.build.targets.wheel]
packages = ["src/palimpsest", "viewer"]
```

If the section does not exist, add it at the bottom of the file.

- [ ] **Step 3: Verify package discovery**

Run: `uv sync && uv run python -c "import viewer.backend"`
Expected: clean exit (will fail on missing `__init__.py` — fixed in next task).

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "chore(viewer): register viewer package in hatchling build"
```

### Task 0.2: Directory scaffold

**Files:**
- Create: `viewer/backend/__init__.py` (empty)
- Create: `viewer/backend/paths.py`, `adapter.py`, `catalog.py`, `main.py` (each empty placeholder with module docstring)
- Create: `viewer/__init__.py` (empty)
- Create: `tests/viewer/__init__.py`, `tests/viewer/conftest.py`
- Create: `tests/viewer/fixtures/.gitkeep`

- [ ] **Step 1: Create files**

```bash
mkdir -p viewer/backend tests/viewer/fixtures
touch viewer/__init__.py viewer/backend/__init__.py
for f in paths adapter catalog main; do
  echo '"""Stub for $f.py — implemented in later tasks."""' > viewer/backend/$f.py
done
touch tests/viewer/__init__.py tests/viewer/fixtures/.gitkeep
```

- [ ] **Step 2: Smoke test imports**

Run: `uv run python -c "import viewer.backend.paths, viewer.backend.adapter, viewer.backend.catalog, viewer.backend.main"`
Expected: no output, exit 0.

- [ ] **Step 3: Commit**

```bash
git add viewer/ tests/viewer/
git commit -m "feat(viewer): scaffold backend package and test layout"
```

---

## Phase 1 — Backend

### Task 1.1: `viewer/backend/paths.py` — PathSpec parsing and validation

**Files:**
- Modify: `viewer/backend/paths.py`
- Create: `tests/viewer/test_paths.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/viewer/test_paths.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest

from viewer.backend.paths import PathSpec, ResolvedPaths, resolve_paths


def test_parse_valid_spec():
    spec = PathSpec.parse("qwen_edited_par_by_par/v1/gpt-5.5-low")
    assert spec.run == "qwen_edited_par_by_par"
    assert spec.variant == "v1"
    assert spec.judge == "gpt-5.5-low"


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "only-one-segment",
        "two/segments",
        "four/segments/here/extra",
        "../etc/passwd",
        "qwen/v1/../judge",
        "qwen/v1/gpt 5.5",          # whitespace
        "qwen/v1/gpt;rm -rf",       # punctuation
        "qwen/v1/gpt-5.5/",         # trailing slash
        "/qwen/v1/gpt-5.5",         # leading slash
    ],
)
def test_parse_rejects_invalid(raw):
    with pytest.raises(ValueError):
        PathSpec.parse(raw)


def test_resolve_inside_root(tmp_path: Path):
    eval_root = tmp_path / "evaluation"
    (eval_root / "qwen/v1/reports").mkdir(parents=True)
    (eval_root / "qwen/v1/comparison.jsonl").write_text("")
    (eval_root / "qwen/v1/reports/gpt-5.5-low.jsonl").write_text("")
    spec = PathSpec.parse("qwen/v1/gpt-5.5-low")
    resolved = resolve_paths(eval_root, spec)
    assert resolved.comparison == eval_root / "qwen/v1/comparison.jsonl"
    assert resolved.report == eval_root / "qwen/v1/reports/gpt-5.5-low.jsonl"


def test_resolve_rejects_symlink_escape(tmp_path: Path):
    eval_root = tmp_path / "evaluation"
    eval_root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (eval_root / "trick").symlink_to(outside)
    spec = PathSpec.parse("trick/v1/gpt-5.5-low")
    with pytest.raises(ValueError, match="escape"):
        resolve_paths(eval_root, spec)


def test_resolve_missing_files_raises(tmp_path: Path):
    eval_root = tmp_path / "evaluation"
    (eval_root / "qwen/v1").mkdir(parents=True)
    spec = PathSpec.parse("qwen/v1/gpt-5.5-low")
    with pytest.raises(FileNotFoundError):
        resolve_paths(eval_root, spec)
```

- [ ] **Step 2: Run the tests — verify they fail**

Run: `uv run python -m pytest tests/viewer/test_paths.py -v`
Expected: ImportError / NameError on `PathSpec`, `ResolvedPaths`, `resolve_paths`.

- [ ] **Step 3: Implement `paths.py`**

Replace `viewer/backend/paths.py` content with:

```python
"""Path parsing and safety for the viewer backend.

A `PathSpec` is three filename segments — `run`, `variant`, `judge` — that come
from the URL. We validate them strictly because they end up in filesystem
lookups, and we resolve them against `EVAL_ROOT` while refusing anything that
would escape that root.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_SEGMENT_RE = re.compile(r"^[A-Za-z0-9_.\-]+$")


@dataclass(frozen=True, slots=True)
class PathSpec:
    """Parsed `<run>/<variant>/<judge>` triplet."""

    run: str
    variant: str
    judge: str

    @classmethod
    def parse(cls, raw: str) -> PathSpec:
        parts = raw.split("/")
        if len(parts) != 3:
            raise ValueError(
                f"PathSpec must have exactly 3 segments, got {len(parts)}: {raw!r}"
            )
        for part in parts:
            if not _SEGMENT_RE.match(part):
                raise ValueError(
                    f"PathSpec segment {part!r} fails {_SEGMENT_RE.pattern}"
                )
        return cls(run=parts[0], variant=parts[1], judge=parts[2])

    def as_str(self) -> str:
        return f"{self.run}/{self.variant}/{self.judge}"


@dataclass(frozen=True, slots=True)
class ResolvedPaths:
    """Filesystem paths the adapter will read."""

    comparison: Path
    report: Path


def resolve_paths(eval_root: Path, spec: PathSpec) -> ResolvedPaths:
    """Resolve a PathSpec under `eval_root` with symlink-escape protection."""

    root = eval_root.resolve()
    variant_dir = (root / spec.run / spec.variant).resolve()
    try:
        variant_dir.relative_to(root)
    except ValueError as exc:
        raise ValueError(
            f"PathSpec {spec.as_str()!r} would escape EVAL_ROOT"
        ) from exc

    comparison = variant_dir / "comparison.jsonl"
    report = variant_dir / "reports" / f"{spec.judge}.jsonl"

    for path in (comparison, report):
        if not path.is_file():
            raise FileNotFoundError(path)

    return ResolvedPaths(comparison=comparison, report=report)
```

- [ ] **Step 4: Verify tests pass**

Run: `uv run python -m pytest tests/viewer/test_paths.py -v`
Expected: all 5 test functions (1 parameterised × 10) pass.

- [ ] **Step 5: Commit**

```bash
git add viewer/backend/paths.py tests/viewer/test_paths.py
git commit -m "feat(viewer): PathSpec parsing and root-escape protection"
```

### Task 1.2: `viewer/backend/adapter.py` — JSONL → LLM-Comparator JSON

**Files:**
- Modify: `viewer/backend/adapter.py`
- Create: `tests/viewer/test_adapter.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/viewer/test_adapter.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

import pytest

from viewer.backend.adapter import CRITERIA, build_dataset
from viewer.backend.paths import PathSpec


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows))


def _comparison_row(id_: int, source: str, translated: str, scores: dict) -> dict:
    return {"id": id_, "source": source, "translated": translated,
            "scores": {"gpt-5.5-low": scores}}


def _report_row(id_: int, source: str, translated: str,
                per_crit: dict[str, dict]) -> dict:
    row = {"id": id_, "source": source, "translated": translated}
    for crit, vals in per_crit.items():
        row[crit] = {
            "criteria_assessment": {},
            "summary": vals["summary"],
            "final_score": vals["final_score"],
        }
    return row


def _full_per_crit(score: int, summary_prefix: str) -> dict[str, dict]:
    return {
        c: {"final_score": score, "summary": f"{summary_prefix} {c}"} for c in CRITERIA
    }


@pytest.fixture
def fixture_pair(tmp_path: Path):
    root = tmp_path / "evaluation"
    a_dir = root / "qwen_par_by_par/v1"
    b_dir = root / "opus_par_by_par/v1"
    _write_jsonl(a_dir / "comparison.jsonl", [
        _comparison_row(0, "src-0", "qwen-0",
                        {c: 9 for c in CRITERIA}),
        _comparison_row(1, "src-1", "qwen-1",
                        {c: 10 for c in CRITERIA}),
    ])
    _write_jsonl(b_dir / "comparison.jsonl", [
        _comparison_row(0, "src-0", "opus-0",
                        {c: 10 for c in CRITERIA}),
        _comparison_row(1, "src-1", "opus-1",
                        {c: 10 for c in CRITERIA}),
    ])
    _write_jsonl(a_dir / "reports/gpt-5.5-low.jsonl", [
        _report_row(0, "src-0", "qwen-0", _full_per_crit(9, "A")),
        _report_row(1, "src-1", "qwen-1", _full_per_crit(10, "A")),
    ])
    _write_jsonl(b_dir / "reports/gpt-5.5-low.jsonl", [
        _report_row(0, "src-0", "opus-0", _full_per_crit(10, "B")),
        _report_row(1, "src-1", "opus-1", _full_per_crit(10, "B")),
    ])
    return root, PathSpec("qwen_par_by_par", "v1", "gpt-5.5-low"), \
                 PathSpec("opus_par_by_par", "v1", "gpt-5.5-low")


def test_build_dataset_happy_path(fixture_pair):
    root, a, b = fixture_pair
    out = build_dataset(root, a, b)

    assert out["metadata"]["source_path"].startswith("qwen_par_by_par/v1")
    assert [f["name"] for f in out["metadata"]["custom_fields_schema"]] == [
        "accuracy", "terminology", "fluency", "cultural", "style",
        "Δ accuracy", "Δ terminology", "Δ fluency", "Δ cultural", "Δ style",
        "accuracy rationale", "terminology rationale", "fluency rationale",
        "cultural rationale", "style rationale",
    ]
    assert len(out["models"]) == 2
    assert len(out["examples"]) == 2

    ex = out["examples"][0]
    assert ex["input_text"] == "src-0"
    assert ex["output_text_a"] == "qwen-0"
    assert ex["output_text_b"] == "opus-0"
    assert ex["custom_fields"]["accuracy"] == [9, 10]
    assert ex["custom_fields"]["Δ accuracy"] == -1
    # score = mean(-1 five times)/9*1.5 = -0.16666… clipped to [-1.5, 1.5]
    assert ex["score"] == pytest.approx(-1 / 9 * 1.5)


def test_inner_join_drops_unmatched(tmp_path: Path):
    root = tmp_path / "evaluation"
    a_dir = root / "a/v1"
    b_dir = root / "b/v1"
    _write_jsonl(a_dir / "comparison.jsonl", [
        _comparison_row(0, "s0", "ta0", {c: 9 for c in CRITERIA}),
        _comparison_row(1, "s1", "ta1", {c: 9 for c in CRITERIA}),
    ])
    _write_jsonl(b_dir / "comparison.jsonl", [
        _comparison_row(1, "s1", "tb1", {c: 10 for c in CRITERIA}),
        _comparison_row(2, "s2", "tb2", {c: 10 for c in CRITERIA}),
    ])
    _write_jsonl(a_dir / "reports/judge.jsonl", [
        _report_row(0, "s0", "ta0", _full_per_crit(9, "A")),
        _report_row(1, "s1", "ta1", _full_per_crit(9, "A")),
    ])
    _write_jsonl(b_dir / "reports/judge.jsonl", [
        _report_row(1, "s1", "tb1", _full_per_crit(10, "B")),
        _report_row(2, "s2", "tb2", _full_per_crit(10, "B")),
    ])
    out = build_dataset(
        root,
        PathSpec("a", "v1", "judge"),
        PathSpec("b", "v1", "judge"),
    )
    assert [ex["input_text"] for ex in out["examples"]] == ["s1"]


def test_null_final_score_propagates(fixture_pair):
    root, a, b = fixture_pair
    # patch one row to have null final_score
    rp = root / "qwen_par_by_par/v1/reports/gpt-5.5-low.jsonl"
    rows = [json.loads(l) for l in rp.read_text().splitlines() if l.strip()]
    rows[0]["accuracy"]["final_score"] = None
    rp.write_text("\n".join(json.dumps(r) for r in rows))

    out = build_dataset(root, a, b)
    ex = out["examples"][0]
    assert ex["custom_fields"]["accuracy"] == [None, 10]
    assert ex["custom_fields"]["Δ accuracy"] is None


def test_judge_mismatch_raises(tmp_path: Path):
    root = tmp_path / "evaluation"
    a_dir = root / "a/v1"
    _write_jsonl(a_dir / "comparison.jsonl",
                 [_comparison_row(0, "s", "t", {c: 9 for c in CRITERIA})])
    _write_jsonl(a_dir / "reports/judge1.jsonl",
                 [_report_row(0, "s", "t", _full_per_crit(9, ""))])
    b_dir = root / "b/v1"
    _write_jsonl(b_dir / "comparison.jsonl",
                 [_comparison_row(0, "s", "t", {c: 9 for c in CRITERIA})])
    _write_jsonl(b_dir / "reports/judge2.jsonl",
                 [_report_row(0, "s", "t", _full_per_crit(9, ""))])
    with pytest.raises(ValueError, match="judges? must match"):
        build_dataset(root, PathSpec("a", "v1", "judge1"),
                      PathSpec("b", "v1", "judge2"))
```

- [ ] **Step 2: Run tests — verify they fail**

Run: `uv run python -m pytest tests/viewer/test_adapter.py -v`
Expected: ImportError on `CRITERIA`, `build_dataset`.

- [ ] **Step 3: Implement `adapter.py`**

Replace `viewer/backend/adapter.py` with:

```python
"""JSONL → LLM Comparator JSON adapter.

Reads `comparison.jsonl` and `reports/<judge>.jsonl` produced by Stage 03
Scoring for two evaluation runs (A, B), inner-joins them on paragraph `id`,
and shapes the result into the shape the upstream LLM Comparator frontend
expects (`metadata`, `models`, `examples[]`).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Iterable

from viewer.backend.paths import PathSpec, resolve_paths

log = logging.getLogger(__name__)

CRITERIA: tuple[str, ...] = ("accuracy", "terminology", "fluency", "cultural", "style")
SCORE_RANGE = 9  # 1..10 → max delta 9
SCORE_CLIP = 1.5  # LLM Comparator expects [-1.5, 1.5]


def _iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open(encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                log.warning("malformed JSON in %s:%d — skipped", path, lineno)


def _load_keyed(path: Path) -> dict[int, dict[str, Any]]:
    return {row["id"]: row for row in _iter_jsonl(path) if "id" in row}


def _human_label(spec: PathSpec) -> str:
    return f"{spec.run} / {spec.variant} ({spec.judge})"


def _per_criterion_score(report_row: dict[str, Any], crit: str) -> int | None:
    block = report_row.get(crit) or {}
    score = block.get("final_score")
    return score if isinstance(score, int) else None


def _per_criterion_summary(report_row: dict[str, Any], crit: str) -> str | None:
    block = report_row.get(crit) or {}
    summary = block.get("summary")
    return summary if isinstance(summary, str) and summary else None


def _build_example(
    pid: int,
    comp_a: dict[str, Any],
    comp_b: dict[str, Any],
    rep_a: dict[str, Any],
    rep_b: dict[str, Any],
) -> dict[str, Any]:
    if comp_a.get("source") != comp_b.get("source"):
        log.warning("source mismatch on id=%d; using A's", pid)

    scores_a = [_per_criterion_score(rep_a, c) for c in CRITERIA]
    scores_b = [_per_criterion_score(rep_b, c) for c in CRITERIA]
    deltas = [
        (a - b) if (a is not None and b is not None) else None
        for a, b in zip(scores_a, scores_b)
    ]
    real_deltas = [d for d in deltas if d is not None]
    if real_deltas:
        raw = (sum(real_deltas) / len(real_deltas)) / SCORE_RANGE * SCORE_CLIP
        score: float | None = max(-SCORE_CLIP, min(SCORE_CLIP, raw))
    else:
        score = None

    custom: dict[str, Any] = {}
    for crit, a, b, delta in zip(CRITERIA, scores_a, scores_b, deltas):
        custom[crit] = [a, b]
        custom[f"Δ {crit}"] = delta
        custom[f"{crit} rationale"] = [
            _per_criterion_summary(rep_a, crit),
            _per_criterion_summary(rep_b, crit),
        ]

    return {
        "input_text": comp_a.get("source", ""),
        "tags": [],
        "output_text_a": comp_a.get("translated", ""),
        "output_text_b": comp_b.get("translated", ""),
        "score": score,
        "individual_rater_scores": [],
        "rationale_list": [],
        "custom_fields": custom,
    }


def build_dataset(eval_root: Path, a: PathSpec, b: PathSpec) -> dict[str, Any]:
    """Return the LLM-Comparator-shaped JSON for the (a, b) pair."""

    if a.judge != b.judge:
        raise ValueError(f"judges must match on both sides: {a.judge!r} vs {b.judge!r}")

    paths_a = resolve_paths(eval_root, a)
    paths_b = resolve_paths(eval_root, b)

    comp_a = _load_keyed(paths_a.comparison)
    comp_b = _load_keyed(paths_b.comparison)
    rep_a = _load_keyed(paths_a.report)
    rep_b = _load_keyed(paths_b.report)

    common = sorted(set(comp_a) & set(comp_b) & set(rep_a) & set(rep_b))
    dropped = (set(comp_a) | set(comp_b) | set(rep_a) | set(rep_b)) - set(common)
    if dropped:
        log.info("inner-join dropped %d ids: %s", len(dropped), sorted(dropped)[:10])

    examples = [_build_example(pid, comp_a[pid], comp_b[pid], rep_a[pid], rep_b[pid])
                for pid in common]

    schema: list[dict[str, str]] = []
    for c in CRITERIA:
        schema.append({"name": c, "type": "per_model_number"})
    for c in CRITERIA:
        schema.append({"name": f"Δ {c}", "type": "number"})
    for c in CRITERIA:
        schema.append({"name": f"{c} rationale", "type": "per_model_text"})

    return {
        "metadata": {
            "source_path": f"{a.as_str()} vs {b.as_str()}",
            "custom_fields_schema": schema,
        },
        "models": [{"name": _human_label(a)}, {"name": _human_label(b)}],
        "examples": examples,
    }
```

- [ ] **Step 4: Verify tests pass**

Run: `uv run python -m pytest tests/viewer/test_adapter.py -v`
Expected: all 4 pass.

- [ ] **Step 5: Commit**

```bash
git add viewer/backend/adapter.py tests/viewer/test_adapter.py
git commit -m "feat(viewer): adapter joins evaluation JSONL into comparator JSON"
```

### Task 1.3: `viewer/backend/catalog.py` — scan `EVAL_ROOT`

**Files:**
- Modify: `viewer/backend/catalog.py`
- Create: `tests/viewer/test_catalog.py`

- [ ] **Step 1: Write failing tests**

Create `tests/viewer/test_catalog.py`:

```python
from __future__ import annotations

from pathlib import Path

from viewer.backend.catalog import scan_catalog


def _make_variant(root: Path, run: str, variant: str, judges: list[str],
                  n_lines: int) -> None:
    vdir = root / run / variant
    (vdir / "reports").mkdir(parents=True, exist_ok=True)
    (vdir / "comparison.jsonl").write_text("{}\n" * n_lines)
    for j in judges:
        (vdir / "reports" / f"{j}.jsonl").write_text("{}\n" * n_lines)


def test_scan_returns_full_tree(tmp_path: Path):
    _make_variant(tmp_path, "qwen", "v1", ["gpt-5.5-low"], 3)
    _make_variant(tmp_path, "qwen", "v2", ["gpt-5.5-low", "gpt-5.4-mini"], 3)
    _make_variant(tmp_path, "opus", "v1", ["gpt-5.5-low"], 2)

    out = scan_catalog(tmp_path)
    assert [r["name"] for r in out["runs"]] == ["opus", "qwen"]
    qwen = next(r for r in out["runs"] if r["name"] == "qwen")
    assert [v["variant"] for v in qwen["variants"]] == ["v1", "v2"]
    v2 = qwen["variants"][1]
    assert v2["judges"] == ["gpt-5.4-mini", "gpt-5.5-low"]
    assert v2["n_paragraphs"] == 3


def test_skip_variant_without_comparison(tmp_path: Path):
    (tmp_path / "qwen/v1/reports").mkdir(parents=True)
    (tmp_path / "qwen/v1/reports/gpt.jsonl").write_text("{}\n")
    # No comparison.jsonl → variant skipped, so no run record either.
    out = scan_catalog(tmp_path)
    assert out == {"runs": []}


def test_skip_variant_without_reports(tmp_path: Path):
    vdir = tmp_path / "qwen/v1"
    vdir.mkdir(parents=True)
    (vdir / "comparison.jsonl").write_text("{}\n")
    out = scan_catalog(tmp_path)
    assert out == {"runs": []}


def test_empty_root(tmp_path: Path):
    assert scan_catalog(tmp_path) == {"runs": []}


def test_nonexistent_root(tmp_path: Path):
    assert scan_catalog(tmp_path / "missing") == {"runs": []}
```

- [ ] **Step 2: Run tests — fail**

Run: `uv run python -m pytest tests/viewer/test_catalog.py -v`
Expected: ImportError on `scan_catalog`.

- [ ] **Step 3: Implement `catalog.py`**

Replace `viewer/backend/catalog.py` with:

```python
"""Catalog scanner: walk EVAL_ROOT and report (run, variant, judges)."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def _count_lines(path: Path) -> int:
    n = 0
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                n += 1
    return n


def scan_catalog(eval_root: Path) -> dict[str, Any]:
    """Return `{runs: [{name, variants: [{variant, judges, n_paragraphs}]}]}`.

    A `(run, variant)` is included iff its directory has both `comparison.jsonl`
    and at least one `reports/*.jsonl`. Missing roots or empty trees return
    `{"runs": []}`.
    """

    if not eval_root.is_dir():
        return {"runs": []}

    runs: list[dict[str, Any]] = []
    for run_dir in sorted(p for p in eval_root.iterdir() if p.is_dir()):
        variants: list[dict[str, Any]] = []
        for variant_dir in sorted(p for p in run_dir.iterdir() if p.is_dir()):
            comparison = variant_dir / "comparison.jsonl"
            reports_dir = variant_dir / "reports"
            if not comparison.is_file() or not reports_dir.is_dir():
                continue
            judges = sorted(
                p.stem for p in reports_dir.glob("*.jsonl") if p.is_file()
            )
            if not judges:
                continue
            variants.append({
                "variant": variant_dir.name,
                "judges": judges,
                "n_paragraphs": _count_lines(comparison),
            })
        if variants:
            runs.append({"name": run_dir.name, "variants": variants})

    return {"runs": runs}
```

- [ ] **Step 4: Verify tests pass**

Run: `uv run python -m pytest tests/viewer/test_catalog.py -v`
Expected: 5/5 pass.

- [ ] **Step 5: Commit**

```bash
git add viewer/backend/catalog.py tests/viewer/test_catalog.py
git commit -m "feat(viewer): catalog scanner for EVAL_ROOT"
```

### Task 1.4: `viewer/backend/main.py` — FastAPI app + static `dist/`

**Files:**
- Modify: `viewer/backend/main.py`
- Create: `tests/viewer/test_main.py`

- [ ] **Step 1: Write failing tests**

Create `tests/viewer/test_main.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from viewer.backend.adapter import CRITERIA
from viewer.backend.main import create_app


def _seed_eval(tmp_path: Path) -> Path:
    root = tmp_path / "evaluation"
    for run, variant in [("qwen", "v1"), ("opus", "v1")]:
        (root / run / variant / "reports").mkdir(parents=True)
        (root / run / variant / "comparison.jsonl").write_text(
            json.dumps({"id": 0, "source": "s", "translated": f"{run}-t",
                        "scores": {"gpt": {c: 9 for c in CRITERIA}}}) + "\n"
        )
        report = {"id": 0, "source": "s", "translated": f"{run}-t"}
        for c in CRITERIA:
            report[c] = {"final_score": 9, "summary": f"{run}-{c}",
                         "criteria_assessment": {}}
        (root / run / variant / "reports/gpt.jsonl").write_text(json.dumps(report) + "\n")
    return root


@pytest.fixture
def client(tmp_path: Path):
    root = _seed_eval(tmp_path)
    app = create_app(eval_root=root)
    return TestClient(app)


def test_get_datasets(client):
    r = client.get("/api/datasets")
    assert r.status_code == 200
    body = r.json()
    assert [run["name"] for run in body["runs"]] == ["opus", "qwen"]


def test_get_dataset_happy_path(client):
    r = client.get("/api/dataset",
                   params={"a": "qwen/v1/gpt", "b": "opus/v1/gpt"})
    assert r.status_code == 200
    body = r.json()
    assert len(body["examples"]) == 1
    ex = body["examples"][0]
    assert ex["output_text_a"] == "qwen-t"
    assert ex["output_text_b"] == "opus-t"


def test_get_dataset_bad_pathspec(client):
    r = client.get("/api/dataset", params={"a": "x", "b": "y"})
    assert r.status_code == 400


def test_get_dataset_missing_files(client):
    r = client.get("/api/dataset",
                   params={"a": "qwen/v1/nonexistent", "b": "opus/v1/gpt"})
    assert r.status_code == 404


def test_get_dataset_judge_mismatch(client, tmp_path: Path):
    root = tmp_path / "evaluation"
    # rebuild with two different judges
    (root / "opus/v1/reports").mkdir(parents=True, exist_ok=True)
    # Need both judges present in opus/v1
    src = (root / "opus/v1/reports/gpt.jsonl").read_text()
    (root / "opus/v1/reports/other.jsonl").write_text(src)
    r = client.get("/api/dataset",
                   params={"a": "qwen/v1/gpt", "b": "opus/v1/other"})
    assert r.status_code == 422
```

- [ ] **Step 2: Run tests — fail**

Run: `uv run python -m pytest tests/viewer/test_main.py -v`
Expected: ImportError on `create_app`.

- [ ] **Step 3: Implement `main.py`**

Replace `viewer/backend/main.py` with:

```python
"""FastAPI app for the translation comparison viewer.

Two API routes plus optional static-dir serving:
- `GET /api/datasets`         — catalog
- `GET /api/dataset?a=&b=`    — joined LLM-Comparator JSON
- `GET /` and friends         — serves `viewer/frontend/dist/` if it exists
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from viewer.backend.adapter import build_dataset
from viewer.backend.catalog import scan_catalog
from viewer.backend.paths import PathSpec

log = logging.getLogger(__name__)


def _default_eval_root() -> Path:
    env = os.environ.get("EVAL_ROOT")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[2] / "data/pilot/evaluation"


def _default_dist_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "frontend" / "dist"


def create_app(
    eval_root: Path | None = None,
    dist_dir: Path | None = None,
) -> FastAPI:
    eval_root = (eval_root or _default_eval_root()).resolve()
    dist_dir = dist_dir if dist_dir is not None else _default_dist_dir()

    app = FastAPI(title="Translation Comparison Viewer")

    @app.get("/api/datasets")
    def get_datasets() -> dict:
        return scan_catalog(eval_root)

    @app.get("/api/dataset")
    def get_dataset(a: str = Query(...), b: str = Query(...)) -> dict:
        try:
            spec_a = PathSpec.parse(a)
            spec_b = PathSpec.parse(b)
        except ValueError as exc:
            raise HTTPException(400, detail=str(exc))
        try:
            return build_dataset(eval_root, spec_a, spec_b)
        except FileNotFoundError as exc:
            raise HTTPException(404, detail=f"missing file: {exc}")
        except ValueError as exc:
            msg = str(exc)
            if "judges must match" in msg:
                raise HTTPException(422, detail=msg)
            raise HTTPException(400, detail=msg)

    if dist_dir.is_dir():
        app.mount("/", StaticFiles(directory=dist_dir, html=True), name="dist")
        log.info("serving static frontend from %s", dist_dir)
    else:
        log.info("no dist/ at %s — API-only mode", dist_dir)

        @app.get("/")
        def root() -> JSONResponse:
            return JSONResponse({
                "service": "Translation Comparison Viewer",
                "status": "API only (no frontend dist/ built)",
                "endpoints": ["/api/datasets", "/api/dataset?a=&b="],
            })

    return app


app = create_app()
```

- [ ] **Step 4: Verify tests pass**

Run: `uv run python -m pytest tests/viewer/test_main.py -v`
Expected: 5/5 pass.

- [ ] **Step 5: Quick smoke run**

Run: `EVAL_ROOT=data/pilot/evaluation uv run uvicorn viewer.backend.main:app --port 8765 &` for 3 seconds, then `curl http://localhost:8765/api/datasets | head -c 300`, then `kill %1`.
Expected: JSON catalog with runs from real evaluation data.

- [ ] **Step 6: Commit**

```bash
git add viewer/backend/main.py tests/viewer/test_main.py
git commit -m "feat(viewer): FastAPI app for catalog + dataset endpoints"
```

---

## Phase 2 — Frontend snapshot

### Task 2.1: Snapshot upstream `PAIR-code/llm-comparator` into `viewer/frontend/`

**Files:**
- Create: `viewer/frontend/` (entire upstream tree)
- Create: `viewer/frontend/UPSTREAM.md`

- [ ] **Step 1: Copy upstream code**

```bash
cp -R /tmp/llm-comparator viewer/frontend
rm -rf viewer/frontend/.git viewer/frontend/.npmignore
```

- [ ] **Step 2: Document the snapshot**

Create `viewer/frontend/UPSTREAM.md`:

```markdown
# Upstream source

This directory is a snapshot of [PAIR-code/llm-comparator](https://github.com/PAIR-code/llm-comparator)
licensed Apache-2.0, copied verbatim and then modified for this project. The
original `LICENSE` is preserved alongside.

Source commit: see `upstream-rev.txt` for the commit hash captured at clone
time.

Modifications:
- Dataset selection replaced with a catalog picker tied to a FastAPI backend.
- Sidebar reworked to show per-criterion histograms, aggregate stats, and a
  delta-distribution view.
- Detail panel rewritten as a single stack with five criterion cards.
- Markdown rendering added via `marked`.
```

- [ ] **Step 3: Capture upstream revision**

```bash
( cd /tmp/llm-comparator && git rev-parse HEAD ) > viewer/frontend/upstream-rev.txt
```

- [ ] **Step 4: Install npm deps (verify build runs)**

```bash
cd viewer/frontend && npm install --no-audit --no-fund && cd -
```

- [ ] **Step 5: Build smoke**

```bash
cd viewer/frontend && npm run build && cd -
ls viewer/frontend/dist/index.html viewer/frontend/dist/static
```

Expected: `index.html` present, `static/` populated.

- [ ] **Step 6: Add `node_modules`, `dist`, `package-lock.json` rules**

Append to root `.gitignore`:
```
viewer/frontend/node_modules/
viewer/frontend/dist/
viewer/frontend/package-lock.json
```

Then `git rm -rf --cached` any of those that snuck in.

- [ ] **Step 7: Commit**

```bash
git add viewer/frontend .gitignore
git commit -m "feat(viewer): vendor PAIR-code/llm-comparator snapshot under viewer/frontend"
```

### Task 2.2: Add `marked` dependency and rename `package.json` metadata

**Files:**
- Modify: `viewer/frontend/package.json`

- [ ] **Step 1: Update metadata + add marked**

```bash
cd viewer/frontend
npm pkg set name="translation-comparison-viewer" \
            description="Per-paragraph translation comparison UI on top of LLM Comparator" \
            repository="local"
npm install marked@^12.0.0 --save
cd -
```

- [ ] **Step 2: Verify build still works**

```bash
cd viewer/frontend && npm run build && cd -
```

- [ ] **Step 3: Commit**

```bash
git add viewer/frontend/package.json viewer/frontend/package-lock.json
git commit -m "build(viewer): rename frontend package and add marked dep"
```

---

## Phase 3 — Frontend modifications

### Task 3.1: AppState extensions — catalog, URL sync, render flags

**Files:**
- Modify: `viewer/frontend/client/services/state_service.ts`

- [ ] **Step 1: Read current AppState**

Run: `grep -n "loadData\|isShowSidebar\|class AppState" viewer/frontend/client/services/state_service.ts`
Expected: locate `loadData` and constructor.

- [ ] **Step 2: Add fields and methods**

Append to the `AppState` class (after existing observable fields):

```typescript
@observable catalog: {runs: Array<{name: string; variants: Array<{variant: string; judges: string[]; n_paragraphs: number}>}>} = {runs: []};
@observable catalogLoadState: 'idle' | 'loading' | 'ready' | 'error' = 'idle';
@observable catalogError: string | null = null;

@observable catalogSelectionA: {run: string; variant: string; judge: string} | null = null;
@observable catalogSelectionB: {run: string; variant: string; judge: string} | null = null;

@observable isRenderMarkdown = true;
@observable isShowDiff = false;
@observable isOpenCatalogPicker = false;

async loadCatalog() {
  this.catalogLoadState = 'loading';
  this.catalogError = null;
  try {
    const r = await fetch('/api/datasets');
    if (!r.ok) throw new Error(`/api/datasets returned ${r.status}`);
    this.catalog = await r.json();
    this.catalogLoadState = 'ready';
  } catch (e: any) {
    this.catalogError = e?.message ?? String(e);
    this.catalogLoadState = 'error';
  }
}

loadComparison(a: {run: string; variant: string; judge: string},
               b: {run: string; variant: string; judge: string}) {
  this.catalogSelectionA = a;
  this.catalogSelectionB = b;
  const qs = new URLSearchParams({
    a: `${a.run}/${a.variant}/${a.judge}`,
    b: `${b.run}/${b.variant}/${b.judge}`,
  });
  history.pushState({}, '', `?${qs.toString()}`);
  this.loadData(`/api/dataset?${qs.toString()}`, null);
  this.isOpenCatalogPicker = false;
}

readSelectionsFromUrl(): boolean {
  const url = new URL(window.location.href);
  const a = url.searchParams.get('a');
  const b = url.searchParams.get('b');
  if (!a || !b) return false;
  const parseSpec = (s: string) => {
    const [run, variant, judge] = s.split('/');
    return (run && variant && judge) ? {run, variant, judge} : null;
  };
  const pa = parseSpec(a);
  const pb = parseSpec(b);
  if (!pa || !pb) return false;
  this.catalogSelectionA = pa;
  this.catalogSelectionB = pb;
  return true;
}
```

In `initialize()`, replace existing dataset-load logic with:
```typescript
await this.loadCatalog();
if (this.readSelectionsFromUrl() && this.catalogSelectionA && this.catalogSelectionB) {
  const a = this.catalogSelectionA;
  const b = this.catalogSelectionB;
  const qs = new URLSearchParams({
    a: `${a.run}/${a.variant}/${a.judge}`,
    b: `${b.run}/${b.variant}/${b.judge}`,
  });
  this.loadData(`/api/dataset?${qs.toString()}`, null);
} else {
  this.isOpenCatalogPicker = true;
}
```

Also set `isShowSidebar = false` as initial value (sidebar collapsed by default).

- [ ] **Step 3: Verify TypeScript compiles**

```bash
cd viewer/frontend && npm run build && cd -
```
Expected: no TS errors.

- [ ] **Step 4: Commit**

```bash
git add viewer/frontend/client/services/state_service.ts
git commit -m "feat(viewer/frontend): AppState catalog, URL sync, markdown flag"
```

### Task 3.2: Catalog picker component

**Files:**
- Create: `viewer/frontend/client/components/catalog_picker.ts`
- Create: `viewer/frontend/client/components/catalog_picker.css`
- Modify: `viewer/frontend/client/app.ts` (replace `comparator-dataset-selection` with `comparator-catalog-picker`)

- [ ] **Step 1: Write the component**

Create `viewer/frontend/client/components/catalog_picker.css`:

```css
:host {
  position: fixed;
  inset: 0;
  display: grid;
  place-items: center;
  background: rgba(0, 0, 0, 0.4);
  z-index: 100;
}

.modal {
  background: var(--background-color, #fff);
  width: 720px;
  max-width: 90vw;
  border-radius: 8px;
  box-shadow: 0 10px 40px rgba(0, 0, 0, 0.25);
  padding: 24px;
}

.modal h2 { margin: 0 0 16px; font-size: 18px; }

.two-cols {
  display: grid; grid-template-columns: 1fr 1fr; gap: 40px;
}
.col h3 { font-size: 13px; margin: 0 0 8px; color: #555; }
.field { margin-bottom: 16px; }
.field label { display: block; font-size: 12px; color: #666; margin-bottom: 4px; }
select { width: 100%; padding: 6px 8px; font: inherit; }
select:disabled { background: #f4f4f4; color: #999; }

.swap-row { text-align: center; margin: 12px 0; }
.swap-btn { background: transparent; border: 1px solid #ccc; padding: 4px 12px; border-radius: 4px; cursor: pointer; font-size: 12px; }
.swap-btn:hover { background: #f4f4f4; }

.hint { color: #666; font-size: 12px; margin: 12px 0; }
.warn { color: #c0392b; font-size: 12px; margin: 6px 0; }

.actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 16px; }
.btn { padding: 6px 16px; border: 1px solid #ccc; background: #fff; border-radius: 4px; cursor: pointer; font: inherit; }
.btn.primary { background: #1976d2; color: #fff; border-color: #1976d2; }
.btn.primary:disabled { background: #aaa; border-color: #aaa; cursor: not-allowed; }

.empty, .loading, .error { padding: 24px 8px; text-align: center; color: #444; }
.error { color: #c0392b; }
```

Create `viewer/frontend/client/components/catalog_picker.ts`:

```typescript
/**
 * @license Apache-2.0
 *
 * Catalog picker modal: lets the user pick two (run, variant, judge) triples
 * to compare. Sits on top of `AppState.catalog` and calls `loadComparison`.
 */

import {MobxLitElement} from '@adobe/lit-mobx';
import {html} from 'lit';
import {customElement} from 'lit/decorators.js';
import {makeObservable, observable} from 'mobx';

import {core} from '../core';
import {AppState} from '../services/state_service';

import {styles} from './catalog_picker.css';

type Sel = {run: string; variant: string; judge: string} | null;

interface Run {name: string; variants: Array<{variant: string; judges: string[]; n_paragraphs: number}>}

function emptySel(): {run: string; variant: string; judge: string} {
  return {run: '', variant: '', judge: ''};
}

@customElement('comparator-catalog-picker')
export class CatalogPickerElement extends MobxLitElement {
  private readonly appState = core.getService(AppState);

  static override get styles() { return [styles]; }

  @observable a = emptySel();
  @observable b = emptySel();

  constructor() {
    super();
    makeObservable(this);
  }

  override connectedCallback() {
    super.connectedCallback();
    if (this.appState.catalogSelectionA) this.a = {...this.appState.catalogSelectionA};
    if (this.appState.catalogSelectionB) this.b = {...this.appState.catalogSelectionB};
    document.addEventListener('keydown', this.handleKey);
  }
  override disconnectedCallback() {
    document.removeEventListener('keydown', this.handleKey);
    super.disconnectedCallback();
  }

  private handleKey = (e: KeyboardEvent) => {
    if (e.key === 'Escape') this.cancel();
  };

  private cancel = () => { this.appState.isOpenCatalogPicker = false; };

  private getRun(name: string): Run | undefined {
    return this.appState.catalog.runs.find(r => r.name === name);
  }

  private variantsFor(runName: string) {
    return this.getRun(runName)?.variants ?? [];
  }
  private judgesFor(runName: string, variantName: string) {
    return this.variantsFor(runName).find(v => v.variant === variantName)?.judges ?? [];
  }
  private nParagraphsFor(runName: string, variantName: string) {
    return this.variantsFor(runName).find(v => v.variant === variantName)?.n_paragraphs ?? 0;
  }

  private setRun(side: 'a' | 'b', run: string) {
    const s = side === 'a' ? this.a : this.b;
    if (side === 'a') this.a = {run, variant: '', judge: ''};
    else this.b = {run, variant: '', judge: ''};
  }
  private setVariant(side: 'a' | 'b', variant: string) {
    if (side === 'a') this.a = {...this.a, variant, judge: ''};
    else this.b = {...this.b, variant, judge: ''};
  }
  private setJudge(side: 'a' | 'b', judge: string) {
    if (side === 'a') this.a = {...this.a, judge};
    else this.b = {...this.b, judge};
  }

  private swap() {
    const tmp = this.a;
    this.a = this.b;
    this.b = tmp;
  }

  private get loadInvalidReason(): string | null {
    const full = (s: typeof this.a) => s.run && s.variant && s.judge;
    if (!full(this.a)) return 'Pick run, variant, and judge for A';
    if (!full(this.b)) return 'Pick run, variant, and judge for B';
    if (this.a.judge !== this.b.judge) return 'Judges must match';
    if (this.a.run === this.b.run && this.a.variant === this.b.variant &&
        this.a.judge === this.b.judge) return 'A and B point to the same dataset';
    return null;
  }

  private load = () => {
    if (this.loadInvalidReason) return;
    this.appState.loadComparison(this.a, this.b);
  };

  private renderSide(side: 'a' | 'b') {
    const s = side === 'a' ? this.a : this.b;
    const variants = this.variantsFor(s.run);
    const judges = this.judgesFor(s.run, s.variant);
    return html`
      <div class="col">
        <h3>Translation ${side.toUpperCase()}</h3>

        <div class="field">
          <label>Run</label>
          <select .value=${s.run}
                  @change=${(e: Event) => this.setRun(side, (e.target as HTMLSelectElement).value)}>
            <option value="">Select…</option>
            ${this.appState.catalog.runs.map(r => html`
              <option value=${r.name} ?selected=${s.run === r.name}>${r.name}</option>
            `)}
          </select>
        </div>

        <div class="field">
          <label>Variant</label>
          <select .value=${s.variant} ?disabled=${!s.run}
                  @change=${(e: Event) => this.setVariant(side, (e.target as HTMLSelectElement).value)}>
            <option value="">Select…</option>
            ${variants.map(v => html`
              <option value=${v.variant} ?selected=${s.variant === v.variant}>
                ${v.variant} · ${v.n_paragraphs} paragraphs
              </option>
            `)}
          </select>
        </div>

        <div class="field">
          <label>Judge</label>
          <select .value=${s.judge} ?disabled=${!s.variant}
                  @change=${(e: Event) => this.setJudge(side, (e.target as HTMLSelectElement).value)}>
            <option value="">Select…</option>
            ${judges.map(j => html`
              <option value=${j} ?selected=${s.judge === j}>${j}</option>
            `)}
          </select>
        </div>
      </div>
    `;
  }

  private renderBody() {
    if (this.appState.catalogLoadState === 'loading') {
      return html`<div class="loading">Loading datasets…</div>`;
    }
    if (this.appState.catalogLoadState === 'error') {
      return html`
        <div class="error">⚠ Failed to load catalog: ${this.appState.catalogError}</div>
        <div class="actions">
          <button class="btn" @click=${this.cancel}>Cancel</button>
          <button class="btn primary" @click=${() => this.appState.loadCatalog()}>Retry</button>
        </div>`;
    }
    if (this.appState.catalogLoadState === 'ready' && this.appState.catalog.runs.length === 0) {
      return html`
        <div class="empty">
          No evaluations found in <code>EVAL_ROOT</code>.<br>
          Run Stage 03 Scoring to produce <code>comparison.jsonl</code> +
          <code>reports/&lt;judge&gt;.jsonl</code>, then
          <button class="btn" @click=${() => this.appState.loadCatalog()}>Reload</button>.
        </div>
        <div class="actions"><button class="btn" @click=${this.cancel}>Cancel</button></div>`;
    }

    const reason = this.loadInvalidReason;
    const mismatch = this.a.judge && this.b.judge && this.a.judge !== this.b.judge;

    return html`
      <div class="two-cols">
        ${this.renderSide('a')}
        ${this.renderSide('b')}
      </div>
      <div class="swap-row">
        <button class="swap-btn" @click=${this.swap}>⇄ Swap A ↔ B</button>
      </div>
      <div class="hint">Judge must match on both sides.</div>
      ${mismatch ? html`<div class="warn">⚠ "${this.a.judge}" ≠ "${this.b.judge}"</div>` : ''}
      <div class="actions">
        <button class="btn" @click=${this.cancel}>Cancel</button>
        <button class="btn primary" title=${reason ?? ''}
                ?disabled=${!!reason} @click=${this.load}>Load</button>
      </div>
    `;
  }

  private onOverlayClick = (e: Event) => {
    if (e.target === this) this.cancel();
  };

  override render() {
    return html`
      <div @click=${this.onOverlayClick}>
        <div class="modal" @click=${(e: Event) => e.stopPropagation()}>
          <h2>Compare two translations</h2>
          ${this.renderBody()}
        </div>
      </div>`;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'comparator-catalog-picker': CatalogPickerElement;
  }
}
```

- [ ] **Step 2: Wire into `app.ts`**

In `viewer/frontend/client/app.ts`, replace the `import './components/dataset_selection'` line with `import './components/catalog_picker'`. In the `render()` method, replace `<comparator-dataset-selection></comparator-dataset-selection>` with:
```typescript
${this.appState.isOpenCatalogPicker
  ? html`<comparator-catalog-picker></comparator-catalog-picker>`
  : ''}
```

Update the header's "Load Data" button click handler:
```typescript
const handleClickLoadData = () => {
  this.appState.isOpenCatalogPicker = true;
};
```

- [ ] **Step 3: Build smoke**

```bash
cd viewer/frontend && npm run build && cd -
```
Expected: clean build.

- [ ] **Step 4: Commit**

```bash
git add viewer/frontend/client/components/catalog_picker.ts \
        viewer/frontend/client/components/catalog_picker.css \
        viewer/frontend/client/app.ts
git commit -m "feat(viewer/frontend): catalog picker modal replaces dataset selection"
```

### Task 3.3: Sidebar — three new widgets

**Files:**
- Create: `viewer/frontend/client/components/per_criterion_histograms.ts` (+ `.css`)
- Create: `viewer/frontend/client/components/aggregate_stats.ts` (+ `.css`)
- Create: `viewer/frontend/client/components/delta_distribution.ts` (+ `.css`)
- Modify: `viewer/frontend/client/app.ts` (sidebar layout)

- [ ] **Step 1: Create per-criterion histograms widget**

The criterion list is `["accuracy", "terminology", "fluency", "cultural", "style"]`. For each criterion, render an overlay histogram with bins 1..10 — bars for A in blue, B in orange — using inline SVG. Pull values from `appState.examples` via `custom_fields[crit]`.

Create `viewer/frontend/client/components/per_criterion_histograms.ts`:

```typescript
import {MobxLitElement} from '@adobe/lit-mobx';
import {html} from 'lit';
import {customElement} from 'lit/decorators.js';

import {core} from '../core';
import {AppState} from '../services/state_service';

import {styles} from './per_criterion_histograms.css';

const CRITERIA = ['accuracy', 'terminology', 'fluency', 'cultural', 'style'] as const;

@customElement('comparator-per-criterion-histograms')
export class PerCriterionHistogramsElement extends MobxLitElement {
  private readonly appState = core.getService(AppState);

  static override get styles() { return [styles]; }

  private histogram(values: Array<number | null>): number[] {
    const bins = Array.from({length: 10}, () => 0);
    for (const v of values) {
      if (v == null) continue;
      const idx = Math.max(0, Math.min(9, Math.round(v) - 1));
      bins[idx] += 1;
    }
    return bins;
  }

  private renderHist(crit: string) {
    const examples = this.appState.examples ?? [];
    if (!examples.length) return html`<div class="empty">No data</div>`;

    const aVals = examples.map(e => (e.custom_fields?.[crit] as Array<number | null>)?.[0] ?? null);
    const bVals = examples.map(e => (e.custom_fields?.[crit] as Array<number | null>)?.[1] ?? null);
    const ha = this.histogram(aVals);
    const hb = this.histogram(bVals);
    const max = Math.max(1, ...ha, ...hb);

    const w = 220, h = 80, n = 10, pad = 4, barW = (w - pad * (n + 1)) / n;
    const bars = (counts: number[], color: string, dx: number) =>
      counts.map((c, i) => {
        const x = pad + i * (barW + pad) + dx;
        const bh = (c / max) * (h - 14);
        return `<rect x="${x}" y="${h - bh - 2}" width="${barW / 2 - 1}" height="${bh}" fill="${color}" opacity="0.8"></rect>`;
      }).join('');

    return html`
      <div class="hist">
        <div class="label">${crit}</div>
        <svg viewBox="0 0 ${w} ${h}" width="${w}" height="${h}">
          ${unsafeHTML(bars(ha, '#1976d2', 0))}
          ${unsafeHTML(bars(hb, '#e8742c', barW / 2 + 1))}
        </svg>
      </div>`;
  }

  override render() {
    return html`
      <div class="root">
        ${CRITERIA.map(c => this.renderHist(c))}
        <div class="legend">
          <span><span class="swatch a"></span> A</span>
          <span><span class="swatch b"></span> B</span>
        </div>
      </div>`;
  }
}

import {unsafeHTML} from 'lit/directives/unsafe-html.js';

declare global {
  interface HTMLElementTagNameMap {
    'comparator-per-criterion-histograms': PerCriterionHistogramsElement;
  }
}
```

Create `viewer/frontend/client/components/per_criterion_histograms.css`:
```css
.root { padding: 8px; }
.hist { margin-bottom: 12px; }
.hist .label { font-size: 11px; color: #555; text-transform: uppercase; letter-spacing: 0.5px; }
.legend { display: flex; gap: 12px; font-size: 12px; color: #555; padding-top: 4px; border-top: 1px solid #eee; margin-top: 4px; }
.swatch { display: inline-block; width: 10px; height: 10px; vertical-align: middle; margin-right: 4px; }
.swatch.a { background: #1976d2; opacity: 0.8; }
.swatch.b { background: #e8742c; opacity: 0.8; }
.empty { color: #999; padding: 8px; font-size: 12px; }
```

- [ ] **Step 2: Create aggregate stats widget**

Create `viewer/frontend/client/components/aggregate_stats.ts`:

```typescript
import {MobxLitElement} from '@adobe/lit-mobx';
import {html} from 'lit';
import {customElement} from 'lit/decorators.js';

import {core} from '../core';
import {AppState} from '../services/state_service';

import {styles} from './aggregate_stats.css';

const CRITERIA = ['accuracy', 'terminology', 'fluency', 'cultural', 'style'] as const;

function mean(nums: Array<number | null | undefined>): number | null {
  const xs = nums.filter((x): x is number => typeof x === 'number');
  return xs.length ? xs.reduce((s, v) => s + v, 0) / xs.length : null;
}

@customElement('comparator-aggregate-stats')
export class AggregateStatsElement extends MobxLitElement {
  private readonly appState = core.getService(AppState);

  static override get styles() { return [styles]; }

  override render() {
    const examples = this.appState.examples ?? [];
    if (!examples.length) return html`<div class="empty">No data</div>`;
    const fmt = (x: number | null) => x == null ? '—' : x.toFixed(2);
    const pct = (x: number) => `${(x * 100).toFixed(0)}%`;

    const rows = CRITERIA.map(c => {
      const aVals = examples.map(e => (e.custom_fields?.[c] as Array<number | null>)?.[0] ?? null);
      const bVals = examples.map(e => (e.custom_fields?.[c] as Array<number | null>)?.[1] ?? null);
      const deltas = examples.map(e => e.custom_fields?.[`Δ ${c}`] as number | null | undefined);
      const real = deltas.filter((x): x is number => typeof x === 'number');
      const aw = real.filter(d => d > 0).length;
      const bw = real.filter(d => d < 0).length;
      const tie = real.filter(d => d === 0).length;
      const total = real.length || 1;
      return {c, avgA: mean(aVals), avgB: mean(bVals),
              aw: aw / total, bw: bw / total, tie: tie / total,
              dAvg: mean(deltas)};
    });

    return html`
      <table>
        <thead><tr>
          <th></th><th>avg A</th><th>avg B</th>
          <th>A wins</th><th>B wins</th><th>ties</th><th>Δ avg</th>
        </tr></thead>
        <tbody>
          ${rows.map(r => html`<tr>
            <td>${r.c}</td>
            <td>${fmt(r.avgA)}</td><td>${fmt(r.avgB)}</td>
            <td>${pct(r.aw)}</td><td>${pct(r.bw)}</td><td>${pct(r.tie)}</td>
            <td>${fmt(r.dAvg)}</td>
          </tr>`)}
        </tbody>
      </table>`;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'comparator-aggregate-stats': AggregateStatsElement;
  }
}
```

Create `viewer/frontend/client/components/aggregate_stats.css`:
```css
table { width: 100%; border-collapse: collapse; font-size: 12px; }
th, td { padding: 4px 6px; text-align: right; }
th:first-child, td:first-child { text-align: left; text-transform: capitalize; }
thead th { color: #666; font-weight: 500; border-bottom: 1px solid #ddd; }
tbody tr:nth-child(even) { background: #fafafa; }
.empty { color: #999; padding: 8px; font-size: 12px; }
```

- [ ] **Step 3: Create delta-distribution widget**

Create `viewer/frontend/client/components/delta_distribution.ts`:

```typescript
import {MobxLitElement} from '@adobe/lit-mobx';
import {html} from 'lit';
import {customElement} from 'lit/decorators.js';

import {core} from '../core';
import {AppState} from '../services/state_service';

import {styles} from './delta_distribution.css';

const CRITERIA = ['accuracy', 'terminology', 'fluency', 'cultural', 'style'] as const;

@customElement('comparator-delta-distribution')
export class DeltaDistributionElement extends MobxLitElement {
  private readonly appState = core.getService(AppState);
  static override get styles() { return [styles]; }

  override render() {
    const examples = this.appState.examples ?? [];
    if (!examples.length) return html`<div class="empty">No data</div>`;

    // sum of Δ across 5 criteria, skip null
    const sums = examples.map(e => {
      let s = 0;
      let any = false;
      for (const c of CRITERIA) {
        const v = e.custom_fields?.[`Δ ${c}`] as number | null | undefined;
        if (typeof v === 'number') { s += v; any = true; }
      }
      return any ? s : null;
    }).filter((x): x is number => x != null);

    if (!sums.length) return html`<div class="empty">No deltas</div>`;
    const min = -45, max = 45;
    const bins = 19;
    const buckets = Array.from({length: bins}, () => 0);
    const w = 220, h = 80, pad = 4, bw = (w - pad * 2) / bins;
    for (const v of sums) {
      const t = (v - min) / (max - min);
      const i = Math.max(0, Math.min(bins - 1, Math.floor(t * bins)));
      buckets[i] += 1;
    }
    const maxC = Math.max(1, ...buckets);
    const bars = buckets.map((c, i) => {
      const x = pad + i * bw;
      const bh = (c / maxC) * (h - 14);
      return `<rect x="${x}" y="${h - bh - 2}" width="${bw - 1}" height="${bh}" fill="#666"></rect>`;
    }).join('');

    return html`
      <div class="root">
        <svg viewBox="0 0 ${w} ${h}" width="${w}" height="${h}">${unsafeHTML(bars)}</svg>
        <div class="axis"><span>−45 (B better)</span><span>0</span><span>+45 (A better)</span></div>
      </div>`;
  }
}

import {unsafeHTML} from 'lit/directives/unsafe-html.js';

declare global {
  interface HTMLElementTagNameMap {
    'comparator-delta-distribution': DeltaDistributionElement;
  }
}
```

Create `viewer/frontend/client/components/delta_distribution.css`:
```css
.root { padding: 8px; }
.axis { display: flex; justify-content: space-between; font-size: 10px; color: #888; padding-top: 2px; }
.empty { color: #999; padding: 8px; font-size: 12px; }
```

- [ ] **Step 4: Wire sidebar in `app.ts`**

In `viewer/frontend/client/app.ts`:
- Replace existing `renderSidebar()` body with collapsible sections that each show one of the three new components:
  ```typescript
  renderSidebar() {
    return html`<div id="sidebar">
      <details><summary>Score histograms per criterion</summary>
        <comparator-per-criterion-histograms></comparator-per-criterion-histograms>
      </details>
      <details><summary>Aggregate stats</summary>
        <comparator-aggregate-stats></comparator-aggregate-stats>
      </details>
      <details><summary>Δ distribution</summary>
        <comparator-delta-distribution></comparator-delta-distribution>
      </details>
    </div>`;
  }
  ```
- Remove imports of `score_histogram`, `metrics_by_slice`, `rationale_summary`, `custom_functions`, `charts`. Add imports for the three new components.

- [ ] **Step 5: Build smoke**

```bash
cd viewer/frontend && npm run build && cd -
```
Expected: clean build.

- [ ] **Step 6: Commit**

```bash
git add viewer/frontend/client/components/per_criterion_histograms.* \
        viewer/frontend/client/components/aggregate_stats.* \
        viewer/frontend/client/components/delta_distribution.* \
        viewer/frontend/client/app.ts
git commit -m "feat(viewer/frontend): per-criterion sidebar widgets"
```

### Task 3.4: Detail panel rewrite

**Files:**
- Modify: `viewer/frontend/client/components/example_details.ts`
- Modify: `viewer/frontend/client/components/example_details.css`

- [ ] **Step 1: Read current component**

Run: `wc -l viewer/frontend/client/components/example_details.ts viewer/frontend/client/components/example_details.css`
Expected: line counts to plan the rewrite footprint.

- [ ] **Step 2: Replace component body**

The component receives the current `Example` from `AppState.selectedExample`. Render layout:
1. Header: paragraph index, render-markdown toggle, show-diff toggle, close button.
2. Three-column source/A/B block. Render markdown via `marked` when `isRenderMarkdown` is true. When `isShowDiff` is true, run text diff between A and B and wrap added/removed spans.
3. Five criterion cards: for each `crit in CRITERIA`, show `final_score A | B (Δ)` heading and two paragraphs (`summary A`, `summary B`).

Use `marked.parse(text)` for markdown rendering inside `unsafeHTML(...)`. Use `jsdifflib`-based diff already imported in `lib/utils.ts` (`getTextDiff` + `renderDiffString`). 

Replace the file content with:

```typescript
/**
 * @license Apache-2.0
 *
 * Detail panel: stack layout (source/A/B + 5 criterion cards).
 */

import {MobxLitElement} from '@adobe/lit-mobx';
import {html} from 'lit';
import {customElement} from 'lit/decorators.js';
import {unsafeHTML} from 'lit/directives/unsafe-html.js';

import {marked} from 'marked';

import {core} from '../core';
import {getTextDiff, renderDiffString} from '../lib/utils';
import {AppState} from '../services/state_service';

import {styles} from './example_details.css';

const CRITERIA = ['accuracy', 'terminology', 'fluency', 'cultural', 'style'] as const;

@customElement('comparator-example-details')
export class ExampleDetailsElement extends MobxLitElement {
  private readonly appState = core.getService(AppState);
  static override get styles() { return [styles]; }

  private close = () => { this.appState.showSelectedExampleDetails = false; };

  private renderText(s: unknown): unknown {
    if (typeof s !== 'string') return '';
    if (this.appState.isRenderMarkdown) {
      try { return unsafeHTML(marked.parse(s) as string); } catch { return s; }
    }
    return html`<pre class="raw">${s}</pre>`;
  }

  private renderTexts() {
    const ex = this.appState.selectedExample!;
    const src = typeof ex.input_text === 'string' ? ex.input_text : '';
    const a = typeof ex.output_text_a === 'string' ? ex.output_text_a : '';
    const b = typeof ex.output_text_b === 'string' ? ex.output_text_b : '';
    let aBlock: unknown = this.renderText(a);
    let bBlock: unknown = this.renderText(b);
    if (this.appState.isShowDiff) {
      const diff = getTextDiff(a, b);
      aBlock = unsafeHTML(renderDiffString(diff.parsedA, diff.isEquals));
      bBlock = unsafeHTML(renderDiffString(diff.parsedB, diff.isEquals));
    }
    return html`
      <div class="texts">
        <div class="col"><h4>Source</h4><div class="body">${this.renderText(src)}</div></div>
        <div class="col"><h4>A</h4><div class="body">${aBlock}</div></div>
        <div class="col"><h4>B</h4><div class="body">${bBlock}</div></div>
      </div>`;
  }

  private renderCriterion(c: string) {
    const ex = this.appState.selectedExample!;
    const pair = (ex.custom_fields?.[c] as Array<number | null>) ?? [null, null];
    const delta = ex.custom_fields?.[`Δ ${c}`] as number | null | undefined;
    const rats = (ex.custom_fields?.[`${c} rationale`] as Array<string | null>) ?? [null, null];
    const fmt = (x: number | null) => x == null ? '—' : String(x);
    const dClass = typeof delta === 'number'
      ? (delta > 0 ? 'pos' : delta < 0 ? 'neg' : 'zero') : 'neg';
    return html`
      <div class="criterion">
        <h3>${c}
          <span class="scores">${fmt(pair[0])} | ${fmt(pair[1])}</span>
          <span class="delta ${dClass}">Δ ${typeof delta === 'number' ? (delta > 0 ? '+' : '') + delta : '—'}</span>
        </h3>
        <div class="rats">
          <div><strong>A:</strong> ${rats[0] ?? '—'}</div>
          <div><strong>B:</strong> ${rats[1] ?? '—'}</div>
        </div>
      </div>`;
  }

  override render() {
    const ex = this.appState.selectedExample;
    if (!ex) return html``;
    return html`
      <div class="header">
        <span>Paragraph ${ex.index}</span>
        <label><input type="checkbox" ?checked=${this.appState.isRenderMarkdown}
          @change=${(e: Event) => this.appState.isRenderMarkdown = (e.target as HTMLInputElement).checked}>
          markdown</label>
        <label><input type="checkbox" ?checked=${this.appState.isShowDiff}
          @change=${(e: Event) => this.appState.isShowDiff = (e.target as HTMLInputElement).checked}>
          diff</label>
        <button class="close" @click=${this.close}>×</button>
      </div>
      ${this.renderTexts()}
      ${CRITERIA.map(c => this.renderCriterion(c))}`;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'comparator-example-details': ExampleDetailsElement;
  }
}
```

Replace `example_details.css` with:

```css
:host { display: block; padding: 12px; overflow-y: auto; }

.header { display: flex; align-items: center; gap: 12px; padding-bottom: 8px; border-bottom: 1px solid #eee; }
.header span { font-weight: 600; }
.header label { font-size: 12px; color: #555; }
.header .close { margin-left: auto; border: none; background: transparent; font-size: 18px; cursor: pointer; }

.texts { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 16px; margin: 12px 0 24px; }
.texts h4 { margin: 0 0 6px; font-size: 12px; color: #666; text-transform: uppercase; }
.texts .body { font-size: 13px; line-height: 1.5; }
.texts .body pre.raw { white-space: pre-wrap; font-family: inherit; margin: 0; }

.criterion { padding: 12px 0; border-top: 1px solid #eee; }
.criterion h3 { display: flex; align-items: center; gap: 12px; margin: 0 0 8px; font-size: 14px; text-transform: capitalize; }
.criterion .scores { font-family: ui-monospace, monospace; font-weight: 500; }
.criterion .delta { font-size: 12px; padding: 2px 6px; border-radius: 4px; }
.criterion .delta.pos { background: #e6f4ea; color: #137333; }
.criterion .delta.neg { background: #fce8e6; color: #c5221f; }
.criterion .delta.zero { background: #eee; color: #555; }
.criterion .rats div { margin-bottom: 4px; font-size: 13px; }
```

- [ ] **Step 3: Build smoke**

```bash
cd viewer/frontend && npm run build && cd -
```
Expected: clean.

- [ ] **Step 4: Commit**

```bash
git add viewer/frontend/client/components/example_details.*
git commit -m "feat(viewer/frontend): detail panel stack with markdown + diff toggles"
```

### Task 3.5: Example table — hide noisy columns, add Σ Δ

**Files:**
- Modify: `viewer/frontend/client/services/state_service.ts` (initial visibility)
- Optional: add a computed `Σ Δ` field to adapter output OR derive on the frontend.

Since computing `Σ Δ` requires no backend change, derive on the client by extending the `custom_fields_schema` and `custom_fields` shape *after* fetch.

- [ ] **Step 1: Post-process datasets on load**

In `state_service.ts`, find where `loadData()` ends with `this.examples = data.examples`. Just before that assignment, walk `data.examples` and add `Σ Δ` to each `custom_fields`. Also extend `data.metadata.custom_fields_schema` with `{name: "Σ Δ", type: "number"}`. Hide `score`, `tags` from default visibility.

Pseudo-code addition:
```typescript
for (const ex of data.examples) {
  let s = 0; let any = false;
  for (const c of ['accuracy','terminology','fluency','cultural','style']) {
    const v = ex.custom_fields?.[`Δ ${c}`];
    if (typeof v === 'number') { s += v; any = true; }
  }
  ex.custom_fields['Σ Δ'] = any ? s : null;
}
const schema = data.metadata.custom_fields_schema as Array<{name: string; type: string}>;
schema.push({name: 'Σ Δ', type: 'number'});

// In the field-visibility map produced after load, force-hide:
//   FIELD_ID_FOR_SCORE, FIELD_ID_FOR_TAGS
//   rationale fields (per_model_text) — search for `.endsWith(' rationale')`
```

The exact place to set initial visibility is wherever AppState builds `fields[]` from the schema. Find it via `grep -n "visible" viewer/frontend/client/services/state_service.ts` and set `visible: false` for the noted ids.

- [ ] **Step 2: Build smoke**

```bash
cd viewer/frontend && npm run build && cd -
```

- [ ] **Step 3: Commit**

```bash
git add viewer/frontend/client/services/state_service.ts
git commit -m "feat(viewer/frontend): derive Σ Δ column and hide score/tags/rationales by default"
```

---

## Phase 4 — Deployment

### Task 4.1: Dockerfile

**Files:** Create `viewer/Dockerfile`

- [ ] **Step 1: Write Dockerfile**

```dockerfile
# syntax=docker/dockerfile:1.7
FROM node:20-alpine AS frontend
WORKDIR /work
COPY viewer/frontend ./viewer/frontend
RUN cd viewer/frontend && npm ci --no-audit --no-fund && npm run build

FROM python:3.12-slim AS runtime
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
COPY src/ ./src/
COPY viewer/__init__.py viewer/__init__.py
COPY viewer/backend ./viewer/backend
COPY --from=frontend /work/viewer/frontend/dist ./viewer/frontend/dist

RUN pip install --no-cache-dir uv && uv pip install --system .

ENV EVAL_ROOT=/data/pilot/evaluation
EXPOSE 8000
CMD ["uvicorn", "viewer.backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 2: Commit**

```bash
git add viewer/Dockerfile
git commit -m "build(viewer): Dockerfile multistage node+python"
```

### Task 4.2: `viewer/docker-compose.yml` and `viewer/Caddyfile`

**Files:** Create both.

- [ ] **Step 1: Write compose**

```yaml
services:
  viewer:
    build:
      context: ..
      dockerfile: viewer/Dockerfile
    environment:
      EVAL_ROOT: /data/pilot/evaluation
    volumes:
      - ../data/pilot/evaluation:/data/pilot/evaluation:ro
    expose:
      - "8000"

  caddy:
    image: caddy:2-alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
      - caddy_data:/data
      - caddy_config:/config
    depends_on: [viewer]

volumes:
  caddy_data:
  caddy_config:
```

- [ ] **Step 2: Write Caddyfile**

```caddy
# Replace `viewer.example.com` with the real domain on deploy.
viewer.example.com {
    reverse_proxy viewer:8000
}

# Local fallback: visit http://localhost:8080 in dev.
:8080 {
    reverse_proxy viewer:8000
}
```

- [ ] **Step 3: Commit**

```bash
git add viewer/docker-compose.yml viewer/Caddyfile
git commit -m "build(viewer): docker-compose + Caddyfile"
```

---

## Phase 5 — Playwright smoke

### Task 5.1: Add playwright optional dep + config

**Files:** Modify `pyproject.toml`, create `tests/viewer/conftest.py` helpers if needed.

- [ ] **Step 1: Add playwright extra**

In `pyproject.toml`, under `[project.optional-dependencies]`:
```toml
e2e = ["playwright>=1.45"]
```

Run: `uv sync --extra dev --extra e2e && uv run playwright install chromium`

- [ ] **Step 2: Write E2E test**

Create `tests/viewer/test_e2e.py`:

```python
"""Browser smoke test for the viewer.

Requires the optional `e2e` extras and Playwright Chromium installed.
Skipped automatically if either is missing.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

import pytest

pw = pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    repo_root = Path(__file__).resolve().parents[2]
    # Real data only if pilot fixture exists. Otherwise build a tiny tree.
    eval_root = tmp_path_factory.mktemp("eval")
    for run, variant, judge in [("a", "v1", "j"), ("b", "v1", "j")]:
        (eval_root / run / variant / "reports").mkdir(parents=True)
        (eval_root / run / variant / "comparison.jsonl").write_text(
            json.dumps({"id": 0, "source": "Hello", "translated": f"{run}-tx",
                        "scores": {judge: {c: 9 for c in
                                           ["accuracy","terminology","fluency","cultural","style"]}}}) + "\n"
        )
        rep = {"id": 0, "source": "Hello", "translated": f"{run}-tx"}
        for c in ["accuracy","terminology","fluency","cultural","style"]:
            rep[c] = {"final_score": 9, "summary": f"{run}-{c}-summary",
                      "criteria_assessment": {}}
        (eval_root / run / variant / "reports/j.jsonl").write_text(json.dumps(rep) + "\n")

    proc = subprocess.Popen(
        ["uv", "run", "uvicorn", "viewer.backend.main:app",
         "--host", "127.0.0.1", "--port", "8765"],
        cwd=repo_root,
        env={**__import__("os").environ, "EVAL_ROOT": str(eval_root)},
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    for _ in range(50):
        time.sleep(0.2)
        try:
            import urllib.request
            urllib.request.urlopen("http://127.0.0.1:8765/api/datasets", timeout=1)
            break
        except Exception:
            continue
    else:
        proc.terminate()
        pytest.fail("viewer did not become healthy")
    yield "http://127.0.0.1:8765"
    proc.terminate()
    proc.wait(timeout=10)


def test_picker_to_table(server):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(server)
        page.wait_for_selector("comparator-catalog-picker", state="attached")
        # Set the dropdowns via the DOM since they're inside a shadow root.
        page.evaluate(
            """
            const picker = document.querySelector('comparator-catalog-picker');
            const root = picker.shadowRoot;
            const sels = root.querySelectorAll('select');
            const change = (el, val) => { el.value = val; el.dispatchEvent(new Event('change')); };
            change(sels[0], 'a');   // Run A
            change(sels[1], 'v1');  // Variant A
            change(sels[2], 'j');   // Judge A
            change(sels[3], 'b');   // Run B
            change(sels[4], 'v1');  // Variant B
            change(sels[5], 'j');   // Judge B
            root.querySelector('button.btn.primary').click();
            """
        )
        page.wait_for_selector("comparator-example-table", state="attached", timeout=10_000)
        page.wait_for_function(
            """() => {
                const t = document.querySelector('comparator-example-table');
                if (!t) return false;
                const rows = t.shadowRoot.querySelectorAll('tr');
                return rows.length >= 2;
            }""",
            timeout=10_000,
        )
        browser.close()
```

- [ ] **Step 3: Run E2E (only if frontend built)**

```bash
cd viewer/frontend && npm run build && cd -
uv run python -m pytest tests/viewer/test_e2e.py -v
```
Expected: passes.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml tests/viewer/test_e2e.py
git commit -m "test(viewer): playwright smoke for picker → table"
```

---

## Phase 6 — Documentation sync

### Task 6.1: Viewer README

**Files:** Create `viewer/README.md`

- [ ] **Step 1: Write README**

```markdown
# Translation Comparison Viewer

UI for the GSE-translation project — see paragraphs, two translations side by side, judge scores per criterion. Built on a fork of [PAIR-code/llm-comparator](https://github.com/PAIR-code/llm-comparator), fed by a FastAPI backend that reads `data/pilot/evaluation/`.

## Quick start (local)

```bash
uv sync --extra dev
cd viewer/frontend && npm install && npm run build && cd -
uv run uvicorn viewer.backend.main:app --reload --port 8000
# open http://localhost:8000
```

`EVAL_ROOT` (env var) lets you point at a different evaluation tree.

## Production (Caddy + Docker)

```bash
cd viewer
docker compose up -d
```

Edit `Caddyfile` to swap `viewer.example.com` for your real domain — Caddy obtains a Let's Encrypt certificate automatically.

## Layout

- `backend/` — FastAPI app, JSONL→JSON adapter, catalog scanner. Tests in `tests/viewer/`.
- `frontend/` — vendored snapshot of upstream llm-comparator + modifications. See `UPSTREAM.md`.

Design: [docs/superpowers/specs/2026-05-15-translation-viewer-design.md](../docs/superpowers/specs/2026-05-15-translation-viewer-design.md).
```

- [ ] **Step 2: Commit**

```bash
git add viewer/README.md
git commit -m "docs(viewer): operating guide"
```

### Task 6.2: Cross-references in repo-level docs

**Files:** Modify `README.md`, `docs/pipeline.md`.

- [ ] **Step 1: Add link in pipeline doc**

In `docs/pipeline.md`, append a section near the bottom:

```markdown
## Reviewing results — Translation Comparison Viewer

See [viewer/README.md](../viewer/README.md). It hosts a small FastAPI app + frontend on top of `data/pilot/evaluation/`, lets the expert browse paragraphs side by side, and shows per-criterion judge scores and summaries. Design in [docs/superpowers/specs/2026-05-15-translation-viewer-design.md](superpowers/specs/2026-05-15-translation-viewer-design.md).
```

- [ ] **Step 2: Add small link in README**

Append a one-liner under the relevant section of `README.md` pointing to `viewer/README.md`.

- [ ] **Step 3: Commit**

```bash
git add README.md docs/pipeline.md
git commit -m "docs(viewer): cross-reference viewer from README + pipeline"
```

---

## Self-Review Checklist

After each phase, run:

```bash
uv run python -m pytest -q
cd viewer/frontend && npm run build && cd -
```

Both must come back clean before moving to the next phase. After Phase 5, also run the e2e test.

---

## Status

Draft — ready for subagent-driven execution.
