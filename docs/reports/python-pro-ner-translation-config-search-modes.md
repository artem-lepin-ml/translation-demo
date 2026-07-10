# Report — search-mode widening tiers + `--reuse-extraction` (wiki-eval)

Agent: `python-pro`. Branch: `claude/ner-translation-config-b0ozsc` (shared checkout, no worktree — per task instructions).

## Scope

Two deliverables on the wiki-eval grounding experiment, per the orchestrator's task:

1. **`search_mode` setting** (`baseline` | `alt-names` | `label-guess`, cumulative) on candidate search, wired into `scripts/wiki_eval.py run` as `--search-mode`. `baseline` is a hard byte-for-byte regression constraint against pre-existing behavior.
2. **`--reuse-extraction <run-dir>`**: ground a prior completed run's already-extracted mentions (surface/lemma/category) without re-paying extraction LLM cost, writing a new run dir, never touching the source.

`src/palimpsest/terminology/extract.py` (NER prompt) was not touched, per the hard constraint. No real network/LLM calls in any test (fakes only).

## Files changed

- `/home/user/translation-demo/src/palimpsest/terminology/base.py` — `GroundingConfig.search_mode` field (+ custom `__init__` update).
- `/home/user/translation-demo/src/palimpsest/terminology/grounding/candidates.py` — cumulative widening tiers (`_alt_names_from_context`, `_guess_labels`, `DEFAULT_LABEL_GUESS_SYSTEM_PROMPT`/`_USER_TEMPLATE`), per-candidate `"source"` provenance, `label_guesser` param on `generate_candidates`.
- `/home/user/translation-demo/src/palimpsest/terminology/grounding/label_first.py` — `LabelFirstGrounding.label_guesser` (constructor-bound), threaded into `generate_candidates`.
- `/home/user/translation-demo/src/palimpsest/terminology/evaluation/predict.py` — shared `_ground_and_record` helper (used by both bridges), new `predict_tuples_from_mentions` for `--reuse-extraction`, candidate `"source"` passthrough.
- `/home/user/translation-demo/scripts/wiki_eval.py` — `--search-mode`/`--reuse-extraction` CLI flags, `_build_label_guesser`, `_reconstruct_mentions_for_article`, `_assert_reuse_extraction_coverage`, `_read_jsonl`, `BudgetGuard`'s lazy `label_guess` kind, `_config_from_bits`/`_run_one_config`/`_process_articles_parallel`/`cmd_run` plumbing, run_id mode-suffix, meta.json fields (`search_mode`, `reuse_extraction_from`, `spend.label_guess`, `calls.label_guess`, `n_reuse_extraction_unmatched`).
- `/home/user/translation-demo/docs/stages/wiki-eval.md` — Interface block, Design decisions (three modes, provenance, reuse-extraction mechanics), dated 2026-07-10 Status entry.
- `/home/user/translation-demo/docs/stages/terminology.md` — doc-parity note that `search_mode` is a fifth `GroundingConfig` field, CLI-only, not one of the four ablation toggles.
- Tests: `/home/user/translation-demo/tests/test_terminology.py` (alt-names/label-guess tier unit tests with fakes), `tests/test_wiki_predict.py` (`predict_tuples_from_mentions`, candidate `"source"` passthrough), `tests/test_wiki_eval_runner.py` (BudgetGuard kind, `_build_label_guesser`, CLI guard, reuse-extraction reconstruction/coverage/`cmd_run` wiring, run_id suffix).

## Decisions & rationale

- **Mode encoding**: `meta.json` always; run-dir `run_id` gets a `_<search-mode>` suffix only for the two non-default modes (checked: nothing in the codebase `strptime`s/globs `run_id` as a rigid timestamp — `cmd_report`/`--resume` both treat it as an opaque string) — baseline's `run_id` stays the bare ISO timestamp, unchanged.
- **Provenance field shape**: per-candidate `"source"` (`baseline`/`alt`/`label_guess`) added only when `search_mode != "baseline"`; baseline candidates never gain the key — this, plus gating every widening branch behind an early return, is what keeps `search_mode="baseline"` byte-identical (verified: the full pre-existing test suite, including exact-equality assertions, passes unmodified).
- **`label_guesser` is a separate callable**, not the disambiguation `judge` reused directly — the `judge` closure hardcodes `JUDGE_SYSTEM_PROMPT`, wrong role/contract for a label guess. Built by `_build_label_guesser` on the *same resolved route* (model/provider/sampling) as the judge, satisfying "the run's judge LLM client" without corrupting the disambiguation prompt.
- **Spend kind**: `BudgetGuard.reserve`/`settle` switched from direct `dict[kind] +=` to `.get(kind, default) +=`, so a third kind (`label_guess`) is added lazily on first use — a run that never uses it keeps the pre-existing 2-key `{extract, judge}` shape (regression-safe for the existing strict-equality test). `meta.json`'s `spend`/`calls` dicts always show a `label_guess` key (mirrors `extract`/`judge`), since that's a diagnostics artifact, not the wire-identity-constrained surface.
- **Judge-required guard**: CLI-level (`cmd_run`, before any I/O) rejects `--search-mode label-guess --no-judge`; `_run_one_config` has a second defensive `ValueError` for direct callers (tests, future scripts) that bypass `cmd_run`.
- **`--reuse-extraction` mention reconstruction**: `pred.jsonl` records don't carry `char_start`/`context` (confirmed by inspecting the live in-flight `--no-judge` runs under `reports/terminology/wiki-eval/*/111/2026-07-10T2*/pred.partial.jsonl`, which use the *current*, unmodified `predict.py` schema) — so `char_start`/`char_end`/`context` are re-derived by scanning the re-fetched article text for the literal surface occurrence whose `char_to_token_index` equals the recorded `index` (the exact inverse of how the index was originally computed, same pinned tokenizer both sides — round-trips exactly). `index` itself is always reused verbatim, never recomputed from a possibly-unmatched `-1`. Unmatched records degrade to an empty-context mention rather than being dropped, counted in `meta.json`'s `n_reuse_extraction_unmatched`.
- **DRY refactor**: `predict.py`'s per-mention ground+record body factored into `_ground_and_record`, shared by `predict_tuples` (paragraph-chunked) and the new `predict_tuples_from_mentions` (pre-extracted, `--reuse-extraction`) — zero behavior change to `predict_tuples` (verified: its existing tests pass unmodified).

## Open questions

- Owner should confirm the `run_id` mode-suffix choice (`_<search-mode>`) is the desired discoverability tradeoff vs. meta.json-only.
- `--ablate` was intentionally left without `--search-mode`/`--reuse-extraction` (task scoped to `run`) — flag if the 8-config ablation loop should also support them.

## NOT done (explicit)

- `ablate` subcommand does not accept `--search-mode`/`--reuse-extraction`.
- `--dry-run` + `--reuse-extraction` interaction is not specially handled (dry-run just ignores reuse, no crash, but the forecast doesn't account for zero extraction cost).
- Context reconstructed by `--reuse-extraction` runs sentence-splitting over the *whole article* rather than the original single paragraph (paragraph boundary isn't recoverable from `pred.jsonl` alone) — a known, documented approximation, not byte-identical to a fresh extraction's context.
- Did not touch/verify the currently-running live `--no-judge` extraction runs (read-only telemetry check only, as instructed).

## Process note — shared-branch commit collision

A concurrent process on this shared checkout committed `6f6fce4` ("fix(wiki-eval): tolerate missing reasoning tokens on extraction calls") using broad staging, which swept in this lane's in-progress `scripts/wiki_eval.py`, `docs/stages/wiki-eval.md` and `tests/test_wiki_eval_runner.py` changes alongside its own unrelated fix — leaving HEAD import-broken (missing `GroundingConfig.search_mode`, `DEFAULT_LABEL_GUESS_SYSTEM_PROMPT`, etc., which only existed in this lane's *uncommitted* working tree at the time). Per Hard Invariants (never amend a shared commit), I did not rewrite `6f6fce4`; instead committed the remaining grounding-layer files as `8b84226`, restoring a working HEAD (verified via full test suite before and after). Both commits are now on `origin/claude/ner-translation-config-b0ozsc`.

## Artifacts

- `uv run pytest tests/ -k "terminology or wiki"` → **329 passed, 0 failed**.
- Full suite `uv run pytest tests/` → **682 passed, 0 failed**.
- Commits: `8b84226` (this lane's grounding-layer files, on top of `6f6fce4`). Both pushed to `origin/claude/ner-translation-config-b0ozsc` (clean push, no rebase needed).
- `date -u` at task completion: `Fri Jul 10 22:10:36 UTC 2026`.
- Live-run telemetry (read-only, untouched), last `progress.jsonl` line per run dir under `reports/terminology/wiki-eval/*/111/2026-07-10T2*/`:
  - `deepseek--deepseek-v4-flash--Novita/111/2026-07-10T20-20-34Z`: 16/100 articles, $0.311 spent
  - `google--gemini-3.1-flash-lite--Google-AI-Studio/111/2026-07-10T20-19-19Z`: 19/100, $1.400
  - `google--gemma-4-31b-it--WandB/111/2026-07-10T20-20-09Z`: 13/100, $0.245
  - `qwen--qwen3.6-27b--Io-Net/111/2026-07-10T20-19-44Z`: 25/100, $0.612
