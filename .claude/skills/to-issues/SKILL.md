---
name: to-issues
description: Break a plan, spec, or PRD into independently-grabbable file-based tickets under docs/superpowers/plans/<slug>/tickets/ using tracer-bullet vertical slices.
disable-model-invocation: true
---

# To Issues

Break a plan into independently-grabbable **file-based tickets** using vertical
slices (tracer bullets). This repo has no issue tracker — tickets are files.

## Process

### 1. Gather context

Work from whatever is already in the conversation context. If the user passes
a ticket reference (a ticket number, path, or the plan/spec it came from) as
an argument, read that ticket file (or the plan/spec) in full before drafting.

### 2. Explore the codebase (optional)

If you have not already explored the codebase, do so to understand the
current state of the code. Ticket titles and descriptions should use the
project's [CONTEXT.md](../../../CONTEXT.md) ubiquitous-language vocabulary,
and respect ADRs in the area you're touching — this repo records ADRs inline
in the relevant spec under `docs/superpowers/specs/`, not in a separate
`docs/adr/` directory, so check the source spec's body for an ADR-style
"decision and alternatives" section before drafting.

Look for opportunities to prefactor the code to make the implementation
easier. "Make the change easy, then make the easy change."

### 3. Draft vertical slices

Break the plan into **tracer bullet** tickets. Each ticket is a thin vertical
slice that cuts through ALL integration layers end-to-end, NOT a horizontal
slice of one layer.

<vertical-slice-rules>

- Each slice delivers a narrow but COMPLETE path through every layer (schema, API, UI, tests)
- A completed slice is demoable or verifiable on its own
- Any prefactoring should be done first

</vertical-slice-rules>

### 4. Quiz the user

Present the proposed breakdown as a numbered list. For each slice, show:

- **Title**: short descriptive name
- **Blocked by**: which other slices (if any) must complete first
- **User stories covered**: which user stories this addresses (if the source material has them)

Ask the user:

- Does the granularity feel right? (too coarse / too fine)
- Are the dependency relationships correct?
- Should any slices be merged or split further?

Iterate until the user approves the breakdown.

### 5. Write the ticket files

For each approved slice, write a new ticket file to
`docs/superpowers/plans/<slug>/tickets/NNN-<name>.md`, where:

- `<slug>` is the kebab-case stem of the source plan/spec this breakdown came
  from (e.g. a plan at `docs/superpowers/plans/2026-07-03-wiki-eval-plan.md`
  gets tickets under `docs/superpowers/plans/2026-07-03-wiki-eval-plan/tickets/`);
  if there is no single source plan, pick a fresh kebab-case slug for the
  breakdown and say so to the user.
- `NNN` is a zero-padded 3-digit sequence number (`001`, `002`, ...) in
  dependency order (blockers first), so later tickets can reference earlier
  ones by their real ticket number in "depends_on".
- `<name>` is a short kebab-case slice name.

Use the ticket schema below (this repo's W5 frontmatter — canonical home
`.claude/workflow.md § W5` when that file is present in the checkout; the
schema is reproduced here in full so this skill is self-contained even
without it).

<ticket-schema>

```yaml
---
status: ready          # ready | in-progress | blocked | done
agent: <named-agent>   # a named agent from CLAUDE.md's dispatch map, e.g. backend-developer
model: sonnet           # a ticket is a plan to execute -> always sonnet (CLAUDE.md model routing R5)
depends_on: []          # list of blocking ticket numbers, e.g. [1, 2]; [] if none
files: []               # repo paths this ticket is expected to touch
---
```

Body, in order:

1. **Scope** — up to 10 lines describing the end-to-end behavior of this
   vertical slice, not layer-by-layer implementation. Avoid specific file
   paths or code snippets — they go stale fast. Exception: if a prototype
   produced a snippet that encodes a decision more precisely than prose can
   (state machine, reducer, schema, type shape), inline it here and note
   briefly that it came from a prototype. Trim to the decision-rich parts —
   not a working demo, just the important bits.
2. **Acceptance Criteria** — a numbered list; each item is either an
   executable command with its expected output (e.g. `pytest tests/x.py::y`
   → `1 passed`) or an observable UI fact (e.g. "the Settings tab shows a
   `Registered models` table row for the new provider").
3. **Out of scope** — exactly one line naming what this slice deliberately
   does not cover.

</ticket-schema>

Example ticket body shape:

```markdown
---
status: ready
agent: backend-developer
model: sonnet
depends_on: []
files:
  - src/palimpsest/webapp/routes/models.py
  - docs/subsystems/webapp.md
---

## Scope

Add a `POST /api/models` endpoint that registers a new model entry in the
`model` table and returns its id. No UI yet — this slice proves the
schema + API path end-to-end.

## Acceptance Criteria

1. `curl -X POST localhost:8000/api/models -d '{"name":"gpt-5.5-low"}'` → `201`, body has `"id"`.
2. `pytest tests/webapp/test_models.py::test_register_model` → `1 passed`.

## Out of scope

The Settings-tab UI that calls this endpoint (next slice).
```

Write ticket files in dependency order (blockers first) so each ticket can
reference the real ticket numbers of the tickets it depends on in
`depends_on`.

**Do NOT close or modify any parent ticket** (the plan/spec this breakdown
came from, or any ticket already marked `done`).
