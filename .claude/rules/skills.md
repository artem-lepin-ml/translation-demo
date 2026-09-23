# Skill invocation taxonomy

Durable classification of every skill under [.claude/skills/](../skills/) into
user-invoked vs. model-invoked, referenced from the repo-root
[CLAUDE.md](../../CLAUDE.md) (§ Agents, skills & docs lookup). Purpose: keep
orchestration explicit — know which skills are workflow entry points an
orchestrator/human deliberately triggers, versus which ones the model may
fire on its own mid-task as a helper.

## The rule

**User-invoked skills orchestrate and may call model-invoked skills; a
user-invoked skill never calls another user-invoked skill.**

## Classification

18 dirs currently under `.claude/skills/`; 16 of them have their own `SKILL.md` (`lessons/` and `superpowers/` are support dirs without one, not standalone skills).

| Skill | Class | Trigger / role |
|---|---|---|
| `grill-with-docs` | User-invoked | `disable-model-invocation: true` in frontmatter (owner-fixed) |
| `grilling` | User-invoked | Owner-fixed; relentless plan/design interview the user deliberately starts |
| `handoff` | Model-invoked | Owner-fixed; compacts the running conversation into a W7 doc, fires as a helper near context/session end rather than as a process stage |
| `looper` | User-invoked | `disable-model-invocation: true` in frontmatter; scaffolds a whole agent loop, a deliberate one-off setup action |
| `playwright-cli` | Model-invoked | No `disable-model-invocation` flag and no process stage of its own — CLAUDE.md lists it under "Useful skills & MCP" as the preferred *mechanism* the `e2e-tester` agent (or any browser task) reaches for mid-task, not a process stage of its own |
| `report-gen` | User-invoked | Invoked deliberately when an HTML report is due (owner request or a large feature) to assemble the report deliverable |
| `superpowers-brainstorming` | User-invoked | Large-feature brainstorm stage, CLAUDE.md § Process |
| `superpowers-dispatching-parallel-agents` | User-invoked | Large-feature execute stage, CLAUDE.md § Process — a deliberate strategy choice for 2+ independent tasks |
| `superpowers-finishing-a-development-branch` | User-invoked | Finishing a branch, CLAUDE.md § Branches & worktrees |
| `superpowers-subagent-driven-development` | User-invoked | Large-feature execute stage, CLAUDE.md § Process |
| `superpowers-systematic-debugging` | Model-invoked | Description reads as an ambient helper trigger ("Use when encountering any bug... before proposing fixes"); CLAUDE.md § Process names it for the large-feature fix loop, but the skill itself auto-fires whenever a bug/failure surfaces |
| `superpowers-using-git-worktrees` | User-invoked | The entry action for the per-task isolation model in § Branches & worktrees |
| `superpowers-writing-plans` | User-invoked | Large-feature plan stage, CLAUDE.md § Process |
| `to-issues` | User-invoked | Owner-fixed; `disable-model-invocation: true` in frontmatter |
| `verify-pr` | User-invoked | Large-feature verify stage, CLAUDE.md § Process |
| `verify-spec` | User-invoked | Large-feature spec-review stage, CLAUDE.md § Process |

## Not yet vendored

`improve-codebase-architecture` was **blocked** in supply-chain review — its
HTML report performs a runtime CDN fetch — and is therefore **not vendored**
into `.claude/skills/`. Once remediated it will be classified **user-invoked**
(an explicit architecture-review entry point, not an ambient helper).
