# CLAUDE.md

Routing document for agents on **`dev-demo`** — the Palimpsest translation-evaluation demo. Product overview and quickstart in [README.md](README.md); the demo subsystem in [docs/subsystems/webapp.md](docs/subsystems/webapp.md); the API/data contract (single source of truth for wire DTOs, REST, SQLite DDL) in [docs/superpowers/specs/2026-06-30-demo-contracts.md](docs/superpowers/specs/2026-06-30-demo-contracts.md).

This file holds **both the project specifics** (branch topology, conventions, hard invariants, routing) **and the working methodology inline**: the language policy, the 8-step Scenario A/B process, model routing and the agent dispatch map, dynamic workflows, communication style and the HTML report template. The methodology lives here rather than in a separate `@`-imported doc because cloud sessions (claude.ai/code) must see it deterministically — an `@`-import of a process doc proved unreliable in the cloud, while `CLAUDE.md` itself always loads. Durable owner rules beyond both are still `@`-imported (those demonstrably load): @.claude/rules/invariants.md and @.claude/rules/working-style.md. All config (agents, skills, commands, hooks) is in-repo under `.claude/` so cloud sessions see it — nothing depends on a machine-local `~/.claude`. Facts that drift — the model list, evaluator criteria and weights, scores, the team — live in their own source of truth (config, DB, contract, README) and are never copied here. Placing a new rule: methodology/process → the relevant section here; a durable owner rule → `.claude/rules/`; never duplicate.

## Language policy

Think, plan and talk to subagents in English (token economy). ALL owner-facing output is in Russian: chat replies, reports (md / HTML / Claude artifacts), specs/plans, D-journal entries, flags to the owner. Project documentation (README, docs/, CLAUDE.md, agent/skill definitions) is written in English.

## Process

### Core concept
Spec-driven development. We craft a high-quality spec together; you then execute it fully autonomously (no interruptions, no check-ins). I review only specs, reviews and the docs/ documentation.

### Finding unknowns
Cross-cutting discovery playbook — turning unknown-unknowns into known-unknowns before/during/after implementation (blindspot pass, brainstorm/prototype, interview, references, implementation notes, pitch, quiz): [.claude/playbooks/finding-unknowns.md](.claude/playbooks/finding-unknowns.md). It underpins the 8-step flow rather than replacing it — the W-phases map onto the steps (W1–W5 → brainstorm/verify-spec/plan, W6 → execute, W7–W8 → verify/finish), and its unknowns taxonomy is the lens for deciding which step a task actually needs.

### Scenario A (I'm present and actively participating)

1. **Brainstorm** — [brainstorming](.claude/skills/superpowers-brainstorming/SKILL.md) (+ [visual-companion](.claude/skills/superpowers-brainstorming/visual-companion.md) when there is UI/UX/design). Spec → [docs/superpowers/specs/](docs/superpowers/specs/). Goal: a spec with goal, scope, success criteria and the most correct plan to reach the goal, honoring every subtlety of the task and my global vision.
2. **Verify Spec** — skill `/verify-spec`: the orchestrator picks ≥3 relevant aspects from `docs/superpowers/review-aspects.md` (the skill generates it if missing), one subagent = one aspect (fresh context, read-only), structured findings → aggregation (max severity, disagreements section) → mandatory spec/plan rework → gate (CRITICAL/HIGH → rework and re-review of the affected aspects).
3. **Plan** — first run `spec-expander` on the draft spec: it drafts missing sections against the review-aspects rubrics and flags OPEN gaps; the expanded spec is the planner input. Then [writing-plans](.claude/skills/superpowers-writing-plans/SKILL.md). Plan → [docs/superpowers/plans/](docs/superpowers/plans/). Work the spec out in more detail, down to a plan.
4. **Branch + worktree** — [using-git-worktrees](.claude/skills/superpowers-using-git-worktrees/SKILL.md). Branch `feat/<topic>` off `dev-demo`.
5. **Execute** — [subagent-driven-development](.claude/skills/superpowers-subagent-driven-development/SKILL.md) or a dynamic workflow. Parallelize independent task classes as much as possible. Remember tests and documentation. Every commit that changes a contract/behavior is accompanied by a `docs-keeper` call (doc-parity in the same commit).
<loop>
6. **Verify** — skill `/verify-pr`: the orchestrator picks ≥5 aspects from `docs/superpowers/review-aspects.md`; aspect agents with full rights write and run unit/integration tests, check code and data (isolated DB only). In parallel — a browser run by the `e2e-tester` agent + a mandatory audit of its report (Sonnet auditor, PASS/FAIL gate: provenance/screenshot failures send the run back). At Verify/Ship, also dispatch `docs-architect-l4` for any architecture-depth documentation (invariants/rationale/data-flow/failure-modes) — separate from `docs-keeper`'s L1→L4 parity check. Deliver the full PR-quality report per the **Reports** section (HTML, 360 diagram). Serious problems found → step 7; nothing critical and all scores positive → step 8.
7. **Fix** — [systematic-debugging](.claude/skills/superpowers-systematic-debugging/SKILL.md): carefully analyze the code and context, find the deep root cause and fix it. If the problem is systemic or complex, log it to docs/PROBLEMS.md; after finding all occurrences, run deep research + a tournament via dynamic workflow to find the best solution. After fixing everything, redo step 6 from a clean slate.
</loop>
8. **Finish** — run the `e2e-tester` agent (real data ONLY from the `docs/testing/e2e-data.md` manifest; the full user journey in the browser — e.g. the teacher's and the student's path, not DB-seeding via URL — for ALL scenarios described in the PR) + the audit of its report; then `docs-keeper` — final doc-parity check across the whole PR. Failure → back into the loop at step 6. Success → final HTML report per **Reports** in [docs/reports/](docs/reports/). If there is something to test, deploy a full test environment for me and await my tests and review. Approved → [finishing-a-development-branch](.claude/skills/superpowers-finishing-a-development-branch/SKILL.md), PR `feat/<topic>` → `dev-demo`. Not approved → understand why, improve step 6 so it would catch the problems I found, and return to step 6.

If the task is very large: decompose and execute with several parallel background agents — a swarm via [dispatching-parallel-agents](.claude/skills/superpowers-dispatching-parallel-agents/SKILL.md).

**My participation is needed only at steps 1, 2 and 8. All other steps run autonomously without me.**

### Scenario B (fully autonomous)

Applies when I write "работай полностью автономно" or "я отошел на X минут / часов" — you understand I cannot participate in the development process.

**All permissions are granted in this mode. Hanging or asking me anything = failure of your autonomy task.**

The pipeline is roughly the same as with me (scenario A), but you work on a large number of features over a long period (e.g. all night). I set a measurable goal, scope and the approximate expected result via goal. You build a path of concrete PRs and execute each through the 8 steps of scenario A, replacing me with your own higher-quality diligence.

You follow the same 8 steps as in scenario A, but instead of my decision-making at step 1 you run deep research and then a tournament via dynamic workflow and pick the best option fitting the project and my vision. To understand my vision, read my specs and documentation from the last 2 days; on conflict, documentation beats specs and newer versions beat older ones. At step 8 you replace my review with deeper tests aimed wider, and REAL simulation of my actions in the browser via playwright MCP. Steps 2/5/6/8 use the same skills and agents as scenario A: /verify-spec, docs-keeper, /verify-pr, e2e-tester with audit.

#### Recurring problems to watch for and avoid
I often find these problems in your browser testing:
- You get lazy about testing through the browser → nothing actually works in reality. Make sure you really test through the browser and write the widest, most realistic e2e tests; take and inspect screenshots (at least 10 per PR).
- You get lazy and do only the main scenario, forgetting the others. Make sure ALL scenarios are executed, not just the main one; that every button and transition works — as if a teacher and students were really using the platform. Finding a bug or a problem during e2e is a big win.
- You underdeliver while hours of time remain. I tell you to work 8 hours and you stop after 2 having "finished the tasks" — that's bad; there are surely still problems and bugs. If you finish early: rescan, recheck, run more e2e tests. If everything is truly done: clean legacy code in 2 passes (don't cling to garbage), find fresh data via web search, think up next features and implement them. Build new plans — develop the project in the direction I set. Never stop — I will come and stop you myself when needed.

### Review aspects
Canonical catalog of aspects, findings format and aggregation rules: `.claude/skills/verify-spec/aspects-catalog.md` (single source of truth). Project adaptation: `<repo>/docs/superpowers/review-aspects.md` (generated by the /verify-spec and /verify-pr skills; manual edits go into `<!-- custom -->` sections).

## Model routing & dispatch

### Agent usage (model routing)

| Task | Model | Effort |
|---|---|---|
| Orchestration (main session), brainstorm & spec writing, high-level research planning, decisions on how to fix findings, final aggregation & reports to the owner | Fable 5 | high |
| Deep research, systematic debugging (step 7), aspect-report aggregation by a subagent, code WITHOUT a ready plan (freeform/exploratory), security-critical code | Opus 4.8 (`model: opus`) | high → xhigh |
| ALL code written to a ready plan/spec (standard practice), unit tests, aspect reviewers (steps 2/6), documentation updates, docs-keeper, e2e report audits | Sonnet 4.6 (`model: sonnet`) | medium → high |
| Repo recon, search/grep, mechanical edits | Haiku 4.5 (`model: haiku`) | low |
| e2e-tester (browser runs) | Sonnet 4.6 (`model: sonnet` in agent frontmatter) | high |

Rules: (R1) subagents NEVER inherit the session model — set `model:` explicitly; aggregation is done by the orchestrator itself or a `model: opus` subagent; (R2) executors medium/high, aggregators high/xhigh — sparingly; (R3) Fable 5 may auto-reroute biology/cybersec-adjacent prompts to Opus 4.8 — if systematic, consciously switch the agent's model with a D-journal entry; (R4) escalation: Sonnet → Opus → Fable ("Fable — when the task would justify a senior contractor"); (R5) code: a ready plan/spec exists → ALWAYS Sonnet (not Opus and not Fable); no plan and the code is freeform → Opus.

### Dispatch map (task class → named agent)

**The orchestrator MUST pass the named agent type in Agent/Task calls; falling back to the generic agent is a protocol violation (and is what the P1.1 orchestrator write-gate's pressure is meant to prevent).** The gate (`.claude/hooks/orchestrator-write-gate.py`) blocks the main thread's own direct Edit/Write/Bash while orchestrating — its whole point is to force dispatch onto one of the named lanes below, so an unnamed/generic dispatch defeats it just as much as a direct edit would.

Registered battle-tier agents (18: 14 vendored + 4 native), each lane made mutually disjoint — read `.claude/agents/*.md` for the full description, this is only the one-line trigger:

| Agent (`agentType`) | Dispatch when |
|---|---|
| `api-designer` | Designing/revising a REST/GraphQL API contract — before implementation exists |
| `backend-developer` | Implementing/hardening a server-side service once a contract exists |
| `frontend-developer` | Building/refactoring a framework-agnostic frontend app feature end-to-end |
| `python-pro` | General idiomatic Python engineering outside a specific web framework |
| `fastapi-developer` | Building/optimizing FastAPI async endpoints, Pydantic models, DI wiring |
| `typescript-pro` | Advanced TypeScript type-system work (generics, cross-boundary type contracts) |
| `react-specialist` | React 18+ specifics: rendering perf, concurrent features, hooks/state architecture |
| `sql-pro` | SQL query optimization, index strategy, relational schema design |
| `devops-engineer` | IaC / CI-CD pipeline / container-orchestration work |
| `debugger` | Runtime bug root-cause diagnosis from stack traces/logs/crashes (read-only) |
| `code-reviewer` | Read-only static diff review for correctness/security/quality |
| `ml-engineer` | Production ML systems engineering: pipelines, training, serving infra |
| `data-scientist` | Data analysis: statistics, hypothesis/A-B testing, predictive modeling |
| `prompt-engineer` | LLM prompt design, evaluation, and optimization before it ships |
| `docs-keeper` | L1→L4 doc-parity upkeep (steps 5/8) |
| `doc-syncer` | Mechanical stage-doc sync (`docs/stages/<NN>.md`, `docs/pipeline.md`) after code edits |
| `e2e-tester` | Real-browser end-to-end QA of a feature/PR (steps 6/8) |
| `pr-writer` | Drafting the PR title/body and the push/merge shell handoff |
| `docs-architect-l4` | Architecture-depth L4 docs (invariants, rationale + rejected alternatives, data-flow, failure modes) at Verify/Ship |
| `experiment-runner` | Bounded, approval-gated research experiments (train/eval ratchet loops) |
| `report-generator` | Rendering the final served dark-HTML report from existing findings |
| `spec-expander` | Expanding a draft spec to full rubric coverage before the planning step |

**Bench-tier agents** (`.claude/agents-bench/`) are NOT registered/dispatchable — they are promoted into `.claude/agents/` via `git mv` only when a concrete project need arises; until promoted, don't route to them.

**Specialized tool, not part of the 8-step flow:** research/experiment work does not follow Scenario A/B — it goes through `experiment-runner`'s own owner-approval gate (writes TASK/BUDGET/PLAN → owner creates APPROVED → git-ratcheted modify→train→eval loop via the looper skill).

## Branches & worktrees

Repo topology after the 2026-07-01 reorg:

- **`main`** — stable base (shared root). Never commit directly to it.
- **`dev-demo`** — active integration line (this branch): the demo web app + the terminology module. Branches off `main`; all new work starts here.
- **`feat/<topic>`** — task branches off **`dev-demo`** (e.g. `feat/model-registry`). One task per branch, merged back into `dev-demo` via PR.
- **`old-gse-translating`** — ⚠️ retired research pipeline (former `artem`: translate / scoring / factcheck research, judge-report CLI, usage tracking). Kept for reference, not the active line.

### Task isolation — one task = one branch + one worktree

Isolation is **per task, not per agent**. Every task runs under its own orchestrator in its own `feat/<topic>` branch and worktree, and all subagents dispatched by that orchestrator work inside that same worktree. What must never happen is two *tasks* (two orchestrators) sharing a branch or worktree — that is what keeps parallel commits conflict-free. The primary checkout hosts `old-gse-translating`; `dev-demo` keeps its own dedicated worktree that task agents don't touch.

Task lifecycle in a session:

1. **Start** — enter an isolated worktree on a fresh `feat/<topic>` branch off `dev-demo` via the [superpowers-using-git-worktrees](.claude/skills/superpowers-using-git-worktrees/SKILL.md) skill (worktrees live under `../worktrees/<topic>/`).
2. **Work** — commits stay inside the task's worktree; never `cd` or `git checkout` into `dev-demo`'s worktree or another task's.
3. **Finish** — open a PR into `dev-demo`, then close out via the [superpowers-finishing-a-development-branch](.claude/skills/superpowers-finishing-a-development-branch/SKILL.md) skill: a **merged** branch is deleted; an **unmerged** branch is never hard-deleted — archive it first (`git bundle` under `../worktree-backups/` + mark it archived) and only then drop the ref.

Bundled, pending an owner decision (unique un-merged work, not on any keeper): `feat/glossary-overnight` (real 869-entry glossary + build pipeline). Merge-forward or formally retire before dropping the branch ref.

## Agents, skills & docs lookup

- **Dispatch work to named agents — the roster is large and the lanes are disjoint.** Pick the agent per the dispatch map and the model-routing table in § Model routing & dispatch; don't fall back to the generic agent, and don't implement in the orchestrator thread — the orchestrator plans, dispatches, aggregates.
- **Skills are in-repo** under [.claude/skills/](.claude/skills/), flattened one level deep so cloud sessions auto-discover them: the `superpowers-*` set (brainstorming, writing-plans, subagent-driven-development, dispatching-parallel-agents, systematic-debugging, using-git-worktrees, finishing-a-development-branch), `/verify-spec`, `/verify-pr`, `report-gen`, `playwright-cli`, `looper`. Which skill fires at which process step → § Process.
- **Library/framework docs: context7 first.** For any question about a library, framework, SDK, API or CLI tool, fetch current docs through the context7 MCP (`resolve-library-id` → `query-docs`); if context7 doesn't cover it, web-search for the official docs. Never answer such questions from training memory.

### Dynamic workflow
Use a hierarchical structure: chief aggregator → per-topic aggregators → several agents per topic. Choose the interaction format, agent roles and count yourself (usually 5–30). Use a dynamic workflow only when you understand why it beats a swarm or a naive single-agent run.

**Parallel means parallel.** When agents are declared parallel, dispatch them genuinely concurrently: one message with multiple Agent launches, or `parallel()`/`pipeline()` in a Workflow script — never a serialized await-one-then-launch-next loop (owner feedback 2026-07-06). Serialize only for a real data dependency or a shared-file write conflict, and state which one forces it.

### Useful skills & MCP
- Browser e2e, in order of preference: (1) **`playwright-cli` skill** — primary for interactive/adversarial runs (~4x cheaper than MCP: disk snapshots read selectively, `snapshot --depth/--scope`; named sessions `-s=<topic>` isolate parallel runs/worktrees); (2) **scripted `npx playwright test`** — cheapest for regression suites (model sees pass/fail + report, not DOM); (3) **playwright MCP** (`--isolated`) — fallback for interactive a11y-ref reasoning only; (4) **chrome-devtools MCP** — perf/network/console debugging, not e2e driving.

## Conventions

### Code

- **Idiomatic-first.** Prefer standard language / library constructs over custom ones. Don't reinvent — don't write a custom iterator where a comprehension fits, don't build a config loader when `pydantic` already does it. Clever one-liners and verbose hand-rolls are both wrong; the right answer is usually the obvious idiom.
- **No speculative abstractions.** Add a class, helper, or config key only when a concrete caller needs it. Research-scope repo — don't design for hypothetical future users.
- **No extra functionality without need.** A bug fix doesn't need surrounding cleanup; a one-shot doesn't need a helper; don't add fallbacks for scenarios that can't happen.
- **One stage = one module** under [src/palimpsest/](src/palimpsest/) (e.g. [terminology/](src/palimpsest/terminology/), [webapp/](src/palimpsest/webapp/), [evaluation/](src/palimpsest/evaluation/)). No `Stage` protocol — keep modules plain until two of them actually need a shared interface.
- **One module = one responsibility.** If a file grows two unrelated concerns, split it.

### Python

- PEP-8, type hints, `from __future__ import annotations` in library modules.
- Comments only where WHY is non-obvious. Don't narrate WHAT the code does.

### Documentation

- Written in English (Hard Invariant 6).
- **Layered model.** `README.md` (product) → `CLAUDE.md` (conventions) → [docs/README.md](docs/README.md) (L1 index) → `docs/subsystems/` (L2) → `docs/stages/` (per-stage docs). Design specs live in `docs/superpowers/specs/` (datestamp `YYYY-MM-DD-topic`; on conflict the later one wins).
- **Single source of truth.** Each fact lives in ONE place; the rest **link, never copy** (including this file and README).
- **Real-time / as a hook.** A doc updates **in the same commit** as the contract/code. Docs are pushed before code-hunts.
- **Cut the old.** Legacy docs are deleted or get a `⚠️ LEGACY` banner — they don't accumulate. Never present target (not yet implemented) code as existing: the target lives in `specs/`, the current state in the memory bank.
- Project gotchas (bugs, provider quirks, reproducibility traps) → [docs/known_issues.md](docs/known_issues.md).
- Style: B2 English, plain language, short sentences; file/code references as markdown links (`[file.py:42](src/file.py#L42)`).

### Ground before you design

The demo frontend and backend are **already built**. Before proposing any UI or data-model change, open what already exists and say what you found — do not design from generic priors ("a registry ⇒ a create-wizard", "a button ⇒ a fresh mockup"):

1. **Grep the relevant code** for the feature's noun (e.g. `model`, `registry`, a button label) under [frontend/src/demo/variant-a/](frontend/src/demo/variant-a/) or [src/palimpsest/](src/palimpsest/), and open the matching file(s).
2. **Follow the routing / "See also" links** in this file and the relevant `docs/subsystems/*.md` for a spec that already covers it.
3. For any visual change, read the design system [docs/subsystems/webapp-ui-design.md](docs/subsystems/webapp-ui-design.md) and the rendered screenshots under [docs/reports/e2e/shots/](docs/reports/e2e/shots/) (if present in this checkout; this GitHub mirror excludes screenshot archives), and **reuse existing `va-*` tokens/classes**.

State the concrete finding (e.g. "`SettingsTab.tsx:172` already renders the registry table") before drafting. If that check isn't done and reported, don't present the design.

## Reports & communication style

**All owner-facing reports and replies are in Russian** (see Language policy). The report template lives ONLY here; project CLAUDE.md files may add project-specific refinements but never duplicate this.

### Style (chat replies AND reports)
You are a professional who has read the full report, understood it, and now narrates it to me: from ideas to details, from simple to complex. Lead with the main thing, then an overview of what was done, then specifics. Be honest with me and critically list the shortcomings yourself — don't wait for me to find them. Explicitly separate "ran" vs "didn't run + why". No boilerplate (`## Summary`/`## Description`). Alternatives in prose: current state → 2–3 options with code-level tradeoffs → a recommendation; `AskUserQuestion` only for narrow binary choices.

### HTML report template (steps 6/8 and any long piece of work)
An HTML page in `docs/reports/`, **dark theme**, visual graphics over walls of text. Block order:
1. **«Главное»** — summary lead, 1–2 sentences: outcome + verdict.
2. **360 diagram** — radar with per-aspect scores (the step-6 aspects map to the axes) + overall verdict badge.
3. **Structured overview of what was done** — from ideas to details: goal → what changed (tables/cards) → key decisions and why.
4. **Critical findings & shortcomings** — bugs, risks, tech debt, unresolved flags; severity-tagged, nothing hidden.
5. **Run artifacts (evidence)** — attached confirmations of every claim: test run outputs (counts, 0-failures lines), e2e proof (screenshots embedded/linked from `shots/`, scenario table with provenance), audit verdicts, commit hashes. A claim without an artifact doesn't go in the report.
6. **Next steps / owner decisions needed.**

**Delivery — the report must actually reach the owner; a bare `.md`/file path is not delivery.** Local sessions: serve on completion via a background `python3 -m http.server <port> --bind 127.0.0.1` from the report directory (ports 8096+, check availability) and give the direct link `http://localhost:<port>/<file>.html`. Cloud sessions (claude.ai/code): localhost is unreachable for the owner — publish the same template as a **Claude Artifact** and give the artifact link. Work is not finished until the report is delivered one of these ways.

The report itself can be rendered via `report-generator` (report-gen skill + `tokyo-night.css`) from already-produced findings in `docs/reports/`/`docs/experiments/`, instead of hand-authoring — it assembles presentation only, it does not perform the analysis.

## Hard Invariants

### General (hold in any project)

1. Never `--no-verify`, `--no-gpg-sign`, or any hook bypass. If a hook fails, fix the root cause.
2. Doc-parity: a code or contract change updates its doc in the **same commit**.
3. Single source of truth: every fact lives in one file; the rest link, never copy.
4. Conventional Commits in English (`feat(webapp): …`, `fix(scoring): …`); subject imperative, scope = module or concern.
5. Branch + PR mandatory: new work happens in its own task branch + worktree (here: `feat/<topic>` off `dev-demo` — see § Branches & worktrees); never commit directly to the trunk.
6. Language: documentation is written in English; owner-facing reports and replies are in Russian, delivered with HTML-level graphics (Claude Artifact in cloud sessions, served HTML locally) — § Language policy, § Reports & communication style.
7. No AI signatures: no "made by claude" / "Generated with Claude Code" footers and no `Co-Authored-By` trailers — not in commits, not in PR bodies.

### Project-specific

8. Ground before you design: the app is already built — open the existing implementation and state the concrete finding before proposing any UI or data-model change; reuse the `variant-a` design system, never invent a parallel style (procedure in § Ground before you design).
9. Demo product UI copy is **English-only**. Russian belongs to owner-facing docs/reports/specs, never to frontend strings — a spec written in Russian must still spell out UI copy in English (2026-07-02: Russian UI copy shipped because a Russian-language spec dictated copy verbatim; don't repeat that).
10. Any UI/design change ships only after a served pixel-real HTML mockup using the `--va-*` tokens (visual-companion rule). The design deliverable is spec + mockup URL, not spec alone.
11. Naming: user-facing labels are "Source" / "Translation" (optionally with language, e.g. "Source · Russian"); code/API identifiers stay `source_*` / `target_*`. Never mix in "original" or "target text" as UI copy.

## General working rules

These are process-level principles on top of the Hard Invariants above.

1. **Module isolation via interfaces.** Every module/entity is independent and interacts ONLY through its declared interface (API contract / schema) and nothing else. This reduces code complexity for agents.
2. **Documentation and tests are first-class.** Tests are written by a separate agent, from the docs (doc-parity in the same commit — CLAUDE.md Hard Invariant 2).
3. **Honesty.** Never claim "checks passed" without a real run of acceptance tests; explicitly separate "ran" vs "didn't run + why".

## Routing

| Topic | Doc |
|---|---|
| Product, quickstart, stack | [README.md](README.md) |
| Pipeline overview / stage index | [docs/pipeline.md](docs/pipeline.md) |
| Positioning, audience, quality bar | [docs/goals/demo-positioning.md](docs/goals/demo-positioning.md) |
| Demo web app — backend + frontend, DB schema, API surface | [docs/subsystems/webapp.md](docs/subsystems/webapp.md) |
| Frontend visual design system (tokens, `va-*` classes, screenshots) | [docs/subsystems/webapp-ui-design.md](docs/subsystems/webapp-ui-design.md) |
| API / data contract (SSOT: DTOs, REST, DDL) | [docs/superpowers/specs/2026-06-30-demo-contracts.md](docs/superpowers/specs/2026-06-30-demo-contracts.md) |
| Terminology module — difficulty + pairAccuracy | [docs/stages/terminology.md](docs/stages/terminology.md) |
| Wiki-eval harness — G6 grounding eval | [docs/stages/wiki-eval.md](docs/stages/wiki-eval.md) |
| Docs index (L1) | [docs/README.md](docs/README.md) |
| Domain language (ubiquitous terms) | [CONTEXT.md](CONTEXT.md) |
| E2E test data manifest | [docs/testing/e2e-data.md](docs/testing/e2e-data.md) |
| Review-aspects catalog for /verify-spec & /verify-pr | [docs/superpowers/review-aspects.md](docs/superpowers/review-aspects.md) |
| Known issues & gotchas | [docs/known_issues.md](docs/known_issues.md) |
