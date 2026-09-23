# CLAUDE.md

Routing document for agents on **`dev-demo`** — the Palimpsest translation-evaluation demo. Product overview and quickstart in [README.md](README.md); the demo subsystem in [docs/subsystems/webapp.md](docs/subsystems/webapp.md); the API/data contract (single source of truth for wire DTOs, REST, SQLite DDL) in [docs/superpowers/specs/2026-06-30-demo-contracts.md](docs/superpowers/specs/2026-06-30-demo-contracts.md).

This file holds **both the project specifics** (branch topology, conventions, hard invariants, routing) **and the working methodology inline**: the language policy, the size-based process (small / medium / large, autonomous mode), model routing and the agent roster, communication style and the HTML report template. The methodology lives here rather than in a separate `@`-imported doc because cloud sessions (claude.ai/code) must see it deterministically — an `@`-import of a process doc proved unreliable in the cloud, while `CLAUDE.md` itself always loads. Durable owner rules beyond both are still `@`-imported (those demonstrably load): @.claude/rules/invariants.md and @.claude/rules/working-style.md. All config (agents, skills, commands, hooks) is in-repo under `.claude/` so cloud sessions see it — nothing depends on a machine-local `~/.claude`. Facts that drift — the model list, evaluator criteria and weights, scores, the team — live in their own source of truth (config, DB, contract, README) and are never copied here. Placing a new rule: methodology/process → the relevant section here; a durable owner rule → `.claude/rules/`; never duplicate.

## Language policy

Think, plan and talk to subagents in English (token economy). ALL owner-facing output is in Russian: chat replies, reports (md / HTML / Claude artifacts), specs/plans, D-journal entries, flags to the owner. Project documentation (README, docs/, CLAUDE.md, agent/skill definitions) is written in English.

## Process

Keep it light: the process scales with the task. The main session does small work itself; ceremony (spec, aspect reviews, agent pipeline, HTML report) is reserved for large features.

### Task sizes

| Size | Examples | What it needs |
|---|---|---|
| **Small** | a fix, a bug, a change that fits one PR | The main session does it directly: `feat/<topic>` branch + worktree (§ Branches & worktrees), the change with its doc update, real tests, a browser check if UI is touched, PR. No spec, no mandatory agents. |
| **Medium** | a feature across a few modules, still one PR | A short plan in chat, then the same as small. Agents only where they pay off (below). |
| **Large** | a new subsystem, a cross-cutting contract change, multi-PR work | Brainstorm ([brainstorming](.claude/skills/superpowers-brainstorming/SKILL.md), + [visual-companion](.claude/skills/superpowers-brainstorming/visual-companion.md) for UI) → spec in [docs/superpowers/specs/](docs/superpowers/specs/), owner approves → `/verify-spec` → plan (`spec-expander`, then [writing-plans](.claude/skills/superpowers-writing-plans/SKILL.md)) → execute ([subagent-driven-development](.claude/skills/superpowers-subagent-driven-development/SKILL.md) or [parallel agents](.claude/skills/superpowers-dispatching-parallel-agents/SKILL.md)) → `/verify-pr` + `e2e-tester` on real data from [docs/testing/e2e-data.md](docs/testing/e2e-data.md) → fix root causes ([systematic-debugging](.claude/skills/superpowers-systematic-debugging/SKILL.md); systemic ones go to [docs/PROBLEMS.md](docs/PROBLEMS.md)) and re-verify → `docs-keeper` final parity check → HTML report (§ Reports) → PR. |

Unclear requirements or an unfamiliar area: use the [finding-unknowns playbook](.claude/playbooks/finding-unknowns.md) (blindspot pass, prototype, interview) before building. Research experiments do not follow these sizes — they go through `experiment-runner`'s own owner-approval gate.

### When to use agents

Only where they pay off: **independent parallel branches of work**, **large research or search sweeps**, and **an independent review before merging a risky change** (contracts, data-deleting paths, security). Otherwise the main session does the work itself. Every subagent gets an explicit `model:` — never the inherited session model (§ Model routing). Parallel means parallel: the Workflow tool caps concurrency per run at min(16, CPU cores − 2), so check `nproc` before a fan-out and split it across concurrent runs if the cap would serialize it.

### Verification

- **Tests really run.** Never claim "passed" without a run; report "ran" vs "didn't run + why".
- **UI changes: really click through them in the browser** (preferred tools in § Useful skills & MCP) — every touched button and transition, not only the main scenario; take and inspect screenshots.
- **Fix the root cause, not the symptom.**

### Finishing

Open a PR into `dev-demo`; the owner reviews and merges — never merge yourself. An HTML report is produced only on the owner's request or for a large feature (§ Reports). § Hard Invariants apply at every size.

### Autonomous mode

Applies when I write "работай полностью автономно" or "я отошел на X минут / часов". All permissions are granted; asking me anything is a failure — replace my decisions with research and your own diligence. To understand my vision, read my specs and docs from the last 2 days; on conflict, docs beat specs and newer beats older. Finish the stated goal fully, verify for real (including the browser for UI), report honestly what is done and what is not, then stop.

Recurring problems I find in your browser testing:
- You get lazy about testing through the browser → nothing actually works in reality. Really test through the browser with the widest, most realistic e2e runs; take and inspect screenshots (at least 10 per UI PR).
- You do only the main scenario and forget the others. Execute ALL scenarios; every button and transition must work — as if real users were using the app. Finding a bug during e2e is a win.

## Model routing & dispatch

### Model routing

| Role | Model |
|---|---|
| Main session — orchestrates and does small work itself | the owner's pick (Fable 5.1 or Opus 5.5) |
| Strongest subagent tier: hard design, specs, freeform code without a plan, debugging, security-critical code, reports, aggregation | Opus 5.5 (`model: opus`) |
| Default executor: code to a ready plan, tests, reviews, docs, `e2e-tester` | Sonnet 5 (`model: sonnet`) |
| Recon, search, mechanical edits | Haiku 4.5 (`model: haiku`) |

Fable runs only as the main session — no subagent is ever pinned to it. Escalate Sonnet → Opus when an attempt demonstrably fails.

### Agent roster

Registered agents, one line each — read `.claude/agents/*.md` for the full description. Use a named agent when its lane fits:

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
| `docs-keeper` | L1→L4 doc-parity upkeep (large features: during execution and the final parity check) |
| `doc-syncer` | Mechanical stage-doc sync (`docs/stages/<NN>.md`, `docs/pipeline.md`) after code edits |
| `e2e-tester` | Real-browser end-to-end QA of a large feature/PR |
| `pr-writer` | Drafting the PR title/body and the push/merge shell handoff |
| `docs-architect-l4` | Architecture-depth L4 docs (invariants, rationale + rejected alternatives, data-flow, failure modes) when a large feature needs them |
| `experiment-runner` | Bounded, approval-gated research experiments (train/eval ratchet loops) |
| `report-generator` | Rendering the final served dark-HTML report from existing findings |
| `spec-expander` | Expanding a draft spec to full rubric coverage before the planning step |

**Bench-tier agents** (`.claude/agents-bench/`) are NOT registered/dispatchable — they are promoted into `.claude/agents/` via `git mv` only when a concrete project need arises; until promoted, don't route to them.

## Branches & worktrees

Repo topology after the 2026-07-01 reorg:

- **`dev-demo`** — the trunk: active integration line (this branch) for the demo web app + the terminology module. There is currently no `main` branch (checked 2026-07-07: absent locally and on origin, `origin/HEAD` points at `dev-demo`) — `dev-demo` is the base all new work starts from. Never commit directly to it.
- **`feat/<topic>`** — task branches off **`dev-demo`** (e.g. `feat/model-registry`). One task per branch, merged back into `dev-demo` via PR.
- **`old-gse-translating`** — ⚠️ retired research pipeline (former `artem`: translate / scoring / factcheck research, judge-report CLI, usage tracking). Kept for reference, not the active line.

### Task isolation — one task = one branch + one worktree

Isolation is **per task, not per agent**. Every task runs in its own session on its own `feat/<topic>` branch and worktree, and any subagents that session dispatches work inside that same worktree. What must never happen is two *tasks* (two sessions) sharing a branch or worktree — that is what keeps parallel commits conflict-free. The primary checkout hosts `old-gse-translating`; `dev-demo` keeps its own dedicated worktree that task agents don't touch.

Task lifecycle in a session:

1. **Start** — enter an isolated worktree on a fresh `feat/<topic>` branch off `dev-demo` via the [superpowers-using-git-worktrees](.claude/skills/superpowers-using-git-worktrees/SKILL.md) skill (worktrees live under `../worktrees/<topic>/`).
2. **Work** — commits stay inside the task's worktree; never `cd` or `git checkout` into `dev-demo`'s worktree or another task's.
3. **Finish** — open a PR into `dev-demo`, then close out via the [superpowers-finishing-a-development-branch](.claude/skills/superpowers-finishing-a-development-branch/SKILL.md) skill: a **merged** branch is deleted; an **unmerged** branch is never hard-deleted — archive it first (`git bundle` under `../worktree-backups/` + mark it archived) and only then drop the ref.

Bundled, pending an owner decision (unique un-merged work, not on any keeper): `feat/glossary-overnight` (real 869-entry glossary + build pipeline). Merge-forward or formally retire before dropping the branch ref.

## Agents, skills & docs lookup

- **Agents are optional.** When a task does call for one (§ When to use agents), pick the named lane from § Agent roster with an explicit `model:`.
- **Skills are in-repo** under [.claude/skills/](.claude/skills/), flattened one level deep so cloud sessions auto-discover them: the `superpowers-*` set (brainstorming, writing-plans, subagent-driven-development, dispatching-parallel-agents, systematic-debugging, using-git-worktrees, finishing-a-development-branch), `/verify-spec`, `/verify-pr`, `report-gen`, `playwright-cli`, `looper`. Which skill belongs to which task size → § Process.
- **Library/framework docs: context7 first.** For any question about a library, framework, SDK, API or CLI tool, fetch current docs through the context7 MCP (`resolve-library-id` → `query-docs`); if context7 doesn't cover it, web-search for the official docs. Never answer such questions from training memory.

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

### HTML report template (on the owner's request or for a large feature)
An HTML page in `docs/reports/`, **dark theme**, visual graphics over walls of text. Block order:
1. **«Главное»** — summary lead, 1–2 sentences: outcome + verdict.
2. **360 diagram** — radar with per-aspect scores (the `/verify-pr` aspects map to the axes) + overall verdict badge.
3. **Structured overview of what was done** — from ideas to details: goal → what changed (tables/cards) → key decisions and why.
4. **Critical findings & shortcomings** — bugs, risks, tech debt, unresolved flags; severity-tagged, nothing hidden.
5. **Run artifacts (evidence)** — attached confirmations of every claim: test run outputs (counts, 0-failures lines), e2e proof (screenshots embedded/linked from `shots/`, scenario table with provenance), audit verdicts, commit hashes. A claim without an artifact doesn't go in the report.
6. **Next steps / owner decisions needed.**

**Delivery — the report must actually reach the owner; a bare `.md`/file path is not delivery.** Local sessions: serve on completion via a background `python3 -m http.server <port> --bind 127.0.0.1` from the report directory (ports 8096+, check availability) and give the direct link `http://localhost:<port>/<file>.html`. Cloud sessions (claude.ai/code): localhost is unreachable for the owner — publish the same template as a **Claude Artifact** and give the artifact link. When a report is due, the work is not finished until it is delivered one of these ways.

The report itself can be rendered via `report-generator` (report-gen skill + `tokyo-night.css`) from already-produced findings in `docs/reports/`/`docs/experiments/`, instead of hand-authoring — it assembles presentation only, it does not perform the analysis.

## Hard Invariants

### General (hold in any project)

1. Never `--no-verify`, `--no-gpg-sign`, or any hook bypass. If a hook fails, fix the root cause.
2. Doc-parity: a code or contract change updates its doc in the **same commit**.
3. Single source of truth: every fact lives in one file; the rest link, never copy.
4. Conventional Commits in English (`feat(webapp): …`, `fix(scoring): …`); subject imperative, scope = module or concern.
5. Branch + PR mandatory: new work happens in its own task branch + worktree (here: `feat/<topic>` off `dev-demo` — see § Branches & worktrees); never commit directly to the trunk.
6. Language: documentation is written in English; owner-facing reports and replies are in Russian; an HTML report, when one is due, is delivered as a Claude Artifact in cloud sessions or served HTML locally — § Language policy, § Reports & communication style.
7. No AI signatures: no "made by claude" / "Generated with Claude Code" footers and no `Co-Authored-By` trailers — not in commits, not in PR bodies.

### Project-specific

8. Ground before you design: the app is already built — open the existing implementation and state the concrete finding before proposing any UI or data-model change; reuse the `variant-a` design system, never invent a parallel style (procedure in § Ground before you design).
9. Demo product UI copy is **English-only**. Russian belongs to owner-facing docs/reports/specs, never to frontend strings — a spec written in Russian must still spell out UI copy in English (2026-07-02: Russian UI copy shipped because a Russian-language spec dictated copy verbatim; don't repeat that).
10. Any UI/design change ships only after a served pixel-real HTML mockup using the `--va-*` tokens (visual-companion rule). The design deliverable is spec + mockup URL, not spec alone.
11. Naming: user-facing labels are "Source" / "Translation" (optionally with language, e.g. "Source · Russian"); code/API identifiers stay `source_*` / `target_*`. Never mix in "original" or "target text" as UI copy.

## General working rules

These are process-level principles on top of the Hard Invariants above.

1. **Module isolation via interfaces.** Every module/entity is independent and interacts ONLY through its declared interface (API contract / schema) and nothing else. This reduces code complexity for agents.
2. **Documentation and tests are first-class.** Every change ships with its tests and its doc update (doc-parity in the same commit — Hard Invariant 2); on a large feature, tests are written from the docs by a separate agent.
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
