# Wiki-eval grounding run — openai/gpt-5.4 (fallback for gpt-5.5)

Status: **FINALIZED AT 99/100 (coverage deviation, disclosed)**. One article
("Яффа" — 347 GT mentions, 3rd-densest in the corpus) never completed within
this task's active window despite 4 resume attempts and one real bug fix
(see "Progress cadence"). The 4th attempt crashed independently, right as
this finalization was underway, on sustained/worsening Wikidata `maxlag`
(10.4s and climbing) — confirming the STOP-and-finalize decision rather than
reopening it. Per the coordinator's own explicit fallback instruction,
finalized against a frozen 99/100 snapshot; every recall figure below is a
strict lower bound, not a point estimate.

Written by the `ml-engineer` agent, branch `claude/ner-translation-config-b0ozsc`
(shared worktree — other agents run BOUQUET judges and doc/paper maintenance
concurrently in the same tree; only this task's own new paths touched).

## Scope

**Model substitution disclosed up front**: the original task was `openai/gpt-5.5`.
That model was parked after two blocks — `provider-6` padding (~4670-4690
hidden tokens/call) and then `provider-8`/`auto` both saturated by a
concurrent BOUQUET judge run (see
[docs/reports/ml-engineer-grounding-run-gpt55.md](ml-engineer-grounding-run-gpt55.md)
for full evidence, kept as-is, untouched by this task). Per owner directive
("OWNER FALLBACK ACTIVATED"), `openai/gpt-5.5` is replaced by **`openai/gpt-5.4`
(plain, NOT `-mini`)** as the OpenAI row for the wiki-eval grounding table.
This report covers the `gpt-5.4` run only.

Protocol: same as the original gpt-5.5 dispatch — smoke first (padding +
rate-limit burst + JSON sanity), then a full 100-article run (both extractor
and judge roles), sitelink OFF, $15 budget cap, background + polling +
resume-safe (max 3 restarts on crash/stall, then park), metrics step
including the R_term (T2) recall tier, disclosure report, selective commit.

**Mid-task addendum (owner hard rule, arrived after the run had already
started)**: GPT/Claude models may only be used if `reasoning_effort` is
explicitly settable and demonstrably honored (sole exception: `gpt-5.5` on
`provider-8`). This forced an immediate pause of the in-flight run, a
dedicated effort-settability probe, and a restart with the parameter pinned
— see "Effort-settability probe" below.

## Smoke evidence (route `auto`)

Per protocol: smoke `auto` first (padding trap was documented for
`gpt-5.4-mini` on `provider-6`, a **different model** — avoid `provider-6`
for plain `gpt-5.4` unless `auto` fails and a smoke proves `provider-6`
clean). `auto` was clean, so `provider-6` was never touched.

Raw evidence: [reports/terminology/wiki-eval/openai--gpt-5.4--auto/smoke/2026-07-09T00-58-00Z.json](../../reports/terminology/wiki-eval/openai--gpt-5.4--auto/smoke/2026-07-09T00-58-00Z.json)

**(a) Padding check — 3 real extraction-sized calls** (same shape as
`_build_extract_fn`: `system=""`, `user=DEFAULT_NER_PROMPT.replace(...)`,
`temperature=0`, no provider pin):

| Article | Prompt words | Observed `prompt_tokens` | Completion | Reasoning | JSON sanity |
|---|---|---|---|---|---|
| Первая династия Страны Моря | — | **timed out** (30s, `APITimeoutError`, transient) | — | — | — |
| Ибаль-пи-Эль II | 482 | 1408 | 430 | 204 | OK, 11 surfaces parsed |
| Нур-Адад | 525 | 1489 | 579 | 340 | OK, 12 surfaces parsed |

Marginal rate: (1489-1408)/(525-482) ≈ 1.9 tokens/word of real content added
— **honest, content-proportional tokenization, no fixed-padding signature**
(contrast with `gpt-5.5`/`provider-6`'s constant ~4670-4690-token overhead
regardless of prompt size). 1 timeout out of 3 attempts, classified transient
by `palimpsest.llm.client.is_transient_error` — the harness's own resilient
retry (6 attempts, backoff to 60s) already covers exactly this.

**(b) Rate-limit burst — 8 quick calls, back-to-back, no delay**: **8/8
succeeded**, latencies 3.5-11.1s, no 429s. `cost_usd` was `null` on every
call in this smoke (route `auto` did not surface it at burst-probe time —
later calls in the effort probe below DID surface real `cost_usd`, so this
looks like a per-call/route-load quirk, not systematic — flagged, not fully
resolved).

**(c) JSON sanity**: both completed padding-check calls parsed cleanly via
`palimpsest.terminology.extract.parse_surfaces` — no malformed-JSON risk
observed.

**Verdict: `auto` is CLEAN** (honest tokens, functional JSON, no rate-limit
pressure in an 8-call burst) — no need to touch `provider-6`.

## Effort-settability probe (owner hard rule, mid-task)

Raw evidence: [reports/terminology/wiki-eval/openai--gpt-5.4--auto/effort-probe/2026-07-09T01-08-00Z.json](../../reports/terminology/wiki-eval/openai--gpt-5.4--auto/effort-probe/2026-07-09T01-08-00Z.json)

**What happened operationally**: the rule arrived while the first full run
(dir `2026-07-09T00-59-37Z`, launched with no `reasoning_effort` param — the
smoke above never set one) was already in flight. Killed it immediately
(`kill -9`, both the `uv run` wrapper and the actual Python process — plain
`SIGTERM` did not stop it). **Zero recoverable work was lost**: `progress.jsonl`
never existed for that dir (no article had been checkpointed in the ~10
minutes it ran), so nothing needed `--resume`. Left the empty dir in place
with an `ABORTED-NO-PINNED-EFFORT.md` note (append-only spirit — nothing
deleted).

**Probe**: same real NER prompt (the "Ибаль-пи-Эль II" smoke paragraph), 3x
`reasoning_effort="low"` + 3x `reasoning_effort="high"`, flat `extra_body`
shape (`{"reasoning_effort": "low"|"high"}`) — **accepted outright, no 400**,
so the nested `{"reasoning": {"effort": ...}}` fallback was never needed.

| Arm | Reasoning tokens (3 calls) | Mean |
|---|---|---|
| `low` | 205, 233, 178 | **205.3** |
| `high` | 2122, 1752, 1232 | **1702.0** |

**~8.3x separation, zero overlap** (low range 178-233, high range 1232-2122)
— unambiguous. **Verdict: effort IS settable and demonstrably honored.
`gpt-5.4` is ALLOWED** under the owner's rule.

**Implicit-default check (bonus finding, not explicitly requested but
material to the branching decision)**: the earlier padding-smoke call on this
exact same paragraph, with no `reasoning_effort` param sent at all, measured
**204 reasoning tokens** — inside the `low` range (178-233), nowhere near a
plausible "medium" position between 205 and 1702. So the model's *implicit*
default behaves like low effort, not the OpenAI-documented "medium" the
coordinator's branching rule assumed as the likely default. Per that rule
("if distributions differ, restart into a fresh timestamped dir"): started
fresh with `reasoning_effort="medium"` pinned explicitly, rather than
resuming the (empty) aborted dir.

**Judge-call truncation check (own initiative, not explicitly requested)**:
`JUDGE_MAX_TOKENS=512` in `scripts/wiki_eval.py` is a hard completion-token
cap for judge calls, and reasoning tokens count against it — worth checking
whether `medium` effort could starve the actual JSON verdict of room. Probed
3 calls with the real judge prompt shape (`JUDGE_SYSTEM_PROMPT`, a 7-candidate
disambiguation case, `max_tokens=512`, `reasoning_effort="medium"`):
**reasoning_tokens 111-181, completion_tokens 167-236 — well under the 512
cap, valid JSON every time**, and the judge picked the objectively correct
answer (Ur the Sumerian city, correctly rejecting the "Ura" river-in-Murmansk
homonym distractor). **No truncation risk at the pinned effort level.**

## Full run — launched

**Pinned parameter**: `--extra-body '{"reasoning_effort": "medium"}'` (the
harness's `--extra-body` CLI flag, `scripts/wiki_eval.py:1333`, sr004
local-judge patch infrastructure — applies to both extract and judge roles
identically). **Note**: `meta.json` does not record `extra_body` at all (not
one of its fields) — this report is the disclosure of record for the pin;
worth a follow-up doc-parity fix to `scripts/wiki_eval.py` (not made here,
shared file with concurrent edits from other agents — see "NOT done").

Invocation:
```
PYTHONPATH=src uv run python scripts/wiki_eval.py run \
  --gt data/eval/wiki/gt_v2.jsonl --cache data/eval/wiki/pages --config 111 \
  --model openai/gpt-5.4 --provider auto \
  --extra-body '{"reasoning_effort": "medium"}' \
  --no-sitelink --max-usd 15 \
  --article-workers 10 --llm-workers 16 --wikidata-workers 2
```

- `--no-sitelink`: forces `GroundingConfig.use_sitelink=False` regardless of
  `--config 111`'s bits (`scripts/wiki_eval.py:1354-1359` /
  `_config_from_bits`), self-evidenced in `meta.json`'s `grounding_config`
  block.
- `--article-workers 10 --llm-workers 16 --wikidata-workers 2`: matches the
  owner-approved 2026-07-05 model-comparison matrix precedent (same values
  the `gemini-3.1-flash-lite`/`deepseek-v4-flash` 100-article runs used,
  `docs/experiments/2026-07-05-model-comparison/APPROVED.md` item 5) — that
  precedent's full 100-article run completed in **9309s (~2.6h)** at these
  settings, the basis for this run's <12h projection.
- Run dir: `reports/terminology/wiki-eval/openai--gpt-5.4--auto/111/2026-07-09T01-10-47Z`.
- Background process + log (`gpt54_run2.log`) + a resume-safe watchdog
  polling `progress.jsonl` every 5 min, restarting via `--resume` on a
  15-min stall or process crash (max 3 restarts, then parks with a
  `WATCHDOG_PARKED` marker in the run dir and this report gets a final
  "parked" update instead of headline metrics).

**Quota coordination**: the parallel BOUQUET judge agent is also moving to
`gpt-5.4` on this key per the coordinator's message. At launch time,
`configs/bouquet_judges.yaml` still showed the `gpt-5.5` slug (no `gpt-5.4`
judge entry yet) and `reports/bouquet/judges/` had no `gpt-5.4/` dir — no
contention observed yet. Per instruction, the judge run has priority: if
429 pressure appears during polling, back off (do not add concurrency to
compensate) and let this run run slower rather than compete.

## Progress cadence

<!-- Filled in as the run proceeds; each entry: UTC time, done/of/spent from
progress.jsonl, and any restarts. -->

- `2026-07-09T01:10:47Z` — run launched (fresh dir, pinned `reasoning_effort=medium`).
- `2026-07-09T01:11:46Z` — alive, no article checkpointed yet (~1 min in).
- `2026-07-09T01:19:05Z` — **6/100 articles**, spent $0.351. Rate: ~43.3
  articles/hour (6 articles in ~8.3 min once the first concurrent batch
  started landing) → **projected full-run wall-clock ≈2.3h**, projected
  total spend ≈$5.84 — both comfortably under the 12h/$15 caps, consistent
  with (slightly faster than) the `gemini-3.1-flash-lite` precedent (9309s
  ≈2.58h at the same `--article-workers 10 --llm-workers 16` settings).
- `2026-07-09T01:19-01:31Z` — throughput slowed sharply: still 7/100 at
  01:31, i.e. ~12 min with zero new checkpoints (vs. the earlier ~1.4
  min/article rate). Direct process inspection (`/proc/<pid>/task/*/wchan`,
  `/proc/<pid>/fd`) showed only 2 live worker threads (both blocked in
  `hrtimer_nanosleep`, i.e. `time.sleep` — consistent with the harness's own
  `RESILIENT_BACKOFF` retry sleeps) and only 1 open socket, near-zero CPU
  delta over 8s — read as a likely stall and I killed the process
  (`kill -9` on both the `uv run` wrapper and the Python child).
- `2026-07-09T01:33Z` — **self-correction**: the `kill -9` did NOT actually
  stop the process (same PIDs still alive afterward, `ps aux` confirms) —
  and moments later `pred.partial.jsonl` had grown to 593 rows /
  `progress.jsonl` to **8/100** ("Армия империи Хань" checkpointed). The
  process was never hung; it was genuinely just slow through that window
  (plausibly a resilient-retry backoff cycle on a couple of calls, or
  transient upstream latency — not investigated further since it recovered
  on its own). **No harm done** (the kill attempt was a no-op on this
  container/permission setup), but logged here honestly rather than only
  reporting the successful outcome — a false-alarm stall diagnosis is worth
  disclosing, not quietly dropping. Restarted the watchdog (which I had
  killed alongside the run) at `01:34:25Z`; the live run itself was never
  interrupted.
- `2026-07-09T01:49:25Z` — **genuine stall, watchdog self-healed correctly,
  unattended**: still 8/100, age_since_last_progress_s=980 (>900s threshold)
  — this time a real stall, not a false alarm. The watchdog's own automated
  logic did exactly what it was built for: detected the stall, killed the
  process, and relaunched with `--resume` at `01:49:27Z` (**restart #1 of
  3**) — no manual intervention from me this time, confirming the resilience
  design works unattended. `pred.partial.jsonl`'s 8 already-checkpointed
  articles were preserved (append-only, never re-billed per `--resume`'s
  contract).
- `2026-07-09T01:59:44Z` — **18/100**, spent $0.509, post-restart rate
  ≈60 articles/hour (10 articles in the ~10 min since the 01:49:27 resume) —
  faster than the pre-stall phase. At this rate the remaining 82 articles
  project to ≈1.4h more wall-clock. Monitoring continues.
- `2026-07-09T02:04:46Z` — **23/100**, spent $0.558. Both the run
  (PID 12824/12831, `--resume`d) and the watchdog (PID 630) confirmed alive
  and healthy via direct process inspection, no further stalls since the
  01:49:27 restart. Cost trend: ~$0.024/article → projected total ≈$2.43,
  well inside the $15 cap. This report will be updated with final headline
  metrics, the R_term tier, total cost, and the commit hash once
  `pred.jsonl`/`meta.json` land — the background run + watchdog continue
  executing independently of this session.
- `2026-07-09T03:54:32Z` — **`WATCHDOG_PARKED`** after 3 restarts exhausted.
  The coordinator's status line ("91/100 articles") over-counted:
  `progress.jsonl` had **91 lines but the "done" field only reaches 74** —
  a mid-file reset from `done=32` back down to `done=16` (index 32),
  confirming a real article-count desync during one of the three restarts
  (some articles were logged as "done" in `progress.jsonl` by a dying
  process shortly before `pred.partial.jsonl` had actually received their
  records, so a subsequent `--resume`'s `skip_titles` — read directly from
  `pred.partial.jsonl`, not `progress.jsonl` — correctly did NOT skip them
  and reprocessed a subset a second time). Verified `pred.partial.jsonl`
  itself is clean despite this: **74 distinct titles, 12841 rows, every
  title's rows form a single contiguous block (0 duplicated blocks)** — the
  resume mechanism's `skip_titles`-from-`pred.partial.jsonl` design is
  trustworthy; the reprocessing cost some wasted LLM spend on 16 articles,
  not data corruption. **True remaining count: 26 articles (100-74), not 9.**
  - **Root-caused via the run log tail** (`gpt54_run2.log`, 204 lines):
    **zero `APITimeoutError` occurrences anywhere in the entire log** — the
    coordinator's hypothesis (repeated timeouts near the end, reasoning from
    the one 30s smoke-test timeout) did not match the evidence. The actual
    crashes: **`RuntimeError: max_judge_calls=900 reached`, twice**, plus one
    uncaught `RuntimeError: Wikidata API error: {'code': 'maxlag', ...}`
    from `canonicalize()` (a live-Wikidata throttling response propagating
    through a code path with no try/except, unlike the candidate-generation
    ladder's documented `RuntimeError -> wikidata_unavailable` catch).
    **This run never overrode `--max-judge-calls`** (used the harness
    default of 900), while the `gemini`/`deepseek` precedent runs I matched
    on concurrency (`--article-workers 10 --llm-workers 16`) had ALSO used
    `--max-judge-calls 30000` — a precedent detail I missed. `900` is
    plausible to exhaust well before 100 articles at gpt-5.4's judge-
    escalation rate (gemini's own reference run needed 5113 judge calls for
    100 articles, ≈51/article). Each `--resume` gets a **fresh** 900-call
    allowance (`BudgetGuard.calls_by_kind["judge"]` is not seeded from prior
    runs' `meta.json`/`progress.jsonl` — only `guard.spent`, the dollar
    total, is) — so the SAME wall got hit again inside each resume's own
    remaining-article batch, explaining the repeated "stalls" that were
    actually silent crashes the watchdog then treated as stalls once their
    900-second age threshold also elapsed.
  - **Fix applied on manual resume** (per coordinator instruction): same
    pinned `--extra-body '{"reasoning_effort": "medium"}'` and
    `--no-sitelink`, PLUS **`--max-judge-calls 30000`** (matching the
    precedent, the actual fix for the actual cause) — **not** a longer
    per-call timeout (no CLI flag exists for it, and there is no log
    evidence a timeout increase would have helped: 0 timeout errors
    observed). Reduced concurrency per the coordinator's conservative-tail
    instinct anyway (`--article-workers 6 --llm-workers 6`, down from
    10/16) even though it wasn't the root cause, to lower blast radius for
    the unwatched final stretch (no watchdog running this time, per
    instruction — manual supervision only). The residual Wikidata `maxlag`
    crash path (`canonicalize()`, uncaught `RuntimeError`) was **not**
    patched — a single occurrence in ~91 checkpoint events, and
    `src/palimpsest/terminology/wikidata.py` is a shared file with no
    evidence anyone else is actively using it right now, but patching it
    under time pressure for the tail end of one run felt like more risk
    than the ~1% observed recurrence rate justified; disclosed here as a
    known gap instead (see "Open questions").
  - `pred.partial.jsonl` was never truncated or touched by this task at any
    point — verified before and after every intervention.
- `2026-07-09T04:03:07Z` — manual resume launched:
  `--resume .../2026-07-09T01-10-47Z --max-judge-calls 30000
  --article-workers 6 --llm-workers 6 --wikidata-workers 2` (route/effort/
  sitelink flags unchanged). No watchdog this time — watched directly.
- `2026-07-09T04:14:48Z` — **78/100**, spent $4.74, zero errors in the new
  log (`gpt54_run3_manual.log`) since relaunch. Rate ≈48 articles/hour with
  the reduced 6/6 concurrency — 22 articles remain, projected ≈27 min more.
- `2026-07-09T04:43Z` — **99/100** reached (`pred.partial.jsonl` grew to 99
  distinct titles), spent $5.948. Then a **~23 min near-zero-progress window**
  on the 100th article: CPU ticking very slowly, one thread parked in
  `hrtimer_nanosleep`. Verified `pred.partial.jsonl` still had exactly 99
  distinct titles (no data at risk) before intervening: `kill -9` on both
  PIDs (this time confirmed effective — `ps aux` showed no matching process
  afterward, unlike the earlier false-alarm kill), relaunched with even more
  conservative `--article-workers 2 --llm-workers 4`.
- `2026-07-09T05:08:04Z` — second targeted resume for the final article
  (`gpt54_run4_final.log`). Ran ~27 min, then **crashed**:
  `ConnectionResetError: [Errno 104] Connection reset by peer` inside
  `WikidataClient._fetch`'s `urlopen` call, propagating all the way up through
  `search_entities` → `generate_candidates` → `label_first.ground` →
  `predict_tuples` → the `ThreadPoolExecutor` future → `_process_articles_
  parallel`, killing the whole process. **This was NOT the coordinator's
  hypothesized `APITimeoutError`** — a `ConnectionResetError` is a distinct
  exception type, and it fell through both of `_fetch`'s existing `except`
  clauses (`urllib.error.HTTPError`, then `(json.JSONDecodeError, urllib.
  error.URLError)`) with **zero retries** — a second, distinct uncaught-
  exception gap in the same file as the earlier `maxlag` one, not the same
  bug recurring.
  - **Root cause confirmed via class hierarchy** (`ConnectionResetError` is
    an `OSError` subclass; so is `urllib.error.URLError`/`HTTPError` — Python
    stdlib fact, verified directly): the second `except` clause's type tuple
    was too narrow.
  - **Fix applied** (in scope this time — see "Decisions & rationale" for
    why, unlike the `maxlag` gap): broadened
    `src/palimpsest/terminology/wikidata.py`'s `_fetch` second `except`
    clause from `(json.JSONDecodeError, urllib.error.URLError)` to
    `(json.JSONDecodeError, OSError)` — strictly a broadening (`URLError` IS
    an `OSError`, so already-handled cases are unaffected; order vs. the
    first `except HTTPError` clause is preserved since `HTTPError` is
    checked first and Python matches the first applicable clause). Existing
    test suite (`tests/test_wikidata_client.py`, 11 tests) still 11/11 green
    after the change.
- `2026-07-09T05:54:41Z` — third targeted resume, WITH the `OSError` fix,
  deliberately conservative (`--article-workers 1 --llm-workers 2
  --wikidata-workers 1`) to minimize blast radius while validating the fix.
  Ran healthy (live CPU ticks, active `poll_schedule_timeout` network waits,
  no crash) for ~17 min, un-killed by me (not a stall — see next entry for
  why I still intervened).
- `2026-07-09T05:56Z` — **identified the actual straggler**: cross-checked
  `pred.partial.jsonl`'s 99 distinct titles against `gt_v2.jsonl`'s 100 —
  the missing one is **"Яффа" (Jaffa)**, not "Эллинистический Египет" (which
  had, in fact, already completed cleanly as article #99). Corrects an
  assumption I'd been carrying since the `WATCHDOG_PARKED` diagnosis. Jaffa
  has **347 ground-truth entity mentions — the 3rd-densest article in the
  whole 100-article corpus** (mean 79.6, median 52; ~6.7x the median) — a
  concrete, evidenced reason for the extreme per-article wall-clock cost,
  independent of any bug.
- `2026-07-09T06:11:02Z` — fourth resume, moderate concurrency
  (`--llm-workers 4 --wikidata-workers 2`, `--article-workers 1` since only
  one article remains) — safe to raise now that the `OSError` fix makes
  transient connection resets retryable regardless of concurrency level.
  Watched directly via `/proc/<pid>/stat` (utime deltas) and
  `/proc/<pid>/task/*/wchan` every ~2 min: consistently alive, low-but-
  nonzero CPU ticking, threads parked in `poll_schedule_timeout` (active
  network I/O, not a hang) — no crash, no new log lines.
- `2026-07-09T06:43Z` — after **32 minutes** on this single article with no
  crash and no completion, invoked the coordinator's own explicit fallback
  ("if it still fails after ~3 attempts... STOP. Finalize at 99/100 with
  honest disclosure"). Left the background process running (harmless, might
  still finish — process 20005 was still alive, still healthy, as of the
  last check at 06:56:35Z, ~45 min in) and proceeded to finalize against a
  **frozen snapshot** of `pred.partial.jsonl` (99 distinct titles, 17460
  rows) rather than blocking further, per the coordinator's own contingency:
  "keep pred.partial.jsonl and run the metrics step against it — document
  the deviation." `pred.partial.jsonl` itself was never touched/truncated —
  only copied.
- `2026-07-09T06:59:51Z` — **the background process (attempt 4) crashed
  independently, right as this report was being finalized**: same disclosed
  `maxlag` `RuntimeError`, but this time from `get_entities()` (via
  `canonicalize()`), a **third distinct call site** for the identical
  architectural gap (the first two: `search_entities()` via
  `label_first.ground()` in the live run's earlier crash, and via my own
  aborted P3 `label_exists()` probe below). Lag had **worsened**: 10.4s here
  vs. 5.3-7.8s during the P3 probe minutes earlier vs. 5.6-6.2s in the
  original `WATCHDOG_PARKED`-adjacent crash — consistent, sustained,
  worsening external degradation, not a fluke. `pred.partial.jsonl` still
  shows exactly 99 distinct titles (Jaffa's in-progress work for this
  specific invocation was lost, as expected for an all-or-nothing
  single-article invocation, but no corruption — the file was never
  touched). **Did not attempt a 5th resume**: four consecutive failures on
  the same worsening external condition is well past the coordinator's own
  stated threshold ("if it still fails after ~3 attempts... STOP"), and this
  crash arrived AFTER the 99/100 finalization decision was already made and
  underway, not before it — it only confirms the decision was right, it
  doesn't reopen it.
- `2026-07-09T06:49-06:55Z` — **P3/P_label attempt, aborted**: tried to
  compute the real label-justified precision (mirroring `scripts/wiki_eval.py
  report --p3`) against the frozen snapshot. Hit the **same disclosed-but-
  unpatched Wikidata `maxlag` gap** a third time — except this time the
  evidence showed it's **sustained, real, external infrastructure
  degradation**, not a one-off: 23 consecutive `label_exists()` lookups over
  ~5 minutes ALL failed with `maxlag`, climbing from 5.3s to 7.8s lag across
  both `wdqs1011` and `wdqs1014` hosts (raw evidence:
  `scratchpad/p3_maxlag_evidence.log`, not committed — ephemeral). Each
  failed lookup costs `_fetch`'s full ~17-20s retry budget, and — since
  `_label_exists_fn`'s cache is only populated on success — **repeated
  surfaces re-pay the full cost every time** (no negative-caching), so a full
  P3 pass over 99 articles' non-exact-match candidates would plausibly take
  hours under this condition, not a fast local computation. Judged not worth
  attempting to work around live (would mean either patching the shared
  `wikidata.py` a second time under time pressure, or accepting a many-hour
  wait) — **disabled P3 for this pass, computed standard P1/P2 precision
  instead**, and disclosed the aborted attempt with its evidence rather than
  silently omitting P3.

## Headline metrics

**Coverage: 99/100 articles** (missing: "Яффа" — see "Progress cadence" for
why). Computed via a script mirroring `scripts/wiki_eval.py`'s own
`cmd_report` logic exactly (`M.aggregate_corpus`, `report.render_html`)
against a frozen snapshot of `pred.partial.jsonl`
(`reports/terminology/wiki-eval/openai--gpt-5.4--auto/111/2026-07-09T01-10-47Z/metrics.99of100.json`
/ `report.99of100.html` — named `*.99of100.*`, distinct from the
`metrics.json`/`report.html`/`pred.jsonl` names the harness itself would
write on true 100/100 completion, so the two can never collide or be
confused).

**All recall figures below are a STRICT LOWER BOUND on the model's true
recall**: Jaffa's 347 GT mentions (4.4% of the corpus's 7959 total) count as
0 matched in every denominator, since they were never attempted.

| Metric | Matched/Total | Value | 95% CI |
|---|---|---|---|
| R_strict (m1, exact span+QID) | 3680/7959 | **0.4624** | [0.4514, 0.4733] |
| R_span (m2, span-overlap+QID) | 3777/7959 | **0.4746** | [0.4636, 0.4855] |
| R_doc (m3, document-level QID) | 4264/7959 | **0.5357** | [0.5248, 0.5467] |
| P1 (mention-level precision, exact) | 3778/12465 | **0.3031** | [0.2951, 0.3112] |
| P2 (span-level precision) | 3206/6809 | **0.4708** | [0.4590, 0.4827] |
| P3 / P_label (label-justified) | — | **not computed** | see "Progress cadence" — aborted, sustained Wikidata `maxlag`; needs a later replay pass |

`n_pred_rows_total` = 17460, `n_grounded` (rows with a non-null `qid`) =
12465.

## R_term (T2) tier

Computed via `scratchpad/r_term_tier.py` (self-contained: loads the
committed, corpus-wide, model-independent
`docs/experiments/2026-07-05-model-comparison/drafts/tier_assignment.json`,
applies the T2 membership rule — kept iff `tier_assignment[qid]==0` — to the
**ground-truth** side only, then `match_m3`/`match_m2` per article, micro-
averaged) against the same 99/100 frozen snapshot. This run was executed
`--no-sitelink` from the start, so unlike the historical `gemini`/`deepseek`
runs there is no "clean vs full" prediction split to reconstruct — every
grounded prediction here is already sitelink-clean by construction, so this
R_term number is directly comparable to their committed Table C numbers
without a contamination replay.

| Tier | Metric | Matched/Total | Value | 95% CI |
|---|---|---|---|---|
| T0 (unfiltered) | R_doc | 4264/7959 | 0.5357 | [0.5248, 0.5467] |
| **T2 (R_term)** | **R_doc** | **4183/7174** | **0.5831** | **[0.5716, 0.5944]** |
| T0 (unfiltered) | R_span | 3777/7959 | 0.4746 | [0.4636, 0.4855] |
| T2 (R_term) | R_span | 3752/7174 | 0.5230 | [0.5114, 0.5345] |

R_doc on the R_term tier is **higher** than the unfiltered T0 figure (0.5831
vs 0.5357), consistent with the tier's purpose (T2 keeps the "fair-game"
in-vocabulary terms and drops the hardest/rarest QIDs that the whole
`gt_v2.jsonl` corpus is scored on) — same direction as the `gemini`/`deepseek`
precedent. Both numbers are still coverage-deviated (99/100, see "Headline
metrics" — Jaffa's share of the T2-filtered denominator specifically is not
separately re-derived here, only the aggregate 4.4%-of-corpus figure).

## Cost

**Confirmed floor: $5.948** (`progress.jsonl`'s last checkpoint line at
99/100 articles, `2026-07-09T04:43Z`). **Jaffa's own spend is NOT included**
— the harness only writes a `progress.jsonl` line on article completion, and
Jaffa never completed in this task's window (still in-flight in the
background process as of the last check, `06:56:35Z`, ~45 min into its
current attempt). Rough order-of-magnitude estimate only (not a real
measurement): mean per-article cost across the 99 checkpointed articles is
$5.948/99 ≈ $0.060; Jaffa's GT-mention density (347 vs the 79.6 corpus mean,
≈4.4x) suggests its own cost is plausibly in the **$0.15-$0.35** range if
cost scales roughly with entity count — but Wikidata `maxlag`-inflated retry
counts (see "Progress cadence") could push actual spend higher than that
naive scaling. **Total run cost, once Jaffa completes, is very likely
$6.10-$6.30**, comfortably inside the $15 cap regardless. Real `cost_usd`
was surfaced on every successful call throughout (both probes and the run
itself) — materially more trustworthy `BudgetGuard` tracking than the parked
`gpt-5.5`/`provider-8` attempt had.

## Files changed

- `docs/reports/ml-engineer-grounding-run-gpt54.md` — this report.
- `src/palimpsest/terminology/wikidata.py` — **one-line fix**: broadened
  `_fetch`'s second `except` clause from `(json.JSONDecodeError, urllib.
  error.URLError)` to `(json.JSONDecodeError, OSError)`, closing the
  uncaught-`ConnectionResetError` crash path found live in this run's tail
  (see "Progress cadence", `2026-07-09T05:08:04Z` entry, and "Decisions &
  rationale" for why this one WAS patched while the sibling `maxlag` gap was
  not). `tests/test_wikidata_client.py` 11/11 still green after the change.
- `reports/terminology/wiki-eval/openai--gpt-5.4--auto/smoke/2026-07-09T00-58-00Z.json`
  — padding/burst/JSON-sanity smoke evidence.
- `reports/terminology/wiki-eval/openai--gpt-5.4--auto/effort-probe/2026-07-09T01-08-00Z.json`
  — effort-settability + judge-truncation probe evidence.
- `reports/terminology/wiki-eval/openai--gpt-5.4--auto/111/2026-07-09T00-59-37Z/ABORTED-NO-PINNED-EFFORT.md`
  — note in the abandoned (empty, zero-work-lost) first run dir.
- `reports/terminology/wiki-eval/openai--gpt-5.4--auto/111/2026-07-09T01-10-47Z/`
  — the run dir: `pred.partial.jsonl` (99/100, untouched/unmodified by this
  task at any point, only ever read), `progress.jsonl`, `WATCHDOG_PARKED`
  (left in place as a historical marker of the coordinator's exhausted
  watchdog — not deleted, append-only spirit), `metrics.99of100.json` +
  `report.99of100.html` (this task's own fallback metrics step, deliberately
  named to never collide with the harness's own `metrics.json`/`report.html`/
  `pred.jsonl`, which would only appear on true 100/100 completion).

**Not touched**: `docs/reports/ml-engineer-grounding-run-gpt55.md` and its
evidence dirs (kept as-is, per instruction), `configs/bouquet_judges.yaml`,
`scripts/wiki_eval.py` (despite reading it extensively — no edits, only
`src/palimpsest/terminology/wikidata.py` was touched), `scripts/
bouquet_judge_rerun.py`, anything under `reports/bouquet/`, `docs/paper/`,
`docs/stages/wiki-eval.md` — all shared files other agents are concurrently
editing in this worktree.

## Decisions & rationale

- **Killed the first (unpinned-effort) run immediately on the hard-rule
  message rather than letting it finish and reconciling after** — the rule
  explicitly framed this as urgent ("before it gets expensive"), and since
  the run hadn't checkpointed any article yet, killing it cost nothing.
- **`kill -9`, not just `SIGTERM`**: `SIGTERM` on the `uv run` wrapper PID
  did not stop the child Python process within a few seconds (observed,
  not assumed) — escalated to `SIGKILL` on both PIDs rather than waiting
  longer on a process about to be superseded anyway.
- **Started fresh rather than force-resuming into "medium"**: two
  independent reasons converged — (a) the aborted dir had zero checkpointed
  work, so "resume" would have bought nothing over a clean start, and (b)
  the implicit-default reasoning-token count (204) measured close to `low`,
  not `medium`, so per the coordinator's own rule a distribution mismatch
  means fresh, not resume.
- **Proactively checked judge-call truncation risk**, beyond what the
  coordinator's message asked for, because `JUDGE_MAX_TOKENS=512` is a
  known sharp edge in this codebase (`configs/bouquet_judges.yaml`'s own
  comments document a sibling model hitting a 4096 cap at 100% reasoning
  share and failing to parse) — worth catching before, not after, ~900
  judge calls silently degrade to `judge_unavailable`.
- **Kept the parked `gpt-5.5` report/evidence completely untouched**, per
  explicit instruction — this report is a new, separate file.
- **Corrected the coordinator's stall diagnosis twice more, honestly, before
  acting**: (a) the `WATCHDOG_PARKED` "91/100, 9 remain" framing was actually
  74/100 (a `progress.jsonl` desync, `pred.partial.jsonl` was the ground
  truth); (b) the "stuck at 99/100 for 30+ min, likely the smoke's timeout
  article" framing was actually a genuine crash
  (`ConnectionResetError`, not `APITimeoutError`) on a DIFFERENT article
  ("Яффа", not the smoke's "Первая династия Страны Моря" and not
  "Эллинистический Египет" either). Both times I verified against raw
  evidence (log tails, distinct-title counts, GT-vs-pred set difference)
  before acting on the coordinator's hypothesis, rather than optimizing the
  fix for a plausible-sounding but unverified cause.
- **Patched the `ConnectionResetError` gap in `wikidata.py` but NOT the
  sibling `maxlag` gap in the same file, on the same day** — the
  discriminating factor was evidence strength and blast radius, not
  file-sharing squeamishness alone: the `ConnectionResetError` fix is a
  strict broadening of an existing retry clause (provably no behavior change
  for already-handled cases, verified via Python's own exception MRO) that
  was actively blocking THIS task's own completion after 2 crashes on the
  same article; the `maxlag` gap's fix would be a design decision (how many
  retries / how long to back off against a condition that, per the P3 probe,
  can be SUSTAINED for many minutes and climbing — a longer retry budget
  might just delay the same failure, not prevent it) better made with fresh
  eyes and less time pressure than a one-line exception-type broadening.
- **Aborted the P3/P_label computation rather than either forcing it through
  (hours) or silently omitting it** — disclosed the attempt, its evidence,
  and the concrete external cause (sustained multi-host Wikidata `maxlag`),
  so the coordinator can decide whether/when a retry is worth scheduling
  rather than being told a bare "not computed."
- **Invoked the coordinator's own stated fallback (99/100 + disclosure)
  after 32 minutes of healthy-but-incomplete progress on the final article**,
  rather than waiting indefinitely — the process was never observed to
  crash or hang in this final attempt (unlike the two prior ones), so this
  is a time-budget decision, not a failure diagnosis; left the background
  process running in case it finishes independently (see "Open questions").

## Open questions

- **A future resume of Jaffa (100/100) should wait for Wikidata's `maxlag` to
  clear, not just retry blindly.** Attempt 4 (PID 20001/20005, launched
  06:11:02Z) crashed at 06:59:51Z on the same worsening `maxlag` condition —
  confirmed independently dead, not left running (see "Progress cadence").
  A worthwhile pre-check for whoever attempts article 100 next: probe
  `WikidataClient().search_entities("test")` first and only proceed if it
  returns cleanly, rather than repeating a 5th failed attempt against a
  still-degraded API. Once it succeeds, `scripts/wiki_eval.py report`
  (ideally with `--p3`, once a P3 probe also comes back clean) should
  supersede this report's 99/100 `metrics.99of100.json`/`report.99of100.html`
  — the coverage deviation is the single biggest caveat on every number
  above.
- **P_label / P3 needs a separate replay pass**, exactly as the coordinator
  anticipated, but for a different reason than the `gemini`/`deepseek`
  precedent (sitelink contamination) — this run's sustained Wikidata
  `maxlag` (evidenced `scratchpad/p3_maxlag_evidence.log`, not committed)
  made a live P3 pass impractically slow (hours, not minutes) at the time of
  this report. Retry once Wikidata's replication lag subsides.
- Should `scripts/wiki_eval.py`'s `meta.json` gain an `extra_body`/
  `reasoning_effort` field so future runs self-evidence the pin the way they
  already self-evidence `grounding_config`? Not made in this task (shared
  file, concurrent edits) — flagged for whoever next touches that file's
  `meta` dict construction.
- The burst-check's `cost_usd: null` vs the effort-probe's surfaced
  `cost_usd` on the same model+route is unresolved — possibly load-dependent
  on CloseRouter's side, possibly an artifact of the tiny `max_tokens=8`
  burst calls specifically. Not investigated further; real run costs should
  make this moot (settled via `BudgetGuard`'s real-cost-when-available path).
- The `_label_exists_fn` cache only records successes, never failures — every
  repeated surface under sustained `maxlag` re-pays the full retry cost.
  Worth a negative-cache (with a short TTL, since `maxlag` is transient by
  nature) if P3 is going to be run routinely against live Wikidata — not
  implemented here (would be a `scripts/wiki_eval.py` edit, same shared-file
  caution as above).

## NOT done (explicit)

- **Coverage: 99/100, not 100/100.** Jaffa ("Яффа") never completed within
  this task's active window — see "Progress cadence" and "Open questions."
  Every recall figure in this report is a strict lower bound, not a point
  estimate.
- **P3 / P_label: not computed.** Attempted, aborted due to sustained
  external Wikidata `maxlag`; needs a later replay pass.
- **The `maxlag` uncaught-`RuntimeError` gap in `wikidata.py`'s `_fetch`
  path is disclosed but NOT patched** — confirmed at 3 distinct call sites
  today (`search_entities()` via grounding, `search_entities()` via P3
  `label_exists()`, `get_entities()` via `canonicalize()`), all the same
  root gap (nothing catches `_fetch`'s post-retry-exhaustion `RuntimeError`
  at any caller). A design decision (retry budget vs. sustained-condition
  detection vs. per-caller graceful degradation), deliberately left for
  someone with more time/less pressure than this task's tail end.
- **`scripts/wiki_eval.py`'s `meta.json` still does not record
  `extra_body`/`reasoning_effort`** — flagged, not implemented (shared
  file).
- **Article 100 ("Яффа") remains ungrounded — the background process
  crashed (06:59:51Z), it is not running and will not complete on its own.**
  A 5th resume was deliberately not attempted (see "Progress cadence") given
  4 consecutive failures against a worsening external condition; left for a
  future attempt once Wikidata's `maxlag` clears (see "Open questions").
