# Repo de-versioning cleanup — synthesized spec

**Date:** 2026-07-10
**Provenance:** synthesized from two independent review drafts — `plan_draft_engineering.md`
(safety/execution lens) and `plan_draft_conventions.md` (naming/product-coherence lens) — plus
eight zone inventories, reconciled by a cross-examiner. Spot-verified in the working tree
(branch `claude/ner-translation-config-b0ozsc`); verification notes inline as `[V]`.

> **Header note — out of scope by design:** the exclusions-promotion rename
> `anchor_exclusions_draft.json → anchor_exclusions.json` is a SEPARATE in-flight,
> owner-approved workflow-status change (`_draft` = unapproved→approved lifecycle marker,
> not a version). It is NOT part of this spec and MUST NOT be folded into any commit here.

---

## Autonomy resolution (owner grant, 2026-07-10)

The owner granted full autonomy for this cleanup ("работай автономно", 2026-07-10). The
OWNER-GATE rows below are therefore resolved as argued, effective immediately:

- **J-SUB20** — `gt_v2_sub20.jsonl` DELETED (C5). The `2026-07-10-gt-canonicalization.md`
  "не трогать" was a scope boundary of that task, not a preservation mandate; superseding
  noted in the final owner report.
- **J-SCAF** — scaffold DELETED (C7), including the live `client.py` dead-import strip and
  the `README.md:53` parity edit. The `translation-eval.md` / `configs/models.yaml`
  provenance check (R10) is executed inside C7 by the implementing agent: verify the
  runbook references the sr004 external clone; if they reference the repo file, add the
  runbook parity edit to the same commit.
- **J-GOLD** — target name `terminology_gold_manual.jsonl` (C6), both lenses concurring.
- **J-A11** — `audit_prompt_v11.md` KEPT (provenance artifact).
- **J-PROTO** — `"protocol":"v3"` field, report `<h1>`, and methodology prose KEPT.
- **J-V1C3 / J-DOCX / J-SEED** — remain open items, surfaced in the final owner report;
  no action in this spec.
- **J-GUARD / C9** — ships ADVISORY-ONLY; the flip to blocking stays with the owner.
- **R11** — resolved: NER *extraction* runs (prompt frozen at commit 8bbafcf) may execute
  concurrently with these lanes — extraction touches neither the lane file sets nor the
  scoring code C2 renames; C2 lands before any *scoring* run is invoked.
- **Execution mode amendment:** lanes A and B run SERIALLY on the main working tree
  (A then B) instead of two concurrent worktrees — two agents sharing one working tree
  would contaminate each other's pre-commit pytest runs; serial execution trades ~an hour
  of wall clock for deterministic suite-green verification at every commit.

## Goal

Bring the repo to a **clean fixed state before the next expensive full runs**: version
suffixes survive on our own artifacts (files, identifiers, schema names) **only where 2+
versions genuinely coexist live** in the demo/pipeline; otherwise the current artifact
goes unversioned and the retired predecessor is left to git history. Ship a durable guard
so the recurrence (a fresh `foo_v2.py`) is caught at introduction time — a Claude-Code
PreToolUse hook (§ C9) that covers commits made through Claude-Code sessions only, NOT
owner-shell/CI commits — and remove fully-dead predecessor code discovered by the same audit
(the unlabeled translation/judge scaffold), so the fixed state is clean of both stale names and
dead lanes.

## Naming principles (the vocabulary this spec applies)

- **unversioned-canonical** — exactly one live version, predecessor(s) fully deleted → drop
  the suffix to the bare name.
- **semantic-name-instead-of-version** — a bare de-version would collide or the suffix never
  meant a version → rename by ROLE.
- **schema-version-field-kept** — a tag serialized into live/accumulating data (DB column, GT
  record, run-artifact self-description) as forward-compat/provenance → exempt.
- **provenance-artifact-kept** — the number records a real methodology/campaign iteration, or
  coexisting-live artifacts, or immutable/vendored/dated/dotted-model naming → exempt.

## Scope / non-goals

**In scope:** de-versioning our own code identifiers, live data-file names and their readers,
dead-artifact deletion, one live doc-parity bug fix, and the durable guard.

**Non-goals (explicit):**
- The `anchor_exclusions_draft → anchor_exclusions` rename (separate in-flight change).
- Any edit to immutable trees (see § MUST-NOT-TOUCH).
- Cache hygiene of `data/eval/wiki/pages/` (124 cached HTML vs 100 titles) — same root cause
  as the pilot deletes but not a version-suffix item; owner-optional follow-on, not here.
- Relocating/renaming the vendored `v1_core3` prompt dir (out of our editable surface).
- The `VENDORED.md` "do not edit" boundary breach (commit `74b3ceb` added `v1_core3/` into
  `external/`) — a repo-hygiene question routed to the owner, not a de-versioning item.

## Success criteria

1. Full `pytest` green after **every** commit (each commit is self-contained: code + tests +
   active docs together — Hard Invariant 2).
2. The 3 wiki-eval regression anchors continue to pass unmodified after de-versioning. The
   **authoritative check** is C2's identifier-token-only `git diff -U0` on the test file (shows
   NO numeric-literal churn) plus a green full `pytest` run — de-versioning perturbs no numeric
   literal. The pinned values below are **informational cross-reference only**, verified against
   `tests/test_wiki_metrics_v3.py` at HEAD as of this amendment: `n_ambiguous_gold_units` = 112,
   `n_gold_mentions_dropped_by_tier` = 764, `named` class tp/fn/fp/gold_units = 3078/807/1526/3885,
   total `gold_units` (named+term) = 5351.
   **Warning:** these numbers drift independently of this spec (concurrent gold-corpus commits on
   this branch change them) — an implementing agent must NEVER edit the pinned numbers in the test
   file to match this list, and must NEVER edit this list to "fix" an observed mismatch; the only
   sanctioned pass criterion is the diff-shows-no-numeric-churn + suite-green check above.
3. Live-tree grep for each retired identifier/filename returns 0 outside the allowlist:
   `aggregate_corpus_v3`, `render_html_v3`, `_v3_cell_td`, `_V3_CLASS_LABELS`,
   `test_wiki_metrics_v3`, `methodology_draft`, `selection_v2`, `titles_v2`,
   `gt_v2_sub20`, `titles_pilot20`, `gt_pilot.jsonl`, `terminology_gold_v1`, `_metrics_v1`,
   `palimpsest.pipeline|palimpsest.evaluation|palimpsest.config|from_model_config`.
4. C8 repo-wide `v[0-9]` sweep: every survivor is on the § C8 allowlist; no un-listed residue.
5. The durable guard (C9) is installed and green; never bypassed (`--no-verify` forbidden).
6. `git diff --name-only <pre-C1 base>..HEAD -- reports/ external/ docs/reports/
   docs/experiments/ docs/paper/snapshots/ docs/superpowers/specs/ docs/superpowers/plans/`
   returns ONLY this spec file itself (its own verify-spec amendments are the sanctioned
   exception) — a mechanical immutability gate over the whole branch range.

---

## The plan — atomic commits (each suite-green; code + tests + active docs together)

**Line-anchor drift note (read first):** every `:NNN` line anchor in this document was verified
against HEAD at synthesis time but MAY have drifted since due to concurrent commits on this
branch — e.g. `scripts/wiki_eval.py`'s `aggregate_corpus_v3` call site alone already drifted from
the cited `:1545` to `:1577` (+32) by amendment time, verified against HEAD. Implementing agents
MUST locate each edit by TOKEN MATCH (`rg` on the identifier/string quoted in the bullet), not by
trusting the line number — treat every `:NNN` as a hint, not a coordinate.

**Immutability rule — canonical exclusion set (defined ONCE here; every per-commit Verify grep
below references it as "exclusions per § Immutability rule" instead of restating a subset):**
`reports/`, `external/`, `docs/reports/`, `docs/experiments/`, `docs/paper/snapshots/`, dated
`docs/superpowers/{specs,plans}/`, and `docs/handoff-*.md` session notes. These are append-only /
never edited — a fresh commit supersedes a dated spec's recommendation, it does not rewrite it.

**Branch & worktree:** commits in this plan land on the harness-designated session branch
`claude/ner-translation-config-b0ozsc` (owner-directed session branch; supersedes the
`feat/<topic>` convention for this session's work — deviation from CLAUDE.md § Task isolation
explicitly noted), with serial execution on the main working tree per the Autonomy resolution
above (no worktree fan-out).

**Pytest collection baseline:** record `pytest --collect-only -q | tail -1` once before landing
C1; every commit's Verify step compares the collected-item count against the expected delta for
that commit (0 for pure renames; **−2 files** at C7 for the 2 deleted test files; C9's synthetic
`foo_v2.py` verification file is created and removed within C9's own Verify step and is excluded
from the baseline collection count).

### C1 — `fix(paper): correct wiki-eval protocol label v2→v3` · [S · Lane A, first · within-mandate]
Pure doc-parity bug, independent of every rename.
- `docs/paper/sections/eval-metrics-terminology.tex:15` `% PROTOCOL v2` → `% PROTOCOL v3`.
  `[V]` this file describes the identical set-based document-level formalism that
  `table-c-grounding.tex:2` ("PROTOCOL v3") and every other active doc names v3; and it IS
  the methodology-prose SSOT that `metrics.py`/`report.py` docstrings point at.
- **Verify:** `rg -n "PROTOCOL v2" docs/paper/sections` → 0; `rg -n "PROTOCOL v3"
  docs/paper/sections/eval-metrics-terminology.tex docs/paper/sections/table-c-grounding.tex`
  matches in BOTH files (concrete both-match check, replaces the vaguer "the two active .tex
  agree").
- **Overleaf flag (loud):** co-author text (§3.1); owner's uploaded copy may diverge — list the
  edited line in the report and courtesy-confirm with the paper co-author (non-blocking).

### C2 — `refactor(evaluation): de-version wiki-eval protocol code identifiers` · [L · Lane A, atomic · within-mandate]
Single atomic commit — imports/tests break if split. **KEEP** the "protocol v3" methodology
proper-noun everywhere it is prose/self-description (see § Judgment items J-PROTO, RESOLVED);
de-version ONLY the code-identifier tokens.
- `src/palimpsest/terminology/evaluation/metrics.py`: `aggregate_corpus_v3` → `aggregate_corpus`
  (def `:63`); update the identifier tokens in docstrings; **KEEP** the `"Protocol v3:"`
  methodology naming and **KEEP** `"protocol": "v3"` (`:149`). `[V]`
- `src/palimpsest/terminology/evaluation/report.py`: `render_html_v3` → `render_html` (`:75`),
  `_V3_CLASS_LABELS` → `_CLASS_LABELS` (`:62`), `_v3_cell_td` → `_cell_td` (`:65`); update
  identifier tokens in docstrings; **KEEP** the `<h1>Wiki-eval report (protocol v3)</h1>`
  (`[V]` renders into every report.html; methodology self-label) and **KEEP** "protocol v3"
  prose. `[V]`
- `scripts/wiki_eval.py`: `:1494` comment, `:1522`, `:1545` call sites.
- `data/eval/wiki/cleanup/tools/replay_analysis.py`: `:115` call + `:147/:197/:202` comments;
  `enumerate_misses.py`: `:104` comment (`M.aggregate_corpus_v3` → `M.aggregate_corpus`). `[V]`
- **Tests:** `git mv tests/test_wiki_metrics_v3.py tests/test_wiki_metrics.py`; update
  `aggregate_corpus_v3` → `aggregate_corpus` throughout — **10 call sites + 1 import + 2
  docstring/comment mentions** (verified count `[V]`, not the earlier "(12)" estimate) + the
  module/class docstrings; **KEEP** `test_protocol_key_present` and its
  `result["protocol"] == "v3"` assertion (`:149`) UNCHANGED; keep every pinned regression number
  byte-identical. `[V]`
- `tests/test_wiki_report.py`: `render_html_v3` → `render_html` import + 5 call sites;
  `test_render_html_v3_*` → `test_render_html_*` (5 fns); **KEEP** the protocol fixture assertion
  (`:28`).
- `tests/test_wiki_eval_runner.py`: `test_cmd_report_writes_v3_metrics_*` → drop `_v3` from the
  function NAME; **KEEP** the `metrics["protocol"] == "v3"` assertion (`:2180`). Note: this file
  also carries a stray old-filename comment ("tests in test_wiki_metrics_v3.py", `~:2246`,
  verified `[V]`) — no separate edit needed, it is caught by C2's own `test_wiki_metrics_v3` grep
  gate below.
- **Active docs (same commit):**
  - `docs/stages/wiki-eval.md`: `:35, :37, :66, :73, :93` (identifier tokens); **KEEP** all
    "protocol-v3"/"Protocol v3" methodology prose. (`:125` drift banner handled in C3.) `[V]`
  - `docs/paper/paper-state.md:53` (`metrics.aggregate_corpus_v3` identifier); **KEEP** the
    Protocol-v2 history `<details>` block and all methodology prose. `[V]` **(engineering C2 missed this file.)**
  - `docs/paper/sections/table-c-grounding.tex:18` (cites `tests/test_wiki_metrics_v3.py` →
    `test_wiki_metrics.py`); **KEEP** the `% PROTOCOL v3` header. `[V]`
  - **NOT in C2:** `docs/runbooks/sr004-local-eval-runbook.md` — `[V]` zero code-identifier
    hits; it carries only "protocol v3" prose (keep). (Conventions §6 over-listed it.)
- **Verify:** full `pytest` green; the 3 regression anchors pass with unchanged numbers (see
  Success Criterion 2 — informational cross-reference only, NOT the pass criterion);
  `rg -n "aggregate_corpus_v3|render_html_v3|_v3_cell_td|_V3_CLASS_LABELS|test_wiki_metrics_v3"`
  over live tree = 0 (exclusions per § Immutability rule); **identifier-token-only** `git diff -U0`
  on `test_wiki_metrics.py` shows NO numeric-literal churn (R1 guard) — this diff check, not the
  pinned numbers, is the authoritative regression gate.
- **Overleaf flag:** `table-c-grounding.tex` edited.

### C3 — `refactor(evaluation): delete dead methodology_draft` · [S · Lane A, serial after C2 · within-mandate]
- `report.py`: delete `methodology_draft()` (`:123-172`) + its docstring bullet. `[V]` zero
  production callers; returns stale protocol-v1/v2 prose next to v3 code.
- `tests/test_wiki_report.py`: drop the `methodology_draft` import (`:11`) + `test_methodology_draft_*`.
- `docs/stages/wiki-eval.md:125`: remove the now-obsolete ⚠️ drift-flag banner. `[V]` the
  function's docstring claim of a "byte-identical copy in wiki-eval.md § Methodology" is already
  STALE — that doc says it "no longer carries its own copy of it"; nothing to reconcile, just
  drop the banner.
- **Verify:** `pytest` green; `rg -n methodology_draft` live tree = 0.
- Serial after C2 (shares `report.py`, `test_wiki_report.py`); kept separate for a clean
  delete-vs-rename bisect boundary.

### C4 — `refactor(wiki-corpus): de-version selection/titles corpus files` · [M · Lane A, serial after C3 · within-mandate]
- `git mv data/eval/wiki/selection_v2.json selection.json`; `titles_v2.txt titles.txt`. `[V]`
  both on disk (selection 810 lines, titles 100 lines); v1 fully retired, no sibling.
- `scripts/select_wiki_corpus.py`: `:2` "Selection v2:" label → "Selection:", `:7` docstring
  output paths, `:204` `json.dump` path. `[V]`
- `scripts/export_wiki_corpus.py`: `:6` docstring, `:37` `DEFAULT_TITLES` (LIVE input — must
  move with the file). `[V]`
- `src/palimpsest/terminology/evaluation/wiki_gt.py:4` "(selection v2)" pointer comment →
  "(corpus selection)". `[V]` (prose, but the vestigial "selection v2" shorthand fully
  de-versions — unlike the kept "protocol v3", there is no paper-narrated v1→v2 selection lineage).
- **Active docs (same commit):** `docs/stages/wiki-eval.md` (`:9` "## Corpus (selection v2…)",
  `:17, :21, :23`), `docs/paper/sections/appendix-wiki-corpus.tex` (`:2-3` header comment),
  `docs/runbooks/sr004-local-eval-runbook.md:346` (`head -10 … titles_v2.txt`),
  `data/eval/wiki/README.md` (`:45` `titles_*.txt` → `titles.txt`, `:56`, `:57`). `[V]`
- **Verify:** `titles.txt`=100 lines / `selection.json`=810 lines; `sha256sum` before (on
  `titles_v2.txt`/`selection_v2.json`) and after (on `titles.txt`/`selection.json`) match —
  content byte-identical across the `git mv`; `python scripts/export_wiki_corpus.py --help` path
  resolution OK; `pytest` green; `rg -n "selection_v2|titles_v2"` live tree (exclusions per §
  Immutability rule) = 0.
- **Overleaf flag:** `appendix-wiki-corpus.tex` edited.
- **Atomicity:** `titles.txt` is a live pipeline input → data + code rename MUST be one commit.
- **Do NOT touch** `data/eval/wiki/pilot_articles.json` — `[V]` it is a LIVE OUTPUT of
  `export_wiki_corpus.py:304` (documented `:17`), not a corpus-selection artifact and not dead.

### C5 — `chore(wiki-corpus): delete retired pilot/subset corpus artifacts` · [S · Lane A, serial after C4 · OWNER-GATE(gt_v2_sub20)]
- **BEFORE deleting `gt_v2_sub20.jsonl`:** extract its 20 `"title"` fields into a new committed
  `data/eval/wiki/titles_ablation20.txt` (`title<TAB>stratum` format — the source records carry a
  `stratum` field `[V]`; else one title per line if a future source lacks it). The file's header
  comment notes it was preserved from `gt_v2_sub20.jsonl` for byte-rebuild via
  `wiki_eval.py build-gt --titles`. Same commit as the deletion below.
- `git rm data/eval/wiki/{gt_v2_sub20.jsonl,titles_pilot20.txt,gt_pilot.jsonl}`. `[V]` all three
  on disk; grep of `scripts/`,`src/`,`tests/`,`cleanup/tools/` = 0 code readers.
- `docs/runbooks/sr004-local-eval-runbook.md` `:343, :465`: reword the two lines that treat
  `gt_v2_sub20.jsonl` as a usable shortcut. **Correction:** the runbook's documented `build-gt`
  recipe (no `--titles` flag) derives a DIFFERENT subset than the deleted file — it is NOT a
  faithful substitute. Point these two lines at the new `titles_ablation20.txt` +
  `wiki_eval.py build-gt --titles titles_ablation20.txt` instead — THAT is the faithful
  re-derivation path for the exact deleted 20-title subset. `[V]`
- **Verify:** `pytest` green; `rg -n "gt_v2_sub20|titles_pilot20|gt_pilot\.jsonl"` live tree
  (exclusions per § Immutability rule) = 0.
  Note: the `gt_pilot` LOCAL VAR in `replay_analysis.py`/`enumerate_misses.py` is a different
  token (in-memory slice of `gt_all`) — do NOT flag it.
- **OWNER-GATE:** `gt_v2_sub20.jsonl` deletion contradicts the committed
  `2026-07-10-gt-canonicalization.md` "не трогать" prose (that was a scope boundary, not a
  keep-forever mandate; the file embeds a discredited article "Стигия" → footgun). Within
  mandate, but give the owner a one-line courtesy heads-up before landing.
- Serial after C4 (shares the sr004 runbook).

### C6 — `refactor(gold+eval): de-version terminology_gold source + _metrics helper` · [S · Lane B, first · OWNER-GATE(name, low-stakes)]
- `git mv data/seed/gold_sources/terminology_gold_v1.jsonl terminology_gold_manual.jsonl`. `[V]`
  bare `terminology_gold.jsonl` would collide with the MERGE OUTPUT `data/seed/terminology_gold.jsonl`;
  `_manual` matches the unversioned siblings `grounding_gold`/`pairing_gold` and merge_goldens' own
  "mine" label.
- `scripts/merge_goldens.py`: `:6` comment, `:135` filename (in the `("…","mine")` tuple). `[V]`
- `scripts/eval_grounding.py`: `:108` comment, `:114` filename tuple; `_metrics_v1` → `_metrics`
  (`:327` def, `:448` call); **KEEP** the `"v": 1` output field (`:352`). `[V]`
  - **Do NOT touch** `:355` `"golden": {"version": "terminology_gold.jsonl"}` — `[V]` it names the
    MERGED OUTPUT, not the renamed source; no `v[0-9]` pattern, unaffected by this rename.
- **Verify:** `sha256sum` before (`terminology_gold_v1.jsonl`) and after (`terminology_gold_manual.jsonl`)
  match — content byte-identical across the `git mv`; `python scripts/merge_goldens.py` produces
  byte-identical `data/seed/terminology_gold.jsonl` (99 lines); `eval_grounding.py` import/help OK;
  `pytest` green; `rg -n "terminology_gold_v1|_metrics_v1"` live tree (exclusions per §
  Immutability rule) = 0.
- **OWNER-GATE (low stakes):** confirm the target name `terminology_gold_manual.jsonl` (both draft
  lenses recommend `_manual`).
- Disjoint file set from Lane A → parallel lane.

### C7 — `chore: remove dead translation/judge scaffold` · [M · Lane B, serial after C6 · OWNER-GATE(module-level)]
`[V]` The scaffold's ONLY non-external, non-venv importers are `tests/test_criteria.py`,
`tests/test_offline_callers_content.py`, and `src/palimpsest/llm/client.py` — the reader list is
COMPLETE, so this atomic set is suite-green.
- `git rm -r src/palimpsest/evaluation/` (criteria.py, judge.py, __init__.py).
- `git rm -r src/palimpsest/pipeline/` (base, draft, factcheck, polish, terminology, runner, __init__).
- `git rm src/palimpsest/config.py`.
- `git rm configs/models.yaml configs/pipeline.yaml`. `[V]` read only by the deleted
  `config.py::load_models/load_pipeline`, which have zero callers.
- `git rm tests/test_offline_callers_content.py tests/test_criteria.py`.
- `src/palimpsest/llm/client.py` (LIVE webapp hot path): strip `from ..config import ModelConfig`
  (`:13`) AND the `from_model_config` classmethod (`:60-63`). `[V]` **J3 dead-import detail:**
  `ModelConfig` has no other use in `client.py`; `from_model_config` has zero live repo callers
  (all other hits are inside vendored `external/`, which has its own `palimpsest.config`).
- **`README.md:53`** — update `configs/  YAML: pipeline.yaml, models.yaml` to reflect that
  `configs/` now holds only `bouquet_judges.yaml`. `[V]` **DOC-PARITY EDIT BOTH DRAFTS MISSED.**
- **Verify:** full `pytest` green **minus** the 2 deleted test files (expect a collected-count DROP,
  not failures); `python -c "import palimpsest.webapp.app"` smoke; `uv run pytest tests/ -k
  "webapp" -q` (implementing agent confirms the actual test-selection expression collects >0 items
  and reports the count — no live-server curl required for this repo-only commit); `rg -n
  "palimpsest\.pipeline|palimpsest\.evaluation|palimpsest\.config|from_model_config"` live tree
  (exclusions per § Immutability rule) = 0.
- **OWNER-GATE:** (1) module-level deletion that *looks* load-bearing — confirm "reference scaffold
  to keep, or dead?" (argued: dead). (2) `[V]` `docs/stages/translation-eval.md`'s
  `configs/models.yaml` references are for **Danil's sr004 clone** of `external/gse-translation`
  (its own config loader — the doc links `from_model_config` to
  `external/gse-translation/src/palimpsest/llm/client.py`), NOT the repo file the dead scaffold
  reads (two independent reviewers already re-verified this sr004-clone reading as correct).
  Implementing agent verifies during C7 (per Autonomy resolution): if translation-eval.md's
  models.yaml references turn out to be the repo file rather than the sr004 external clone, add
  the runbook parity edit to this same commit — no owner step.
- Serial after C6; the ONE commit that edits the live LLM client — flag loudly.

### C8 — `chore: v[0-9] residue sweep + allowlist` · (HUMAN-TRIAGED gate, not pure pass/fail; not a code commit) · [S · after both lanes merge]
`rg -n "v[0-9]"` over the live tree, exclusions per § Immutability rule. Every remaining hit must
be on the allowlist below, else it is residue flagged for HUMAN TRIAGE before declaring clean —
this gate is judgment-based, not automated pass/fail: a hit that is neither an obvious allowlist
match nor obvious residue is surfaced to the owner rather than silently resolved either way.

**Unified allowlist of legitimate survivors (must NOT be flagged) — merge of both drafts:**
1. `CHRONO_P31_VERSION = "chrono_p31_v1"` (wiki_gt.py) + the surviving `gt.jsonl` records (100
   after C5) + `test_wiki_gt.py:190` — schema-provenance tag (J8).
2. `GroundingTrace "v": 1` (label_first.py:287, eval_grounding.py:352) + the demo-contracts DDL
   comment — schema tag on the live `term.trace_json` column (J8).
3. `"protocol": "v3"` (metrics.py:149) + `<h1>Wiki-eval report (protocol v3)</h1>` (report.py) +
   the "Protocol v3" docstring naming — methodology self-description (J-PROTO, RESOLVED KEEP).
4. "protocol v3"/"PROTOCOL v3" methodology PROSE: wiki-eval.md, paper-state.md,
   table-c-grounding.tex, eval-metrics-terminology.tex (post-C1), sr004 runbook.
5. External API strings: `openrouter.ai/api/v1`, `sk-or-v1-…`, the
   `${OPENROUTER_BASE_URL}`/`base_url: …/api/v1` literal — third-party contract (the
   `localhost:8001/v1` literal moved to the pattern-based item 24 below).
6. `USER_AGENT="palimpsest-llm/1.0"`, `__version__="0.1.0"`, frontend `package.json "0.0.0"`,
   `.mcp.json @latest` — packaging/UA slots.
7. `rev-4`/`rev-5` contract revisions (webapp.md, README, known_issues.md, demo-contracts) — coexist live in prod DB.
8. `v1_core3` vendored prompt dir + `external/…/prompts/03_scoring/{v1,v2,universal,_legacy}` +
   `external/…/configs/scoring/*-v1-*.yaml`/`*-v2-*.yaml` — 5 coexisting variants; `external/` read-only.
9. Dotted/hyphenated third-party model names anywhere in the live tree (`gpt-5.5`,
   `claude-opus-4.8`, `gemini-3.1-*`, `qwen3.6-27b`, `deepseek-v4-flash`, …) — multiple judges run
   simultaneously (Table A).
10. `wiki_eval.py --config` ids (`111`/`001`/`000`) — 3-bit ablation flags.
11. Tier keys `R-T0/R-T1/R-T2`; cleanup `wave1`/`wave2-4`/`wave5-7`/`wave8-10`/`replacements` +
    `overrides_wave{1,2}.json`/`overrides_replacements.json` — disjoint batches read together.
12. `document.version` / `docVersion` — optimistic-concurrency counter (wire contract).
13. `audit_prompt_v11.md` — provenance/methodology artifact (J5, RESOLVED KEEP).
14. `seed_prompt_variant="v2"` — write-only seed-row provenance DB value.
15. `report-ru-v3.md`, `model-comparison-experiment-v4.docx`, `-v3_1.docx` — external report
    revision series / snapshots.
16. Dated spec/schema filenames: `2026-07-10-wiki-eval-experiment-v2.md`, `loop.v1.schema.json`
    (vendored), `superpowers` `VENDORED.md` `v6.0/v6.1.1`.
17. `scripts/01_parse_pdf.py` — stage-order prefix.
18. `anchor_exclusions.json` — status-lifecycle name (post the SEPARATE in-flight `_draft` rename).
19. `eval_grounding.py:355 "version": "terminology_gold.jsonl"` — provenance value = merged-output
    filename (no `vN`; listed to prevent a false edit).
20. `data/eval/wiki/pilot_articles.json` — LIVE output of `export_wiki_corpus.py` (verified live).
21. `G6`/`G1-G5`, `P1/P2/P3` strategy codenames; `C1/C5`, `S1-S6` aspect-ids — not the `vN` pattern.
22. SVG path-data `v<digit>` commands (e.g. `v12`, `v-4`) inside `frontend/src` component
    markup — SVG path syntax, not a version suffix.
23. Opaque test-fixture strings, e.g. `tests/test_revision_history.py` `"v2"`/`"v3"` placeholder
    payloads — fixture data values, not identifiers to de-version.
24. `localhost:\d+/v1` as a PATTERN (replaces the single-port `localhost:8001/v1` literal
    previously in item 5) — third-party API contract, the port varies by environment.
25. Prose citations of the external v1/v2 scoring-prompt lineage at
    `src/palimpsest/webapp/seed.py:27` and `src/palimpsest/webapp/judge.py:17`, plus the
    `docs/stages/translation-eval.md:115` `from_model_config` citation of the sr004 external clone's
    `client.py` — external-prompt/external-clone provenance, same class as items 3-4/8.

### C9 — `chore: durable de-versioning guard (convention + allowlist + advisory hook)` · [S · after C8 · OWNER-GATE(blocking flip)]
The durable guard the owner asked for (§ finding-unknowns W6→next map).
1. **CLAUDE.md § Conventions** — one line: *"No new `vN` suffix on our own artifacts (files,
   identifiers, schema names) unless 2+ versions run simultaneously in the live demo/pipeline;
   dotted model names, external-API `/vN`, `rev-N` contract revisions and serialized schema tags
   are exempt. Allowlist: `.claude/allowlist-versioned.txt`."* Single source of truth.
2. **`.claude/allowlist-versioned.txt`** — new file seeded from the C8 allowlist above.
3. **Claude-Code PreToolUse hook (advisory first):** `.claude/hooks/no-new-version-suffix.py`,
   wired via a Bash matcher entry in `.claude/settings.json` that intercepts `git commit` tool
   calls. Operates on the STAGED DIFF only; match only (a) newly-added file paths matching
   `_v[0-9]`/`V[0-9]` under owned dirs (`src/`, `scripts/`, `data/`, `frontend/src/`, `configs/`);
   (b) newly-added definition lines `^(def|class|[A-Z0-9_]+ *=).*_v[0-9]` in those dirs. Skip
   prose, dotted decimals (`\d\.\d`), `api/v1`, `rev-`, `wave-`, and anything on the allowlist.
   Reuse the existing `.claude/hooks/` infra; do NOT add a new CI system.
   **Scope caveat:** a PreToolUse hook fires only inside Claude-Code sessions — this covers
   commits made through Claude-Code sessions ONLY, NOT owner-shell or CI commits. Repo-wide git
   pre-commit coverage is a possible future step, owner's call — out of scope here.
- **Verify:** stage a synthetic `src/palimpsest/foo_v2.py` → hook warns; stage a file containing
  the allowlisted token `chrono_p31_v1` → silent (no warning); unstage/remove the synthetic file;
  full `pytest` green.
- **OWNER-GATE:** run advisory (warn-only) for ~1 week to tune the allowlist from real diffs, THEN
  the owner approves the flip to blocking. The hook must never be disabled/bypassed; Hard
  Invariant 1 applies to whatever hook chain exists.

---

## Execution order

Execution is **serial A→B on the main working tree**, per the Autonomy resolution above (§
Autonomy resolution, "Execution mode amendment") — no worktree fan-out, no parallel lanes:
`C1 → C2 → C3 → C4 → C5` then `C6 → C7`, then the closing gate/guard `C8 → C9`.

`[V]` **Lane file sets are disjoint** — Lane A: metrics.py, report.py, wiki_eval.py, the two
cleanup tools, the three wiki test files, wiki-eval.md, table-c-grounding.tex,
eval-metrics-terminology.tex, paper-state.md, select/export_wiki_corpus.py, wiki_gt.py,
appendix-wiki-corpus.tex, sr004 runbook, data/eval/wiki/README.md + the corpus data files. Lane B:
merge_goldens.py, eval_grounding.py, terminology_gold source, evaluation/, pipeline/, config.py,
configs/*.yaml, the 2 scaffold test files, client.py, README.md. No shared file → conflict-free
merge; the union suite is green because each lane is individually green.

Ordering principles: (1) data-file rename lands WITH its code reader in one commit (C4 titles.txt
+ export_wiki_corpus.py; C6 gold file + merge_goldens/eval_grounding). (2) test-file rename lands
WITH the src identifier rename (C2). (3) delete-vs-rename split (C3 vs C2, C5 vs C4) keeps each
commit's intent single/bisectable, serialized on shared files. (4) the one live-client-touching
delete (C7 → client.py) is isolated and flagged.

## Effort sizing (S/M/L per commit)

| Commit | Size | Lane |
|---|---|---|
| C1 tex parity | S | A (first) |
| C2 identifier de-version | **L** | A (atomic) |
| C3 methodology_draft delete | S | A (after C2) |
| C4 selection/titles rename | M | A (after C3) |
| C5 pilot/subset deletes | S | A (after C4) |
| C6 gold + _metrics_v1 | S | B (first) |
| C7 scaffold delete | M | B (after C6) |
| C8 sweep gate | S | closing |
| C9 durable guard | S | closing |

---

## Judgment items — RESOLVED positions (OWNER-GATE per conventions §7 split)

| # | Item | Resolved position | Gate |
|---|---|---|---|
| J-PROTO | `"protocol":"v3"` field + report `<h1>` + paper prose | **KEEP** (see § Resolution) | OWNER-GATE (co-owned w/ paper author; orchestrator lean affirmed) |
| J-CODE | `aggregate_corpus_v3`/`render_html_v3`/`_V3_CLASS_LABELS`/`_v3_cell_td` + test file/fn names | **DE-VERSION** (C2) | within mandate |
| J-SEL | `selection_v2.json`/`titles_v2.txt` | **DE-VERSION → selection.json/titles.txt** (C4) | within mandate |
| J-METR | `_metrics_v1` | **rename → `_metrics`**; keep its `"v":1` output (C6) | within mandate |
| J-METH | `methodology_draft()` | **DELETE** (dead, misleading; docs already flag) (C3) | within mandate |
| J-PILOT | `titles_pilot20.txt`, `gt_pilot.jsonl` | **DELETE** (0 readers) (C5) | within mandate |
| J-TEX | `eval-metrics-terminology.tex:15` v2→v3 | **FIX** (plain bug) (C1) | within mandate |
| J-SUB20 | `gt_v2_sub20.jsonl` | **DELETE** (supersedes narrow spec scoping; footgun) (C5) | **OWNER-GATE** — contradicts committed spec prose; courtesy ack |
| J-SCAF | scaffold `evaluation/`+`pipeline/`+`config.py`+`configs/*.yaml`+2 tests + client.py strip | **DELETE NOW** (C7) | **OWNER-GATE** — module-level; + confirm translation-eval.md/models.yaml is the sr004 external clone |
| J-GOLD | `terminology_gold_v1.jsonl` target name | **`terminology_gold_manual.jsonl`** (C6) | **OWNER-GATE** — low-stakes name confirm |
| J-A11 | `audit_prompt_v11.md` | **KEEP** (frozen 11th-iteration campaign artifact, campaign in-flight) | OWNER-GATE — owner may de-number |
| J-V1C3 | `v1_core3` vendored dir | **KEEP name**; escalate the `VENDORED.md` boundary breach (document vs relocate) | OWNER-GATE — separate hygiene question, not this spec |
| J-DOCX | `report-ru-v3.md`/`-v4.docx` external series | **KEEP** (external revision series; snapshots archive) | OWNER-GATE — reconcile md-v3/docx-v4 numbering (cosmetic) |
| J-SEED | `seed_prompt_variant="v2"` | **LEAVE** (write-only DB provenance; rename only at a future forced reseed) | OWNER-GATE — low priority |
| J-GUARD | advisory→blocking hook flip (C9) | advisory ~1 week, then flip | **OWNER-GATE** — owner approves the flip |

### Resolution of the known disagreement — `"protocol":"v3"` (engineering DROP vs conventions KEEP)
**KEEP** the `"protocol":"v3"` field and, for coherence, the report `<h1>` label. Both drafts, the
paper, and the tex SSOT retain "protocol v3" as a methodology proper-noun for the real v1→v2→v3
(mention-level→set-based) lineage; a run artifact that stamps *which methodology produced it* is
self-description — exactly the schema-provenance carve-out the rule exempts (like `chrono_p31_v1`
and GroundingTrace `"v":1`), not a versioned-artifact name. `metrics.json` is written under the
immutable `reports/` tree; the already-committed run carries `"protocol":"v3"`, and dropping it from
new runs would leave old-vs-new artifacts with no provenance tag to tell them apart — worse than
keeping. Only the CODE IDENTIFIERS have a fully-deleted v1/v2 sibling and no live coexistence, so
only they de-version. **Consequence:** the three protocol assertions and `test_protocol_key_present`
stay unchanged, and engineering C2's "drop the key / drop the `<h1>` / remove the assertions" steps
are retracted.

---

## Risk register (engineering §5 ∪ conventions §8, deduped)

| # | Item | Blast radius | Detection | Rollback |
|---|---|---|---|---|
| R1 | pinned regression fixtures (C2) | 3 anchor tests | identifier-token-only `git diff -U0` shows no numeric churn; anchors pass | `git checkout` test file, re-apply token-only |
| R2 | scaffold delete edits live `client.py` (C7) | whole demo LLM path | `python -c "import palimpsest.webapp.app"` + full pytest + evaluate smoke; `rg from_model_config` live = 0 | revert C7; client.py edit is 2 hunks |
| R3 | `titles.txt` is a live input (C4) | `export_wiki_corpus.py` rebuilds | same-commit `DEFAULT_TITLES` update + `--help` path check; `rg titles_v2` live = 0 | `git mv` back; 1-line code revert |
| R4 | `.tex` edits vs owner Overleaf (C1/C2/C4) | 3 `.tex` files | not auto-detectable — flag every edited `.tex` line loudly in the report | owner re-syncs; repo diff is source of truth |
| R5 | campaign tools mirror `aggregate_corpus_v3` (C2) | replay_analysis/enumerate_misses | `rg aggregate_corpus_v3` live = 0; `python replay_analysis.py` import | restore the single-token call |
| R6 | C8 false-flag of the KEPT `"protocol":"v3"`/`<h1>` | sweep noise | allowlist items 3–4 whitelist them explicitly | extend allowlist |
| R7 | `gt_v2_sub20` resurrection trap (C5) | anyone reviving from history | deletion removes the footgun; runbook reworded | `git revert`/checkout if a real need appears |
| R8 | shared-doc conflict across lanes | wiki-eval.md, sr004 runbook | lanes disjoint + Lane A serial on these docs | standard rebase, confined to Lane A |
| R9 | `external/gse-translation` false alarm | none | external has its OWN `palimpsest.config`; `external/` is immutable | avoided by construction |
| R10 | `configs/*.yaml` doc-parity (C7) | README.md + sr004 runbook | `README.md:53` edited same commit; implementing agent verifies translation-eval.md's models.yaml is the external sr004 clone during C7 (resolved, no owner step — § C7 OWNER-GATE bullet 2) | if it's the repo file, add a translation-eval.md edit to C7 |
| R11 | renaming `aggregate_corpus_*` touches the live Table C harness | paper runs may be pending | do C2 in the gap BETWEEN full runs (mandate's "clean fixed state before expensive runs"); resolved per the Autonomy resolution — NER extraction may run concurrently, C2 lands before any scoring run | defer C2 until the in-flight run lands |
| R12 | `terminology_gold_v1.jsonl → terminology_gold_manual.jsonl` rename (C6) | gold-source readers | `sha256sum` before/after equality on the renamed file (C6 Verify) | `git mv` back + 2-line revert |
| R13 | C9 advisory hook: excess false positives during the ~1 week trial | developer friction, alert fatigue | observed false-positive rate against real diffs during the advisory trial week | remove the `.claude/settings.json` matcher entry + delete `.claude/hooks/no-new-version-suffix.py` |

**Top-3 (raw):** R1 (perturbing pinned numbers), R2 (scaffold delete hits the live LLM client),
R4 (`.tex` collides with the owner's Overleaf — flag line-by-line, never silent).

---

## MUST-NOT-TOUCH (immutables)

- `reports/**` — all run artifacts, `metrics.json`, and the two `pred.jsonl` regression fixtures.
- `external/gse-translation/**` — vendored: its own `config.py`/`client.py`,
  `prompts/03_scoring/{v1,v2,universal,_legacy,v1_core3}`, `configs/scoring/*-v1-*/-v2-*.yaml`.
- `docs/reports/**` — point-in-time (incl. `wiki-eval-v2-pilot-analysis.md`,
  `prompt-engineer-ner-prompt-v22.md`, `report-ru-v3.md`).
- `docs/experiments/**` (`model-comparison-experiment-v4.docx`) and `docs/paper/snapshots/**`
  (`model-comparison-experiment-v3_1.docx`, dated `.tex`/`.pdf`).
- Dated `docs/superpowers/specs/**` + `docs/superpowers/plans/**` — incl.
  `2026-07-10-gt-canonicalization.md` ("не трогать" prose STAYS; superseded by a fresh commit,
  never rewritten), `2026-07-10-wiki-eval-experiment-v2.md`, `tickets/001-gt-v2-build.md`.
- `docs/known_issues.md` RESOLVED entries (the `gt_v2.jsonl` incident) — historical record.
- The pinned regression numbers in `test_wiki_metrics.py` — byte-identical.
- The allowlist survivors (§ C8): `CHRONO_P31_VERSION` value, GroundingTrace `"v":1`, demo-contracts
  DDL comment, `seed_prompt_variant` DB value, `rev-4/rev-5`, dotted model names, `document.version`,
  `USER_AGENT`, `__version__`, `package.json`, `api/v1`.
- `data/eval/wiki/pilot_articles.json` — LIVE output of `export_wiki_corpus.py` (verified).
- `data/eval/wiki/pages/` cache — separate hygiene, owner-optional, out of this spec.

---

## Open questions

**Resolved & executing (FYI in the final owner report, non-blocking):** the Autonomy resolution
(2026-07-10, top of this doc) already resolved these OWNER-GATE items for immediate execution —
each is FYI'd to the owner in the final report rather than blocking on a reply.
- **J-SUB20** — `gt_v2_sub20.jsonl` deletion (C5); courtesy heads-up only.
- **J-SCAF** — scaffold deletion (C7), including the `client.py` dead-import strip and the
  `README.md:53` parity edit.
- **J-GOLD** — target name `terminology_gold_manual.jsonl` (C6).
- **J-A11** — `audit_prompt_v11.md` KEPT (provenance artifact); owner may de-number later.
- **R10** — `configs/models.yaml` provenance: implementing agent verifies during C7 (per Autonomy
  resolution) rather than waiting on an owner confirm — see the C7 OWNER-GATE bullet 2.
- **R11** — Table C run timing: resolved per the Autonomy resolution above (NER extraction may run
  concurrently; C2 lands before any scoring run is invoked).
- **`.tex` co-author confirm (C1)** — courtesy-confirm with the paper co-author happens alongside
  landing C1 that "v2" is a stale label, not a distinct paper numbering; non-blocking, flagged in
  the final report (R4).

**Genuinely open (no action in this spec):**
- **J-V1C3** — `v1_core3` vendored dir name; `VENDORED.md` boundary-breach escalation.
- **J-DOCX** — `report-ru-v3.md`/`-v4.docx` external numbering reconciliation.
- **J-SEED** — `seed_prompt_variant="v2"` rename (deferred to a future forced reseed).
- **`pages/` cache hygiene** (`data/eval/wiki/pages/`) — owner-optional follow-on, out of scope.
- **C9 blocking flip** — advisory→blocking hook flip stays with the owner (J-GUARD), owner-timed.
