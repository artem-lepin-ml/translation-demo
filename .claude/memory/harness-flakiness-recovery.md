---
name: harness-flakiness-recovery
description: "Recovery patterns for transient harness failures (Bash safety classifier outage, mid-stream agent deaths)"
metadata: 
  node_type: memory
  type: project
  originSessionId: 885fa765-6e1c-44ca-879b-c279775013c1
---

Two transient failure modes seen on 2026-07-06 (local Claude Code, this project) and their working recovery:

- **Bash safety classifier outage** ("claude-opus-4-8[1m] is temporarily unavailable... auto mode cannot determine the safety of Bash"): only non-allowlisted Bash stalls; read-only ops and commands matching `.claude/settings.json` permissions.allow (git status/log/diff/add/commit/switch/worktree, npm, uv...) keep working. Recovery: keep doing allowlisted/read-only work or dispatch to subagents, retry the blocked command after ~30–60 s. Note: allowlist entries match by command PREFIX — `git -C <path> log` does NOT match `git log *`; run from the right cwd instead.
- **Background agents dying mid-stream** ("Response stalled mid-stream" / "Server error mid-response" / "Not logged in"): the work usually survived up to the crash point. Recovery: `SendMessage` to the same agentId with "resume from step N, check idempotently what already happened" — resumed agents keep their context and finish fine.
- **SendMessage to a BUSY agent gets mistaken for prompt injection**: a mid-task SendMessage is delivered embedded inside an unrelated tool result with no channel markers, and a well-trained subagent correctly refuses it as injected text (seen twice on 2026-07-06). Recovery: wait until the agent stops, then resume via SendMessage (a resume arrives as a proper user turn and is trusted); acknowledge its vigilance and restate the instruction. Rule of thumb: never send mid-task extensions to busy agents — queue them for the resume.

**Why:** these are infra flakes, not task errors — don't redo completed work, don't treat them as code failures.
**How to apply:** on any background-agent failure notification, first read its last result line to find the crash point, then resume via SendMessage; see [[prod-server-ops]] for the deploy chain this protected.
