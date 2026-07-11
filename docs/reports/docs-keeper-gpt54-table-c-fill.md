# docs-keeper — GPT-5.4 Table C row fill (R_doc), 2026-07-09

## Scope

Three-file, selective docs-parity update following the finalized
`ml-engineer` grounding run (`docs/reports/ml-engineer-grounding-run-gpt54.md`,
commit `5546459`). Source-of-truth numbers used verbatim, no recomputation:

- R_doc on the R_term (T2) tier: **0.583** (4183/7174), 95% CI [0.572, 0.594].
- Unfiltered T0 R_doc: **0.536** (4264/7959), 95% CI [0.525, 0.547].
- Coverage: 99/100 articles (missing "Яффа", 347 GT mentions, Wikidata
  `maxlag`) — every recall figure is a strict lower bound.
- P_label: **not computed** — P3 pass aborted due to sustained Wikidata
  `maxlag`; retry pending.
- Cost: ≈$6.1–6.3.
- Sitelink-clean by construction (`--no-sitelink`), `reasoning_effort`
  pinned "medium".

Diff zone: 3 files named by the dispatcher, plus the docs-keeper report
itself. No other paths touched (`reports/**`, `src/**`, `scripts/**` left
alone as instructed).

## Files changed

1. **`docs/paper/sections/table-c-grounding.tex`**
   - Main table: relabeled the GPT row from "GPT-5.5" to
     `GPT-5.4$^{\ddagger}$`, filled $R_{\mathrm{doc}}$ = 0.583
     [.572–.594], left $P_{\mathrm{label}}$ as `---` (comment above the row
     now reads "pending Wikidata maxlag replay" instead of the stale
     provider-smoke TODO).
   - Added a table-footnote-style `$^{\ddagger}$` note in the `\caption`,
     consistent with the file's existing footnote convention (cf. the
     appendix's `$^{\dagger}$4.1\%...` note): GPT-5.4 substitutes GPT-5.5 due
     to sustained provider rate limits; the run covers 99 of 100 articles, so
     recall is a strict lower bound.
   - Appendix full-grid table: verified the appendix carries the
     $R_{\mathrm{all}}$/T0 tier (caption says so explicitly) — filled T0
     $R_{\mathrm{doc}}$ = 0.536 [.525–.547] into the appendix GPT row
     (renamed to GPT-5.4 with the same `$^{\ddagger}$` marker), left the
     other 4 appendix metric cells (`R_span`, `R_strict`, `P_mention`,
     `P_type`) as `XX` — those were not part of the source report's
     explicitly-requested fill and I did not want to silently promote
     unrequested numbers into the paper without an explicit go-ahead, even
     though the source report does contain T0 values for them
     (R_strict 0.4624, R_span 0.4746, P1 0.3031, P2 0.4708) — flagged below
     as an open question rather than filled unilaterally.
   - $P_{\mathrm{label}}$ in the appendix GPT row set to `---` (not `XX`),
     matching the main table's "not computed, not merely unfilled" semantics.

2. **`docs/paper/paper-state.md`**
   - Table C fill-status line updated: 3/6 rows now have some $R_{\mathrm{doc}}$
     figure (Gemini, DeepSeek fully filled with $R_{\mathrm{doc}}$+$P_{\mathrm{label}}$;
     GPT-5.4 has $R_{\mathrm{doc}}$ only, $P_{\mathrm{label}}$ pending the
     maxlag retry), 3 local rows still pending sr004. Both the "In flight"
     Table C paragraph and the "Done" Table C paragraph updated to say the
     same thing (avoiding the two places silently drifting from each other,
     since paper-state.md itself is L1-adjacent for this doc).

3. **`docs/reports/html/overnight-mission-2026-07-09.html`** and
   **`/tmp/.../scratchpad/overnight-report-artifact.html`** (outside the
   repo, edited but not staged/committed, per instruction)
   - Updated 5 spots in each file identically: the lead summary, the 360
     radar-legend table row (badge yellow→green for the run itself, since
     the run/commit is now done — R_doc is filled; P_label is called out
     separately as pending), the Table C results table row + a new
     honest-caveats paragraph (coverage 99/100, "Яффа"/maxlag, P_label
     pending, cost $5.95–6.3), the evidence-item for the gpt-5.4 run (now
     citing commit `5546459` and the final numbers instead of the stale
     "78/100, $4.74" mid-run snapshot), and the next-steps bullet (replaced
     "wait for finalization" with "retry P_label once maxlag clears + resume
     Jaffa for true 100/100").
   - Verified byte-for-byte content match between the two files after edits
     (compared the `<h1>...</h1>` through `</footer>`-adjacent span; 22094
     chars each, identical) — confirmed programmatically, not just by eye.
   - Did not touch the SVG radar polygon coordinates/shape or axis labels —
     those encode the 8-thread visual, and the dispatcher's instruction was
     "keep them content-identical" for the specific card/row, not to
     recompute the whole radar; flagged as a minor residual inconsistency
     below (the radar table-legend badge went green but the polygon point
     for that axis was not geometrically adjusted).

## Decisions & rationale

- **Left $P_{\mathrm{label}}$ as `---`** everywhere rather than `XX` or a
  placeholder score, per Hard Invariant: never present target/not-yet-computed
  data as existing. `---` mirrors the existing convention used for the three
  still-pending local (sr004) rows in the same table.
- **Did not fill the appendix's other 4 metric columns** for GPT-5.4 even
  though the source report has T0 values for R_strict/R_span/P_mention/P_type,
  because the dispatcher's instruction was scoped to "R_doc cell" for the
  main table and "T0 value... if the appendix carries T0-tier recall" — singular,
  recall only. Filling the rest would be scope creep on a paper table under
  review; flagged in "Open questions" for an explicit follow-up decision.
- **Kept the `$^{\ddagger}$` footnote text word-for-word close to the
  dispatcher's instruction** (no em-dashes, no semicolons, academic English)
  and reused it identically in both the main table and the appendix caption,
  to keep the single fact ("GPT-5.4 substitutes GPT-5.5...") in one wording
  even though it physically appears in two `\caption`s (LaTeX has no
  cross-table $\ref$ for caption prose, so exact-text duplication was the
  only option within one file without introducing a `\newcommand`, which
  would be a speculative abstraction for a single reuse).
- **HTML: recolored the radar-legend Table C · gpt-5.4 badge from yellow
  (IN PROGRESS) to green (DONE — R_doc; P_label pending)** rather than
  inventing a third badge color — reflects that the run itself is finished
  and committed, while still visually flagging the P_label gap in the badge
  text itself rather than hiding it.

## Open questions

- Should the appendix full-grid GPT-5.4 row's remaining 4 cells
  (R_strict/R_span/P_mention/P_type) be filled now from the same source
  report (values are available: R_strict 0.4624, R_span 0.4746, P1 0.3031,
  P2 0.4708, all T0-tier, all with CIs in the source), or left `XX` until an
  owner explicitly extends the fill scope? Left `XX` this pass — narrower
  interpretation of the dispatch instruction.
- The radar SVG's 8th-axis polygon vertex (`142.93,142.93`, the "C: GPT-5.4"
  axis) was not recomputed to reflect the status change from "in progress"
  to "R_doc done, P_label pending" — the instruction only asked for the
  card/row and didn't mention the polygon geometry; flagged, not touched.

## NOT done (explicit)

- Did not touch `reports/**`, `src/**`, `scripts/**`, or any file outside
  the three named paths (plus this report) — confirmed via `git status`
  before staging.
- Did not fill the appendix's 4 remaining T0 metric cells for GPT-5.4 (see
  Open questions).
- Did not run a P_label/P3 replay myself — that is explicitly the
  `ml-engineer` agent's follow-up, out of scope for a docs-parity pass.
- Did not stage the scratchpad artifact HTML (it lives outside the repo, at
  `/tmp/claude-0/.../scratchpad/overnight-report-artifact.html`) — edited in
  place per instruction, not part of the git commit.
