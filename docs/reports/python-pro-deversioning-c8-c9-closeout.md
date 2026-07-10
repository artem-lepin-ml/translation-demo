# De-versioning cleanup — C8/C9 closeout (agent task report)

Mandatory per-agent report (Reporting protocol). The owner-facing deliverable for this
task is [docs/reports/deversioning-c8-sweep-record.md](deversioning-c8-sweep-record.md);
this file is the process/audit trail for the orchestrator, not a second owner report.

## Scope

Closed out [docs/superpowers/specs/2026-07-10-deversioning-cleanup.md](../superpowers/specs/2026-07-10-deversioning-cleanup.md)
after Lane A (`e880d55`..`bee239b`) and Lane B (`e764678`, `e11be5f`) landed:

- **C8** — human-triaged `v[0-9]` residue sweep over the live tree, gated on the § C8
  allowlist (items 1–25), with two task-specified folds-in (translation-eval.md:115
  `from_model_config` prose; Lane A's 3 `gt_v2_sub20` provenance-prose mentions).
- **C9** — durable advisory guard: CLAUDE.md convention line, `.claude/allowlist-versioned.txt`,
  `.claude/hooks/no-new-version-suffix.py`, `.claude/settings.json` wiring.
- **Hygiene closeout** — stray `docs/reports/` stragglers committed, a new
  `docs/known_issues.md` entry, final clean-state verification.

Ran under the concurrent-agent constraint (a live wiki-eval run writing under
`reports/terminology/`): never staged `reports/` paths, exact-path `git add` only,
index.lock retry logic, push-after-each-commit.

## Files changed

| Commit | Files |
|---|---|
| `3288c37` chore: v-suffix residue sweep record + allowlist prose extension | `docs/reports/deversioning-c8-sweep-record.md` (new), `docs/superpowers/specs/2026-07-10-deversioning-cleanup.md` (item-25 wording extension), `scripts/select_wiki_corpus.py` (residue fix: dropped stale `[v2]` debug tag at `:196`) |
| `f4d1ab4` feat(hooks): advisory no-new-version-suffix guard (C9) | `CLAUDE.md` (one-line convention), `.claude/allowlist-versioned.txt` (new), `.claude/hooks/no-new-version-suffix.py` (new), `.claude/settings.json` (PreToolUse Bash matcher entry) |
| `31f75b4` docs: known-issues entry + stray task reports batch | `docs/known_issues.md` (new entry: `terminology_gold.jsonl` not reproducible from `merge_goldens.py`), `docs/reports/python-pro-deversioning-lane-a-execution.md` (landed, was untracked) |
| (this report, uncommitted at write time — see below) | `docs/reports/python-pro-deversioning-c8-c9-closeout.md` (new) |

## Decisions & rationale

- **Scripted bucket triage over an 833-row literal table.** The raw sweep was 834 hits
  (833 after the residue fix); a literal one-row-per-hit table would be unreadable and
  add no signal over the spec's own grouping precedent (e.g. its item 22 already buckets
  "SVG path-data commands"). Built a Python classifier keyed to each allowlist item's
  described tokens/patterns, then manually reviewed and spot-checked every bucket the
  script left ambiguous (19 lines) before folding in the final verdicts. Full accounting
  in the sweep record § 3–4.
- **Out-of-scope noise bucket (439 hits) kept separate from "allowlisted."** Lockfile
  hashes (`uv.lock`, `package-lock.json`) and cached wiki HTML pages
  (`data/eval/wiki/pages/*.html`) match `v[0-9]` only by coincidental substring / third-party
  content, and are not "our own artifacts" per the spec's own Scope section — classifying
  them as a 26th allowlist item would misrepresent them as legitimate version-suffix
  survivors rather than as sweep-pattern noise.
- **One true residue found and fixed, not deferred.** `scripts/select_wiki_corpus.py:196`'s
  `[v2]` debug-print tag was missed by C4 (C4's file-list only named `:2`, `:7`, `:204`).
  S-sized, one-token fix — within the spec's "small edits only" mandate for this closeout,
  so fixed directly rather than reported as a follow-up.
- **`scripts/merge_goldens.py:38` judged as historical prose, not residue.** The comment
  "my v1 golden over-labelled…" doesn't cite the retired `terminology_gold_v1.jsonl`
  filename — it reads as an informal note about an early manual-labeling round. Flagged as
  the one genuinely borderline call in § 6 of the sweep record rather than silently
  resolved either way, per the C8 gate's own judgment-based framing.
- **Known-issues entry written from task-supplied facts, independently spot-checked**
  (not blindly copied): confirmed `seed_paragraphs.jsonl` has 15 lines, the committed gold
  has 99, and commit `2493ec4` is genuinely the initial import — before writing the drift
  claim into `known_issues.md`. Did not execute `merge_goldens.py` live (it writes straight
  to the committed `data/seed/terminology_gold.jsonl` with no dry-run flag; re-running it
  to double-check the 16-row claim risked corrupting a committed data file for no
  additional confidence beyond what the task brief and the independent paragraph-count
  check already gave).
- **C9 hook mirrors `experiment-approval-gate.py`'s exact conventions**: same stdin-JSON
  read pattern, same `Bash` matcher (self-filtering to `git commit` inside the script
  rather than in the matcher regex), same fail-open exception handling, same
  `$CLAUDE_PROJECT_DIR`-relative invocation in `settings.json`.
- **C9 Verify done as a real allowlist-off sanity check, not just a positive/negative
  pair.** Beyond staging `foo_v2.py` (warns) and a `chrono_p31_v1` file (silent), also
  temporarily removed `.claude/allowlist-versioned.txt` and re-ran the hook against the
  same staged diff to confirm it DOES warn without the allowlist — proving the silence in
  the negative case is caused by the allowlist match, not an incidental path/regex miss.
  Both synthetic files were unstaged and deleted immediately after; `git status` showed no
  trace before the real C9 commit.

## Open questions

- **`docs/paper/handoff-paper-text-session-2026-07-10.md`** sits at `docs/paper/handoff-*.md`,
  not the top-level `docs/handoff-*.md` the spec's Immutability-rule glob names — the glob
  is non-recursive and doesn't cover nested `handoff-*.md` files. Flagged in the sweep
  record § 6 as a spec-wording gap; not fixed here (the one hit affected is Russian prose,
  not a code identifier, so it didn't matter in practice — but a future nested handoff file
  with real code-identifier content would slip the exclusion).
- **`data/seed/terminology_gold.jsonl` non-reproducibility** (new known-issues entry) has
  no resolution path decided — the entry explicitly asks the owner to choose between
  reconciling the docstring to 15 paragraphs or investigating whether a 16th paragraph was
  lost from `seed_paragraphs.jsonl`.
- **C9's blocking flip (J-GUARD)** stays with the owner per the spec — not addressed here,
  correctly out of scope for this closeout.

## NOT done (explicit)

- **Did not re-run `merge_goldens.py` live** to verify the 16-vs-99 row claim by direct
  execution (see rationale above) — relied on the task-supplied facts plus an independent
  paragraph-count/commit-existence spot check instead.
- **Did not edit the Immutability-rule's `docs/handoff-*.md` glob** to also cover nested
  paths (e.g. `docs/paper/handoff-*.md`) — flagged as an open question, not fixed, since it
  was outside this closeout's "small edits only" mandate and the one affected line wasn't
  actual residue.
- **Did not attempt the C9 blocking flip** — explicitly an owner decision per the spec
  (J-GUARD).
- **Did not investigate or fix the `docs/eval/wiki/pages/` cache-hygiene gap** (124 cached
  HTML vs 100 titles) — explicitly out of scope per the spec's non-goals.
- **Did not touch `J-V1C3`, `J-DOCX`, `J-SEED`** — the spec's own "genuinely open, no
  action" list; none of these fell inside C8/C9/hygiene-closeout scope.
