# docs-keeper Report — Final Tree Cleanup (`claude/ner-translation-config-b0ozsc`)

## Scope

Final tree-cleanup on branch `claude/ner-translation-config-b0ozsc`: commit
orphaned overnight-session evidence left uncommitted by agents whose sessions
ended without a final commit. Task instructions enumerated four expected
items and asked for verification, not blind commit, of item 4
(`reports/bouquet/judges/summary.md`).

## Files changed

- **Committed as-is (untracked, session evidence):**
  - `docs/reports/debugger-poller-silence-diagnosis.md` — read-only debugger
    report on the dual-poller simultaneous-silence incident, referenced by
    `known_issues` commit `e61692d`.
  - `docs/reports/docs-keeper-ner-translation-config.md` — a prior mechanical
    docs-keeper's own report (staged/committed/pushed the overnight-mission
    HTML report, commit `e6deb9b`).
  - `reports/bouquet/judges/gemini-3.1-pro/` (`scores.jsonl`, 12 rows) — the
    aborted gemini-3.1-pro judge attempt, stopped when the owner swapped
    `pro` for `flash-lite-think` mid-mission. Append-only judge-prediction
    data per `.claude/rules/invariants.md` ("never delete LLM predictions") —
    committed unmodified as archived evidence. No `stats.json` exists for
    this judge (only 12/2376 scored) and it is correctly absent from
    `summary.md`.

- **Corrected, then committed:**
  - `reports/bouquet/judges/summary.md` — see Decisions below; the
    pre-existing working-tree diff was not a valid "status-table update", it
    was a **regression** that had to be fixed before committing.
  - `reports/bouquet/judges/deepseek-v4-flash/stats.json` — recomputed (see
    below); not in the original expected list, but needed to make the
    deepseek row in `summary.md` correct.

## Decisions & rationale

**1. Diagnosed why `summary.md`'s working-tree diff was wrong, not just stale.**

The diff replaced ALL rows for `gpt-5.5`, `claude-opus-4.8`,
`gemini-3.1-flash-lite` and `deepseek-v4-flash` with ONLY the
`gemini-3.1-flash-lite-think` rows (12 rows, 198 paragraphs each). Root
cause, found in [scripts/bouquet_judge_rerun.py:885-888](../../scripts/bouquet_judge_rerun.py#L885):
`cmd_stats` builds `summary_slugs` from `args.judge` when `--judge` is
passed explicitly — so whoever ran
`bouquet_judge_rerun.py stats --judge gemini-3.1-flash-lite-think` after
commit `f901210` (flash-lite-think done, 2376 calls) correctly refreshed
that judge's own `stats.json`, but as a side effect **overwrote
`summary.md` with only that one judge's rows**, silently dropping four
other judges' already-committed results out of the aggregate. This is not
"stale numbers" (which the task anticipated and pre-authorized fixing
inline) — it's data loss in a derived artifact. Per task instruction 4
("if the diff is something else entirely, report it instead of committing
blindly"), I did not commit the diff verbatim; I regenerated it correctly
instead of reverting, since reverting would have thrown away the legitimate
`f901210` flash-lite-think numbers.

**2. Regenerated `summary.md` from all committed `stats.json` files, without re-running scoring.**

Confirmed via directory listing that exactly 5 judges have `stats.json`:
`claude-opus-4.8`, `deepseek-v4-flash`, `gemini-3.1-flash-lite`,
`gemini-3.1-flash-lite-think`, `gpt-5.5` (matches "gemini/opus/gpt-5.5/
flash-lite-think done" from the task brief). `gemini-3.1-pro` correctly has
no `stats.json` (aborted at 12 rows). I called
`build_summary_md(out_dir, slugs)` directly (the pure local aggregation
function — reads existing `stats.json` files, no network, no rescoring) via
the project's `.venv`, covering all 5 slugs, so no judge's already-computed
result was discarded and none of the four untouched `stats.json` files were
modified.

**3. Found and fixed a second staleness bug in `deepseek-v4-flash/stats.json` itself.**

Before touching `summary.md`, the committed `deepseek-v4-flash/stats.json`
was itself stale: generated `2026-07-08T22:03:43Z`, reflecting only a
5-row early snapshot (all under one system/`Translate Gemma`), while
`deepseek-v4-flash/scores.jsonl` on disk already has **290** rows across
all 4 systems (87 + 71 + 66 + 66 = 290), matching the task's cited
"290/2376 parked, `fa46091`". Left as-is, the corrected `summary.md` would
still have shown the deepseek judge frozen at its old 5-row state instead
of the real 290-row parked state. I ran
`scripts/bouquet_judge_rerun.py stats --judge deepseek-v4-flash` (local
recompute only — `compute_stats_for_judge` reads `scores.jsonl` +
vendored metric files under `eval_root`, no API calls, no network) to
refresh `deepseek-v4-flash/stats.json`, then re-ran the full
`build_summary_md` step over all 5 slugs again (to undo the same
single-judge-summary side effect this command has, per point 1). Verified
the new deepseek rows in `summary.md` sum to `30+29+28+24+24+23+23+23+20+
21+23+22 = 290`, matching the parked count exactly.

No other `stats.json` file was touched or regenerated — `gpt-5.5`,
`claude-opus-4.8` and `gemini-3.1-flash-lite` diffs are empty; only
`deepseek-v4-flash/stats.json` and `summary.md` show as modified.

**4. Everything else committed as delivered, no content edits.**

The two `docs/reports/*.md` files and the `gemini-3.1-pro/` directory
needed no correction — read and sanity-checked only, committed verbatim.

## Open questions

- `scripts/bouquet_judge_rerun.py`'s `cmd_stats` still has the
  single-judge-collapses-summary bug described above (§ Decisions point 1)
  for any future single-`--judge` stats run. Flagging for the owner —
  fixing the script itself (making `summary_slugs` always union with
  existing `stats.json` dirs regardless of `--judge`) is a code change
  outside this cleanup task's scope (docs/evidence commit only, not a
  scripts change) and I did not make it. Left `docs/known_issues.md`
  untouched since amending it is also outside the explicit scope of this
  commit-orphans task — recommend a follow-up ticket.
- Whether `gemini-3.1-pro`'s 12 partial rows should eventually be merged
  into a resumed run or stay permanently archived at 12/2376 is an owner
  call (the task brief already frames it as "aborted... owner replaced pro
  with flash-lite-think mid-mission", i.e. terminal, not resumable) — no
  action taken beyond archiving.

## NOT done (explicit)

- Did NOT fix the `cmd_stats` single-judge/summary-collapse bug in
  `scripts/bouquet_judge_rerun.py` — flagged above as a follow-up, out of
  this cleanup commit's scope.
- Did NOT touch `gpt-5.5/stats.json`, `claude-opus-4.8/stats.json`, or
  `gemini-3.1-flash-lite/stats.json` — verified their diffs are empty and
  left them alone.
- Did NOT amend `docs/known_issues.md` for the `cmd_stats` bug finding —
  out of scope for an orphan-commit cleanup task; a note above documents it
  for the owner instead.
- Did NOT resume or retry the `gemini-3.1-pro` judge run — archived as-is
  per instructions (append-only, never delete).
