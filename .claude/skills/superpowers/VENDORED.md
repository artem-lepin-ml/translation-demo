# Vendored: Superpowers skill set

- **Source repo:** https://github.com/obra/superpowers
- **Pinned commit SHA:** `d884ae04edebef577e82ff7c4e143debd0bbec99` (tag: release v6.1.1 — "fix Codex SessionStart hook re-registration, add Codex portal packaging")
- **Vendor date:** 2026-07-04
- **License:** MIT (SPDX: `MIT`) — Copyright (c) 2025 Jesse Vincent. Full text preserved at the upstream `LICENSE` file; not copied here (see repo link above). This vendoring is a subset of files under MIT terms; the license permits redistribution with attribution, retained above.

Vendored as **plain files** — no upstream plugin manifests, hooks, or install
scripts were copied. Only the skill content and the two runtime assets called
out below.

## Vendored skill folders (7, as specced)

| # | Skill | Upstream path | Vendored path |
|---|-------|----------------|----------------|
| 1 | brainstorming | `skills/brainstorming/` | `.claude/skills/superpowers-brainstorming/` |
| 2 | writing-plans | `skills/writing-plans/` | `.claude/skills/superpowers-writing-plans/` |
| 3 | subagent-driven-development | `skills/subagent-driven-development/` | `.claude/skills/superpowers-subagent-driven-development/` |
| 4 | dispatching-parallel-agents | `skills/dispatching-parallel-agents/` | `.claude/skills/superpowers-dispatching-parallel-agents/` |
| 5 | systematic-debugging | `skills/systematic-debugging/` | `.claude/skills/superpowers-systematic-debugging/` |
| 6 | using-git-worktrees | `skills/using-git-worktrees/` | `.claude/skills/superpowers-using-git-worktrees/` |
| 7 | finishing-a-development-branch | `skills/finishing-a-development-branch/` | `.claude/skills/superpowers-finishing-a-development-branch/` |

(Vendored path column reflects the post-2026-07-04-flatten depth-1 location;
see "Local modifications — flattened to depth-1" below. Originally each
folder vendored under a shared `.claude/skills/superpowers/<name>/` parent.)

Each folder was vendored **whole** (SKILL.md + every auxiliary file living
alongside it upstream), except brainstorming's `scripts/` (see below).

### File inventory

```
superpowers-brainstorming/SKILL.md
superpowers-brainstorming/spec-document-reviewer-prompt.md
superpowers-brainstorming/visual-companion.md
superpowers-brainstorming/brainstorm-server/frame-template.html
superpowers-brainstorming/brainstorm-server/helper.js
superpowers-brainstorming/brainstorm-server/server.cjs
superpowers-brainstorming/brainstorm-server/start-server.sh
superpowers-brainstorming/brainstorm-server/stop-server.sh
superpowers-writing-plans/SKILL.md
superpowers-writing-plans/plan-document-reviewer-prompt.md
superpowers-subagent-driven-development/SKILL.md
superpowers-subagent-driven-development/implementer-prompt.md
superpowers-subagent-driven-development/task-reviewer-prompt.md
superpowers-subagent-driven-development/scripts/review-package
superpowers-subagent-driven-development/scripts/sdd-workspace
superpowers-subagent-driven-development/scripts/task-brief
superpowers-dispatching-parallel-agents/SKILL.md
superpowers-systematic-debugging/SKILL.md
superpowers-systematic-debugging/CREATION-LOG.md
superpowers-systematic-debugging/condition-based-waiting-example.ts
superpowers-systematic-debugging/condition-based-waiting.md
superpowers-systematic-debugging/defense-in-depth.md
superpowers-systematic-debugging/find-polluter.sh
superpowers-systematic-debugging/root-cause-tracing.md
superpowers-systematic-debugging/test-academic.md
superpowers-systematic-debugging/test-pressure-1.md
superpowers-systematic-debugging/test-pressure-2.md
superpowers-systematic-debugging/test-pressure-3.md
superpowers-using-git-worktrees/SKILL.md
superpowers-finishing-a-development-branch/SKILL.md
superpowers/task-reviewer-prompt.md
superpowers/VENDORED.md
```

(Paths above are relative to `.claude/skills/`. `superpowers-subagent-driven-development/task-reviewer-prompt.md`
is now an unreferenced leftover copy of `superpowers/task-reviewer-prompt.md` —
see "Local modifications — flattened to depth-1" below.)

## Supporting assets

### `brainstorm-server` (the browser-based visual-companion server)

The spec asked to vendor `lib/brainstorm-server/` — **that path does not exist
at this SHA**. Upstream's superpowers repo has no top-level `lib/` directory;
the equivalent asset (a zero-dependency WebSocket/HTTP server for the
brainstorming skill's visual companion) lives at
`skills/brainstorming/scripts/` and consists of `server.cjs`, `helper.js`,
`start-server.sh`, `stop-server.sh`, `frame-template.html`. This is the asset
the spec's destination path (originally `.claude/skills/superpowers/brainstorming/brainstorm-server/`,
now `.claude/skills/superpowers-brainstorming/brainstorm-server/` — see
"Local modifications — flattened to depth-1" below) clearly refers to, so it
was vendored there, **renamed from `scripts/` to `brainstorm-server/`** per
the spec's explicit destination.

### `task-reviewer-prompt.md` (v6.0 unified reviewer)

**Found, no discrepancy.** At this SHA the file already is the unified v6.0
template: `skills/subagent-driven-development/task-reviewer-prompt.md`.
Confirmed via `RELEASE-NOTES.md` (v6.0.0, 2026-06-16): *"The two per-task
reviewer prompts became one. `spec-reviewer-prompt.md` and
`code-quality-reviewer-prompt.md` are gone, replaced by a single
`task-reviewer-prompt.md`."* The file itself returns two verdicts (spec
compliance + code quality) in one report, matching that description. No
separate legacy `spec-reviewer-prompt.md` / `code-quality-reviewer-prompt.md`
exist anywhere in the repo at this SHA (checked full-tree grep).

Vendored to **both**:
- `.claude/skills/superpowers/subagent-driven-development/task-reviewer-prompt.md`
  (kept in place — `subagent-driven-development/SKILL.md` references it via
  the relative link `./task-reviewer-prompt.md`; removing it would break that
  skill).
- `.claude/skills/superpowers/task-reviewer-prompt.md` (top-level copy, as
  explicitly specced).

Both copies are byte-identical to the upstream file; no rewrite needed since
it contains no upstream-layout-assuming paths.

**2026-07-04 update:** after the depth-1 flatten (see "Local modifications —
flattened to depth-1" below), `superpowers-subagent-driven-development/SKILL.md`
now points at the holder copy via `../superpowers/task-reviewer-prompt.md`
instead of its own local `./task-reviewer-prompt.md`. The local copy at
`.claude/skills/superpowers-subagent-driven-development/task-reviewer-prompt.md`
is consequently an unreferenced duplicate, left in place rather than deleted
(not asked for; still byte-identical to the holder copy).

## Local modifications (relative-path rewrites)

Vendoring moved the brainstorming skill from `skills/brainstorming/` (repo
root) to `.claude/skills/superpowers/brainstorming/` and renamed its
`scripts/` subfolder to `brainstorm-server/`. Three files contained paths that
assumed the old location/name and were rewritten:

1. **`brainstorming/brainstorm-server/server.cjs`** (`readSuperpowersVersion()`,
   was line 209): `path.join(__dirname, '../../..')` → `path.join(__dirname, '../..')`.
   Upstream, `server.cjs` sits 3 levels below the repo root
   (`skills/brainstorming/scripts/`) and reads `package.json` /
   `.codex-plugin/plugin.json` there to render a "Superpowers vX.Y.Z" brand
   string. Vendored, it sits 2 levels below `.claude/skills/superpowers/`
   (`brainstorming/brainstorm-server/`). Neither manifest is vendored, so this
   still resolves to the `'unknown'` fallback either way — fixed the
   arithmetic anyway so the lookup is self-consistent with the new location
   (forward-compatible if a version manifest is ever added at
   `.claude/skills/superpowers/`). Comment added explaining this.

2. **`brainstorming/visual-companion.md`**: 8 occurrences of `scripts/<file>`
   rewritten to `brainstorm-server/<file>` (lines 38, 65, 74, 82, 90 —
   `start-server.sh`; 283 — `stop-server.sh`; 290, 291 — `frame-template.html`,
   `helper.js` reference list). These are the shell commands and reference
   list an agent following this skill would actually run/read; left unrewritten
   they'd 404 against the renamed folder.

3. **`brainstorming/SKILL.md`** (was line 159): `` `skills/brainstorming/visual-companion.md` ``
   (a repo-root-relative path, valid only in the upstream layout where
   `skills/` sits at the repo root) → `` `visual-companion.md` (this skill's
   directory) `` — same-directory relative reference, matching the convention
   used elsewhere in these skills (e.g. subagent-driven-development's
   `./task-reviewer-prompt.md`).

No other vendored file contained a hardcoded upstream-layout path (checked:
`plugins/`, `~/.claude`, `../../lib/`, and bare absolute `/`-paths across all
brainstorming assets — the only hits were the three above plus
`server.cjs`'s own `__dirname`-relative reads of `frame-template.html` /
`helper.js`, which are same-directory and needed no change).

All other skill folders (writing-plans, subagent-driven-development,
dispatching-parallel-agents, systematic-debugging, using-git-worktrees,
finishing-a-development-branch) were vendored as self-contained units with no
cross-file relative paths that reach outside their own folder, so no rewrites
were needed there. The `.superpowers/sdd/` workspace convention
(`subagent-driven-development/scripts/sdd-workspace`) resolves its directory
via `git rev-parse --show-toplevel` at runtime — dynamic, not a hardcoded
path — and needed no change; it still lives outside `.git/`, self-ignoring,
exactly as upstream.

## Local modifications (G4/§8 supply-chain review)

- **`brainstorming/brainstorm-server/server.cjs`** (`brandMarkup()`, and the
  removed `SUPERPOWERS_BRAND_IMAGE_URL` constant): **G4/§8 — removed the
  browser-side remote brand-logo fetch to primeradiant.com.** Upstream,
  `brandMarkup()` emitted `<img src="https://primeradiant.com/brand/…png">`
  into every served companion page whenever telemetry was not disabled, so a
  viewer's browser fetched that remote asset at runtime. The `<img>` and the
  `SUPERPOWERS_BRAND_IMAGE_URL` constant were removed; `brandMarkup()` now
  **always** renders the plain-text brand (the former telemetry-disabled
  branch: `Prime Radiant Superpowers v<version>`), so no served page reaches
  any external host. No other behavior changed. The now-unreferenced
  `SUPERPOWERS_TELEMETRY_DISABLED` constant and its env-var detection were left
  in place (pre-existing, unrelated — not ripped out). `node -c` passes; the
  vendored tree has no remaining runtime fetch of remote content in live code.

## Local modifications (T-P0.3 — dangling `superpowers:` cross-references)

- Rewrote inter-skill `superpowers:<name>` cross-references inside vendored
  SKILL.md files to relative `../<name>/SKILL.md` sibling links (the
  `superpowers:` plugin namespace no longer resolves after vendoring).
  References to skills outside the 7 vendored here (`requesting-code-review`,
  `test-driven-development`, `executing-plans`, `verification-before-completion`)
  were converted to plain prose naming the skill plus "(not vendored in this
  repo)" instead, so nothing points at a path that doesn't exist. Touched:
  - `.claude/skills/superpowers-subagent-driven-development/SKILL.md`
  - `.claude/skills/superpowers-writing-plans/SKILL.md`
  - `.claude/skills/superpowers-systematic-debugging/SKILL.md`

## Local modifications (2026-07-04 — flattened to depth-1 for skill discovery)

- **Bug:** Claude Code only auto-discovers skills at `.claude/skills/<name>/SKILL.md`
  (depth 1). All 7 skills lived at `.claude/skills/superpowers/<name>/SKILL.md`
  (depth 2), so none of them were registered as invocable skills.
- **Fix:** flattened the 7 skill dirs from `superpowers/<name>/` to
  `superpowers-<name>/` (depth-1) via `git mv`, so Claude Code auto-discovers
  them as invocable skills. `VENDORED.md` and `task-reviewer-prompt.md`
  remain in `.claude/skills/superpowers/`, which now holds only those two
  files (provenance/holder dir, not a skill dir itself).
- **Refs updated:** inter-skill cross-references inside the moved SKILL.md /
  aux files (`../<name>/SKILL.md` → `../superpowers-<name>/SKILL.md` for the
  7; refs to the shared `task-reviewer-prompt.md` → `../superpowers/task-reviewer-prompt.md`),
  `.claude/process.md`, this file, `.claude/portable-manifest.json`
  (`layers.core.dirs`), and one broken link in the top-level `CLAUDE.md`
  (`using-git-worktrees`). Dated historical docs under `docs/superpowers/plans/`,
  `docs/goals/`, and `docs/reports/` that mention the old `skills/superpowers/<name>/`
  paths were left untouched — they are point-in-time records, not live routing
  docs.
