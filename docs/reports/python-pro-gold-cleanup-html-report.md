# python-pro: final gold-cleanup campaign HTML report (render only)

## Scope

Task: programmatically render the final gold-cleanup HTML report (owner-facing,
Russian, dark Tokyo Night) from already-committed findings, in two variants
(standalone page + Claude-Artifact-ready fragment), then commit and push. This
was a pure presentation/assembly task — no new analysis, no re-derivation of
any number. `data/eval/wiki/gt.jsonl` and `reports/` were explicitly
out-of-scope and confirmed untouched throughout. Branch
`claude/ner-translation-config-b0ozsc`, never switched.

## Files changed

- **Created** (scratchpad, not committed) `SCRATCHPAD/gold_cleanup/report/build_report.py`
  — the build script. Loads `data/eval/wiki/anchor_exclusions_draft.json` and
  `data/eval/wiki/cleanup/replacements_2026-07-10.json`, generates every table
  row and stat card from that data (`html.escape`d), assembles both HTML
  variants from one shared body/CSS, and runs sanity assertions (750/130/56/3
  row-count checks, balanced `<details>`/`<table>` tags, no stray
  `{template}` placeholders) before writing files.
- **Created** `docs/reports/html/gold-cleanup-2026-07-10.html` (251 495 bytes)
  — the standalone report: `<!doctype html>`, full `<head>`, inline
  `<style>` using the `.claude/rules/tokyo-night.css` token set.
- **Created** (scratchpad, not committed)
  `SCRATCHPAD/gold_cleanup/report/artifact.html` (251 332 bytes) — identical
  content, starting directly at `<title>…</title><style>…</style>` with no
  `<!doctype>/<html>/<head>/<body>` wrapper, for the Claude Artifact
  publishing path.
- **Committed as-is** `docs/reports/python-pro-span-ner-before-after-cleanup.md`
  — a prior agent's leftover, untracked task report; staged and committed per
  the task's explicit instruction, not authored by this task.

Commit `bef70d8c7c9503f7f8b54bbeddef77a8d73a7d85`
(`docs(reports): final gold-cleanup campaign HTML report`), pushed to
`origin/claude/ner-translation-config-b0ozsc` (succeeded on the first push
attempt, no retries needed).

## Decisions & rationale

- **Report structure follows CLAUDE.md's mandatory HTML template block
  order** («Главное» → сводная панель/360-style summary → what-was-done →
  critical findings → evidence → next steps), adapted per the task's own
  explicit brief for a data-campaign report (stat cards + horizontal bar
  chart instead of a radar, since this isn't an aspect review).
- **a–e category classifier for the 750 live exclusions is a
  presentation-layer construction, not a re-derived fact.** The source JSON
  (`anchor_exclusions_draft.json`) carries a `reason` string per exclusion but
  no category field. The task gave five verified aggregate counts
  (a=272, b=258, c=14, d=37, e=169) and required a full itemized `<details>`
  table per category. I built a deterministic keyword classifier
  (`classify()` in `build_report.py`, ordered a→d→c→e→b) and iteratively
  tuned its keyword/exact-string sets against the real `reason` value
  distribution (`collections.Counter` inspection) until all five bucket
  totals matched the given counts exactly and summed to 750. Every field
  shown in each row (article_no, title, anchor_text, qid, reason,
  provenance) is copied verbatim from the source JSON — only which
  `<details>` block a row lands in was computed. This is flagged as an
  anomaly in the final JSON return, not hidden.
- **"Why flagged" labels for the 5 replaced articles were sourced from
  `docs/known_issues.md`**, not inferred: its "WikiHist corpus selection P31
  gate does not exclude fictional-universe entities" entry gives the
  authoritative per-title mapping (Гелиополиты→Marvel, Стигия→Conan,
  Керченский пролив→modern-geography, Кесарево безумие→historiographic
  concept, Яффа→~72% post-cutoff). An initial draft guess had Керченский
  пролив and Яффа's labels reversed; caught and corrected before writing the
  table by reading `known_issues.md` directly instead of trusting the
  inference from `wiki_original.json` text alone.
- **Top-10 anchor / top-5 article counts in the summary panel use the task's
  given campaign-totals numbers verbatim**, even though a spot-check against
  the raw JSON (`collections.Counter` over `anchor_text`) showed small
  discrepancies for a few forms (e.g. `лат.` actual 23 vs given 17) —
  per the task's explicit "use as given, verified by orchestrator"
  instruction, these were not recomputed or overridden.
- **CSS table-wrap bug found and fixed during QA, before commit.** The first
  build used a positional `nth-child(2)/(5)` rule to decide which table
  columns wrap, tuned for the 6-column exclusion-row table. The
  replacements/precedents/commits tables have different column layouts, so
  the same positional rule wrapped the wrong columns and caused real
  horizontal overflow (verified via a Playwright screenshot, not assumed).
  Fixed by switching to an explicit `.wrap` class applied per-cell in each
  table builder, then re-verified visually.
- **Visual QA via headless Chromium (Playwright, `NODE_PATH` pointed at the
  system-installed `/opt/node22/lib/node_modules/playwright`)** rather than
  the `playwright-cli` skill, since this was a one-shot static-file
  screenshot check with no interactive session needed. Screenshots covered:
  top/summary panel, one opened `<details>` table, the 5-replacement table,
  critical findings, evidence/commits table, and the closing next-steps
  list.
- **`html.escape` applied to every data-derived string** (titles, anchors,
  QIDs, reasons, provenance, replacement rationale) — no raw f-string
  interpolation of source data into markup.

## Open questions

None generated by this task itself — the 3 open questions embedded in the
report (ancient-language tags in article 010; Орбан/ЕС KEEP-bias in 072/073;
generic-vs-specialized material line in 089) are the campaign's own open
questions, carried verbatim from `anchor_exclusions_draft.json`'s
`open_questions` array into the report's "Критические находки" section for
the owner to resolve — not raised or answered by this rendering task.

## NOT done

- **No new analysis or number was computed.** This task only assembled
  presentation from already-committed sources; all metrics (recall/precision
  before/after, commit hashes/subjects, counts) are copied from the cited
  docs/JSON, not recalculated.
- **`data/eval/wiki/gt.jsonl` and `reports/` were not touched** — verified
  via `git status --porcelain` / `git diff --stat` before and after, per the
  task's explicit constraint.
- **No PR opened** — task said "No PR," push only.
- **The report was not delivered as a served-HTML link or Claude Artifact in
  this turn** — CLAUDE.md's delivery rule (serve via `python3 -m http.server`
  locally, or publish as a Claude Artifact in cloud sessions) was not
  executed as part of this specific render-and-push task; the task's own
  "Commit & push" instructions specified git delivery only (commit + push,
  no PR), which is what was done. If the owner needs the rendered report
  served/artifact-published for direct viewing, that is a follow-up action,
  not covered by this task's explicit scope.
- **The scratchpad `artifact.html` fragment was not committed to the repo**
  (by design — task said it goes to `SCRATCHPAD/gold_cleanup/report/`, for
  the publishing pipeline to consume, not to `docs/reports/`).
