# DeepSeek-V4-Flash temperature paper-parity fix

## Scope

Paper §3.3 Implementation Details states: "DeepSeek-V4-Flash uses its
vendor-recommended temperature of 1.0, and all other models use temperature
0.7." The demo's model registry (`model_matrix.py::MATRIX`, read by
`migrate.py::_pin_demo_model_temperature` as the single source of truth) had
all 4 rows pinned to 0.7, including deepseek. Task: fix the deepseek row's
`default_params.temperature` to 1.0, update the surrounding docstrings/comments
that claimed "0.7 on all 4 rows", check test expectations, and check
`deploy/update-server.sh` / the contracts spec for stale "all-four-0.7"
wording.

## Files changed

- [src/palimpsest/webapp/model_matrix.py](../../src/palimpsest/webapp/model_matrix.py)
  - `deepseek/deepseek-v4-flash` row: `default_params["temperature"]` `0.7` → `1.0`, inline comment updated.
  - Module docstring (lines ~9-15): added the deepseek exception with the paper §3.3 citation.
  - `_SPECS` block comment (lines ~52-58): same exception noted next to the "0.7 on all 4 rows" claim.
- [src/palimpsest/webapp/migrate.py](../../src/palimpsest/webapp/migrate.py)
  - `_pin_demo_model_temperature` docstring: "currently 0.7 on all 4 rows" → "0.7 on 3 of the 4 rows ... except deepseek ... pinned to 1.0", with the paper citation. No code change — the function already reads `spec.default_params.get("temperature")` from `MATRIX` per-row, so it picks up the new value with zero logic changes (this was the point of routing the fix through `MATRIX` as SSOT, per the task instructions — confirmed correct by reading the function body first).
- [docs/subsystems/webapp.md](../../docs/subsystems/webapp.md) (line ~220)
  - Was: "pins `temperature: 0.7` on the demo model rows" (a flatly false claim once deepseek diverges). Updated to: "pins each model's own MATRIX temperature on the demo model rows (... `temperature: 0.7` on 3 of the 4 rows, `1.0` on `deepseek/deepseek-v4-flash` per the published paper's vendor-recommended-temperature note)". Not explicitly named in the task's checklist, but it makes the same kind of stale wire-level claim the task flagged in the other two files — fixed under Hard Invariant 2 (doc-parity in the same commit).

## Decisions & rationale

- **No change to `deploy/update-server.sh`.** Its one "temperature=0.7" mention (line 34) is a past-tense historical note ("this script used to end with two more steps ... pinning temperature=0.7 on the demo model rows") describing what the *retired* post-serving step used to do, back when it really was uniform 0.7 for all 4 rows. That's accurate history, not a current claim, and the task's own step-5 log lines (lines 99-100) don't mention "0.7" at all — nothing to fix there.
- **No change to `docs/superpowers/specs/2026-06-30-demo-contracts.md`.** Grepped for `0.7`/`temperature`/`deepseek` — the only temperature values quoted are for the translator (0.3) and grounding (0) default params in unrelated sections; no "all models use 0.7" claim exists in this file to begin with.
- **No test file needed a literal-value update.** Checked `tests/test_model_registry_v2.py`, `test_model_params.py`, `test_migrate.py`, `test_llm_result.py` for hardcoded `0.7`/`deepseek` assertions. The only registry-temperature assertion (`test_owner_edited_api_key_not_clobbered_on_second_run`, line 178) compares against `MATRIX[DEFAULT_CRITERION_MODEL].default_params["temperature"]` dynamically — and `DEFAULT_CRITERION_MODEL` is `google/gemini-3.1-flash-lite` (still 0.7), not deepseek, so it was already correct and needed no edit. No test anywhere references the string `"deepseek"`. `test_llm_result.py`'s `temperature == 0.7` assertion is an unrelated unit test against an arbitrary `LLMConfig` fixture, not tied to `MATRIX`.
- **seed.py** iterates `MATRIX.values()` directly (`json.dumps(spec.default_params)`) — confirmed no independent hardcoded copy of the temperature values exists there either.

## Open questions

None — the fix is a single-value change behind an already-correct single source of truth; no design ambiguity.

## NOT done (explicit)

- Did not touch `frontend/src/demo/variant-a/glossary-grouping.ts`, which shows as a diff in `git status`/`git diff` in this worktree — that change pre-existed before this task started (a parallel frontend-lane edit already in the worktree, out of my backend-only lane) and was not created or modified by this task.
- Did not run any live OpenRouter call against deepseek to re-confirm the provider actually accepts `temperature=1.0` for `deepseek/deepseek-v4-flash` — out of scope for a paper-parity value fix, and the row's `supports_temperature=True` flag (cross-checked against a live `/models` fetch on 2026-07-11 per the module docstring) was not re-verified live in this task.
- Did not git commit/push, per instructions.

## Test run

```
.venv/bin/python -m pytest -q
635 passed in 5.88s
```
