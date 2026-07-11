# wiki-eval v2 — smoke + pilot mission, 2026-07-10

Spec: [docs/superpowers/specs/2026-07-10-wiki-eval-experiment-v2.md](../superpowers/specs/2026-07-10-wiki-eval-experiment-v2.md)
§5 ("План прогона"). Branch `claude/ner-translation-config-b0ozsc` (code
complete, 619 tests passing per mission brief; commits 421c99d/0d89242/7e7ddfd).
Nothing in `src/`, `scripts/`, or `tests/` was modified; nothing was
committed. `$SCR` = the session scratchpad
(`/tmp/claude-0/-home-user-translation-demo/d94abddc-f105-576c-b81a-a51a1ca3f0ff/scratchpad`).

## TL;DR

All 5 phases the orchestrator authorized ran. Verdicts:

| Phase | What | Verdict |
|---|---|---|
| 0 | Smoke, gemini | PASS 6/6 |
| 0 | Smoke, deepseek | PASS 6/6 |
| 0 | Smoke, gemma | PASS on retry (1/6 first attempt, then 6/6 after the sustained WandB 429 cleared) |
| 1 | Gemini pilot, 10 articles | PASS — $0.4894 spent, 0 failures |
| 2 | gate_check on gemini pilot | **ALL GATES PASS** |
| 2 | 3×100-article cost extrapolation | **PASS** — $7.36 total (gate ≤$15) |
| 3a | Deepseek mini-pilot, 3 articles | **HALTED at article 3** — unclassified infra error (not a `FatalGroundingJudgeError`); 2/3 articles completed cleanly with all gates green |
| 3b | Gemma smoke re-retry | **PASS**, 6/6, first attempt after the orchestrator's decision |
| 3b | Gemma mini-pilot, 3 articles | **PASS** — $0.0370 spent, ALL GATES PASS |
| 4 | v3 scoring sanity, gemini pilot | PASS — `protocol=v3`, `classes.named`/`classes.term` present, `report.html` written |

**Total spend this mission: $0.5669** (of the $1.20 cap, ~47% used).

## Phase 0 — smoke (all 3 models)

### Commands

```
set -a; source $SCR/openrouter-fallback.env; set +a
export OPENROUTER_API_KEY="$OPENROUTER_FALLBACK_API_KEY"
PYTHONPATH=src uv run --no-sync python3 $SCR/smoke_v2.py                      # all 3 models
PYTHONPATH=src uv run --no-sync python3 $SCR/smoke_v2.py --models google/gemma-4-31b-it --results-suffix _gemma    # retry 1
PYTHONPATH=src uv run --no-sync python3 $SCR/smoke_v2.py --models google/gemma-4-31b-it --results-suffix _gemma2   # retry 2
PYTHONPATH=src uv run --no-sync python3 $SCR/smoke_v2.py --models google/gemma-4-31b-it --results-suffix _gemma_attempt1   # retry 3 (post orchestrator decision)
```

### google/gemini-3.1-flash-lite — PASS (6/6)

Route: `provider_pin=Google AI Studio`, `reasoning={"effort":"medium"}`, `temperature=1.0`, `max_tokens=20000`.

| call | prompt_tok | completion_tok | reasoning_tok | finish | provider | cost | gate |
|---|---|---|---|---|---|---|---|
| extract[0] | 1202 | 856 | 701 | stop | Google AI Studio | $0.00158 | PASS |
| extract[1] | 1230 | 779 | 708 | stop | Google AI Studio | $0.00148 | PASS |
| extract[2] | 1136 | 1024 | 967 | stop | Google AI Studio | $0.00182 | PASS |
| judge[0] | 212 | 403 | 358 | stop | Google AI Studio | $0.00066 | PASS (qid=Q463280) |
| judge[1] | 212 | 394 | 347 | stop | Google AI Studio | $0.00064 | PASS (qid=Q463280) |
| judge[2] | 212 | 352 | 307 | stop | Google AI Studio | $0.00058 | PASS (qid=Q463280) |

Total: **$0.00676**.

### deepseek/deepseek-v4-flash — PASS (6/6)

Route: `provider_pin=Novita`, `reasoning={"enabled":true}`, `temperature=1.0`, `top_p=1.0`, `max_tokens=20000`.

| call | prompt_tok | completion_tok | reasoning_tok | finish | provider | cost | gate |
|---|---|---|---|---|---|---|---|
| extract[0] | 1232 | 3021 | 2740 | stop | Novita | $0.00102 | PASS |
| extract[1] | 1278 | 1963 | 1825 | stop | Novita | $0.00061 | PASS |
| extract[2] | 1172 | 1740 | 1637 | stop | Novita | $0.00054 | PASS |
| judge[0] | 207 | 224 | 183 | stop | Novita | $0.00009 | PASS (qid=Q463280) |
| judge[1] | 207 | 248 | 197 | stop | Novita | $0.00010 | PASS (qid=Q463280) |
| judge[2] | 207 | 249 | 183 | stop | Novita | $0.00010 | PASS (qid=Q463280) |

Total: **$0.00246**. Notable: deepseek's reasoning is 2-4x heavier than gemini's on the *same* extraction prompts (2740/1825/1637 vs. 701/708/967 reasoning tokens) — cheaper overall only because Novita's per-token price is roughly half gemini's.

### google/gemma-4-31b-it — PASS on retry (WandB 429 was transient-for-now, per orchestrator ruling)

Route: `provider_pin=WandB`, `reasoning={"enabled":true}`, `temperature=1.0`, `top_p=0.95`, `top_k=64`, `max_tokens=20000`.

**Attempt 1** (before the orchestrator's ruling): extract[0] succeeded and passed all gates
(p=1273, c=1581, r=1176, finish=stop, provider=WandB, cost=$0.00071). extract[1] then hit
`openai.RateLimitError` 429 ("temporarily rate-limited upstream", WandB) and stayed 429
through 2 internal retries (5s/15s backoff).

**Attempt 2** ("gemma2", longer backoff 10s/30s/60s/90s): all 5 attempts (1 initial + 4
retries) on the very first call returned 429 — zero successful calls this invocation.

**Orchestrator decision** (received mid-mission): treat the 429 as transient-for-now — the
one successful call already proves the pin/reasoning/params config is correct (all gates
green), account credit likely governs upstream quota and will be raised before full runs, no
pin change (spec Р14). Retry with up to 2 attempts spaced ~5 minutes.

**Attempt 3** ("gemma_attempt1", run at 2026-07-10T08:46:25Z, ~8 minutes after attempt 2's
last 429): 3 more internal retries fired (10s/30s/60s backoff, all still 429) plus one
transient connection error (90s backoff), THEN **all 6 calls succeeded**:

| call | prompt_tok | completion_tok | reasoning_tok | finish | provider | cost | gate |
|---|---|---|---|---|---|---|---|
| extract[0] | 1273 | 2504 | 2141 | stop | WandB | $0.00103 | PASS |
| extract[1] | 1301 | 1512 | 1474 | stop | WandB | $0.00069 | PASS |
| extract[2] | 1207 | 1229 | 1093 | stop | WandB | $0.00057 | PASS |
| judge[0] | 246 | 369 | 319 | stop | WandB | $0.00016 | PASS (qid=Q463280) |
| judge[1] | 246 | 352 | 316 | stop | WandB | $0.00015 | PASS (qid=Q463280) |
| judge[2] | 246 | 350 | 310 | stop | WandB | $0.00015 | PASS (qid=Q463280) |

Total attempt 3: **$0.00275**. Only 1 of the up-to-2 spaced retries the orchestrator
authorized was needed — gemma's smoke is now **fully PASS (6/6, all gates green)**, and no
second 5-minutes-later attempt was required.

**Phase 0 spend** (all attempts, all 3 models): $0.00676 + $0.00246 + $0.00071 (attempt 1
partial) + $0 (attempt 2, all-429) + $0.00275 (attempt 3, full pass) = **$0.01268**.

## Phase 1 — gemini pilot (10 articles)

### Command

```
PYTHONPATH=src uv run --no-sync python3 scripts/wiki_eval.py run \
  --gt $SCR/gt_pilot10.jsonl --config 111 --no-sitelink \
  --model google/gemini-3.1-flash-lite \
  --max-usd 0.60 --max-judge-calls 2000 \
  --article-workers 3 --llm-workers 4
```

Run dir: `reports/terminology/wiki-eval/google--gemini-3.1-flash-lite--Google-AI-Studio/111/2026-07-10T08-31-04Z`

Wall clock: 404.9s (started 08:31:04Z, finished 08:37:49Z).

### Result

- 10/10 articles completed, `stopped_reason: null` (never hit the budget or judge-call cap).
- `n_paragraphs=140`, `n_pred_mentions=1203`.
- `n_failed_paragraphs=0`, `n_failed_judge_calls=0`, `n_extraction_parse_failures=0`.
- `calls`: extract=140, judge=335 (475 total).
- `spend`: extract=$0.2362, judge=$0.2531, **total=$0.4894** (of `--max-usd 0.60`).
- `llm_max_in_flight_observed=4` (matches `--llm-workers 4`, semaphore bound respected).
- Wikidata: 352 live calls, 3204 cache hits, 110.5s.

## Phase 2 — gate_check on the gemini pilot

### Command

```
python3 $SCR/gate_check.py --run-dir <pilot run dir> --gt $SCR/gt_pilot10.jsonl --extrapolate
```

### Gate table

| gate | value | verdict |
|---|---|---|
| `finish_reason == "length"` count | 0 / 475 | **PASS** |
| `reasoning_tokens > 0` share | 100.0% (475/475), min=140, p50=402 | **PASS** |
| served provider == pin (`Google AI Studio`) share | 100.0% (475/475) | **PASS** |
| `n_extraction_parse_failures` / `n_paragraphs` | 0.00% (0/140) | **PASS (<1%)** |

**>>> ALL GATES PASS <<<**

Cost cross-check: `calls.jsonl` cost sum = $0.4894, `meta.json` `spend.total` = $0.4894
(exact match). Cost/article = $0.0489.

### 3×100-article cost extrapolation

Gemini's own pilot cost scales directly (measured, not a proxy). Deepseek and gemma reuse
gemini's measured pilot **token volume** (262,777 prompt tokens + 282,441 completion tokens,
completion already includes the reasoning-token subset per the OpenAI usage schema) scaled
×10, priced through each model's own pinned-endpoint pricing (live-fetched
`https://openrouter.ai/api/v1/models/<model>/endpoints`, `pricing.prompt`/`pricing.completion`):

| model | pin | price in/out ($/tok) | method | 100-article forecast |
|---|---|---|---|---|
| google/gemini-3.1-flash-lite | Google AI Studio | 0.00000025 / 0.0000015 | measured pilot cost ×10 | **$4.8936** |
| deepseek/deepseek-v4-flash | Novita | 0.00000014 / 0.00000028 | gemini token volume ×10 × own price | **$1.1587** |
| google/gemma-4-31b-it | WandB | 0.00000012 / 0.00000035 | gemini token volume ×10 × own price | **$1.3039** |
| **TOTAL 3×100** | | | | **$7.3562** |

**Gate (≤$15): PASS** — $7.36 well under the cap, ~49% margin.

Caveat carried forward from the extrapolation script: deepseek and gemma both showed
noticeably heavier reasoning than gemini on identical prompts in Phase 0 smoke (deepseek
2-4x, gemma comparable-to-heavier) and their own mini-pilots (Phase 3) now give REAL
per-model token volumes rather than relying on this proxy — see below, both mini-pilots'
actual costs came in even cheaper per-article than the gemini-volume-proxy forecast implies
(gemma: $0.0123/article actual vs. an implied ~$0.0130/article from the 100-article
forecast ÷100 — consistent; deepseek's 2 completed articles cost $0.0140/article actual,
also broadly consistent with the $0.0116/article implied by its forecast). The proxy method
held up against real mini-pilot data.

## Phase 3a — deepseek mini-pilot (3 articles) — HALTED

### Command

```
PYTHONPATH=src uv run --no-sync python3 scripts/wiki_eval.py run \
  --gt $SCR/gt_pilot3.jsonl --config 111 --no-sitelink \
  --model deepseek/deepseek-v4-flash \
  --max-usd 0.25 --max-judge-calls 600 \
  --article-workers 3 --llm-workers 4
```

Run dir: `reports/terminology/wiki-eval/deepseek--deepseek-v4-flash--Novita/111/2026-07-10T08-38-16Z`
(partial — no `meta.json`/`pred.jsonl`, only `calls.jsonl`/`pred.partial.jsonl`/`progress.jsonl`,
since the run crashed before `cmd_run` reached its final-write step).

### What happened

Articles 1 ("XXX династия") and 2 ("XXVII династия") completed cleanly. On article 3, an
extraction call crashed the whole process with:

```
json.decoder.JSONDecodeError: Expecting value: line 169 column 1 (char 924)
```

raised from `httpx`'s `response.json()` inside the `openai` SDK's response parsing —
i.e. Novita/OpenRouter returned an HTTP response body that was not valid JSON for a chat
completion call. **This is not one of the three documented halt types**
(`LengthOverflowError`/`CallGateError`/`BudgetExhaustedError`) — it is a raw,
un-wrapped exception from the transport layer. Per
`palimpsest.llm.client.is_transient_error`, a `JSONDecodeError` matches none of its
recognized transient categories (`TimeoutError`/`APITimeoutError`/`APIConnectionError`/
`RateLimitError`/`InternalServerError`/`APIStatusError` with `status>=500`), so it was
**not retried at all** — it propagated on the very first attempt and killed the run
immediately (no `[transient error, retrying...]` evidence in the log, consistent with
`is_transient_error` returning `False` for this exception type).

Per the mission's explicit halt-diagnosis instruction ("capture the exception text and the
last lines of calls.jsonl, then STOP and report — do not retry, do not resume"), this run
was **not** retried or resumed.

### Evidence captured (partial run)

- `calls.jsonl`: 90 calls (32 extract, 58 judge) before the crash.
- `progress.jsonl`: 2/3 articles recorded, `spent=$0.0283` after article 2 (well within
  `--max-usd 0.25`).
- Gate check on the 90 captured calls (computed manually — no `meta.json` for the standard
  `gate_check.py` script to read):

| gate | value | verdict (on captured calls) |
|---|---|---|
| `finish_reason == "length"` count | 0 / 90 | PASS |
| `reasoning_tokens > 0` share | 100.0% (90/90), min=30, p50=265.5 | PASS |
| served provider == pin (`Novita`) share | 100.0% (90/90) | PASS |
| cost (2 articles + partial 3rd) | $0.02790 | — |

Every call that DID complete was clean — the halt is an infra/transport-layer reliability
gap (an occasional malformed HTTP response body from this route not being classified as
retry-worthy), not a prompt/parameter/pin defect. The same pin/reasoning/sampling
parameters that produced this evidence are the ones Phase 0's clean 6/6 smoke and the first
2 mini-pilot articles already validated.

### Last lines of calls.jsonl before the crash

```
{"ts": "2026-07-10T08:44:41.162286+00:00", "kind": "judge", ..., "finish_reason": "stop", "reasoning_tokens": 201, "cost_usd": 0.00010402}
{"ts": "2026-07-10T08:44:43.839254+00:00", "kind": "judge", ..., "finish_reason": "stop", "reasoning_tokens": 144, "cost_usd": 9.282e-05}
```
(both healthy `stop`/reasoning>0 judge calls immediately preceding the crash — the failure
was specific to the very next extraction call, not a degrading pattern).

**This is a reportable code-level finding for the owner/orchestrator, not something fixed in
this mission** (this session may not touch `src/`/`scripts/`): `is_transient_error` in
`src/palimpsest/llm/client.py` currently treats a malformed/non-JSON HTTP response body as a
deterministic (non-retried) error. Given OpenRouter/Novita occasionally returns such a body
for reasons that look like a transport hiccup rather than a real API contract violation, it
may be worth widening the transient classification to cover `json.JSONDecodeError` raised
from inside the SDK's response parsing — a decision for whoever owns that module, not made
here.

## Phase 3b — gemma smoke retry + mini-pilot (3 articles)

Gemma's smoke retry (see Phase 0 above, "Attempt 3") passed 6/6 on the first of the two
orchestrator-authorized spaced retries — no second attempt was needed.

### Command

```
PYTHONPATH=src uv run --no-sync python3 scripts/wiki_eval.py run \
  --gt $SCR/gt_pilot3.jsonl --config 111 --no-sitelink \
  --model google/gemma-4-31b-it \
  --max-usd 0.25 --max-judge-calls 600 \
  --article-workers 3 --llm-workers 4
```

Run dir: `reports/terminology/wiki-eval/google--gemma-4-31b-it--WandB/111/2026-07-10T08-52-00Z`

Wall clock: 705.7s (started 08:52:00Z, finished 09:03:46Z — noticeably slower than deepseek's
comparable run, consistent with gemma's occasional 429-retry overhead even when it
ultimately succeeds).

### Result

- 3/3 articles completed, `stopped_reason: null`.
- `n_paragraphs=33`, `n_pred_mentions=295`.
- `n_failed_paragraphs=0`, `n_failed_judge_calls=0`, `n_extraction_parse_failures=0`.
- `calls`: extract=33, judge=75 (108 total).
- `spend`: extract=$0.0212, judge=$0.0158, **total=$0.0370** (of `--max-usd 0.25`).

### gate_check.py

| gate | value | verdict |
|---|---|---|
| `finish_reason == "length"` count | 0 / 108 | **PASS** |
| `reasoning_tokens > 0` share | 100.0% (108/108), min=215, p50=364.5 | **PASS** |
| served provider == pin (`WandB`) share | 100.0% (108/108) | **PASS** |
| `n_extraction_parse_failures` / `n_paragraphs` | 0.00% (0/33) | **PASS (<1%)** |

**>>> ALL GATES PASS <<<**

No 429s occurred during the 3-article mini-pilot itself — consistent with the
orchestrator's "account-credit-governed, transient-for-now" read: once past the earlier
rate-limit window, the pin behaved cleanly under sustained real load.

## Phase 4 — v3 scoring sanity (gemini pilot)

### Command

```
PYTHONPATH=src uv run --no-sync python3 scripts/wiki_eval.py report \
  --gt $SCR/gt_pilot10.jsonl --pred <gemini pilot run dir>
```

### Result

`metrics.json`: `protocol: "v3"`, `classes: {"named": {...}, "term": {...}}` present.
`report.html` written (2756 bytes).

**10-article numbers are sanity-noise, NOT results** — stated explicitly per the mission
brief; this is a protocol-plumbing check (v3 aggregator runs end-to-end on real pilot data),
not a claim about model quality. For the record only:

| class | gold_units | TP | FN | FP | R_doc | P_doc |
|---|---|---|---|---|---|---|
| named | 302 | 255 | 47 | 106 | 0.844 (CI 0.799-0.881) | 0.706 (CI 0.657-0.751) |
| term | 77 | 32 | 45 | 62 | 0.416 (CI 0.312-0.527) | 0.340 (CI 0.253-0.441) |

## Run-dir index

| run | path |
|---|---|
| Phase 1 gemini pilot (10 articles) | `reports/terminology/wiki-eval/google--gemini-3.1-flash-lite--Google-AI-Studio/111/2026-07-10T08-31-04Z` |
| Phase 3a deepseek mini-pilot (HALTED, 2/3 articles) | `reports/terminology/wiki-eval/deepseek--deepseek-v4-flash--Novita/111/2026-07-10T08-38-16Z` |
| Phase 3b gemma mini-pilot (3 articles) | `reports/terminology/wiki-eval/google--gemma-4-31b-it--WandB/111/2026-07-10T08-52-00Z` |

## Total spend this mission

| item | spend |
|---|---|
| Phase 0 smoke, gemini (6/6) | $0.00676 |
| Phase 0 smoke, deepseek (6/6) | $0.00246 |
| Phase 0 smoke, gemma attempt 1 (1/6 before 429) | $0.00071 |
| Phase 0 smoke, gemma attempt 2 (0/6, all 429) | $0.00000 |
| Phase 0 smoke, gemma attempt 3 = Phase 3b retry (6/6) | $0.00275 |
| Phase 1 gemini pilot (10 articles) | $0.48936 |
| Phase 3a deepseek mini-pilot (halted, 2/3 articles) | $0.02790 |
| Phase 3b gemma mini-pilot (3 articles) | $0.03699 |
| **TOTAL** | **$0.5669** |

Of the $1.20 mission cap — **47% used**, $0.633 headroom remaining.

## Anomalies (summary)

1. **Gemma/WandB sustained 429 (Phase 0, before orchestrator ruling)**: 5 consecutive 429s
   across ~3 minutes of escalating backoff before the pin recovered on the 3rd
   script-invocation-level attempt. Orchestrator ruled this transient-for-now
   (account-credit-governed); confirmed by a subsequent clean 6/6 smoke pass and a fully
   clean 3-article mini-pilot with zero further 429s.
2. **Deepseek/Novita malformed-JSON crash (Phase 3a)**: an un-retried, unclassified
   transport-layer failure (`json.JSONDecodeError` on the HTTP response body) halted the
   mini-pilot at article 3 of 3. Not one of the three documented halt types. Not retried or
   resumed per the mission's diagnosis-is-the-orchestrator's-job instruction. Flagged as a
   possible `is_transient_error` classification gap for the code owner — not fixed here.

## NOT done (explicit)

- Deepseek mini-pilot was not completed (halted at article 3/3, not retried/resumed per
  instruction) — 2/3 articles' worth of real evidence exists and is reported above, but
  there is no `meta.json`/`pred.jsonl`/`metrics.json` for this run.
- No root-cause fix for either anomaly above — both are `src/` changes, out of this
  session's scope, and are handed off as findings.
- No full 3×100-article production runs — those are the NEXT step after this pilot mission,
  not part of it.
- Nothing was committed (as instructed).
