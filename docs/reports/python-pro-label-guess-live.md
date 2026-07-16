# Python-pro report — enable the label-guess tier in the live terminology pipeline

## Scope

Enable the existing "label-guess" query-expansion mechanism (candidates.py's
`search_mode="label-guess"`) in the LIVE demo pipeline (`webapp/terminology_live.py`),
owner-approved 2026-07-17. Before this change, the live pipeline always ran plain
`GroundingConfig()` defaults (`search_mode="baseline"`), so a mention whose
lemma/surface found 0 candidates through the deterministic tiers (prefix search,
CirrusSearch, sitelink) died as `no_candidates`/red without ever consulting an LLM
label guess — including the paper's own Figure 1 example, «Ханейское царство»
(canonical Wikidata label «Хана» / "Kingdom of Hana", Q425405).

File lane (per dispatch): `src/palimpsest/terminology/**`,
`src/palimpsest/webapp/terminology_live.py`, tests, `docs/stages/terminology.md`.
`migrate.py`, `model_matrix.py`, `frontend/` explicitly out of scope (other agents
working there concurrently — confirmed via `git status` before and after: their
files show unstaged edits I never touched). `app.py` also not in my lane (not
explicitly listed as "my files") — see Decisions below for how that shaped the
design.

## Files changed

- `src/palimpsest/terminology/grounding/candidates.py` — module docstring +
  `_widen()`'s query-building: the label-guess tier's widened queries now carry
  `"strategy": "guess"` (new value) instead of `"prefix"`, so a trace UI can tell
  an LLM-guessed query apart from an ordinary widening call at a glance. `"alt"`
  (alt-names tier) is unchanged (`"strategy": "prefix"`). No other candidate-gen
  logic touched — the label-guess tier's escalation order/semantics (fires only
  after ALL deterministic tiers AND alt-names widening find 0 candidates) were
  already correct and are unchanged.
- `src/palimpsest/webapp/terminology_live.py`:
  - New import: `DEFAULT_LABEL_GUESS_SYSTEM_PROMPT` from
    `terminology.grounding.candidates`.
  - New constants `_LABEL_GUESS_TIMEOUT`/`_LABEL_GUESS_RETRIES`/`_LABEL_GUESS_BACKOFF`
    (env-overridable, same shape/defaults as the existing `_NER_*` constants).
  - `_effective_ner_timeout` generalized into `_effective_call_timeout(client, floor)`
    (shared helper) + a thin `_effective_ner_timeout` wrapper kept for the existing
    test that asserts against it directly (`test_ner_timeout_exceeds_sdk_client_timeout`).
  - New `_grounding_label_guess_live(conn, client_for, prompt, endpoint="label_guess")`
    (async): budget-guarded label-guess call, mirrors `app._grounding_judge_live`'s
    reserve/settle/retry/timeout shape but self-contained in this module (see
    Decisions below for why it isn't a reuse of that function).
  - New `_make_sync_label_guesser(conn, client_for, loop)`: bridges the sync
    `Judge`-shaped `label_guesser` callable `generate_candidates()` expects to the
    async function above, via the same `run_coroutine_threadsafe` pattern
    `_make_sync_judge` already uses for the disambiguation judge.
  - `_run()`: now builds `sync_guesser` and constructs
    `LabelFirstGrounding(wd, config=GroundingConfig(search_mode="label-guess"),
    label_guesser=sync_guesser)` instead of plain `GroundingConfig()`.
  - Module docstring + inline comments updated to describe the new tier, its
    cost bound, and the budget endpoint tag.
- `tests/test_terminology_live.py` — 4 new tests (mocked WikidataClient +
  mocked LLM client, no network, no paid calls):
  1. `test_run_label_guess_tier_resolves_no_candidates_mention` — the
     Ханейское-shape case: all deterministic tiers find 0 hits, the guesser
     returns "Хана", search finds the candidate via the guessed label, the term
     resolves (via disambiguation-judge escalation, since the guessed label
     doesn't lexically match the surface) instead of dying `no_candidates`.
     Asserts the trace carries a `kind="label_guess"` query with
     `strategy="guess"`, and `chosen_qid` is set.
  2. `test_run_label_guesser_not_called_when_normal_tiers_find_candidates` — a
     mention resolved at rung 1 never reaches the guesser (asserted via the
     fake LLM client's call count staying at 1 — NER only).
  3. `test_run_builds_and_passes_label_guesser_into_grounder` — unit-level
     wiring check: `_run` constructs `LabelFirstGrounding` with
     `search_mode="label-guess"` and a callable `label_guesser`.
  4. `test_label_guess_call_logged_under_distinct_budget_endpoint` — the
     label-guess LLM call is logged via `budget.log_call` with
     `endpoint="label_guess"`, coexisting with the NER call's own
     `"terms_extract"` tag.
- `docs/stages/terminology.md` — doc-parity:
  - § Design decisions: updated the `strategy` field description to include the
    new `"guess"` value.
  - § Live trigger: new paragraph describing the label-guess tier now running
    live, the reference case, the cost bound ("at most one extra short LLM call
    per mention, only for mentions already headed for `no_candidates`/red — can
    only improve recall, never regress an already-groundable mention"), and an
    explicit flag for the one doc still needing a delta outside this task's
    lane (see NOT done below).

## Decisions & rationale

1. **A new `_grounding_label_guess_live` in `terminology_live.py`, not a reuse
   of `app._grounding_judge_live`.** `app.py` is outside my authorized file
   lane for this task (only `terminology/**` and `webapp/terminology_live.py`
   were listed). `_grounding_judge_live` also hardcodes
   `DEFAULT_GROUNDING_JUDGE_SYSTEM_PROMPT` as its system message — the
   label-guess tier needs a genuinely different system prompt
   (`DEFAULT_LABEL_GUESS_SYSTEM_PROMPT`). So I mirrored its
   reserve→call→settle→log_call shape self-contained in `terminology_live.py`,
   reusing the already-injected `client_for` parameter (no new callable needed
   in `launch()`'s signature) and the same `grounding_config` DB row/model the
   disambiguation judge uses. **Flag for the orchestrator:** if a future task
   wants this DRYer, the natural refactor is to parameterize
   `app._grounding_judge_live` with a `system_prompt` argument and delete my
   mirrored copy — deliberately not done here since it would touch `app.py`.

2. **New trace `strategy` value `"guess"` instead of reusing `"prefix"`.** The
   task explicitly asked me to verify guessed-label queries carry a
   distinguishable strategy label since the frontend renders `q.strategy`. Before
   this change, `_widen()` gave BOTH the alt-names and label-guess widening
   tiers `strategy="prefix"` (only `kind` distinguished them) — per the
   pre-existing code comment, "`strategy` tracks the BACKEND, `kind` already
   tracks the tier". Since a frontend view that renders `q.strategy` alone (not
   `kind`) couldn't tell an LLM-guessed query from an ordinary prefix search, I
   added a 4th enum value for the label-guess tier specifically, leaving
   alt-names (`"prefix"`) untouched (it's zero-LLM, arguably needs no visual
   flag). No test in the existing suite asserted `strategy=="prefix"` for
   either widening tier (only `kind` was asserted), so this is additive, not a
   regression. **`docs/superpowers/specs/2026-06-30-demo-contracts.md`
   currently documents `strategy` as a CLOSED enum
   (`"prefix" | "cirrus" | "sitelink"`)** — that spec is the wire-contract SSOT
   and needs the same delta; it is outside my file lane (not listed in "your
   files") so I flagged it in `terminology.md` instead of editing it directly,
   per the task's own instruction ("note it for the orchestrator").

3. **`search_mode="label-guess"` also silently enables the alt-names widening
   tier.** Per `candidates.py`'s own module docstring, `"label-guess"` mode is
   "alt-names PLUS" — the alt-names tier (parenthesized-alternate extraction,
   zero LLM calls) now also runs live wherever it previously didn't (baseline
   mode never widens at all). This is existing, tested behavior of the mode I
   was told not to change the escalation order of — flagging it explicitly
   since it's a second, free recall improvement bundled into this change
   that the task description didn't separately call out.

4. **Discrepancy found during grounding (documented, not silently
   "fixed"):** the task's grounding instructions point to
   `scripts/wiki_eval.py::_build_label_guesser` as "the reference wiring" for
   how a Judge callable is built from an LLM client. That function does **not
   exist** in the current `scripts/wiki_eval.py` (confirmed via full-text
   search — `wiki_eval.py` has no `search_mode`/`label_guesser`/`guess`
   references at all, despite `base.py`'s and `label_first.py`'s own docstrings
   claiming it does). `scripts/wiki_eval.py` currently has no `--search-mode`
   CLI flag and `_config_from_bits` never sets `search_mode`, so the
   label-guess tier has, as far as I can tell, never actually been exercised
   by the research harness either — only by `tests/test_terminology.py`'s unit
   tests directly against `generate_candidates`. I did NOT build
   `_build_label_guesser`/`--search-mode` in `wiki_eval.py` — it's a
   research-CLI concern, outside this task's live-pipeline scope and outside my
   file lane, and doing it well (CLI flag, cost estimation, budget wiring)
   is a separate unit of work. I instead used `app._grounding_judge_live` /
   `_build_judge` (which DOES exist in both files) as the pattern reference for
   "how a Judge callable is built from an LLM client", which was sufficient.
   **This is a pre-existing doc/code discrepancy, not something I introduced —
   flagging for the owner/orchestrator to decide whether `wiki_eval.py` should
   get the CLI wiring these comments assume exists.**

5. **Timeout/retry constants kept independent from `_NER_*`** rather than
   reused, so either leg (NER vs label-guess) can be tuned via its own env var
   without coupling. Same default values (20s/2 retries/0.5s backoff) since
   both are "one short LLM call" in shape.

## Open questions

- Should `_grounding_label_guess_live` eventually be unified with
  `app._grounding_judge_live` via a `system_prompt` parameter? (See Decision 1.)
  Not done here — `app.py` outside my lane.
- Should `scripts/wiki_eval.py` get the `--search-mode`/`_build_label_guesser`
  wiring its own sibling modules' docstrings claim it has? (See Decision 4.)
  Not done here — separate research-CLI task, outside scope.

## NOT done (explicit)

- **`docs/superpowers/specs/2026-06-30-demo-contracts.md`** — the
  Grounding-trace `strategy` enum needs a 4th value, `"guess"`, added to its
  documented `prefix|cirrus|sitelink` closed set. Not edited (outside my file
  lane); flagged in `docs/stages/terminology.md`'s § Live trigger and here for
  `docs-keeper`/the orchestrator to close out.
- **`scripts/wiki_eval.py`** — no `--search-mode` CLI flag or
  `_build_label_guesser` added; the research harness still can never exercise
  `search_mode="alt-names"/"label-guess"` end-to-end, only via direct unit
  tests against `generate_candidates`. Out of scope for this task (see
  Decision 4).
- **No live/paid-API smoke test was run.** All 4 new tests use a mocked
  WikidataClient and a mocked LLM client (`_FakeClient`), per the task's "NO
  paid LLM calls in tests" instruction — I never called a real
  Wikidata/OpenRouter/OpenAI endpoint. The real end-to-end behavior against
  live Wikidata (does "Хана" really surface Q425405 via `wbsearchentities`
  today) was NOT verified against the live API in this task.
- `app.py` was not touched at all (confirmed via `git diff --stat`), including
  its `_grounding_judge_live` function — no code sharing/refactor attempted
  there, per the file-lane restriction.

## Test run (honesty: ran, not simulated)

Full backend suite, from the worktree root:

```
$ .venv/bin/python -m pytest -q
639 passed in 5.53s
```

No unrelated failures — I confirmed via `git status`/`git diff --stat` that
`model_matrix.py`, `migrate.py`, `webapp.md`, and everything under `frontend/`
carry other agents' concurrent unstaged edits, none of which I touched; the
639-pass count includes their in-flight changes plus mine, all green together
(no deselection was needed — nothing failed).

Label-guess-specific subset (4 new + 7 pre-existing `candidates.py` unit
tests covering the mode):

```
$ .venv/bin/python -m pytest -q -k "label_guess" tests/test_terminology_live.py tests/test_terminology.py
11 passed in 0.05s
```

`ruff check` on the 3 touched files reports 5 pre-existing issues (2 in
`candidates.py`, 1 in `terminology_live.py`, all on lines I never edited —
confirmed by line number/content) and 0 new issues on the lines I added (I
fixed 3 lines-too-long that my own new code introduced before finalizing).

## New trace `strategy` value for the frontend (flag for the orchestrator)

`Term.traceJson.queries[].strategy` gains a 4th possible value: `"guess"`
(label-guess-tier widened queries; `mechanism` stays `"wbsearchentities"`,
same as `"prefix"`). The frontend agent (out of my lane, `frontend/` is
another agent's territory) may want a visual treatment for it alongside the
existing `prefix|cirrus|sitelink` badges in the grounding-trace UI.
