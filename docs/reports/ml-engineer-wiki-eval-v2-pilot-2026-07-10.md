# wiki-eval v2 smoke + pilot mission — agent report (FINAL)

Task: docs/superpowers/specs/2026-07-10-wiki-eval-experiment-v2.md §5 (smoke +
pilot phases), branch `claude/ner-translation-config-b0ozsc`. The owner-facing
evidence deliverable is
[docs/reports/wiki-eval-v2-pilot-2026-07-10.md](wiki-eval-v2-pilot-2026-07-10.md)
(the mission's mandated "Deliverable"); this file is the agent-process report
(Scope/Files changed/Decisions/Open questions/NOT done).

## Scope

Run Phase 0 (smoke) through Phase 4 (v3 scoring sanity) of the approved
experiment, staying under $1.20 total spend, without touching `src/`,
`scripts/`, or `tests/`, and without committing anything. Mid-mission, the
orchestrator reviewed my Phase 0 gemma finding and issued a follow-up
instruction to proceed through all 5 phases (gemini pilot -> gate_check ->
deepseek mini-pilot -> gemma smoke retry + mini-pilot -> v3 scoring sanity),
which this session executed in full.

## Files changed

None in `src/`, `scripts/`, or `tests/`. Two report files under
`docs/reports/` (not committed, per instruction):
- `docs/reports/wiki-eval-v2-pilot-2026-07-10.md` — full evidence deliverable
  (all 5 phases, gate tables, cost extrapolation, anomalies).
- `docs/reports/ml-engineer-wiki-eval-v2-pilot-2026-07-10.md` — this file.

Real run artifacts were produced under `reports/terminology/wiki-eval/`
(existing, git-tracked directory used by every prior wiki-eval run — these
new run dirs are new files in an existing structure, not repo edits, and
were left un-added/un-committed per instruction):
- `reports/terminology/wiki-eval/google--gemini-3.1-flash-lite--Google-AI-Studio/111/2026-07-10T08-31-04Z/`
  (Phase 1 pilot: `calls.jsonl`, `pred.jsonl`, `meta.json`, plus Phase 2's
  `gate_check_result.json` and Phase 4's `metrics.json`/`report.html`).
- `reports/terminology/wiki-eval/deepseek--deepseek-v4-flash--Novita/111/2026-07-10T08-38-16Z/`
  (Phase 3a, HALTED — `calls.jsonl`/`pred.partial.jsonl`/`progress.jsonl`
  only, no `meta.json`/`pred.jsonl` since the run crashed before reaching
  its final-write step).
- `reports/terminology/wiki-eval/google--gemma-4-31b-it--WandB/111/2026-07-10T08-52-00Z/`
  (Phase 3b mini-pilot: full `calls.jsonl`/`pred.jsonl`/`meta.json`/
  `gate_check_result.json`).

Scratchpad (`$SCR`, not committed, not part of the repo):
- `smoke_v2.py` — the `--models` filter (added earlier in the mission) used
  this turn to re-run gemma-only smoke once more.
- `gate_check.py` — used as designed against both the gemini pilot
  (`--extrapolate`) and the gemma mini-pilot; NOT run as-is against the
  deepseek mini-pilot (no `meta.json` — see below), so that gate table was
  computed with an ad hoc one-off Python snippet instead.
- New logs: `smoke_v2_gemma_attempt1.log`, `pilot_gemini_run.log`,
  `minipilot_deepseek_run.log`, `minipilot_gemma_run.log`, plus small
  tracking files (`pilot_gemini_rundir.txt`, `minipilot_deepseek_rundir.txt`,
  `minipilot_gemma_rundir.txt`, `gemma_retry_attempt1_start.txt`).

## Decisions & rationale

1. **Followed the orchestrator's ruling on the WandB 429 exactly**: no pin
   change, retried with up to 2 attempts spaced ~5 minutes (only needed 1;
   the retry succeeded 6/6 after ~8 minutes' total gap since the last
   failure, well past the ~5-minute spacing floor).
2. **Did not retry or resume the deepseek mini-pilot after its halt** — the
   halting exception (`json.decoder.JSONDecodeError` from `httpx`'s
   response parsing) is not one of the three documented halt types
   (`LengthOverflowError`/`CallGateError`/`BudgetExhaustedError`), but the
   mission's underlying principle ("diagnosis is the orchestrator's job")
   clearly applies to any unexpected halt, not just the three named ones.
   I traced the root cause as far as I could without touching `src/`
   (confirmed `is_transient_error` doesn't classify a `JSONDecodeError` as
   retry-worthy, so the failure propagated immediately with zero retries)
   and reported it as a finding rather than guessing at a fix.
3. **Computed the deepseek mini-pilot's partial gate evidence manually**
   instead of running `gate_check.py` against it, since that script
   requires `meta.json` (only written by `cmd_run` at successful
   completion) and this run never reached that point. A one-off Python
   snippet over the 90 captured `calls.jsonl` lines gives the same 4
   gate numbers on the calls that DID complete.
4. **Reported deepseek's mini-pilot as HALTED, not as a fresh mission-stop
   trigger** — unlike Phase 0's gemma question (where I paused and asked),
   here the orchestrator's dispatch message already covered this contingency
   implicitly (Phase 3b is independent of 3a's outcome, and Phase 4 only
   depends on the Phase 1 gemini pilot), so I proceeded through the
   remaining phases and surfaced the halt as a reported finding rather than
   stopping the whole mission a second time. If this reading was wrong, it
   is easy to correct: nothing downstream of Phase 3a depended on its
   output.
5. **Left gemini's dry-run cost estimate ($0.0724) in the deliverable only
   as a reference** — it is the CLI's flat gpt-4o-mini-based estimator, not
   the real reasoning-inclusive cost; the real pilot cost ($0.4894) is
   reported as the authoritative number throughout.

## Open questions

1. Root cause of the deepseek/Novita malformed-JSON response — genuinely
   transient (worth widening `is_transient_error`'s classification) or a
   real API contract issue on Novita's side under certain conditions? Not
   determined; flagged for the code owner.
2. Whether the orchestrator wants the deepseek mini-pilot re-attempted (a
   simple `run` retry, no code change needed, would very likely just
   complete cleanly given the failure looked like a one-off transport
   glitch and every call before/after the crash point was healthy) — left
   as an owner decision since the mission's explicit instruction was not to
   retry/resume without direction.

## NOT done (explicit)

- Deepseek mini-pilot article 3/3 — not completed; no retry attempted
  (explicit instruction). 2/3 articles' worth of clean evidence exists.
- Full 3×100-article production runs — intentionally out of scope for this
  pilot mission (next step after owner sign-off on this report).
- Any `src/`/`scripts/`/`tests/` change to address the deepseek transport
  reliability gap — flagged as a finding only, per the "do not touch
  src/scripts/tests" constraint.
- Nothing committed, per instruction.
