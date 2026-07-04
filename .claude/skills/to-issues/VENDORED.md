- **Source repo:** https://github.com/mattpocock/skills
- **Upstream path:** skills/engineering/to-issues/
- **Pinned commit SHA:** `272f99b22574f50e4266791c86b9302682970e23`
- **Upstream commit date:** 2026-07-03
- **Vendor date:** 2026-07-04
- **License:** MIT (SPDX: MIT) — Copyright (c) 2026 Matt Pocock. Full text at the upstream LICENSE; not copied here.
- **Supply-chain review:** CLEAN (adversarial opus review, 2026-07-04) — no runtime-fetch / permission-change / meta-instruction.
- **Local modifications:**
  - Remapped output from the upstream issue tracker to file-based tickets at
    `docs/superpowers/plans/<slug>/tickets/NNN-<name>.md` (zero-padded
    sequence number, dependency order) — every "publish/fetch to/from the
    issue tracker" step became "write/read the ticket file".
  - Replaced the upstream issue-body template (`## Parent` / `## What to
    build` / `## Acceptance criteria` / `## Blocked by`) with this repo's W5
    ticket schema: YAML frontmatter (`status`, `agent`, `model`, `depends_on`,
    `files`) + a scope/acceptance-criteria/out-of-scope body, embedded inline
    in `SKILL.md` so it is self-contained even where `.claude/workflow.md §
    W5` is absent.
  - Stripped the `/setup-matt-pocock-skills` reference and all
    tracker/triage-label vocabulary ("AFK agents", triage labels) — no issue
    tracker or label system exists in this repo.
  - Repointed "domain glossary vocabulary" to `CONTEXT.md`'s ubiquitous-language
    vocabulary, and "respect ADRs" to this repo's inline-in-spec ADR
    convention (`docs/superpowers/specs/`) instead of a `docs/adr/` directory.
  - Kept the vertical-slice / tracer-bullet rules verbatim in spirit, the
    "quiz the user" step, dependency-first write ordering, and the "Do NOT
    close or modify any parent ticket" safety note.
  - Kept `disable-model-invocation: true`.
