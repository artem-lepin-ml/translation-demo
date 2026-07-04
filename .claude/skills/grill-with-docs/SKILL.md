---
name: grill-with-docs
description: A relentless interview to sharpen a plan or design, which also creates docs (ADR-style decision notes and a glossary) as we go.
disable-model-invocation: true
---

Run a relentless, one-question-at-a-time interview to sharpen the plan or design at
hand — the same method as the `grilling` skill (see `.claude/skills/grilling/SKILL.md`):
no multi-part questions, don't move on until the current answer is sharp. Do not
invoke `/grilling` as a skill call — both are user-invoked and a user-invoked skill
never calls another; follow its method in prose instead.

As a ubiquitous-language term surfaces or sharpens, record/update its row in
`CONTEXT.md` at the repo root — `term | meaning | code anchor` — creating the file
lazily on first use.

When a load-bearing decision lands, append to the **current spec**
(`docs/superpowers/specs/YYYY-MM-DD-<slug>.md`, never a separate ADR store):

```
## ADR: <title>
- **Decision:** …
- **Context:** …
- **Consequences:** …
```

Keep grilling until no soft spots remain; the CONTEXT.md rows and spec ADRs are the
deliverable alongside the sharpened plan.
