# ml-engineer report — wiki-eval extraction-run babysitting (stall recovery)

Branch: `claude/ner-translation-config-b0ozsc`. Emergency babysit lane for the 4
detached wiki-eval NER extraction runs left in progress by
`docs/reports/ml-engineer-wiki-eval-5model-parallel-run.md`. Confirmed stall
report: qwen run frozen at 50/100 ($1.276) since ~01:44Z. This task checked all
4 extraction runs (not touching the 3 judge runs unless also stalled), killed
and relaunched dead processes with `--resume`, and verified progress resumed.

## Scope

Check `progress.jsonl` mtime + owning process state (`ps`) for each of the 4
in-flight extraction runs (qwen, gemini-3.1-flash-lite, gemma-4-31b-it,
deepseek-v4-flash). Any stalled >10 min or with a dead process: kill leftovers,
relaunch with `--resume` into the same run dir using the exact flags documented
in the source report. Verify each resumed run produces a new progress line
within a bounded wait (no open-ended sleep). Diagnose the qwen stall's root
cause from its log. Check the 3 co-running judge runs' freshness only as a
guard condition (not otherwise in scope). No code changes, no commits.

## Files changed

None. This was a pure operational/process-babysitting task — no repository
files were edited. The only state changes are external to git: killed dead
background processes (none were actually alive to kill — see below) and
launched 2 new detached background processes continuing pre-existing run
directories under `reports/terminology/wiki-eval/` (gitignored/uncommitted
checkpoint data, not part of this report's diff).

## Decisions & rationale

1. **Checked all 4 runs' `progress.jsonl` mtime + `ps` before acting on any of
   them**, rather than trusting the task prompt's stall claim blindly for qwen
   alone. This surfaced a second, unflagged dead run (gemma-4-31b-it, frozen
   since 2026-07-10T23:52:02Z, ~2h33m stale) that the task description didn't
   call out — worth flagging since the prompt only named qwen as "CONFIRMED
   STALL."

2. **Both qwen and gemma-4-31b-it had actually crashed (process exited), not
   hung.** `ps -eo pid,cmd | grep -i "qwen"` / `grep -i "gemma-4-31b"` returned
   zero processes for either — no PID to kill. This matters for the recovery
   action: there was nothing to `kill`, only to relaunch. Confirmed via the
   session's own scratchpad logs (`full_qwen36_resume3.log`,
   `full_gemma4_resume4.log`), whose mtimes exactly match each `progress.jsonl`
   freeze point, that both processes terminated with an unhandled exception
   (tracebacks in both, not silent kills / OOM signatures).

3. **Relaunched with the exact flags from the source report's "Resume
   commands" section** (`--wikidata-cache <per-model file>`,
   `--wikidata-workers 2`, `--max-usd` unchanged since real spend at time of
   stall was well under each run's ceiling: qwen $1.276/$3.0, gemma4
   $0.478/$3.0). Did not change any flag, per the instruction to relaunch
   "same flags as documented" — this preserves the already-diagnosed
   429-storm/OOM mitigations from the source report rather than re-deriving
   them.

4. **Left gemini-3.1-flash-lite and deepseek-v4-flash untouched.** Both had
   fresh `progress.jsonl` mtimes (within 1-3 min of the check) and live PIDs
   with matching `--resume` args — healthy, actively progressing, no action
   warranted.

5. **Left all 3 judge runs (`23-40-53Z` dirs: baseline/alt-names/label-guess)
   untouched.** Checked their `calls.jsonl`/`progress.jsonl` mtimes twice
   (02:15Z and 02:24Z) — both passes showed writes within the preceding
   30-60 seconds, well inside the 10-min stall threshold. No relaunch
   triggered, per the instruction to only touch them if independently
   stalled.

6. **Verification via bounded polling loops (`timeout N bash -c 'while ...;
   sleep 60|30; done'`), never open-ended sleep.** The orchestrating Bash tool
   itself has a 2-minute default cutoff that auto-backgrounds any longer-
   running command — used that (rather than fighting it) by letting bounded
   `timeout 570`/`timeout 300` polling loops run as background tasks and
   polling their output files, consistent with the "never open-ended sleep"
   constraint. Both resumed runs were confirmed to produce a new
   `progress.jsonl` line: qwen advanced 50→51 within ~5 min of relaunch;
   gemma-4-31b-it advanced 23→24 within ~9 min (slower, but still inside the
   WandB per-call latency range of 6-490s already documented in the source
   report — not treated as a fresh anomaly).

## Open questions

- Should `google/gemma-4-31b-it`'s `LengthOverflowError` halt at "Веды"
  paragraph=3 be looked at for a pattern similar to the deepseek
  "Ашшур (город)" reproducible double-miss documented in the source report?
  Not investigated here — out of this babysit task's remit (same as the
  source report's stance on not loosening Р15 under time pressure).
- The `client.py:153` malformed-response `TypeError` (Io Net) that killed the
  qwen run is still unpatched and will very likely recur on the next Io Net
  hiccup — same open question as flagged in the source report, now with one
  more real occurrence as evidence it's not a one-off.
- No owner decision was sought or made on the $12 budget ceiling question
  raised in the source report — real spend as of this check was still well
  under each individual run's `--max-usd` cap, so it wasn't blocking.

## NOT done

- **No code changes.** The `client.py:153` malformed-response handling and the
  `LengthOverflowError` gate (Р15) were not touched — both are known,
  previously-disclosed gaps, and fixing either is a bigger blast-radius
  decision than a babysit task's remit.
- **No commits.** Nothing in the git working tree changed; only detached
  background process state (external to git) changed.
- Did not aggregate or report category-distribution/mention-count figures for
  any of the 4 in-progress runs — out of scope, same as the source report's
  stance (not meaningful before completion).
- Did not raise `--wikidata-workers` or otherwise try to speed up any run
  beyond restoring the 2 dead ones to their documented resume state.
- Did not wait for full completion of any of the 4 runs — all were left
  running in the background at session close, same continuation model as the
  source report.

## Run artifacts (evidence)

Final process snapshot (`ps -eo pid,ppid,etime,stat,cmd`, 2026-07-11 02:25:41
UTC) showed all 7 `wiki_eval.py` processes alive: 4 extraction runs (gemini
PID 4781/4784, qwen PID 12153/12160 — relaunched, gemma4 PID 12154/12159 —
relaunched, deepseek PID 29747/29750) plus 3 judge runs (PID
10272/10278/10281, `etime` 01:09:04, unchanged/untouched).

Final `progress.jsonl` line counts at last check: qwen 51/100, gemini 68/100,
gemma4 24/100, deepseek 57/100 (all confirmed advancing from the stall-check
baseline of 50/66/23/55 respectively).

Qwen crash traceback (from `full_qwen36_resume3.log`, mtime
2026-07-11T00:28:04Z, matching the frozen `progress.jsonl`):
`TypeError: 'NoneType' object is not subscriptable` at
`src/palimpsest/llm/client.py:153` (`choice = resp.choices[0]`).

Gemma-4-31b-it crash traceback (from `full_gemma4_resume4.log`, mtime
2026-07-10T23:52:02Z, matching its frozen `progress.jsonl`):
`LengthOverflowError: extract call to 'google/gemma-4-31b-it' hit the
output-length limit ... article='Веды' paragraph=3`.
