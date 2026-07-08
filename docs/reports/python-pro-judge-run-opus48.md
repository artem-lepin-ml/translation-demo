# BOUQUET judge run — claude-opus-4.8

Status: **complete**. Pilot gate passed, full run finished, `stats.json`
generated, committed. Written by the `python-pro` agent on branch
`claude/ner-translation-config-b0ozsc` (shared worktree — 3 other agents ran
other judges in parallel in the same tree; only `claude-opus-4.8` paths and
this report were touched/committed by this task).

## Scope

Run the BOUQUET judge re-scoring for slug `claude-opus-4.8`
(`anthropic/claude-opus-4.8`, `regime: frontier_default`) via
`scripts/bouquet_judge_rerun.py` and `configs/bouquet_judges.yaml` (already
`enabled: true`, no `--allow-disabled` needed): pilot gate → full run →
`stats` → this report → commit. Cost cap $6.00.

Known quirk, disclosed up front by the task and explicitly re-confirmed
below: the OpenAI-compat bridge silently drops reasoning params for this
model — Opus 4.8 runs the entire judge role with `reasoning_tokens = 0`
regardless of the `reasoning: {enabled: true}` sent in every request
(`regime: frontier_default`). This is the accepted, disclosed configuration
for this task, not a bug to fix.

## Environment note

`httpx`/`numpy`/`pyyaml` are only importable from the repo's `.venv`
(`source .venv/bin/activate`), not the bare system `python3`. `scipy` is
absent even in `.venv`; the runner's documented `except ImportError` fallback
(exact average-rank Spearman, same tie convention) covered this — `stats`
ran cleanly without it.

## Pilot gate — PASS

`run --judge claude-opus-4.8 --pilot 20` (240 calls: 20 paragraphs × 4
systems × 3 criteria), 424s elapsed.

| Metric | Result | Gate | Verdict |
|---|---|---|---|
| Parse-failure rate | 0/240 = **0.00%** | ≤ 2% | PASS |
| Valid 1–10 scores | 240/240 = **100.00%** | ≥ 98% | PASS |
| `reasoning_tokens` | **0** across all 240 rows | disclosed quirk | confirmed |

`parse_failures.jsonl` was never created (the runner only creates it on the
first failure — there wasn't one). Pilot usage: prompt=467,417,
completion=147,765 tokens.

## Full run

Launched immediately after the gate passed (`run --judge claude-opus-4.8`,
no `--pilot`), resumed from the 240 already-scored pilot rows — 2,136 calls
planned to reach the 2,376 target (198 paragraphs × 4 systems × 3 criteria).
Background process + log; polled `scores.jsonl` line count every ~1 min
(inside single `Bash` calls with an internal loop, since no `Monitor` tool
was available to this agent) — steady linear growth throughout (~31–37
rows/min), **0 stalls, 0 crashes, 0 restarts needed**. Finished in 3,642s
(~60.7 min), matching the "~9s/call, ~1h" estimate.

**Final: 2,376/2,376 scored, 0 parse failures, 0 duplicate `(system, id,
criterion)` keys** (verified programmatically). `reasoning_tokens = 0` on
every one of the 2,376 rows — the quirk holds for the entire run, not just
the pilot.

## Cost

The gateway does not surface `usage.cost`/`usage.cost_usd` for the
`anthropic/claude-opus-4.8` route on this proxy (`real=$0.0000` in the
runner's own printed summary, 0/2376 rows with a real cost — same gap the
runner's module docstring already documents for other judges lacking a
`PRICE_TABLE_USD_PER_MTOK` entry). Cost was computed manually from summed
token counts against the task's stated catalog price ($0.40/$0.40 per Mtok
in/out):

- Tokens: prompt=4,767,135, completion=1,531,024, total=6,298,159
  (2,376/2,376 rows with usage).
- **Cost: (4,767,135 + 1,531,024) × $0.40 / 1,000,000 = $2.5193.**
- Well under the $6.00 cap (42% of budget used).

## Results (`stats.json`)

Overall (all 2,376 rows): distribution `{6: 10, 7: 12, 8: 245, 9: 1126,
10: 983}`, mean **9.288**, tie-rate{9,10} **88.76%**.

### Per-system / per-criterion (n=198 per cell)

| System | Accuracy mean | Fluency mean | Style mean | Acc tie%{9,10} | Flu tie% | Sty tie% |
|---|---|---|---|---|---|---|
| Qwen3.6-27B | 9.293 | 9.768 | 8.732 | 91.9% | 98.0% | 69.7% |
| Qwen3.6-27B Refined | 9.384 | 9.753 | 8.732 | 93.9% | 99.0% | 71.7% |
| Translate Gemma | 9.323 | 9.657 | 8.813 | 92.4% | 98.0% | 75.3% |
| Translate Gemma Refined | 9.444 | 9.647 | 8.909 | 94.9% | 97.0% | 83.3% |
| **Avg across systems** | **9.361** | **9.706** | **8.797** | **93.3%** | **98.0%** | **75.0%** |

### Spearman ρ vs. vendored automatic metrics (avg across 4 systems, n=198 each)

| Criterion | ρ MetricX-ref | ρ MetricX-QE | ρ COMET |
|---|---|---|---|
| Accuracy | −0.080 | +0.016 | **+0.189** |
| Fluency | −0.085 | −0.045 | **+0.089** |
| Style | −0.128 | −0.021 | **+0.226** |

Sign pattern matches the other judges already in `summary.md` (negative or
near-zero vs. both MetricX variants, positive vs. COMET), with generally weak
magnitude (|ρ| < 0.23 throughout) and a heavily right-skewed, low-variance
score distribution (tie-rate{9,10} 70–99% depending on criterion/system) —
this judge scores generously with low spread, which mechanically compresses
achievable rank correlation against any external metric. No cross-judge
comparison beyond this sign-consistency note; a full 4-judge comparison is
a separate, later task once all judges finish.

## Files changed (committed by this task)

- `reports/bouquet/judges/claude-opus-4.8/scores.jsonl` — 2,376 rows,
  append-only.
- `reports/bouquet/judges/claude-opus-4.8/stats.json` — per-system
  means/tie-rates/Spearman.
- `docs/reports/python-pro-judge-run-opus48.md` — this file.

**Not committed, out of scope (other agents' concurrent uncommitted state in
the shared worktree, confirmed via `git status` before staging):**
`configs/bouquet_judges.yaml` (modified — another agent's edits),
`scripts/bouquet_judge_rerun.py` (modified — another agent's edits),
`reports/bouquet/judges/deepseek-v4-flash/*` (modified/new — not mine),
`reports/bouquet/judges/gemini-3.1-pro/`, `reports/bouquet/judges/gpt-5.5/`
(new dirs — not mine), `reports/bouquet/judges/summary.md` (shared
cross-judge aggregate — regenerated locally as a side effect of this task's
own `stats` run since it now includes the `claude-opus-4.8` rows, but
deliberately left uncommitted since it also carries the other 3 judges'
content and is not this task's to commit).

## Open questions

- `reports/bouquet/judges/summary.md` was regenerated on disk by this
  task's `stats` step (now includes `claude-opus-4.8` alongside whatever the
  other agents had already contributed) but stays uncommitted per the
  "never touch their files" instruction — whoever commits last, or a
  dedicated aggregation step, should regenerate and commit the final
  4-judge combined version.
- The `frontier_default` regime sends `reasoning: {enabled: true}` to Opus
  4.8 every call; this is a confirmed no-op on this bridge (matches the
  2026-07-08 probe finding referenced in `configs/bouquet_judges.yaml`), so
  no further action was taken to "fight" it, per the task's explicit
  instruction.

## NOT done (explicit)

- Full 4-judge cross-comparison / aggregate report — depends on the other 3
  agents' runs finishing; out of this task's scope.
- No changes proposed or made to `scripts/bouquet_judge_rerun.py` or
  `configs/bouquet_judges.yaml` — the existing `frontier_default` regime and
  `enabled: true` gate needed no modification for this judge.
