# Scoring v1-only Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Roll back to 6 single-criterion judge prompts in `prompts/03_scoring/v1/`, drop the consolidated path entirely, replace `score=-1` soft fallback with fail-fast + diagnostic `parse_failures.jsonl`, and make the dispatcher generic enough to pick up future `v2/`, `v3/` variants by filename discovery alone.

**Architecture:** Single-path dispatcher: `run_scoring` loads prompts once from `prompts/03_scoring/<variant>/*.md` (filename = criterion name), threads `criteria: list[str]` through `_score_run_for_judge`, `build_merged_jsonl`, `build_aggregate_scores`. `score_paragraph` fires N criterion prompts in parallel via `asyncio.gather` with inline retry of up to 2 attempts on parse failure. A `JudgeParseError` exception replaces the soft `score=-1` fallback; raw responses go to `<judge>/parse_failures.jsonl` for human inspection. After 3 escalations for the same `(paragraph_id, criterion)`, a terminal `score: null` row is written. No `response_format` plumbing — JSON instruction lives in prompts only.

**Tech Stack:** Python 3.11, pydantic v2, pytest, `asyncio.gather`, openai/anthropic SDKs (already in place).

**Spec:** [docs/superpowers/specs/2026-05-14-scoring-v1-only-design.md](../specs/2026-05-14-scoring-v1-only-design.md) — D1–D13.

---

## File Structure

**Created:**
- `prompts/03_scoring/v1/` (via rename from `old/`)
- `docs/known_issues.md` — top-level pitfalls doc, 4 entries.
- `scripts/03_cleanup_minus_one.py` — one-shot data scrubber.

**Modified:**
- `src/palimpsest/scoring.py` — heavy refactor (~50% of file).
- `src/palimpsest/config.py` — drop `JudgeConfig.variant`, change `prompts_variant: str = "v1"`, add soft-warning validator.
- `src/palimpsest/llm/client.py` — remove dead `response_format` plumbing.
- All 9 `configs/scoring/*.yaml` — `prompts_variant: v1`.
- `tests/conftest.py` — swap consolidated helpers for single-criterion.
- `tests/test_scoring_*.py` (5 files) — rewrites per spec.
- `docs/stages/03_scoring.md`, `docs/pipeline.md`, `CLAUDE.md` — sync with new architecture.
- `README.md` — pitch check, edit if mentions consolidated.

**Deleted:**
- `prompts/03_scoring/full/`, `prompts/03_scoring/compact/`
- `tests/test_scoring_strategy_consolidated.py`

**Renamed:**
- `tests/test_scoring_strategy_legacy.py` → `tests/test_scoring_strategy.py`

---

## Task 1: Prompts directory rename + cleanup

**Files:**
- Move: `prompts/03_scoring/old/` → `prompts/03_scoring/v1/`
- Delete: `prompts/03_scoring/full/`, `prompts/03_scoring/compact/`

- [ ] **Step 1: Verify current state**

```bash
ls prompts/03_scoring/
```
Expected: `compact  full  old`. v1 must not exist yet.

- [ ] **Step 2: Rename old → v1**

```bash
git mv prompts/03_scoring/old prompts/03_scoring/v1
```

- [ ] **Step 3: Delete full and compact**

```bash
git rm -r prompts/03_scoring/full prompts/03_scoring/compact
```

- [ ] **Step 4: Verify result**

```bash
ls prompts/03_scoring/ && ls prompts/03_scoring/v1/
```
Expected:
- `prompts/03_scoring/` shows only `v1`
- `prompts/03_scoring/v1/` shows 6 files: `accuracy.md  consistency.md  cultural.md  fluency.md  style.md  terminology.md`

- [ ] **Step 5: Verify each v1 prompt has JSON-only output instruction**

For each of `accuracy.md`, `consistency.md`, `cultural.md`, `fluency.md`, `style.md`, `terminology.md`:
- Open the file, scroll to the end.
- Confirm it contains an explicit instruction like "Respond with a valid JSON object and nothing else" and a JSON skeleton showing `"final_score": <int>`.
- If any prompt lacks this instruction, append a standard footer (copy from `accuracy.md`'s footer for consistency).

- [ ] **Step 6: Commit**

```bash
git add prompts/03_scoring/
git commit -m "prompts(scoring): rename old → v1, drop full and compact variants"
```

---

## Task 2: Update scoring YAML configs to prompts_variant: v1

**Files:**
- Modify: `configs/scoring/01-top-vs-baseline.yaml`, `configs/scoring/02-large-chunking.yaml`, `configs/scoring/03-small-anchor.yaml`, `configs/scoring/04-small-chunking.yaml`, `configs/scoring/05-family-and-alt.yaml`, `configs/scoring/06-reasoning-low.yaml`, `configs/scoring/large-low.yaml`, `configs/scoring/small-low.yaml`, `configs/scoring/smoke.yaml`

- [ ] **Step 1: Audit current values**

```bash
grep -H 'prompts_variant' configs/scoring/*.yaml
```
Expected: 8 files show `full`, 1 file (`small-low.yaml`) shows `compact`.

- [ ] **Step 2: Replace `prompts_variant: full` with `prompts_variant: v1` in 8 files**

For each of 01..06, `large-low.yaml`, `smoke.yaml` — change `prompts_variant: full` to `prompts_variant: v1` (Edit tool, exact string match).

- [ ] **Step 3: Replace `prompts_variant: compact` with `prompts_variant: v1` in `small-low.yaml`**

```yaml
# Before
prompts_variant: compact
# After
prompts_variant: v1
```

- [ ] **Step 4: Check for per-judge `variant:` overrides**

```bash
grep -H 'variant:' configs/scoring/*.yaml | grep -v prompts_variant
```
Expected: empty output. If anything matches, remove that `variant:` line from each judge entry.

- [ ] **Step 5: Verify all files now declare v1**

```bash
grep -H 'prompts_variant' configs/scoring/*.yaml
```
Expected: all 9 lines say `prompts_variant: v1`.

- [ ] **Step 6: Commit**

```bash
git add configs/scoring/
git commit -m "configs(scoring): switch all profiles to prompts_variant: v1"
```

---

## Task 3: Add JudgeParseError exception class

**Files:**
- Modify: `src/palimpsest/scoring.py` (add after existing imports, before `ParagraphKind`)
- Test: `tests/test_scoring_strategy_legacy.py` (will be renamed in Task 16)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_scoring_strategy_legacy.py`:

```python
def test_judge_parse_error_carries_diagnostic_fields():
    from palimpsest.scoring import JudgeParseError
    exc = JudgeParseError(criterion="fluency", raw="not json", reason="json_decode")
    assert exc.criterion == "fluency"
    assert exc.raw == "not json"
    assert exc.reason == "json_decode"
    assert "fluency" in str(exc)
    assert "json_decode" in str(exc)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
unset VIRTUAL_ENV && uv run --extra dev pytest tests/test_scoring_strategy_legacy.py::test_judge_parse_error_carries_diagnostic_fields -v
```
Expected: FAIL with `ImportError: cannot import name 'JudgeParseError' from 'palimpsest.scoring'`.

- [ ] **Step 3: Add JudgeParseError class**

In `src/palimpsest/scoring.py`, after the existing imports block and before `ParagraphKind`:

```python
class JudgeParseError(Exception):
    """Raised when an LLM response cannot be parsed into a valid judge payload.

    Carries the raw response and a categorical reason so the dispatcher can
    persist diagnostic info to <judge>/parse_failures.jsonl before escalation.
    Reasons: "empty" | "json_decode" | "missing_score" | "score_out_of_range".
    """

    def __init__(self, criterion: str, raw: str, reason: str):
        self.criterion = criterion
        self.raw = raw
        self.reason = reason
        super().__init__(f"{criterion}: {reason}")
```

- [ ] **Step 4: Run test to verify it passes**

```bash
unset VIRTUAL_ENV && uv run --extra dev pytest tests/test_scoring_strategy_legacy.py::test_judge_parse_error_carries_diagnostic_fields -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/palimpsest/scoring.py tests/test_scoring_strategy_legacy.py
git commit -m "feat(scoring): add JudgeParseError for parse-failure diagnostics"
```

---

## Task 4: Refactor parse_judge_response to raise on failure

**Files:**
- Modify: `src/palimpsest/scoring.py` (replace `parse_judge_response` body and signature)
- Test: `tests/test_scoring_strategy_legacy.py`

- [ ] **Step 1: Write failing tests**

Append:

```python
def test_parse_judge_response_returns_valid_payload():
    from palimpsest.scoring import parse_judge_response
    raw = '```json\n{"final_score": 8, "summary": "ok"}\n```'
    parsed = parse_judge_response(raw, criterion="accuracy")
    assert parsed["final_score"] == 8
    assert parsed["summary"] == "ok"

def test_parse_judge_response_raises_on_empty():
    from palimpsest.scoring import parse_judge_response, JudgeParseError
    import pytest
    with pytest.raises(JudgeParseError) as exc:
        parse_judge_response("", criterion="accuracy")
    assert exc.value.reason == "empty"

def test_parse_judge_response_raises_on_malformed_json():
    from palimpsest.scoring import parse_judge_response, JudgeParseError
    import pytest
    with pytest.raises(JudgeParseError) as exc:
        parse_judge_response("not json at all", criterion="accuracy")
    assert exc.value.reason.startswith("json_decode")
    assert exc.value.raw == "not json at all"

def test_parse_judge_response_raises_on_missing_score():
    from palimpsest.scoring import parse_judge_response, JudgeParseError
    import pytest
    with pytest.raises(JudgeParseError) as exc:
        parse_judge_response('{"summary": "ok"}', criterion="accuracy")
    assert exc.value.reason == "missing_score"

def test_parse_judge_response_raises_on_score_out_of_range():
    from palimpsest.scoring import parse_judge_response, JudgeParseError
    import pytest
    with pytest.raises(JudgeParseError) as exc:
        parse_judge_response('{"final_score": 99}', criterion="accuracy")
    assert exc.value.reason == "score_out_of_range"

def test_parse_judge_response_raises_on_score_zero():
    from palimpsest.scoring import parse_judge_response, JudgeParseError
    import pytest
    with pytest.raises(JudgeParseError) as exc:
        parse_judge_response('{"final_score": 0}', criterion="accuracy")
    assert exc.value.reason == "score_out_of_range"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
unset VIRTUAL_ENV && uv run --extra dev pytest tests/test_scoring_strategy_legacy.py -k parse_judge_response -v
```
Expected: 6 FAIL — most will fail because the old signature returns `{-1, raw}` dict, no exception.

- [ ] **Step 3: Rewrite parse_judge_response**

In `src/palimpsest/scoring.py`, replace the existing `parse_judge_response` function body entirely:

```python
def parse_judge_response(raw: str, criterion: str) -> dict:
    """Extract a JSON object from a judge response and validate `final_score`.

    Handles markdown ```json fences and prose before/after the JSON.
    Raises JudgeParseError on any failure (empty / malformed / missing score /
    out-of-range). Caller is responsible for catching and persisting raw
    to parse_failures.jsonl before re-raising for escalation.
    """
    if not raw or not raw.strip():
        raise JudgeParseError(criterion, raw or "", "empty")
    match = _JSON_FENCE.search(raw)
    candidate = match.group(1) if match else raw
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise JudgeParseError(criterion, raw, f"json_decode: {exc.msg}") from exc
    if not isinstance(parsed, dict):
        raise JudgeParseError(criterion, raw, "json_decode: not an object")
    score = parsed.get("final_score")
    if not isinstance(score, int) or isinstance(score, bool):
        raise JudgeParseError(criterion, raw, "missing_score")
    if not 1 <= score <= 10:
        raise JudgeParseError(criterion, raw, "score_out_of_range")
    return parsed
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
unset VIRTUAL_ENV && uv run --extra dev pytest tests/test_scoring_strategy_legacy.py -k parse_judge_response -v
```
Expected: 6 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/palimpsest/scoring.py tests/test_scoring_strategy_legacy.py
git commit -m "refactor(scoring): parse_judge_response raises on failure instead of soft -1 fallback"
```

---

## Task 5: Refactor load_prompts to filename-driven discovery

**Files:**
- Modify: `src/palimpsest/scoring.py` (replace `load_prompts`)
- Test: `tests/test_scoring_prompts.py` (will be largely rewritten in Task 19; here just adjust the new contract)

- [ ] **Step 1: Write failing tests**

Replace the entire contents of `tests/test_scoring_prompts.py` with:

```python
from pathlib import Path

import pytest

from palimpsest.scoring import load_prompts


@pytest.fixture
def prompts_root(tmp_path):
    root = tmp_path / "prompts" / "03_scoring"
    v1 = root / "v1"
    v1.mkdir(parents=True)
    for c in ("accuracy", "fluency", "style"):
        (v1 / f"{c}.md").write_text(f"PROMPT FOR {c}", encoding="utf-8")
    return root


def test_load_prompts_returns_filename_stem_to_text(prompts_root):
    p = load_prompts(prompts_root, "v1")
    assert p == {
        "accuracy": "PROMPT FOR accuracy",
        "fluency": "PROMPT FOR fluency",
        "style": "PROMPT FOR style",
    }


def test_load_prompts_keys_are_sorted(prompts_root):
    keys = list(load_prompts(prompts_root, "v1").keys())
    assert keys == sorted(keys)


def test_load_prompts_picks_up_new_variant(tmp_path):
    root = tmp_path / "prompts" / "03_scoring"
    v2 = root / "v2"
    v2.mkdir(parents=True)
    for c in ("alpha", "beta", "gamma", "delta", "epsilon"):
        (v2 / f"{c}.md").write_text(f"V2 {c}", encoding="utf-8")
    p = load_prompts(root, "v2")
    assert set(p.keys()) == {"alpha", "beta", "gamma", "delta", "epsilon"}
    assert list(p.keys()) == sorted(p.keys())


def test_load_prompts_raises_on_missing_dir(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_prompts(tmp_path, "nonexistent")


def test_load_prompts_raises_on_empty_dir(tmp_path):
    empty = tmp_path / "prompts" / "v_empty"
    empty.mkdir(parents=True)
    with pytest.raises(FileNotFoundError):
        load_prompts(tmp_path / "prompts", "v_empty")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
unset VIRTUAL_ENV && uv run --extra dev pytest tests/test_scoring_prompts.py -v
```
Expected: most FAIL — current `load_prompts` branches on `"old"` and returns different shapes.

- [ ] **Step 3: Rewrite load_prompts**

In `src/palimpsest/scoring.py`, replace the entire `load_prompts` function:

```python
def load_prompts(prompts_root: Path, variant: str) -> dict[str, str]:
    """Load all `*.md` prompts from `prompts_root/variant/`.

    Each `.md` file = one criterion. Returns `{filename_stem: file_text}` with
    keys in sorted order for deterministic JSONL column ordering. Raises
    FileNotFoundError if the directory is missing or contains no `.md` files.
    """
    variant_dir = prompts_root / variant
    if not variant_dir.is_dir():
        raise FileNotFoundError(
            f"prompts variant directory not found: {variant_dir}"
        )
    files = sorted(variant_dir.glob("*.md"))
    if not files:
        raise FileNotFoundError(
            f"no *.md prompts found in {variant_dir}"
        )
    return {f.stem: f.read_text(encoding="utf-8") for f in files}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
unset VIRTUAL_ENV && uv run --extra dev pytest tests/test_scoring_prompts.py -v
```
Expected: 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/palimpsest/scoring.py tests/test_scoring_prompts.py
git commit -m "refactor(scoring): load_prompts now filename-driven, sorts keys"
```

---

## Task 6: Refactor score_legacy → score_paragraph with inline retry

**Files:**
- Modify: `src/palimpsest/scoring.py` (replace `score_legacy` and add retry constant)
- Test: `tests/test_scoring_strategy_legacy.py`

- [ ] **Step 1: Write failing tests**

Replace the entire contents of `tests/test_scoring_strategy_legacy.py` with (the previously-added tests from Tasks 3-4 plus new ones; preserve them):

```python
from unittest.mock import AsyncMock, call

import pytest

from palimpsest.scoring import (
    JudgeParseError,
    parse_judge_response,
    score_paragraph,
)


# ---- JudgeParseError ----

def test_judge_parse_error_carries_diagnostic_fields():
    exc = JudgeParseError(criterion="fluency", raw="not json", reason="json_decode")
    assert exc.criterion == "fluency"
    assert exc.raw == "not json"
    assert exc.reason == "json_decode"
    assert "fluency" in str(exc)
    assert "json_decode" in str(exc)


# ---- parse_judge_response ----

def test_parse_judge_response_returns_valid_payload():
    raw = '```json\n{"final_score": 8, "summary": "ok"}\n```'
    parsed = parse_judge_response(raw, criterion="accuracy")
    assert parsed["final_score"] == 8
    assert parsed["summary"] == "ok"


def test_parse_judge_response_raises_on_empty():
    with pytest.raises(JudgeParseError) as exc:
        parse_judge_response("", criterion="accuracy")
    assert exc.value.reason == "empty"


def test_parse_judge_response_raises_on_malformed_json():
    with pytest.raises(JudgeParseError) as exc:
        parse_judge_response("not json at all", criterion="accuracy")
    assert exc.value.reason.startswith("json_decode")
    assert exc.value.raw == "not json at all"


def test_parse_judge_response_raises_on_missing_score():
    with pytest.raises(JudgeParseError) as exc:
        parse_judge_response('{"summary": "ok"}', criterion="accuracy")
    assert exc.value.reason == "missing_score"


def test_parse_judge_response_raises_on_score_out_of_range():
    with pytest.raises(JudgeParseError) as exc:
        parse_judge_response('{"final_score": 99}', criterion="accuracy")
    assert exc.value.reason == "score_out_of_range"


def test_parse_judge_response_raises_on_score_zero():
    with pytest.raises(JudgeParseError) as exc:
        parse_judge_response('{"final_score": 0}', criterion="accuracy")
    assert exc.value.reason == "score_out_of_range"


# ---- score_paragraph ----

_VALID_JSON = '```json\n{"final_score": 8, "summary": "ok"}\n```'


@pytest.fixture
def fake_client():
    c = AsyncMock()
    c.complete.return_value = _VALID_JSON
    return c


@pytest.mark.asyncio
async def test_score_paragraph_returns_one_dict_per_criterion(fake_client):
    prompts = {c: f"P {c}" for c in ["accuracy", "fluency", "style"]}
    out = await score_paragraph(fake_client, "ru", "en", prompts)
    assert set(out.keys()) == set(prompts.keys())
    for payload in out.values():
        assert payload["final_score"] == 8


@pytest.mark.asyncio
async def test_score_paragraph_invokes_client_once_per_criterion(fake_client):
    prompts = {c: f"P {c}" for c in ["accuracy", "fluency", "style"]}
    await score_paragraph(fake_client, "ru", "en", prompts)
    assert fake_client.complete.call_count == 3


@pytest.mark.asyncio
async def test_score_paragraph_retries_once_on_parse_failure_then_succeeds():
    c = AsyncMock()
    c.complete.side_effect = ["not json", _VALID_JSON]
    prompts = {"accuracy": "P"}
    out = await score_paragraph(c, "ru", "en", prompts)
    assert out["accuracy"]["final_score"] == 8
    assert c.complete.call_count == 2


@pytest.mark.asyncio
async def test_score_paragraph_raises_after_exhausting_retries():
    c = AsyncMock()
    c.complete.side_effect = ["not json", "still not json"]
    prompts = {"accuracy": "P"}
    with pytest.raises(JudgeParseError) as exc:
        await score_paragraph(c, "ru", "en", prompts)
    assert exc.value.criterion == "accuracy"
    assert c.complete.call_count == 2  # 1 initial + 1 retry = _MAX_PARSE_ATTEMPTS


@pytest.mark.asyncio
async def test_score_paragraph_propagates_first_failure_among_concurrent_criteria():
    c = AsyncMock()
    # accuracy fails twice, fluency succeeds — gather() raises the first exc.
    call_count = {"accuracy": 0, "fluency": 0}

    async def _complete(system, user, **kw):
        if "ACC" in system:
            call_count["accuracy"] += 1
            return "not json"
        call_count["fluency"] += 1
        return _VALID_JSON

    c.complete.side_effect = _complete
    prompts = {"accuracy": "ACC", "fluency": "FLU"}
    with pytest.raises(JudgeParseError):
        await score_paragraph(c, "ru", "en", prompts)
    assert call_count["accuracy"] == 2
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
unset VIRTUAL_ENV && uv run --extra dev pytest tests/test_scoring_strategy_legacy.py -v
```
Expected: many FAIL — `score_paragraph` doesn't exist; old code returns `-1`.

- [ ] **Step 3: Rewrite score_legacy → score_paragraph**

In `src/palimpsest/scoring.py`:

a) Add constant near the top (after `_USER_MSG_TEMPLATE` definition or near `parse_judge_response`):

```python
_MAX_PARSE_ATTEMPTS: int = 2  # 1 initial + 1 retry; see spec D12.
```

b) Replace the entire `score_legacy` function (and remove `score_consolidated` while we're at it — covered in Task 7 too, but easier to drop here):

```python
async def score_paragraph(
    client: LLMClient,
    source: str,
    translated: str,
    prompts: dict[str, str],
) -> dict[str, dict]:
    """Fire N single-criterion prompts in parallel for one paragraph.

    Returns {criterion: parsed_payload} on success. Raises JudgeParseError
    after exhausting _MAX_PARSE_ATTEMPTS inline retries for any criterion;
    siblings whose retries succeed are dropped (the dispatcher handles
    escalation per-paragraph, not per-criterion).
    """
    user_msg = _USER_MSG_TEMPLATE.format(source, translated)

    async def _one(criterion: str, prompt: str) -> tuple[str, dict]:
        last_exc: JudgeParseError | None = None
        for attempt in range(_MAX_PARSE_ATTEMPTS):
            raw = await client.complete(system=prompt, user=user_msg)
            try:
                return criterion, parse_judge_response(raw, criterion)
            except JudgeParseError as exc:
                last_exc = exc
                if attempt + 1 < _MAX_PARSE_ATTEMPTS:
                    print(
                        f"warning: parse failure for {criterion} "
                        f"(attempt {attempt+1}/{_MAX_PARSE_ATTEMPTS}, "
                        f"reason={exc.reason}); retrying",
                        flush=True,
                    )
        assert last_exc is not None
        raise last_exc

    results = await asyncio.gather(*(_one(c, p) for c, p in prompts.items()))
    return dict(results)
```

(Keep old `score_legacy` reference removed — it's replaced by `score_paragraph`.)

- [ ] **Step 4: Run tests to verify they pass**

```bash
unset VIRTUAL_ENV && uv run --extra dev pytest tests/test_scoring_strategy_legacy.py -v
```
Expected: all PASS (12 tests).

- [ ] **Step 5: Commit**

```bash
git add src/palimpsest/scoring.py tests/test_scoring_strategy_legacy.py
git commit -m "refactor(scoring): rename score_legacy → score_paragraph with inline parse retry"
```

---

## Task 7: Drop dead code (constants, score_consolidated, helpers)

**Files:**
- Modify: `src/palimpsest/scoring.py`

- [ ] **Step 1: Remove constants and dead functions**

In `src/palimpsest/scoring.py`, delete these blocks:

a) `LEGACY_CRITERIA: list[str] = [...]` declaration (whole block).

b) `CONSOLIDATED_PROMPTS: dict[str, list[str]] = {...}` declaration.

c) `SCORE_LLM_FAIL: Final[int] = -1` line (keep `SCORE_SKIPPED: Final[None] = None`).

d) `_JUDGE_RESPONSE_FORMAT = {"type": "json_object"}` line (and its surrounding comment block).

e) `async def score_consolidated(...)` function in its entirety.

f) `async def _resolve_variant(...)` helper.

g) `async def _score_paragraph(...)` wrapper function. (Note: this is the underscore-prefixed wrapper that branched on variant; the public `score_paragraph` from Task 6 replaces it.)

- [ ] **Step 2: Replace remaining usages of LEGACY_CRITERIA inside _score_run_for_judge with `criteria` argument**

Find every `LEGACY_CRITERIA` reference in `_score_run_for_judge` — replace with the function's new `criteria` parameter (will be added in Task 10).

Temporary placeholder for this step: leave `LEGACY_CRITERIA` references intact for now, but reference them via a new local variable `criteria = sorted(prompts.keys())` defined at the top of the function. We'll properly thread it through in Task 10.

Actually, simpler: keep the constant definition removed; let pytest fail; Task 10 fixes by threading.

- [ ] **Step 3: Verify scoring.py at least imports correctly**

```bash
unset VIRTUAL_ENV && uv run --extra dev python -c "import palimpsest.scoring"
```
Expected: should fail with `NameError: name 'LEGACY_CRITERIA' is not defined` — proves the dead code is gone. We'll fix references in subsequent tasks.

- [ ] **Step 4: Stage but don't commit yet** — this is part of a contiguous refactor; commit at end of Task 10 once `_score_run_for_judge` is fixed.

---

## Task 8: Change ScoringConfig.prompts_variant type + soft validator

**Files:**
- Modify: `src/palimpsest/config.py`
- Test: `tests/test_scoring_config.py`

- [ ] **Step 1: Update failing tests for new contract**

Replace the entire contents of `tests/test_scoring_config.py` with:

```python
from pathlib import Path

import pytest
from pydantic import ValidationError

from palimpsest.config import FactcheckConfig, JudgeConfig, ScoringConfig


def test_judge_config_minimal():
    j = JudgeConfig(model="claude-opus-4.7-low")
    assert j.model == "claude-opus-4.7-low"


def test_judge_config_no_variant_field():
    # `variant` was removed per spec D2; constructing with it should be rejected.
    with pytest.raises(ValidationError):
        JudgeConfig(model="x", variant="anything")  # type: ignore[call-arg]


def test_factcheck_config_defaults():
    f = FactcheckConfig()
    assert f.enabled is True
    assert f.judge == "gpt-5.4-mini-low"


def test_scoring_config_defaults_and_required(tmp_path, capsys):
    cfg = ScoringConfig(
        base_dir=Path("data/pilot"),
        judges=[JudgeConfig(model="claude-opus-4.7-low")],
        runs=["large/claude-opus-4.7-low_par_by_par"],
    )
    assert cfg.prompts_variant == "v1"
    assert cfg.translations_subdir == "translating"
    assert cfg.evaluation_subdir == "evaluation"
    assert cfg.max_concurrency == 64
    assert cfg.factcheck.enabled is True


def test_scoring_config_accepts_arbitrary_variant_string():
    # Per D2 + D7: type is `str`, not Literal. Validation is a soft warning.
    cfg = ScoringConfig(
        base_dir=Path("data/pilot"),
        judges=[JudgeConfig(model="x")],
        runs=["a/b"],
        prompts_variant="v2_experimental",
    )
    assert cfg.prompts_variant == "v2_experimental"


def test_scoring_config_warns_when_variant_dir_missing(tmp_path, capsys):
    # Soft warning, not error.
    ScoringConfig(
        base_dir=Path("data/pilot"),
        judges=[JudgeConfig(model="x")],
        runs=["a/b"],
        prompts_root=tmp_path / "does_not_exist",
        prompts_variant="v1",
    )
    captured = capsys.readouterr()
    assert "does_not_exist" in captured.err or "v1" in captured.err


def test_scoring_config_no_warning_when_variant_dir_valid(tmp_path, capsys):
    v1 = tmp_path / "prompts" / "v1"
    v1.mkdir(parents=True)
    (v1 / "accuracy.md").write_text("ok")
    ScoringConfig(
        base_dir=Path("data/pilot"),
        judges=[JudgeConfig(model="x")],
        runs=["a/b"],
        prompts_root=tmp_path / "prompts",
        prompts_variant="v1",
    )
    captured = capsys.readouterr()
    assert "warning" not in captured.err.lower()


def test_scoring_config_rejects_empty_judges():
    with pytest.raises(ValidationError):
        ScoringConfig(
            base_dir=Path("data/pilot"),
            judges=[],
            runs=["large/x"],
        )
```

- [ ] **Step 2: Run tests to verify failures**

```bash
unset VIRTUAL_ENV && uv run --extra dev pytest tests/test_scoring_config.py -v
```
Expected: multiple FAIL on the new contract.

- [ ] **Step 3: Update config.py**

In `src/palimpsest/config.py`:

a) **Remove `JudgeConfig.variant` field.** Find:
```python
variant: Literal["old", "compact", "full"] | None = None
```
Delete this entire line.

b) **Change `ScoringConfig.prompts_variant` type** from `Literal[...]` to `str` with default `"v1"`:
```python
prompts_variant: str = "v1"
```

c) **Add the soft-warning model_validator.** At the bottom of `ScoringConfig`:
```python
@model_validator(mode="after")
def _warn_if_variant_dir_missing(self) -> "ScoringConfig":
    import sys
    variant_dir = self.prompts_root / self.prompts_variant
    if not variant_dir.is_dir() or not list(variant_dir.glob("*.md")):
        print(
            f"warning: prompts variant directory {variant_dir} "
            f"is missing or empty — load_prompts() will raise at runtime",
            file=sys.stderr,
            flush=True,
        )
    return self
```

d) Add the import: `from pydantic import BaseModel, Field, model_validator` (probably already has BaseModel/Field — add model_validator).

e) If you find an unused import `from typing import Literal`, remove it.

- [ ] **Step 4: Run tests to verify pass**

```bash
unset VIRTUAL_ENV && uv run --extra dev pytest tests/test_scoring_config.py -v
```
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/palimpsest/config.py tests/test_scoring_config.py
git commit -m "refactor(config): drop JudgeConfig.variant, prompts_variant becomes str with soft-warning validator"
```

---

## Task 9: Drop response_format plumbing in LLMClient

**Files:**
- Modify: `src/palimpsest/llm/client.py`
- Test: existing `tests/test_llm_client.py` should still pass (no test specifically asserts response_format support).

- [ ] **Step 1: Remove the response_format block from _complete_openai**

In `src/palimpsest/llm/client.py`, locate this block in `_complete_openai` (added in commit `5f46128`):

```python
        # Per-call JSON mode (OpenAI/OpenRouter standard). Scoring uses this to
        # force structured output on long judge prompts where gpt-5.5-low otherwise
        # collapses to free-form markdown. Caller passes response_format only when
        # the prompt itself instructs JSON output; OpenAI's JSON mode requires the
        # word "JSON" to appear in the prompt.
        response_format = overrides.get("response_format")
        if response_format is not None:
            kwargs["response_format"] = response_format
```

Delete the entire block (comment + 3 code lines).

- [ ] **Step 2: Run existing client tests to confirm nothing broke**

```bash
unset VIRTUAL_ENV && uv run --extra dev pytest tests/test_llm_client.py -v
```
Expected: all PASS (no test depends on response_format).

- [ ] **Step 3: Commit**

```bash
git add src/palimpsest/llm/client.py
git commit -m "refactor(llm): drop dead response_format override plumbing"
```

---

## Task 10: _score_run_for_judge — thread prompts/criteria; handle JudgeParseError

**Files:**
- Modify: `src/palimpsest/scoring.py` (function `_score_run_for_judge`)
- Test: will be covered by dispatcher tests in Task 17

- [ ] **Step 1: Add paths helper for parse_failures.jsonl**

In `src/palimpsest/paths.py`, find the existing `criterion_jsonl` helper. Add a sibling:

```python
def parse_failures_jsonl(
    base_dir: Path, evaluation_subdir: str, run: str, judge: str
) -> Path:
    """Diagnostic log for criterion-prompt parse failures. Append-only.
    Sibling to <criterion>_scores.jsonl files under <judge>/."""
    return judge_dir(base_dir, evaluation_subdir, run, judge) / "parse_failures.jsonl"
```

- [ ] **Step 2: Add _load_parse_failure_counts in scoring.py**

After `load_existing_ids`, add:

```python
def _load_parse_failure_counts(path: Path) -> dict[tuple[int, str], int]:
    """Count parse failures per (paragraph_id, criterion) from parse_failures.jsonl.
    Used by `_score_run_for_judge` to decide when to write a terminal-null row."""
    if not path.exists():
        return {}
    counts: dict[tuple[int, str], int] = {}
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            key = (row.get("id"), row.get("criterion"))
            if key[0] is None or key[1] is None:
                continue
            counts[key] = counts.get(key, 0) + 1
    return counts


_PERSISTENT_FAILURE_THRESHOLD: int = 3
```

- [ ] **Step 3: Update load_existing_ids to drop the -1 special case**

Replace the `load_existing_ids` body. Old version had:
```python
if row.get("score") == SCORE_LLM_FAIL:
    continue
```
Drop those two lines. New body:

```python
def load_existing_ids(path: Path) -> set[int]:
    """Return paragraph ids already persisted to this criterion-jsonl.

    Per spec D12: presence of a row = done. No more -1 sentinel filtering;
    parse failures don't write here, they write to parse_failures.jsonl.
    """
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
            if "id" in row:
                ids.add(row["id"])
    return ids
```

- [ ] **Step 4: Update _avg_excluding_nulls**

Replace:
```python
def _avg_excluding_nulls(values: list) -> float | None:
    valid = [v for v in values if v is not None and v != -1]
    if not valid:
        return None
    return sum(valid) / len(valid)
```
With:
```python
def _avg_excluding_nulls(values: list) -> float | None:
    valid = [v for v in values if v is not None]
    if not valid:
        return None
    return sum(valid) / len(valid)
```

- [ ] **Step 5: Rewrite _score_run_for_judge signature + body**

Replace the function entirely:

```python
async def _score_run_for_judge(
    *,
    cfg: ScoringConfig,
    run: str,
    judge: JudgeConfig,
    prompts: dict[str, str],
    criteria: list[str],
    max_paragraphs: int | None = None,
) -> None:
    """Run one (run × judge) pair. Per spec D12-D13:
    - Successful paragraph: append row(s) to <criterion>_scores.jsonl.
    - Parse failure: log raw to parse_failures.jsonl; escalate via failures list.
    - After _PERSISTENT_FAILURE_THRESHOLD failures for (id, criterion):
      write terminal {"score": null, "llm_report": "persistent_parse_failure_..."}.
    """
    client = _build_client(judge.model, max_concurrency=cfg.max_concurrency)

    ru_md = cfg.base_dir / "pilot_original.md"
    en_md = translation_md(cfg.base_dir, cfg.translations_subdir, run)
    pairs = _read_aligned_lines(ru_md, en_md, limit=max_paragraphs)

    target_paths = {
        c: criterion_jsonl(cfg.base_dir, cfg.evaluation_subdir, run, judge.model, c)
        for c in criteria
    }
    failures_path = parse_failures_jsonl(
        cfg.base_dir, cfg.evaluation_subdir, run, judge.model
    )
    existing = {c: load_existing_ids(p) for c, p in target_paths.items()}
    fail_counts = _load_parse_failure_counts(failures_path)
    write_lock = asyncio.Lock()
    variant = cfg.prompts_variant

    async def _persist_terminal_null(i: int, source: str, translated: str, criterion: str) -> None:
        row = {
            "id": i,
            "source": source,
            "translated": translated,
            "judge": judge.model,
            "variant": variant,
            "score": SCORE_SKIPPED,
            "llm_report": (
                f"persistent_parse_failure_after_{_PERSISTENT_FAILURE_THRESHOLD}_attempts; "
                f"see parse_failures.jsonl"
            ),
        }
        async with write_lock:
            append_jsonl_row(target_paths[criterion], row)

    async def _persist_failure_log(i: int, source: str, translated: str, exc: JudgeParseError) -> None:
        row = {
            "id": i,
            "criterion": exc.criterion,
            "reason": exc.reason,
            "raw": exc.raw,
            "source": source,
            "translated": translated,
            "judge": judge.model,
            "variant": variant,
            "ts": time.time(),
        }
        async with write_lock:
            append_jsonl_row(failures_path, row)

    async def _process(i: int, source: str, translated: str) -> None:
        # Terminal-null preemption: if any criterion is over threshold, write null
        # for those and reduce the prompt set sent to the LLM.
        prompts_for_this = dict(prompts)
        rows_to_write: dict[str, dict] = {}
        for c in criteria:
            if i in existing[c]:
                prompts_for_this.pop(c, None)
                continue
            if fail_counts.get((i, c), 0) >= _PERSISTENT_FAILURE_THRESHOLD:
                # Write terminal null and skip API call.
                await _persist_terminal_null(i, source, translated, c)
                prompts_for_this.pop(c, None)
        if not prompts_for_this:
            return

        kind = classify_paragraph(source)
        if kind == "translation_failed":
            print(f"warning: [TRANSLATION FAILED] at id={i} for {run}", flush=True)
        if kind in ("marker", "translation_failed"):
            reason = "marker" if kind == "marker" else "translation_failed"
            for criterion in prompts_for_this:
                payload = _skip_payload(reason)
                rows_to_write[criterion] = {
                    "id": i,
                    "source": source,
                    "translated": translated,
                    "judge": judge.model,
                    "variant": variant,
                    "score": SCORE_SKIPPED,
                    "llm_report": payload["llm_report"],
                }
            async with write_lock:
                for criterion, row in rows_to_write.items():
                    append_jsonl_row(target_paths[criterion], row)
            return

        try:
            results = await score_paragraph(client, source, translated, prompts_for_this)
        except JudgeParseError as exc:
            await _persist_failure_log(i, source, translated, exc)
            raise

        for criterion, payload in results.items():
            rows_to_write[criterion] = {
                "id": i,
                "source": source,
                "translated": translated,
                "judge": judge.model,
                "variant": variant,
                "score": payload.get("final_score"),
                "llm_report": json.dumps(payload, ensure_ascii=False),
            }
        async with write_lock:
            for criterion, row in rows_to_write.items():
                append_jsonl_row(target_paths[criterion], row)

    tasks = [_process(i, ru, en) for i, (ru, en) in enumerate(pairs)]
    failures: list[BaseException] = []
    with async_tqdm(total=len(tasks), desc=f"{run} × {judge.model}", file=sys.stderr) as bar:
        for coro in asyncio.as_completed(tasks):
            try:
                await coro
            except BaseException as exc:
                failures.append(exc)
                async_tqdm.write(
                    f"warning: paragraph failed for {judge.model}: {exc!r}",
                    file=sys.stderr,
                )
            bar.update(1)

    j_dir = judge_dir(cfg.base_dir, cfg.evaluation_subdir, run, judge.model)
    j_dir.mkdir(parents=True, exist_ok=True)
    meta = {"judge": judge.model, "variant": variant, "prompts": prompts}
    (j_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2))

    if failures:
        print(
            f"warning: {run} × {judge.model}: {len(failures)} paragraphs raised; "
            f"first error: {failures[0]!r}",
            file=sys.stderr,
            flush=True,
        )
        raise failures[0]
```

Note the new imports needed at the top of `scoring.py`: `from .paths import parse_failures_jsonl` (add to existing import block).

- [ ] **Step 6: Run unit tests so far**

```bash
unset VIRTUAL_ENV && uv run --extra dev pytest tests/test_scoring_strategy_legacy.py tests/test_scoring_prompts.py tests/test_scoring_config.py -v
```
Expected: PASS for the tests we wrote earlier. Dispatcher tests will be rewritten in Task 17.

- [ ] **Step 7: Commit**

```bash
git add src/palimpsest/scoring.py src/palimpsest/paths.py
git commit -m "refactor(scoring): _score_run_for_judge threads prompts/criteria; handles JudgeParseError via parse_failures.jsonl + terminal null"
```

---

## Task 11: Update build_merged_jsonl and build_aggregate_scores

**Files:**
- Modify: `src/palimpsest/scoring.py`

- [ ] **Step 1: Update build_merged_jsonl signature**

Find the function. Change signature to accept `criteria`:

```python
def build_merged_jsonl(
    run_dir: Path,
    *,
    judges: list[str],
    criteria: list[str],
    include_factcheck: bool,
    factcheck_judge: str | None = None,
) -> None:
```

In the body, replace every `LEGACY_CRITERIA` with `criteria`:

```python
    by_criterion: dict[str, dict[str, dict[int, dict]]] = {
        c: {j: _read_jsonl(run_dir / j / f"{c}_scores.jsonl") for j in judges}
        for c in criteria
    }
```

And:
```python
            for criterion in criteria:
```

- [ ] **Step 2: Update build_aggregate_scores signature**

```python
def build_aggregate_scores(
    evaluation_dir: Path,
    *,
    run_to_path: dict[str, str],
    judges: list[str],
    criteria: list[str],
    include_factcheck: bool,
) -> None:
```

Body: replace `for criterion in LEGACY_CRITERIA` with `for criterion in criteria`.

- [ ] **Step 3: No new tests** — these are pure parametrisation changes. Existing dispatcher tests (after Task 17) cover end-to-end behavior.

- [ ] **Step 4: Commit** (will commit together with Task 12 since they belong to the same refactor)

---

## Task 12: run_scoring pre-loads prompts and threads criteria

**Files:**
- Modify: `src/palimpsest/scoring.py`

- [ ] **Step 1: Update run_scoring**

Replace the relevant part:

```python
async def run_scoring(cfg: ScoringConfig, *, max_paragraphs: int | None = None) -> None:
    """Main entry. Per spec D6: load prompts once; thread criteria through."""
    prompts = load_prompts(cfg.prompts_root, cfg.prompts_variant)
    criteria = list(prompts.keys())

    n_runs = len(cfg.runs)
    n_per_run = (1 if cfg.factcheck.enabled else 0) + len(cfg.judges)
    total = n_runs * n_per_run
    config_start = time.time()
    completed = 0
    print(
        f"[scoring] {total} tasks starting ({n_runs} runs × "
        f"({len(cfg.judges)} judges{' + factcheck' if cfg.factcheck.enabled else ''}); "
        f"criteria={criteria})",
        file=sys.stderr,
        flush=True,
    )

    failed_tasks: list[tuple[str, BaseException]] = []

    async def _run_task(task, label: str) -> None:
        nonlocal completed
        t0 = time.time()
        try:
            await task
        except BaseException as exc:
            failed_tasks.append((label, exc))
            print(f"warning: task failed: {label}: {exc!r}", flush=True)
        finally:
            completed += 1
            print(
                f"[{completed}/{total}] done in {time.time() - t0:.0f}s "
                f"(total {time.time() - config_start:.0f}s): {label}",
                file=sys.stderr,
                flush=True,
            )

    for run in cfg.runs:
        if cfg.factcheck.enabled:
            await _run_task(
                _score_factcheck_for_run(cfg=cfg, run=run, max_paragraphs=max_paragraphs),
                f"{run} × factcheck",
            )
        for judge in cfg.judges:
            await _run_task(
                _score_run_for_judge(
                    cfg=cfg, run=run, judge=judge,
                    prompts=prompts, criteria=criteria,
                    max_paragraphs=max_paragraphs,
                ),
                f"{run} × {judge.model}",
            )

    print(
        f"[scoring] all {total} tasks done in {time.time() - config_start:.0f}s",
        file=sys.stderr,
        flush=True,
    )

    for run in cfg.runs:
        run_dir = evaluation_run_dir(cfg.base_dir, cfg.evaluation_subdir, run)
        build_merged_jsonl(
            run_dir,
            judges=[j.model for j in cfg.judges],
            criteria=criteria,
            include_factcheck=cfg.factcheck.enabled,
            factcheck_judge=cfg.factcheck.judge if cfg.factcheck.enabled else None,
        )

    run_to_path = {}
    for run in cfg.runs:
        _, run_name = _split_run(run)
        run_to_path[run] = run_name
    build_aggregate_scores(
        cfg.base_dir / cfg.evaluation_subdir,
        run_to_path=run_to_path,
        judges=[j.model for j in cfg.judges],
        criteria=criteria,
        include_factcheck=cfg.factcheck.enabled,
    )

    if failed_tasks:
        raise RuntimeError(
            f"{len(failed_tasks)}/{total} scoring tasks raised after retries; "
            f"first: {failed_tasks[0][0]}: {failed_tasks[0][1]!r}"
        )
```

- [ ] **Step 2: Sanity check — module imports**

```bash
unset VIRTUAL_ENV && uv run --extra dev python -c "import palimpsest.scoring; print('OK')"
```
Expected: `OK`. If any `LEGACY_CRITERIA` reference remains, this fails — fix it.

- [ ] **Step 3: Commit Tasks 7, 11, 12 together**

```bash
git add src/palimpsest/scoring.py
git commit -m "refactor(scoring): thread criteria through aggregation; drop dead consolidated/legacy paths"
```

---

## Task 13: Rewrite tests/conftest.py

**Files:**
- Modify: `tests/conftest.py`

- [ ] **Step 1: Read current conftest to find what to remove**

Open `tests/conftest.py`. It contains `consolidated_engq_response()` and `consolidated_faith_response()` helpers used by `test_scoring_dispatcher.py` and `test_scoring_resume.py`.

- [ ] **Step 2: Replace contents**

Replace the conftest body entirely (keep any non-scoring shared fixtures untouched):

```python
"""Shared pytest helpers."""
from __future__ import annotations

import json


def single_criterion_response(score: int = 8, summary: str = "ok") -> str:
    """Return a fake LLM response for one criterion, JSON-fenced."""
    payload = {
        "final_score": score,
        "summary": summary,
        "identified_issues": [],
    }
    return f"```json\n{json.dumps(payload, ensure_ascii=False)}\n```"
```

Remove the old `consolidated_*` functions and any imports they depend on (unless used by tests outside scoring).

- [ ] **Step 3: Commit**

```bash
git add tests/conftest.py
git commit -m "test(scoring): swap consolidated helpers for single_criterion_response in conftest"
```

---

## Task 14: Delete test_scoring_strategy_consolidated.py

- [ ] **Step 1:**

```bash
git rm tests/test_scoring_strategy_consolidated.py
git commit -m "test(scoring): delete consolidated-strategy tests (path removed)"
```

---

## Task 15: Rename test_scoring_strategy_legacy.py → test_scoring_strategy.py

- [ ] **Step 1: Rename**

```bash
git mv tests/test_scoring_strategy_legacy.py tests/test_scoring_strategy.py
```

- [ ] **Step 2: Verify tests still pass under new name**

```bash
unset VIRTUAL_ENV && uv run --extra dev pytest tests/test_scoring_strategy.py -v
```
Expected: all PASS (the file was already updated in Tasks 3/4/6).

- [ ] **Step 3: Commit**

```bash
git add tests/test_scoring_strategy.py
git commit -m "test(scoring): rename strategy test file (no more legacy/consolidated split)"
```

---

## Task 16: Rewrite test_scoring_dispatcher.py

**Files:**
- Modify: `tests/test_scoring_dispatcher.py`

- [ ] **Step 1: Replace the file body**

Replace entire contents of `tests/test_scoring_dispatcher.py` with:

```python
import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from tests.conftest import single_criterion_response

from palimpsest.config import FactcheckConfig, JudgeConfig, ScoringConfig
from palimpsest.scoring import run_scoring


@pytest.fixture
def repo_layout(tmp_path):
    """Build a fake data/pilot tree + prompts/v1 tree + translation files."""
    base = tmp_path / "pilot"
    (base / "translating" / "large" / "run_x").mkdir(parents=True)
    (base / "translating" / "large" / "run_x" / "translation.md").write_text(
        "первая строка\nвторая строка\nтретья строка\n", encoding="utf-8"
    )
    (base / "pilot_original.md").write_text(
        "first paragraph\nsecond paragraph\nthird paragraph\n", encoding="utf-8"
    )
    prompts = tmp_path / "prompts" / "03_scoring" / "v1"
    prompts.mkdir(parents=True)
    for c in ("accuracy", "terminology", "cultural", "fluency", "style", "consistency"):
        (prompts / f"{c}.md").write_text(f"PROMPT {c}", encoding="utf-8")
    return base, tmp_path / "prompts" / "03_scoring"


@pytest.fixture
def mock_llm_client(monkeypatch):
    client = AsyncMock()

    async def _complete(system, user, **kwargs):
        return single_criterion_response()

    client.complete.side_effect = _complete
    monkeypatch.setattr(
        "palimpsest.scoring._build_client",
        lambda model_key, max_concurrency=0: client,
    )
    return client


@pytest.mark.asyncio
async def test_dispatcher_writes_one_jsonl_per_criterion(repo_layout, mock_llm_client):
    base, prompts_root = repo_layout
    cfg = ScoringConfig(
        base_dir=base,
        prompts_root=prompts_root,
        prompts_variant="v1",
        judges=[JudgeConfig(model="gpt-5.5-low")],
        runs=["large/run_x"],
        factcheck=FactcheckConfig(enabled=False),
    )
    await run_scoring(cfg)

    judge_dir = base / "evaluation" / "run_x" / "gpt-5.5-low"
    for c in ("accuracy", "terminology", "cultural", "fluency", "style", "consistency"):
        f = judge_dir / f"{c}_scores.jsonl"
        assert f.exists()
        rows = [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]
        assert len(rows) == 3
        for row in rows:
            assert row["score"] == 8
            assert row["variant"] == "v1"
            assert row["judge"] == "gpt-5.5-low"


@pytest.mark.asyncio
async def test_dispatcher_writes_meta_json(repo_layout, mock_llm_client):
    base, prompts_root = repo_layout
    cfg = ScoringConfig(
        base_dir=base,
        prompts_root=prompts_root,
        prompts_variant="v1",
        judges=[JudgeConfig(model="gpt-5.5-low")],
        runs=["large/run_x"],
        factcheck=FactcheckConfig(enabled=False),
    )
    await run_scoring(cfg)

    meta = json.loads(
        (base / "evaluation" / "run_x" / "gpt-5.5-low" / "meta.json").read_text()
    )
    assert meta["judge"] == "gpt-5.5-low"
    assert meta["variant"] == "v1"
    assert set(meta["prompts"].keys()) == {
        "accuracy", "terminology", "cultural", "fluency", "style", "consistency"
    }


@pytest.mark.asyncio
async def test_dispatcher_writes_parse_failures_on_bad_json(repo_layout, monkeypatch):
    base, prompts_root = repo_layout

    fail_then_ok = AsyncMock()
    call_log = {"n": 0}

    async def _complete(system, user, **kwargs):
        call_log["n"] += 1
        # Fail twice for first criterion, then succeed (1 + 1 retry = 2 attempts).
        # Subsequent calls always succeed.
        if call_log["n"] <= 2 and "PROMPT accuracy" in system:
            return "garbage not json"
        return single_criterion_response()

    fail_then_ok.complete.side_effect = _complete
    monkeypatch.setattr(
        "palimpsest.scoring._build_client",
        lambda model_key, max_concurrency=0: fail_then_ok,
    )

    cfg = ScoringConfig(
        base_dir=base,
        prompts_root=prompts_root,
        prompts_variant="v1",
        judges=[JudgeConfig(model="gpt-5.5-low")],
        runs=["large/run_x"],
        factcheck=FactcheckConfig(enabled=False),
    )
    with pytest.raises(Exception):
        await run_scoring(cfg)

    # parse_failures.jsonl should exist with at least one row for accuracy.
    pf = base / "evaluation" / "run_x" / "gpt-5.5-low" / "parse_failures.jsonl"
    assert pf.exists()
    rows = [json.loads(l) for l in pf.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert any(r["criterion"] == "accuracy" for r in rows)
    assert all(r["raw"] == "garbage not json" for r in rows if r["criterion"] == "accuracy")


@pytest.mark.asyncio
async def test_dispatcher_never_writes_minus_one(repo_layout, mock_llm_client):
    base, prompts_root = repo_layout
    cfg = ScoringConfig(
        base_dir=base,
        prompts_root=prompts_root,
        prompts_variant="v1",
        judges=[JudgeConfig(model="gpt-5.5-low")],
        runs=["large/run_x"],
        factcheck=FactcheckConfig(enabled=False),
    )
    await run_scoring(cfg)

    judge_dir = base / "evaluation" / "run_x" / "gpt-5.5-low"
    for f in judge_dir.glob("*_scores.jsonl"):
        for line in f.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            assert row["score"] != -1, f"unexpected -1 in {f.name}: {row}"
```

- [ ] **Step 2: Run**

```bash
unset VIRTUAL_ENV && uv run --extra dev pytest tests/test_scoring_dispatcher.py -v
```
Expected: 4 PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_scoring_dispatcher.py
git commit -m "test(scoring): rewrite dispatcher tests for v1 single-criterion + JudgeParseError + no-`-1` invariant"
```

---

## Task 17: Rewrite test_scoring_resume.py

**Files:**
- Modify: `tests/test_scoring_resume.py`

- [ ] **Step 1: Replace the file body**

```python
"""Verifies spec D4 (resume) + D12 (no `-1` in JSONL) + D13 (persistent fail → null).

Behavior:
- A crash mid-task doesn't re-call already-scored paragraphs on the next attempt.
- Parse failures don't write to criterion JSONL — they write to parse_failures.jsonl.
- After _PERSISTENT_FAILURE_THRESHOLD failures for (id, criterion), terminal null row.
"""
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from tests.conftest import single_criterion_response

from palimpsest.config import FactcheckConfig, JudgeConfig, ScoringConfig
from palimpsest.scoring import run_scoring


@pytest.fixture
def repo_layout(tmp_path):
    base = tmp_path / "pilot"
    (base / "translating" / "large" / "run_x").mkdir(parents=True)
    (base / "translating" / "large" / "run_x" / "translation.md").write_text(
        "\n".join(f"line {i}" for i in range(5)) + "\n", encoding="utf-8"
    )
    (base / "pilot_original.md").write_text(
        "\n".join(f"строка {i}" for i in range(5)) + "\n", encoding="utf-8"
    )
    prompts = tmp_path / "prompts" / "03_scoring" / "v1"
    prompts.mkdir(parents=True)
    (prompts / "accuracy.md").write_text("PROMPT acc", encoding="utf-8")
    return base, tmp_path / "prompts" / "03_scoring"


@pytest.mark.asyncio
async def test_resume_skips_already_scored_paragraphs(repo_layout, monkeypatch):
    base, prompts_root = repo_layout

    # First run: crash after id=2 succeeds.
    calls_run1: list[int] = []

    async def first_run_complete(system, user, **kw):
        idx = int(user.rsplit("строка ", 1)[1].split("\n", 1)[0])
        calls_run1.append(idx)
        if idx >= 3:
            raise RuntimeError("simulated crash")
        return single_criterion_response()

    client1 = AsyncMock()
    client1.complete.side_effect = first_run_complete
    monkeypatch.setattr(
        "palimpsest.scoring._build_client",
        lambda model_key, max_concurrency=0: client1,
    )

    cfg = ScoringConfig(
        base_dir=base,
        prompts_root=prompts_root,
        prompts_variant="v1",
        judges=[JudgeConfig(model="gpt-5.5-low")],
        runs=["large/run_x"],
        factcheck=FactcheckConfig(enabled=False),
    )
    with pytest.raises(Exception):
        await run_scoring(cfg)

    # ids 0,1,2 should have written; 3,4 not.
    f = base / "evaluation" / "run_x" / "gpt-5.5-low" / "accuracy_scores.jsonl"
    rows = [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]
    persisted_ids = {r["id"] for r in rows}
    assert persisted_ids == {0, 1, 2}

    # Second run: should only call the LLM for ids 3,4.
    calls_run2: list[int] = []

    async def second_run_complete(system, user, **kw):
        idx = int(user.rsplit("строка ", 1)[1].split("\n", 1)[0])
        calls_run2.append(idx)
        return single_criterion_response()

    client2 = AsyncMock()
    client2.complete.side_effect = second_run_complete
    monkeypatch.setattr(
        "palimpsest.scoring._build_client",
        lambda model_key, max_concurrency=0: client2,
    )

    await run_scoring(cfg)

    assert sorted(calls_run2) == [3, 4]
    rows = [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]
    persisted_ids = {r["id"] for r in rows}
    assert persisted_ids == {0, 1, 2, 3, 4}


@pytest.mark.asyncio
async def test_persistent_parse_failure_writes_terminal_null(repo_layout, monkeypatch):
    base, prompts_root = repo_layout

    # Always return bad JSON for paragraph 0 in 3 consecutive run_scoring calls.
    async def always_bad(system, user, **kw):
        return "not valid json"

    client = AsyncMock()
    client.complete.side_effect = always_bad
    monkeypatch.setattr(
        "palimpsest.scoring._build_client",
        lambda model_key, max_concurrency=0: client,
    )

    cfg = ScoringConfig(
        base_dir=base,
        prompts_root=prompts_root,
        prompts_variant="v1",
        judges=[JudgeConfig(model="gpt-5.5-low")],
        runs=["large/run_x"],
        factcheck=FactcheckConfig(enabled=False),
    )

    # 3 attempts — each one escalates because score_paragraph exhausts retries.
    for _ in range(3):
        with pytest.raises(Exception):
            await run_scoring(cfg)

    # 4th attempt: should NOT call the LLM for failed criteria; instead write terminal null.
    client.complete.reset_mock()
    client.complete.side_effect = always_bad  # still bad, but shouldn't be called

    # Allow the dispatch to complete cleanly because the only remaining work is
    # writing terminal nulls. (Other criteria might still fail; we have only one.)
    try:
        await run_scoring(cfg)
    except Exception:
        pass  # expected for any non-terminal paragraph that still fails

    f = base / "evaluation" / "run_x" / "gpt-5.5-low" / "accuracy_scores.jsonl"
    rows = [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]
    # Paragraph 0 should now have a terminal-null row.
    by_id = {r["id"]: r for r in rows}
    assert 0 in by_id
    assert by_id[0]["score"] is None
    assert "persistent_parse_failure" in by_id[0]["llm_report"]


@pytest.mark.asyncio
async def test_parse_failures_jsonl_accumulates_raw_responses(repo_layout, monkeypatch):
    base, prompts_root = repo_layout

    async def always_bad(system, user, **kw):
        return "garbage"

    client = AsyncMock()
    client.complete.side_effect = always_bad
    monkeypatch.setattr(
        "palimpsest.scoring._build_client",
        lambda model_key, max_concurrency=0: client,
    )

    cfg = ScoringConfig(
        base_dir=base,
        prompts_root=prompts_root,
        prompts_variant="v1",
        judges=[JudgeConfig(model="gpt-5.5-low")],
        runs=["large/run_x"],
        factcheck=FactcheckConfig(enabled=False),
    )
    with pytest.raises(Exception):
        await run_scoring(cfg)

    pf = base / "evaluation" / "run_x" / "gpt-5.5-low" / "parse_failures.jsonl"
    assert pf.exists()
    rows = [json.loads(l) for l in pf.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert all(r["raw"] == "garbage" for r in rows)
    assert all(r["criterion"] == "accuracy" for r in rows)
```

- [ ] **Step 2: Run**

```bash
unset VIRTUAL_ENV && uv run --extra dev pytest tests/test_scoring_resume.py -v
```
Expected: 3 PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_scoring_resume.py
git commit -m "test(scoring): rewrite resume tests for D12/D13 — parse_failures.jsonl + terminal null"
```

---

## Task 18: Full test suite green

- [ ] **Step 1: Run everything**

```bash
unset VIRTUAL_ENV && uv run --extra dev pytest tests/ -v
```
Expected: ALL PASS. Investigate and fix any failure.

- [ ] **Step 2: If any test fails, fix the test or the code (depending on what's wrong); commit each fix separately**

```bash
git add <files>
git commit -m "fix(scoring): <what was wrong>"
```

---

## Task 19: Create scripts/03_cleanup_minus_one.py

**Files:**
- Create: `scripts/03_cleanup_minus_one.py`

- [ ] **Step 1: Write the script**

```python
#!/usr/bin/env python3
"""One-shot scrubber: remove `score: -1` rows from existing scoring JSONLs.

After spec D12, score=-1 is gone — but old runs may have written such rows.
load_existing_ids would now treat them as done, which is wrong. This script
walks <root> recursively, finds *_scores.jsonl, and rewrites them without
any -1 row. Idempotent.

Usage:
  python scripts/03_cleanup_minus_one.py --root data/pilot/evaluation_smoke
  python scripts/03_cleanup_minus_one.py --root data/pilot/evaluation
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def scrub_file(path: Path) -> tuple[int, int]:
    """Return (kept, removed) row counts."""
    kept_rows: list[str] = []
    removed = 0
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                row = json.loads(stripped)
            except json.JSONDecodeError:
                kept_rows.append(line)
                continue
            if row.get("score") == -1:
                removed += 1
                continue
            kept_rows.append(line if line.endswith("\n") else line + "\n")
    if removed == 0:
        return len(kept_rows), 0
    with path.open("w", encoding="utf-8") as f:
        f.writelines(kept_rows)
    return len(kept_rows), removed


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", required=True, type=Path)
    args = p.parse_args()

    if not args.root.is_dir():
        print(f"error: {args.root} is not a directory", file=sys.stderr)
        return 1

    total_removed = 0
    for path in sorted(args.root.rglob("*_scores.jsonl")):
        kept, removed = scrub_file(path)
        if removed:
            print(f"{path}: kept {kept}, removed {removed}")
            total_removed += removed
    print(f"total -1 rows removed: {total_removed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Make executable**

```bash
chmod +x scripts/03_cleanup_minus_one.py
```

- [ ] **Step 3: Smoke run against the existing v2 data**

```bash
unset VIRTUAL_ENV && uv run python scripts/03_cleanup_minus_one.py --root data/pilot/evaluation_smoke
```
Expected: some rows removed from `fluency_scores.jsonl`, `style_scores.jsonl`, `consistency_scores.jsonl` (the broken v2 outputs from earlier in the session).

- [ ] **Step 4: Verify**

```bash
grep -c '"score": -1' data/pilot/evaluation_smoke/qwen_par_by_par/gpt-5.5-low/*.jsonl
```
Expected: 0 in every file.

- [ ] **Step 5: Commit script (data changes stay uncommitted — LFS-tracked smoke data is local-only)**

```bash
git add scripts/03_cleanup_minus_one.py
git commit -m "chore(scripts): add one-shot scrubber for legacy -1 rows in scoring JSONLs"
```

---

## Task 20: Audit scripts for variant name references

**Files:**
- Read: `scripts/03_translation_scoring.py`, `scripts/03_scoring_exprs.sh`, `scripts/03_scoring_smoke.sh`

- [ ] **Step 1: Audit**

```bash
grep -nE 'prompts_variant|"old"|"compact"|"full"|variant' scripts/03_translation_scoring.py scripts/03_scoring_exprs.sh scripts/03_scoring_smoke.sh 2>/dev/null
```

- [ ] **Step 2: If anything matches, update accordingly**

- CLI flag like `--variant` → drop it or update default to `v1`.
- Hardcoded string `"full"` → `"v1"`.
- Comments mentioning consolidated → drop.

- [ ] **Step 3: Commit if anything changed**

```bash
git add scripts/
git commit -m "chore(scripts): drop variant references for old/compact/full"
```

(If nothing changed, skip the commit.)

---

## Task 21: Rewrite docs/stages/03_scoring.md

**Files:**
- Modify: `docs/stages/03_scoring.md`

- [ ] **Step 1: Replace contents**

```markdown
# Stage 03 — Scoring (Оценка)

Up-link: [docs/pipeline.md](../pipeline.md). Контракт путей: [pilot_interfaces_agreement.md](../pilot_interfaces_agreement.md).

## Purpose

Оценить переводы из Stage 02 N одно-criterion LLM-промптами на каждого судью (по умолчанию 6 промптов: accuracy, terminology, cultural, fluency, style, consistency) + один factcheck-вызов фиксированной моделью. Множественные судьи поддерживаются; в стартовой батарее — только `gpt-5.5-low` для скорости и стоимости. Остальные добавляются по мере необходимости.

## Design decisions

- **Config-driven**: список судей, список run'ов, имя папки промптов (`prompts_variant`), параметры factcheck'а — всё в YAML. CLI вызывает `palimpsest.scoring.run_scoring(cfg)`.
- **Filename-driven variant discovery** (spec D1): `load_prompts(prompts_root, variant)` делает `glob('*.md')` в `prompts_root/variant/`, имя файла без расширения = имя criterion'а. Завтра можно положить `prompts/03_scoring/v2/` с любым числом `*.md` — диспетчер подхватит без изменений в коде.
- **Один variant на весь scoring-конфиг** (D2): `JudgeConfig.variant` нет; все судьи одного конфига используют единственный `cfg.prompts_variant`. Сравнение v1 vs v2 = два отдельных scoring-конфига + две `evaluation/` директории.
- **Без structured-output** (D3): инструкция «верни JSON» живёт в самом промпте, никакого `response_format` в API-вызовах. Универсальность между OpenAI/Anthropic/Gemini/Qwen/GLM провайдерами.
- **Output layout**: `evaluation/<run>/<judge>/<criterion>_scores.jsonl` (сырые, idempotent) + `evaluation/<run>/<judge>/parse_failures.jsonl` (диагностика парс-неудач) + `evaluation/<run>/merged_scores.jsonl` (сводный per-paragraph) + `evaluation/scores.json` (top-level агрегат).
- **Idempotent resume**: повторный запуск пропускает `id`'ы, уже записанные в criterion-JSONL.
- **Sentinel handling**: `* * *` / `picture` / `[TRANSLATION FAILED]` → skip, `score: null`, в average не идут.
- **Fail-fast на parse error** (D12): `parse_judge_response` бросает `JudgeParseError` при невалидном JSON / отсутствии score / score вне диапазона 1-10. `score_paragraph` делает inline-retry до `_MAX_PARSE_ATTEMPTS = 2`. Если все попытки провалились — raw попадает в `parse_failures.jsonl` и параграф остаётся «не оценённым», resume его подбирает на следующей попытке.
- **Terminal null после 3 escalation'ов** (D13): если `(paragraph_id, criterion)` упал в `parse_failures.jsonl` ≥ 3 раз — пишется terminal `{score: null, llm_report: "persistent_parse_failure..."}`, параграф больше не пытается оцениваться, в average не идёт.
- **Factcheck**: отдельный шаг с одной фиксированной моделью (default `gpt-5.4-mini-low`); промпты живут в `src/palimpsest/factcheck/`.

## Interface

```python
from pathlib import Path
from palimpsest.config import load_scoring
from palimpsest.scoring import run_scoring

cfg = load_scoring(Path("configs/scoring/large-low.yaml"))
await run_scoring(cfg)
```

CLI:

```bash
python scripts/03_translation_scoring.py --config configs/scoring/large-low.yaml
python scripts/03_translation_scoring.py --config configs/scoring/large-low.yaml --force
python scripts/03_translation_scoring.py --config configs/scoring/smoke.yaml --max-paragraphs 5
```

Пример конфига:

```yaml
base_dir: data/pilot
prompts_variant: v1
max_concurrency: 64
judges:
  - model: gpt-5.5-low
factcheck:
  enabled: true
  judge: gpt-5.4-mini-low
runs:
  - large/qwen_par_by_par
```

Для боевого прогона с retry-on-crash есть тонкая шелл-обёртка `scripts/03_scoring_resume.sh` — запускает large-low и small-low параллельно, каждый с `MAX_RETRIES` повторами и логом в `data/pilot/evaluation/<profile>.log`. API-провайдеры периодически рвут соединение — обёртка перезапускает python, дальше идёт idempotent resume.

## Subtleties

- `merged_scores.jsonl` всегда пересобирается из сырых JSONL — это derived view; criterion-список берётся из `list(prompts.keys())`, передаётся в `build_merged_jsonl`.
- `scores.json` мёрджится: при перезапуске только указанные в config'е runs обновляются; остальные ключи сохраняются.
- **Score field в `<criterion>_scores.jsonl`**: `int 1-10` (валидная оценка) или `null` (sentinel skip: marker / `[TRANSLATION FAILED]` / persistent parse failure). Никакого `-1`.
- **`parse_failures.jsonl`** — append-only лог per judge, со схемой `{id, criterion, reason, raw, source, translated, judge, variant, ts}`. Не читается агрегацией, не считается оценкой. Сюда уходит сырой ответ модели когда `parse_judge_response` бросил `JudgeParseError`. Аналитик может открыть и разобраться руками.
- **`_PERSISTENT_FAILURE_THRESHOLD = 3`** — константа в [scoring.py](../../src/palimpsest/scoring.py). Если на старте `_score_run_for_judge` обнаруживается, что `(id, criterion)` уже упал ≥ 3 раз (по `parse_failures.jsonl`) — этот criterion для этого paragraph'а получает terminal null без API-вызова.
- **Sequential dispatch (v2)**: `run_scoring` грузит promptы один раз, далее processes runs строго последовательно; внутри run factcheck runs до завершения перед стартом любого judge task'а. `MAX_CONCURRENCY` enforced inside `LLMClient` через constructor-injected `asyncio.Semaphore`, так что значение — литеральный cap на одновременные HTTP-запросы на одного клиента.
- **Smoke harness**: `scripts/03_scoring_smoke.sh` гоняет factcheck + scoring на 50 параграфах `local/qwen_par_by_par` в `data/pilot/evaluation_smoke/`. Запускать перед каждой большой батареей.
- **Cleanup утилита**: `scripts/03_cleanup_minus_one.py --root <dir>` — один раз пройтись по существующим JSONL, чтобы убрать строки с `score: -1` из старых v2 прогонов. После refactor'а `load_existing_ids` трактует наличие row как done, без специальной обработки `-1`.

## Status

Реализован. Smoke на `configs/scoring/smoke.yaml` зелёный.

- v1 single-criterion + filename-driven discovery + no-`-1` policy shipped 2026-05-14 (commit TBD). Промпты в `prompts/03_scoring/v1/`; consolidated path удалён полностью.
- v2 sequential dispatch + per-client concurrency cap + 2-retry transient guarantee — наследуется без изменений.
- Единственный judge `gpt-5.5-low` в 01-06 priority конфигах; другие подключаются через resume.
```

- [ ] **Step 2: Commit**

```bash
git add docs/stages/03_scoring.md
git commit -m "docs(stages): rewrite 03_scoring for v1 single-criterion + no-1 policy"
```

---

## Task 22: Update docs/pipeline.md

**Files:**
- Modify: `docs/pipeline.md`

- [ ] **Step 1: Audit**

```bash
grep -n 'consolidated\|english_quality\|faithfulness\|2 consolidated\|{full,compact}' docs/pipeline.md
```

- [ ] **Step 2: For each match, update**

- Replace «2 consolidated LLM calls per judge per paragraph» with «N одно-criterion вызовов на judge на paragraph (по умолчанию 6: accuracy, terminology, cultural, fluency, style, consistency)».
- Replace «`prompts/03_scoring/{full,compact}/english_quality.md` (3 criteria per call)» с строками отдельных critериев: каждый `prompts/03_scoring/v1/<criterion>.md` → один critеrion в JSONL.
- Если есть упоминание `consolidated faithfulness` / `consolidated english_quality` — заменить на «single-criterion prompts in v1».

- [ ] **Step 3: Verify all updated**

```bash
grep -n 'consolidated\|{full,compact}' docs/pipeline.md
```
Expected: empty.

- [ ] **Step 4: Commit**

```bash
git add docs/pipeline.md
git commit -m "docs(pipeline): sync Stage 03 narrative with v1 single-criterion architecture"
```

---

## Task 23: Create docs/known_issues.md

**Files:**
- Create: `docs/known_issues.md`

- [ ] **Step 1: Write the file**

```markdown
# Известные проблемы и грабли

Up-link: [CLAUDE.md](../CLAUDE.md).

Сюда фиксируем грабли проекта (баги, неочевидные ограничения провайдеров, проблемы воспроизводимости) — чтобы не наступать дважды. Формат записи: краткое описание → симптомы → причина → текущее решение → когда пересмотреть.

---

## 1. JSON output — через промпт, не через `response_format`

**Симптомы.** Часть провайдеров (Anthropic API, некоторые маршруты OpenRouter) не поддерживают параметр `response_format={"type":"json_object"}` или молча его игнорируют. При попытке унифицировать вызовы между судьями — рассинхронизация поведения, у одного судьи JSON жёстко, у другого — drift.

**Причина.** Structured-output поддержка варьируется: у OpenAI она каноническая (gpt-5.x), у Anthropic native API нет такого параметра, у Gemini есть `responseSchema`, OpenRouter частично проксирует — но не всегда. Кросс-провайдерная сравнимость ломается.

**Текущее решение** (spec D3). Никакого `response_format` в коде. Каждый scoring-промпт в `prompts/03_scoring/v1/*.md` содержит **явную JSON-инструкцию в хвосте** (фраза «Respond with a valid JSON object and nothing else» + JSON-структура с `final_score`). Парсинг через `parse_judge_response` с поддержкой ```json fence и plain JSON.

**Когда пересмотреть.** Если на конкретной модели увидим стабильный JSON drift (>5% параграфов с `JudgeParseError` в `parse_failures.jsonl` за прогон) — fallback'ом включить JSON mode именно для этой модели, на уровне `LLMClient` за per-model toggle. До того — prompt-driven.

---

## 2. Параллельность: `max_concurrency` per-client, не глобально

**Симптомы.** При батарее из нескольких параллельных scoring-процессов начинают вылетать `429 RateLimitError` от провайдера, хотя `cfg.max_concurrency` стоит, скажем, 64.

**Причина.** Семафор живёт внутри одного `LLMClient` (constructor-injected `asyncio.Semaphore`). v2 sequential dispatch держит runs/judges последовательно **внутри одного процесса**. Но `scripts/03_scoring_resume.sh` запускает `large-low` и `small-low` **двумя параллельными процессами**, у каждого свой `LLMClient`, каждый со своим semaphore'ом. Плюс умножение на число criterion'ов: на v1 один параграф = 6 одновременных API-вызовов. Реальная нагрузка на провайдер ≈ (параллельных процессов) × (max_concurrency) × (criteria per paragraph).

**Текущее решение.** При планировании батареи считать кратность. При первых 429 — снижать `max_concurrency` в конфиге (с 64 на 32, например). `LLMClient` уже умеет retry с экспоненциальным backoff на `RateLimitError`, так что разовые 429 не критичны; критично когда они становятся систематикой.

**Когда пересмотреть.** Если переход на больший pilot (>1000 параграфов) или multi-judge battery с 3+ моделями начинает упираться в провайдерские лимиты — ввести глобальный rate-limit gate (per-provider, per-model) на уровне `LLMClient.complete` через shared semaphore по `model_name`.

---

## 3. Стохастичность LLM-багов

**Симптомы.** Smoke прогон на 50 параграфах ловит 49/50 fail для одного критерия. Rerun на ОДНОМ из этих 50 параграфов даёт валидный ответ. Кажется, что баг «починился» — на самом деле он стохастический.

**Причина.** `temperature=1.0` (как у Gemini 3.x — обязательно, и у gpt-5.x — рекомендуется для естественности) даёт распределение ответов. Баги вида «модель путает формат» имеют вероятность срабатывания на конкретном параграфе, скажем, 90% — но на single-paragraph repro попадаешь в 10% хвоста и думаешь, что всё ок.

**Текущее решение.** Если smoke ловит регрессию — **фиксировать список paragraph_idx из smoke** (например, в `data/pilot/evaluation_smoke/<run>/<judge>/parse_failures.jsonl`), не уходить на N=1 single-paragraph repro без подтверждения, что баг даёт ≥80% воспроизводимости.

**Когда пересмотреть.** Если появится возможность зафиксировать seed (некоторые провайдеры поддерживают `seed` параметр) — для regression tests'ов это снимет головную боль. Сейчас не реализовано.

---

## 4. Soft-fallback `score = -1` на parse fail — антипаттерн

**Симптомы.** При неудаче парсинга LLM-ответа (malformed JSON, missing key, score out-of-range) writer писал в criterion-JSONL row с `score: -1` и `llm_report: "missing criterion X in Y response"`. Aggregation должен был помнить про этот sentinel и фильтровать (`v != -1`). Raw-ответ модели **затирался** сообщением — диагностика терялась.

**Причина.** Соблазн «row есть — resume увидит — перепробует»: семантически у тебя выходит, что параграф **обработан**, но score «недействителен». Аналитик читает JSONL, видит row, думает «ок, оценка есть», смотрит в report — а там административное сообщение. Дезориентирует.

**Текущее решение** (spec D12 + D13). Никакого `-1` на диске. parse fail = `JudgeParseError` exception, никакого row в criterion-JSONL не пишется; raw уходит в отдельный `<judge>/parse_failures.jsonl` (append-only diagnostic log). После 3 escalation'ов для одного `(paragraph, criterion)` — записывается terminal `score: null` с указателем на `parse_failures.jsonl`. Aggregation теперь фильтрует только `None`, никаких specials.

**Когда пересмотреть.** Если parse-failure rate станет систематически >10% на любой модели — это сигнал что либо промпт слишком жёсткий для модели, либо JSON-инструкцию надо усилить, либо в самом деле временно вернуть `response_format=json_object` для этого судьи (см. запись 1). До того — fail-fast и расследовать через `parse_failures.jsonl`.
```

- [ ] **Step 2: Commit**

```bash
git add docs/known_issues.md
git commit -m "docs(known-issues): add pitfalls log — JSON output, parallelism, stochasticity, -1 antipattern"
```

---

## Task 24: Update CLAUDE.md routing + conventions

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add Routing row**

Locate the Routing table at the bottom. Add a row:

```markdown
| Известные проблемы и грабли | [docs/known_issues.md](docs/known_issues.md) |
```

Insert it between the "Specs / plans" row and "Research drafts" row.

- [ ] **Step 2: Add convention bullet in Documentation section**

In the `### Documentation` section, after the bullet about "Sync rule", add:

```markdown
- Грабли проекта (баги, неочевидные ограничения провайдеров, проблемы воспроизводимости) фиксируем в [docs/known_issues.md](docs/known_issues.md) — добавлять новую запись когда столкнулись и согласовали решение.
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs(claude-md): add docs/known_issues.md to routing + conventions"
```

---

## Task 25: README pitch check

**Files:**
- Read: `README.md`

- [ ] **Step 1: Search for consolidated/scoring-architecture references**

```bash
grep -n 'consolidated\|2 calls\|faithfulness\|english_quality\|6 criteria\|2 prompts per' README.md
```

- [ ] **Step 2: If matches found, update accordingly**

Replace «2 consolidated prompts» language with «6 single-criterion prompts». Replace mentions of `english_quality.md` / `faithfulness.md` with criterion-by-criterion language.

- [ ] **Step 3: Commit if changed**

```bash
git add README.md
git commit -m "docs(readme): sync scoring pitch with v1 single-criterion architecture"
```

(If no matches — skip this commit.)

---

## Task 26: Smoke verification on v1

**Pre-step (already done in Task 19):** legacy `-1` rows scrubbed from `data/pilot/evaluation_smoke/`.

- [ ] **Step 1: Wipe smoke output so we test from scratch**

```bash
rm -rf data/pilot/evaluation_smoke/qwen_par_by_par/gpt-5.5-low
rm -rf data/pilot/evaluation_smoke/qwen_par_by_par/factcheck
rm -f data/pilot/evaluation_smoke/qwen_par_by_par/merged_scores.jsonl
rm -f data/pilot/evaluation_smoke/scores.json
rm -f data/pilot/evaluation_smoke/smoke.log
```

(Keep the `qwen_par_by_par/` directory itself in case smoke.yaml expects the source translations to be there.)

- [ ] **Step 2: Run smoke**

```bash
unset VIRTUAL_ENV && uv run python scripts/03_translation_scoring.py --config configs/scoring/smoke.yaml --max-paragraphs 50 2>&1 | tee data/pilot/evaluation_smoke/smoke.log | tail -40
```

(If `scripts/03_scoring_smoke.sh` is the canonical wrapper — use it instead.)

- [ ] **Step 3: Verify no `-1` anywhere**

```bash
grep -lE '"score":\s*-1' data/pilot/evaluation_smoke/qwen_par_by_par/gpt-5.5-low/*.jsonl
```
Expected: empty (no files match).

- [ ] **Step 4: Verify all 6 criterion JSONLs exist and have rows**

```bash
for c in accuracy terminology cultural fluency style consistency; do
  f="data/pilot/evaluation_smoke/qwen_par_by_par/gpt-5.5-low/${c}_scores.jsonl"
  count=$(wc -l < "$f" 2>/dev/null || echo "MISSING")
  echo "$c: $count rows"
done
```
Expected: each criterion has ≥ 45 rows (50 paragraphs - allowed sentinel skips).

- [ ] **Step 5: Verify meta.json**

```bash
cat data/pilot/evaluation_smoke/qwen_par_by_par/gpt-5.5-low/meta.json | python -m json.tool | head -20
```
Expected: `"variant": "v1"`.

- [ ] **Step 6: Verify merged_scores.jsonl has all 6 criterion keys**

```bash
head -1 data/pilot/evaluation_smoke/qwen_par_by_par/merged_scores.jsonl | python -m json.tool
```
Expected: top-level keys include `accuracy`, `terminology`, `cultural`, `fluency`, `style`, `consistency`, `factcheck` (if enabled).

- [ ] **Step 7: If everything green — done. If smoke red — investigate parse_failures.jsonl**

```bash
if [ -f data/pilot/evaluation_smoke/qwen_par_by_par/gpt-5.5-low/parse_failures.jsonl ]; then
  wc -l data/pilot/evaluation_smoke/qwen_par_by_par/gpt-5.5-low/parse_failures.jsonl
fi
```

If there are entries — open the file, look at `raw` field for the failing criterion, decide if it's transient (rerun smoke) or systematic (fix prompt / consider JSON mode for this model).

- [ ] **Step 8: Final commit**

Smoke data is LFS-tracked — keep changes uncommitted (operator decides whether to push). Just leave the worktree green for next steps.

---

## Verification checklist (top-level)

- [ ] `pytest tests/` — all green.
- [ ] No `-1` in any `*_scores.jsonl` under `data/pilot/evaluation_smoke/`.
- [ ] `meta.json` for smoke run shows `variant: v1`.
- [ ] 6 criterion JSONLs each have ≥ 45 valid rows for 50-paragraph smoke.
- [ ] `merged_scores.jsonl` has 6 criterion-keyed columns.
- [ ] `prompts/03_scoring/` has only `v1/` subdirectory (no full/compact/old).
- [ ] All 9 `configs/scoring/*.yaml` declare `prompts_variant: v1`.
- [ ] `docs/known_issues.md` exists with 4 entries.
- [ ] `CLAUDE.md` Routing table has known_issues entry.
- [ ] `git status` shows clean working tree (besides smoke output, which is LFS-tracked and not necessarily committed).
