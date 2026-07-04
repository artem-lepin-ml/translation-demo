# VENDORED

- **Source repo:** https://github.com/mattpocock/skills
- **Upstream path:** skills/engineering/grill-with-docs/
- **Pinned commit SHA:** `272f99b22574f50e4266791c86b9302682970e23`
- **Upstream commit date:** 2026-07-03
- **Vendor date:** 2026-07-04
- **License:** MIT (SPDX: MIT) — Copyright (c) 2026 Matt Pocock. Full text at the upstream LICENSE; not copied here.
- **Supply-chain review:** CLEAN (adversarial opus review, 2026-07-04) — no runtime-fetch / permission-change / meta-instruction.
- **Local modifications:**
  - Stripped the `/domain-modeling` reference (not vendored in this repo) and inlined its glossary + ADR-note behavior directly into SKILL.md.
  - Remapped doc targets: glossary now lives in `CONTEXT.md` at the repo root (not a `docs/adr/` dir); decision notes are appended to the current spec under `docs/superpowers/specs/YYYY-MM-DD-<slug>.md`, not to a separate ADR store.
  - Rephrased the upstream `/grilling` skill invocation into a prose method-reference ("the same method as the `grilling` skill, see `.claude/skills/grilling/SKILL.md`") instead of a literal `/grilling` call, per this repo's rule that a user-invoked skill never calls another user-invoked skill.
  - Kept `disable-model-invocation: true` from upstream frontmatter unchanged.
