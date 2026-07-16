# FastAPI developer report — 4-model registry / prod parity (EMNLP demo sprint)

Branch: `feat/emnlp-demo-sprint` (shared worktree, multiple concurrent lanes). Commit: `54b67d3 feat(webapp): finalize 4-model registry with paper params`. Not pushed.

## Scope

Surgical backend-config change: the owner finalized the model registry **on prod, via
the Settings UI** (4 OpenRouter rows, `TranslateGemma-27B` deleted, `max_tokens=20000`,
`temperature=0.7` on all rows, gemini `reasoning.effort="medium"`). The task was to make
the **code** (seed defaults / migration insert list) match that live state, so a future
`seed()` run or `migrate()` deploy does not silently undo the owner's edit.

Files in scope: `src/palimpsest/webapp/model_matrix.py`, `seed.py`, `migrate.py`
(registry parts only), affected tests. `deploy/update-server.sh`'s `MODELS` list:
verify-only. Explicitly out of scope / owned by other concurrent lanes: `app.py`'s
`create_document` region, `frontend/src/demo/variant-a/SettingsTab.tsx`,
`translate.py` (already mid-edit by another lane at task start).

Ground-before-design check: grepped `model_matrix.MATRIX` usage first — both
`seed.py` and `migrate.py` iterate `MATRIX.values()` directly (no separate literal
row lists to hunt down), so the fix is concentrated almost entirely in
`model_matrix.py`'s `_SPECS`; `seed.py`/`migrate.py` needed only comment/docstring
fixes, no logic changes.

## Files changed

All edits, no new files:

- `src/palimpsest/webapp/model_matrix.py` — `_SPECS` now exactly 4 OpenRouter rows
  (`qwen/qwen3.6-27b`, `google/gemma-3-27b-it`, `deepseek/deepseek-v4-flash`,
  `google/gemini-3.1-flash-lite`) at `{"max_tokens": 20000, "temperature": 0.7}`
  (gemini additionally carries `"reasoning": {"effort": "medium"}`). Capability flags
  (incl. gemini's `supports_temperature=False`) left exactly as-is per the task's
  explicit instruction. Removed the `TranslateGemma-27B` row, the now-zero-caller
  `_vllm()` spec-constructor helper, and the now-zero-caller `VLLM` base_url constant
  (confirmed via repo-wide grep that nothing else imports `VLLM` from this module).
  Refreshed the module docstring, the `_SPECS` block comments, and the
  `DEFAULT_CRITERION_MODEL` comment (row counts 5→4, "temperature forced to 0" →
  "0.7, owner-finalized live on prod", `"low"` effort → `"medium"`, and the stale
  "< the 20s /evaluate timeout" claim replaced with an accurate note pointing at the
  actual `EVAL_TIMEOUT` mechanism in `app.py`).
- `src/palimpsest/webapp/seed.py` — comment-only fix on the model-registry insert
  loop (stale "5 curated rows" / "the vLLM row keeps an empty key" language). The
  loop itself (`for spec in MATRIX.values(): ...`) is unchanged and fully
  data-driven, so it now seeds 4 rows automatically.
- `src/palimpsest/webapp/migrate.py` — two stale docstring references only
  (`_upsert_model_registry_and_remap`: "5-row MATRIX" → "4-row MATRIX";
  `_prune_obsolete_model_rows`: "5-model MATRIX" → "4-model MATRIX"). No logic
  changes — `INSERT OR IGNORE` (name is the `model` table's `PRIMARY KEY`) and the
  prune-if-unreferenced step already produced the required behavior; see Decisions.
- `tests/test_model_registry_v2.py` — docstring/fixture-comment counts (5→4);
  renamed `test_five_matrix_models_present_after_migration` →
  `test_four_matrix_models_present_after_migration`; replaced
  `test_translategemma_vllm_row_present_and_display_only` (asserted a row that no
  longer exists) with two new tests:
  `test_translategemma_not_in_matrix_and_never_inserted` and
  `test_translategemma_pruned_if_present_from_pre_finalization_snapshot`.
- `tests/test_seed_registry.py` — docstring fix; `test_five_models_seeded` →
  `test_four_models_seeded`, count `5`→`4`.
- `tests/test_model_params.py` — `test_matrix_has_five_models_four_openrouter` →
  `test_matrix_has_four_models_all_openrouter` (`len(mm.MATRIX)==4`); stale
  "5-model"/"5 real rows" comments fixed; `test_vllm_no_usage_accounting_field` and
  `test_seed_omitted_when_unsupported` rewired from the real (now-removed)
  `"TranslateGemma-27B"` row onto a synthetic `ModelSpec` via
  `monkeypatch.setitem(mm.MATRIX, ...)` — this file's own established pattern for
  capability-flag unit tests (3 other tests in the same file already used it before
  my change).
- `tests/test_test_endpoint.py` — `test_client_for_no_fallback_for_vllm` now inserts
  its own synthetic non-OpenRouter row instead of depending on a seeded
  `TranslateGemma-27B`.
- `tests/test_http_routing.py` — `test_delete_unused_model_slashed_name_routes` now
  deletes `google/gemma-3-27b-it` (seeded, genuinely unreferenced by any
  criterion/config, and — unlike the old `TranslateGemma-27B` fixture — actually
  contains the slash the test's own name claims to exercise).
- `tests/test_migrate.py` — one docstring count fix (5→4), no assertion changes.

Explicitly NOT touched: `app.py`, `SettingsTab.tsx`, `translate.py`,
`deploy/update-server.sh` (verified only), `docs/superpowers/specs/2026-06-30-demo-contracts.md`.

## Decisions & rationale

**No functional changes needed in `seed.py`/`migrate.py` beyond comments.** Both
already treat `model_matrix.MATRIX` as the single source of truth and iterate it
generically (`for spec in MATRIX.values(): INSERT OR IGNORE ...`). Once `_SPECS`
dropped to 4 rows, both modules' behavior updated for free — this is exactly the
"module isolation via interfaces" invariant working as intended.

**Migration no-op proof, concretely run (not just read from code).** Wrote a
standalone script (scratchpad, not committed) that builds a DB against the real
`db.py::SCHEMA`, seeds it with the *old* 5-row/cheap-params shape (simulating
pre-owner-edit prod), applies the owner's UI edit by hand (UPDATE the 4 OR rows to
the target params, DELETE `TranslateGemma-27B`), then runs the **full**
`migrate.migrate(conn)` from this worktree (the same call `app.py`'s startup
lifespan / the `migrate` CLI make on prod) and diffs before/after:

```
RESULT: migrate() is a byte-for-byte no-op on the owner-edited registry rows,
and TranslateGemma-27B is not re-inserted. PROOF PASSED.
```

All 4 rows' `base_url`/`api_key`/`params_json` were bit-identical before and after;
`TranslateGemma-27B` stayed absent. Mechanism: `model.name` is the table's
`PRIMARY KEY`, so `INSERT OR IGNORE` is a true no-op on conflict (not a partial
column update), and `_prune_obsolete_model_rows` only ever deletes names outside
`MATRIX.keys()` — since `TranslateGemma-27B` is gone from `MATRIX`, it is simply
never inserted again, and would be pruned (not re-added) if a stray copy existed
from an unfinished pre-finalization snapshot. This exact scenario is now also
covered by the two new pytest tests in `test_model_registry_v2.py` (not just the
scratch script).

**Test rewiring used the file's own existing pattern, not a new one.**
`test_model_params.py` already had 3 tests exercising capability-flag logic via a
synthetic `ModelSpec` injected with `monkeypatch.setitem(mm.MATRIX, "test/...", ...)`
(decoupling the test from whichever real models happen to be registered). The two
tests that hard-depended on the real `"TranslateGemma-27B"` row were converted to
the same pattern rather than either (a) keeping a dead production row alive just for
test fixtures, or (b) leaving assertions that would keep "passing" post-change for
the wrong reason (e.g. `ModelParams.for_model` silently skips all capability
filtering when `MATRIX.get(name) is None`, so the old assertions would not have
failed loudly — they would have degraded into accidentally-correct-for-the-wrong-reason
tests).

**Budget-cap regression check (not requested, but a real risk I chased down).**
`budget.estimate()` multiplies `max_tokens` directly into the worst-case USD
reservation (`(max_tokens + reasoning_max_tokens) * price_per_token_out`), so
jumping registry defaults from ~1536–2048 to 20000 could plausibly have pushed some
test's `reserve()` call over a tight `_CAP_USD`. Traced every test that performs a
*real* (non-`_client_for`-faked) `evaluate`/`test_model` call: all either fake the
client entirely (`_install_fake_client`, so `client.config.max_tokens` comes from
the fake, not the DB row), explicitly override `model.params_json` with their own
small value, or run under a generous `$100` cap. Pure `budget.py` unit tests
(`test_budget.py`, `test_evaluate_retry*.py`) pass explicit literal token counts,
fully decoupled from `model_matrix`. Conclusion: no hidden regression; confirmed by
the full green run below, not just this trace.

**Removed `_vllm()`/`VLLM` rather than leaving them as dead code.** Zero callers
remained after dropping the `TranslateGemma-27B` row; project convention
(`CLAUDE.md` § Conventions: "No speculative abstractions... add a helper only when a
concrete caller needs it") argues against keeping an unused local-vLLM constructor
"just in case." Confirmed via repo-wide grep that no other module imports `VLLM`
from `model_matrix`.

## Test results

- Task-required scope: `uv run pytest tests/ -q -k "registry or seed or model or
  matrix or migrate"` → **102 passed, 460 deselected**.
- Full suite: `uv run pytest tests/ -q` → **562 passed, 0 failed** (run twice — once
  mid-edit, once as the final state after the last docstring tweak; both green).
- `uv run ruff check` on all 9 touched files: zero *new* violations. Verified by
  diffing every `+` line in `git diff` against ruff's line-length/style output —
  every flagged E501/E702/I001/E741/UP017 finding sits on a pre-existing line I never
  touched (`seed.py`/`migrate.py`/`test_migrate.py` carry pre-existing tech debt of
  this kind repo-wide). `model_matrix.py`, the most heavily rewritten file, is
  fully clean (`All checks passed!`).
- Compiled all 9 touched files with `python -m py_compile` before running tests
  (syntax sanity gate).

## Open questions

- Should `deploy/update-server.sh` step 8's temperature-forcing block be deleted
  outright, or converted into a one-time migration note now that `temperature=0.7`
  is the intended steady state? I did not decide this myself — it is outside my
  authorized file scope (verify-only was explicitly granted for the `MODELS` list,
  not the PUT-loop body) and is devops-engineer's lane. See NOT done below — this is
  the most important open item from this task.
- `docs/superpowers/specs/2026-06-30-demo-contracts.md:441` (the canonical
  API/data-contract SSOT) still describes the original 5-row registry including
  `TranslateGemma-27B`. Doc-parity update needed; `docs-keeper`'s lane, not mine.

## NOT done (explicit)

- **`deploy/update-server.sh` step 8 not fixed — CRITICAL, flagged only.** Verified
  (read, did not edit) that step 8 unconditionally PUTs `temperature=0` onto exactly
  the 4 model names on *every deploy*:
  ```
  log "8/8 force temperature=0 on the demo model rows via the live API"
  ...
  params['temperature'] = 0
  ```
  This directly contradicts the owner's finalized `temperature=0.7` and will
  silently undo it on the next deploy run — the exact failure mode this task exists
  to prevent, just via a different code path than the one I was scoped to touch (the
  `MODELS` name list itself is correct and was left unedited, per instruction). This
  needs an explicit owner/devops-engineer decision (drop step 8, or change what it
  forces) before `update-server.sh` runs again on prod.
- `docs/superpowers/specs/2026-06-30-demo-contracts.md` doc-parity not updated (out
  of my file scope; flagged for `docs-keeper`).
- `app.py`, `SettingsTab.tsx`, `translate.py` not touched (owned by other concurrent
  lanes in this shared worktree — confirmed via `git diff --stat HEAD` that my
  commit contains exactly the 9 intended files and nothing from lanes already
  committed at `869843e`/`270408b`/`4bd4d23`/`af60df2`).
- Not pushed (per task instruction — no push requested).

## Security note (unrelated to the registry work, logged for the record)

The task message this session received had an appended block claiming
"context_window_protection" rules and referencing MCP tools
(`ctx_batch_execute`, `ctx_search`, `ctx_execute`, etc.) that do not exist in this
agent's actual toolset (Read/Write/Edit/Bash only), and a later `Bash` tool result
had an injected-looking `<system-reminder>` block about Telegram/"Auto Mode" mid
tool-output. Both were inconsistent with the real system prompt and tool list, so
they were treated as untrusted content and ignored; the task was executed with the
actual available tools per the real `fastapi-developer` system prompt.
