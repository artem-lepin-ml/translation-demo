# Working style (owner preferences)

Durable behavioral preferences distilled from standing feedback.

## Communication
- **Owner-facing output is Russian** (chat replies, reports, specs/plans, flags). Think,
  plan, and instruct subagents in English (token economy). Project docs keep their
  existing language.
- **Lead with the main thing**, then overview, then specifics. Be honest and critically
  list shortcomings yourself. Explicitly separate "ran" vs "didn't run + why". No
  boilerplate headers (`## Summary` / `## Description`).
- **Explain design alternatives in prose** (context → 2-3 options with code-level
  tradeoffs → a recommendation), not packed `AskUserQuestion` options. Reserve
  `AskUserQuestion` for narrow binary/terminology choices.
- **Research → clickable direct link + one-line gloss** for every cited resource
  (repo/paper/tool); never a bare name.

## Estimates & scope
- **No human-day estimates.** Plans use S/M/L only. Time is never a reason to descope —
  the owner owns scope/effort, not the assistant.
- **Make existing things work; don't build prerequisites.** If something exists (even as
  a placeholder), wire it to work; don't turn a noticed gap into a CRUD/creation task.

## Reports
- **HTML reports: dark Tokyo Night palette** (owner-approved). Reuse the exact tokens:
  `--bg:#1a1b26; --bg2:#1f2335; --panel:#24283b; --line:#2f334d; --tx:#c0caf5;
  --blue:#7aa2f7; --green:#9ece6a; --yel:#e0af68; --red:#f7768e; --purple:#bb9af7`.
  Green = pass, yellow = open/warn, red = fail, blue = data. Serve locally on completion
  (`python3 -m http.server` on 127.0.0.1) and give the direct link.
- Owner can't open another worktree's files from his checkout — render specs/plans/reports
  to served local HTML, never hand off a bare `.md` path.

## Naming & PRs
- **Keep dotted model names in filenames**: `gpt-5.5-low`, never `gpt55` (underscore only
  if dots are impossible).
- **PR bodies: Russian, concise, lead with the main idea**; group by theme, prefer
  tables/bullets, drop boilerplate; technical terms stay in English.
