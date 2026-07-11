# ml-engineer report — wiki-eval NER extraction-only cost run (5 models, OpenRouter)

Branch: `claude/ner-translation-config-b0ozsc`. Commit: `e85112b`.

## Scope

Task: execute NER **extraction-only** runs (no disambiguation judge) over the
full 100-article WikiHist corpus for 5 models via OpenRouter (Gemma-3-27B-it,
Qwen3.6-27B, Gemma-4-31B-it, Gemini-3.1-Flash-Lite, DeepSeek-V4-Flash), gated
by a 2-article smoke test and a hard $5 cost guard. The NER prompt
(`src/palimpsest/terminology/extract.py`, commit `8bbafcf`) was explicitly
frozen — no prompt/extract.py edits permitted.

Outcome: smoke ran successfully, judge-free mode verified, but the cost-gate
extrapolation (smoke cost × 100 articles × 5 models ≈ $13.02) exceeded the
$5 cap → **stopped per protocol before any of the 5 full 100-article runs**.
No model run beyond the 2-article smoke was executed.

## Files changed

- `scripts/wiki_eval.py`
  - Added `run --no-judge` CLI flag and threaded `no_judge: bool = False`
    through `_run_one_config`. When set, `judge=None` is passed instead of
    calling `_build_judge(...)` — reuses `LabelFirstGrounding.ground()`'s
    pre-existing `if judge is None:` branch (`resolved_by=judge_unavailable`,
    zero LLM calls). Exact-label matches and the free Wikidata candidate
    search are unaffected.
  - `meta.json` now discloses `"no_judge": true/false` (added to the
    `counters` dict returned by `_run_one_config`) so a run dir is
    self-evidencing about whether judge calls were even attempted.
  - No changes to `MODEL_PARAMS`, `_resolve_route`, prompts, or any other
    gate/retry/checkpoint logic.

- `src/palimpsest/terminology/evaluation/predict.py`
  - `predict_tuples`'s per-mention `records` dict now includes
    `"category": mention.category` (previously silently dropped between
    `TermMention` — which already carried `.category` — and the record dict
    written to `pred.jsonl`). One-line fix; not a prompt or extract.py change.

- `docs/stages/wiki-eval.md`
  - Documented both changes under "Design decisions" (doc-parity, same
    commit as the code per Hard Invariant 2).
  - Added `[--no-judge]` to the `run` CLI signature under "Interface".
  - Added a dated Status entry (2026-07-10) recording this cost run and the
    gate-stop finding, so the doc stays the single source of truth for what
    was actually run vs. pending.

- `reports/terminology/wiki-eval/google--gemini-3.1-flash-lite--Google-AI-Studio/111/2026-07-10T18-01-56Z/`
  - Smoke run artifacts (`pred.jsonl`, `meta.json`, `calls.jsonl`,
    `progress.jsonl`) — the evidence backing the cost-gate stop. Committed
    per the "reports/ is append-only" convention; grepped for secret
    material before commit (0 matches for `OPENROUTER`/`sk-or`).

All changes pushed to `origin/claude/ner-translation-config-b0ozsc`.

## Decisions & rationale

1. **`--no-judge` over a standalone driver script.** The task said "look for
   phase flags/subcommands" and to prefer extraction+search-without-judge if
   invocable. No such flag existed, but the underlying capability already did
   (`ground()`'s `judge is None` branch) — composing it via one CLI flag on
   the existing `run` subcommand reuses all existing infrastructure
   (checkpointing, `--resume`, `BudgetGuard`, `meta.json`/`calls.jsonl`
   observability, output layout) instead of risking a parallel, less-tested
   path. Verified live: smoke `meta.json` shows `judge_calls: 0`,
   `spend.judge: 0.0`.

2. **`category` passthrough fix.** The smoke gate explicitly required
   verifying `pred` entries carry `{surface, lemma, category}`. Reading
   `predict.py` showed `category` was computed (`TermMention.category`,
   populated by `mentions_from_surfaces` from the frozen prompt's wire
   schema) but never copied into the output record — a real plumbing gap
   unrelated to the frozen prompt/extract.py, so fixing it was in-scope.
   Confirmed post-fix: all 247 smoke pred records carry a `category` value
   from the `NER_CATEGORIES` set (`other`, `person`, `place`, `title`,
   `event`, `language`, `work`, `institution`, `realia`, `people`, `deity`,
   `dynasty`).

3. **Router ID resolution.** Resolved live via `GET
   https://openrouter.ai/api/v1/models` (346 models), not invented or
   guessed:
   - `deepseek/deepseek-v4-flash`, `google/gemini-3.1-flash-lite`,
     `google/gemma-4-31b-it` — already in `wiki_eval.py`'s `MODEL_PARAMS`
     with owner-locked provider pins (Novita / Google AI Studio / WandB);
     left untouched (a pin change requires a spec edit per the code
     docstring, spec Р14 — out of scope here).
   - `google/gemma-3-27b-it` and `qwen/qwen3.6-27b` are **not** in
     `MODEL_PARAMS` — in the paper's Table C plan they run locally on sr004,
     not via OpenRouter (`docs/runbooks/sr004-local-eval-runbook.md`). This
     task explicitly asked for all 5 via OpenRouter, so I did not add them to
     `MODEL_PARAMS` (would require a spec edit) and instead resolved
     provider pins by querying each model's `/models/{id}/endpoints` and
     picking the cheapest reliable provider by uptime: `google/gemma-3-27b-it`
     → DeepInfra ($0.08/$0.16 per Mtok, 99.8%+ uptime), `qwen/qwen3.6-27b` →
     Io Net ($0.285/$2.40 per Mtok, 99.97% uptime). Both probe-confirmed live
     with a raw single-call `curl` test (outside `wiki_eval.py`, cost
     ≈$0.0003 total, not committed as a run artifact) before committing to
     using them: gemma-3-27b-it returns clean (fenced) JSON, no reasoning
     capability; qwen3.6-27b with `reasoning:{"enabled":false}` returns
     `reasoning_tokens: 0` (hybrid-thinking model actually suppressed, unlike
     the local vLLM runbook's `chat_template_kwargs.enable_thinking` — the
     OpenRouter-normalized `reasoning` field was the only lever available
     through this transport and it worked).
   - None of these 5 models' full 100-article runs were executed — the cost
     gate tripped first.

4. **Stopping at the cost gate instead of proceeding.** Smoke:
   $0.05206175 for 2 articles (25 paragraphs, 247 mentions, extraction only).
   Per-article rate $0.026030875 → ×100 articles ×5 models = $13.0154375,
   2.6x over the $5 cap. The task's cost-gate instruction was explicit and
   unconditional ("If projected extraction total exceeds $5, STOP and report
   the projection instead of proceeding") — I followed it literally rather
   than substituting my own judgment (e.g. reasoning that the 4 untested
   models are much cheaper per-token, which is true but not what the given
   gate formula tests). Root cause disclosed in `docs/stages/wiki-eval.md`:
   gemini-3.1-flash-lite's locked `MODEL_PARAMS` pin sends
   `reasoning:{"effort":"medium"}` on every extraction call, and reasoning
   tokens dominate the completion (e.g. 1001/1225 completion tokens on one
   observed call) — so "extraction is the cheap part, judge is the expensive
   part" (the task's framing) does not hold for this model under its locked
   generation params. `--no-judge` removes judge cost, not reasoning-token
   cost.

5. **Committing work despite stopping at the gate.** The `--no-judge`
   flag and `category` fix are independently correct/useful infrastructure
   (verified by the full existing test suite, 273 passed under `uv run
   pytest tests/ -k "terminology or wiki"`), and the smoke run is real,
   billed evidence that should not be lost or left uncommitted. Committed
   with doc-parity in the same commit per Hard Invariant 2, then pushed
   (this is a shared task branch with other agents' commits already on it).

## Open questions

- Should the owner raise the $5 cap, given the real extraction-only cost for
  just gemini-3.1-flash-lite alone projects to ~$2.60/100 articles? A
  same-shape smoke for each of the other 4 models (not run here, to stay
  within the given protocol) would let a per-model rate replace the uniform
  gemini-derived extrapolation and likely show the total is well under $13 —
  gemma-3-27b-it/DeepInfra and qwen3.6-27b/Io Net price 30-280x cheaper per
  token than gemini.
- Is `--no-judge`'s NER-only output (no `qid` for anything that would have
  needed judge disambiguation) actually sufficient for "a later
  search-analysis" the task mentioned for gemini's corpus, or does that
  downstream use need real judge-resolved QIDs after all? Not something I
  could resolve without the downstream consumer's contract.
- Should `google/gemma-3-27b-it`/`qwen/qwen3.6-27b` be added to
  `MODEL_PARAMS` with a spec edit, formalizing OpenRouter routing for them
  as a durable alternative/supplement to the sr004 local runbook, or was
  this task's OpenRouter routing meant to be a one-off?

## NOT done

- **None of the 5 models' full 100-article runs were executed** — only the
  2-article gemini smoke ran. No `reports/terminology/wiki-eval/<slug>/111/`
  full-corpus run dirs exist for any of the 5 models from this task.
- No per-model commits/pushes of the form `feat(wiki-eval): NER extraction
  run — <model>` (step 4 of the task protocol) — none applicable since no
  full run completed.
- No category-distribution, mention-count, or per-model cost telemetry
  beyond the single gemini smoke (`n_pred_mentions=247` over 2 articles) —
  the requested `per_model` array in the task's return schema is empty.
- Did not add `google/gemma-3-27b-it`/`qwen/qwen3.6-27b` to `MODEL_PARAMS`
  (would need a spec edit, out of scope for direct code execution).
- Did not attempt to reduce gemini's reasoning-token cost (e.g. try
  `reasoning:{"enabled": false}` instead of the locked `{"effort":"medium"}`)
  to see if the gate could be passed differently — the pin is spec-locked
  (Р14) and changing it wasn't authorized here.
- Did not run smoke tests for the other 4 models (only a cheap raw single
  `curl` probe each for gemma-3-27b-it/qwen3.6-27b, not a `wiki_eval.py run`
  smoke) — the task's protocol specified smoke only for gemini.
