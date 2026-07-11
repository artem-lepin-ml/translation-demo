# ml-engineer report — single-run diagnostic: gemma-4-31b-it wiki-eval stall

Focused diagnostic on ONE detached run:
`reports/terminology/wiki-eval/google--gemma-4-31b-it--WandB/111/2026-07-10T20-20-09Z`,
reported stuck at `done=24` ("Дауния") since ~02:25Z. No other run was touched.

## Scope

1. Determine whether the run's process (PIDs 12154/12159 from the prior babysit
   session) is alive; read the log tail.
2. Apply the decision rule: same deterministic `LengthOverflowError` crash at
   article "Веды" again → park (no resume, no code patch, document in
   `docs/known_issues.md`); alive-but-slow or a crash at a different point →
   one `--resume` relaunch, verify a new progress line within a bounded ~5 min
   window.
3. Report process state, log findings, action taken, resulting state.

## Decisions & rationale

1. **Confirmed the process was dead, not merely slow.** `ps` found zero
   processes matching PIDs 12154/12159 or any `wiki_eval.py` command at
   03:03:40Z. `free -h` showed 13Gi free (no system-wide memory pressure);
   `dmesg`/`journalctl -k` had no post-boot entries available in this sandboxed
   VM (kernel ring buffer only retains boot messages here), so an OOM-kill or
   external `SIGKILL` could not be confirmed or ruled out from kernel logs —
   only inferred from the silent-death log pattern below.

2. **This was NOT a repeat of the same "Веды" `LengthOverflowError` crash loop**
   — the deciding evidence:
   - `calls.jsonl` (555 lines total) contains the historical `LengthOverflowError`-triggering
     call for `article='Веды' paragraph=3` at `2026-07-10T22:51:15Z` (`finish_reason: 'error'`,
     `content_len: 0`) — this is the **old** crash from before the prior
     babysit session's 02:16Z resume, already documented.
   - After that 02:16Z resume, the run **did not revisit "Веды"** — it
     completed a *different* article, "Дауния" (`done: 23→24`), the very
     article the task description names as the last completed one. So the
     resume succeeded past whatever caused the historical "Веды" crash before
     stalling again on a later, unnamed article (#25 in this run's order,
     never named because it never completed — `pred.partial.jsonl`'s last
     unique title is still "Дауния").
   - `calls.jsonl` has **no new `finish_reason: 'error'` entries after
     line 334** (the historical Веды error at 22:51:15Z). The last logged
     call (line 555, `2026-07-11T02:30:54Z`) is a clean, successful
     `finish_reason: 'stop'`.
   - The scratchpad log the prior session redirected this resume's stdout+stderr
     to, `full_gemma4_resume5.log`, is **0 bytes** — unlike the two earlier
     crashes (`resume1.log` 4173 B, `resume4.log` 4812 B, both containing full
     Python tracebacks). A clean unhandled-exception exit (the `LengthOverflowError`
     path) always flushes a traceback to stderr before the interpreter exits; a
     0-byte log after ~14 min of file activity is the signature of an external
     `SIGKILL` (no traceback opportunity), not a repeat of the Р15 gate.
   - Conclusion: dead process, different (unconfirmed, non-Р15) failure mode,
     different point in the corpus than the previously-documented "Веды" crash
     → decision-rule branch 2 (resume), not branch 1 (park).

3. **Relaunched with the exact documented flags**, unchanged, per
   `docs/reports/ml-engineer-wiki-eval-5model-parallel-run.md`'s "Resume
   commands" section (`--wikidata-cache reports/terminology/wikidata_cache_gemma4.jsonl
   --wikidata-workers 2 --resume <same dir>`, `--max-usd 3.0`). Spend at
   relaunch time was `$0.518/$3.0` — well inside the cap, no reason to change it.

4. **API key sourced from the scratchpad fallback env file and exported
   inline**, never printed or logged (per task instruction and the repo's
   secrets invariant).

5. **Verification used bounded polling, never open-ended sleep** — a
   `timeout 300 … while … sleep 30 …` loop backgrounded by the Bash tool's own
   2-min auto-background behavior, cross-checked with direct one-shot `ps`/`wc -l`/`tail`
   calls every ~15-30 s over a ~7.5 min window (03:07:20Z launch → 03:14:48Z
   last check).

## Process state (verified)

- **Before action (03:03:40Z):** no process alive for PIDs 12154/12159 or any
  `wiki_eval.py` command — confirmed dead.
- **Action:** one `--resume` relaunch at ~03:07:20Z (new PIDs: wrapper 11918,
  `uv run` 11920, actual interpreter 11926).
- **After action (03:14:48Z, ~7.5 min later):** PID 11920 alive
  (`etime 07:21`, state `S`/`Sl`), `calls.jsonl` grew steadily and
  monotonically 555 → 582 lines (27 new extract calls), **every new call
  `finish_reason: 'stop'`** (no errors, no Length-gate hits). No new
  `progress.jsonl` line landed yet within the observation window — expected
  given WandB's documented per-call latency (up to ~290 s observed in this
  same window; historically up to ~490 s per the source report) multiplied
  across however many paragraphs the current (unnamed, uncompleted) article
  has; this matches the already-documented WandB latency profile, not a new
  anomaly.

## Log tail findings

- `full_gemma4_resume5.log` (prior session's redirect target for the run that
  just died): 0 bytes — no traceback captured, consistent with an external
  kill rather than an unhandled Python exception.
- `calls.jsonl` tail before relaunch: last entry `2026-07-11T02:30:54Z`,
  `finish_reason: 'stop'` (clean, successful call) — the file was not
  truncated mid-write.
- The **only** `LengthOverflowError`/`finish_reason: 'error'` evidence in the
  entire `calls.jsonl` for "Веды" is the single historical entry at
  `2026-07-10T22:51:15Z` (`article='Веды' paragraph=3`, matches
  `full_gemma4_resume4.log`'s captured traceback) — from **before** the prior
  session's 02:16Z resume, not from this stall.
- New resume's log (`full_gemma4_resume6.log`, this session): growing
  normally with successful `stop`-finish extract calls; no errors as of last
  check.

## Action taken

One `--resume` relaunch into the same run directory, same flags as previously
documented, API key sourced from scratchpad (not logged). No code touched, no
`docs/known_issues.md` entry added (the park branch's precondition — a
repeat deterministic Веды/Р15 crash — was not met), no commit made.

## Resulting run state

Alive and progressing as of `2026-07-11T03:14:48Z`: PID 11920 (`etime 07:21`),
`calls.jsonl` at 582 lines and climbing, all-`stop` finish reasons,
`progress.jsonl` still at `done=24` ("Дауния") pending the in-flight article's
completion. Spend well under the `$3.0` cap. Left running in the background,
untouched, at session close — same continuation model as prior babysit
sessions.

## Open questions

- What exactly killed the process between `02:30:54Z` and the ~03:03Z check
  (silent death, 0-byte log, no kernel-level OOM evidence obtainable in this
  sandboxed VM)? Not resolved — flagged for the next babysit/owner review if
  it recurs. If the *same* silent-kill pattern repeats on this fresh PID, that
  would itself become a new, distinct pattern worth a `known_issues.md` entry
  (external kill, not Р15) — not raised now since it has only been observed
  once.
- Which article is #25 in this run's corpus order (the one that was in flight
  when the process died, and is in flight again now)? Not determined — it
  never completed, so its name never reached `progress.jsonl` or
  `pred.partial.jsonl`. Not needed for the decision (the decision rested on
  the *absence* of a fresh Веды/Р15 signature, not on identifying the new
  article).

## NOT done

- Did not touch any of the other 3 extraction runs (gemini, qwen, deepseek) or
  the 3 judge runs — out of scope per the task instruction.
- Did not patch `scripts/wiki_eval.py` or loosen the Р15 length gate — no code
  changes at all, consistent with "pipeline frozen" guidance and this task's
  own remit.
- Did not add a `docs/known_issues.md` entry — the park branch's trigger
  condition (repeat deterministic crash at the same article "Веды") was not
  observed this cycle.
- Did not wait for the relaunched run to reach a new `progress.jsonl` line —
  the bounded ~7.5 min verification window closed with the process
  demonstrably alive and healthy (27 consecutive successful calls) but before
  the in-flight article's full paragraph set completed. Did not extend the
  wait further, per "bounded loop" instruction.
- Did not commit anything — no repository files were changed by this task.
