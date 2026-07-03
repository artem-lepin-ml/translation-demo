# CLAUDE.md

Routing document for agents on **`dev-demo`** — the Palimpsest translation-evaluation demo. Product overview and quickstart in [README.md](README.md); the demo subsystem in [docs/subsystems/webapp.md](docs/subsystems/webapp.md); the API/data contract (single source of truth for wire DTOs, REST, SQLite DDL) in [docs/superpowers/specs/2026-06-30-demo-contracts.md](docs/superpowers/specs/2026-06-30-demo-contracts.md).

This file is **conventions + invariants + routing only**. Facts that drift — the model list, evaluator criteria and weights, scores, the team — live in their own source of truth (config, DB, contract, README) and are never copied here.

The full development process (8-step Scenario A/B, model routing, report template, agent/skill calls) lives in @.claude/process.md. Durable behavioral rules and hard invariants live in @.claude/rules/invariants.md and @.claude/rules/working-style.md. All config (agents, skills, commands, hooks) is in-repo under `.claude/` so cloud sessions (claude.ai/code) see it — nothing depends on a machine-local `~/.claude`.

## Branches & worktrees

Repo topology after the 2026-07-01 reorg:

- **`main`** — stable base (shared root).
- **`dev-demo`** — active integration line (this branch): the demo web app + the terminology module. Branches off `main`; all new work starts here.
- **`feat/<topic>`** — feature branches off **`dev-demo`** (e.g. `feat/model-registry`, `feat/terminology-extract`). One topic per branch, merged back into `dev-demo`. **Never commit directly to `main`.**
- **`old-gse-translating`** — ⚠️ retired research pipeline (former `artem`: translate / scoring / factcheck research, judge-report CLI, usage tracking). Kept for reference, not the active line.

### Parallel work — one worktree + one branch per agent (MANDATORY)

Multiple sessions/agents run at the same time. To keep their commits from colliding, each concurrent task is fully isolated:

1. **Its own `feat/<topic>` branch off `dev-demo`** — never off `main`, never a branch another agent is already using.
2. **Its own worktree** under `../worktrees/<topic>/` (`superpowers:using-git-worktrees`).

An agent works **only inside its assigned worktree path**. It must never `cd` or `git checkout` into `dev-demo`'s worktree or another agent's worktree — that is the only way parallel commits stay conflict-free. Each `feat/*` branch merges back into `dev-demo` on its own. The primary checkout hosts `old-gse-translating`; `dev-demo` keeps its own dedicated worktree that feature agents do not touch.

Archived branches are preserved as `git bundle` files under `../worktree-backups/` — **never hard-deleted**.

Bundled, pending an owner decision (unique un-merged work, not on any keeper): `feat/glossary-overnight` (real 869-entry glossary + build pipeline). Merge-forward or formally retire before dropping the branch ref.

## Conventions

### Code

- **Idiomatic-first.** Prefer standard language / library constructs over custom ones. Don't reinvent — don't write a custom iterator where a comprehension fits, don't build a config loader when `pydantic` already does it. Clever one-liners and verbose hand-rolls are both wrong; the right answer is usually the obvious idiom.
- **No speculative abstractions.** Add a class, helper, or config key only when a concrete caller needs it. Research-scope repo — don't design for hypothetical future users.
- **No extra functionality without need.** A bug fix doesn't need surrounding cleanup; a one-shot doesn't need a helper; don't add fallbacks for scenarios that can't happen.
- **One stage = one module** under [src/palimpsest/](src/palimpsest/) (e.g. [terminology/](src/palimpsest/terminology/), [webapp/](src/palimpsest/webapp/), [evaluation/](src/palimpsest/evaluation/)). No `Stage` protocol — keep modules plain until two of them actually need a shared interface.
- **One module = one responsibility.** If a file grows two unrelated concerns, split it.

### Python

- PEP-8, type hints, `from __future__ import annotations` in library modules.
- LLM access goes through `palimpsest.llm.client.LLMClient`. No direct `openai` imports outside that module.
- Comments only where WHY is non-obvious. Don't narrate WHAT the code does.

### Git

- Conventional Commits in English: `feat(webapp): …`, `fix(scoring): …`, `chore(repo): …`, `docs(readme): …`, `refactor(…): …`, `test(…): …`.
- Subject in the imperative (`add`, not `added`); scope is the module or concern.
- Branch off `dev-demo` for new work; never commit directly to `main`. Never `--no-verify` or any hook bypass.

### Data

- **No Git-LFS.** This GitHub mirror carries only the light files the demo needs to build and run. Heavy corpora (`data/raw/`, `data/pilot/`, `data/interim/`) and e2e screenshot archives are **not** in this repo — they live in the GitLab origin and the pre-migration bundle. Don't reintroduce LFS or commit large binaries here.
- Never edit anything in `data/raw/` — it is immutable. Demo seed data lives in `data/seed/`.
- Glossary `glossary/main.json` is the single source of truth for RU→EN terminology.

### Documentation

- Layered, single-source-of-truth: [README.md](README.md) (product) → CLAUDE.md (conventions) → [docs/README.md](docs/README.md) (L1 index) → subsystem / stage docs. Each fact lives in one place; the rest link, never copy.
- Sync rule: a code or contract change updates its doc in the **same commit**.
- Project gotchas (bugs, provider quirks, reproducibility traps) → [docs/known_issues.md](docs/known_issues.md).
- Style: B2 English, plain language, short sentences; file/code references as markdown links (`[file.py:42](src/file.py#L42)`).

### Working with this repo as a model

- Don't read full PDFs in `data/raw/` or full markdown books in `data/interim/` unless explicitly asked — they are huge. Read head/excerpts.
- Don't read `references/`.

### Ground before you design

The demo frontend and backend are **already built**. Before proposing any UI or data-model change, open what already exists and say what you found — do not design from generic priors ("a registry ⇒ a create-wizard", "a button ⇒ a fresh mockup"):

1. **Grep the relevant code** for the feature's noun (e.g. `model`, `registry`, a button label) under [frontend/src/demo/variant-a/](frontend/src/demo/variant-a/) or [src/palimpsest/](src/palimpsest/), and open the matching file(s).
2. **Follow the routing / "See also" links** in this file and the relevant `docs/subsystems/*.md` for a spec that already covers it.
3. For any visual change, read the design system [docs/subsystems/webapp-ui-design.md](docs/subsystems/webapp-ui-design.md) and the rendered screenshots under [docs/reports/e2e/shots/](docs/reports/e2e/shots/), and **reuse existing `va-*` tokens/classes**.

State the concrete finding (e.g. "`SettingsTab.tsx:172` already renders the registry table") before drafting. If that check isn't done and reported, don't present the design.

## Hard Invariants

1. Never `--no-verify`, `--no-gpg-sign`, or any hook bypass. If a hook fails, fix the root cause.
2. Doc-parity: a code / contract change updates its doc in the same commit.
3. Single source of truth: every fact lives in one file; CLAUDE.md and README link, never copy.
4. Conventional Commits in English. Subject imperative, scope = module or concern.
5. Branch + PR mandatory. New work happens in a `feat/<topic>` worktree off `dev-demo`; never commit directly to `main`.
6. LLM access only through `palimpsest.llm.client.LLMClient`. No direct `openai` imports outside that module.
7. Never edit anything in `data/raw/`.
8. Glossary `glossary/main.json` is the single source of truth for RU→EN terminology.
9. Ground before you design: the app is already built — before proposing any UI/data change, open the existing implementation (grep the component dir + follow routing/See-also links) and state what you found; reuse the `variant-a` design system, never invent a parallel style.
10. Demo product UI copy is **English-only**. Russian belongs to owner-facing docs/reports/specs, never to frontend strings — a spec written in Russian must still spell out UI copy in English (2026-07-02: Russian UI copy shipped because a Russian-language spec dictated copy verbatim; don't repeat that).
11. Any UI/design change ships only after a served pixel-real HTML mockup using the `--va-*` tokens (visual-companion rule). The design deliverable is spec + mockup URL, not spec alone.
12. Naming: user-facing labels are "Source" / "Translation" (optionally with language, e.g. "Source · Russian"); code/API identifiers stay `source_*` / `target_*`. Never mix in "original" or "target text" as UI copy.

## Routing

| Topic | Doc |
|---|---|
| Product, quickstart, stack | [README.md](README.md) |
| Positioning, audience, quality bar | [docs/goals/demo-positioning.md](docs/goals/demo-positioning.md) |
| Demo web app — backend + frontend, DB schema, API surface | [docs/subsystems/webapp.md](docs/subsystems/webapp.md) |
| Frontend visual design system (tokens, `va-*` classes, screenshots) | [docs/subsystems/webapp-ui-design.md](docs/subsystems/webapp-ui-design.md) |
| API / data contract (SSOT: DTOs, REST, DDL) | [docs/superpowers/specs/2026-06-30-demo-contracts.md](docs/superpowers/specs/2026-06-30-demo-contracts.md) |
| Terminology module — difficulty + pairAccuracy | [docs/stages/terminology.md](docs/stages/terminology.md) |
| Docs index (L1) | [docs/README.md](docs/README.md) |
| E2E test data manifest | [docs/testing/e2e-data.md](docs/testing/e2e-data.md) |
| Known issues & gotchas | [docs/known_issues.md](docs/known_issues.md) |
