# docs-keeper report — setsid-detach gotcha for background pollers

## Scope

Diff zone: one gotcha entry added to `docs/known_issues.md` on branch
`claude/ner-translation-config-b0ozsc` (shared worktree). No code/contract
change in this task — this is a knowledge-capture entry from an operational
incident (background pollers reaped silently during a cloud session), not a
code-driven doc-parity update. Per the shared-worktree constraint, staging
was selective: only `docs/known_issues.md` and this report. `reports/**`,
`src/**` and any other in-flight untracked files in the shared worktree
(e.g. `docs/reports/docs-keeper-ner-translation-config.md`,
`reports/bouquet/judges/...`) were left untouched — they belong to other
concurrent work in this worktree, not this task.

## Files changed

- `docs/known_issues.md` — added one `### Background pollers launched with
  plain nohup ... & disown die when the cloud session's shell is torn down
  (2026-07-09)` entry under `## Open`, appended after the existing
  2026-07-08 deepseek-v4-flash entry (file's entries run roughly
  chronological within accumulating sections; this keeps the newest at the
  bottom, consistent with the surrounding entries' dated headings).

## Decisions & rationale

- **Placement**: appended at the very end of the file rather than inserted
  mid-file, matching the existing convention where dated entries
  (2026-07-06 through 2026-07-08) accumulate toward the bottom.
- **Evidence links**: cited both `docs/reports/python-pro-judge-run-deepseek.md`
  and `docs/reports/python-pro-judge-run-gemini-flash-lite.md` (the latter
  is the actual on-disk filename for the "flash-lite-think" judge run the
  task description referred to — grepped `docs/reports/` for
  `judge-run-*` and confirmed no file literally named `flash-lite-think`
  exists; `python-pro-judge-run-gemini-flash-lite.md` is the closest and
  correct match, referenced instead of inventing a path).
- **Style match**: kept the entry in the file's existing register — English,
  B2, short-to-medium sentences, a `### <Title> (date)` heading, one
  paragraph body, code spans for commands/flags, bold for the durable
  pattern's key steps — matching neighboring entries like "CloseRouter:
  provider-9 pin..." and "deepseek-v4-flash still reasons on route auto...".
- **Content fidelity**: reproduced the substance given in the task exactly
  (nohup/disown vs setsid distinction, both kill timestamps ~04:17Z/~05:41Z,
  0-byte stdout logs, no traceback, the `ps -o pid,ppid,pgid,sid` verification
  recipe, fresh-log-per-relaunch, and the "don't rely on harness
  notifications for OS-detached processes" self-verification note) without
  adding unverified claims of my own.

## Open questions

- None. This is a standalone operational gotcha, not tied to a specific
  code module, so no L1→L4 index update or cross-link elsewhere in the docs
  tree was needed.

## NOT done (explicit)

- Did not touch `reports/bouquet/judges/summary.md` (modified in the shared
  worktree) or the untracked `reports/bouquet/judges/gemini-3.1-flash-lite-think/`
  and `reports/bouquet/judges/gemini-3.1-pro/` directories — out of scope
  per the task's explicit staging restriction (`reports/**`, `src/**` never
  touched by this task).
- Did not touch the pre-existing untracked
  `docs/reports/docs-keeper-ner-translation-config.md` — belongs to a
  different concurrent docs-keeper task in this shared worktree.
- No L1/L2/L3 index update — `docs/known_issues.md` is a flat gotcha list
  with no per-entry index; the up-link from `docs/README.md` already covers
  the whole file.
