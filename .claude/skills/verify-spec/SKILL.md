---
description: >-
  Aspect-based adversarial review of a spec/design doc (workflow step 2 Verify
  Spec). Orchestrator picks >=3 relevant aspects from the project aspects file,
  dispatches one fresh-context READ-ONLY subagent per aspect, aggregates
  structured findings (max severity), reworks the plan, applies the gate.
  Use when a spec or design document needs verification before writing-plans.
---

# /verify-spec — aspect-based spec review (step 2, read-only)

Input: spec path (from the argument; if absent — the newest one in `docs/superpowers/specs/`).

Algorithm (mechanics rules, findings format and severity scale live in `.claude/skills/verify-spec/aspects-catalog.md` — read it first):

1. Read the project aspects file `docs/superpowers/review-aspects.md`. Missing → generate it per the catalog procedure (and commit), then continue.
2. Pick **at least 3** aspects relevant to the spec content. Record the chosen and the skipped ones with one-line reasons.
3. One subagent per chosen aspect — `model: sonnet`, effort medium, **read-only tools** (Read/Glob/Grep/WebFetch/WebSearch — no Write/Edit, no runs). The task is self-contained: spec path, the aspect's spec questions from the project file, the findings format from the catalog. Launch all agents in parallel.
4. Aggregate per the catalog rules (dedup, max severity, "agents disagree").
5. Rework the spec/plan from the aggregate (mandatory step) — changes go into the spec text, forks into the D-journal.
6. Gate: unresolved CRITICAL/HIGH → rework the spec and re-run the affected aspects; otherwise → writing-plans.

Output: findings aggregate + the list of spec changes + the gate decision. Owner-facing summary in Russian.
