# CLAUDE.md

Routing document for agents on **`dev-demo`** — the Palimpsest translation-evaluation demo. Product overview and quickstart in [README.md](README.md); the demo subsystem in [docs/subsystems/webapp.md](docs/subsystems/webapp.md); the API/data contract (single source of truth for wire DTOs, REST, SQLite DDL) in [docs/superpowers/specs/2026-06-30-demo-contracts.md](docs/superpowers/specs/2026-06-30-demo-contracts.md).

This file holds **project specifics only: branch topology, conventions, hard invariants, routing**. The working methodology — language policy, the 8-step Scenario A/B process, model routing, the agent dispatch map, dynamic workflows, graphify, communication style and the HTML report template — lives in @.claude/process.md. Durable owner rules beyond both live in @.claude/rules/invariants.md and @.claude/rules/working-style.md. All config (agents, skills, commands, hooks) is in-repo under `.claude/` so cloud sessions (claude.ai/code) see it — nothing depends on a machine-local `~/.claude`. Facts that drift — the model list, evaluator criteria and weights, scores, the team — live in their own source of truth (config, DB, contract, README) and are never copied here.

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

- **Dispatch work to named agents — the roster is large and the lanes are disjoint.** Pick the agent per the dispatch map and the model-routing table in [.claude/process.md](.claude/process.md); don't fall back to the generic agent, and don't implement in the orchestrator thread — the orchestrator plans, dispatches, aggregates.
- **Skills are in-repo** under [.claude/skills/](.claude/skills/), flattened one level deep so cloud sessions auto-discover them: the `superpowers-*` set (brainstorming, writing-plans, subagent-driven-development, dispatching-parallel-agents, systematic-debugging, using-git-worktrees, finishing-a-development-branch), `/verify-spec`, `/verify-pr`, `report-gen`, `playwright-cli`, `graphify`, `looper`. Which skill fires at which process step → [.claude/process.md](.claude/process.md).
- **Library/framework docs: context7 first.** For any question about a library, framework, SDK, API or CLI tool, fetch current docs through the context7 MCP (`resolve-library-id` → `query-docs`); if context7 doesn't cover it, web-search for the official docs. Never answer such questions from training memory.

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

- Written in English (Hard Invariant 6). The layered L1→L4 model, single-source-of-truth linking, legacy cleanup and the report template are canonical in [.claude/process.md](.claude/process.md).
- Project gotchas (bugs, provider quirks, reproducibility traps) → [docs/known_issues.md](docs/known_issues.md).
- Style: B2 English, plain language, short sentences; file/code references as markdown links (`[file.py:42](src/file.py#L42)`).

### Ground before you design

The demo frontend and backend are **already built**. Before proposing any UI or data-model change, open what already exists and say what you found — do not design from generic priors ("a registry ⇒ a create-wizard", "a button ⇒ a fresh mockup"):

1. **Grep the relevant code** for the feature's noun (e.g. `model`, `registry`, a button label) under [frontend/src/demo/variant-a/](frontend/src/demo/variant-a/) or [src/palimpsest/](src/palimpsest/), and open the matching file(s).
2. **Follow the routing / "See also" links** in this file and the relevant `docs/subsystems/*.md` for a spec that already covers it.
3. For any visual change, read the design system [docs/subsystems/webapp-ui-design.md](docs/subsystems/webapp-ui-design.md) and the rendered screenshots under [docs/reports/e2e/shots/](docs/reports/e2e/shots/) (if present in this checkout; this GitHub mirror excludes screenshot archives), and **reuse existing `va-*` tokens/classes**.

State the concrete finding (e.g. "`SettingsTab.tsx:172` already renders the registry table") before drafting. If that check isn't done and reported, don't present the design.

## Hard Invariants

### General (hold in any project)

1. Never `--no-verify`, `--no-gpg-sign`, or any hook bypass. If a hook fails, fix the root cause.
2. Doc-parity: a code or contract change updates its doc in the **same commit**.
3. Single source of truth: every fact lives in one file; the rest link, never copy.
4. Conventional Commits in English (`feat(webapp): …`, `fix(scoring): …`); subject imperative, scope = module or concern.
5. Branch + PR mandatory: new work happens in its own task branch + worktree (here: `feat/<topic>` off `dev-demo` — see § Branches & worktrees); never commit directly to the trunk.
6. Language: documentation is written in English; owner-facing reports and replies are in Russian, delivered with HTML-level graphics (Claude Artifact in cloud sessions, served HTML locally) — policy and template in @.claude/process.md.
7. No AI signatures: no "made by claude" / "Generated with Claude Code" footers and no `Co-Authored-By` trailers — not in commits, not in PR bodies.

### Project-specific

8. Ground before you design: the app is already built — open the existing implementation and state the concrete finding before proposing any UI or data-model change; reuse the `variant-a` design system, never invent a parallel style (procedure in § Ground before you design).
9. Demo product UI copy is **English-only**. Russian belongs to owner-facing docs/reports/specs, never to frontend strings — a spec written in Russian must still spell out UI copy in English (2026-07-02: Russian UI copy shipped because a Russian-language spec dictated copy verbatim; don't repeat that).
10. Any UI/design change ships only after a served pixel-real HTML mockup using the `--va-*` tokens (visual-companion rule). The design deliverable is spec + mockup URL, not spec alone.
11. Naming: user-facing labels are "Source" / "Translation" (optionally with language, e.g. "Source · Russian"); code/API identifiers stay `source_*` / `target_*`. Never mix in "original" or "target text" as UI copy.

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
| E2E test data manifest | [docs/testing/e2e-data.md](docs/testing/e2e-data.md) |
| Review-aspects catalog for /verify-spec & /verify-pr | [docs/superpowers/review-aspects.md](docs/superpowers/review-aspects.md) |
| Known issues & gotchas | [docs/known_issues.md](docs/known_issues.md) |
