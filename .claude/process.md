# CLAUDE.md

## Language policy

Think, plan and talk to subagents in English (token economy). ALL owner-facing output is in Russian: chat replies, reports (md/HTML), specs/plans, D-journal entries, flags to the owner. Project docs keep their existing language (Russian).

## Process

### Core concept
Spec-driven development. We craft a high-quality spec together; you then execute it fully autonomously (no interruptions, no check-ins). I review only specs, reviews and the docs/ documentation.

### Scenario A (I'm present and actively participating)

1. **Brainstorm** — [brainstorming](.claude/skills/superpowers/brainstorming/SKILL.md) (+ [visual-companion](.claude/skills/superpowers/brainstorming/visual-companion.md) when there is UI/UX/design). Spec → [docs/superpowers/specs/](docs/superpowers/specs/). Goal: a spec with goal, scope, success criteria and the most correct plan to reach the goal, honoring every subtlety of the task and my global vision.
2. **Verify Spec** — skill `/verify-spec`: the orchestrator picks ≥3 relevant aspects from `docs/superpowers/review-aspects.md` (the skill generates it if missing), one subagent = one aspect (fresh context, read-only), structured findings → aggregation (max severity, disagreements section) → mandatory spec/plan rework → gate (CRITICAL/HIGH → rework and re-review of the affected aspects).
3. **Plan** — [writing-plans](.claude/skills/superpowers/writing-plans/SKILL.md). Plan → [docs/superpowers/plans/](docs/superpowers/plans/). Work the spec out in more detail, down to a plan.
4. **Branch + worktree** — [using-git-worktrees](.claude/skills/superpowers/using-git-worktrees/SKILL.md). Branch `feat/<topic>` off `dev-demo`.
5. **Execute** — [subagent-driven-development](.claude/skills/superpowers/subagent-driven-development/SKILL.md) or a dynamic workflow. Parallelize independent task classes as much as possible. Remember tests and documentation. Every commit that changes a contract/behavior is accompanied by a `docs-keeper` call (doc-parity in the same commit).
<loop>
6. **Verify** — skill `/verify-pr`: the orchestrator picks ≥5 aspects from `docs/superpowers/review-aspects.md`; aspect agents with full rights write and run unit/integration tests, check code and data (isolated DB only). In parallel — a browser run by the `e2e-tester` agent + a mandatory audit of its report (Sonnet auditor, PASS/FAIL gate: provenance/screenshot failures send the run back). Deliver the full PR-quality report per the **Reports** section (HTML, 360 diagram). Serious problems found → step 7; nothing critical and all scores positive → step 8.
7. **Fix** — [systematic-debugging](.claude/skills/superpowers/systematic-debugging/SKILL.md): carefully analyze the code and context, find the deep root cause and fix it. If the problem is systemic or complex, log it to docs/PROBLEMS.md; after finding all occurrences, run deep research + a tournament via dynamic workflow to find the best solution. After fixing everything, redo step 6 from a clean slate.
</loop>
8. **Finish** — run the `e2e-tester` agent (real data ONLY from the `docs/testing/e2e-data.md` manifest; the full user journey in the browser — e.g. the teacher's and the student's path, not DB-seeding via URL — for ALL scenarios described in the PR) + the audit of its report; then `docs-keeper` — final doc-parity check across the whole PR; then `/graphify <root> --update` via a background agent. Failure → back into the loop at step 6. Success → final HTML report per **Reports** in [docs/reports/](docs/reports/). If there is something to test, deploy a full test environment for me and await my tests and review. Approved → [finishing-a-development-branch](.claude/skills/superpowers/finishing-a-development-branch/SKILL.md), PR `feat/<topic>` → `dev-demo`. Not approved → understand why, improve step 6 so it would catch the problems I found, and return to step 6.

If the task is very large: decompose and execute with several parallel background agents — a swarm via [dispatching-parallel-agents](.claude/skills/superpowers/dispatching-parallel-agents/SKILL.md).

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

### Agent usage (model routing)

| Task | Model | Effort |
|---|---|---|
| Orchestration (main session), brainstorm & spec writing, high-level research planning, decisions on how to fix findings, final aggregation & reports to the owner | Fable 5 | high |
| Deep research, systematic debugging (step 7), aspect-report aggregation by a subagent, code WITHOUT a ready plan (freeform/exploratory), security-critical code | Opus 4.8 (`model: opus`) | high → xhigh |
| ALL code written to a ready plan/spec (standard practice), unit tests, aspect reviewers (steps 2/6), documentation updates, docs-keeper, e2e report audits | Sonnet 4.6 (`model: sonnet`) | medium → high |
| Repo recon, search/grep, mechanical edits | Haiku 4.5 (`model: haiku`) | low |
| e2e-tester (browser runs) | Fable 5 (agent frontmatter) | high |

Rules: (R1) subagents NEVER inherit the session model — set `model:` explicitly; aggregation is done by the orchestrator itself or a `model: opus` subagent; (R2) executors medium/high, aggregators high/xhigh — sparingly; (R3) Fable 5 may auto-reroute biology/cybersec-adjacent prompts to Opus 4.8 — if systematic, consciously switch the agent's model with a D-journal entry; (R4) escalation: Sonnet → Opus → Fable ("Fable — when the task would justify a senior contractor"); (R5) code: a ready plan/spec exists → ALWAYS Sonnet (not Opus and not Fable); no plan and the code is freeform → Opus.

### Convention: config lives in the repo (cloud-ready)
This file (`.claude/process.md`) carries the process common to the work: the 8 steps, A/B scenarios, routing, calls to agents/skills (e2e-tester, docs-keeper, doc-syncer, pr-writer, /verify-spec, /verify-pr — doc-syncer does mechanical stage-doc sync after code edits, docs-keeper does L1→L4 parity upkeep), graphify rules, documentation convention, hard invariants. It is `@`-imported from the repo-root `CLAUDE.md`.
- Repo-root `CLAUDE.md` — project specifics: stack, repo map, test tiers and commands, data manifest (`docs/testing/e2e-data.md`), project invariants, path overrides — plus `@.claude/process.md`.
- Agents live in `.claude/agents/`, skills in `.claude/skills/`, commands in `.claude/commands/`, durable rules in `.claude/rules/`. Everything is in-repo so cloud sessions (claude.ai/code) see it — nothing depends on a machine-local `~/.claude`.
- Placing a new rule: process/routing → here; project fact → repo CLAUDE.md; a durable invariant → its own file under `.claude/rules/`. Single source of truth, never duplicate.

### Dynamic workflow
Use a hierarchical structure: chief aggregator → per-topic aggregators → several agents per topic. Choose the interaction format, agent roles and count yourself (usually 5–30). Use a dynamic workflow only when you understand why it beats a swarm or a naive single-agent run.

### Knowledge graph (graphify)
graphify is a skill (invoke via the Skill tool, not bash; its python package installs itself on the first run).
- Auto-use: questions about architecture/relations/"where does X live" → `/graphify query "<question>"` first; grep only if the graph can't answer. Pass `graphify-out/GRAPH_REPORT.md` to recon and review agents as input context.
- Auto-update: at feature end (step 8) — `/graphify <root> --update` via a background agent.
- Auto-start: on the SessionStart hook injection, build the graph via a background agent without blocking the main work.

### Useful skills & MCP
- context7
- clone-website — used mostly as a template that defines the algorithm for porting a real site into our code.
- Browser e2e, in order of preference: (1) **`playwright-cli` skill** — primary for interactive/adversarial runs (~4x cheaper than MCP: disk snapshots read selectively, `snapshot --depth/--scope`; named sessions `-s=<topic>` isolate parallel runs/worktrees); (2) **scripted `npx playwright test`** — cheapest for regression suites (model sees pass/fail + report, not DOM); (3) **playwright MCP** (`--isolated`) — fallback for interactive a11y-ref reasoning only; (4) **chrome-devtools MCP** — perf/network/console debugging, not e2e driving.

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

**Always serve HTML reports locally on completion:** a background `python3 -m http.server <port> --bind 127.0.0.1` from the report directory (ports 8096+, check availability) and give me the direct link `http://localhost:<port>/<file>.html`. Work is not finished until the report is served.

## Documentation

- **Layered model.** `README.md` (product) → `CLAUDE.md` (conventions) → [docs/README.md](docs/README.md) (L1 index) → `docs/subsystems/` (L2) → `docs/stages/` (per-stage docs). Design specs live in `docs/superpowers/specs/` (datestamp `YYYY-MM-DD-topic`; on conflict the later one wins).
- **Single source of truth.** Each fact lives in ONE place; the rest **link, never copy** (including this file and README).
- **Real-time / as a hook.** A doc updates **in the same commit** as the contract/code. Docs are pushed before code-hunts.
- **Cut the old.** Legacy docs are deleted or get a `⚠️ LEGACY` banner — they don't accumulate. Never present target (not yet implemented) code as existing: the target lives in `specs/`, the current state in the memory bank.

## Hard Invariants

### General working rules
1. **Module isolation via interfaces.** Every module/entity is independent and interacts ONLY through its declared interface (API contract / schema) and nothing else. This reduces code complexity for agents.
2. **Documentation and tests are first-class** (see the eponymous sections): doc-parity in the same commit; tests — by a separate agent, from the docs.
3. **Honesty.** Never claim "checks passed" without a real run of acceptance tests; explicitly separate "ran" vs "didn't run + why".
