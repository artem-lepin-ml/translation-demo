# Working style (owner preferences)

Durable behavioral preferences distilled from standing feedback. Language policy,
communication style and the HTML report template are canonical in the repo-root
[CLAUDE.md](../../CLAUDE.md) (§ Language policy, § Reports & communication style) —
this file carries only what is not covered there.

## Communication extras
- **Research → clickable direct link + one-line gloss** for every cited resource
  (repo/paper/tool); never a bare name.

## Estimates & scope
- **No human-day estimates.** Plans use S/M/L only. Time is never a reason to descope —
  the owner owns scope/effort, not the assistant.
- **Make existing things work; don't build prerequisites.** If something exists (even as
  a placeholder), wire it to work; don't turn a noticed gap into a CRUD/creation task.

## Reports
- **Dark Tokyo Night palette** (owner-approved). Canonical tokens:
  [tokyo-night.css](tokyo-night.css) (same directory). Green = pass, yellow = open/warn,
  red = fail, blue = data.
- Delivery rules (served HTML locally / Claude Artifact in cloud) → repo-root
  [CLAUDE.md](../../CLAUDE.md) § Reports & communication style / HTML report
  template. Never hand off a bare `.md` path — the owner can't open
  another worktree's files from his checkout.

## Naming & PRs
- **Keep dotted model names in filenames**: `gpt-5.5-low`, never `gpt55` (underscore only
  if dots are impossible).
- **PR bodies: Russian, concise, lead with the main idea**; group by theme, prefer
  tables/bullets, drop boilerplate; technical terms stay in English. No AI signatures
  in commits or PR bodies (CLAUDE.md Hard Invariant 7).
