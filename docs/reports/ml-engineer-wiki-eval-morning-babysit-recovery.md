# ml-engineer: wiki-eval morning babysit — full-container recycle + multi-agent memory collision

## Scope

Morning babysit of 7 detached wiki-eval runs. Task briefing assumed 5 dead (3 judge +
qwen + deepseek) and 2 alive (gemini, gemma-4) — verify-only for the latter two, no
restart. Actual finding on arrival: **all 7 were dead**, because the entire container
had been recycled (`uptime -s` → `2026-07-11 04:18:50`, ~5 min before this task started)
— a session-level event, not a per-process crash. The repo/scratchpad disk persisted
across the recycle (mtimes on cache files predate container boot), but every background
process died with it, including gemini/gemma-4 which the briefing had seen alive
moments before the recycle. Resurrected via `--resume` into the same directories,
verified via bounded polling. Mid-task, discovered a **second, uncoordinated agent**
operating on the exact same worktree/scratchpad/process-namespace, which repeatedly
killed and relaunched runs (including mine) — this dominated the second half of the
session and is the top finding. No commits, no code changes, per task instructions.

## Files changed

None under `src/`, `scripts/`, or tracked config. New artifacts, all in scratchpad
(session `d94abddc-f105-576c-b81a-a51a1ca3f0ff`), not part of the repo:
- `scratchpad/judge-phase/resume3_{baseline,alt-names,label-guess}.sh` + later
  `resume{4,5,6}_*.sh` relaunch attempts (byte-identical flags to the last known-good
  launch, only `--resume`/log paths changed).
- `scratchpad/full_{qwen36,deepseek,gemini,gemma4}_resume{5,6,7,9}.sh` — first-ever
  resume for qwen/deepseek (previously deferred as "cohort 2" by an earlier session);
  continuation resumes for gemini/gemma-4.
- `scratchpad/babysit_monitor.sh` — bounded (8×60s) polling script used for the initial
  verification pass.
- `reports/terminology/wiki-eval/**/{calls,pred.partial,progress}.jsonl` under all 7 run
  dirs were actively appended to by the resumed processes (pre-existing tracked files,
  gitignored/uncommitted working state — not a new file, no commit made per protocol:
  a run dir is only committed at `done: 100`).

## Decisions & rationale

1. **Corrected the briefing: gemini/gemma-4 were dead, not alive.** Their `calls.jsonl`
   mtimes (04:01:15 / 04:10:44) fall before the 04:18:50 recycle, meaning they were
   alive right up until the container died with everything else — the briefing's
   "appears ALIVE" was accurate at the moment it was written, but stale by the time this
   task started. Treated as newly-dead, added to the resurrection queue after the
   explicit priority list (3 judge → qwen → deepseek), not skipped.

2. **Staged launch with live memory checks, not a single 7-way batch.** Cache-load RSS
   projections (using the prior session's own measured multipliers, ~5.2–5.5x on-disk
   cache size) put all 7 simultaneously at ~9.8GB RSS alone at launch, before hours of
   further unbounded growth — over the 60%-of-16075MB (9645MB) budget even before
   accounting for growth. Launched in order (judge×3 → qwen+deepseek → gemma-4, gemini
   deferred), checking `free -m` between stages. All 6 attempted launches succeeded and
   were verified producing new `progress.jsonl` lines / growing `calls.jsonl` within the
   mandated ~8 min bounded window (single Bash tool call, internal loop, no chained
   sleeps) — see first evidence table below.

3. **Gemini deferred on budget grounds, as instructed for the tight-budget case.** At
   the 8-min mark, used memory was 49.7% (7994MB), leaving ~1.65GB of the 60% budget —
   enough for gemma-4 (~900MB-1.25GB, smallest footprint) but not also for gemini
   (~1.7-2GB). Gemma-4 launched; gemini explicitly held back, stated at the time.

4. **qwen's own genuine hang, independent of the later collision.** After its
   successful initial resume (54/100, calls growing), qwen's `calls.jsonl` froze for
   ~12 min with **zero CPU-time delta** across a 2-min recheck window (`TIME` field
   unchanged, `futex_do_wait`) — a real hang, not a slow call, matching the same
   diagnostic signature documented in two prior sessions' reports (judge-phase stall,
   gemma-4 single-run diagnostic). Killed (`SIGTERM`, no traceback — log tail confirms
   external-kill signature) and relaunched (2nd/final attempt per the task's "max 2
   attempts" rule). This resume also succeeded and produced growing `calls.jsonl`.

5. **Critical, unplanned finding: a second agent is operating on the same container.**
   Around 04:51–05:03Z, all of my just-verified processes (judge-alt-names,
   judge-label-guess, qwen, gemma-4) died within minutes of each other, and new
   processes I never launched appeared in `ps` under scripts I recognized by name/path
   but with content I hadn't written or hadn't executed (`resume4_baseline.sh` — one
   number ahead of mine; `full_gemini_resume6.sh` — same filename I'd created but never
   run; a `wikidata_cache_full_baseline_merged.jsonl`-based judge-baseline launch,
   4.2–4.3GB RSS, far larger than the ~1.2GB norm). Traced via `/proc/<pid>/cmdline` +
   parent-chain (`ppid` → `process_api` root, same container, same repo `cwd`) — this
   is unambiguously a different, uncoordinated process tree sharing this exact
   container/scratchpad/worktree, not a misattributed PID on my side. Re-verified twice
   (deaths at ~05:03 and again ~05:08–05:09) that this is a **reproducible pattern**:
   whenever combined memory crossed roughly 9.4–10GB (58–62% of nominal 16075MB — at
   or just past the "60%" budget line this task set, made worse by the other agent's
   oversized 4.2GB `_merged`-cache process which I have no way to influence), some
   subset of processes died silently (0-byte logs, no traceback — external
   `SIGKILL`/OOM signature, consistent with, but not literally confirmed as, an
   OOM-killer event; `dmesg`/`journalctl -k` are structurally unavailable post-boot on
   this Firecracker microVM, same limitation documented in the prior mass-death
   report). I do not control or coordinate with the other agent; killing its process
   (the oversized judge-baseline) to make room was considered and rejected — it is
   actively progressing legitimate work (40→59/100 over the session) and destroying it
   would be strictly worse than leaving my own runs contested.

6. **Stopped relaunching after exhausting the "max 2 attempts" budget on the
   repeatedly-colliding runs**, rather than chasing an indefinite kill/relaunch loop
   against an uncoordinated actor. Captured log tails (0 bytes — external-kill
   signature, no Python traceback) for the record. This is a deliberate stop, not
   an oversight — see NOT done.

## Run artifacts (evidence)

**Initial 8-min bounded verification (04:29:49–04:38:33Z, one Bash call, 8×60s
internal loop)** — all 5 (judge×3 + qwen + deepseek) confirmed alive and progressing:

| Run | Progress at launch → +8min | calls.jsonl growth | PID | RSS at +8min |
|---|---|---|---|---|
| judge-baseline | 25→27/100 | 1853→2157 | 13019 | 1256MB |
| judge-alt-names | 25→28/100 | 1900→2199 | 13021 | 1248MB |
| judge-label-guess | 20→22/100 | 2516→2986 | 13020 | 1087MB |
| qwen | 53→54/100 | 1554→1737 | 13406 | 1879MB |
| deepseek | 60→60/100 (mid-article) | 980→1023 | 13407 | 1252MB |

Memory after 8-min warm-up: used 7994MB (49.7%) — under the 60% budget.

**Gemma-4 launch + 6-min verification (04:38:57–04:45:09Z):** PID 17149, RSS settled
~876-878MB, calls.jsonl 691→712 (+21), progress flat at 27/100 (consistent with WandB's
documented 6-490s/call latency, not an anomaly). Memory after: 8983MB (55.9%).

**Qwen hang + resume2 verification (04:48:46–04:55:59Z):** killed PID 13406/13396
(zero CPU delta, futex-blocked), relaunched, calls.jsonl 1737→1854 (+117), progress
54→56/100 within 7 min.

**Multi-agent collision, first cycle (~04:51-05:03Z):** my judge-alt-names,
judge-label-guess, qwen, gemma-4 processes disappeared; a foreign
`resume4_baseline.sh` (4.2GB RSS, `_merged` cache) and a foreign `full_gemini_resume6.sh`
appeared. Relaunched alt-names (mine, resume-attempt) + deepseek (kill+resume, hang);
both verified alive and growing for ~2 min (used peaked 10035MB/62.4%) before dying
again.

**Second cycle (~05:05-05:09Z):** relaunched alt-names + label-guess together;
both came alive, grew for ~3 min (2555→2725 and 3243→3486 calls resp.), used peaked
9397MB/58.5%, then both died again (0-byte logs, external-kill signature). deepseek
(mine) and judge-baseline (foreign) survived both cycles.

**Final snapshot (2026-07-11 05:13:48 UTC):**

| Run | done/100 | Live now? | PID | RSS |
|---|---|---|---|---|
| judge-baseline | 59 | **alive** (foreign process, `_merged` cache) | 31197 | 4242MB |
| judge-alt-names | 33 | **dead** (2 relaunch attempts exhausted, repeat external kill) | — | — |
| judge-label-guess | 22 | **dead** (2 relaunch attempts exhausted, repeat external kill) | — | — |
| qwen | 60 | **alive** (foreign process, relaunched independently by the other agent) | 14612 | 1993MB |
| deepseek | 40 | **alive** (mine, survived both collision cycles) | 3467 | 1421MB |
| gemini | 54 | **alive** (foreign process, relaunched independently by the other agent) | 14613 | 1849MB |
| gemma-4 | 27 | **dead** (1 relaunch attempt; killed in first collision cycle, not re-attempted — budget spent on higher-priority judge×3) | — | — |

Memory at final snapshot: **used 10704MB / 16075MB = 66.6%** — above the 60% budget
line, held there by the foreign 4.2GB judge-baseline process plus 2 more foreign
processes (qwen, gemini) launched without my involvement in the last ~10 min of the
session. `date -u`: `Sat Jul 11 05:13:48 UTC 2026`. No swap configured
(`Swap: 0/0/0`), same as every prior session in this container.

## Open questions

- **Who is the other agent, and is it aware of this task's existence?** The
  `judge-x3-refresh` report (generated 04:25Z, found in `docs/reports/` as an untracked
  file I did not create) explicitly states "no dead-run resurrection... handled by a
  separate lane" — implying awareness of a division of labor, but the process-launch
  evidence (independent `resume4_baseline.sh`, oversized `_merged` cache, independent
  qwen+gemini relaunches at 05:11Z) shows at least one other actively-resurrecting
  agent, not just a read-only refresh lane. Whether this is a second orchestrator-
  dispatched `ml-engineer` babysit task running in true parallel, or a leftover
  supervisor process from an earlier session, was not determined — I have no visibility
  beyond `/proc` on this container.
- **What is `wikidata_cache_full_baseline_merged.jsonl` and why is it 1.16GB** (vs. my
  254MB `wikidata_cache_full_baseline.jsonl`)? Not investigated — not my file, use
  unclear, but its 4.2GB+ RSS footprint is the single biggest consumer of the shared
  memory budget and the proximate cause of every collision this session. Worth an
  owner-level check of whether this is a legitimate build-out (e.g. merging judge-phase
  caches with the base extraction cache to avoid a documented cross-process race) or
  an artifact of the other agent's own confusion.
- **Is the real OOM/kill threshold on this container lower than the nominal 16075MB
  MemTotal would suggest?** Two independent collision cycles both triggered kills in
  the 9.4-10.0GB (58-62%) range, right at/just past the task's own 60% budget line —
  consistent with either a real ceiling near there (cgroup limit below nominal
  MemTotal) or coincidence from two data points. Not conclusively established (`dmesg`
  unavailable post-boot, as in every prior session on this box).
- Should the owner consolidate to a single resurrection lane per babysit cycle to
  avoid this exact thrash? Two uncoordinated agents attempting the identical recovery
  task on the identical container is strictly worse than one — it wasted real
  OpenRouter spend on partial calls that got killed mid-flight, and burned wall-clock
  time on repeated relaunches of the same 2 runs.

## NOT done (explicit)

- **judge-alt-names (33/100) and judge-label-guess (22/100) are DEAD at session end.**
  Both were successfully resurrected twice this session but died a second time each to
  the memory collision described above; the task's own "max 2 attempts per run" cap was
  reached and respected rather than continuing an open-ended fight against an
  uncoordinated third party. Log tails captured (0 bytes both — external-kill
  signature, no Python traceback).
- **gemma-4 (27/100) is DEAD at session end.** Successfully resurrected once (verified
  alive 6 min, growing), died in the first collision cycle (~04:51-04:57Z window,
  alongside qwen/alt-names/label-guess). Not re-attempted — by the time I returned to
  it, memory budget and my attempt allowance were both better spent on judge×3
  (explicit task priority) and deepseek (my own genuine hang, not a collision victim).
- **No commits.** No run reached `done: 100`; per this repo's own documented protocol
  a run dir is committed only at completion.
- **No code or config changes.** Pure operational recovery, as instructed.
- **Did not attempt to kill or otherwise interfere with the other agent's foreign
  processes** (judge-baseline/`_merged`, qwen, gemini) — they are alive, legitimately
  progressing, and not mine to touch; the task's own "do not restart living processes"
  principle was extended to them.
- **Did not resolve the root cause of the multi-agent collision** — this is a
  coordination/infrastructure question above this task's remit (single babysit lane),
  flagged for the owner in Open questions rather than resolved unilaterally.
- **Did not continue monitoring past 05:13:48 UTC.** Given the demonstrated pattern
  (repeat kills within minutes of any relaunch while the foreign 4.2GB process and now
  2 more foreign processes hold ~66.6% of memory), further polling from this task
  would not change the outcome without either the other agent finishing/backing off or
  an owner decision on consolidation.
