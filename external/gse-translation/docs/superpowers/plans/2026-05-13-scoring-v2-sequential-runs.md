# Scoring v2 — sequential runs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `MAX_CONCURRENCY` an honest hard cap on simultaneous HTTP requests; guarantee that the LLM router returns a real response or raises (no soft `-1`); persist every scored paragraph to disk before the task moves on so a crash can be resumed; switch the scoring dispatcher to one-translation-at-a-time so progress is humanly observable.

**Architecture:** Three call sites change. (1) `LLMClient` gets a constructor-injected `asyncio.Semaphore` that gates every SDK call and the retry count drops 8 → 3 (= 2 retries). (2) `scoring._score_run_for_judge` / `_score_factcheck_for_run` drop their local semaphore (client owns it now) and use `asyncio.as_completed` + `tqdm` for per-paragraph progress with sibling-finishing exception flow. (3) `run_scoring` becomes a sequential `for run in cfg.runs: await factcheck; for judge: await judge_task` loop. The hard `score=-1` / `None` semantics get named constants + a contract-doc table. A smoke YAML + shell script exercise the whole pipeline on 50 paragraphs in an isolated `evaluation_smoke/` dir.

**Tech Stack:** Python 3.13, asyncio, `tqdm.asyncio`, pytest 9 + pytest-asyncio (auto mode), AsyncOpenAI / AsyncAnthropic via `LLMClient`.

**Spec:** [docs/superpowers/specs/2026-05-13-scoring-v2-sequential-runs.md](../specs/2026-05-13-scoring-v2-sequential-runs.md)

---

## File structure

Files we'll touch — one responsibility each:

- `src/palimpsest/llm/client.py` — adds `max_concurrency` kwarg + internal semaphore, reduces retry count, keeps the existing transient-classifier + `EmptyContentError`. No new module.
- `src/palimpsest/scoring.py` — `run_scoring` becomes sequential; `_build_client` accepts a `max_concurrency` arg; `_score_run_for_judge` / `_score_factcheck_for_run` drop their local `Semaphore` and use `asyncio.as_completed` + `tqdm`; named constants `SCORE_LLM_FAIL` / `SCORE_SKIPPED` replace literal `-1` / `None` at every write site; `load_existing_ids` docstring gets the D4a table.
- `configs/scoring/01-top-vs-baseline.yaml` … `06-reasoning-low.yaml` — `judges:` reduced to `gpt-5.5-low` only.
- `configs/scoring/smoke.yaml` — new (or rewritten): factcheck + gpt-5.5-low on `local/qwen_par_by_par`, output to `evaluation_smoke/`.
- `scripts/03_scoring_smoke.sh` — new: thin wrapper around `03_translation_scoring.py` with `--max-paragraphs 50`.
- `tests/test_llm_client.py` — adds tests for retry-count + semaphore cap + empty-content-retried.
- `tests/test_scoring_resume.py` — new: paragraph-level resume verification.
- `references/interfaces_agreement.md` — new "Scoring JSONL row schema" section.
- `data/pilot/evaluation/README.md` — new one-page reader's note.
- `docs/stages/04_scoring.md` — sync note (sequential dispatch + smoke harness).
- `docs/pipeline.md` — single-line status update on Stage 04.

---

## Task 1: Test-first — `LLMClient.complete` caps in-flight at `max_concurrency`

**Files:**
- Modify: `tests/test_llm_client.py`
- Modify: `src/palimpsest/llm/client.py`

- [ ] **Step 1: Append the failing test**

Append to `tests/test_llm_client.py`:

```python
import asyncio

import pytest

from palimpsest.llm.client import LLMClient, LLMConfig


@pytest.mark.asyncio
async def test_llm_client_semaphore_caps_inflight(monkeypatch):
    """When max_concurrency=N, at most N _complete_* calls run concurrently."""
    cfg = LLMConfig(
        model="test/model",
        base_url="https://api.openai.com/v1",
        api_key="x",
        max_tokens=100,
    )
    client = LLMClient(cfg, max_concurrency=3)

    inflight = 0
    peak = 0

    async def slow_dispatch(*args, **kwargs):
        nonlocal inflight, peak
        inflight += 1
        peak = max(peak, inflight)
        await asyncio.sleep(0.05)
        inflight -= 1
        return "ok"

    monkeypatch.setattr(client, "_complete_openai", slow_dispatch)
    monkeypatch.setattr("palimpsest.llm.client.asyncio.sleep", lambda *_a, **_kw: asyncio.sleep(0))

    await asyncio.gather(*(client.complete("sys", "usr") for _ in range(20)))
    assert peak == 3


@pytest.mark.asyncio
async def test_llm_client_default_concurrency_unbounded(monkeypatch):
    """max_concurrency=0 (default) → no effective cap → all 20 run together."""
    cfg = LLMConfig(
        model="test/model",
        base_url="https://api.openai.com/v1",
        api_key="x",
        max_tokens=100,
    )
    client = LLMClient(cfg)

    inflight = 0
    peak = 0

    async def slow_dispatch(*args, **kwargs):
        nonlocal inflight, peak
        inflight += 1
        peak = max(peak, inflight)
        await asyncio.sleep(0.05)
        inflight -= 1
        return "ok"

    monkeypatch.setattr(client, "_complete_openai", slow_dispatch)
    monkeypatch.setattr("palimpsest.llm.client.asyncio.sleep", lambda *_a, **_kw: asyncio.sleep(0))

    await asyncio.gather(*(client.complete("sys", "usr") for _ in range(20)))
    assert peak == 20
```

- [ ] **Step 2: Run tests, confirm they fail**

Run: `unset VIRTUAL_ENV && uv run pytest tests/test_llm_client.py::test_llm_client_semaphore_caps_inflight tests/test_llm_client.py::test_llm_client_default_concurrency_unbounded -v`
Expected: both **FAIL** — `LLMClient.__init__` rejects the unknown `max_concurrency` kwarg.

- [ ] **Step 3: Add `max_concurrency` kwarg and internal semaphore**

Modify `src/palimpsest/llm/client.py`. Locate the `LLMClient` class. Replace its `__init__` and add the gate inside `complete()`:

```python
class LLMClient:
    """One client per model. Provider is derived from base_url; dispatch is per-call."""

    # 2**20 is "effectively unlimited" for our pilot workloads; spec D2 keeps
    # this as the no-op behavior when max_concurrency <= 0.
    _UNLIMITED: int = 2**20

    def __init__(self, config: LLMConfig, *, max_concurrency: int = 0):
        self.config = config
        self._provider: Provider = "anthropic" if "anthropic.com" in config.base_url else "openai"
        if self._provider == "anthropic":
            self._anthropic = AsyncAnthropic(api_key=config.api_key)
        else:
            self._openai = AsyncOpenAI(base_url=config.base_url, api_key=config.api_key)
        effective = max_concurrency if max_concurrency > 0 else self._UNLIMITED
        self._gate = asyncio.Semaphore(effective)
```

Then replace the body of `complete()` so the SDK call is inside `async with self._gate`. Find the existing `complete` method and replace the `for attempt in range...` loop:

```python
    async def complete(
        self,
        system: str,
        user: str,
        *,
        thinking: bool = False,
        thinking_budget_tokens: int | None = None,
        **overrides,
    ) -> str:
        """Send one prompt to the configured LLM. Retries transient failures
        (RateLimit / connection / timeout / empty-content) with exponential
        backoff up to _RETRY_MAX_ATTEMPTS. Raises the last exception only when
        every attempt has been exhausted. The internal semaphore (set via
        max_concurrency at construction) caps simultaneous SDK calls.
        """
        last_exc: Exception | None = None
        for attempt in range(1, _RETRY_MAX_ATTEMPTS + 1):
            try:
                async with self._gate:
                    if self._provider == "anthropic":
                        result = await self._complete_anthropic(
                            system, user, thinking, thinking_budget_tokens, overrides
                        )
                    else:
                        result = await self._complete_openai(system, user, overrides)
                if not result.strip():
                    raise EmptyContentError(
                        f"{self.config.model}: empty content from provider"
                    )
                return result
            except _TRANSIENT_ERRORS as exc:
                last_exc = exc
            except (openai.APIStatusError, anthropic.APIStatusError) as exc:
                status = getattr(exc, "status_code", None)
                if status is None or status < 500:
                    raise
                last_exc = exc

            if attempt >= _RETRY_MAX_ATTEMPTS:
                break
            delay = _retry_delay(attempt)
            print(
                f"[retry] {self.config.model} attempt {attempt}/{_RETRY_MAX_ATTEMPTS} "
                f"after {type(last_exc).__name__}: sleep {delay:.1f}s",
                file=sys.stderr,
                flush=True,
            )
            await asyncio.sleep(delay)

        assert last_exc is not None
        raise last_exc
```

- [ ] **Step 4: Run tests, confirm they pass**

Run: `unset VIRTUAL_ENV && uv run pytest tests/test_llm_client.py -v`
Expected: **all 18 tests pass** (16 existing + 2 new).

- [ ] **Step 5: Commit**

```bash
git add tests/test_llm_client.py src/palimpsest/llm/client.py
git commit -m "feat(llm): semaphore-gated max_concurrency in LLMClient (D2)"
```

---

## Task 2: Test-first — retry count drops from 8 to 3

**Files:**
- Modify: `tests/test_llm_client.py`
- Modify: `src/palimpsest/llm/client.py`

- [ ] **Step 1: Append the failing test**

Append to `tests/test_llm_client.py`:

```python
from palimpsest.llm.client import EmptyContentError


@pytest.mark.asyncio
async def test_llm_client_retries_2_then_raises(monkeypatch):
    """Persistent transient (empty content) → 3 attempts total → raise."""
    cfg = LLMConfig(
        model="test/model",
        base_url="https://api.openai.com/v1",
        api_key="x",
        max_tokens=100,
    )
    client = LLMClient(cfg)

    calls = 0

    async def always_empty(*args, **kwargs):
        nonlocal calls
        calls += 1
        return ""

    monkeypatch.setattr(client, "_complete_openai", always_empty)
    monkeypatch.setattr("palimpsest.llm.client.asyncio.sleep", lambda *_a, **_kw: asyncio.sleep(0))

    with pytest.raises(EmptyContentError):
        await client.complete("sys", "usr")
    assert calls == 3


@pytest.mark.asyncio
async def test_llm_client_succeeds_after_one_retry(monkeypatch):
    """Empty once, then content → succeeds, 2 calls total."""
    cfg = LLMConfig(
        model="test/model",
        base_url="https://api.openai.com/v1",
        api_key="x",
        max_tokens=100,
    )
    client = LLMClient(cfg)

    responses = ["", "real response"]
    calls = 0

    async def two_step(*args, **kwargs):
        nonlocal calls
        out = responses[calls]
        calls += 1
        return out

    monkeypatch.setattr(client, "_complete_openai", two_step)
    monkeypatch.setattr("palimpsest.llm.client.asyncio.sleep", lambda *_a, **_kw: asyncio.sleep(0))

    result = await client.complete("sys", "usr")
    assert result == "real response"
    assert calls == 2
```

- [ ] **Step 2: Run tests, confirm the first fails**

Run: `unset VIRTUAL_ENV && uv run pytest tests/test_llm_client.py::test_llm_client_retries_2_then_raises -v`
Expected: **FAIL** — `assert calls == 3` but actual is `8` (current `_RETRY_MAX_ATTEMPTS = 8`).

- [ ] **Step 3: Reduce retry constants in `client.py`**

In `src/palimpsest/llm/client.py`, change the retry constants (look for the comment block before `_retry_delay`):

```python
_RETRY_MAX_ATTEMPTS = 3         # 1 initial + 2 retries (spec D3).
_RETRY_BASE_SECONDS = 2.0       # exponent base; 2,4s with cap.
_RETRY_CAP_SECONDS = 8.0
```

- [ ] **Step 4: Run tests, confirm they pass**

Run: `unset VIRTUAL_ENV && uv run pytest tests/test_llm_client.py -v`
Expected: **all 20 tests pass**.

- [ ] **Step 5: Commit**

```bash
git add tests/test_llm_client.py src/palimpsest/llm/client.py
git commit -m "feat(llm): 2-retry hard guarantee (8 attempts → 3) per spec D3"
```

---

## Task 3: Named score sentinels + `load_existing_ids` docstring

**Files:**
- Modify: `src/palimpsest/scoring.py`

- [ ] **Step 1: Add the constants and update the docstring**

Open `src/palimpsest/scoring.py`. Find the `LEGACY_CRITERIA` declaration (~line 64). Insert above it:

```python
# JSONL score field conventions (spec D4a). Use these constants at every write
# site so the magic numbers are never typed by hand.
#
# | value     | meaning                                                       | counted as done? |
# | --------- | ------------------------------------------------------------- | ---------------- |
# | int 1-10  | real judge score                                              | yes              |
# | None      | sentinel skip (picture / [TRANSLATION FAILED]); LLM not called| yes — terminal   |
# | -1        | LLM-level failure (parseable JSON missing the criterion key,  | no — re-evaluated|
# |           | or malformed JSON). Not a network error (those raise).        | on next run      |
#
# Anything labelled "done" is excluded from re-evaluation by load_existing_ids.
SCORE_LLM_FAIL: int = -1
SCORE_SKIPPED: None = None
```

Then update `load_existing_ids` (~line 187). Replace its docstring:

```python
def load_existing_ids(path: Path) -> set[int]:
    """Return paragraph ids that count as 'done' for this jsonl path.

    Resume contract (spec D4a):

    - `score` is a positive int (1-10): real judge score → counted as done.
    - `score` is `None` (SCORE_SKIPPED): sentinel skip (picture marker or
      [TRANSLATION FAILED] paragraph). Terminal — counted as done, never
      re-evaluated.
    - `score == -1` (SCORE_LLM_FAIL): LLM-level failure — parseable JSON
      missing the criterion key, or malformed JSON. NOT counted as done,
      so the next run retries this paragraph. Bounded by paragraph count;
      idempotent (next attempt overwrites).
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
            if "id" not in row:
                continue
            if row.get("score") == SCORE_LLM_FAIL:
                continue
            ids.add(row["id"])
    return ids
```

- [ ] **Step 2: Replace literal `-1` write sites with `SCORE_LLM_FAIL`**

Find the two surviving call sites of `"score": -1` in `scoring.py`. They're inside `parse_judge_response`'s fallback and inside `score_consolidated`'s missing-criterion branch.

In `parse_judge_response` (~line 54):

```python
def parse_judge_response(raw: str) -> dict:
    """Extract a JSON object from a judge response.

    Handles markdown ```json fences and prose before/after the JSON.
    Returns {"final_score": SCORE_LLM_FAIL, "llm_report": <raw>} on parse failure.
    """
    if not raw or not raw.strip():
        return {"final_score": SCORE_LLM_FAIL, "llm_report": raw or ""}
    match = _JSON_FENCE.search(raw)
    candidate = match.group(1) if match else raw
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        return {"final_score": SCORE_LLM_FAIL, "llm_report": raw}
```

In `score_consolidated`'s missing-criterion branch (~line 146):

```python
            if not isinstance(payload, dict):
                out[criterion] = {
                    "final_score": SCORE_LLM_FAIL,
                    "llm_report": f"missing criterion {criterion} in {prompt_name} response",
                }
```

In `_skip_payload` (~line 264):

```python
def _skip_payload(reason: str) -> dict:
    return {
        "final_score": SCORE_SKIPPED,
        "summary": "",
        "identified_issues": [],
        "llm_report": f"skipped: {reason}",
    }
```

Also update the sentinel-row build inside `_process` in `_score_run_for_judge` (the `kind in ("marker", "translation_failed")` branch) and inside `_score_factcheck_for_run`'s marker branch — replace literal `"score": None` with `"score": SCORE_SKIPPED`.

- [ ] **Step 3: Run tests, confirm green**

Run: `unset VIRTUAL_ENV && uv run pytest tests/ -q`
Expected: **121 tests pass** — pure refactor, no behavior change.

- [ ] **Step 4: Commit**

```bash
git add src/palimpsest/scoring.py
git commit -m "refactor(scoring): name score sentinels (SCORE_LLM_FAIL, SCORE_SKIPPED) per D4a"
```

---

## Task 4: Wire `cfg.max_concurrency` into `_build_client`, drop local `Semaphore` in scoring tasks

**Files:**
- Modify: `src/palimpsest/scoring.py`
- Modify: `tests/test_scoring_dispatcher.py`

- [ ] **Step 1: Update `_build_client` signature**

Find `_build_client` (~line 226) and change to:

```python
def _build_client(model_key: str, max_concurrency: int = 0) -> LLMClient:
    """Build an LLMClient for a model_key in configs/models.yaml.

    Module-level indirection so tests can monkeypatch.
    """
    models = load_models()
    if model_key not in models:
        raise KeyError(f"model {model_key!r} not found in models.yaml")
    return LLMClient(
        LLMConfig.from_model_config(models[model_key]),
        max_concurrency=max_concurrency,
    )
```

- [ ] **Step 2: Drop local `Semaphore` in `_score_run_for_judge`**

Find `_score_run_for_judge` (~line 277). Replace the lines that build `client` and `sem`:

```python
    client = _build_client(judge.model, max_concurrency=cfg.max_concurrency)
```

(Delete the `sem = asyncio.Semaphore(_judge_max_concurrency(judge, cfg))` line entirely.)

Inside `_process`, remove the `async with sem:` wrapper around the LLM logic — the client owns the gate now. The remaining body should look like:

```python
    async def _process(i: int, source: str, translated: str) -> None:
        if all(i in existing[c] for c in LEGACY_CRITERIA):
            return
        kind = classify_paragraph(source)
        if kind == "translation_failed":
            print(
                f"warning: [TRANSLATION FAILED] at id={i} for {run}",
                flush=True,
            )
        rows: dict[str, dict] = {}
        if kind in ("marker", "translation_failed"):
            reason = "marker" if kind == "marker" else "translation_failed"
            for criterion in LEGACY_CRITERIA:
                if i in existing[criterion]:
                    continue
                payload = _skip_payload(reason)
                rows[criterion] = {
                    "id": i,
                    "source": source,
                    "translated": translated,
                    "judge": judge.model,
                    "variant": variant,
                    "score": SCORE_SKIPPED,
                    "llm_report": payload["llm_report"],
                }
        else:
            results = await _score_paragraph(
                client=client,
                variant=variant,
                prompts=prompts,
                source=source,
                translated=translated,
            )
            for criterion, payload in results.items():
                if i in existing[criterion]:
                    continue
                rows[criterion] = {
                    "id": i,
                    "source": source,
                    "translated": translated,
                    "judge": judge.model,
                    "variant": variant,
                    "score": payload.get("final_score"),
                    "llm_report": json.dumps(payload, ensure_ascii=False),
                }
        async with write_lock:
            for criterion, row in rows.items():
                append_jsonl_row(target_paths[criterion], row)
```

- [ ] **Step 3: Drop local `Semaphore` in `_score_factcheck_for_run`**

Find `_score_factcheck_for_run` (~line 380). Replace the client/sem lines:

```python
    client = _build_client(cfg.factcheck.judge, max_concurrency=cfg.max_concurrency)
```

(Delete the `sem = asyncio.Semaphore(cfg.max_concurrency)` line.)

Inside `_process`, remove `async with sem:`. Body becomes:

```python
    async def _process(i: int, source: str, translated: str) -> None:
        if i in existing:
            return
        kind = classify_paragraph(source)
        if kind in ("marker", "translation_failed"):
            row = {
                "id": i,
                "source": source,
                "translated": translated,
                "score": SCORE_SKIPPED,
                "llm_report": f"skipped: {kind}",
            }
        else:
            fc = await score_factcheck(client, source, translated)
            row = {"id": i, "source": source, "translated": translated, **fc}
        async with write_lock:
            append_jsonl_row(target, row)
```

- [ ] **Step 4: Run tests, confirm green**

Run: `unset VIRTUAL_ENV && uv run pytest tests/ -q`
Expected: **121 tests pass** — the mock client in `test_scoring_dispatcher.py` does not exercise the semaphore so behavior is unchanged.

- [ ] **Step 5: Commit**

```bash
git add src/palimpsest/scoring.py
git commit -m "refactor(scoring): hand concurrency control to LLMClient (D2)"
```

---

## Task 5: Sequential dispatch in `run_scoring`

**Files:**
- Modify: `src/palimpsest/scoring.py`
- Modify: `tests/test_scoring_dispatcher.py`

- [ ] **Step 1: Append a failing test**

Append to `tests/test_scoring_dispatcher.py`:

```python
import asyncio


async def test_run_scoring_dispatch_order_is_factcheck_then_judges_per_run(
    repo_layout, mock_llm_client, monkeypatch
):
    """Per spec D1: for each run, factcheck completes before any judge task
    for that run starts. Verified by ordering of mock calls."""
    base, prompts_root = repo_layout

    order: list[str] = []

    async def fake_factcheck(client, source, translated):
        order.append("factcheck")
        return {"score": 0.9, "precision": 1.0, "recall": 0.8, "llm_report": "ok"}

    monkeypatch.setattr("palimpsest.scoring.score_factcheck", fake_factcheck)

    orig_complete = mock_llm_client.complete.side_effect

    async def tagged_complete(system, user, **kw):
        order.append("judge")
        return await orig_complete(system, user, **kw)

    mock_llm_client.complete.side_effect = tagged_complete

    cfg = ScoringConfig(
        base_dir=base,
        prompts_root=prompts_root / "03_scoring",
        prompts_variant="full",
        factcheck=FactcheckConfig(enabled=True, judge="claude-opus-4.7-low"),
        judges=[JudgeConfig(model="claude-opus-4.7-low")],
        runs=["large/run_x"],
    )
    await run_scoring(cfg)

    first_judge_idx = order.index("judge")
    last_factcheck_idx = max(i for i, x in enumerate(order) if x == "factcheck")
    assert last_factcheck_idx < first_judge_idx, (
        f"factcheck must finish before any judge starts; got {order!r}"
    )
```

- [ ] **Step 2: Run the test, confirm it fails**

Run: `unset VIRTUAL_ENV && uv run pytest tests/test_scoring_dispatcher.py::test_run_scoring_dispatch_order_is_factcheck_then_judges_per_run -v`
Expected: **FAIL** — current `run_scoring` runs factcheck and judges concurrently via gather.

- [ ] **Step 3: Refactor `run_scoring` to sequential dispatch**

In `src/palimpsest/scoring.py`, replace the body of `run_scoring` (the part from `tasks: list = []` through the gather + post-processing). The full replacement:

```python
async def run_scoring(cfg: ScoringConfig, *, max_paragraphs: int | None = None) -> None:
    """Main entry. Sequentially: for each run, factcheck → each judge. Spec D1."""
    n_runs = len(cfg.runs)
    n_per_run = (1 if cfg.factcheck.enabled else 0) + len(cfg.judges)
    total = n_runs * n_per_run
    config_start = time.time()
    completed = 0
    print(
        f"[scoring] {total} tasks starting "
        f"({n_runs} runs × ({len(cfg.judges)} judges"
        f"{' + factcheck' if cfg.factcheck.enabled else ''}))",
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
                _score_factcheck_for_run(
                    cfg=cfg, run=run, max_paragraphs=max_paragraphs
                ),
                f"{run} × factcheck",
            )
        for judge in cfg.judges:
            await _run_task(
                _score_run_for_judge(
                    cfg=cfg, run=run, judge=judge, max_paragraphs=max_paragraphs
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
        include_factcheck=cfg.factcheck.enabled,
    )

    if failed_tasks:
        raise RuntimeError(
            f"{len(failed_tasks)}/{total} scoring tasks raised after retries; "
            f"first: {failed_tasks[0][0]}: {failed_tasks[0][1]!r}"
        )
```

- [ ] **Step 4: Run tests, confirm green**

Run: `unset VIRTUAL_ENV && uv run pytest tests/ -q`
Expected: **122 tests pass** (121 existing + 1 new).

- [ ] **Step 5: Commit**

```bash
git add src/palimpsest/scoring.py tests/test_scoring_dispatcher.py
git commit -m "feat(scoring): sequential dispatch — one run at a time, factcheck → judges (D1)"
```

---

## Task 6: `asyncio.as_completed` + tqdm progress per task

**Files:**
- Modify: `src/palimpsest/scoring.py`

- [ ] **Step 1: Add the import**

In `src/palimpsest/scoring.py`, add the import near the other imports:

```python
from tqdm.asyncio import tqdm as async_tqdm
```

- [ ] **Step 2: Replace the per-paragraph gather in `_score_run_for_judge`**

In `_score_run_for_judge`, find the block that starts with `results = await asyncio.gather(` (the post-`_process`-definition gather). Replace it with:

```python
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

- [ ] **Step 3: Replace the per-paragraph gather in `_score_factcheck_for_run`**

In `_score_factcheck_for_run`, find the `results = await asyncio.gather(...)` block. Replace with:

```python
    tasks = [_process(i, ru, en) for i, (ru, en) in enumerate(pairs)]
    failures: list[BaseException] = []
    with async_tqdm(total=len(tasks), desc=f"{run} × factcheck", file=sys.stderr) as bar:
        for coro in asyncio.as_completed(tasks):
            try:
                await coro
            except BaseException as exc:
                failures.append(exc)
                async_tqdm.write(
                    f"warning: factcheck paragraph failed for {run}: {exc!r}",
                    file=sys.stderr,
                )
            bar.update(1)

    fc_dir.mkdir(parents=True, exist_ok=True)
    (fc_dir / "meta.json").write_text(
        json.dumps({"judge": cfg.factcheck.judge}, ensure_ascii=False, indent=2)
    )

    if failures:
        print(
            f"warning: {run} × factcheck: {len(failures)} paragraphs raised; "
            f"first error: {failures[0]!r}",
            file=sys.stderr,
            flush=True,
        )
        raise failures[0]
```

- [ ] **Step 4: Run tests, confirm green**

Run: `unset VIRTUAL_ENV && uv run pytest tests/ -q`
Expected: **122 tests pass**.

- [ ] **Step 5: Commit**

```bash
git add src/palimpsest/scoring.py
git commit -m "feat(scoring): per-paragraph tqdm progress via as_completed (D6)"
```

---

## Task 7: Paragraph-level resume verification test

**Files:**
- Create: `tests/test_scoring_resume.py`

- [ ] **Step 1: Write the new test file**

Create `tests/test_scoring_resume.py`:

```python
"""Verifies spec D4: a crash mid-task does not re-call already-scored paragraphs
on the next attempt. The mechanism is per-row fsync + load_existing_ids."""
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from palimpsest.config import FactcheckConfig, JudgeConfig, ScoringConfig
from palimpsest.scoring import run_scoring


@pytest.fixture
def repo_layout(tmp_path):
    base = tmp_path / "pilot"
    (base / "translating" / "large" / "run_x").mkdir(parents=True)
    (base / "translating" / "large" / "run_x" / "translation.md").write_text(
        "\n".join(f"line {i}" for i in range(5)) + "\n"
    )
    (base / "pilot_original.md").write_text(
        "\n".join(f"строка {i}" for i in range(5)) + "\n"
    )
    pr = tmp_path / "prompts" / "03_scoring" / "full"
    pr.mkdir(parents=True)
    (pr / "faithfulness.md").write_text("FAITH_PROMPT")
    (pr / "english_quality.md").write_text("ENGQ_PROMPT")
    return base, tmp_path / "prompts"


def _valid_faith() -> str:
    return (
        '```json\n'
        '{"accuracy":   {"final_score": 8, "summary": "a", "identified_issues": []},'
        ' "terminology":{"final_score": 7, "summary": "t", "identified_issues": []},'
        ' "cultural":   {"final_score": 9, "summary": "c", "identified_issues": []}}\n'
        '```'
    )


def _valid_engq() -> str:
    return (
        '```json\n'
        '{"source_structure_note": "n",'
        ' "fluency":     {"final_score": 8, "summary": "f", "identified_issues": []},'
        ' "style":       {"final_score": 7, "summary": "s", "identified_issues": []},'
        ' "consistency": {"final_score": 6, "summary": "k", "identified_issues": []}}\n'
        '```'
    )


async def test_resume_skips_paragraphs_already_persisted(repo_layout, monkeypatch):
    """First run crashes after 3 paragraphs land on disk. Second run only calls
    the LLM for the remaining 2."""
    base, prompts_root = repo_layout

    # Run 1: succeed on paragraphs 0,1,2 then start failing.
    calls_run1: list[int] = []

    async def first_run_complete(system, user, **kw):
        # source line is unique per paragraph — we use the line number to
        # decide success vs failure.
        idx = int(user.rsplit("строка ", 1)[1].split("\n", 1)[0])
        calls_run1.append(idx)
        if idx >= 3:
            raise RuntimeError("simulated crash")
        return _valid_faith() if "FAITH" in system else _valid_engq()

    client1 = AsyncMock()
    client1.complete.side_effect = first_run_complete
    monkeypatch.setattr("palimpsest.scoring._build_client", lambda *_a, **_kw: client1)

    cfg = ScoringConfig(
        base_dir=base,
        prompts_root=prompts_root / "03_scoring",
        prompts_variant="full",
        factcheck=FactcheckConfig(enabled=False),
        judges=[JudgeConfig(model="claude-opus-4.7-low")],
        runs=["large/run_x"],
    )

    with pytest.raises(RuntimeError):
        await run_scoring(cfg)

    # 3 paragraphs persisted on disk:
    jsonl = base / "evaluation" / "run_x" / "claude-opus-4.7-low" / "accuracy_scores.jsonl"
    ids_persisted = {
        json.loads(line)["id"]
        for line in jsonl.read_text().splitlines()
        if line.strip()
    }
    assert ids_persisted == {0, 1, 2}

    # Run 2: succeed for everyone.
    calls_run2: list[int] = []

    async def second_run_complete(system, user, **kw):
        idx = int(user.rsplit("строка ", 1)[1].split("\n", 1)[0])
        calls_run2.append(idx)
        return _valid_faith() if "FAITH" in system else _valid_engq()

    client2 = AsyncMock()
    client2.complete.side_effect = second_run_complete
    monkeypatch.setattr("palimpsest.scoring._build_client", lambda *_a, **_kw: client2)

    await run_scoring(cfg)

    # Only paragraphs 3 and 4 should have been LLM-called the second time:
    assert set(calls_run2) == {3, 4}
    # And every paragraph (0..4) ends up persisted:
    ids_final = {
        json.loads(line)["id"]
        for line in jsonl.read_text().splitlines()
        if line.strip()
    }
    assert ids_final == {0, 1, 2, 3, 4}
```

- [ ] **Step 2: Run the test, confirm it passes**

Run: `unset VIRTUAL_ENV && uv run pytest tests/test_scoring_resume.py -v`
Expected: **PASS** — fsync + load_existing_ids already provide this; we're locking the guarantee in.

- [ ] **Step 3: Run full suite**

Run: `unset VIRTUAL_ENV && uv run pytest tests/ -q`
Expected: **123 tests pass**.

- [ ] **Step 4: Commit**

```bash
git add tests/test_scoring_resume.py
git commit -m "test(scoring): paragraph-level resume guarantee (D4)"
```

---

## Task 8: Single-judge configs (gpt-5.5-low only)

**Files:**
- Modify: `configs/scoring/01-top-vs-baseline.yaml`
- Modify: `configs/scoring/02-large-chunking.yaml`
- Modify: `configs/scoring/03-small-anchor.yaml`
- Modify: `configs/scoring/04-small-chunking.yaml`
- Modify: `configs/scoring/05-family-and-alt.yaml`
- Modify: `configs/scoring/06-reasoning-low.yaml`

- [ ] **Step 1: Edit each yaml**

For each of the six configs, locate the `judges:` block and replace its contents with one entry. Example for `configs/scoring/01-top-vs-baseline.yaml` — leave every other field untouched, only the `judges:` block changes:

```yaml
judges:
  - model: gpt-5.5-low
```

Repeat verbatim for `02-large-chunking.yaml`, `03-small-anchor.yaml`, `04-small-chunking.yaml`, `05-family-and-alt.yaml`, `06-reasoning-low.yaml`.

Also update the leading comment in each file (the multi-line header that lists "Judge profile: large-low (opus-low + gemini-pro-low + gpt-5.5-low)" or similar). Change it to: `# Judge profile: single (gpt-5.5-low). Other judges plug back in later via D5.`

- [ ] **Step 2: Verify each yaml loads**

Run from worktree root:

```bash
unset VIRTUAL_ENV && uv run python -c "
from pathlib import Path
from palimpsest.config import load_scoring
for name in ['01-top-vs-baseline', '02-large-chunking', '03-small-anchor',
             '04-small-chunking', '05-family-and-alt', '06-reasoning-low']:
    cfg = load_scoring(Path(f'configs/scoring/{name}.yaml'))
    assert [j.model for j in cfg.judges] == ['gpt-5.5-low'], name
    print(name, 'OK')
"
```

Expected: six `OK` lines.

- [ ] **Step 3: Run full suite**

Run: `unset VIRTUAL_ENV && uv run pytest tests/ -q`
Expected: **123 tests pass**.

- [ ] **Step 4: Commit**

```bash
git add configs/scoring/01-top-vs-baseline.yaml configs/scoring/02-large-chunking.yaml \
        configs/scoring/03-small-anchor.yaml configs/scoring/04-small-chunking.yaml \
        configs/scoring/05-family-and-alt.yaml configs/scoring/06-reasoning-low.yaml
git commit -m "config(scoring): single judge gpt-5.5-low in priority configs (D5)"
```

---

## Task 9: E2e smoke harness

**Files:**
- Modify: `configs/scoring/smoke.yaml`
- Create: `scripts/03_scoring_smoke.sh`

- [ ] **Step 1: Replace `smoke.yaml` with the spec D7 version**

Open `configs/scoring/smoke.yaml` (it already exists with a stale haiku config). Replace the entire file:

```yaml
# Smoke test: real OpenRouter calls on 50 paragraphs of local/qwen_par_by_par.
# factcheck (gpt-mini) + 1 judge (gpt-5.5-low) exercise the full pipeline.
# Output: data/pilot/evaluation_smoke/  (NOT real evaluation data).
# Re-runnable: load_existing_ids skips paragraphs already on disk.
# Run: bash scripts/03_scoring_smoke.sh
base_dir: data/pilot
evaluation_subdir: evaluation_smoke
prompts_variant: full
max_concurrency: 4
factcheck:
  enabled: true
  judge: gpt-5.4-mini-low
judges:
  - model: gpt-5.5-low
runs:
  - local/qwen_par_by_par
```

- [ ] **Step 2: Create the smoke wrapper script**

Create `scripts/03_scoring_smoke.sh`:

```bash
#!/usr/bin/env bash
# Smoke test: real OpenRouter calls on 50 paragraphs of one already-translated run.
# Exercises factcheck + scoring + merge + aggregate end-to-end. Output goes to
# data/pilot/evaluation_smoke/  (deliberately separate from real evaluation/).
#
# Resume: load_existing_ids skips paragraphs already on disk; re-run safely.
# To start fresh: rm -rf data/pilot/evaluation_smoke/
#
# Tune: MAX_PARAGRAPHS=20 MAX_CONCURRENCY=2 bash scripts/03_scoring_smoke.sh
set -euo pipefail

CONFIG=configs/scoring/smoke.yaml
N="${MAX_PARAGRAPHS:-50}"
CONC="${MAX_CONCURRENCY:-4}"
LOG=data/pilot/evaluation_smoke/smoke.log

mkdir -p "$(dirname "$LOG")"
echo "[smoke] $(date +%H:%M:%S) config=$CONFIG n=$N concurrency=$CONC"

uv run python scripts/03_translation_scoring.py \
  --config "$CONFIG" \
  --max-paragraphs "$N" \
  --max-concurrency "$CONC" \
  >>"$LOG" 2> >(tee -a "$LOG" >&2)

echo "[smoke] $(date +%H:%M:%S) done. Output: data/pilot/evaluation_smoke/"
```

Then make it executable:

```bash
chmod +x scripts/03_scoring_smoke.sh
```

- [ ] **Step 3: Smoke-check the smoke script — bash syntax + config loads**

Run:

```bash
bash -n scripts/03_scoring_smoke.sh && echo "bash syntax OK"
unset VIRTUAL_ENV && uv run python -c "
from pathlib import Path
from palimpsest.config import load_scoring
cfg = load_scoring(Path('configs/scoring/smoke.yaml'))
assert cfg.evaluation_subdir == 'evaluation_smoke'
assert [j.model for j in cfg.judges] == ['gpt-5.5-low']
assert cfg.factcheck.enabled
print('smoke cfg OK')
"
```

Expected: `bash syntax OK` and `smoke cfg OK`.

- [ ] **Step 4: Commit**

```bash
git add configs/scoring/smoke.yaml scripts/03_scoring_smoke.sh
git commit -m "feat(scoring): smoke harness — 50 paragraphs, isolated output (D7)"
```

---

## Task 10: JSONL row schema in the pipeline contract + reader's note

**Files:**
- Modify: `references/interfaces_agreement.md`
- Create: `data/pilot/evaluation/README.md`

- [ ] **Step 1: Add the schema subsection to `interfaces_agreement.md`**

Open `references/interfaces_agreement.md`. Find an existing Stage 04 / scoring section (or the end of file if none). Append:

```markdown
### Scoring JSONL row schema

Files under `data/pilot/<evaluation_subdir>/<run>/<judge>/<criterion>_scores.jsonl`
and `data/pilot/<evaluation_subdir>/<run>/factcheck/factcheck_scores.jsonl` use
the following schema for the `score` field (spec D4a):

| `score` value | Meaning | Counted as done by `load_existing_ids`? |
|---|---|---|
| `int` in `1..10` | Real judge score | yes |
| `null` (Python `None`) | Sentinel skip — paragraph is a picture marker (`==> picture ... <==`, `* * *`) or `[TRANSLATION FAILED]`. The LLM was never called. | **yes** — terminal, never re-evaluated |
| `-1` | LLM-level failure: parseable JSON missing the criterion key, or malformed JSON survived `parse_judge_response`. Network/transient errors do **not** produce `-1` — they raise. | **no** — re-evaluated on next run |

Companion fields:

- `id` (int): paragraph index (0-based, aligned with `pilot_original.md` and `translation.md`).
- `source` (str): the Russian paragraph.
- `translated` (str): the English paragraph.
- `judge` (str): model key from `configs/models.yaml` (judge JSONL only).
- `variant` (str): prompt variant, "full" | "compact" | "old" (judge JSONL only).
- `llm_report` (str): JSON-encoded judge payload on success, free-text on skip/fail.

For factcheck rows, additional fields:

- `precision`, `recall` (float | None): two-sided atomic-fact overlap stats.
- `matches`, `unmatched_ru`, `unmatched_en` (list): per-claim breakdown.

The dispatcher uses `SCORE_LLM_FAIL` and `SCORE_SKIPPED` constants
([src/palimpsest/scoring.py](../src/palimpsest/scoring.py)) at every write
site — readers should never see literal `-1` / `null` magic in the source.

Spec: [docs/superpowers/specs/2026-05-13-scoring-v2-sequential-runs.md](../docs/superpowers/specs/2026-05-13-scoring-v2-sequential-runs.md).
```

- [ ] **Step 2: Create the reader's note**

Create `data/pilot/evaluation/README.md`:

```markdown
# Stage 04 evaluation outputs

Up: [docs/pipeline.md](../../../docs/pipeline.md) · Stage doc: [docs/stages/04_scoring.md](../../../docs/stages/04_scoring.md) · Contract: [references/interfaces_agreement.md § Scoring JSONL row schema](../../../references/interfaces_agreement.md).

## What you see here

Each `<run_name>/` has one folder per judge plus a `factcheck/` folder:

```
qwen_par_by_par/
├── factcheck/
│   ├── factcheck_scores.jsonl   # one row per paragraph
│   └── meta.json
├── gpt-5.5-low/
│   ├── accuracy_scores.jsonl    # one row per paragraph per criterion
│   ├── terminology_scores.jsonl
│   ├── cultural_scores.jsonl
│   ├── fluency_scores.jsonl
│   ├── style_scores.jsonl
│   ├── consistency_scores.jsonl
│   └── meta.json
└── merged_scores.jsonl          # wide per-paragraph view across criteria
```

`../scores.json` at the parent level holds the cross-run aggregate.

## Reading the score column

| value | meaning |
|---|---|
| 1–10 | real score from the judge |
| `null` | paragraph was skipped — picture/dinkus marker or `[TRANSLATION FAILED]` from translation stage. Never re-scored. |
| `-1` | LLM gave a response we couldn't parse (missing key or non-JSON). Will be re-scored on the next pilot run. Network / 429 errors are **not** in this bucket — those crash the process so the wrapper retries. |

Anything you'd want to ask "is this paragraph done?" → use `load_existing_ids` in `palimpsest.scoring`, or filter out `score == -1` yourself.

## Re-running

```bash
bash scripts/03_scoring_exprs.sh   # full P1-P6 sweep
bash scripts/03_scoring_smoke.sh   # 50 paragraphs into evaluation_smoke/
```

Both are crash-safe: every successful paragraph fsyncs before its task moves on, so killing the process loses at most the paragraphs currently in flight.
```

- [ ] **Step 3: Commit**

```bash
git add references/interfaces_agreement.md data/pilot/evaluation/README.md
git commit -m "docs(contract): scoring JSONL row schema + evaluation/ reader's note (D4a)"
```

---

## Task 11: Stage doc + pipeline.md sync

**Files:**
- Modify: `docs/stages/04_scoring.md`
- Modify: `docs/pipeline.md`

- [ ] **Step 1: Update stage doc with v2 design notes**

Open `docs/stages/04_scoring.md`. Locate the "Subtleties" or "Design decisions" section (the structure is fixed per CLAUDE.md). Append a numbered point:

```markdown
- **Sequential dispatch (v2, 2026-05-13).** `run_scoring` processes runs strictly sequentially; within a run, factcheck runs to completion before any judge task starts. `MAX_CONCURRENCY` is enforced inside `LLMClient` via a constructor-injected `asyncio.Semaphore`, so the value is the literal cap on simultaneous HTTP calls. Spec: [docs/superpowers/specs/2026-05-13-scoring-v2-sequential-runs.md](../superpowers/specs/2026-05-13-scoring-v2-sequential-runs.md).
- **Score sentinel semantics.** `score=-1` means the LLM returned an unusable response (parseable JSON missing the criterion key, or malformed JSON); `load_existing_ids` excludes these so they retry on the next run. `score=null` is a terminal sentinel skip (picture markers, `[TRANSLATION FAILED]`). Network/transient errors never reach the JSONL — they raise out of `LLMClient.complete` after 2 retries.
- **Smoke harness.** `scripts/03_scoring_smoke.sh` exercises factcheck + scoring on 50 paragraphs of `local/qwen_par_by_par` and writes to `data/pilot/evaluation_smoke/` so real evaluation data is never touched. Run before kicking off P1-P6 sweeps.
```

Update the **Status** section's bullet list (or add one) to reflect v2 completion:

```markdown
- v2 sequential dispatch + per-call concurrency cap + 2-retry hard guarantee shipped 2026-05-13. Single judge `gpt-5.5-low` in 01-06 configs; other judges fill in via resume.
```

- [ ] **Step 2: Update pipeline.md status line for Stage 04**

Open `docs/pipeline.md`. Find the Stage 04 section. Update its "Status" or status sentence to:

```markdown
- Stage 04 — Scoring + factcheck: **v2 shipped 2026-05-13** (sequential dispatch, per-call concurrency cap, 2-retry hard router guarantee, paragraph-level resume). Single judge `gpt-5.5-low`; other judges pluggable later.
```

(If the exact wording differs in the existing doc, preserve surrounding format and just match the date + bullet content.)

- [ ] **Step 3: Run full suite**

Run: `unset VIRTUAL_ENV && uv run pytest tests/ -q`
Expected: **123 tests pass**.

- [ ] **Step 4: Commit**

```bash
git add docs/stages/04_scoring.md docs/pipeline.md
git commit -m "docs(stages): scoring v2 status + sentinel semantics (D1, D3, D4a, D7)"
```

---

## Task 12: Backward-compat verification (translate + factcheck CLI)

**Files:**
- (no code changes — verification only)

- [ ] **Step 1: Run the translate-side and factcheck-side test files**

Run:

```bash
unset VIRTUAL_ENV && uv run pytest \
  tests/test_translate_chunked.py \
  tests/test_llm_client.py \
  tests/test_scoring_strategy_factcheck.py \
  tests/test_scoring_strategy_consolidated.py \
  tests/test_scoring_strategy_legacy.py \
  -v
```

Expected: **all green** — these exercise the LLMClient via mocks and the factcheck primitives; nothing about our changes is supposed to affect them.

- [ ] **Step 2: Verify `LLMClient` callers compile**

Run a smoke import for each caller outside scoring:

```bash
unset VIRTUAL_ENV && uv run python -c "
from palimpsest.translate import translate_per_paragraph, translate_chunked
from palimpsest.correction import run_correction
from palimpsest.factcheck.extractor import FactExtractor
from palimpsest.factcheck.overlap import FactOverlap
print('all caller imports OK')
"
```

Expected: `all caller imports OK`.

- [ ] **Step 3: Full suite, one more time**

Run: `unset VIRTUAL_ENV && uv run pytest tests/ -v`
Expected: **123 tests pass**, no warnings about deprecated args.

- [ ] **Step 4: Manual smoke (real API, user-driven)**

Hand off to the user. The command to run is:

```bash
bash scripts/03_scoring_smoke.sh
```

Expected on stderr:

```
[smoke] HH:MM:SS config=configs/scoring/smoke.yaml n=50 concurrency=4
[scoring] 2 tasks starting (1 runs × (1 judges + factcheck))
local/qwen_par_by_par × factcheck: 100%|████| 50/50 [...]
[1/2] done in Xs (total Xs): local/qwen_par_by_par × factcheck
local/qwen_par_by_par × gpt-5.5-low: 100%|████| 50/50 [...]
[2/2] done in Xs (total Xs): local/qwen_par_by_par × gpt-5.5-low
[scoring] all 2 tasks done in Xs
[smoke] HH:MM:SS done. Output: data/pilot/evaluation_smoke/
```

User then inspects:

```bash
ls data/pilot/evaluation_smoke/qwen_par_by_par/
wc -l data/pilot/evaluation_smoke/qwen_par_by_par/gpt-5.5-low/accuracy_scores.jsonl   # 50
wc -l data/pilot/evaluation_smoke/qwen_par_by_par/factcheck/factcheck_scores.jsonl    # 50
grep -c '"score": -1' data/pilot/evaluation_smoke/qwen_par_by_par/gpt-5.5-low/*.jsonl  # near 0
```

Optional but recommended: re-run the smoke a second time — must skip everything and finish in seconds (resume guarantee, spec D4).

- [ ] **Step 5: Final commit (if any)**

If steps 1-3 surfaced any test/doc adjustments, commit them now. If not, this task ends without a commit. Either way, the branch is ready to merge into `feat/chunking-format` (and from there to `feat/project` per project workflow).

---

## Done conditions

- All 12 tasks complete.
- 123 unit tests pass.
- Smoke run produces `data/pilot/evaluation_smoke/` with 50 factcheck rows and 50 × 6 criterion rows.
- Re-running the smoke is a no-op (resume).
- No `score == -1` from network errors anywhere in smoke output.
- `references/interfaces_agreement.md` and `data/pilot/evaluation/README.md` describe the conventions.
- `feat/scoring-v2-sequential` branch has 12 conventional-commit messages, ready for PR back to `feat/chunking-format`.
