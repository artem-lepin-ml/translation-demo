# Terminology robustness fixes: per-mention isolation + trace field rename

Scope: `src/palimpsest/terminology/` only (per task boundary — `src/palimpsest/webapp/` and `frontend/` were not touched).

## Issue 1 — one non-retryable Wikidata error dropped the whole paragraph

### Root cause

Three layers stacked to produce full-paragraph data loss from a single bad lookup:

1. `wikidata.py::WikidataClient._fetch` (unchanged, confirmed correct — line refs below) re-raises a **bare** `urllib.error.HTTPError` in two cases: a deterministic non-retryable 4xx, and a retryable 429/5xx whose 5 attempts are exhausted (`wikidata.py:111-117`, specifically the `raise` at what is now line ~117 inside the `except urllib.error.HTTPError` branch). Every other failure path in `_fetch` is normalized to `RuntimeError`.
2. `grounding/label_first.py`'s `LabelFirstGrounding.ground()` wrapped its call to `generate_candidates()` in `except RuntimeError` only (was `label_first.py:101-108`, function moved under `terminology/grounding/` — task description's flat `terminology/label_first.py` path predates the `grounding/` subpackage split; line numbers matched exactly once resolved to the real path `src/palimpsest/terminology/grounding/label_first.py`). A bare `HTTPError` from step 1 was therefore never caught here and propagated out of `ground()`.
3. `pipeline.py::run()` iterated `mentions` with no per-mention `try/except` (`pipeline.py:23-24`, now `pipeline.py:46-48` after the fix), so the uncaught exception from step 2 killed the entire `for m in mentions` loop — every other mention in the same paragraph, including ones that would have grounded fine, was lost with it.

### Fix

- [src/palimpsest/terminology/pipeline.py](../../src/palimpsest/terminology/pipeline.py) — `run()`'s mention loop now wraps `grounder.ground(...)` in `try/except`: any exception is logged at `logging.warning` (mention surface + exception type/message, no secrets — Wikidata calls carry no API key) and that mention is skipped (`continue`), the rest of the paragraph proceeds. `FatalGroundingJudgeError` is explicitly re-raised, not isolated — it is documented in `grounding/label_first.py`'s own docstring as a halt marker (token-limit overflow, per-call gate violations) that must stop the run, and the pipeline layer must not accidentally swallow it. Added `import logging` + `logger = logging.getLogger(__name__)`, imported `FatalGroundingJudgeError` from `.base`.
- [src/palimpsest/terminology/grounding/label_first.py](../../src/palimpsest/terminology/grounding/label_first.py) — the candidate-gen catch (`ground()`, around line 111) is broadened from `except RuntimeError` to `except (RuntimeError, urllib.error.HTTPError, OSError)`, still resolving to `red`/`wikidata_unavailable` (never `no_candidates` — a network failure must not masquerade as an honest miss, per the existing docstring policy). Added `import urllib.error`. **Existing retry logic in `wikidata.py::_fetch` was not touched** — retryable 429/5xx errors are still retried exactly as before; only the catch that wraps the retry-exhausted/non-retryable escape hatch was widened.
- Docstring updates in both files explain the two-layer defense: the strategy degrades gracefully first (`label_first.py`), the pipeline loop is a second, defense-in-depth layer for anything a strategy still lets escape (`pipeline.py`).
- [docs/stages/terminology.md](../stages/terminology.md) — added a `Subtleties` bullet documenting the per-mention isolation and the broadened catch (doc-parity, same commit).

### Why `OSError` too, even though it currently never escapes `_fetch` bare

Traced `_fetch`'s three `except` branches: `HTTPError` (bare re-raise on non-retryable/exhausted), `(JSONDecodeError, OSError)` (always wrapped to `RuntimeError` on exhaustion, retried otherwise), and the maxlag/other-API-error branch (always `RuntimeError`). So today only `HTTPError` and `RuntimeError` can escape `_fetch`. Per the task's explicit instruction and `HTTPError` being an `OSError` subclass anyway, `OSError` was added as an explicit, low-risk defense-in-depth term at the `label_first.py` catch site (covers e.g. a `resp.read()` failure inside the `try` block, or a future `WikidataClient`-alike that doesn't normalize as strictly) — it does not change behavior for any exception `_fetch` produces today.

## Issue 2 — trace wrote the deprecated `use_fallbacks` field

### Consumer grep (done before renaming, per task instruction)

```
grep -rn "use_fallbacks" src/ frontend/ docs/   # frontend/src/demo/variant-a: 0 hits
grep -rln "trace" frontend/src/demo/variant-a/  # GlossaryTab.tsx, glossary-grouping.ts
grep -n "trace\." frontend/.../GlossaryTab.tsx frontend/.../glossary-grouping.ts
  → only trace.resolved_by is read; trace.config is never touched
grep -n "use_lemma|use_fallbacks|\"config\"" docs/superpowers/specs/2026-06-30-demo-contracts.md
  → 0 hits (the contracts spec — SSOT for wire DTOs — doesn't pin trace.config's shape)
```

`base.py`'s own `GroundingConfig` docstring (2026-07-06 deprecation note) and `docs/stages/terminology.md` already document `use_cirrus`/`use_sitelink` as the current fields, with `use_fallbacks` as a **constructor-only** compat alias — no doc claims the trace still emits `use_fallbacks`. No consumer reads `trace.config.use_fallbacks`. **Conclusion: straight rename, no backward-compat shim needed** (per the task's own conditional instruction).

### Fix

[src/palimpsest/terminology/grounding/label_first.py](../../src/palimpsest/terminology/grounding/label_first.py):`_result()` (was lines 296-298) now writes `"config": {"use_lemma": ..., "use_cirrus": ..., "use_sitelink": ..., "match_aliases": ...}` instead of `"use_fallbacks"`, with a comment recording the grep result so a future reader doesn't have to redo it.

## Tests

Added to [tests/test_terminology.py](../../tests/test_terminology.py) (existing file — found via `find tests -iname "*terminology*"`):

- `test_pipeline_isolates_mention_whose_grounder_raises_and_keeps_the_rest` — fake grounder raises `RuntimeError` for one mention; asserts the loop continued (both mentions' `.ground()` called) and only the bad one is dropped from the returned `terms`.
- `test_pipeline_logs_skipped_mention_at_warning_level_no_secrets` — `caplog` at `WARNING` on `palimpsest.terminology.pipeline`, asserts the mention surface appears in the log and no other level is used.
- `test_pipeline_does_not_swallow_fatal_grounding_judge_error` — fake grounder raises `FatalGroundingJudgeError`; asserts it propagates out of `pipeline.run()` (`pytest.raises`) and the loop halted (second mention never reached).
- `test_label_first_http_error_resolves_wikidata_unavailable_not_crash` / `test_label_first_os_error_resolves_wikidata_unavailable_not_crash` — fake `WikidataClient` whose `search_entities` raises a real `urllib.error.HTTPError(503)` / `ConnectionResetError`; asserts `LabelFirstGrounding.ground()` itself degrades to `red`/`wikidata_unavailable` rather than raising.
- `test_pipeline_survives_one_mention_wikidata_http_error_mid_paragraph` — **the exact scenario requested**: real `LabelFirstGrounding` + `pipeline.run()` over two mentions, one of whose Wikidata lookup raises `HTTPError(500)` mid-paragraph, the other resolves normally. Asserts both `Term`s come back (`["Навуходоносор", "Саргон"]`), the failing one is `red`/`wikidata_unavailable`, the other is `green` — this is the full-stack regression test for the bug as originally reported (0 terms back before the fix).
- `test_label_first_trace_config_writes_split_fields_not_deprecated_use_fallbacks` — asserts `trace["config"]` has `use_cirrus`/`use_sitelink` and no `use_fallbacks` key.

7 new tests, 92 → 99 in `test_terminology.py`.

## Test evidence

**Ran** (both commands, exact output):

```
$ ./.venv/bin/python -m pytest tests/test_terminology.py tests/test_terminology_live.py \
      tests/test_wikidata_client.py tests/test_demo_terminology_seed.py -q
........................................................................ [ 57%]
......................................................                   [100%]
126 passed in 1.02s
```

```
$ ./.venv/bin/python -m pytest -q      # full backend suite
........................................................................ [ 12%]
........................................................................ [ 25%]
........................................................................ [ 37%]
........................................................................ [ 50%]
........................................................................ [ 63%]
........................................................................ [ 75%]
........................................................................ [ 88%]
...................................................................      [100%]
571 passed in 5.06s
```

Baseline (before this change, via `git stash`): `tests/test_terminology.py` alone was `92 passed`. After: `99 passed` (this file) / `126 passed` (terminology subset) / `571 passed` (full suite), 0 failures either run.

**Lint**: `ruff check --select I --fix` was run against the two changed source files only (`pipeline.py`, `grounding/label_first.py`) to fix an import-order issue my own new `import logging`/`import urllib.error` lines introduced; it reformatted the long `from ..base import (...)`/`from .base import (...)` lines into multi-line form, no behavior change (tests re-ran green after). `tests/test_terminology.py` and the rest of `terminology/` carry substantial **pre-existing** ruff debt (mostly `E501` line-too-long, some `E402` inline mid-file imports that are this test file's established convention — see its own `# ── grounding candidate generation ──` section headers before each inline import block) predating this task; per repo convention ("a bug fix doesn't need surrounding cleanup") this was left alone and is not attributable to this change.

**Not run**: no live/paid LLM or real-network Wikidata calls (explicitly out of scope per task instructions — "Do not make paid LLM calls"; all tests use fake `WikidataClient`/`Judge` stand-ins already established in the test file, e.g. `_FakeWD`, `_RaisingWD`, `_judge_counter`).

## Files changed

- `src/palimpsest/terminology/pipeline.py` — per-mention isolation (Issue 1).
- `src/palimpsest/terminology/grounding/label_first.py` — broadened catch (Issue 1) + trace field rename (Issue 2).
- `tests/test_terminology.py` — 7 new tests.
- `docs/stages/terminology.md` — doc-parity bullet for the isolation behavior.

## Open questions / not done

- None outstanding for the two issues as scoped. `wikidata.py` itself was deliberately left untouched — the task explicitly said to keep its retry logic intact, and the root-cause trace above confirms it already normalizes almost everything to `RuntimeError`; the residual bare `HTTPError` escape is exactly what `label_first.py`'s broadened catch now handles.
- Did not touch `pairer.pair()` calls in `pipeline.run()` — the reported issue and the task's fix instructions are scoped to the *grounding* lookup path only; pairing strategies (`link_locate.py`, `llm_judge.py`, `neural_align.py`) were out of scope and their own error-handling conventions were not audited here.
