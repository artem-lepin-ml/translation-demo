# BOUQUET judge run — deepseek-v4-flash

**STATUS: RUN PARKED — provider outage, resumable.** Not the final report.
`deepseek/deepseek-v4-flash` has no available upstream provider on the
CloseRouter gateway (`503 no_available_provider`) as of this writing, with a
brief inconsistent flicker (mixed 503/400) that did not stabilize. This is
confirmed model-specific, not a gateway-wide outage — the 3 other judges
running in parallel in this same shared worktree (`gpt-5.5`,
`claude-opus-4.8`, `gemini-3.1-flash-lite`) all progressed normally over the
same window (`claude-opus-4.8` and `gemini-3.1-flash-lite` both reached
2376/2376 and are already committed on this branch). Not a payload/config
bug on my side either — verified with 5 direct-HTTP variants (old
`max_tokens=4096`, no `reasoning` key, no `response_format`, a different
criterion, a different paragraph) that all returned the same 503 once the
outage resumed.

**Resume command** (skips the 19 already-scored rows automatically via the
runner's resume-by-existing-keys logic):

```
.venv/bin/python3 scripts/bouquet_judge_rerun.py run --judge deepseek-v4-flash --pilot 20 --concurrency 6
```

Then continue exactly as originally planned: pilot gate check (≤2% parse
failures, ≥98% valid scores across the 240-call pilot) → full run (no
`--pilot`, background + poll) → `stats` → update this report with final
numbers → commit `feat(eval): BOUQUET judge run — deepseek-v4-flash (2376
calls)`.

Written by the `python-pro` agent on branch `claude/ner-translation-config-b0ozsc`
(shared worktree — 3 other agents run other judges in parallel in the same
tree; this run touches only its own paths).

## Scope

Original task: run the full BOUQUET judge re-scoring for slug
`deepseek-v4-flash` (`scripts/bouquet_judge_rerun.py`, `configs/bouquet_judges.yaml`) —
pilot gate → full 2376-call run → stats → report → commit. Mid-task, a
coordinator status-check (branch not blocked while parked) asked for this
interim commit; the underlying provider outage is real and independently
confirmed (see below), so parking is the correct response rather than
continuing to burn poll cycles against a dead route.

## Reasoning-suppression experiment (done first, before the pilot gate)

Config sends `reasoning: {enabled: false}` (regime `t0_no_reasoning`), but
the existing 15 validation rows already showed 45-89% of completion tokens
went to reasoning anyway (from the 2026-07-08 probe). Tested whether
suppression is achievable at all, using 4 direct-HTTP calls (real BOUQUET
paragraphs, outside the runner, before touching any config):

| # | Form tested | Paragraph/criterion | Result |
|---|---|---|---|
| 1 | `reasoning` key omitted entirely | accuracy, id=72 | 200 OK, JSON valid, reasoning_tokens=2258/2707 (83.4%) |
| 2 | `reasoning` key omitted entirely | fluency, id=178 | 200 OK, JSON valid, reasoning_tokens=335/637 (52.6%) |
| 3 | `reasoning` key omitted entirely | style, id=10 | 200 OK, hit `max_tokens=4096` cap, reasoning_tokens=4096/4096 (100%) — **JSON parse FAILED** (reasoning consumed the entire budget, no room for the answer) |
| 4 | `reasoning: {"effort": "none"}` (alternative form) | accuracy, id=72 | 200 OK, JSON valid, reasoning_tokens=1984/2467 (80.4%) |

**Outcome: nothing suppresses it.** Every form tested (explicit `false`,
omitted entirely, `effort="none"`) reasons at 45-100% of completion tokens.
This independently confirms an owner decision that had already landed in the
repo by the time I got here (`docs/paper/paper-state.md` "Table A protocol",
commit `ef98e33`, and a mid-task coordinator message): **lock reasoning ON**
for this judge — stop pretending it's off (`reasoning: {enabled: false}`
silently no-ops) and configure honestly. Case #3 above also surfaced a
concrete, previously-undocumented risk: at the old `max_tokens=4096`, a
verbose-reasoning response can consume the entire budget and leave zero room
for the actual JSON answer — a parse failure driven by truncation, not by
the model's answer quality. Fixed by raising `max_tokens` to 8192 (see
below); confirmed fixed by a 3-call smoke run through the actual runner
(`qwen-27b-bouquet`, id=0, all 3 criteria) — 0 parse failures, reasoning
present (83-88% of completion tokens), JSON valid every time.

## Pilot gate: BLOCKED by provider outage, not evaluated

`--pilot 20` (240 calls, 18-19 already scored from prior validation + smoke
→ ~221-222 planned). Three attempts:

1. **First attempt**: crashed after 1 successful call — unhandled
   `httpx.ReadError` (see Files changed below). 19/240 rows on disk at the
   time.
2. **Second attempt** (after the `ReadError` fix): crashed again — this time
   an unhandled `JudgeCallError` (genuine `HTTP 400`) killed the whole
   221-call batch, discarding all in-flight work. Root-caused to a second,
   deeper gap: no exception boundary around the per-call coroutine at all
   (see Files changed below).
3. **Third attempt** (after both fixes): completed cleanly without crashing
   — but **0/221 scored, 221/221 failed**, all `HTTP 503
   no_available_provider`. Confirmed via a standalone probe (trivial
   payload, bypassing the runner) that the provider was down, independent of
   my code/config.

Then: ~55 minutes of outage (first direct observation ~22:24, confirmed
recovery 23:18:49), followed by a brief, apparently partial recovery — one
probe call and a resumed pilot batch initially returned `200`, but the very
next full pilot invocation immediately produced a *mixed* 375×`503` +
67×`400` failure set (out of the cumulative 442 failure rows now on disk),
and a direct retry of one of the 400-failing requests (3 attempts, identical
payload) reproduced the same 400 three times in a row — looked at first
like a real payload bug. Ruled that out with 5 additional direct-HTTP
variants (old `max_tokens=4096`, no `reasoning` key at all, no
`response_format`, `accuracy` instead of `style`, a different paragraph id)
— **all 5 came back `503` again**, i.e. the underlying route capacity had
gone from "flickering" to "fully down" again in the few minutes between
tests. This is consistent with a single degraded/flapping upstream
provider slot (`route_candidate_counts: resolved_models=2,
filtered_endpoint_rows=0` in every error body) rather than anything in the
request. **Gate not evaluated** — cannot compute a meaningful parse-failure
rate against an unavailable route; will re-run cleanly once the provider is
back.

## Files changed

- `scripts/bouquet_judge_rerun.py`:
  - Added regime `t0_reasoning_on` (`_REGIMES` tuple + a new `elif` branch in
    `build_payload()`): `temperature=0` + explicit `reasoning: {enabled:
    true}`. Purely additive — does not touch `t0_no_reasoning` /
    `frontier_default` (used by the other 3 judges) or the concurrently-added
    `vendor_default` regime (another agent's in-flight edit to this same
    shared file, verified non-overlapping).
  - Widened `_post_chat`'s retryable-exception tuple from
    `(ConnectError, ConnectTimeout, ReadTimeout, TimeoutException)` to the
    base class `httpx.TransportError` (a strict superset — same 4 plus
    `ReadError`/`WriteError`/`RemoteProtocolError`/etc.). The narrower tuple
    missed `httpx.ReadError`, which crashed a live pilot run mid-flight (bug,
    not intentional design — the module's own docstring already says
    "transient errors only: timeout / connection drop / 429 / 5xx", and a
    read-error genuinely is a connection drop).
  - Wrapped the per-call coroutine (`_one()`'s call into
    `score_one_criterion`) in a `try/except (TransientHTTPError,
    JudgeCallError)`, converting an HTTP-level failure into a logged
    `parse_failures.jsonl` row (reason `http_error: ...`) instead of letting
    it propagate through `asyncio.as_completed` and crash the entire
    concurrent batch. This was the deeper of the two crash bugs found live:
    a single non-retryable 4xx (or a transient error that exhausts all 3
    retries) previously took down every other in-flight/pending call in the
    same `run` invocation, not just the failing one.
  - Both fixes are backward-compatible / behavior-preserving for
    successfully-completing calls (verified: `build_payload()` output for
    `frontier_default`/`t0_no_reasoning` unchanged; syntax-checked
    (`ast.parse`) after every edit; re-verified against the shared file after
    two other agents' concurrent edits landed on top).
- `configs/bouquet_judges.yaml` — `deepseek-v4-flash` entry: `regime:
  t0_reasoning_on` (was `t0_no_reasoning`), `max_tokens: 8192` (was 4096,
  raised after the case #3 truncation-driven parse failure above). Header
  comment block updated to document the superseded regime and point at this
  report.
- `reports/bouquet/judges/deepseek-v4-flash/scores.jsonl` — 19 rows (append-only,
  0 deleted/overwritten): 15 pre-existing validation rows (`t0_no_reasoning`,
  `translate-gemma-bouquet` ids 0-4) + 4 new rows from the `t0_reasoning_on`
  smoke test (`qwen-27b-bouquet` id=0, all 3 criteria, plus 1 row from the
  brief provider-flicker window).
- `reports/bouquet/judges/deepseek-v4-flash/parse_failures.jsonl` — new file,
  442 rows, all from the outage window (375× `503 no_available_provider`,
  67× `400 invalid_request` from the brief flicker). Diagnostic only — none
  of these represent a real judge-response parse failure; absence from
  `scores.jsonl` is what drives the resume, so all 442 will be retried
  automatically once the provider is healthy.

**Multi-agent shared-worktree note**: `configs/bouquet_judges.yaml` and
`scripts/bouquet_judge_rerun.py` are edited concurrently by up to 3 other
agents in this same tree. Rather than `git add` the whole file (which would
sweep in their in-progress, not-yet-final edits — e.g. a `gemini-3.1-flash-lite-think`
config block and a `vendor_default` regime, both mid-flight and not authored
by this task), this commit stages **only my own hunks** via a hand-built,
`git apply --cached --check`-verified patch, re-derived against the current
`HEAD` immediately before staging (the shared branch moved twice from other
agents' commits while this task was running; re-verified both times that
their commits did not touch the `deepseek-v4-flash` block before rebuilding
the isolated patch).

## Decisions & rationale

**Why fix the runner instead of only restarting on crash.** The task's own
resilience plan ("on stall or crash, restart, max 3, then stop") already
anticipates failures, and a 3-restart budget is not generous for a
multi-hour run against a moderately flaky gateway. The `httpx.ReadError` gap
and the whole-batch-crash-on-single-4xx gap are both narrow, additive,
low-risk fixes (a strict-superset exception class, and a try/except that
reuses the existing `JudgeParseError`/`parse_failures.jsonl` recording path
verbatim) that directly serve "see it through to completion" — without them,
a single flaky call late in a 2376-call run would discard everything not yet
flushed and force a full restart from the resume point anyway, at a much
higher token/time cost than the fix itself.

**Why raise `max_tokens` to 8192 instead of leaving it at 4096.** Direct
evidence (case #3 in the reasoning-suppression experiment) that the old
budget was insufficient once reasoning is genuinely unleashed: a real
production-shaped call hit the cap with 100% reasoning share and produced no
parseable answer at all. 8192 matches the frontier judges' existing budget.
Cost impact checked before committing to it: the 3-call `t0_reasoning_on`
smoke averaged ~1510 prompt / ~4174 completion tokens/call → ≈$0.00069/call
→ ≈$1.6 projected for the full 2376-call run, comfortably under the $4.00
cap even allowing for variance.

**Why park instead of continuing to poll aggressively.** The provider outage
is confirmed model-specific (other judges in this same session are healthy)
and was still active after ~55+ minutes of direct observation with a
misleading brief flicker in between. Parking with the runner
hardening/config already committed means the branch isn't blocked on this
judge while the outage resolves, and the 19 real scored rows +
diagnostic failure log are preserved (append-only) rather than sitting
uncommitted and at risk in a shared worktree for an unknown number of
further hours.

## Open questions

- Is the deepseek-v4-flash route's flakiness (503 outage + a brief
  405/mixed-error flicker) a known, recurring CloseRouter issue for this
  specific model, or a one-off? Worth checking `docs/known_issues.md` /
  asking the gateway operator if it recurs on the eventual full run.
- Should the widened `httpx.TransportError` retry-catch and the
  whole-batch-crash fix in `_one()` be treated as a general reliability fix
  worth flagging to the other 3 agents' judge runs (they use the same shared
  script and could hit the same `ReadError`/4xx-crash pattern), or left as
  this task's own scoped finding? Not proactively communicated to the other
  agents (no inter-agent messaging channel in this setup) — they will pick
  up the fix automatically only if/when they next restart their own `run`
  invocation.

## NOT done (explicit)

- **Pilot gate not evaluated** — blocked by the provider outage described
  above. No pass/fail verdict yet.
- **Full run not started** — depends on the pilot gate passing first.
- **`stats` subcommand not run** — no `stats.json` for `deepseek-v4-flash`
  yet; `reports/bouquet/judges/summary.md` currently reflects only the other
  3 judges (regenerated by another agent's `stats` run) and is intentionally
  left untouched/uncommitted by this task.
- **Final cost not known** — only $0.0073 spent so far (19 real scored
  rows' worth of usage, catalog-estimated since the gateway surfaces no
  `cost`/`cost_usd` for this model).
- **Final commit (`feat(eval): BOUQUET judge run — deepseek-v4-flash (2376
  calls)`) not made** — this park commit is an interim checkpoint, not the
  task's completion.
- Continuing to poll for provider recovery (every 5-10 min per the
  coordinator's guidance, not 90s) after this park commit lands.
