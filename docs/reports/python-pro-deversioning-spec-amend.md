# Report: amend de-versioning cleanup spec per verify-spec findings

## Scope

Task: amend `docs/superpowers/specs/2026-07-10-deversioning-cleanup.md` per 24 verify-spec
findings (1 CRITICAL, 9 HIGH, 8 MEDIUM, 6 LOW) and their orchestrator dispositions, on branch
`claude/ner-translation-config-b0ozsc` (verify-only branch, never switched), commit, push.
Edit scope was restricted to that single spec file. No code was touched — this was a
documentation-only task; the spec's own plan (C1–C9) has not been executed.

## Files changed

- `docs/superpowers/specs/2026-07-10-deversioning-cleanup.md` — 160 insertions / 68 deletions.
  Commit `35cf90d`, pushed to `origin/claude/ner-translation-config-b0ozsc` (fast-forward, no
  retries needed — no `index.lock` contention, no push rejection encountered).

No other files were modified. `docs/reports/python-pro-deversioning-spec-install.md` and
`reports/terminology/wiki-eval/google--gemma-3-27b-it--Parasail/` appeared as untracked in
`git status` throughout the session (concurrent agents on the shared working tree) — not touched.

## Decisions & rationale

All 16 numbered instructions from the dispatch were applied; see the final chat message to the
orchestrator for the exhaustive line-by-line mapping. Key judgment calls made while executing
(each grounded in a live-file check, not assumption):

- **Item 1 (pinned numbers):** verified `n_ambiguous_gold_units=112`,
  `n_gold_mentions_dropped_by_tier=764`, named tp/fn/fp/gold_units=`3078/807/1526/3885`, total
  `gold_units=5351` directly against `tests/test_wiki_metrics_v3.py` at HEAD — the orchestrator's
  supplied numbers were correct. Reframed the criterion so the diff-based check is authoritative
  and the numbers are informational only, per instruction.
- **Item 7 (line-anchor drift):** the orchestrator's example figure ("+15") did not match live
  reality — `grep` showed `scripts/wiki_eval.py`'s `aggregate_corpus_v3` call site had actually
  drifted from the spec's cited `:1545` to `:1577` (+32), and the spec's third cited anchor
  (`:1522`) no longer corresponds to any occurrence at all (only 2 occurrences exist now, not 3).
  Rather than insert an unverified "+15" claim into a note whose whole purpose is to warn against
  trusting stale numbers, I substituted the actual measured drift (+32, both anchors named) so
  the note is self-consistent and defensible.
- **Item 16 (C2 test count):** grepped `aggregate_corpus_v3` in `tests/test_wiki_metrics_v3.py`
  and got exactly 13 hits, decomposing as 1 import + 10 call sites + 2 docstring/comment mentions
  — matches the orchestrator's given breakdown exactly; used it as given.
- **Item 16 (stray comment line number):** the orchestrator said "~2194"; the actual line is
  2246 (`grep -n "test_wiki_metrics_v3.py" tests/test_wiki_eval_runner.py`). Used the verified
  value with a `~` prefix (consistent with the doc's own line-anchor-drift convention from item 7)
  rather than the stale estimate.
- **Item 13 (C5 titles_ablation20.txt):** confirmed `data/eval/wiki/gt_v2_sub20.jsonl` records
  carry both `"title"` and `"stratum"` fields, so the `title<TAB>stratum` format is directly
  usable (not falling back to the title-only variant).
- **Item 14 (C8 items 22–25):** spot-checked `src/palimpsest/webapp/seed.py:27` and
  `src/palimpsest/webapp/judge.py:17` — both carry the cited "v2 prompt"/"v2 judge prompts" prose
  exactly as the orchestrator described.
- **Coherence pass (end-of-task requirement):** updated C8's own sweep-exclusion clause to
  reference "§ Immutability rule" instead of restating a (now stale, missing `docs/handoff-*.md`)
  subset, resolving the one place where a second, drifting copy of the exclusion list could have
  contradicted the new canonical one (item 3's explicit ask was C2/C4/C5/C6/C7 only; C8's sweep
  clause was a closely related but unlisted 6th grep needing the same treatment to pass the
  end-of-task "no contradictions" check).
- Left the Judgment-items table's per-row `OWNER-GATE` labels and the risk register's R2 row
  ("evaluate smoke" wording) untouched — outside the 16 listed items, and not literal
  contradictions (the Autonomy-resolution section at the top of the doc already establishes that
  OWNER-GATE rows are resolved-as-argued; R2 is a loose paraphrase, not a normative statement).

## Open questions

None blocking. Two minor items worth the orchestrator's awareness (not corrections requested,
just surfaced per the honesty principle):

- The "+15" and "~2194" figures supplied in the dispatch didn't match the live file at the time
  of editing; both were replaced with verified figures (see Decisions above). If those figures
  originated from a different HEAD snapshot than the one checked out for this task, that's
  expected drift, not an error in the dispatch — flagging in case it indicates a stale review
  artifact upstream.
- The risk register's R2 row still describes the C7 check informally as "evaluate smoke," while
  C7's own Verify bullet (item 6) now spells out the concrete `uv run pytest tests/ -k "webapp"`
  command. Not a contradiction, but a follow-up edit could tighten R2's wording to match if the
  orchestrator wants full literal consistency between the two mentions.

## NOT done

- Did not execute any part of the spec's plan (C1–C9) — this task was strictly a spec-document
  amendment, no code/data changes were in scope or made.
- Did not touch any file other than the target spec.
- Did not verify the C8 allowlist items 1–21 (pre-existing, unmodified) against the live tree —
  only the newly-added items 5 (partial edit)/9/22–25 were spot-checked, per the task's explicit
  edit list.
- Did not run `pytest` or any test suite — not applicable to a documentation-only change.
- No HTML/Russian owner-facing report was produced — this task's deliverable was the amended spec
  file itself plus a plain per-item chat confirmation, as explicitly instructed by the dispatch
  ("No extra report file — final chat message: per-item confirmation").
