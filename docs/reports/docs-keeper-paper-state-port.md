# docs-keeper report: port + update `docs/paper/paper-state.md`

## Scope

Task-scoped diff, not a full-repo doc-parity sweep. Zone:
- Port `docs/paper/paper-state.md` from `origin/claude/ner-translation-pipeline-config-x7xyuj` into
  the current branch (`claude/ner-translation-config-b0ozsc`, tip of `origin/dev-demo`).
- Integrate today's (2026-07-08) owner decisions on the EMNLP paper's evaluation section
  (three-table restructuring, Table A judge lineup/protocol) into that file.
- Create the `v1_core3` filtered prompt variant directory referenced by the updated doc.
- Two commits + push, per explicit instructions from the dispatching orchestrator.

No other doc in the repo was read for drift in this pass — the task was scoped narrowly to
`docs/paper/paper-state.md` and the new prompt-variant directory it references. This is a
living-document port + edit, not an L1→L4 parity sweep across the whole repo.

## Files changed

- `docs/paper/paper-state.md` — created (ported from the sibling branch, then edited).
  Commit `b4ba4a3` — `docs(paper): restructure eval into three per-contribution tables;
  lock Table A judge protocol`.
- `external/gse-translation/prompts/03_scoring/v1_core3/accuracy.md` — created, verbatim
  copy of `v1/accuracy.md` (diff-verified identical).
- `external/gse-translation/prompts/03_scoring/v1_core3/fluency.md` — created, verbatim
  copy of `v1/fluency.md`.
- `external/gse-translation/prompts/03_scoring/v1_core3/style.md` — created, verbatim
  copy of `v1/style.md`.
  Commit `74b3ceb` — `feat(prompts): add v1_core3 scoring variant (accuracy/fluency/style
  only)`.

Both commits pushed to `origin/claude/ner-translation-config-b0ozsc` (new branch on
remote), first push attempt succeeded, no retries needed.

## Decisions & rationale

1. **Ported the file as-is first, then edited** (per explicit step order) rather than
   hand-authoring from scratch — preserves everything still valid from the sibling
   session (skeleton table, Related-work state, Done/Queued history) instead of risking
   silent loss of facts recorded there. Single-source-of-truth respected: the file is the
   one place tracking paper progress; nothing here duplicates the spec at
   `docs/superpowers/specs/2026-07-07-wiki-llm-judge-eval.md`, which is still linked from
   the header.

2. **Restructured T2/T3 → Table A/B/C in place, not as an append.** The owner's decision
   explicitly reframes the whole evaluation section (one table per contribution), so
   editing the existing "Skeleton" row and "Experiments → paper mapping" section
   in-place is correct doc-parity behavior rather than leaving stale T2/T3 language
   alongside new Table A/B/C language. Verified via `grep -n "T2\|T3"` after edit — only
   one incidental match remains, in prose describing the restructuring itself ("replaces
   the earlier flat T2/T3 numbering"), which is intentional and not a residual reference.

3. **Kept the BOUQUET "Done" entry but reattributed it to Table A**, and added an
   explicit note that the old Danil-verbatim numbers (T=0.7, thinking on — the
   screenshot numbers) are a *sensitivity footnote*, not part of the new Table A run.
   This matches instruction (c) precisely and avoids the doc silently implying the old
   run satisfies the new protocol.

4. **Table B keeps the Danil-verbatim judge config** (qwen3.6-27b, T=0.7, thinking on)
   distinct from Table A's new 7-judge protocol — added one clarifying sentence
   ("Table B is about refinement usefulness, not judge comparison, so the judge stays
   fixed") because the two tables now share the same wiki-100/refinement-adjacent
   territory and a reader could otherwise assume Table A's protocol also governs Table B.
   This is an inference to keep the doc internally consistent, not a fact the owner
   stated explicitly — flagged here for owner confirmation if wrong.

5. **`v1_core3` treated as a single artifact reused by both Table A and Table B**, per
   instruction (c)/(step 3) — one prompt-variant dir, not two. The Table B paragraph
   was edited to say "same filtered variant, no separate copy" to prevent a future
   reader/agent from creating a duplicate `v1_core3`-for-B directory.

6. **No code changes** — instruction (step 3) states `load_prompts` already globs `*.md`
   per variant dir, so `v1_core3/` needs no wiring. Not independently verified against
   the actual `load_prompts` implementation in this pass (see Open questions /
   NOT done) — taken on the orchestrator's explicit instruction since verifying it was
   out of the stated task scope (docs + prompt-file port only, no pipeline code touched).

7. **Verbatim copy, no content edits** to `accuracy.md`/`fluency.md`/`style.md`, per
   explicit instruction — confirmed with `diff` (byte-identical) rather than assuming.

## Open questions

- **Table B judge-fixing clarification (decision 4 above) is an inference**, not an
  owner-stated fact — worth a one-line owner confirmation next time the paper doc is
  touched, in case Table B is meant to eventually adopt the new 7-judge protocol too.
- **7-row Table B matrix and exact CloseRouter router IDs for the frontier judges are
  still explicitly "pending owner confirmation" / "pending probe"** in the source
  instructions — carried through unchanged as open items in the doc, not resolved here.
- **`load_prompts` glob behavior was not independently re-verified** in this pass (see
  NOT done) — the doc states it needs no code change based on the orchestrator's
  assertion.

## NOT done

- **No repo-wide doc-parity sweep.** Per the docs-keeper convention, edits are scoped to
  the diff zone (this file + the new prompt directory). Did not check whether other
  docs (e.g. `docs/README.md` L1 index, `docs/subsystems/*.md`, `docs/pipeline.md`)
  reference or should now link to `docs/paper/paper-state.md` or the eval restructuring
  — `docs/paper/` did not exist in this branch before this port, so there may be an L1
  index gap. Flagged, not fixed, since it's outside the explicit instruction set and the
  file is described as a living/working document tied to the sibling session's spec,
  not obviously an L1/L2/L3 subsystem doc.
- **Did not verify `load_prompts` glob logic in code** — took the orchestrator's
  assertion in the task instructions at face value; no `grep`/read of the actual
  pipeline source was performed to confirm `*.md`-globbing behavior in the variant dir.
- **Did not check for other stale T2/T3 references** anywhere else in the repo (e.g.
  `docs/superpowers/specs/2026-07-07-wiki-llm-judge-eval.md`) — out of scope per the
  explicit instruction (edit only `paper-state.md` + create the prompt dir).
- **No verified code↔doc pairs to list** — this task touched no application code, only
  a living-document Markdown file and static prompt-text files copied verbatim; there
  is no contract/implementation pairing to cross-check in this diff.
