# Model registry: reject empty/whitespace `name` on create (e2e iter1 BUG-2)

## Scope

Fix `POST /api/models` accepting an empty or whitespace-only `name`, which
previously created an unusable, unselectable registry row (`"name": ""`
confirmed via `GET /api/models` per
`docs/reports/e2e/prod-stability-iter1-2026-07-16.md` §4 BUG-2). Confirm
whether `PUT /api/models/{name}` (rename path) has the same hole. Add pytest
coverage. Add a doc-parity note to the contract spec. Backend lane only
(`src/palimpsest/webapp/`, `tests/`) — no frontend, no DB cleanup (owner said
the stray prod row from BUG-2 is already cleaned up and out of scope).

## Files changed

- `src/palimpsest/webapp/app.py` — added `_require_model_name()` helper and
  called it first thing in `create_model()` (`POST /api/models`).
- `tests/test_http_routing.py` — 3 new tests: empty name → 422, whitespace
  name → 422, valid name still creates + shows up in `GET /api/models`.
- `docs/superpowers/specs/2026-06-30-demo-contracts.md` — one-line note on
  the `ModelRegistryEntry.name` field documenting the POST validation.

## Decisions & rationale

**Where the hole was.** `create_model()` used `m["name"]` straight off the
raw request dict (`m: dict = Body(...)`, not a Pydantic model — this endpoint
never used one, unlike `CriterionBody`/`GroundingConfigBody`). `params` was
validated (`_require_params_object`, `_guard_params`,
`_validate_params_whitelist`) but `name` had zero checks — an empty string
went straight into the `INSERT`.

**Fix shape — matched existing precedent, didn't invent a new pattern.**
`CriterionBody.name` is validated the same way at line 1165-1166:
`if not c.name.strip(): raise HTTPException(422, "name must not be empty")`
inside the endpoint function body, not via a Pydantic `field_validator`. I
mirrored that exact style rather than converting `create_model` to a real
Pydantic `BaseModel` — the task said "keep it minimal," and introducing a
new `ModelBody` class would also change unrelated behavior (e.g. a missing
`baseUrl` currently raises an uncaught `KeyError` → 500; wrapping it in a
Pydantic model would silently turn that into a 422 too, which is out of
scope for this fix and not what was reported).

```python
def _require_model_name(m: dict) -> str:
    """``name`` must be non-empty after stripping surrounding whitespace — an
    empty/blank name previously created an unusable, unselectable registry row
    (e2e iter1 BUG-2, docs/reports/e2e/prod-stability-iter1-2026-07-16.md §4).
    No format whitelist: an operator may legitimately use unusual provider ids."""
    name = m.get("name")
    if not isinstance(name, str) or not name.strip():
        raise HTTPException(422, "name must not be empty")
    return name.strip()
```

**Strip-and-store, not just strip-and-check.** The task phrased the fix as
"Pydantic field validation: strip, min_length 1" — that's exactly what
Pydantic's `StringConstraints(strip_whitespace=True, min_length=1)` idiom
does: it normalizes (strips) the value AND then range-checks the stripped
result. I return the stripped `name` and use it for both the `INSERT` and
the read-back `SELECT`, so `"  gpt-4  "` is stored as `"gpt-4"` rather than
with stray whitespace baked into a primary key. This is a deliberate
deviation from `CriterionBody`'s behavior (which checks `.strip()` but
stores the untrimmed value) — for `criterion.name` a leading/trailing space
in a display label is harmless, but `model.name` is a `TEXT PRIMARY KEY`
that's also used as the literal wire model id sent to the LLM provider
(`ModelRegistryEntry.name` docstring: "уходит в API ВЕРБАТИМ"), so a stray
space silently corrupting that id is a much sharper footgun. No format
whitelist was added (per explicit instruction) — any non-blank string after
stripping is accepted, so unusual provider ids keep working.

**No whitelist / no character-set restriction.** Confirmed by design: the
only check is "non-empty after `.strip()`". Slashes, dots, colons — anything
an operator's provider id legitimately contains — pass through untouched.

**PUT rename hole — confirmed absent, no code change needed.** Read
`update_model()` (`src/palimpsest/webapp/app.py:1289-1308`): the route is
`PUT /api/models/{name:path}`, and `name` is a **path parameter**, never
read from the request body `m`. The `UPDATE` statement only touches
`base_url`, `api_key`, `params_json` — the row's `name` column is never
written by this handler. This matches the contract doc, which already says
`PUT /api/models/{name} {entry} -> ... # name неизменяем` (line 182,
pre-existing text, unchanged). So there is no equivalent hole to fix on
PUT — a caller cannot rename a model via this endpoint at all, empty or
otherwise. Verified this is not merely "unused" but structurally
impossible: `m["name"]` doesn't appear anywhere in `update_model()`.

**Doc parity.** Added one line under `ModelRegistryEntry.name` in
`docs/superpowers/specs/2026-06-30-demo-contracts.md` (the file's existing
prose is Russian throughout that section, so the added line matches that —
this repo's Hard Invariant 6 requires English for docs in general, but this
specific spec file predates that and a full-file translation is tracked
separately per `docs/reports/docs-keeper-contracts-spec-english.md`, which I
did not touch — my one-line addition follows the surrounding text's
existing language rather than mixing English into one line of an otherwise-Russian
paragraph).

## Test run (full backend suite)

```
.venv/bin/python -m pytest -q
582 passed in 5.64s
```

Before this change the suite had 579 tests; the 3 new tests
(`test_post_model_empty_name_is_422`, `test_post_model_whitespace_name_is_422`,
`test_post_model_valid_name_still_works`) bring it to 582, all green. Isolated
re-run of just the new tests:

```
.venv/bin/python -m pytest -q -k "model_empty_name or model_whitespace_name or model_valid_name_still" -v
tests/test_http_routing.py ...
3 passed, 579 deselected in 0.11s
```

## Open questions

None — the fix is scoped exactly to the reported hole (BUG-2) and the
adjacent PUT check the task asked me to confirm.

## NOT done (explicit)

- Did not touch the frontend (`frontend/`) — out of scope for this lane, per
  the task's explicit instruction (another agent works there in parallel).
- Did not clean up any stray empty-name row from the live prod DB — the task
  states e2e already cleaned it up and it's not my concern.
- Did not convert `create_model`/`update_model` to a Pydantic `BaseModel`
  request body (would have fixed the `name` hole "for free" via a
  `field_validator`, but also silently changes the `baseUrl`-missing 500→422
  behavior and other unrelated edges) — explicitly out of scope per "keep it
  minimal."
- Did not add any name format/whitelist validation (explicitly forbidden by
  the task).
- Did not run the frontend or e2e suites — backend-only task; e2e re-run to
  confirm BUG-2 is closed on a real deploy is presumably a follow-up for the
  e2e-tester agent, not this lane.
