# python-pro: wiki-eval runner rework (transport/params/observability + protocol-v3 report)

Date: 2026-07-10. Branch: `claude/ner-translation-config-b0ozsc` (no commit made — per mission instructions, changes left staged for the orchestrator).

## Scope

Implemented the runner phase of `docs/superpowers/specs/2026-07-10-wiki-eval-experiment-v2.md` §4.1/§4.2 + remainder of §7, building on two prior lanes already landed (LLM client observability fields, terminology NER/judge prompt rework, protocol-v3 aggregator). Concretely:

1. **Route + per-model vendor params** (§4.1, Р2/Р3/Р13/Р14): retired the CloseRouter three-branch `_resolve_route` + env-var machinery; replaced with a single standard-OpenRouter route resolver returning one dict for both extractor and judge roles, driven by a `MODEL_PARAMS` table (deepseek-v4-flash, gemini-3.1-flash-lite, gemma-4-31b-it) with CLI overrides winning per field.
2. **Per-call gates** (§4.1.4, Р13/Р14/Р15): new `LengthOverflowError`/`CallGateError`/`BudgetExhaustedError` (all `FatalGroundingJudgeError` subclasses) and a `_gate_reply` helper invoked after every completed LLM call, run AFTER logging, BEFORE budget settlement.
3. **Parse-fail accounting** (§4.2.5, finding 1): `FailureTracker.record_parse_failure`, `_parallel_extract_fn.safe_extract` now catches `ExtractionParseError` before the transient-error branch, tolerates it as zero mentions, counts it separately, prints one loud stderr line.
4. **Per-call observability** (Р8): new `CallLogger` (lock+append+flush, same pattern as `Checkpointer`) writing `calls.jsonl`; `meta.json` gained `generation_params`.
5. **Budget exhaustion is loud** (findings 2/10): `guard.can_reserve()` failure now raises `BudgetExhaustedError` instead of a bare `RuntimeError` that `ground()`'s judge catch-all used to swallow.
6. **`--resume` restores full guard state** (finding 3): `Checkpointer.record` now snapshots `spent_by_kind`/`calls_by_kind` into each progress line; `cmd_run --resume` restores them, degrading to zero + a loud stderr warning for old-format lines; `meta["n_pred_mentions"]` fixed to the merged (not new-only) count.
7. **Prompts wiring** (Р5/Р7): extraction now uses `NER_SYSTEM_PROMPT`/`ner_user` from `extract.py`; judge system prompt now imports `DEFAULT_GROUNDING_JUDGE_SYSTEM_PROMPT` from `label_first.py` as the single source of truth; reask-prompt comment rewritten to drop the stale temperature=0 premise.
8. **CLI additions**: `--temperature`/`--top-p`/`--top-k`/`--max-tokens`/`--base-url` on `run`/`ablate`; `--model` now defaults to `DEFAULT_MODEL`; `--provider` takes an OpenRouter display-name pin; `report` gained `--tier` and lost `--p3`.
9. **`cmd_report` → protocol v3** (Р9): rebuilt around `metrics.aggregate_corpus_v3`/`report.render_html_v3`; deleted `--p3`, `_label_exists_fn`, `_resolved_by_of_for_article`, `_stratum_of_for_article`, `_type_of_for_article`.
10. **Retired the mention-level protocol machinery** (§7): stripped `metrics.py` down to `Tuple4`/`_cell`/`UNDERPOWERED_THRESHOLD`/`ArticleUnits`/`_classify`/`aggregate_corpus_v3`; deleted `matching.py` and its test (zero remaining importers, confirmed by grep); stripped `report.py` down to `render_html_v3`/`methodology_draft`.
11. Updated/extended `tests/test_wiki_eval_runner.py` (92 → 117 tests) to cover all of the above; moved the still-relevant `_cell`/Wilson-CI boundary tests from the deleted `test_wiki_metrics.py` into `test_wiki_metrics_v3.py`; rewrote `test_wiki_report.py` around `render_html_v3` only.

## Files changed

- `scripts/wiki_eval.py` — full rework (route resolution, gates, CallLogger, parse-fail accounting, budget-exhaustion, resume-state restore, prompts, CLI, `cmd_report` v3). Owned file; no deletions-only constraint.
- `src/palimpsest/terminology/evaluation/metrics.py` — deletions only, per mission constraint: removed mention-level M1/M2/M3 + P1/P2/P3 aggregation machinery, kept v3 + shared primitives.
- `src/palimpsest/terminology/evaluation/matching.py` — deleted (`git rm`).
- `src/palimpsest/terminology/evaluation/report.py` — deletions only: removed old `render_html` + its exclusive helpers, kept `render_html_v3`/`methodology_draft` untouched (methodology text is a "preserve chat formulations" verbatim copy, explicitly outside the deletions-only mandate).
- `tests/test_wiki_eval_runner.py` — updated + extended.
- `tests/test_wiki_matching.py` — deleted (`git rm`).
- `tests/test_wiki_metrics.py` — deleted (`git rm`), its still-useful `_cell` boundary tests moved into `test_wiki_metrics_v3.py`.
- `tests/test_wiki_metrics_v3.py` — extended with the moved `_cell`/`UNDERPOWERED_THRESHOLD` tests.
- `tests/test_wiki_report.py` — rewritten around `render_html_v3`.

No `git commit` was made — the mission explicitly forbids it (`git rm` staging only); all changes are left in the working tree for the orchestrator to review/commit.

## Decisions & rationale

- **`_resolve_route` signature and resolution order** follow the mission's literal pseudocode: CLI value wins when not `None`; else `MODEL_PARAMS[model]` when known; else omitted, except `max_tokens` (falls back to `DEFAULT_MAX_TOKENS`, not `MODEL_PARAMS`, since the spec fixes it at 20000 for every model/role) and `base_url` (falls back to `DEFAULT_BASE_URL`).
- **The served-by gate pin is read back from the *effective* (post-merge) `extra_body["provider"]["order"][0]`**, not the pre-merge `MODEL_PARAMS`/CLI value — this is what makes an explicit `--extra-body` provider override change the gate consistently instead of gating against a pin that's no longer actually requested (finding 4 regression, spec-mandated).
- **`_build_extract_fn`/`_build_judge` each call `_resolve_route` internally** (rather than `cmd_run` resolving once and threading the resolved dict down) so direct unit tests (`_build_extract_fn(guard, sem)` with no kwargs) still get full `MODEL_PARAMS`-driven defaults without needing a route object plumbed through every test call site. `cmd_run` resolves its own route (deterministic, same inputs) purely for the run-dir slug and `meta["generation_params"]` — no behavioral divergence risk since it's a pure function of its arguments.
- **`_gate_reply` is called after `CallLogger.log`** in both builders (mission requirement: "the offending call must be in the artifact").
- **`safe_extract`'s exception ordering**: `FatalGroundingJudgeError` first (halt, enrich with `add_note`), then `ExtractionParseError` (tolerate, separate counter), then the existing transient/deterministic split — matches the mission's explicit ordering.
- **Judge prompt constants**: kept the module-level names `JUDGE_SYSTEM_PROMPT`/`JUDGE_REASK_SYSTEM_PROMPT` in `wiki_eval.py` (now aliasing/derived from `label_first.DEFAULT_GROUNDING_JUDGE_SYSTEM_PROMPT`) rather than removing them, since several existing tests reference `wiki_eval.JUDGE_REASK_SYSTEM_PROMPT` directly and the mission's item 7 describes replacing the *definition*, not the *name*.
- **`report.py`'s `methodology_draft()` left untouched** despite spec §4.5 item 12 suggesting it should eventually link to the tex file instead of duplicating — the OWNED FILES list marks `report.py` "deletions only," so rewriting its content (not deleting) is out of scope for this lane; flagged as an open item below.
- **Did not touch** `scripts/eval_grounding.py`, `scripts/rebuild_demo.py`, `scripts/fix_mention_lemmas.py` — they define their own independent (not imported from `wiki_eval.py`) `CLOSEROUTER_MODEL`/`CLOSEROUTER_PROVIDER`/`JUDGE_MAX_TOKENS` constants and are outside the owned-files list.

## Verification performed

- `PYTHONPATH=src uv run --no-sync python3 -m pytest tests/ -q` → **619 passed** (full suite, not just the owned test files).
- `scripts/wiki_eval.py --help` / `run --help` / `report --help` → all exit 0, `--tier`/new sampling flags present, `--p3` absent.
- **Live dry-run smoke test** against the real `data/eval/wiki/gt.jsonl` + pages cache: `run --dry-run --max-usd 40` → `config=111 articles=100 paragraphs=2644`, forecast `$1.3591` within budget, exits 0.
- **Live `cmd_report` smoke test**: copied a real historical `pred.jsonl` (gemini run `2026-07-05T23-06-38Z`) into the scratchpad (not mutating the committed run dir) and ran `report --pred <scratch>`. Output: `named: gold_units=4032 R_doc=0.8177083333333334 ...` — this exactly matches `test_regression_anchor_run_a_gemini`'s hardcoded `tp=3297/(3297+735)=4032` anchor, confirming the CLI wiring (not just the aggregator unit tests) is correct end-to-end.
- Repo-wide grep sweep (excluding `docs/experiments/**`, frozen history) confirmed zero remaining references to every deleted symbol (`match_m1/2/3`, `matching.py`, mention-level `aggregate`/`aggregate_corpus`/`ArticleTuples`, old `render_html`, `CLOSEROUTER_*`/`WIKI_EVAL_PROVIDER`/`DEFAULT_NER_PROMPT`/`JUDGE_MAX_TOKENS`/`_label_exists_fn`/`--p3` inside `wiki_eval.py`).
- `ruff check` on `metrics.py` → clean (0 findings, improved from baseline). `report.py`'s only remaining `E501`s are in the untouched `_CSS` blob. `wiki_eval.py`'s new findings are `E501`s in argparse help text following the file's pre-existing long-line convention (58 pre-existing → 70 now); not treated as blocking since this codebase already tolerates the pattern throughout and CLAUDE.md doesn't set a line-length hard invariant.

## Open questions / follow-ups for the owner or a later lane

- `report.py`'s `methodology_draft()` still duplicates the old v1/v2 prose (mention-level M1/M2/M3, P1/P2/P3) rather than linking to `docs/paper/sections/eval-metrics-terminology.tex` as the spec's item 12 eventually wants — out of scope here (deletions-only mandate on this file); needs a follow-up docs/content lane.
- `docs/stages/wiki-eval.md`, `docs/paper/paper-state.md`, `docs/known_issues.md`, `docs/runbooks/sr004-local-eval-runbook.md` doc-parity (spec §7 "UPDATE доки"/"UPDATE runbook") was explicitly not in the OWNED FILES list for this lane — belongs to `docs-keeper`/a documentation lane before this can ship per Hard Invariant 2.
- The pilot smoke run and the 3-model full run (spec §5) have not been executed — this task was scoped to the code/tests only, not to spending the actual `$15` pilot budget.

## NOT done (explicit)

- No live paid LLM calls were made (extraction/judge smoke calls against the real OpenRouter API) — all verification was dry-run, offline `cmd_report` against a pre-existing `pred.jsonl`, and unit tests with fakes. Per spec §5, the pilot (10 articles on gemini, gated on `finish_reason=length`=0 / `reasoning_tokens>0` on 100% of calls / served_by==pin on 100% of calls / parse-fail<1%) has **not** been run.
- No documentation files were updated (see Open questions) — outside the OWNED FILES scope given to this lane.
- No git commit was created (explicitly forbidden by the mission; `git rm` staging only).
- Did not clean up or archive the 15 old (SUPERSEDED) run directories mentioned in spec §7/§5.5 — out of scope for this runner-code lane.
