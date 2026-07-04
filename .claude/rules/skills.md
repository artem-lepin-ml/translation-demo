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

17 skill dirs currently under `.claude/skills/`, each with a `SKILL.md`.

| Skill | Class | Trigger / role |
|---|---|---|
| `graphify` | User-invoked | Frontmatter declares an explicit `trigger: /graphify` slash command; also the named entry point for codebase/doc questions and the step-8 `--update` call |
| `grill-with-docs` | User-invoked | `disable-model-invocation: true` in frontmatter (owner-fixed) |
| `grilling` | User-invoked | Owner-fixed; relentless plan/design interview the user deliberately starts |
| `handoff` | Model-invoked | Owner-fixed; compacts the running conversation into a W7 doc, fires as a helper near context/session end rather than as a numbered process step |
| `looper` | User-invoked | `disable-model-invocation: true` in frontmatter; scaffolds a whole agent loop, a deliberate one-off setup action |
| `playwright-cli` | Model-invoked | No `disable-model-invocation` flag and no numbered process step of its own — CLAUDE.md lists it under "Useful skills & MCP" as the preferred *mechanism* the `e2e-tester` agent (or any browser task) reaches for mid-task, not something the orchestrator names as its own step |
| `report-gen` | User-invoked | Description self-declares "Use at workflow steps 6 (Verify) and 8 (Finish)" — an explicit tie to named process steps, invoked to assemble the final report deliverable |
| `superpowers-brainstorming` | User-invoked | Process step 1 ("Brainstorm"), named explicitly in CLAUDE.md § Process |
| `superpowers-dispatching-parallel-agents` | User-invoked | Named explicitly in CLAUDE.md § Process ("swarm via dispatching-parallel-agents") and § Dynamic workflow as the orchestrator's deliberate strategy choice for 2+ independent tasks |
| `superpowers-finishing-a-development-branch` | User-invoked | Process step 8 ("Finish"), named explicitly in CLAUDE.md § Process |
| `superpowers-subagent-driven-development` | User-invoked | Process step 5 ("Execute"), named explicitly in CLAUDE.md § Process |
| `superpowers-systematic-debugging` | Model-invoked | Description reads as an ambient helper trigger ("Use when encountering any bug... before proposing fixes"); process step 7 references it but the skill itself auto-fires whenever a bug/failure surfaces, not only at that numbered step |
| `superpowers-using-git-worktrees` | User-invoked | Process step 4 ("Branch + worktree"), named explicitly in CLAUDE.md § Process, and the entry action for the per-task isolation model in § Branches & worktrees |
| `superpowers-writing-plans` | User-invoked | Process step 3 ("Plan"), named explicitly in CLAUDE.md § Process |
| `to-issues` | User-invoked | Owner-fixed; `disable-model-invocation: true` in frontmatter |
| `verify-pr` | User-invoked | Process step 6 ("Verify"), named explicitly in CLAUDE.md § Process |
| `verify-spec` | User-invoked | Process step 2 ("Verify Spec"), named explicitly in CLAUDE.md § Process |

## Not yet vendored

`improve-codebase-architecture` was **blocked** in supply-chain review — its
HTML report performs a runtime CDN fetch — and is therefore **not vendored**
into `.claude/skills/`. Once remediated it will be classified **user-invoked**
(an explicit architecture-review entry point, not an ambient helper).
