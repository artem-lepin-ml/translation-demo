# docs-keeper — doc-parity pass: wiki-eval experiment v2 (protocol v3)

Branch: `claude/ner-translation-config-b0ozsc`. Commit: `330ccd4`
("docs(wiki-eval): rewrite stage doc for protocol v3 runner, runbook R12
revision, known-issues resolutions"), pushed to origin.

## Scope

Doc-parity for the wiki-eval experiment-v2 rework (spec
[2026-07-10-wiki-eval-experiment-v2.md](../superpowers/specs/2026-07-10-wiki-eval-experiment-v2.md)
§7 UPDATE items), landed in code commits `421c99d` (prompts/schema/
sentence-context), `0d89242` (protocol-v3 aggregator), `275f8c7` (gpt-5.4
leftover-resume archive), `7e7ddfd` (transport rework, gates,
observability, `cmd_report` v3). Ground truth was read directly from the
current code (`extract.py`, `grounding/label_first.py`, `scripts/wiki_eval.py`,
`evaluation/metrics.py`, `evaluation/report.py`) — not reconstructed from the
spec or from memory. Living docs only; `docs/experiments/**` prose drafts
got archive banners (frozen data files untouched); `docs/paper/sections/*.tex`,
`CLAUDE.md`, `README.md` were explicitly out of bounds and not touched.

## Files changed

- `docs/stages/wiki-eval.md` — full rewrite: prompts section (links to
  `extract.py`/`label_first.py`, no copied prompt text), transport/sampling
  table (`MODEL_PARAMS`), per-call gates (Р13/Р14/Р15:
  `LengthOverflowError`/`CallGateError`/`BudgetExhaustedError`),
  `calls.jsonl`/`generation_params` observability, protocol-v3 section
  (`aggregate_corpus_v3`, tier filter, named/term split, tier file
  location), rewritten Interface/Subtleties/Status. Removed: mention-level
  M1/M2/M3, P1/P2/P3/`--p3`, `CONTEXT_PAD`, `sitelink_contamination.py`
  references, CloseRouter env-var routing. Methodology section now links
  only to `eval-metrics-terminology.tex` (SSOT), plus a flagged code-drift
  note (see Decisions).
- `docs/stages/terminology.md` — `DEFAULT_NER_PROMPT` → `NER_SYSTEM_PROMPT`/
  `ner_user`; `{surface, lemma, category}` → `{surface, lemma}` with a note
  that `TermMention.category` stays on the dataclass for legacy demo-seed
  rows only (`category=None` for fresh extractions, per spec Р6); Interface
  block's function list updated (`sentence_context` added,
  `DEFAULT_NER_PROMPT`/`CATEGORIES` removed).
- `docs/known_issues.md` — new RESOLVED entry (silent 4k/512-token
  truncation + `parse_surfaces` silently returning `[]` + ±40-char judge
  context, with commit refs `421c99d`/`7e7ddfd`); new entry documenting
  `finish_reason=length` as a hard, non-tolerated error (Р15); new entry
  for the gpt-5.4 leftover-resume incident (commit `275f8c7`); one stale
  `DEFAULT_NER_PROMPT` reference in an existing entry corrected to
  `NER_SYSTEM_PROMPT`.
- `docs/runbooks/sr004-local-eval-runbook.md` — env-var section flagged
  superseded for Table C (`--base-url` CLI flag replaces
  `OPENROUTER_BASE_URL`/`WIKI_EVAL_PROVIDER` reading, Table A unaffected);
  "Why no patch was needed" routing bullet corrected for `wiki_eval.py`;
  `--extra-body` semantics correction (merge-per-key, not replace, per
  spec §4.1 finding 4); `--max-model-len` bring-up note flagged OPEN
  (16384 no longer fits a 20000-token completion cap); full Table C
  section rewritten: new prompt/schema/context (automatic, no runbook
  action), `--base-url http://127.0.0.1:8000/v1`, per-model
  vendor-sampling table left OPEN ("per HF card — confirm before the
  run"), `--max-tokens 20000`, 10-article pilot gate (no committed
  10-article `gt.jsonl` exists — a `build-gt` command to derive one is
  given instead of inventing a file), `report` command without `--p3`;
  deliverables checklist updated (`calls.jsonl` added, `--p3` removed).
- `docs/superpowers/specs/2026-07-10-wiki-eval-experiment-v2.md` — one
  bracketed correction note appended to the Р12 row only, per instruction
  (owner-reviewed doc, not rewritten).
- `docs/paper/paper-state.md` — Table C narrative resynced to protocol v3:
  6-row lineup (gemma-4-31b-it added, gpt-5.4 excluded and archived), fill
  status reset to 0/6 under v3 (old $R_{doc}$/$P_{label}$ numbers folded
  into a collapsed `<details>` "protocol-v2 history, superseded" block for
  reference, not deleted outright since they're real historical results);
  "Done" bullet for the old grounding run shortened to point at the
  collapsed history; "Queued" section updated with the pending pilot/full
  runs and a note that `table-c-grounding.tex` itself still needs a v3
  rewrite (out of scope here).
- `docs/experiments/2026-07-05-model-comparison/drafts/{paper-section-en-final.md,
  paper-section-en.tex, recall-tiers-analysis.md, report-ru-v3.md,
  sitelink-contamination.md, terminology-spec.md}` — `⚠️ SUPERSEDED`
  banner added at the top of each prose file, pointing at
  `docs/paper/sections/` and `eval-metrics-terminology.tex`. Data files
  (`.png`/`.svg`/`.json`) in the same directory were left untouched per
  instruction.

## Decisions & rationale

- **`report.py::methodology_draft()` left in code, flagged in docs instead
  of silently described as gone.** Spec §4.5 item 12 says this function and
  its doc mirror should collapse into the tex SSOT. Reading the current
  code, the function is still present and still returns the old
  protocol-v1/v2 paragraph verbatim (three matching modes, P3/label-justified
  precision) — the landed commits did the aggregator/report-HTML rework
  (`render_html_v3`) but did not touch `methodology_draft()`. Since
  docs-keeper edits docs, not code, I did not delete it; instead
  `docs/stages/wiki-eval.md` now carries an explicit ⚠️ drift note
  identifying it as dead code (never called by `cmd_report`) so it doesn't
  get mistaken for a live SSOT.
- **Old protocol-v2 Table C numbers kept, not deleted, in `paper-state.md`.**
  These are real historical results (real runs, real commits). Deleting
  them would lose provenance the paper-writing process may still want to
  reference ("what did the v2 numbers look like"). Folded into a collapsed
  `<details>` block explicitly marked superseded instead — single source
  of truth for *current* Table C state is now the top-level text, not the
  collapsed history.
- **10-article pilot gt file**: rather than inventing a path/subset that
  doesn't exist on disk, the runbook now gives the exact `build-gt`
  invocation to derive one from the first 10 titles of the canonical
  corpus (reuses the cached HTML, no network cost).
- **Local vendor-sampling values left blank (OPEN), not guessed.** Per
  explicit instruction and per working-style.md's spirit (don't fabricate
  numbers) — Qwen3-4B-Instruct-2507/Gemma-3-27B-it/Qwen3.6-27B's HF-card
  sampling recommendations were not looked up in this pass (no web access
  budget spent on it here); the runbook states the principle and CLI flags
  and marks the table cells explicitly OPEN.
- **Archive banners on `.md`/`.tex` prose only, not on `.png`/`.svg`/`.json`
  data files in the same `drafts/` directory** — per task instruction 6
  ("NOT json data files"), extended consistently to images since they
  carry no protocol-version claims to supersede.

## Open questions (flagged to the owner, not resolved here)

1. Exact `temperature`/`top_p`/`top_k` for the three local models — needs
   each model's own HF card read before the sr004 session.
2. `--max-model-len` for the local vLLM bring-up under Table C's new
   20000-token cap — a concrete replacement number (e.g. 24576/32768) was
   suggested but not verified against real VRAM/`--help` output.
3. `report.py::methodology_draft()` dead-code removal (or repointing at
   the tex SSOT) — a code change, not something this docs pass could or
   should make.
4. `docs/paper/sections/table-c-grounding.tex` still needs its own v3
   rewrite once real pilot/full-run numbers exist — explicitly out of
   bounds for this task (`.tex` under `docs/paper/sections/` is excluded).

## NOT done (explicit)

- No code was touched — this was a docs-only pass, per the docs-keeper
  role.
- No new `gt_pilot10.jsonl` file was created — only the command to create
  it was documented in the runbook.
- No pilot/full runs were executed — the task was doc-parity for already-landed
  code, not running the experiment.
- `docs/paper/sections/*.tex` was not touched (explicit exclusion), so
  `table-c-grounding.tex` still describes protocol v2 despite
  `paper-state.md` now flagging it as stale.
- Mass drift cleanup outside the named files (e.g. the many historical
  reports under `docs/reports/`, `docs/superpowers/specs/`,
  `docs/superpowers/plans/` that still mention `DEFAULT_NER_PROMPT`,
  `CONTEXT_PAD`, `--p3`, etc.) was intentionally left alone — those are
  frozen historical documents, not living docs, and touching them would be
  the "mass doc cleanup" this role's boundaries reserve for explicit owner
  consent.
