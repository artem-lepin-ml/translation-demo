# docs-keeper report: amend setsid-detach known-issue entry (container recycle evidence)

## Scope

Small doc-only amendment on branch `claude/ner-translation-config-b0ozsc` (shared worktree). Task: extend
the existing `docs/known_issues.md` entry "Background pollers launched with plain `nohup ... & disown` die
when the cloud session's shell is torn down (2026-07-09)" (added in commit `c1d0289`) with new evidence that
`setsid`-detached session leaders also do not survive a cloud-container (firecracker microVM) recycle.
Selective staging only: `docs/known_issues.md` + this report. No changes to `reports/**`, scratchpad, or
other agents' files.

## Files changed

- [docs/known_issues.md](../known_issues.md) — appended an "Amendment (2026-07-09)" paragraph to the existing
  poller entry, in place, same section, matching the entry's English/B2 style. No new section header was
  added — this is an extension of the existing fact, not a new fact, to keep single-source-of-truth intact.

## Decisions & rationale

- **Amended in place rather than adding a new entry.** The new evidence doesn't contradict the original
  `setsid` finding (session-teardown detach) — it narrows its scope (doesn't survive container reclaim). Per
  the layered-docs convention, one fact should live in one place; a second near-duplicate entry would fork
  the truth. Amending keeps the full picture (shell-teardown case + container-recycle case) together.
- **Cited the primary evidence file** ([reports/debugger-poller-silence-diagnosis.md](debugger-poller-silence-diagnosis.md))
  by link rather than copying its data (uptime, PIDs, timestamps) — link-not-copy per convention. Only the
  minimal facts needed to state the conclusion were paraphrased inline (PIDs 6778/26112, reboot time
  09:13:49Z, ~191s uptime, `PID 1 = /process_api --firecracker-init`, scratchpad writes clustered
  08:51:27–46Z).
- **Ended with an actionable rule** ("resume-safe on disk... driven by externally re-armed checks... never by
  a background process assumed to keep running unattended") matching the operator's requested phrasing and
  the existing entry's pattern of ending each item with a durable, actionable takeaway.
- Verified the referenced report exists on disk (`docs/reports/debugger-poller-silence-diagnosis.md`, 6780
  bytes, present) before linking it — did not fabricate the citation.

## Verified code↔doc pairs

This is a docs-only amendment; no code changed. The "pair" verified here is doc↔evidence-report:

| Doc claim | Evidence source |
|---|---|
| Firecracker microVM reclaimed/rebooted at 09:13:49Z after inactivity | `docs/reports/debugger-poller-silence-diagnosis.md` (`uptime -s`, `/proc/uptime` ≈191s) |
| Two setsid-detached session-leader pollers (PIDs 6778, 26112) killed by the recycle, not by a crash | Same report — process table wiped, no OOM traces, both were `PPID=1` session leaders per the original entry's verification pattern |
| Disk/scratchpad survived the recycle | Same report — scratchpad files' last writes clustered 08:51:27–46Z, before the 09:13:49Z reboot |
| `docs/reports/debugger-poller-silence-diagnosis.md` exists and is linkable | Confirmed present on disk in this worktree (6780 bytes) |

## Open questions

None — this was a bounded factual amendment with a fully specified evidence report to cite.

## NOT done (explicit)

- Did not touch any other file besides `docs/known_issues.md` and this report (no changes to `reports/**`
  content, scratchpad, or other agents' in-progress files), per the selective-staging instruction.
- Did not re-verify the underlying `debugger-poller-silence-diagnosis.md` report's raw evidence myself
  (uptime output, PID list) — took it as given per the task instruction; the report's existence and byte
  size were confirmed, but its internal claims were not independently re-derived.
- Did not restructure or split the known-issues entry into separate sections — kept it as a single amended
  entry per the "amend in place" instruction.
