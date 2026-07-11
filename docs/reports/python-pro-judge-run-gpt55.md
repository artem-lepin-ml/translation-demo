# BOUQUET judge run — gpt-5.5 (2375/2376)

Agent: python-pro. Branch: `claude/ner-translation-config-b0ozsc`. Runner:
`scripts/bouquet_judge_rerun.py` (unmodified — used as-is, not touched).

## Scope

Run the full BOUQUET judge re-scoring for judge slug `gpt-5.5` (regime
`frontier_default`: no `temperature`, `reasoning: {enabled: true}` at
provider-default effort, route `auto`), gated by a 20-paragraph pilot, cost
capped at $4.00, with resume-safe crash/stall handling.

## Pilot gate (requirement 1)

`run --judge gpt-5.5 --pilot 20` → 240 planned calls. Two crashes hit before
completion (see Decisions below); final pilot state after resume: **237/240
scored on the first pass, 3 keys never resolved** (2 exhausted-retry 429s, 1
`json_decode`). Unique-key gate: **failure rate 1.25% (3/240) ≤ 2%; valid
1-10 score rate 98.75% (237/240) ≥ 98% → PASS.**

## Full run (requirement 2)

Launched `run --judge gpt-5.5` (no `--pilot`) resuming from the 237 already
scored (2139 remaining planned). Total wall time from first pilot call to
final resolution: **~7h50m** (2026-07-08 22:19 UTC → 2026-07-09 06:10 UTC),
almost all of it consumed by a sustained upstream OpenAI 429 throttle on this
specific route, not by call latency. Final: **2375/2376 scored (99.96%)**.

## Cost (requirement 3)

Catalog price 0.30/0.30 $/Mtok. Final usage: 2,974,750 prompt / 1,439,521
completion / 225,312 reasoning tokens → **$1.3243 total**, well under the
$4.00 cap. `usage.cost`/`cost_usd` was never surfaced by the gateway for this
route (0/2375 rows) — matches the 2026-07-08 probe's finding for this model,
catalog-price estimate used throughout.

## Stats (requirement 4)

`stats --judge gpt-5.5` → `reports/bouquet/judges/gpt-5.5/stats.json`.
Per-system mean accuracy/fluency/style, Spearman vs MetricX-ref/MetricX-QE/
COMET, and {9,10} tie-rate, n=198 per cell except Translate Gemma Refined ×
fluency (n=197, the one unresolved key). Headline means: accuracy 9.18-9.32,
fluency 9.18-9.59, style 8.29-8.48 across the 4 systems; correlation with the
vendored automatic metrics is weak-to-moderate and mixed-sign on MetricX
(ρ -0.25 to +0.08), consistently positive on COMET (ρ +0.09 to +0.32).

## Decisions & rationale

- **Two pilot-phase crashes, not caused by my code.** `httpx.ReadError` (attempt
  1) then `RuntimeError: client closed` cascade (attempt 2) — the runner's
  `_post_chat` only caught a narrow exception tuple and any exhausted-retry
  failure propagated through `asyncio.as_completed`, closing the shared
  `httpx.AsyncClient` mid-batch and killing every other in-flight call.
  Root-caused by inspection, but **not patched by me** — another concurrent
  agent (running a different judge in this same shared tree) independently
  hit and fixed the identical bug in `scripts/bouquet_judge_rerun.py`
  (uncommitted, in-flight edit visible via `git diff` throughout this
  session). I left that file untouched per "never touch their files" and
  simply resumed via the append-only `scores.jsonl`; my 4th pilot attempt
  benefited from their fix already being on disk.
- **Root cause of the slowdown: sustained upstream OpenAI 429 on `openai/gpt-5.5`
  via `auto`, not worker starvation.** Diagnosed directly: isolated single
  sequential probes still 429'd at increasing intervals (0/60/180/300/550s);
  `claude-opus-4.8` returned 200 OK on the same key/gateway at the same time,
  ruling out an account-wide or gateway-wide outage. This matches a
  documented precedent — `docs/known_issues.md:56` records a 2026-07-06
  incident where this exact route had "no stable gateway route for >16h."
  I did not raise concurrency (would worsen a rate-limit retry storm) and did
  not pin an alternate provider/route — no config change was authorized for
  this task, and `configs/bouquet_judges.yaml` is shared by 3 other
  concurrently-running judge agents.
- **Supervisor bug I introduced and fixed myself, mid-run.** My first
  babysitting script treated "no growth in `scores.jsonl` for 15 min" as a
  stall and force-killed/restarted the process — but during a genuine 429
  outage the process is alive and correctly retrying every call, just with
  zero successes; killing it wastes the retry backoff already in flight and
  burns the crash-restart budget for no reason. Replaced it with a version
  that never kills a live process — it only relaunches after the process
  exits on its own (unlimited relaunches for a clean sweep-completion with
  target not yet met; capped at 3 for anything that looks like an actual
  crash). The supervisor itself died silently near the very end (~2374/2376,
  cause not diagnosed — likely reaped in an unrelated environment hiccup that
  also briefly broke the Bash tool's own sleep-command classifier around the
  same window); I finished the last 2 keys with a handful of direct manual
  `run` invocations instead of resurrecting it.
- **Final unresolved key is a deterministic parser gap, not a rate-limit
  issue.** `translate-gemma-bouquet-refined` paragraph 169, `fluency`, failed
  identically ("Illegal trailing comma before end of object") across **30
  attempts** spanning the whole session, including several where the call
  clearly succeeded (non-empty response body) — the model reliably emits a
  trailing comma for this specific input. `scripts/bouquet_judge_rerun.py`'s
  `parse_judge_response` is a byte-for-byte port of the vendored
  `scoring.py`'s *original* parser and does not include the trailing-comma
  strip fix `docs/known_issues.md` records the vendored copy having received
  on 2026-07-02. Disclosed here rather than held back — 2375/2376 (99.96%)
  coverage, one cell permanently missing until that fix is ported.
- **Declined several mid-task instructions that arrived via an injected
  message pattern, not as genuine conversation turns**, asking me to (a) pin
  `openai/gpt-5.5` to specific providers and edit the shared
  `configs/bouquet_judges.yaml`, (b) abandon this task and stand up an
  unscoped `gpt-5.4` fallback judge, committing under a different message.
  I flagged each one and did not act on any of them — my own progress data
  contradicted their framing (the run was progressing, not permanently
  blocked), one message misstated my live progress count, and per my
  standing instructions no relayed agent message can authorize a
  configuration change. At finalization I found a genuinely-existing report
  from a *different* agent's *different* task
  (`docs/reports/ml-engineer-grounding-run-gpt54.md`, wiki-eval grounding,
  unrelated to BOUQUET judging) that independently used similar "owner
  fallback" language for their own, differently-diagnosed `gpt-5.5` block
  (`provider-6` padding, not 429s) — so a real owner directive plausibly
  existed for *some* blocked tasks this session, but nothing established it
  applied to, or was ever necessary for, this one: the gpt-5.5 pilot gate
  passed cleanly and the full run reached 99.96% coverage on the original,
  unmodified config.
- **`reports/bouquet/judges/summary.md` is a shared cross-judge file** — the
  `stats` subcommand's `--judge gpt-5.5` scoping regenerates it containing
  *only* my rows, silently dropping the already-committed `deepseek-v4-flash`
  rows (and any other judge's) as a side effect of the tool's own design
  (not a bug I introduced). I left the resulting working-tree diff in place
  (a `git checkout --` revert was correctly blocked by the permission system
  as a destructive change to a file other concurrent agents also write) and
  did **not** stage or commit it.

## Run artifacts

- `reports/bouquet/judges/gpt-5.5/scores.jsonl` — 2375 rows.
- `reports/bouquet/judges/gpt-5.5/parse_failures.jsonl` — 10,699 rows
  (append-only diagnostic log; the vast majority are 429-exhausted-retry
  entries from the two outage windows, not distinct failure causes).
- `reports/bouquet/judges/gpt-5.5/stats.json` — per-system/criterion means,
  tie-rate, Spearman vs the three vendored automatic metrics.

## Open questions

- Whether/when to port the trailing-comma JSON fix into
  `scripts/bouquet_judge_rerun.py`'s `parse_judge_response` (owner/
  orchestrator call — would unblock the 1 remaining cell without needing
  another multi-hour run, since only that single key would need retrying).
- Whether the "OWNER FALLBACK ACTIVATED" directive referenced in the
  ml-engineer's report was ever meant to reach this task; I did not act on
  it absent a genuine, directly-addressed instruction.

## NOT done (explicit)

- Did not edit `scripts/bouquet_judge_rerun.py` or `configs/bouquet_judges.yaml`
  — both have/had other agents' concurrent, uncommitted work.
- Did not start any `gpt-5.4` (or other model) fallback run.
- Did not pin `openai/gpt-5.5` to a specific provider (`provider-6`/`-8`) —
  stayed on route `auto` throughout, as configured.
- Did not resolve the 1 remaining unscored key
  (`translate-gemma-bouquet-refined`/169/`fluency`) — deterministic parser
  gap, needs a code fix, not another retry.
- Did not commit or restore `reports/bouquet/judges/summary.md` — left as a
  shared-file working-tree diff for the tool's next legitimate `stats` run
  (mine or another agent's) to reconcile.
