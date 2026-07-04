---
description: Extract generalizable lessons from the current session into the experiments knowledge base.
argument-hint: [slug]
allowed-tools: Read, Write, Edit, Bash
---

# /retrospective

Run a lesson-extraction retrospective over the **current transcript**.

Arguments from the user: `$ARGUMENTS` (optional slug for the drafted skill file;
if empty, derive a short kebab-case slug from the session's main topic).

## Workflow

1. Re-read the current session transcript and identify what was learned:
   gotchas hit, dead ends, provider/tooling quirks, and any decision that would
   save a future run time. Focus on the **generalizable** — not one-off facts.
2. Append each lesson as a dated bullet to `docs/experiments/LESSONS.md`
   (one line per lesson; append, never rewrite existing entries).
3. If a lesson is **generalizable** (reusable beyond this session), draft a
   skill file into `.claude/skills/lessons/<slug>.md` capturing the reusable
   procedure, then hand it off to the **pr-writer** agent — do not open a PR
   yourself.
4. Report inline (≤10 lines): the lessons appended, and the skill drafted (if
   any) with its path.

Nothing here executes experiment code; this is documentation only.
