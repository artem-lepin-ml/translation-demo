# backend-developer: gemini-everywhere default + migrate() durability fix

## Scope

Worktree: `/Users/a1111/Projects/Work/worktrees/emnlp-demo-sprint` (branch `feat/emnlp-demo-sprint`).

Task: a live code review found a CRITICAL durability bug — `migrate.py` (which
runs on every app startup via `app.py`'s lifespan, and in the deploy script)
had two over-broad remap predicates that silently reverted an operator's
deliberate, still-valid model choice back to `DEFAULT_CRITERION_MODEL` on
every container restart/redeploy. Fix the predicates so only genuinely
retired (off-`MATRIX`) models get remapped, and switch the demo's default
model to `google/gemini-3.1-flash-lite` for every role (translator, all 3
judge criteria, refiner; grounding was already effectively on gemini) for
demo speed, making that choice durable across restarts. Changes staged, not
committed — the orchestrator finalizes the commit.

## Files changed

- `src/palimpsest/webapp/migrate.py`
  - `_upsert_model_registry_and_remap`: criterion remap predicate
    `WHERE model_name IS NULL OR model_name != DEFAULT_CRITERION_MODEL` →
    `WHERE model_name IS NULL OR model_name NOT IN (<current MATRIX names>)`.
  - `_remap_singleton_config_model_refs`: config remap predicate
    `WHERE id=1 AND model_name IS NOT NULL AND model_name != DEFAULT` →
    `WHERE id=1 AND model_name IS NOT NULL AND model_name NOT IN (<current MATRIX names>)`.
  - `REFINER_DEFAULT_PARAMS`: `{"max_tokens": 2048, "temperature": 0.2}` →
    `{"max_tokens": 4096, "temperature": 0.2}`.
- `src/palimpsest/webapp/model_matrix.py` — `DEFAULT_CRITERION_MODEL`:
  `"qwen/qwen3.6-27b"` → `"google/gemini-3.1-flash-lite"`. `qwen/qwen3.6-27b`
  stays in `MATRIX` as a non-default, still-available registry entry.
- `src/palimpsest/webapp/seed.py` — `_seed_refiner_config`: params
  `{"max_tokens": 2048, ...}` → `{"max_tokens": 4096, "temperature": 0.2}`.
- `docs/known_issues.md` — two new entries: `RESOLVED 2026-07-16` durability
  bug writeup (before/after predicate, root cause, fix, test pointers), and a
  gotcha note on qwen-as-refiner empty-output/timeout (forced reasoning)
  explaining why the demo moved to gemini.
- `docs/superpowers/specs/2026-06-30-demo-contracts.md` — added a dated delta
  paragraph after the existing "qwen is the new default" prose in the Model
  registry section, documenting the second move to gemini and the durability
  fix; did not rewrite the older prose (see Open questions / NOT done).
- `tests/test_model_registry_v2.py` — added
  `test_operator_set_current_matrix_criterion_model_survives_migrate` and
  `test_operator_set_current_matrix_model_survives_migrate` — the durability
  regression coverage the task explicitly required ("an operator-set
  current-MATRIX model survives migrate()").
- `tests/test_refiner.py` — `test_get_refiner_config_returns_seeded_default`:
  expected params `{"max_tokens": 2048, ...}` → `{"max_tokens": 4096, ...}`
  (legitimate change — refiner default changed by this task).
- `tests/test_http_routing.py` —
  `test_delete_referenced_model_returns_409_not_404`: now deletes
  `google/gemini-3.1-flash-lite` instead of the hardcoded
  `qwen/qwen3.6-27b` (qwen is no longer referenced by any seeded
  criterion/config after the default switch, so deleting it now legitimately
  returns 204, not 409 — that case is already covered by
  `test_delete_unused_model_slashed_name_routes`, left unchanged since
  `google/gemma-3-27b-it` still fits it).

## Decisions & rationale

- **Predicate shape mirrors `_prune_obsolete_model_rows`**, per the review's
  explicit recommendation: `NOT IN (<MATRIX names>)` rather than
  `!= DEFAULT_CRITERION_MODEL`. This is the minimal fix that satisfies both
  invariants at once — "revert a retired model" and "never touch a current,
  valid operator choice" — without introducing a new state column or a
  separate "operator override" flag (no speculative abstraction; the current
  MATRIX membership is already the exact boundary the bug needed).
- **Criterion NULL case kept as "use default"** — unchanged semantics, only
  the non-null branch's test tightened. A criterion that was never configured
  still bootstraps onto the default, matching the existing
  `test_create_translator_config_skips_seed_when_model_absent`-style
  FK-safety philosophy elsewhere in this file.
- **Gemini default via the single `DEFAULT_CRITERION_MODEL` constant**,
  not a hardcoded literal in `seed.py`'s refiner seeding — translator,
  grounding, and refiner configs all already read `DEFAULT_CRITERION_MODEL`/
  `MODEL_NAME` (itself `= DEFAULT_CRITERION_MODEL`), so changing the one
  constant propagated gemini everywhere for free, keeping single source of
  truth intact per repo convention.
- **Refiner `max_tokens` 2048→4096** applied in both `migrate.py` (prod
  migration path) and `seed.py` (fresh-seed path) identically, since the two
  are meant to produce schema/data-shape-equivalent results per this repo's
  own `test_migrated_schema_equivalent_to_fresh_seed`-style invariant.
- **Did not add a hardcoded gemini literal for refiner model_name** beyond
  what `DEFAULT_CRITERION_MODEL` already provides — the task's own item 5
  text is satisfied by the constant change, and duplicating the literal would
  violate single-source-of-truth for no benefit.
- **Contracts-spec edit was additive, not a rewrite** of the existing 5-row/
  qwen-default prose — that section already had unrelated pre-existing drift
  (references a 5-row MATRIX including the already-dropped TranslateGemma-27B
  placeholder), which predates this task and is out of scope to fix here. A
  dated delta paragraph was appended instead, consistent with this doc's own
  established convention of stacked dated deltas rather than editing history
  in place.
- **`test_delete_referenced_model_returns_409_not_404` expectation change**
  is not a weakening — it still asserts the exact same invariant (a
  referenced model 409s under the slashed-name route), just pointed at the
  model that is now actually referenced (gemini) instead of the one that no
  longer is (qwen).

## Open questions

- None requiring owner input for this task's scope — the fix and default
  switch were fully specified by the task.

## NOT done

- **Did not fix the pre-existing 5-row-MATRIX / TranslateGemma-27B stale
  prose** in `docs/superpowers/specs/2026-06-30-demo-contracts.md` §"Model
  registry: 8 → 5 (paper models)" — that drift predates this task (the
  registry is actually 4 rows, TranslateGemma-27B was dropped 2026-07-11) and
  is unrelated to the durability bug or the gemini-default switch; flagged in
  the new delta paragraph, not fixed, to keep this change minimal and
  on-scope.
- **Did not run frontend tests** — this task is backend/Python-only per its
  own scope; the worktree also has unrelated, already-staged frontend
  changes from other in-flight work that were left untouched.
- **Did not commit** — all 8 touched files are `git add`-staged; the
  orchestrator finalizes the commit per the task's explicit instruction.
- **Did not touch `google/gemini-3.1-flash-lite`'s `supports_temperature`
  flag or other capability metadata** in `model_matrix.py` — out of scope;
  only `DEFAULT_CRITERION_MODEL` and the refiner/model-registry remap logic
  were changed, per the task.

## Test runs (ran, not simulated)

Targeted suite (exactly as specified in the task):

```
$ uv run python -m pytest tests/test_migrate.py tests/test_model_params.py tests/test_model_registry_v2.py tests/test_refiner.py tests/test_seed_registry.py -q
...................................................................      [100%]
67 passed in 1.98s
```

Full suite (extra verification beyond the task's explicit ask, to catch
collateral damage from the global default-model change):

```
$ uv run python -m pytest tests/ -q
564 passed in 4.97s
```

(First full-suite run surfaced 1 failure —
`test_http_routing.py::test_delete_referenced_model_returns_409_not_404`,
hardcoded qwen — fixed as described above; re-run above is green.)
