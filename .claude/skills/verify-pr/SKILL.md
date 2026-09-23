---
description: >-
  Aspect-based final verification of a PR/feature (verify stage of a large feature).
  Orchestrator picks >=5 relevant aspects from the project aspects file,
  dispatches one fresh-context subagent per aspect with FULL execution rights
  (write and run unit/integration tests, inspect code, data and DB, exercise
  contracts), aggregates structured findings into the 360 HTML report, applies
  the gate. Browser e2e is NOT included here - it is done by the e2e-tester
  agent invoked separately at the same step. Use when a PR/feature needs final
  verification before finish.
---

# /verify-pr — final aspect-based PR verification (large-feature verify stage)

Input: PR diff/branch (from the argument; default — the current feature branch against main).

Algorithm (mechanics rules, findings format and severity scale live in `.claude/skills/verify-spec/aspects-catalog.md` — read it first; it is the single source of truth, do not copy it):

1. Read the project aspects file `docs/superpowers/review-aspects.md`. Missing → generate it per the catalog procedure (and commit), then continue.
2. Pick **at least 5** aspects relevant to the PR content. Record the chosen and the skipped ones with reasons.
3. One subagent per chosen aspect — `model: sonnet`, effort medium (system layer / data at high complexity — `model: opus`), with **full execution rights**: write and run unit/integration tests, read code and real data/DB, exercise contracts with live calls. The task is self-contained: diff/branch, the aspect's PR checks, the findings format. Launch in parallel. IMPORTANT: runs only against the project's isolated/test DB (see the project CLAUDE.md), never against dev data.
4. Browser e2e is NOT part of this skill: at the same step the orchestrator separately runs the `e2e-tester` agent and, after it, the audit subagent (PASS/FAIL gate).
5. Aggregate per the catalog rules; per-aspect axis scores → the 360 diagram in the HTML report (report format — per the owner's rules in CLAUDE.md, in Russian, served locally).
6. Plan rework (mandatory step) → gate: unresolved CRITICAL/HIGH → fix the root causes, then re-run this skill from a clean slate; otherwise → finish (docs-keeper parity check, report, PR).

Output: findings aggregate + the 360 HTML report + the gate decision. Owner-facing report in Russian.
