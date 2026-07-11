# ml-engineer: wiki-eval mass process death — root-cause + cohort resurrection

## Scope

Incident response task: 6 of 7 detached wiki-eval runs (3 judge-phase disambiguation
runs + gemini/qwen/deepseek extraction runs) were reported frozen ~02:30–03:00Z;
gemma-4-31b was reported relaunched 03:07Z and alive. Task: (1) find root-cause
evidence within a 10-minute budget, (2) resurrect a memory-safe cohort without
retriggering the failure, (3) note the durability tweak available without code/spec
changes. No source code or pipeline config was touched — this is an operational
recovery task only, run entirely against the existing `scripts/wiki_eval.py` CLI via
its documented `--resume` flag.

## Files changed

No files under `src/`, `scripts/`, or any tracked config were modified. New artifacts,
all in the session scratchpad (not part of the repo):

- `.../scratchpad/full_gemini_resume5.sh` + `.log` — gemini-3.1-flash-lite resume launcher.
- `.../scratchpad/full_gemma4_resume7.sh` + `.log` — gemma-4-31b resume launcher (7th
  resume attempt for this run overall).
- `.../scratchpad/judge-phase/resume2_baseline.sh` + `.log`
- `.../scratchpad/judge-phase/resume2_alt-names.sh` + `.log`
- `.../scratchpad/judge-phase/resume2_label-guess.sh` + `.log`

Each script is a byte-for-byte copy of the last known-good launch command for that run
(sourced from `docs/reports/ml-engineer-wiki-eval-5model-parallel-run.md`'s Resume
commands section for the 2 extraction runs, and from the already-existing
`judge-phase/resume1_*.sh` scripts for the 3 judge runs) — only the log filename
changed, no flags were altered.

Repo working tree: `reports/terminology/wiki-eval/**/{calls,pred.partial,progress}.jsonl`
under the 5 resumed run directories are being actively appended to by the now-running
processes (pre-existing tracked files, modified in place — expected, not a new file).
No commit was made (see NOT done).

## Decisions & rationale

1. **Root-cause verdict: OOM wave, evidenced circumstantially, not via kernel logs.**
   `dmesg` is readable in this container but only contains ring-buffer entries from the
   *current* boot (timestamps start at `0.000000`); `journalctl -k` reports "No journal
   files were found". The container is a Firecracker microVM
   (`--firecracker-init` in the kernel cmdline) that hard-rebooted at
   **2026-07-11 03:48:40 UTC** (`uptime -s`) — a VM-level restart wipes the ring buffer
   and there is no persistent journal, so pre-reboot OOM-killer lines are structurally
   unrecoverable on this box, not just today. Verdict rests instead on: (a) all 6
   briefed-dead runs' `progress.jsonl` last-write timestamps cluster in a 6-minute
   window (label-guess 02:23:06, alt-names 02:25:05, baseline 02:27:04, qwen 02:27:03,
   gemini 02:27:24, deepseek 02:29:07) — synchronized freezing across processes hitting
   two independent upstream hosts (OpenRouter, Wikidata) is the OOM-killer's signature,
   not 6 unrelated crashes; (b) this is the same mechanism already root-caused earlier
   in the session (`docs/reports/ml-engineer-wiki-eval-5model-parallel-run.md` decision
   #4): `WikidataClient` loads its entire cache file into an in-memory dict with no
   eviction, so RSS grows unboundedly over a run's multi-hour lifetime even after the
   earlier per-run-cache mitigation; (c) live re-measurement during this task's own
   resurrection confirms a ~5.3–5.9x on-disk-cache-size → RSS multiplier (e.g. gemini's
   336MB cache → 1.75GB RSS after resume) — summed over 7 concurrent processes after
   hours of unbounded growth this plausibly exceeds a 16GB container; (d) `Swap: 0/0/0`
   — zero cushion, so exhaustion produces an abrupt kill, matching the observed pattern
   (no gradual slowdown in the progress logs before the freeze).

2. **New fact beyond the incident brief: gemma-4 was also dead, not alive.** The
   03:48:40 UTC reboot killed every process including the "confirmed alive" gemma-4
   run. Its own `progress.jsonl`/wikidata-cache mtime shows it had already stopped
   advancing at **03:21:36 UTC** (26/100), ~27 minutes *before* the reboot — a second,
   apparently independent freeze after its 03:07Z relaunch, not merely a casualty of
   the reboot. By the time remediation started (03:51–03:52 UTC, confirmed via `ps`
   returning zero `wiki_eval`/python processes and zero matches for any PID from
   either prior report), this was 7-of-7 dead. Decision: fold gemma-4 into cohort 1
   rather than leaving it out per the original (now-stale) briefing — it is the
   cheapest run to carry (167MB cache, smallest RSS footprint of the five) and was
   already mid-recovery.

3. **Cohort 1 = 3 judge runs + gemini + gemma-4, unchanged flags.** Followed the task's
   own priority order and the hard constraint to not retrigger the wave: resumed each
   into its identical run directory with identical CLI flags (no `--article-workers`/
   `--llm-workers`/`--wikidata-workers` changes) via `nohup setsid ... & disown`.
   Verified over an 8-minute bounded poll (60s interval) that every one of the 5
   produced either new `progress.jsonl` lines or growing `calls.jsonl` line counts, and
   confirmed real PIDs/RSS via `ps`. All 5 passed on the first attempt — no relaunch
   needed.

4. **Cohort 2 (qwen, deepseek) deferred, not launched.** After the 8-minute warm-up,
   cohort 1 alone already uses 7206MB (44.8% of the 16075MB MemTotal) against the
   task's 60%-of-MemTotal (9645MB) budget cap — and this number will keep climbing for
   hours since unbounded cache growth is the literal failure mechanism, not a one-time
   startup cost. Extrapolating qwen (384MB on-disk cache) + deepseek (253MB) at the
   ~5.3–5.9x file→RSS ratio observed live in cohort 1 projects an additional
   ~3.3–3.8GB, landing around 10.5–11GB (65–68% of MemTotal) — over budget, and before
   accounting for further multi-hour growth across all 7 processes. Launching all 7
   again now would reproduce close to the exact condition that caused the original
   wave. This is a explicit "defer" decision per the task's own decision framework
   ("only if budget clearly allows, else defer and say so"), not an oversight.

5. **Durability tweak (no code changes, per task constraint):** the only lever
   available without touching `scripts/wiki_eval.py` or its spec is concurrent cohort
   size — i.e. running fewer of the 7 models/modes at once (or serializing waves) so
   the sum of unbounded per-process Wikidata-cache RSS growth stays under the
   container's ceiling for the full multi-hour lifetime of a run, not just at startup.
   This was applied here (cohort 1 = 5, cohort 2 deferred) rather than any code
   change, per the task's explicit "do NOT edit the pipeline" instruction.

## Run artifacts (evidence)

| Run | State found (frozen at) | Action | 8-min verification |
|---|---|---|---|
| judge baseline (`...23-40-53Z`) | 02:27:04, 24/100 | `--resume`, `resume2_baseline.sh` | PID 6581, calls.jsonl 1539→1753 (+214), RSS 1207MB |
| judge alt-names (`..._alt-names`) | 02:25:05, 23/100 | `--resume`, `resume2_alt-names.sh` | PID 6580, progress 23→24, calls 1491→1796 (+305), RSS 1193MB |
| judge label-guess (`..._label-guess`) | 02:23:06, 19/100 | `--resume`, `resume2_label-guess.sh` | PID 6582, progress 19→20, calls 2043→2390 (+347), RSS 1011MB |
| gemini-3.1-flash-lite | 02:27:24, 69/100 | `--resume`, `full_gemini_resume5.sh` | PID 6591, progress 69→73 (+4), calls 1348→1578, RSS 1748MB |
| gemma-4-31b | 03:21:36, 26/100 (briefed as alive; actually dead pre-reboot) | `--resume`, `full_gemma4_resume7.sh` | PID 6592, progress steady at 26 (WandB latency 6–490s/call observed historically), calls 625→652 (+27), RSS 873MB |
| qwen3.6-27b | 02:27:03, 53/100 | **deferred (cohort 2)** | not launched |
| deepseek-v4-flash | 02:29:07, 60/100 | **deferred (cohort 2)** | not launched |

All 5 launches succeeded on the first attempt (no relaunch/retry needed).

**Memory (all real, measured this session):** MemTotal 16075MB (16461176kB), no swap
configured. Free before cohort 1 (idle, post-reboot, 03:51:27 UTC): used 1168MB / free
14393MB. Immediately after launch: used 2816MB / free 12320MB. After 8-min warm-up
(04:05:00 UTC): used 7206MB / free 7103MB / available 8869MB.

**Boot evidence:** `uptime -s` → `2026-07-11 03:48:40`; `dmesg | head` shows
`[0.000000] Command line: ... --firecracker-init ...` confirming a fresh microVM boot,
not a process-level kill.

## Open questions

- Whether the owner wants qwen and deepseek launched now anyway (accepting the OOM
  recurrence risk this task explicitly avoided) or held until a cohort-1 slot frees
  (gemini, 73/100 and the fastest riser, is closest to completion and would free the
  most memory first).
- Whether a longer-term fix (bounding `WikidataClient`'s in-memory cache, e.g. an LRU
  cap or periodic eviction) is worth a follow-up ticket — this task deliberately did
  not touch pipeline code per its own constraint, so the unbounded-growth root cause
  remains unfixed and will recur on any sufficiently long run.
- Whether this container's structural inability to retain kernel/journal logs across a
  microVM reboot (no persistent journald, ring buffer reset on every boot) is worth
  flagging to whoever owns the sandbox infra — future incidents here will hit the same
  "no dmesg/journalctl proof available" wall.

## NOT done

- **Qwen and deepseek were not resumed** — deferred per the memory-budget decision
  above; both are still sitting at their pre-freeze progress (53/100, 60/100) with no
  process running against them.
- **No commit was made.** The 5 resumed runs' `progress.jsonl`/`calls.jsonl`/
  `pred.partial.jsonl` are being actively modified in the working tree, but per this
  repo's own documented protocol (both cited prior reports) a run directory is
  committed only on reaching `done: 100`, and none of the 5 has completed yet.
- **No code or spec change was made** to bound the unbounded `WikidataClient` cache
  growth that is the actual root cause — per the task's explicit instruction not to
  edit the pipeline, this incident will recur on a long enough run even after this
  recovery.
- **No literal kernel OOM-killer log line was obtained** — structurally unavailable on
  this container after a microVM reboot (see Decisions #1); the root-cause verdict is
  circumstantial, not a smoking-gun log.
- Did not continue polling cohort 1 beyond the required 8-minute verification window —
  ongoing health of the 5 resumed runs over the remaining hours to completion is not
  monitored by this task.
