# ml-engineer: wiki-eval disambiguation (judge) phase — 3 search-mode runs

## Scope

Execute the disambiguation (judge) phase of the wiki-eval grounding experiment: three
judge-enabled runs, one per `--search-mode` (`baseline`, `alt-names`, `label-guess`),
each reusing the already-paid extraction from the complete `gemma-3-27b-it` base run
(`reports/terminology/wiki-eval/google--gemma-3-27b-it--Parasail/111/2026-07-10T18-22-43Z`,
100/100 articles, `spend.extract=$0.434`, `spend.judge=$0`) via `--reuse-extraction`.
This is a NEW phase — orthogonal to the five in-flight `--no-judge` extraction-only runs,
which this task never touched.

Owner instruction (verbatim): «нужно довести в том числе и метрику про дисамбигуити -
получишь финальный P и R. Сделай это во всех трех случаях (по выбору search, как мы
раньше обсуждали)».

Required flow: Phase 1 smoke ×3 (5 articles) → Phase 2 cost gate (hard $6.00 ceiling
on the 3×100-article projection) → Phase 3 full runs ×3 (100 articles, parallel,
actively polled, stall protocol, per-run-dir commits on completion).

## Files changed

No source code was edited (per task constraint — invoke only). New artifacts, all
under `reports/terminology/wiki-eval/google--gemma-3-27b-it--Parasail/111/`:

| Run dir | Mode | Articles | Status at report time |
|---|---|---|---|
| `2026-07-10T22-16-28Z` | baseline (aborted smoke attempt, killed by a 2-min tool timeout before any article completed — `calls.jsonl` only, no `pred.jsonl`/`meta.json`) | 0/5 | dead leftover, left in place per "no deletes under reports/" |
| `2026-07-10T22-19-00Z` | baseline smoke | 5/5 | **COMPLETE, verified PASS** |
| `2026-07-10T22-48-49Z_alt-names` | alt-names smoke | 5/5 | **COMPLETE, verified PASS** |
| `2026-07-10T23-22-18Z_label-guess` | label-guess smoke | 5/5 | **COMPLETE, verified PASS** (finished on its own in the background after the coordinator authorized not blocking on it) |
| `2026-07-10T23-40-53Z` | baseline full | 100 | **IN PROGRESS, 19–20/100** at report time, PID 10272, healthy |
| `2026-07-10T23-40-53Z_alt-names` | alt-names full | 100 | **IN PROGRESS, 20/100** at report time, PID 10278, healthy |
| `2026-07-10T23-40-53Z_label-guess` | label-guess full | 100 | **IN PROGRESS, 15/100** at report time, PID 10281, healthy |

Per-run dedicated Wikidata caches (outside `reports/`, in the session scratchpad, to
avoid a cross-process append race with the 4 other in-flight extraction processes
sharing the default cache path):
`/tmp/claude-0/-home-user-translation-demo/d94abddc-f105-576c-b81a-a51a1ca3f0ff/scratchpad/judge-phase/wikidata_cache_{smoke,full}_{baseline,alt-names,label-guess}.jsonl`.

No commits made yet — per the task's own protocol, a run dir is committed only on
`done: 100`/complete `meta.json`, which none of the three full runs have reached.

## Decisions & rationale

**Article-limiting mechanism.** `run --help` has no `--limit`/`--sample` flag. Prior
smoke sessions (evidenced by `gt_pilot*.jsonl`/`smoke_gt.jsonl` in the scratchpad)
used a sliced `--gt` file instead. I built a deterministic 5-article slice
(`gt_smoke5.jsonl`, first 5 titles of `data/eval/wiki/gt.jsonl` by file order: KV35YL,
XXVII династия, XXX династия, Абдмилькат, Азиатская экспедиция) and passed it via
`--gt`. `--reuse-extraction`'s coverage guard only requires the *source* run's
`pred.jsonl` to cover the given `--gt`'s titles — a subset of the 100-article base run
qualifies trivially.

**`resolved_by=judge` vs `resolved_by=llm_disambiguation`.** The task text asks to
check for "`resolved_by=judge`" — the actual code (`grounding/label_first.py`) uses
`resolved_by="llm_disambiguation"` for a judge-selected candidate; there is no literal
`"judge"` value. I verified against this real value (284–299 `llm_disambiguation`
mentions per 5-article smoke, each with a QID) rather than patch/rename anything —
this is a wording mismatch in the task description, not a code defect.

**Cost projection methodology.** Followed the task's own formula: (per-article
judge+label_guess cost averaged over the 3 smokes) × 100 × 3 modes. Using the fully
completed 5-article smokes: baseline $0.001653/article, alt-names $0.001683/article,
label-guess $0.001927/article → **$0.526 projected total**, 8.8% of the $6.00 gate.
(An earlier, more conservative interim projection using label-guess's partial 2/5-article
data, at the coordinator's request before the smoke finished, gave $0.579 — still a
clean pass; both numbers are recorded for auditability.)

**Concurrency for full runs.** Bumped `--article-workers 6 --llm-workers 6` (from
defaults 3/4) identically across all three, per an explicit mid-task steering message
from the orchestrating agent, to accelerate given a stated ~01:50Z scoring checkpoint.
Deliberately left `--wikidata-workers 2` unchanged (matches the existing codebase
convention already used by the 4 parallel `--no-judge` extraction runs, chosen
specifically to avoid a documented 429-storm history) — this was not treated as a
speed lever.

**Stall diagnosis and fix (evidence-based, not a guess).** At `01:05:06–09Z` all
three full runs' `calls.jsonl` AND their independent, per-run `--wikidata-cache` files
froze simultaneously. Confirmed genuine hang (not just "between checkpoints") via:
(a) zero growth in `calls.jsonl` line counts across two checks 25s apart holding at
exactly 499/504/645 lines; (b) `/proc/PID/stat` utime deltas of only 1–2 jiffies over
25s — processes essentially idle, not computing; (c) a synchronized freeze across
*three independent processes* touching *two independent upstream hosts* (OpenRouter
Parasail for judge calls, Wikidata's public API for candidate search) rules out a
single-provider slowdown; (d) a direct `curl` to both `openrouter.ai` and
`wikidata.org` immediately after killing returned 200 in ~0.6s each — the network/proxy
was healthy again by the time I checked, consistent with a transient stuck-connection
event (plausibly from the growing 7-process contention on this 4-core container's
single shared outbound HTTPS proxy) rather than a sustained outage or a config defect.
Total downtime: ~10.3 minutes, crossing the task's own 10-minute stall threshold.
**Fix applied:** `kill -TERM` (clean exit, all 3 confirmed dead within 5s) then
`--resume` into the identical run dirs with identical flags. Checkpoints
(`pred.partial.jsonl`/`progress.jsonl`) were intact and consumed correctly — resumed
processes were logging fresh calls within 90 seconds, and the runs stayed healthy for
the remaining ~54 minutes of monitoring in this session with zero further stalls.

## Phase 1 — smoke verification (all PASS)

| Check | baseline | alt-names | label-guess |
|---|---|---|---|
| `search_mode` recorded | baseline | alt-names | label-guess |
| `reuse_extraction_from` recorded | yes | yes | yes |
| `spend.extract == 0` | yes ($0) | yes ($0) | yes ($0) |
| judge calls > 0 | 164 | 166 | 179 |
| `n_reuse_extraction_unmatched` | 0 | 0 | 0 |
| `calls.label_guess` (label-guess only) | n/a | n/a | 37 (>0, confirms the tier fires) |
| non-baseline candidates carry `source` | n/a (baseline never adds the key, by design) | yes: `{baseline: 1739, alt: 5}` | yes: `{baseline: 1739, label_guess: 40, alt: 5}` |
| some mentions `resolved_by=llm_disambiguation` with a QID | 284, e.g. (Тутанхамона, Q12154) | 287 | 299 |
| Total spend | $0.008266 | $0.008416 | $0.009636 |

All checks pass; no STOP condition triggered.

## Phase 2 — cost gate

$0.526 (using the completed 5-article smokes) vs the $6.00 hard ceiling — **PASS**,
8.8% of budget. Full breakdown in Decisions above.

## Phase 3 — full runs (IN PROGRESS, not complete)

Launched **`23:40:53Z`**, resumed once after the stall at **`01:16:37Z`**. Snapshot
at report time (`02:10:40Z`, ~2h30m wall-clock since original launch):

| Mode | Run dir | Progress | Spend split at snapshot | PID |
|---|---|---|---|---|
| baseline | `...T23-40-53Z` | 19/100 | judge $0.0563, label_guess n/a | 10272 |
| alt-names | `...T23-40-53Z_alt-names` | 20/100 | judge $0.0608, label_guess n/a | 10278 |
| label-guess | `...T23-40-53Z_label-guess` | 15/100 | judge $0.0539, label_guess $0.0144 (total $0.0683) | 10281 |

Cumulative judge-phase spend across smokes + full runs at report time: **≈ $0.21**,
nowhere near the $8.00 pause threshold.

**None of the three has reached `done: 100` yet** — per the task's own protocol,
run-dir commits happen only on completion, so **no commits have been made**. All
three processes are detached (`setsid`+`nohup`+`disown`) and will keep running
independent of this session ending.

**Evidence-based ETA (given in the interim report to the coordinator, reproduced
here):** pre-stall net throughput was ~8 min/article (steady-state, excluding the
initial ~20-min 6-worker ramp-up). At that rate, 100 articles ≈ 13.3h per mode,
run in parallel → full completion for all three ETA **~14:30–15:00Z on 2026-07-11**,
assuming no further stalls. This is far beyond what a single bounded interactive
session can babysit turn-by-turn; the runs will need continued external monitoring
(or a follow-on session) to reach completion, verify final `meta.json`, compute
`resolved_by` distributions, and commit+push each run dir per the original protocol.

## Open questions

- Whether the orchestrator wants this session (or a follow-on one) to continue
  polling until 100/100, or whether the ~01:50Z intersection scoring already
  satisfied the immediate deliverable and full completion can proceed unattended
  with periodic check-ins.
- Whether further stalls (same root cause: shared-proxy contention under 7+
  concurrent long-running processes on a 4-core container) should be pre-empted by
  reducing total concurrent process count (e.g. once some of the 4 `--no-judge`
  extraction runs finish, contention eases automatically) rather than reactive
  kill+resume each time.

## NOT done (explicit)

- **Full runs are NOT at 100/100** for any of the three modes (19/20/15 out of 100
  at report time). Realistic ETA is many more hours (see above).
- **No commits or pushes** have been made — the task's protocol only commits a run
  dir on completion, and none has completed.
- **No `resolved_by` distribution / final `P_doc`/`R_doc` metrics** exist yet for the
  full 100-article corpus in any mode — only smoke-scale (5-article) distributions
  are available (in the Phase 1 table above). The task's "final P and R" deliverable
  the owner asked for requires the completed full runs plus a separate `report`
  command invocation (`wiki_eval.py report --gt ... --pred <run_dir>`), neither of
  which has been run yet for the full-scale data.
- The dead leftover smoke attempt dir (`2026-07-10T22-16-28Z`, killed by a tool
  timeout with 0/5 articles, only `calls.jsonl`) was left in place, not deleted, per
  the "never delete under `reports/`" constraint — it is inert and harmless but
  clutters the directory listing.
- One stall (~10.3 min) occurred and was fixed; no guarantee against recurrence
  given the underlying cause (shared-proxy contention) is environmental, not fixed
  by this session's actions beyond the reactive kill+resume already performed.
