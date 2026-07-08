# CLAUDE.md

Routing document for agents working in this repo. Project idea and team in [README.md](README.md). Pipeline detail in [docs/pipeline.md](docs/pipeline.md).

## Team

- Artem Lepin — DS, primary owner of this repo.
- Danil Kostromin — strong junior. Note: commits authored by `KirillParfentiev <rudefellow@gmail.com>` are also Danil — old GitHub account he used by mistake on early `feat/project` work.
- Andrey — research supervisor.

External stakeholders: MGIMO world-history chair (terminology approval) and language departments (verification, markup, proofreading).

## Workflow

Standard cycle for non-trivial work (new stage, contract change, new algorithm, new pilot script):

1. **Brainstorm** → `superpowers:brainstorming`. Spec to [docs/superpowers/specs/](docs/superpowers/specs/).
2. **Plan** → `superpowers:writing-plans`. Plan to [docs/superpowers/plans/](docs/superpowers/plans/).
3. **Branch + worktree** → `superpowers:using-git-worktrees`. Create a `feat/<topic>` worktree off `feat/project`.
4. **Execute** → `superpowers:subagent-driven-development`.
5. **Verify** → `superpowers:verification-before-completion` before any "done" claim.
6. **Finish** → `superpowers:finishing-a-development-branch`. PR `feat/<topic>` → `feat/project`.

Exceptions (short path):

- Bug / failing test → `superpowers:systematic-debugging` directly (no spec/plan), then branch + PR.
- Trivial fix (typo, parameter tune, add a log) → branch + PR directly (no spec/plan).

Branch + PR are mandatory always (Hard Invariant #5).

Trigger table for additional skills:

- Major feature ready → `superpowers:requesting-code-review`.
- Got a review → `superpowers:receiving-code-review`.
- 2+ independent tasks in one session → `superpowers:dispatching-parallel-agents`.
- Any new logic → `superpowers:test-driven-development`.

## Conventions

### Code

- Idiomatic-first. Prefer standard language / library constructs over custom ones. Don't reinvent — don't write a custom iterator where a comprehension fits, don't build a config loader when `pydantic` already does it. Clever one-liners and verbose hand-rolls are both wrong; the right answer is usually the obvious idiom.
- No speculative abstractions. Add a class, helper, or config key only when a concrete caller needs it. Research-scope repo, ~2 months — don't design for hypothetical future users.
- No extra functionality without need. A bug fix doesn't need surrounding cleanup; a one-shot doesn't need a helper; don't add fallbacks for scenarios that can't happen.
- One stage = one module under [src/palimpsest/](src/palimpsest/) (e.g. [translate.py](src/palimpsest/translate.py), [scoring.py](src/palimpsest/scoring.py), [factcheck/](src/palimpsest/factcheck/)) with a thin script wrapper in [scripts/](scripts/). No `Stage` protocol — keep stages as plain modules until two of them actually need a shared interface.
- One module = one responsibility. If a file grows two unrelated concerns, split it.

### Python

- PEP-8, type hints, `from __future__ import annotations` in library modules.
- LLM access goes through `palimpsest.llm.client.LLMClient`. No direct `openai` imports outside that module.
- Comments only where WHY is non-obvious. Don't narrate WHAT the code does.

### Git

- Conventional Commits in English: `feat(pipeline): …`, `fix(io): …`, `chore(repo): …`, `docs(readme): …`, `refactor(…): …`, `test(…): …`, `exp(eval): …` for research experiments.
- Subject in the imperative (`add`, not `added`); scope is the module or concern.

### Data

- Everything under `data/` and `reports/figures/` is Git-LFS tracked (see `.gitattributes`).
- Install LFS once per machine: `brew install git-lfs && git lfs install`.
- Never edit anything in `data/raw/`. Pilot artifacts live under `data/pilot/`.
- Glossary `glossary/main.json` is the single source of truth for RU→EN terminology. Stage 3 reads it and writes back via `Glossary.upsert`.

### Documentation

- Four-level tree: [README.md](README.md) → [CLAUDE.md](CLAUDE.md) → [docs/pipeline.md](docs/pipeline.md) → [docs/stages/](docs/stages/).
- Cross-references: every doc except README has an up-link in its first paragraph. Stage docs link to `docs/pipeline.md`. The pipeline doc links back to each stage doc.
- Stage doc fields, in this order: Title (`# Stage <N> — <Name>`), Up-link line, Purpose, Design decisions, Interface (Python signature in code block), Subtleties, Status. Dual-mode stages split sections under Mode A / Mode B subsections.
- Sync rule: code change in a stage → update the stage doc + pipeline.md status in the same commit. Pipeline-level architecture change → update docs/pipeline.md + README pitch + CLAUDE.md. New stage → add a stage doc + a section in docs/pipeline.md.
- Грабли проекта (баги, неочевидные ограничения провайдеров, проблемы воспроизводимости) фиксируем в [docs/known_issues.md](docs/known_issues.md) — добавлять новую запись когда столкнулись и согласовали решение.
- Style: B2 English. Plain language. Short sentences. File and code references as markdown links: `[file.py:42](src/file.py#L42)`. One concept per paragraph. Russian is acceptable for operational guides (`docs/factchecker.md`).

### Working with this repo as a model

- Don't read full PDFs in `data/raw/` or full markdown books in `data/interim/` unless explicitly asked — they are huge. Read only head/excerpts.
- Don't read `references/`.
- `factowl/` is a read-only design reference: studied for its extraction prompt and few-shot layout, but `src/palimpsest/factcheck/` is an independent implementation.

## Hard Invariants

1. Never `--no-verify`, `--no-gpg-sign`, or any hook bypass. If a hook fails, fix the root cause.
2. Sync rule: code change → corresponding doc change in the same commit.
3. Single source of truth: every fact lives in one file; CLAUDE.md and README.md link, never copy.
4. Conventional Commits in English. Subject in imperative, scope = module or concern.
5. Branch + PR mandatory. New work happens in a `feat/<topic>` worktree off `feat/project`; never push directly to `feat/project`.
6. LLM access only through `palimpsest.llm.client.LLMClient`. No direct `openai` imports outside that module.
7. Never edit anything in `data/raw/`. Pilot artifacts live under `data/pilot/`.
8. Glossary `glossary/main.json` is the single source of truth for RU→EN terminology. Stage 3 reads and writes back via `Glossary.upsert`.
9. `factowl/` is a read-only design reference. Do not edit.
10. Do not read full PDFs in `data/raw/` or full markdown books in `data/interim/` unless explicitly asked. Read head/excerpts instead.

## Routing

| Topic | Doc |
|---|---|
| Project idea, deliverables, stack | [README.md](README.md) |
| Pipeline narrative + per-stage status | [docs/pipeline.md](docs/pipeline.md) |
| Pipeline contract (paths, JSONL schemas) | [references/interfaces_agreement.md](references/interfaces_agreement.md) |
| Per-stage detail | [docs/stages/](docs/stages/) |
| Factcheck operational guide | [docs/factchecker.md](docs/factchecker.md) |
| Specs / plans | [docs/superpowers/](docs/superpowers/) |
| Известные проблемы и грабли | [docs/known_issues.md](docs/known_issues.md) |
| Research drafts (RQ, эксперимент-дизайн) | [docs/experiments/](docs/experiments/) |
