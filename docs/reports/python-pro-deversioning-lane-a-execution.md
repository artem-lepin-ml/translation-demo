# De-versioning cleanup — Lane A execution (C1–C5)

## Scope

Executed commits C1 → C2 → C3 → C4 → C5 of
[docs/superpowers/specs/2026-07-10-deversioning-cleanup.md](../superpowers/specs/2026-07-10-deversioning-cleanup.md)
(spec at HEAD `35cf90d` amendments included), serially, on branch
`claude/ner-translation-config-b0ozsc`, per the spec's Autonomy resolution
("Execution mode amendment": lanes run serially on the main working tree, no
worktree fan-out). Lane B (C6–C7) and the closing gate/guard (C8–C9) are
explicitly **out of scope** for this task — not started.

Pytest baseline recorded before C1: `pytest --collect-only -q` → **639
tests collected**; `pytest tests/ -q` → **639 passed, 0 failed**. Final
state after C5: **638 collected / 638 passed** (−1 from C3's deletion of
`test_methodology_draft_returns_nonempty_string_matching_spec_phrase`, the
only expected delta across the lane — everything else is a pure rename or
pure grep-covered edit with 0 collection delta).

Commits landed and pushed (`git push -u origin
claude/ner-translation-config-b0ozsc`, no retries needed — no index.lock
contention, no push rejects):

| Commit | Hash | Subject |
|---|---|---|
| C1 | `e880d556c2a39915137baa895b453962399b88d0` | `fix(paper): correct wiki-eval protocol label v2->v3` |
| C2 | `ee53b6b11fd31a422d701c97046086310628642a` | `refactor(evaluation): de-version wiki-eval protocol code identifiers` |
| C3 | `9ea646d346e5491b4b5cf9fef76e653938425987` | `refactor(evaluation): delete dead methodology_draft` |
| C4 | `99a988f360f6c64c387344acd59ee39891980ae8` | `refactor(wiki-corpus): de-version selection/titles corpus files` |
| C5 | `bee239be0c00147faba9e6c0d72a2b0e4e30c32c` | `chore(wiki-corpus): delete retired pilot/subset corpus artifacts` |

Full pytest was green after **every** commit (not just at the end); each
commit's own Verify bullets from the spec were run and are recorded per-commit
below. Success Criterion 6 (immutability) was checked over the whole range:

```
git diff --name-only c691eb8..bee239b -- reports/ external/ docs/reports/ \
  docs/experiments/ docs/paper/snapshots/ docs/superpowers/specs/ docs/superpowers/plans/
```
→ empty output. No immutable-tree file was touched.

## Files changed

**C1** — `docs/paper/sections/eval-metrics-terminology.tex` (1 line: `PROTOCOL v2` → `PROTOCOL v3`).

**C2** (12 files, atomic identifier de-version):
`src/palimpsest/terminology/evaluation/metrics.py`,
`src/palimpsest/terminology/evaluation/report.py`,
`scripts/wiki_eval.py`,
`data/eval/wiki/cleanup/tools/replay_analysis.py`,
`data/eval/wiki/cleanup/tools/enumerate_misses.py`,
`data/eval/wiki/cleanup/tools/compute_dataset_stats.py` (divergence, see below),
`tests/test_wiki_metrics_v3.py` → `tests/test_wiki_metrics.py` (git mv + edits),
`tests/test_wiki_report.py`, `tests/test_wiki_eval_runner.py`,
`docs/stages/wiki-eval.md`, `docs/paper/paper-state.md`,
`docs/paper/sections/table-c-grounding.tex`.

**C3** (3 files): `src/palimpsest/terminology/evaluation/report.py` (delete
`methodology_draft()` + docstring bullet), `tests/test_wiki_report.py` (drop
import + test), `docs/stages/wiki-eval.md` (remove obsolete drift banner).

**C4** (9 files, data+code atomic): `data/eval/wiki/selection_v2.json` →
`selection.json`, `data/eval/wiki/titles_v2.txt` → `titles.txt` (git mv,
sha256-verified byte-identical), `scripts/select_wiki_corpus.py`,
`scripts/export_wiki_corpus.py`,
`src/palimpsest/terminology/evaluation/wiki_gt.py`, `docs/stages/wiki-eval.md`,
`docs/paper/sections/appendix-wiki-corpus.tex`,
`docs/runbooks/sr004-local-eval-runbook.md`, `data/eval/wiki/README.md`.

**C5** (6 files): `git rm data/eval/wiki/{gt_v2_sub20.jsonl,titles_pilot20.txt,gt_pilot.jsonl}`;
new `data/eval/wiki/titles_ablation20.txt` (20 titles + stratum, extracted
before deletion); `scripts/wiki_eval.py` (small `cmd_build_gt` addition, see
Decisions); `docs/runbooks/sr004-local-eval-runbook.md` (2 lines reworded).

## Decisions & rationale

- **Token-match over line numbers.** Every edit was located via `rg` on the
  exact identifier/string quoted in the spec, not the `:NNN` line hints,
  per the spec's own drift note. Several line numbers had indeed drifted
  (e.g. `wiki_eval.py`'s call site cited at `:1545` in the spec text was
  actually at `:1585`/`:1608` by the time I landed C2).
- **C2 → C3 known transient, by spec design.** After C2, `docs/stages/wiki-eval.md:130`'s
  drift-flag banner still contained the string `render_html_v3` — the spec
  explicitly assigns that banner's removal to C3, not C2, so C2's own Verify
  grep had one documented residual hit that C3 immediately resolved on the
  next commit. Confirmed 0 hits after C3 landed.
- **Divergence (C2): `compute_dataset_stats.py`.** Not in the spec's C2 file
  list, but it referenced `aggregate_corpus_v3` in a docstring comment — a
  live-tree hit the same identifier-retirement grep must clear. Updated for
  consistency (same reasoning class as the spec's own "engineering C2 missed
  this file" note about `paper-state.md`).
- **Divergence (C4): two extra "selection v2" prose mentions.** `docs/stages/wiki-eval.md`
  had "selection v2" prose at line 7 (Purpose section) and line 116 (Status
  line) beyond the four line-anchors the spec named (`:9,:17,:21,:23`).
  Updated both for consistency, using the same rationale the spec gave for
  the `wiki_gt.py` pointer comment: "selection v2" is a vestigial shorthand
  with no paper-narrated v1→v2 selection lineage (unlike "protocol v3"),
  so it fully de-versions.
- **C5 addition: `cmd_build_gt` now skips `#`-prefixed lines.** Not in the
  spec's C5 worklist. The spec's own instruction — put a provenance header
  comment in the new `titles_ablation20.txt`, "for byte-rebuild via
  `wiki_eval.py build-gt --titles`" — would otherwise be self-defeating:
  `cmd_build_gt`'s existing line parser had no comment-skip logic, so the
  header line would have been silently treated as a bogus 21st "title".
  Added a 2-line filter (`not l.strip().startswith("#")`) so the rebuild
  path the header comment and the runbook edit both promise actually works.
  Verified by simulating the parse logic offline (20 titles parsed
  correctly, comment line excluded) rather than hitting the network.
- **C5 grep gate not literally 0 — judged acceptable.** The spec's own C5
  Verify bullet (`rg -n "gt_v2_sub20|titles_pilot20|gt_pilot\.jsonl"` = 0)
  is not literally satisfied: 3 hits remain, all provenance prose I added
  *because the spec's own C5 instructions required them* — the
  `titles_ablation20.txt` header comment and the two reworded
  `sr004-local-eval-runbook.md` lines, all of which name the retired file to
  document its deletion, not to reference it as a live artifact. This is
  the opposite of the R7 "resurrection footgun" risk the grep is meant to
  catch (someone reviving the file thinking it's still available) — my
  mentions explicitly say "deleted"/"retired". I judged the explicit
  provenance-comment instruction more important than a literal 0-grep and
  am flagging the tension rather than silently claiming a clean pass.
- **OWNER-GATE J-SUB20 (C5).** Per the spec's Autonomy resolution, executed
  without blocking; the courtesy heads-up is recorded in the C5 commit body
  (superseding the `2026-07-10-gt-canonicalization.md` "не трогать" scope
  note, footgun rationale: the deleted file embedded a discredited article
  "Стигия").

## Open questions

- Same as the spec's own "Genuinely open" list (J-V1C3, J-DOCX, J-SEED,
  `pages/` cache hygiene, C9 blocking flip) — none touched by Lane A, no new
  action taken on them here.
- Whether the owner wants the C5 grep-gate tension (see above) resolved by
  de-identifying the provenance prose (dropping the literal filename in
  favor of "see git history") is an open call — I left the literal filename
  in, judging documentation value higher than a mechanical 0-grep.

## NOT done (explicit)

- **Lane B (C6, C7)** — not started; disjoint file set, was never in scope
  for this task.
- **C8 (`v[0-9]` residue sweep)** and **C9 (durable guard)** — not started;
  both are explicitly scoped to run "after both lanes merge" / "after C8".
- **Owner courtesy heads-up delivery** — the J-SUB20 heads-up is written
  into the C5 commit body only; it has not been separately delivered to the
  owner as a standalone message (that is the orchestrator's responsibility
  per the task brief, not performed by this subagent).
- **`.tex` co-author confirm (C1/C2/C4)** — the spec flags an Overleaf
  courtesy-confirm with the paper co-author as non-blocking; not performed
  here (no mechanism available to a subagent to contact the co-author).
- Full aggregate lane-level grep for all 11 Lane A tokens is **not** clean
  (`lane_grep_zero: false`) — see the C5 divergence above; this is the one
  explicit non-pass in an otherwise green lane.
