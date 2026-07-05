---
name: handoff
description: Compact the current conversation into a W7 continuity handoff document for another agent to pick up.
argument-hint: "What will the next session be used for?"
---

Write a handoff document summarising the current conversation so a fresh agent can continue the work. Save it to `.claude/session-context/HANDOFF.md` (create the `.claude/session-context/` directory first if it does not exist yet) — this is a checked-in, repo-local continuity file, not a scratch file, so overwrite it in place rather than timestamping a new one.

Structure the document using this repo's W7 continuity format:

- **Slug + route** — the task's `feat/<topic>` slug and its route size (S/M/L).
- **Ticket-queue status** — which tickets/steps are done, in progress, or still open.
- **Last decision** — the most recent consequential decision made and why.
- **Next action** — the single next concrete step the picking-up agent should take.
- **Open gotchas** — anything non-obvious the next session needs to know to avoid repeating a mistake or re-deriving a finding.
- **Suggested skills** — which skills the next agent should invoke, and when.

Do not duplicate content already captured in other artifacts (specs, plans, ADRs, issues, commits, diffs). Reference them by path or URL instead of copying their content in.

Redact any sensitive information, such as API keys, passwords, or personally identifiable information.

If the user passed arguments, treat them as a description of what the next session will focus on and tailor the doc accordingly.
