# BOUQUET multi-judge re-scoring runner — build + validation report

Agent: python-pro. Branch: `claude/ner-translation-config-b0ozsc`. Commit: `b43bf0f`
(pushed, first attempt, no retries needed).

## Scope

Build a runner that re-scores the 4 vendored BOUQUET ru2en translation systems
(`external/gse-translation`) with pluggable cloud LLM judges through an
OpenAI-compatible gateway, mirroring the vendored judge pipeline's prompt
assembly and response parsing exactly, plus a stats subcommand comparing
judge scores against vendored MetricX-ref/MetricX-QE/COMET. Validate
end-to-end with deepseek-v4-flash on 5 pilot paragraphs, budget ≤ $0.50.
Frontier judges (opus/gpt/gemini) are configured but explicitly NOT run.

## Files changed

- `scripts/bouquet_judge_rerun.py` (new, 878 lines) — the runner. Two
  subcommands: `run` (score judge × system × paragraph × criterion) and
  `stats` (means / tie-rate / Spearman vs vendored automatic metrics).
- `configs/bouquet_judges.yaml` (new) — judge registry: `deepseek-v4-flash`
  (`enabled: true`) + 3 frontier placeholders (`enabled: false`, hard-gated).
- `docs/known_issues.md` (modified) — new addendum documenting a reasoning-
  tokens quirk found during validation (see below).
- `reports/bouquet/judges/deepseek-v4-flash/{scores.jsonl,stats.json}`,
  `reports/bouquet/judges/summary.md` (new) — real validation-run output,
  committed as provenance (matches the existing tracked
  `reports/bouquet/judge_metric_stats.json` convention).

## Grounding (requirement 1)

Read `external/gse-translation/src/palimpsest/scoring.py` (prompt assembly,
`load_prompts`, `_USER_MSG_TEMPLATE`, `parse_judge_response`/`JudgeParseError`,
`score_paragraph`'s `_MAX_PARSE_ATTEMPTS=2` retry), `config.py` (`ModelConfig`/
`JudgeConfig`), `llm/client.py` (OpenAI vs Anthropic dispatch, retry/backoff),
and `configs/models.yaml` (the `t0`/no-temperature regime precedents already
in use for deepseek/gpt-5.5/claude-opus entries). Also read this repo's OWN
`src/palimpsest/llm/client.py` — its "3 attempts, 1s/3s/9s backoff" is an
explicit **owner directive** for CloseRouter's ~90% per-route success rate,
which I adopted for the runner's HTTP retry policy instead of the vendored
package's own (different) numbers, since it's the more authoritative,
same-repo precedent. `scripts/judge_metric_stats.py` (existing Spearman/tie-
stats script) was read and its computation approach (paragraph-level
Spearman with average-rank ties, `share_9_10` tie metric, positional
alignment with no explicit id column) reused rather than rewritten.

**Schema notes (where data actually lives):**
- Translations: `external/gse-translation/data/bouquet/translation/<system>/translation.json`
  — flat `list[str]`, 198 entries, index-aligned with `bouquet_original.json`.
  No `id` column anywhere in this dataset; alignment is purely positional.
- Vendored per-paragraph automatic metrics for the `stats` subcommand:
  `evaluation/<system>/metricx/scores.jsonl` and `scores_wo_ref.jsonl` (key
  `prediction`), `evaluation/<system>/comet/scores.json` (key
  `paragraph_scores`, a flat list). Confirmed no explicit id field in any of
  these — same positional-alignment assumption `judge_metric_stats.py`
  already validated (23/24 cells matched a colleague's screenshot table).
- BOUQUET paragraphs carry **zero** `"* * *"` / `"picture"` / `"[TRANSLATION
  FAILED]"` markers across all 4 translation.json files (checked directly) —
  so `scoring.py`'s `classify_paragraph` marker-skip branch was deliberately
  **not** ported; it cannot fire on this dataset (no speculative code for an
  unreachable case).

## Decisions & rationale

- **HTTP layer: raw `httpx.AsyncClient`, not the `openai` SDK.** Task
  explicitly scoped "stdlib + requests/httpx only — no heavy frameworks";
  `httpx` was already a transitive dependency in `.venv` (used elsewhere in
  `src/palimpsest/webapp/budget.py`). Retry policy and the neutral
  `User-Agent: palimpsest-llm/1.0` header mirror this repo's own
  `llm/client.py` (CloseRouter WAF workaround, "3 attempts, 1s/3s/9s" owner
  directive) rather than the vendored external package's numbers.
- **Response parsing is a byte-for-byte port** of `scoring.py`'s
  `JudgeParseError`/`parse_judge_response` (same JSON-fence regex, same 4
  failure reasons, same `_MAX_PARSE_ATTEMPTS=2`) — required for score
  comparability with Danil's pipeline.
- **Resume key = `(system, paragraph_id, criterion)`**, one `scores.jsonl`
  per judge covering all 4 systems × 3 criteria; presence = done (mirrors
  `scoring.py`'s `load_existing_ids` convention). Parse failures go to a
  sibling `parse_failures.jsonl` and are simply absent from `scores.jsonl`,
  so they're retried automatically on the next run — no 3-strikes-terminal-
  null state machine was ported, since BOUQUET's 198 paragraphs don't need
  it and the task didn't ask for it (no speculative abstraction).
- **Frontier judge config updated live** when
  `docs/experiments/2026-07-08-judge-probe/probe-results.md` appeared mid-task
  (requirement 7). This corrected my initial guess: the probe found
  `reasoning: {"enabled": true}` must be sent **explicitly** for
  `frontier_default` (not omitted as I first assumed), and that Gemini 3.1
  Pro's `response_format=json_object` causes a 400 (modeled via the existing
  `supports_structured_output: false` field, no new plumbing needed).
  Router ids were corrected to the probe's exact `GET /v1/models` values
  (`openai/gpt-5.5`, not the placeholder `openai/custom-gpt-5.5-low` I'd
  guessed). These judges remain `enabled: false` and are hard-gated by
  `run`'s `--allow-disabled` check — not run, per requirement 7.
- **Cost accounting**: real `usage.cost`/`cost_usd` was **not surfaced at
  all** by the gateway for deepseek-v4-flash in this session (confirmed via
  a raw probe call — neither key present). Added a `PRICE_TABLE_USD_PER_MTOK`
  catalog-price fallback (mirrors `scripts/probe_providers.py`'s own pattern)
  so the end-of-run print still gives a meaningful `$` figure, clearly
  labeled real vs. estimated.
- **Spearman**: `scipy` is not installed in `.venv`; implemented an exact
  average-rank fallback (verified by hand against a 5-point tied example,
  matches scipy's default tie convention) and prefer real `scipy.stats.
  spearmanr` when importable, per requirement 5.

## Validation result (requirement 6)

`python scripts/bouquet_judge_rerun.py run --judge deepseek-v4-flash --system
translate-gemma-bouquet --pilot 5` → **15/15 scored, 0 parse failures**, all
`final_score` values in range (8, 9, 10 observed). Resume verified: a second
identical invocation planned 0 calls ("15 already scored, skipped"). `stats`
subcommand ran cleanly, producing `stats.json` (n=5 per criterion for
`translate-gemma-bouquet`, correctly null/n=0 for the 3 unscored systems) and
`summary.md`. Spend: **$0.0049 estimated** (catalog price 0.07/0.14 $ per
Mtok in/out; real cost not surfaced by the gateway) — well under the $0.50
cap.

## Quirk found (not previously documented)

On route `auto` (the route judge-role deepseek calls are forced onto, since
`provider-9` + `response_format=json_object` → 400), sending
`"reasoning": {"enabled": false}` explicitly does **not** suppress reasoning:
all 15/15 validation calls returned `reasoning_tokens > 0` (262–3443, ~45% of
completion tokens). This is a cost quirk, not a correctness one — 0 empty
responses at `max_tokens=4096`, 0 parse failures — but it roughly doubles
expected completion-token spend versus the 2026-07-07 smoke's `provider-9`
numbers. Documented in `docs/known_issues.md` (new addendum after the
existing two deepseek entries) and independently corroborated by the
2026-07-08 probe's own finding on the same model.

## Open questions

- Full BOUQUET run cost for the 3 frontier judges (~$1.3–$14 each, probe
  estimate) depends on which prompt variant ships to production (`v1`
  5-criterion vs `universal`/`v1_core3` 3-criterion) — flagged by the probe,
  not resolved here; this task used `v1_core3` per the explicit instruction.
- Whether `enabled: true` should ever flip for the frontier judges is an
  owner/orchestrator decision, not made here (requirement 7 is explicit:
  do not run them).

## NOT done (explicit)

- Frontier judges (gpt-5.5, claude-opus-4.8, gemini-3.1-pro) were **not
  run** — config pre-filled, hard-gated `enabled: false`, per requirement 7.
- Full 198-paragraph × 4-system run was **not** executed for any judge —
  only the 5-paragraph × 1-system validation pilot, per requirement 6's
  explicit scope and budget cap.
- `docs/experiments/2026-07-08-judge-probe/` and
  `docs/reports/docs-keeper-pdf-extraction-report.md` were left untracked —
  both belong to other parallel tasks/agents, not this one's deliverable;
  `docs/reports/python-pro-pdf-text-extraction.md` (named in the task) was
  already committed by a prior commit (`2d9dcaa`) before this task started,
  so no action was needed on it.
