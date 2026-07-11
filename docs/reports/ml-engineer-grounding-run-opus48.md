# Wiki-eval grounding run — claude-opus-4.8 — STATUS: CLOSED (Opus dropped by owner decision)

Task: run the NER+Wikidata grounding evaluation (wiki-eval harness) end-to-end
with `anthropic/claude-opus-4.8` as candidate (extractor + judge), 100-article
v2 corpus, sitelink rung off. Mid-task, the owner changed the routing
requirement to pin `provider-10` with high-effort reasoning and raised the
budget cap to $25. Smoke testing that change surfaced a blocking problem
(severe token padding on `provider-10` + reasoning not engaging on any route)
that trips the owner's own explicit gate ("if NO form engages reasoning on
provider-10 either, report back BEFORE starting the full run and wait for my
go"). A follow-up coordinator instruction asked for a full catalog-driven
provider sweep (all providers CloseRouter lists for this model, not just
`provider-10`) before escalating to the owner — done, see "Provider sweep"
below. Result: reasoning does not engage on **any** of the 7 providers this
model actually has, across both param forms and both temperature settings (8
direct reasoning attempts). Per the coordinator's own decision rule, this
means **STOP** — no route was adopted, the full run was not started. **The
full paid run has not started; no run directory exists yet.**

## Scope

- Ground the wiki-eval harness (`docs/stages/wiki-eval.md`, `scripts/wiki_eval.py` CLI).
- Add the run-time `use_sitelink=False` toggle the eval protocol requires
  (previously only available as a post-hoc offline replay, not a live-run
  setting).
- Smoke-test the CloseRouter route for `anthropic/claude-opus-4.8`: first
  `auto` (per original task), then `provider-10` pinned + reasoning params
  (per owner's mid-task correction) — verify no hidden prompt-token padding
  and whether reasoning engages.
- Launch the full 100-article background run, poll to completion, compute
  metrics, write this report, commit + push. **Not reached — paused at the
  smoke-test gate.**

## Files changed

- `scripts/wiki_eval.py` — added `--no-sitelink` CLI flag on the `run`
  subcommand. Threaded through `cmd_run` → `_run_one_config(..., use_sitelink=...)`
  → `_config_from_bits(bits, use_sitelink=...)`, which overrides the
  bit-derived `GroundingConfig.use_sitelink` via `dataclasses.replace` (the
  existing 3-bit `--config` id has no room for a 4th independent toggle).
  Applied toggles are self-evidenced in `meta.json`'s new
  `grounding_config: {use_lemma, use_cirrus, use_sitelink, match_aliases}`
  field (real-run counters dict), not just inferred from CLI args. Added
  `import dataclasses`. No signature change that breaks existing callers —
  `use_sitelink` defaults to `None` (no-op) everywhere.
- `docs/stages/wiki-eval.md` — doc-parity for the above: CLI usage block now
  lists `[--no-sitelink]`; the "G6 sitelink rung creates evaluation
  circularity" Subtleties bullet gained a paragraph describing the new flag,
  noting it supersedes the earlier model-comparison close-out's approach
  (run with the rung ON, then compute "clean" numbers via
  `scripts/sitelink_contamination.py`'s offline replay) for runs that opt
  into `--no-sitelink`.
- No run artifacts yet — `reports/terminology/wiki-eval/anthropic--claude-opus-4.8--*/`
  does not exist.
- Untouched (other agents' lanes, confirmed via `git status` before and after):
  `configs/bouquet_judges.yaml`, `reports/bouquet/judges/**`,
  `scripts/bouquet_judge_rerun.py`, `docs/reports/python-pro-*.md`.

## Provider sweep (catalog-driven, coordinator-requested)

**Method.** Before trial-pinning arbitrary provider IDs from project history,
queried CloseRouter's own `/providers` catalog endpoint (free GET,
`{OPENROUTER_BASE_URL}/providers`) for `anthropic/claude-opus-4.8` specifically.
It returns the **authoritative list of providers this model actually has**,
each with `pricing`, `success_rate_24h`, `available`, and
`supports_reasoning_effort` — this is a much stronger signal than blind
trial-pinning, and it immediately explains two things: (1) `auto` currently
resolves to `effective_provider: provider-4` (pricing $0.40/$0.40, matches the
task's stated catalog price and the 1857-token clean baseline exactly), and
(2) the model's `/models` entry lists `reasoning_effort` (flat top-level
string field) as a `supported_parameter` — the **correct** field name, not the
nested OpenRouter-style `reasoning: {effort: "high"}` I'd used in the earlier
`provider-10`-only smoke (both forms were tested here for completeness; both
gave identical null results).

Catalog contents for `anthropic/claude-opus-4.8` (7 providers total):

| Provider | catalog `supports_reasoning_effort` | catalog price in/M | catalog price out/M | catalog `success_rate_24h` |
|---|---|---|---|---|
| `auto` (→ `provider-4`) | No | $0.40 | $0.40 | 99.50% |
| `provider-2` | **Yes** | $0.95 | $0.95 | 84.43% |
| `provider-4` | No | $0.40 | $0.40 | 99.49% |
| `provider-5` | **Yes** | $2.25 | $11.25 | n/a (null — no recent traffic) |
| `provider-8` | **Yes** | $0.75 | $2.25 | 92.77% |
| `provider-9` | No | $1.275 | $4.95 | 99.77% |
| `provider-10` | **Yes** | $0.45 | $2.25 | 98.10% |

**Sweep design.** For every catalog-listed provider: 1 call with a realistic
extraction-shaped prompt (`DEFAULT_NER_PROMPT` + a real 67-word paragraph from
the v2 corpus cache — same prompt used in the earlier `provider-10` smoke, so
padding factors are directly comparable) + `reasoning_effort="high"` in
`extra_body`. If that gave `reasoning_tokens=0` **and** the catalog claimed
`supports_reasoning_effort=true`, one follow-up call with the native Anthropic
`thinking:{type:"enabled",budget_tokens:4000}` form. Two negative-control
calls on `provider-3`/`provider-6` (IDs seen in this project's history for
*other* models, e.g. `gpt-5.5`) to confirm they aren't valid routes for this
model. Round 2: for the two providers that returned a real result
(`provider-2`, `provider-10`), retried both param forms with `temperature`
**omitted** — `provider-2`'s first `thinking` attempt hit a genuine Anthropic
API error (`temperature is deprecated for this model`, 400), which is a real,
documented extended-thinking constraint (temperature must be unset/default
when thinking is enabled), not the "silent drop" quirk — so it needed a clean
retest without that confound. Also retried `provider-5`/`provider-8` once more
(transient-failure check) with `temperature` omitted.

**Full matrix** (17 calls total, ≈$0.025 estimated real spend at each
provider's own catalog price — well under the $0.50 cap; `cost_usd` was never
surfaced by CloseRouter for this model on any call, consistent with the
original task's smoke evidence, so costs below are computed from
`prompt_tokens`/`completion_tokens` × each provider's own catalog price, not a
generic fallback):

| Provider | Call | Result | prompt_tokens | padding factor (vs. 1858 baseline) | completion_tokens | reasoning_tokens | latency | est. cost |
|---|---|---|---|---|---|---|---|---|
| `auto` | `reasoning_effort=high`, temp=0 | OK | 1858 | **1.00x** | 175 | **0** | 6.16s | $0.00081 |
| `provider-2` | `reasoning_effort=high`, temp=0 | OK | 1859 | 1.00x | 391 | **0** | 7.69s | $0.00214 |
| `provider-2` | `thinking`, temp=0 | **400 error** (`temperature deprecated for this model`) | — | — | — | — | 1.26s | $0 (pre-generation reject) |
| `provider-2` | `reasoning_effort=high`, temp=None | OK | 1859 | 1.00x | 370 | **0** | 6.76s | $0.00212 |
| `provider-2` | `thinking`, temp=None | OK | 1859 | 1.00x | 175 | **0** | 7.05s | $0.00193 |
| `provider-4` | `reasoning_effort=high`, temp=0 | OK | 1858 | 1.00x | 175 | **0** | 3.73s | $0.00081 |
| `provider-5` | `reasoning_effort=high`, temp=0 | **400 error** (`up_bad_request`, upstream) | — | — | — | — | 3.29s | $0 |
| `provider-5` | `reasoning_effort=high`, temp=None (retry) | **400 error** (same) | — | — | — | — | 3.92s | $0 |
| `provider-8` | `reasoning_effort=high`, temp=0 | **503 no_available_provider** | — | — | — | — | 0.62s | $0 |
| `provider-8` | `reasoning_effort=high`, temp=None (retry) | **503 no_available_provider** | — | — | — | — | 0.56s | $0 |
| `provider-9` | `reasoning_effort=high`, temp=0 | **timeout (30s)** | — | — | — | — | 30.45s | $0 |
| `provider-10` | `reasoning_effort=high`, temp=0 | OK | 8766 | **4.72x** | 165 | **0** | 6.79s | $0.00432 |
| `provider-10` | `thinking`, temp=0 | OK | 8673 | 4.67x | 165 | **0** | 7.40s | $0.00427 |
| `provider-10` | `reasoning_effort=high`, temp=None | OK | 8809 | 4.74x | 165 | **0** | 9.30s | $0.00434 |
| `provider-10` | `thinking`, temp=None | OK | 8691 | 4.68x | 165 | **0** | 5.90s | $0.00428 |
| `provider-3` (negative control) | `reasoning_effort=high` | **503 no_available_provider** | — | — | — | — | 0.65s | $0 |
| `provider-6` (negative control) | `reasoning_effort=high` | **503 no_available_provider** | — | — | — | — | 0.55s | $0 |

**Verdicts:**

- **`auto`/`provider-4`** — clean (1.00x, matches the documented 1857-token
  baseline exactly), fast, no reasoning (catalog-predicted, confirmed).
- **`provider-2`** — clean tokens (1.00x, the only *other* clean route found),
  but reasoning **never engages** despite the catalog claiming
  `supports_reasoning_effort=true` — confirmed across both param forms and
  both temperature settings (4 attempts, all `reasoning_tokens=0`). Also
  materially more expensive ($0.95/M vs. $0.40/M) and its own catalog-reported
  `success_rate_24h` is the worst of the batch (84.4%). Completion tokens
  (165-391) do not scale up with a requested thinking budget of 4000 either,
  which is corroborating behavioral evidence — not just an unpopulated
  accounting field, the model demonstrably isn't spending extra generation
  budget on deliberation.
- **`provider-10`** — reconfirms the original finding: severely padded
  (4.67x-4.74x across 4 independent calls, both temperature settings, both
  param forms — reproducible, not a one-off), reasoning never engages either.
- **`provider-5`, `provider-8`, `provider-9`** — unusable right now
  regardless of the reasoning question: `provider-5` 400s on every attempt
  (matches its `null` 24h-success-rate — looks unused/broken in practice
  despite `available:true`), `provider-8` 503s "no available upstream" on
  every attempt (despite `available:true`/92.8% catalog success — flaky,
  consistent with `wiki_eval.py`'s own existing comment flagging `provider-8`
  as a route known to trip CloseRouter's circuit breaker), `provider-9` timed
  out (catalog says no reasoning support anyway, moot).
- **`provider-3`, `provider-6`** — confirmed **not valid routes for this
  model** (503 `no_available_provider`) — they served other models
  (`gpt-5.5`) in this project's history, not `claude-opus-4.8`; the catalog's
  absence of these two IDs from `anthropic/claude-opus-4.8`'s provider list
  was itself sufficient evidence, this was just a cheap confirmation.

**Conclusion: no provider — of the 7 CloseRouter actually lists for this
model — engages reasoning, in either param form, at either temperature
setting.** The catalog's own `supports_reasoning_effort=true` flag on
`provider-2`/`provider-5`/`provider-8`/`provider-10` does not correspond to
observed behavior for any of the two providers reachable enough to test it
(`provider-2`, `provider-10`); `provider-5`/`provider-8` couldn't be tested at
all (broken/unavailable). This is a disclosable catalog/bridge reliability gap
worth flagging for future CloseRouter model-comparison runs generally — do
not trust `supports_reasoning_effort` without an empirical check.

**Per the coordinator's decision rule ("if no provider engages reasoning:
STOP ... reply with the matrix — the owner will choose between
auto-without-thinking and dropping Opus"): stopping here.** No route was
adopted, the full run was not launched.

## Decisions & rationale

1. **`--no-sitelink` as a CLI override rather than changing `--config`'s
   bit semantics.** The stage doc already prescribes `use_cirrus=True,
   use_sitelink=False` as the correct eval-scoring config (Subtleties,
   2026-07-06) but no live-run mechanism existed to reach that state — the
   only precedent (gemini/deepseek close-out runs) computed "clean" numbers
   via a separate offline replay script against the ON-by-default run. This
   run needed the real thing at run time, so I added the minimal override
   rather than reusing the replay-script pattern, per the concrete
   documented need (not speculative).

2. **Followed the owner's mid-task provider/reasoning correction, then
   stopped at their own stated gate.** The owner's message set an explicit
   conditional halt: "if NO form engages reasoning on provider-10 either,
   report back BEFORE starting the full run and wait for my go." I ran the
   requested smoke tests (3 forms on `provider-10`: no reasoning param,
   OpenRouter-style `reasoning:{effort:"high"}`, native
   `thinking:{type:"enabled",budget_tokens:8000}`) and none produced
   `reasoning_tokens > 0`. That condition is met, so I stopped rather than
   spending the $25 budget on a run whose config premise (reasoning
   engagement) doesn't hold.

3. **Ran an apples-to-apples `provider-10` vs `auto` comparison on the
   identical prompt**, beyond what was strictly asked, because the raw
   numbers alone (`prompt_tokens≈8800`) were meaningless without a clean
   baseline. Using `auto`'s already-documented "1857 avg in / no padding"
   figure as ground truth, the same exact extraction-shaped prompt gave
   1858 tokens on `auto` and 8701-8883 on `provider-10` — a ~4.7x
   inflation. A near-empty prompt made the gap unambiguous: 23 tokens on
   `auto` vs 6489 on `provider-10` (~282x). This is the same reseller-padding
   failure class the stage doc already warns about for `auto` landing on a
   bad provider — except here the *explicitly requested pinned* route is
   the bad one, so I treated it as gating rather than "note and proceed."

4. **Also tested reasoning forms on `auto`** (2 extra cheap calls,
   ~$0.001) to determine whether the reasoning-drop is `provider-10`-specific
   or bridge-wide. Both forms gave `reasoning_tokens=0` on `auto` too — this
   confirms the original task's disclosed quirk ("the OpenAI-compat bridge
   silently drops reasoning params for Opus") is bridge-wide, not a
   `provider-10` artifact, which is directly useful for the owner's next
   decision (no alternate pinned route is likely to unlock it either).

5. **Flagged, but did not fix, the `PRICE_IN`/`PRICE_OUT` fallback
   mismatch.** `usage.cost_usd` was `None` on every tested call (both
   routes) — CloseRouter isn't surfacing real cost for this model/account.
   `BudgetGuard.settle()` falls back to `scripts/wiki_eval.py`'s hardcoded
   `PRICE_IN=0.15/M, PRICE_OUT=0.60/M` (gpt-4o-mini catalog prices) rather
   than Opus's real catalog price (0.40/0.40 per M, per the task brief) —
   this would undercount real spend on the input side by roughly 2.7x if
   left as-is for the real run. Not fixed yet because it's a small, targeted
   change I'd rather make once the route decision is final (so I don't
   touch the file twice) — flagged for the owner instead of silently
   patched, since "which price constant" depends on which model list this
   file should stay generic over (out of scope for me to redesign
   unilaterally, per "no speculative abstractions").

6. **No code committed.** Per Hard Invariant 5 / the task's own commit
   instruction ("commit ONLY your run dir + your report"), the `wiki_eval.py`/
   stage-doc changes stay uncommitted alongside the eventual run artifacts —
   committing now, before the run exists, would split one logical change
   across two commits for no benefit.

## Open questions (for the owner)

The routing question is now settled by the sweep (`auto`/`provider-4` is the
only clean *and* available route, and no route anywhere engages reasoning) —
what remains is genuinely the owner's call, not something I should resolve
unilaterally:

1. **`auto`-without-thinking, or drop Opus from this comparison entirely?**
   The coordinator's decision rule names exactly these two options. My read:
   `auto` is clean, cheap ($0.40/$0.40, matching the task's stated catalog
   price), fast, and 99.5% available — the only thing missing is reasoning,
   which the original task already scoped as "do not fight it; note it as
   the run's disclosed config" before the mid-task correction asked for high
   effort specifically. Nothing in the sweep suggests Opus itself is
   unreachable or broken — only that extended thinking isn't reachable via
   this particular gateway for this particular model right now.
2. Should I patch `PRICE_IN`/`PRICE_OUT` to Opus's real 0.40/0.40-per-M
   before the real run (affects `BudgetGuard`'s pre-call reservation
   accuracy and `meta.json`'s fallback-estimated spend, not the real
   `usage.cost_usd`-based settlement which stays accurate whenever the API
   does surface it — which it hasn't, for any provider tested, so this
   fallback price is what `meta.json`'s spend figures will actually rest on)?
3. Keep `--max-usd 25` even without reasoning (since reasoning was the
   stated reason for raising it from 15), or drop back to $15? At `auto`'s
   clean pricing the original $15 cap was already comfortable for the
   2644-extraction + ~5k-judge-call estimate.

## NOT done

- **The full 100-article paid run has not started.** No run directory
  exists under `reports/terminology/wiki-eval/anthropic--claude-opus-4.8--*/`.
- No `pred.jsonl`/`progress.jsonl`/`meta.json`/`metrics.json`/`report.html`
  produced.
- No background process launched, no polling, no resume-safety exercised.
- `PRICE_IN`/`PRICE_OUT` fallback pricing not corrected for Opus (flagged
  above, open question 2).
- Nothing committed or pushed — `scripts/wiki_eval.py` and
  `docs/stages/wiki-eval.md` changes sit uncommitted in the worktree.
- Headline metrics (R_doc/R_span/R_strict, P_mention/P_type), cost, and
  final article count are **not available** — nothing to report yet.
- Did not test provider IDs 1, 3, 6, 7, 11, 12 (seen as generic
  `provider-N` placeholders in other scripts' `DEFAULT_ROUTES` lists) —
  the catalog's `/providers` response for `anthropic/claude-opus-4.8`
  authoritatively lists only 6 upstream entries (`provider-2/4/5/8/9/10`)
  plus `auto`; the two tested as negative controls (`provider-3`,
  `provider-6`) confirmed the catalog is exhaustive (503
  `no_available_provider`), so the untested IDs were not probed live —
  treated as excluded by the catalog rather than "not gotten to."
- Did not vary `reasoning_effort` to `"medium"`/`"low"` or try smaller/larger
  `thinking.budget_tokens` values — `"high"`/`4000` was the coordinator's
  specified test condition and the null result was consistent and
  reproducible (8/8 direct reasoning attempts across both working providers,
  both param forms, both temperature settings), so further parameter
  variation didn't seem likely to change the conclusion and would have
  spent more of the sweep budget without new information.

## Closing

**Owner decision 2026-07-09: Opus dropped from Table C; auto-route remains
documented as the only clean route.** No full run happened. Raw provider-sweep
JSON archived for reproducibility at
[docs/experiments/2026-07-09-opus-provider-sweep/raw/](../experiments/2026-07-09-opus-provider-sweep/raw/).
The `--no-sitelink` CLI flag and its doc-parity edit remain in the codebase —
useful prep for the parallel GPT-5.5 grounding run, which needs the same
run-time sitelink-off toggle.
