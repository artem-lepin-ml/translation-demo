# Paper state — EMNLP 2026 System Demonstration (Historical MT tool)

> Living document: current structure + fill-state of the paper draft, and the mapping
> experiments → tables. Update on every experiment/writing change.
> Draft source: ACL-template PDF (`2026_EMNLP_History_Demo.pdf`, uploaded 2026-07-08).
> Companion RU outline lives in the chat; spec for the current eval:
> [2026-07-07-wiki-llm-judge-eval.md](../superpowers/specs/2026-07-07-wiki-llm-judge-eval.md).

## Skeleton (mirrors the abstract)

**2026-07-10: integrated into a single Overleaf tex.** Title: "Beyond Literal
Equivalence: An Interpretable System for Terminology-Aware Machine Translation
in Historical Texts". New macros: `\datasetWikipediaName` = WikiHist,
`\datasetEncyclopediaName` = RuWH, `\systemname` (placeholder, not yet filled).

| # | Section | State |
|---|---------|-------|
| — | **Title** | Set: "Beyond Literal Equivalence: An Interpretable System for Terminology-Aware Machine Translation in Historical Texts" |
| — | **Abstract** | **TODO (Andrey)** |
| 1 | **Introduction** — tool + contributions | Drafted in the tex by the team |
| 2 | **Related work** | Populated with WMT24/25, SemEval-2025 Task 2 (EA-MT), TEaR, DelTA, Tan et al. 2026 (LLM refinement in literary MT), etc. |
| 2.2 | Terminology module — **Artem** | Recognition/Normalization, Disambiguation, and Ambiguity Categories paragraphs drafted in the tex by the team |
| 3 | **System** (tech report, 3 submodules) | In progress |
| 3.1 | Initial translation | In/out + formalization — partial |
| 3.3 | LLM-as-a-judge Evaluation + Refinement — **Danil** | Drafted (judge 1–10, Accuracy/Fluency/Style; issues → editor) |
| 3.1 | WikiHist dataset paragraph | Co-authors rewrote it as `\subsubsection{WikiHist Dataset}` with Data Source + Terminology Annotation paragraphs (docs/paper/sections/3-1-wikipedia-dataset.tex); our Variant 1 kept in the tex as a commented alternative |
| 3.x | Datasets paragraphs (remaining) | history volume (томик), BOUQUET — other datasets **to fill** |
| 3.x | Demo ↔ methodology figure | **TODO** (figure linking demo interfaces to methodology) |
| 3.x | Demo interfaces | TipTap (cite GitHub), LLMs via OpenRouter, HuggingFace record — **to write** |
| 4 | **Evaluation setup** | 4.1 Evaluation Data — partial; 4.2 Evaluation metrics — `\paragraph{Terminology Recognition}` drafted 2026-07-10, see writing-pass subsection below. Maximize model overlap across tables for consistency |
| 5 | **Results** (bold-takeaway paragraph names) | 5.1 Terminology Recognition — 2 findings drafted 2026-07-10, see writing-pass subsection below. Two quantitative tables (one per section). Case study / error analysis on the history book (same in demo) — **TODO**. Qualitative table comparing predictions vs Wikipedia annotation — **TODO** |
| 6 | **Conclusion** | TODO |
| — | Tables | T1 data statistics; **Table A** LLM-as-a-judge (BOUQUET only, 4 fixed systems, 7-judge comparison); **Table B** Refinement usefulness (cross base×refiner matrix, wiki-100 + QE metrics); **Table C** NER + Wikidata grounding (model-comparison v4) |
| — | Appendix | Prompts (per spec §8, `v1_core3` variant for Table A); full judge disclosure (model/config/date) per Table A protocol; per-judge full tables (Table A compact in main paper); limitations sentence re: old BOUQUET numbers from stochastic self-judge (spec §8); `app:wiki-corpus` corpus-construction section drafted 2026-07-10, see writing-pass subsection below |

## Experiments → paper mapping

### Evaluation restructuring (owner, 2026-07-08)

Evaluation section is now **three tables, one per contribution** — replaces the earlier
flat T2/T3 numbering:

- **Table A — LLM-as-a-judge** (contribution: judge/refinement module). **BOUQUET only** —
  the one dataset with human references, so reference-based metrics and ranking are
  meaningful. Judged systems are **fixed at the 4 already-vendored ones** (TranslateGemma,
  TG-Refined, Qwen3.6-27B, Qwen3.6-27B-Refined) — translations are **not** regenerated,
  judges only re-score the existing outputs.
- **Table B — Refinement usefulness** (contribution: refinement module). Cross
  base×refiner matrix — the 7-row proposal below, still pending owner confirmation —
  on wiki-100, reported with QE metrics.
- **Table C — NER + Wikidata grounding** (contribution: terminology extraction). **⚠️ 2026-07-10: protocol
  v3 rework supersedes the $P_{\mathrm{label}}$/mention-level narrative below.** Metrics are now set-based
  document-level $R_{\mathrm{doc}}$/$P_{\mathrm{doc}}$, split named/term (`metrics.aggregate_corpus_v3`,
  spec [2026-07-10-wiki-eval-experiment-v2.md](../superpowers/specs/2026-07-10-wiki-eval-experiment-v2.md)
  Р9) — mention-level M1/M2/M3 matching and $P_{\mathrm{label}}$/P1/P2/P3 precision are **deleted**, not
  just superseded (`matching.py` and the offline sitelink-replay script are gone). Methodology SSOT:
  [eval-metrics-terminology.tex](sections/eval-metrics-terminology.tex).
  **6-model lineup, updated row set**: Qwen3-4B-Instruct, Gemma-3-27B-it, Qwen3.6-27B (local, pending
  sr004), Gemini-3.1-Flash-Lite, DeepSeek-V4-Flash, **Gemma-4-31B-it** (added 2026-07-10, spec Р1 — replaces
  the GPT-5.5/GPT-5.4 cloud row). **`GPT-5.4` is excluded from the experiment entirely** (spec Р1: no run, no
  table row — its earlier run artifacts are archived, commit `275f8c7`, after a leftover `--resume` process
  completed it post-exclusion; see [known_issues.md](../known_issues.md)). Claude Opus 4.8 stays dropped from
  Table C (kept in Table A). qwen3.7-plus stays dropped.
  **Fill status: 0/6 rows filled under protocol v3.** Runner code for the rework landed 2026-07-10 (4
  commits: `421c99d`/`0d89242`/`275f8c7`/`7e7ddfd`); the pilot (10 articles) and the three full cloud runs
  are **pending**, as are the three local sr004 rows (runbook:
  [sr004-local-eval-runbook.md](../runbooks/sr004-local-eval-runbook.md)). Every $R_{\mathrm{doc}}$/
  $P_{\mathrm{label}}$ number quoted below this point (Gemini 0.735/0.530, DeepSeek 0.657/0.535, GPT-5.4
  0.583/0.536) is **protocol-v2 history, not comparable to a v3 run** — kept only as a paper-writing
  reference for what the old numbers looked like, not as current Table C fill state. Historical detail
  (superseded) retained below for that reference purpose; `docs/paper/sections/table-c-grounding.tex` (the
  paste-ready v2 table) also needs a v3 rewrite once the pilot lands — not done in this doc pass.

  <details><summary>Protocol-v2 history (superseded 2026-07-10, kept for reference)</summary>

  Owner-locked main-table format (2026-07-09): only $R_{\mathrm{doc}}$ and $P_{\mathrm{label}}$, sitelink-clean,
  $R_{\mathrm{term}}$ tier (n=7174 terminology-relevant gold mentions); the full 6-metric grid
  (sitelink-clean, $R_{\mathrm{all}}$/T0 tier) moved to an appendix table
  (`\label{app:grounding-full}`). Fill status under v2: 3/6 rows FULLY filled with both $R_{\mathrm{doc}}$ and
  $P_{\mathrm{label}}$ (Gemini, DeepSeek, GPT-5.4); remaining 3 rows pending local sr004 runs.
  (Gemini-3.1-Flash-Lite: $R_{\mathrm{doc}}$ 0.735 $R_{\mathrm{term}}$-tier sitelink-clean,
  $P_{\mathrm{label}}$ 0.530 [.521--.540]; DeepSeek-V4-Flash: $R_{\mathrm{doc}}$ 0.657
  $R_{\mathrm{term}}$-tier sitelink-clean, $P_{\mathrm{label}}$ 0.535 [.524--.545] — clean values
  from `docs/experiments/2026-07-05-model-comparison/sitelink-clean-full-metrics.json`, also
  applied to the appendix full-grid table since $P_{\mathrm{label}}$ has no gold-tier dependence);
  GPT-5.4 (fallback for `gpt-5.5`, sustained provider rate limits): $R_{\mathrm{doc}}$
  0.583 [.572--.594] $R_{\mathrm{term}}$-tier, sitelink-clean by construction (`--no-sitelink`),
  `reasoning_effort` pinned "medium"; coverage 99/100 articles (missing "Яффа", Wikidata `maxlag`),
  so the figure is a strict lower bound; $P_{\mathrm{label}}$ 0.536 [.525--.548] (3773/7037, Wilson
  95% CI), computed once Wikidata `maxlag` cleared (see
  `docs/reports/ml-engineer-grounding-run-gpt54.md` commit `5546459` and
  `docs/reports/python-pro-p-label-gpt54-grounding-run.md` commit `19c7389`).

  **2026-07-10 (pre-rework):** the in-paper Table C the owner had transferred into Overleaf earlier was
  stale ($P_{\mathrm{label}}$ pending, GPT-5.5 row `XX`). The paste-ready replacement (caption
  slimmed with definitions moved to `sec:eval-metrics`, $P_{\mathrm{label}}$ filled for all 3
  cloud rows, GPT-5.5 row swapped for GPT-5.4 with a `\ddagger` footnote, appendix grid caption
  aligned) landed in `docs/paper/sections/table-c-grounding.tex` — this itself is now superseded by the
  protocol-v3 rework the same day; the .tex file still needs its own v3 update (not done here, docs-keeper
  does not edit `docs/paper/sections/*.tex`).

  </details>

### Done
- **BOUQUET ru2en (by paragraphs)** → feeds **Table A**. Systems: TranslateGemma / TG-Refined /
  Qwen3.6-27B / Qwen-Refined; judge Acc/Flu/Sty ≈ 9.5–9.9; MetricX w/ и w/o ref; COMET.
  Spearman judge↔metrics weak (−0.13…+0.37) — discussion point. Old numbers were
  Danil-verbatim (qwen3_6-27b, T=0.7, thinking on) — kept as a **sensitivity footnote**,
  not recomputed; Table A itself uses the new 7-judge protocol below.
- **NER+Wikidata grounding, wiki corpus v2 (model-comparison v4) — protocol-v2 numbers, SUPERSEDED
  2026-07-10** → historical **Table C** / §5.1 reference only, see the collapsed section above for the
  full v2 narrative and the current (v3, all-pending) fill state. Artifacts:
  `reports/terminology/wiki-eval/`, paper section draft `docs/paper/sections/table-c-grounding.tex` (itself
  pending a v3 rewrite).
- **Wiki-100 corpus** built & handed to Danil: 2 553 paragraphs / 100 articles
  (`data/eval/wiki/`, README + sha256), pilot = 10 articles / 274 par.
- **deepseek CloseRouter smoke** ($0.0052): reasoning-off flag mandatory; provider-9 pin
  incompatible with json_object (judge role → route auto). **Superseded 2026-07-08**:
  locked protocol is reasoning **ON** for the judge role (see Table A protocol below).

### In flight (current task)

**Table A fill status (2026-07-09): 4/8 rows DONE, 1 terminally PARKED (`deepseek-v4-flash`
at 290/2376, commit `fa46091`, resumable), 3 local rows pending sr004.**
- DONE: `gemini-3.1-flash-lite` (reasoning off, data commit `ced45c3`), `claude-opus-4.8`
  (no thinking available via gateway, commit `6a90dec`), `gpt-5.5` (default effort, auto
  route, 2375/2376 calls, commit `336f272` — 1 cell short due to a disclosed
  deterministic model-output JSON bug), `gemini-3.1-flash-lite-think` (Gemini-3.1-Flash-Lite
  + reasoning ON, 2376/2376 calls, $0.47, data commit `f901210`; survived a ~11h outage —
  Google-family gateway 503s, two detached-process deaths (session teardown, container
  recycle) — see `docs/reports/python-pro-judge-run-gemini-flash-lite.md` Part 2 for the
  outage timeline).
  - **Reasoning-sensitivity finding** (the `gemini-3.1-flash-lite` /
    `gemini-3.1-flash-lite-think` pair is now complete on both sides): enabling reasoning
    shifts the judge uniformly more generous (mean Acc +0.20, Flu +0.35, Sty +0.35; style
    tie-rate {9,10} 71.1% -> 85.4%) without improving agreement with COMET/MetricX, except
    style rho vs.\ CometKiwi (0.149 -> 0.198). Worth a line in the paper's judge-protocol
    discussion, not just an operational footnote.
- TERMINALLY PARKED, marked `---` with TODO in the table: `deepseek-v4-flash` (reasoning
  on, 290/2376 = 12.2%) — after four earlier parked resumes (commits `501c394`,
  `85e5435`, `02e4f25`, `70e9ba5`), a resident 2h45m poll (11:20Z-14:05Z, 60+ gate
  cycles, 180+ realistic-payload probes) recorded 0 successes with zero flicker; the
  coordinator called a terminal stand-down at ~14:05Z rather than continue an
  open-ended loop against a route showing no recovery signal. `stats.json`
  deliberately NOT computed (290/2376 too partial/uneven a sample — disclosed, not
  silent). Cost ≈$0.128. Resume state (append-only) committed at `fa46091`, exact
  resume commands in
  [python-pro-judge-run-deepseek.md](../reports/python-pro-judge-run-deepseek.md).
- Pending, marked `---` with TODO: the 3 local judges (`qwen3.6-27b`, `qwen3-4b-instruct`,
  `gemma-3-27b-it`, all $T{=}0$, thinking off) await owner-side sr004 vLLM runs per the
  runbook [sr004-local-eval-runbook.md](../runbooks/sr004-local-eval-runbook.md)
  (commit `0c48124`).
- Table skeleton + fills: `docs/paper/table-a-judges.tex`.

**Table A — LLM-as-a-judge, 7-judge lineup (owner-locked, 2026-07-08; updated 2026-07-08 —
Gemini judge swapped to flash-lite):**
- Local vLLM: `qwen3.6-27b` (prod anchor), `qwen3-4b-instruct`, `gemma-3-27b-it`
  (same family/scale as TranslateGemma → family-bias check; also a Gemma-vs-Gemini
  open-vs-cloud same-vendor angle).
- Cloud via CloseRouter: `deepseek-v4-flash`, `claude-opus-4.8`, `gpt-5.5`,
  **`gemini-3.1-flash-lite`** (replaces `gemini-3.1-pro`; exact router ID still being
  confirmed by a smoke test — `google/gemini-3.1-flash-lite` or `-preview`, mirroring
  the `-preview` suffix pattern found for pro in the probe). Side benefit: flash-lite
  already appears in the Table B translator matrix and the Table C grounding eval, so
  the swap increases model overlap across tables, per the §4 "maximize model overlap
  across tables" note.

**Table A protocol (owner-locked, 2026-07-08; updated 2026-07-08):**
- Local/open judges → `temperature=0`, thinking OFF.
- `deepseek-v4-flash` → `T=0`, **reasoning ON** (locked protocol as of 2026-07-08 —
  supersedes the earlier "reasoning OFF mandatory" note from the smoke test; per the
  probe, `reasoning.enabled:false` didn't actually suppress thinking anyway, so ON is
  now the honest, locked setting).
- GPT-5.5 / Opus 4.8 / Gemini-3.1-Flash-Lite → no temperature param, **default effort**,
  thinking on where the gateway honors it. Disclosed quirk (probe, 2026-07-08): the
  OpenAI-compat bridge on CloseRouter silently drops reasoning params for Opus
  (0 reasoning tokens across all 3 parameter forms tried) — Opus judges without
  thinking in practice; GPT-5.5 reasons normally at default effort (110–292 reasoning
  tokens/call). Full per-judge config disclosure goes to the paper appendix
  (`app:judge-configs`), not the compact main-paper table.
- Prompts = **`v1_core3`** (filtered variant of `v1`, 3 criteria only: accuracy/fluency/style;
  `cultural.md` / `terminology.md` dropped — `load_prompts` globs `*.md` in the variant dir,
  no code change needed). The old Danil-verbatim `qwen3.6-27b` run (T=0.7, thinking on —
  the screenshot numbers) is kept as a **sensitivity footnote**, not recomputed.
- Stats to report: per-system mean Accuracy/Fluency/Style per judge; Spearman
  judge↔MetricX-ref / MetricX-QE / COMET; tie-rate (share of {9,10} scores). Full
  per-judge tables → appendix; compact table in the main paper.
- Execution split: the 4 cloud judges run from the cloud session via CloseRouter; the
  3 local judges run via [docs/runbooks/sr004-local-eval-runbook.md](../runbooks/sr004-local-eval-runbook.md)
  — `scripts/bouquet_judge_rerun.py` against a local vLLM server per model, no Danil-pipeline clone needed
  (that clone + `patches/gse-translation-sr004/` is Table B's runbook, [translation-eval.md](../stages/translation-eval.md),
  not Table A's).
- Cost estimates (from the judge probe,
  [docs/experiments/2026-07-08-judge-probe/probe-results.md](../experiments/2026-07-08-judge-probe/probe-results.md),
  per full 2 376-call BOUQUET run): Opus 4.8 ≈ $2.3, GPT-5.5 ≈ $1.3, DeepSeek-V4-Flash
  ≈ $1.5. `gemini-3.1-pro` (≈ $9–14) was dropped in favor of flash-lite, partly on cost —
  flash-lite pricing/cost still TBD, to be confirmed by the pending smoke test.

**Table B — Wiki-100 LLM-judge + refinement eval**, extended matrix: 5 systems
  (TranslateGemma-27B, Qwen3-4B-Instruct-2507, Qwen3.6-27B — local vLLM on 4×A100;
  deepseek-v4-flash, gemini-3.1-flash-lite — CloseRouter), translate + refine stages.
  - Judge prompts = **v1_core3** (see Table A above; same filtered variant, no separate copy).
  - Judge config = **Danil-verbatim** (qwen3_6-27b, T=0.7, thinking on) for this table
    specifically — Table B is about refinement usefulness, not judge comparison, so the
    judge stays fixed.
  - **Invariant: the refiner is strictly stronger than the base translator.**
    No self-refinement anywhere. Assumed strength order:
    Qwen3-4B < TranslateGemma-27B ≤ Qwen3.6-27B < gemini-3.1-flash-lite < deepseek-v4-flash.
  - Runner = **Path A**: Danil's pipeline + `patches/gse-translation-sr004/`.
  - Proposed matrix (7 rows, before→after columns): 2×2 sub-matrix
    {Qwen3-4B, TranslateGemma-27B} × {Qwen3.6-27B, deepseek-v4-flash refiners},
    Qwen3.6-27B→deepseek, gemini-lite→deepseek, deepseek base-only (ceiling).
    Awaiting owner confirmation.
  Runbook (4-system version): [translation-eval.md](../stages/translation-eval.md);
  patches: `patches/gse-translation-sr004/`.
- Judge probes: test-retest (verbatim config), J′ = deepseek inter-judge agreement.

### Queued
- **Table C protocol-v3 pilot + full runs** (2026-07-10, spec 2026-07-10-wiki-eval-experiment-v2.md §5):
  10-article gemini pilot, then 3 full cloud runs (Gemini-3.1-Flash-Lite, DeepSeek-V4-Flash,
  Gemma-4-31B-it) + 3 local sr004 runs. Code landed, no runs executed yet.
- `docs/paper/sections/table-c-grounding.tex` needs a v3 rewrite once real numbers land (out of scope for
  this doc pass — docs-keeper does not edit `docs/paper/sections/*.tex`).
- qwen3.7-plus clean re-run (grounding eval, Table C) — moot under v3 (qwen3.7-plus already dropped from
  the v2/v3 lineup, spec Р1).
- Case study / error analysis (history volume) + qualitative wiki-annotation table.

### 2026-07-10 writing pass (Artem tasks)

Five fragments produced today. Each is **delivered to chat, awaiting owner pick of
variant** — none yet pasted into the Overleaf tex. Fragment texts are not duplicated
here; see the paths.

- [docs/paper/sections/eval-metrics-terminology.tex](sections/eval-metrics-terminology.tex)
  — §4.2 `\paragraph{Terminology Recognition}`, 2 variants. Requires
  `\label{sec:eval-metrics}` on `\subsection{Evaluation Metrics}`.
- [docs/paper/sections/table-c-grounding.tex](sections/table-c-grounding.tex) — updated
  2026-07-10: caption slimmed (definitions moved to `sec:eval-metrics`), $P_{\mathrm{label}}$
  filled for all 3 cloud rows, GPT-5.5 row replaced by GPT-5.4 with a `\ddagger` footnote,
  appendix grid caption aligned.
- [docs/paper/sections/results-terminology-findings.tex](sections/results-terminology-findings.tex)
  — §5.1, 2 findings, 2 variants (commit `f721594`).
- [docs/paper/sections/live-demo.tex](sections/live-demo.tex) — §2.4 Live Demo
  Functionality + Implementation, 2 variants (commit `f5cd2b5`).
- [docs/paper/sections/appendix-wiki-corpus.tex](sections/appendix-wiki-corpus.tex) —
  appendix `app:wiki-corpus`, corpus-construction section (commit `30499b7`).

Citation proposals for the two remaining `(TODO)` placeholders:
- WikiHist intro: `semenov-etal-2025-findings` + `conia-etal-2025-semeval`.
- RuWH intro: `kocmi-etal-2025-findings` + `conia-etal-2024-towards`.
- Caveat: `conia-etal-2025-semeval` currently appears only in a commented-out `\cite` —
  needs an Overleaf bib check before it can be relied on.
