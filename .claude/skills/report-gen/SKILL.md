---
name: report-gen
description: >-
  Assemble a served, dark Tokyo Night HTML report from docs/reports/ and
  docs/experiments/ source data into docs/reports/html/, filling only the
  canonical template's designated content slots — never its CSS or layout.
  Use at workflow steps 6 (Verify) and 8 (Finish), or for any long piece of
  work that needs the final HTML report per .claude/process.md's "HTML report
  template" section.
---

# report-gen

Turns already-produced findings (spec/aspect reviews, e2e reports, audits,
verify output) into the one canonical dark-HTML report artifact. This skill is
presentation only — it does not generate findings, run tests, or review code.

## Invariants

1. **Do not modify CSS or layout.** The template's `<style>` block, wrapper
   `<div>`/`<section>` structure, and CSS variable declarations are fixed.
   Only replace content inside `<!-- SLOT: ... --> ... <!-- /SLOT -->` regions.
2. **Palette = Tokyo Night tokens**, read from
   [.claude/rules/tokyo-night.css](../../rules/tokyo-night.css) — do not
   hardcode different hex values or invent new tokens:
   - `--bg:#1a1b26` `--bg2:#1f2335` `--panel:#24283b` `--line:#2f334d`
     `--tx:#c0caf5`
   - `--blue:#7aa2f7` (data) `--green:#9ece6a` (pass) `--yel:#e0af68`
     (open/warn) `--red:#f7768e` (fail) `--purple:#bb9af7`
3. **Data source**: `docs/reports/` and `docs/experiments/` — read the actual
   review/audit/test output the caller points at. Never fabricate a score,
   verdict, or evidence link; a claim without a backing artifact does not go
   into the report (mirrors process.md block 5, "Run artifacts").
4. **Output**: write the filled report to `docs/reports/html/<slug>.html`
   (slug = `YYYY-MM-DD-topic`, matching the naming already used under
   `docs/experiments/`).
5. **Serving is out of scope for this skill.** The template embeds no server
   and no external assets (self-contained, single file). Serving is a
   separate, later step: `python3 -m http.server <port> --bind 127.0.0.1` run
   from `docs/reports/html/` (ports 8096+, check availability), giving the
   direct `http://localhost:<port>/<file>.html` link. Do not add a server, a
   build step, or any external CDN/font/script reference to the template.

## Template

[templates/report-template.html](templates/report-template.html) is the
canonical structure — six blocks in the fixed order from
`.claude/process.md`:

1. **Главное** (`main-verdict`, `overall-badge`) — 1-2 sentence outcome +
   verdict.
2. **360&deg; radar** (`radar-svg`, `radar-table-rows`) — per-aspect scores as
   axes on the SVG polygon, mirrored in the legend table. The step-6 aspects
   map to the axes; recompute `<polygon>` points and axis label positions for
   the real aspect count, but keep the `<svg>` wrapper/grid/viewBox as-is.
3. **Что сделано** (`overview`) — goal &rarr; what changed (tables/cards)
   &rarr; key decisions and why.
4. **Критичные находки** (`findings`) — one `.finding` block per issue,
   severity-tagged (`finding--critical` / `finding--high` / `finding--info`),
   nothing hidden.
5. **Артефакты запуска** (`evidence`) — one `.evidence-item` per claim: test
   counts, e2e screenshots (linked/embedded), audit verdicts, commit hashes.
6. **Дальнейшие шаги** (`next-steps`) — open items / owner decisions needed.

Plus a `report-title` / `report-meta` header slot and a `footer-note` slot.

## Workflow

1. Read [.claude/rules/tokyo-night.css](../../rules/tokyo-night.css) to
   confirm the hex tokens (the template already inlines them; re-verify on
   drift).
2. Read `templates/report-template.html`.
3. Read the source material under `docs/reports/` and `docs/experiments/`
   the caller names (a spec's verify-spec aggregate, an e2e-tester report, a
   code-reviewer/docs-keeper output, test run logs).
4. Produce the filled HTML by replacing each `<!-- SLOT: ... -->` region's
   placeholder content with real content grounded in that source material —
   leave a slot explicitly `TBD`/`no data` rather than inventing content.
5. Write the result to `docs/reports/html/<slug>.html`.
6. Hand back the file path and note that serving (`python3 -m http.server`)
   is a separate step for whoever has Bash access.
