# De-versioning cleanup — C8 residue sweep record

**Date:** 2026-07-10. **Spec:** [2026-07-10-deversioning-cleanup.md](../superpowers/specs/2026-07-10-deversioning-cleanup.md)
§ C8. **Branch:** `claude/ner-translation-config-b0ozsc`, run after Lane A
(`e880d55`..`bee239b`) and Lane B (`e764678`, `e11be5f`) both landed, HEAD `6958cea`.

This is the HUMAN-TRIAGED gate commit's record, not a code commit — see the spec's C8
framing ("judgment-based, not automated pass/fail"). I (the implementing agent) performed
the triage the spec assigns to this step; no item required escalation to the owner beyond
the two folded-in items the task brief already named.

## 1. Sweep command

```
rg -n "v[0-9]" <live tree> \
  -g '!reports/**' -g '!external/**' -g '!docs/reports/**' -g '!docs/experiments/**' \
  -g '!docs/paper/snapshots/**' -g '!docs/superpowers/specs/**' -g '!docs/superpowers/plans/**' \
  -g '!docs/handoff-*.md' -g '!.git/**'
```
(exclusions per spec § Immutability rule — the canonical exclusion set).

**Before the one residue fix below:** 834 hits. **After:** 833 hits, all triaged.

## 2. Triage method

834 hits is too many for a literal one-row-per-hit table to be readable, so triage was
done with a scripted classifier (regex rules keyed to each of the 25 allowlist items'
described tokens/patterns, run against every `file:line:content` hit) followed by a manual
line-by-line review of everything the script left unclassified (19 lines) and a spot-check
of every bucket's sample. Every one of the 834 raw hits resolved to exactly one bucket —
summarized below by bucket, not by individual line, per the spec's own precedent of
grouping (e.g. allowlist item 22 already covers "SVG path-data commands" as one bucket
rather than 5 rows).

## 3. Results summary

| Category | Hits | Verdict |
|---|---:|---|
| Allowlist items 1–25 (see § 4) | 384 | ALLOWLISTED |
| Out-of-scope noise (not our artifacts / explicit non-goals) | 439 | not residue, no allowlist entry needed |
| `docs/known_issues.md` RESOLVED historical record | 7 | protected by MUST-NOT-TOUCH, not residue |
| Provenance/methodology prose (judgment calls, reasoned below) | 3 | not residue |
| **TRUE RESIDUE found** | **1** | **FIXED in this commit** (§ 5) |
| **Total raw hits (post-fix sweep)** | **833** | **0 unclassified, 0 remaining residue** |

## 4. Allowlist items with live hits (§ C8 allowlist items 1–25)

| Item | Description | Hits | Example |
|---|---|---:|---|
| 1 | `chrono_p31_v1`/`CHRONO_P31_VERSION` schema tag + `gt.jsonl` records | 102 | `data/eval/wiki/gt.jsonl` (100 records) + `wiki_gt.py:37` + `test_wiki_gt.py:190` |
| 2 | `GroundingTrace` `v1` schema tag + prose referencing it | 4 | `candidates.py:17`, `terminology.md:83`, `test_terminology.py:21,762` ("trace v1 completeness") |
| 3–4 | "protocol v3"/"Protocol v3"/"PROTOCOL v3" methodology self-description (code + prose), incl. the KEPT Protocol-v2 `<details>` history block in `paper-state.md:74,79` | 42 | `metrics.py:149`, `report.py:95` `<h1>`, `wiki-eval.md`, `table-c-grounding.tex`, `eval-metrics-terminology.tex`, sr004 runbook |
| 3–4 (campaign) | "wiki-eval v2"/"experiment v2"/"v2 pilot"/"v2 session"/"transport rework v2" as a dated campaign-iteration label, same provenance class as 3–4 | 20 | `client.py:37,80,96`, `label_first.py:20,178`, `wiki_eval.py:2`, 4× `cleanup/tools/*.py` provenance headers |
| 3–4 (ext.) | Local variable names `v3_result`/`articles_for_v3` in `replay_analysis.py` — mirrors the KEPT "protocol v3" naming, not a versioned-artifact name (extends 3–4 by the same reasoning; C2's file-list only touched call sites, not general local identifiers in this analysis tool) | 15 | `cleanup/tools/replay_analysis.py:106-381` |
| 5 | External API `/v1` strings (`openrouter.ai/api/v1`, `closerouter.dev/v1`, `api.openai.com/v1`, `sk-or-v1-`, Wikipedia `rest_v1`, Anthropic SDK `/v1/messages`) | 44 | `configs/bouquet_judges.yaml`, `settings-rework.html`, tests, `wiki_gt.py:34`, sr004-patch |
| 8 | `v1_core3` vendored prompt dir name (references from our own scripts/docs) | 7 | `bouquet_judge_rerun.py:11,90`, `paper-state.md`, `table-a-judges.tex:55`, sr004 runbook |
| 9 | Dotted/hyphenated third-party model names (`deepseek-v4-flash`, `gpt-5.4/5.5`, `gemini-3.1/3.5`, `qwen3.6/3.7`, `claude-opus-4.8` etc.) | 79 | `configs/bouquet_judges.yaml`, `known_issues.md`, `paper-state.md`, tests, scripts |
| 13 | `audit_prompt_v11.md` provenance artifact | 1 | `data/eval/wiki/README.md:64` |
| 14 | `seed_prompt_variant="v2"` write-only DB provenance value | 1 | `seed.py:94` |
| 15 | External report revision series (`report-ru-v3.md`, `model-comparison-v4`/`-experiment-v4`) | 9 | `build_model_comparison_docx.py` (incl. `:38` `TITLE_BASE` — the script that *produces* the `-v4.docx`, same series) |
| 16 | Dated spec filename citations (`2026-07-10-wiki-eval-experiment-v2.md`, `2026-07-01-model-registry-design.md`) | 27 | `docs/README.md`, `known_issues.md`, `paper-state.md`, `.tex` files, `metrics.py`/`report.py`/`extract.py` docstrings, tests |
| 22 | SVG path-data `v<digit>` commands in frontend markup | 5 | `UploadIcon.tsx`, `VariantA.tsx`, `InspectorPanel.tsx` |
| 23 | Opaque test-fixture `"v2"`/`"v3"` placeholder payloads | 3 | `test_revision_history.py:116,117,120` |
| 24 | `localhost:\d+/v1` port-varies pattern | 18 | sr004 runbook `localhost:8000/v1`, `127.0.0.1:8000/v1` |
| 25 | External v1/v2 scoring-prompt lineage prose (`seed.py:27`, `judge.py:17`) + `test_judge_parse.py:1` ("v2 payload" — same class, mirrors `judge.py:17`'s "v2 judge prompts") | 3 | — |
| 25 (extended, sanctioned) | `docs/stages/translation-eval.md:115` `from_model_config` — external sr004-clone citation. **Spec item 25's wording was extended one line** in this commit to name this hit explicitly (task-sanctioned edit) | 1 | `LLMConfig.from_model_config` → `external/gse-translation/.../client.py` |
| C5 provenance (Lane A) | `gt_v2_sub20` mentions in `titles_ablation20.txt` header + 2 reworded sr004-runbook lines — the file's own deletion-provenance comments, opposite of the R7 "resurrection footgun" the grep guards against (Lane A's own report, `docs/reports/python-pro-deversioning-lane-a-execution.md`, flags this same tension; folded in here per task brief) | 3 | — |

**Total allowlisted: 384.**

## 5. TRUE residue found and fixed

**`scripts/select_wiki_corpus.py:196`** — a stale `[v2]` debug-print tag on the per-section
progress log line, left over from before C4 renamed the file's own docstring label
("Selection v2:" → "Selection:", `:2`) and the `selection_v2.json`/`titles_v2.txt` data
files. C4's file-list only named `:2`, `:7`, `:204` — this print statement at `:196` was
missed. It is a genuine versioned-OUR-artifact hit not on the allowlist (S-sized, one
token) — fixed in this commit by dropping the stale tag:

```diff
-    print(f"[v2] {name:26s} found={len(picks)}/10 examined={examined} "
+    print(f"{name:26s} found={len(picks)}/10 examined={examined} "
```

No other TRUE residue found. Nothing was L-sized or required deferring to a follow-up
report.

## 6. Judgment calls (not on the literal allowlist text, resolved as prose/noise by reasoning)

- **`scripts/merge_goldens.py:38`** — `# difficulty disputes — my v1 golden over-labelled
  groundable terms as red.` Reads as informal first-person provenance narrative about an
  early manual-labeling round ("my first golden-label pass"), not a citation of the retired
  `terminology_gold_v1.jsonl` filename by name. Classified as historical/methodology prose
  (provenance-artifact-kept naming principle) — not residue, left unchanged. Flagged here
  rather than silently resolved, since it is the one genuinely borderline call in the sweep.
- **`data/eval/wiki/cleanup/tools/span_ner_before_after.py:28-29`** — cites two `docs/reports/`
  filenames containing `v2` (`wiki-eval-v2-pilot-ner-vs-disambig.md`,
  `wiki-eval-v2-span-ner-before-after-cleanup.md`). These are point-in-time report filenames
  under the immutable `docs/reports/` tree, cited by name from a non-immutable script
  comment — same reasoning as allowlist item 16 (dated-filename citation is not itself a
  version-suffix issue on our code). Not residue.
- **`docs/paper/handoff-paper-text-session-2026-07-10.md:23`** — `v2-прогонов.` (Russian
  "v2 runs"), campaign-iteration prose. Note: this file lives at `docs/paper/handoff-*.md`,
  not the top-level `docs/handoff-*.md` the spec's canonical exclusion glob names — the glob
  is non-recursive and does not cover nested `handoff-*.md` files. This is a spec-wording
  gap (not a residue problem, since the content here is Russian prose, not a code
  identifier) — flagged for awareness, no action taken since fixing it would require editing
  the spec's Immutability-rule glob text, out of this closeout's small-edit mandate.

## 7. Out-of-scope noise (not our artifacts, no allowlist entry needed)

- **Lockfiles** (`uv.lock` 264, `frontend/package-lock.json` — folded together, 264 combined
  across both — see raw counts below): base64 package hashes coincidentally containing a
  `v[0-9]` substring; auto-generated third-party dependency manifests, not "our own
  artifacts" per the spec's Scope section.
- **Cached wiki HTML pages** (`data/eval/wiki/pages/*.html`, 163 hits): third-party page
  content matches; explicitly out of scope per the spec's own non-goals ("Cache hygiene of
  `data/eval/wiki/pages/` … not a version-suffix item … owner-optional follow-on, not
  here").
- **Incidental substring noise** (11 + 1 = 12 hits): local variable names `ev1`/`ev2`/`rev1`
  (e.g. `test_c5_loop_integrity.py`, `test_prediction_preservation.py`,
  `test_revision_history.py:107,109`) where `v1`/`v2` is a coincidental substring of an
  unrelated identifier ("evaluation-result-1", not "version 1"), and one hash-like fixture
  ID `001-kv35yl.json` (`cleanup/manifest.json:4`) with a coincidental `v3` substring.

## 8. `docs/known_issues.md` — RESOLVED historical record (7 hits)

Lines 202–225 and 280 are inside the already-committed `RESOLVED 2026-07-10:
data/eval/wiki/gt.jsonl silently drifted…` entry, documenting the `gt_v2.jsonl` incident.
Protected by the spec's own MUST-NOT-TOUCH list ("`docs/known_issues.md` RESOLVED entries
(the `gt_v2.jsonl` incident) — historical record"). Not edited. (This file is not itself in
the C8 canonical exclusion glob, so these hits legitimately surfaced in the sweep — they are
correctly classified as protected-historical, not residue, rather than silently dropped.)

## 9. Immutability criterion (spec Success Criterion 6 / task step C8.3)

```
git diff --name-only c691eb8..HEAD -- reports/ external/ docs/reports/ docs/experiments/ \
  docs/paper/snapshots/ docs/superpowers/specs/ docs/superpowers/plans/
```
(`c691eb8` = the commit immediately before C1's `e880d55`, i.e. the pre-C1 base.)

Result — 3 paths, all `git diff --name-status` = `A` (pure additions):
```
A  reports/terminology/wiki-eval/google--gemma-3-27b-it--Parasail/111/2026-07-10T18-22-43Z/calls.jsonl
A  reports/terminology/wiki-eval/google--gemma-3-27b-it--Parasail/111/2026-07-10T18-22-43Z/pred.partial.jsonl
A  reports/terminology/wiki-eval/google--gemma-3-27b-it--Parasail/111/2026-07-10T18-22-43Z/progress.jsonl
```
These are the concurrent wiki-eval run agent's live output (matches the untracked
`reports/terminology/wiki-eval/google--gemma-3-27b-it--Parasail/` directory seen in
`git status` at task start) — sanctioned per the task brief ("reports/terminology/*
ADDITIONS from the concurrent run agent"). No pre-existing file in any of the seven
immutable trees was modified.

`docs/reports/` shows **zero** committed changes in the range; the one new report
(`docs/reports/python-pro-deversioning-lane-a-execution.md`, Lane A's own execution report)
is still untracked at sweep time and will be a pure addition in the hygiene-closeout commit.
This spec file itself (`docs/superpowers/specs/2026-07-10-deversioning-cleanup.md`) received
the one sanctioned item-25 wording extension (§ 4 above) plus this C8 section's own edits —
the spec's own sanctioned self-amendment exception.

**Verdict: PASS. No immutability violations.**

## 10. Final grep-zero confirmations (spec Success Criterion 3 tokens)

All run with the same canonical exclusions as § 1:

| Token | Live-tree hits (outside allowlist) |
|---|---:|
| `aggregate_corpus_v3` | 0 |
| `render_html_v3` | 0 |
| `_v3_cell_td` | 0 |
| `_V3_CLASS_LABELS` | 0 |
| `test_wiki_metrics_v3` | 0 |
| `methodology_draft` | 0 |
| `selection_v2` | 0 |
| `titles_v2` | 0 |
| `gt_v2_sub20` | 3 (all provenance prose, § 4 "C5 provenance" row — sanctioned) |
| `titles_pilot20` | 0 |
| `gt_pilot\.jsonl` | 0 |
| `terminology_gold_v1` | 0 |
| `_metrics_v1` | 0 |
| `palimpsest.pipeline\|palimpsest.evaluation\|palimpsest.config\|from_model_config` | 1 (`translation-eval.md:115`, allowlist item 25 extension — sanctioned) |

All 13 tokens are clean per the spec's own definition (0, or the explicitly sanctioned
provenance-prose exceptions the spec/task brief carve out).

## 11. Verdict

C8 gate: **CLEAN.** 833 live `v[0-9]` hits, 384 on the allowlist, 439 out-of-scope noise,
7 protected historical record, 3 reasoned provenance/methodology prose, 1 true residue found
and fixed in this same commit. Zero un-triaged, zero unresolved residue. Immutability
criterion passes. All Success-Criterion-3 tokens are grep-zero or explicitly sanctioned.
