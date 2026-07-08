# Scoring v2 — sequential runs + call-level concurrency + 2-retry hard guarantee

Up: [docs/superpowers/specs/](.)
Related: [docs/experiments/2026-05-13-pilot-evaluation.md](../../experiments/2026-05-13-pilot-evaluation.md), [docs/pipeline.md](../../pipeline.md)

## Motivation

The P1 (01-top-vs-baseline) scoring run on 2026-05-13 11:48 spent ~50 min on a single (run × judge) task and persisted 542/549 paragraphs as `score=-1`. Root causes (in compounding order):

1. **`MAX_CONCURRENCY` lied**: defined as a per-`_score_run_for_judge` cap, distributed as `max_concurrency // len(judges) = 4`, applied to 18 simultaneous (judge × run) tasks → real OpenRouter load was ~144 concurrent calls. `MAX_CONCURRENCY=12` did NOT mean 12.
2. **Soft `-1` fallback** in `_process` (scoring.py:345-363 pre-fix): any exception → `score=-1` written, no retry, process exits 0, wrapper moves on. Transient errors became permanent data.
3. **Empty-content invisible**: gpt-5.5-low under load returned 200 OK with `content=""`; parsed to `{"final_score": -1, "llm_report": ""}`; no exception → 240/549 missing-criterion rows with no retry signal.
4. **Bulk-write per task**: 549 paragraphs accumulated in memory until task completion → killing mid-task lost everything.

Today's fix (uncommitted on `feat/chunking-format`) addresses (2), (3), (4) — per-row fsync, retry-on-transient with empty-content detection, hard re-raise at task and `run_scoring` level. **Still broken**: (1) is unchanged, and the dispatcher fans 24 tasks out in parallel, so progress is opaque ("nothing for 35 min, then 24 lines arrive at once").

This spec re-architects the dispatcher and `LLMClient` so that `MAX_CONCURRENCY` is the **exact** cap on simultaneous HTTP calls, progress is by completed translations, the router guarantees correct LLM responses with no `-1` ever from network/transient errors, and resume is paragraph-granular on every crash.

## Decisions

### D1. Sequential per run, sequential factcheck → scoring inside run

`run_scoring` becomes:

```python
for run in cfg.runs:
    if cfg.factcheck.enabled:
        await _score_factcheck_for_run(..., run, ...)
    for judge in cfg.judges:
        await _score_run_for_judge(..., run, judge, ...)
```

No `asyncio.gather` across runs or across (factcheck, judges) of the same run. Only **one** rate-limit bucket is active at any moment → `MAX_CONCURRENCY` is the only knob in play. Trade-off: total wall-time grows ~2× vs full parallel, but is predictable, observable, and the only mode that matches the user's mental model of "concurrent in-flight HTTP requests = MAX_CONCURRENCY".

### D2. Semaphore is a runtime parameter of `LLMClient`, not part of `LLMConfig`

`LLMConfig` stays a pure model-identity object built from `configs/models.yaml`. Concurrency is a **runtime** control, so it lives on the client:

```python
class LLMClient:
    def __init__(self, config: LLMConfig, *, max_concurrency: int = 0):
        ...
        # 0 / negative → effectively unlimited (we never run that hot
        # in this pipeline; the sequential dispatcher gives us the real cap).
        effective = max_concurrency if max_concurrency > 0 else 2**20
        self._gate = asyncio.Semaphore(effective)
```

Every `complete()` call enters `async with self._gate` around the SDK request. Because dispatch is sequential (D1), only one client's gate is being acquired at any time → the semaphore value is the literal max in-flight HTTP requests to OpenRouter / Anthropic. `models.yaml` keeps zero knowledge of runtime tuning; the dispatcher passes `cfg.max_concurrency` through `_build_client` → `LLMClient(...)`.

### D3. Hard 2-retry guarantee on transient errors, no `-1` fallback

`LLMClient.complete` performs exactly **2 retries (3 attempts total)** for:

- `openai.RateLimitError`, `anthropic.RateLimitError`
- `openai.APIConnectionError`, `anthropic.APIConnectionError`
- `openai.APITimeoutError`, `anthropic.APITimeoutError`
- `openai.APIStatusError` / `anthropic.APIStatusError` with `status_code >= 500`
- `EmptyContentError` — provider returned 200 OK with `content.strip() == ""`

Backoff: full-jitter exponential, base 2s, cap 8s. Worst case wait per call: ~0 + 2 + 4 ≈ 6s plus jitter (~10s). After 3 attempts the last exception is **raised**, never converted to `-1`.

`-1` in JSONL means **only one thing now**: the LLM returned parseable JSON missing the expected criterion key (a real LLM-level semantic failure that retrying inside the same run won't fix). All previously-written `-1` rows from transient errors are picked up on next run by `load_existing_ids`, which already excludes `score == -1`.

Already partially implemented today (8 retries, cap 60s); this spec **reduces** to 2 retries because we want fast crash → wrapper restart instead of long in-process backoff.

### D4. Paragraph-level resume is a first-class guarantee

The pipeline must be safe to kill at any point — the next start MUST pick up at the first not-yet-completed paragraph. Mechanism:

1. **Per-row fsync.** `append_jsonl_row` flushes + `os.fsync` after every JSONL append. No paragraph appears in memory without also being on disk.
2. **`_process` writes inline.** Successful row(s) are appended to JSONL inside `_process`, under an `asyncio.Lock`, **before** the function returns. No bulk-write-after-gather.
3. **`load_existing_ids` filters at task start.** Reads the JSONL, returns the set of paragraph IDs that count as "done" (see D4a for the exact rule). `_process` short-circuits if all criteria for an `id` are already in that set.
4. **Crash mid-`_process`** (between LLM response and JSONL write): no row is written → next run re-issues the LLM call. At-least-once, not exactly-once; idempotent in practice because the score is overwritten on success.

The translate-stage equivalent is `ProgressLog` ([translate.py:25-87](../../../src/palimpsest/translate.py#L25-L87)). Our scoring already has the same property; this decision pins it down explicitly so future refactors don't accidentally break it.

Verification: `tests/test_scoring_resume.py` (new) — start scoring on 5 paragraphs, kill the LLM client after paragraph 3, restart, assert paragraphs 4-5 are the only ones whose `complete()` is called the second time.

### D4a. `score` field semantics are spelled out — no magic numbers

The `score` field in scoring JSONL files (`<criterion>_scores.jsonl`, `factcheck_scores.jsonl`) takes three classes of values and they MUST be self-explanatory to anyone reading the data or the code:

| Value | Meaning | Counted as "done" by `load_existing_ids`? |
|---|---|---|
| `1`–`10` (int) | Real judge score for that criterion. | Yes |
| `None` | Sentinel skip: the paragraph is a picture-marker (`==> picture ... <==`, `* * *`) or `[TRANSLATION FAILED]`. The judge was never called. | **Yes** — sentinels are terminal, never re-evaluated. |
| `-1` | LLM-level failure: 200 OK with parseable JSON that's missing the expected criterion key, or malformed JSON that survived `parse_judge_response`. **Not** a network/transient error (those raise instead). | **No** — `-1` rows are treated as "not yet evaluated" so the next run retries the paragraph. The retry is bounded by paragraph count; if the LLM keeps hallucinating, the `-1` keeps overwriting itself (idempotent), which is the intended behaviour. |

Practical concrete steps to make this readable:

1. **Named constants** at top of `scoring.py`:
   ```python
   # See D4a in docs/superpowers/specs/2026-05-13-scoring-v2-sequential-runs.md
   SCORE_LLM_FAIL: int = -1     # parsed-but-malformed judge response; retried on resume
   SCORE_SKIPPED: None = None    # picture / [TRANSLATION FAILED] sentinel; terminal
   ```
   Every code path that writes `-1` or `None` references one of these constants. `parse_judge_response`'s `final_score` fallback uses `SCORE_LLM_FAIL`.
2. **`load_existing_ids` docstring** spells out exactly the table above, links to D4a by anchor.
3. **`references/interfaces_agreement.md`** gets a "Scoring JSONL row schema" subsection that includes this table and links back to this spec. Per CLAUDE.md routing, that file is the pipeline contract — it's where this lives long-term.
4. **`data/pilot/evaluation/README.md`** (new, one paragraph) for anyone arriving at the data: "what the columns mean, why some rows have score=null vs -1, how to spot still-todo paragraphs".

Why not introduce an explicit `status` enum field on every row? Considered and rejected: it would either duplicate `score` (redundant) or require a JSONL schema migration of existing data. The cost of documenting the conventions in code + a contract file is much lower than schema migration, and the constants make the code self-explanatory without changing what hits disk.

### D5. Drop multi-judge configs; single judge `gpt-5.5-low`

Edit `configs/scoring/01-top-vs-baseline.yaml` through `06-reasoning-low.yaml` in-place: keep only `gpt-5.5-low` in the `judges:` list. Factcheck (`gpt-5.4-mini-low`) is unchanged. Other judges (opus-low, gemini-pro-low) can be added back any time — `load_existing_ids` skips already-done paragraphs for the existing judge and the new judge's directory simply starts empty.

This is a config change, not a code change; the dispatcher already iterates `cfg.judges` correctly. The reason for D5 is purely pilot-velocity: one judge × one factcheck = one bucket at a time, and the science (RQ1/RQ2) is still answerable with a single judge column.

### D6. Per-paragraph progress via `asyncio.as_completed` + manual `tqdm`

`tqdm.asyncio.tqdm.gather` does not support `return_exceptions=True`, and we want sibling paragraphs to keep persisting until the gather finishes (then raise). The cleanest pattern is:

```python
errors: list[BaseException] = []
with tqdm(total=len(tasks), desc=label, file=sys.stderr) as bar:
    for coro in asyncio.as_completed(tasks):
        try:
            await coro
        except BaseException as exc:
            errors.append(exc)
        bar.update(1)
if errors:
    raise errors[0]
```

This guarantees: every paragraph that completes successfully fsyncs its row (D4), the bar advances even when others raise, and after all are done the first exception bubbles up. Per-paragraph warnings use `tqdm.write` so they don't break the bar.

One bar at a time (D1 makes this natural). Between tasks: a `[K/N] {label} done in Xs (total Ys)` line, as today.

### D7. End-to-end smoke harness

Add `configs/scoring/smoke.yaml` and `scripts/03_scoring_smoke.sh` for a real-API but small workload that exercises the full pipeline (factcheck + scoring + merge + aggregate) on 50 paragraphs of one run.

Smoke config:

```yaml
# configs/scoring/smoke.yaml
base_dir: data/pilot
translations_subdir: translating
evaluation_subdir: evaluation_smoke   # never poisons real evaluation data
prompts_root: prompts/03_scoring
prompts_variant: full
max_concurrency: 4
runs:
  - large/qwen_par_by_par              # has translation.md committed
judges:
  - model: gpt-5.5-low
factcheck:
  enabled: true
  judge: gpt-5.4-mini-low
```

Smoke script:

```bash
#!/usr/bin/env bash
# scripts/03_scoring_smoke.sh
# Real API, 50 paragraphs, factcheck + scoring on one run. ~$0.10, ~3-5 min.
# Output: data/pilot/evaluation_smoke/qwen_par_by_par/
# Resume: re-run; load_existing_ids skips done IDs.
set -euo pipefail
uv run python scripts/03_translation_scoring.py \
  --config configs/scoring/smoke.yaml \
  --max-paragraphs 50
```

Purpose: human-inspect output before triggering a full P1 run; CI doesn't need to gate on this.

Verification: documented in README of the script as "expected output files:" — `factcheck_scores.jsonl` (50 rows), 6× `*_scores.jsonl` (50 rows each), `merged_scores.jsonl`, `meta.json`, `evaluation_smoke/scores.json`.

## Backward compatibility with other `LLMClient` consumers

`LLMClient` is used by four call sites outside this spec; D2 and D3 must not regress them.

| Caller | File | Construction | Use pattern |
|---|---|---|---|
| Translate (mode A chunked) | [translate.py:237](../../../src/palimpsest/translate.py#L237) | [02_translate.py:65](../../../scripts/02_translate.py#L65) | `async with caller_semaphore: await client.complete(...)`; on exception → process crash → `02_translate_pilot_resume.sh` restart → `progress.jsonl` resume |
| Translate (mode B per-paragraph) | [translate.py:314](../../../src/palimpsest/translate.py#L314) | same | identical |
| Correction | [correction.py:56-70](../../../src/palimpsest/correction.py#L56-L70) | self | `async with caller_semaphore: await llm.complete(...)`; no try/except |
| Factcheck CLI | [03_factcheck.py:27-31](../../../scripts/03_factcheck.py#L27-L31) | self | via `FactExtractor` / `FactOverlap` instances |
| Factcheck inside scoring | [factcheck/extractor.py:32](../../../src/palimpsest/factcheck/extractor.py#L32), [overlap.py:24](../../../src/palimpsest/factcheck/overlap.py#L24) | scoring `_build_client` | via the same instances |

Compat checks against D2 (semaphore in LLMClient):

- All callers construct `LLMClient(LLMConfig.from_model_config(...))` **without** `max_concurrency=` — the new kwarg's default (`0`) maps to an effectively-unlimited internal semaphore, so the SDK call is never blocked by the new gate. The caller-side `async with caller_semaphore:` continues to be the only effective cap. **No behavior change**.
- Only scoring's `_build_client` is updated to pass `max_concurrency=cfg.max_concurrency`. Inside scoring we additionally **remove** the local `Semaphore` wrap around `client.complete()` because the client now owns it.

Compat checks against D3 (8 retries cap=60s → 2 retries cap=8s) and empty-content-as-transient:

- **Translate (chunked)**: `_parse_and_validate("")` currently returns `parse_failed`, the per-chunk `for _attempt in range(max_retries + 1)` loop hits `[TRANSLATION FAILED]` after two attempts, and the chunk lands in `failures.jsonl`. Under the new client, empty content is intercepted earlier (raised after 2 retries) → the exception propagates through `tqdm.gather` → process crash → wrapper restart → `progress.jsonl` resumes. Net effect: instead of `[TRANSLATION FAILED]` sentinels for empty-content chunks, we get wrapper restarts + a real retry attempt. The translate wrapper's `MAX_RETRIES=20` × `_RETRY_MAX_ATTEMPTS=3` = 60 effective attempts before a chunk is genuinely abandoned; previously the in-client cap was 8 attempts and silent `parse_failed`. **Behavior is strictly tighter** (we no longer silently accept empty translation) and there is no regression for non-empty content.
- **Translate (per-paragraph)**: today `client.complete()` returning `""` would write an empty translation to `progress.jsonl`. Under the new client, that condition raises → wrapper restart → retry. **Strictly tighter**, fixes a silent data-loss bug.
- **Correction**: `tqdm.gather` without `return_exceptions=True` propagates the first exception out of `run_correction`; the caller decides. Identical pattern to translate. Same conclusion: strictly tighter, no regression.
- **Factcheck (standalone CLI)**: error propagation is identical to scoring (per-paragraph try/except removed in today's fix). Compatible.

Retry counts: lowering 8 → 2 means each in-process retry burst is shorter (max wait ~10s instead of ~3 min). For long-running pilots this is desirable: failed paragraphs surface faster, wrapper-level resume kicks in faster, less wallclock burned on slow backoff. The total tolerance is unchanged in practice because wrapper-level `MAX_RETRIES` is the dominant factor.

Verification of compat:

- Run the existing translate + factcheck unit tests after every change (`uv run pytest tests/test_translate_chunked.py tests/test_llm_client.py tests/test_scoring_strategy_factcheck.py`). They should stay green without edits, since they use mocked clients.
- Run the smoke translate (`scripts/02_translate_pilot_resume.sh` on one bucket with `--max-paragraphs 5`, if such an option exists; otherwise skip and re-verify on next real translation pass).

## Non-decisions / out of scope

- Multi-process parallelism (one process per run) — premature at pilot scale.
- Provider-aware token-rate limiting (Anthropic TPM vs OpenRouter): not needed yet.
- Cross-call backoff sharing (one 429 backing off all callers): not worth complexity.
- Reviving the `large-low.yaml` umbrella config: defer.
- Distinguishing transient `-1` from semantic `-1`: collapsed into one (semantic only, transient → raise).
- Per-judge concurrency caps: same MAX_CONCURRENCY for all clients in a run; if user later wants gpt-mini=20 / gpt-5.5=5, that's a future flag.

## Implementation surface

Files touched:

- `src/palimpsest/llm/client.py`
  - Add `max_concurrency: int` kwarg to `LLMClient.__init__`.
  - Create `self._gate = asyncio.Semaphore(...)`.
  - Wrap the SDK call inside `complete()` with `async with self._gate`.
  - Reduce retry attempts 8 → 3 (= 2 retries), cap 60 → 8s.
- `src/palimpsest/scoring.py`
  - Add `SCORE_LLM_FAIL` and `SCORE_SKIPPED` constants at top of the module; replace every literal `-1` / `None` write site with them (D4a).
  - `load_existing_ids`: rewrite docstring to spell out the D4a table.
  - `run_scoring`: replace the flat `asyncio.gather` over all (run × judge + factcheck) tasks with a sequential `for run in cfg.runs: await factcheck; for judge: await judge_task`.
  - `_build_client`: pass `cfg.max_concurrency` through.
  - `_score_run_for_judge`, `_score_factcheck_for_run`: drop local `Semaphore` (client owns it now); replace per-paragraph `asyncio.gather` with `asyncio.as_completed` + `tqdm` (D6).
- `references/interfaces_agreement.md` — new "Scoring JSONL row schema" subsection with the D4a table (per CLAUDE.md routing this is the pipeline contract).
- `data/pilot/evaluation/README.md` — new one-page reader's note: column meanings, `null` vs `-1` semantics, link to the contract.
- `configs/scoring/01-top-vs-baseline.yaml` … `06-reasoning-low.yaml` — single judge `gpt-5.5-low` (D5).
- `configs/scoring/smoke.yaml` — new (D7).
- `scripts/03_scoring_smoke.sh` — new (D7).
- `scripts/03_scoring_exprs.sh` — update comment block (no longer "judges share quota"); raise default `MAX_CONCURRENCY=4` → maybe 10 once smoke validates.
- `tests/test_llm_client.py` — add `test_llm_client_semaphore_caps_inflight`.
- `tests/test_scoring_dispatcher.py` — keep sort-by-id reads (already done); add `test_resume_skips_persisted_ids`.
- `tests/test_scoring_resume.py` — new (D4 verification).

## Verification

1. **Unit — semaphore cap.** Patch `_dispatch_once` to sleep N ms while counting in-flight, fire 50 parallel `complete()` calls, assert max in-flight == `max_concurrency`. Cover `max_concurrency=0` → no cap.
2. **Unit — retry policy.** Patch `_dispatch_once` to raise `RateLimitError` twice then succeed; assert exactly 3 calls. Patch to raise 3 times; assert raises the third exception.
3. **Unit — empty content treated as transient.** Patch to return `""` once then real content; assert 2 calls, returned value is the real content.
4. **Unit — resume (D4).** Mock client returns the paragraph index as a JSON judge response. Run 5 paragraphs, kill after 3 are persisted (set a side-effect that raises on the 4th call). On restart, the mocked client is called only for paragraphs 4-5.
5. **Unit — existing 121 tests stay green.**
6. **Smoke (D7).** Run `scripts/03_scoring_smoke.sh` on a live API key. Inspect output JSONLs:
   - No `score == -1` (or very few — only real LLM hallucinations).
   - 50 rows × 6 criteria × 1 judge = 300 rows in scoring JSONLs; 50 rows in factcheck.
   - tqdm bar reaches 50/50 on each task.
   - `MAX_CONCURRENCY=4` reflected in real network behavior (verify with `httpx` log if needed).
7. **End-to-end P1.** Re-run `scripts/03_scoring_exprs.sh` for one config. Expect:
   - Per-run tqdm bars (factcheck then scoring).
   - No `score=-1` from network errors.
   - Wrapper retry triggered only on true process crash (rare).

## Migration

- Existing `data/pilot/evaluation/01-top-vs-baseline/.../factcheck_scores.jsonl` and the partial gpt-5.5-low/ folder from the 11:48 attempt: keep on disk. After this spec ships, the new run will:
  - Skip the 7 successful paragraphs in gpt-5.5-low (via `load_existing_ids`).
  - Re-evaluate the 542 `score=-1` paragraphs (also via `load_existing_ids` filter).
  - Re-evaluate factcheck `score=-1` paragraphs (~248 out of 549 across the 6 runs).
- The 18 partially-completed judge tasks (opus-low, gemini-pro-low for some runs) — with single-judge configs (D5) they're now out of scope. Their directories stay on disk for archaeological reference; they can be regenerated later by reverting D5 per-config.

## Plan link

Plan goes to `docs/superpowers/plans/2026-05-13-scoring-v2-sequential-runs.md` after this spec is approved.
