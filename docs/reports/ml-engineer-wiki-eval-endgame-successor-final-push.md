# ml-engineer: wiki-eval endgame — successor session, closing the last 3 rows

Branch: `claude/ner-translation-config-b0ozsc`. Successor to the prior session's
handover (`docs/reports/ml-engineer-wiki-eval-endgame-3hour-push.md`, commit
`5442905`). Picked up 3 unfinished rows (qwen, deepseek extraction+judge; gemini judge
extension) and drove all of them to complete, judge-backed 100/100 rows.

## Scope

Continue the wiki-eval 4-model NER-translation-config table (gemma-3-27b-it,
qwen3.6-27b, deepseek-v4-flash, gemini-3.1-flash-lite) x 5 metrics (R_NER, R_search,
A_disamb, R, P), G_6 baseline search strategy. At session start: gemma-3 was the only
fully complete row (prior session); gemini's extraction had just finished 100/100 but
its judge was stuck at a 59-article prefix; qwen's extraction was at 81/100 with a
62-article prefix judge; deepseek's extraction was at 69/100 with no judge run started
yet at handover time (a 35/54-article prefix judge was live). Task: verify/resurrect
what was alive, launch the gemini judge extension immediately (highest-value, lowest
remaining work), then chain qwen and deepseek through the same extraction-complete ->
judge-extend pipeline, committing each milestone, ending in an `ALL_DONE` marker once
all 3 rows independently reached judge 100/100.

## Files changed

**No source code changed** — pure operational/orchestration task against the existing
`scripts/wiki_eval.py` CLI, same as the prior session. All repository changes are
under `reports/terminology/wiki-eval/` (run-directory checkpoints), 6 commits this
shift, all pushed to `claude/ner-translation-config-b0ozsc`:

1. `8240c4c` — gemini-3.1-flash-lite judge, G_6 baseline, **100/100 complete** (extended
   from the prior session's 59-article prefix).
2. `47b06eb` — deepseek-v4-flash judge, G_6 baseline, 54/100 (its own prefix, real
   judge-backed checkpoint, mirrors the qwen/gemini prefix-commit precedent).
3. `330c384` — qwen3.6-27b NER extraction, **100/100 complete**.
4. `49524ab` — qwen3.6-27b judge, G_6 baseline, **100/100 complete** (extended from
   the 62-article prefix).
5. `18f56ff` — deepseek-v4-flash NER extraction, **100/100 complete**.
6. `a59ed95` — deepseek-v4-flash judge, G_6 baseline, **100/100 complete** (extended
   from its own 54-article prefix).

Scratchpad artifacts (not in repo, per convention): `scratchpad/endgame/status.md`
(continuously updated running ledger, extended ~230 lines this shift),
`scratchpad/endgame/ALL_DONE` (final completion marker), `scratchpad/endgame/prefix-
judge/*_extend100.sh` + `*_judge_extend100*.log` (the 3 extension launch scripts/logs),
`scratchpad/endgame/prefix-judge/wikidata_cache_{gemini,qwen,deepseek}_judge_merged.jsonl`
(3 warm-cache merges, ~370-760MB each).

## Decisions & rationale

1. **Verified aliveness before acting (work-queue step 1).** All 3 handed-off
   processes (qwen extraction, deepseek extraction, deepseek judge) were alive and
   progressing at session start; no resurrection needed. Confirmed no stray gemma-4/
   alt-names/label-guess processes and no crontab — the out-of-band actor the prior
   session flagged was not active at any point this shift (checked repeatedly).

2. **Solved the "documented but untested" judge-extension mechanism (prior session's
   #1 NOT-done item), then reused it 3x.** The prior handover correctly predicted the
   approach (`--resume` the prefix judge dir with the full `--gt` once the source
   extraction hits 100/100) but had never run it. Key finding made and verified here:
   `--resume` only reads `pred.partial.jsonl` to compute `skip_titles`
   (`scripts/wiki_eval.py:1719-1726`) — **not** `pred.jsonl`. A completed run has its
   partial file deleted on exit (line 1799-1801), so a naive `--resume` on a completed
   prefix-judge dir would see `old_pred_records=[]` and silently re-pay for every
   already-judged article. Fix (the same 3-step recipe applied identically to gemini,
   qwen, then deepseek):
   - Merge the model's own extraction run's default wikidata cache (paid for during
     `--no-judge` extraction, which still runs Wikidata search) with the judge's own
     prefix cache into a scratch dedup-by-key merge — same warm-cache technique as the
     prior session's Phase 1 gemma-3 acceleration.
   - Copy the judge dir's own `pred.jsonl` (N records) -> `pred.partial.jsonl` in
     place, self-seeding the checkpoint format from the run's own already-good output.
     `_assert_pred_gt_coverage` only checks pred-titles-subset-of-gt (never the
     reverse), so an N-of-100 subset is accepted with no error.
   - Launch `--gt <full 100-gt>`, `--reuse-extraction <the model's 100/100 extraction
     dir>`, `--resume <the same judge dir>` — in place, no new run-dir/history
     fragmentation.
   Verified end-to-end on gemini first (progress.jsonl's `"of"` field correctly
   flipped from 59 to 100 on the very next article, spend increased by exactly the new
   article's cost, no re-billing of the prefix), then reused unmodified for qwen
   (62->100) and deepseek (54->100).

3. **Committed deepseek's 54-article prefix judge as an intermediate checkpoint**
   (`47b06eb`) even though the task's explicit commit instruction only named the
   100/100 target. Rationale: mirrors the established precedent from the prior
   session's `ba2d09b` (qwen 62/100) and `3cee906` (gemini 59/100) — a real,
   judge-backed prefix is valuable evidence per the "never delete predictions"
   invariant, and the 100/100 extension a few minutes later builds directly on top of
   it via `--resume`, so committing it first cost nothing and added a checkpoint.

4. **Two crash-resumes this shift, both `LengthOverflowError` (not the
   `client.py:153` `TypeError` the prior session hit), neither a code fix (out of
   scope, no source changes made).**
   - qwen extraction (08:12 UTC): `finish_reason='length'`, a genuinely oversized
     paragraph (`article='Фокидский союз' paragraph=43`) hit the 20000-token
     completion cap. Checkpoint intact at 90/100, resumed cleanly.
   - deepseek judge extension (10:03 UTC): `finish_reason='stop'` yet
     `completion_tokens == reasoning_tokens == 175` — the reasoning phase consumed
     the entire completion budget, leaving 0 tokens for the actual judge verdict,
     which `_gate_reply` correctly treats as a length-overflow failure rather than
     silently accepting an empty answer. Checkpoint intact at 81/100, resumed cleanly.
   Both are the same underlying class (a "gate" correctly refusing a malformed/
   truncated LLM reply and killing the whole process via thread-pool exception
   propagation) as the prior session's documented `client.py:153` and
   `CallGateError` incidents — a real, recurring reliability gap in
   `scripts/wiki_eval.py`'s per-article fault isolation (one bad paragraph/mention
   kills the entire in-flight run, not just that one item), flagged again here as
   out-of-scope for this operational task.

5. **One clean (non-crash) budget-cap stop.** qwen extraction hit its own
   `--max-usd 3.0` ceiling at 82/100 (`BudgetExhaustedError`, not an error condition —
   working exactly as designed). Relaunched with `--max-usd 8.0`; the key's real
   balance ($7.95-$11.72 range observed this shift) comfortably covered the raise.

6. **No memory-pressure episodes this shift** (unlike the prior session's 3). At most
   4 concurrent `wiki_eval.py` processes were live at once (vs. the prior session's
   peak of 7), and this container's earlier documented unbounded-`WikidataClient`-
   cache RSS growth never became acute — `free -h` was not polled defensively because
   no process showed the stall signature (frozen `calls.jsonl` for minutes) that
   would indicate it.

## Run artifacts (evidence)

Final table (all 4 rows independently verified `n_articles: 100, stopped_reason: null`
in each dir's `meta.json`, each with a clean `git status --porcelain` against its own
commit):

| Model | Extraction | Judge (G_6 baseline) | R_NER | R_search | A_disamb | R | P |
|---|---|---|---|---|---|---|---|
| gemma-3-27b-it | 100/100 (prior session) | **100/100**, `fcda89c` (prior) | 0.896 | 0.822 | 0.944 | 0.695 | 0.497 |
| gemini-3.1-flash-lite | 100/100, `c8f7938` (prior) | **100/100**, `8240c4c` | 0.944 | 0.841 | 0.953 | 0.758 | 0.558 |
| qwen3.6-27b | **100/100**, `330c384` | **100/100**, `49524ab` | 0.919 | 0.813 | 0.942 | 0.704 | 0.566 |
| deepseek-v4-flash | **100/100**, `18f56ff` | **100/100**, `a59ed95` | 0.926 | 0.844 | 0.950 | 0.743 | 0.603 |

All 4 rows: complete extraction + complete G_6-baseline judge, real numbers from
`wiki_eval.py report` (no proxy/fallback metrics anywhere in the final table).

Spend: OpenRouter key usage $18.04 -> $22.05 over this shift (**≈$4.01 new spend**),
against the same $30 key limit the prior session left it at (no top-up needed this
shift — balance stayed comfortably above $7 throughout).

Start (successor session): `date -u` 2026-07-11 07:39. `ALL_DONE` written: 10:31 UTC.
This report written: ~10:35 UTC.

## Open questions

- Whether the two `LengthOverflowError` crash sites found this shift (Decision #4)
  warrant a follow-up fix in `scripts/wiki_eval.py` (e.g. per-article/per-mention
  fault isolation instead of killing the whole process on one bad LLM reply) — flagged
  but not actioned, per the "never modify code" boundary on this task.
- The prior session's out-of-band-actor concern (Decision #8 in the prior report) did
  not recur this shift — no evidence either way on whether that actor is still active
  elsewhere in the container; only confirmed it did not touch this task's 3 run dirs.
- The deepseek judge's 54-article prefix commit (`47b06eb`) is now superseded by the
  100/100 commit (`a59ed95`) but was not squashed/removed — consistent with the
  "never delete predictions" invariant, but means the repo history carries both the
  prefix and the final state as separate commits (same pattern as qwen's `ba2d09b` and
  gemini's `3cee906` from the prior session).

## NOT done (explicit)

- **No source code was touched or fixed** — the two `LengthOverflowError` crash sites
  (Decision #4) remain unfixed; they are a real, recurring reliability gap
  (fault isolation) in `scripts/wiki_eval.py`, explicitly out of this operational
  task's scope.
- **Did not investigate or confirm** whether the prior session's flagged out-of-band
  actor is a real concurrent agent session vs. some other artifact — only reconfirmed
  it was inactive against this task's specific run dirs throughout this shift.
- **Did not touch the parked runs** (gemma-4 extraction, alt-names/label-guess judge
  variants) beyond the initial `ps` scan confirming they were not running — their
  working-tree diffs (visible in `git status` at session end) were left exactly as
  found, per the task's explicit "never touch parked run dirs" boundary.
- **Did not investigate or commit** the other untracked/modified files visible in
  `git status` at session end (`docs/reports/docs-keeper-sweep-*`,
  `docs/reports/ml-engineer-quick-rescore-*`, `docs/reports/python-pro-extract-pdf.md`,
  a handful of new/modified gemma-3 test run dirs, 4 untracked `wikidata_cache_*.jsonl`
  scratch files under `reports/terminology/`) — none of these were produced by this
  task; they appear to be artifacts of other concurrent or prior sessions and were
  left untouched rather than guessed at.
