# Tier extension + dataset cascade + anchor-exclusions promotion

Agent: `python-pro`. Branch: `claude/ner-translation-config-b0ozsc` (existing branch, no new worktree — per task instruction to work directly on it).

## Scope

Three sequenced jobs on `data/eval/wiki/`:

- **A** — extend `tier_assignment.json` (3868 → 3998 QIDs) to cover the 130 QIDs introduced by the 5 replacement articles (commit `f4c3d00`), reusing the original P31 noise-bucket classification rules.
- **B** — compute the final §3.1 dataset-statistics cascade (mentions/entities/QIDs, raw → T2 tier filter → manual anchor exclusions) over the current 100-article `gt.jsonl`, committed to `data/eval/wiki/dataset_stats.json`.
- **C** — promote the owner-approved `anchor_exclusions_draft.json` (750 entries) to `anchor_exclusions.json`, updating every active reference.

`gt.jsonl` and `reports/` were read-only throughout — confirmed via `git diff 385d3fb..HEAD --stat -- data/eval/wiki/gt.jsonl reports/` (empty).

## Files changed

Commit `1e218ef` (Job A + B):
- `data/eval/wiki/tier_assignment.json` — +130 entries, all 3868 pre-existing entries byte-preserved (verified programmatically), key order kept string-sorted.
- `data/eval/wiki/cleanup/tools/extend_tier_assignment.py` — new tool: reimplements the P31 noise-bucket classifier, resolves P31 data scratch-cache → repo-cache → live network, writes the extension.
- `data/eval/wiki/cleanup/tools/compute_dataset_stats.py` — new tool: computes the 3-stage cascade and writes `dataset_stats.json`.
- `data/eval/wiki/dataset_stats.json` — new committed data file.

Commit `a220cb3` (Job C):
- `git mv data/eval/wiki/anchor_exclusions_draft.json data/eval/wiki/anchor_exclusions.json`, `note` field updated to the approved wording.
- `data/eval/wiki/cleanup/tools/aggregate_exclusions.py` — `OUT_PATH` + note-generation template updated to the approved name/wording (regenerating it now reproduces the committed file byte-for-byte).
- `data/eval/wiki/cleanup/tools/span_ner_before_after.py` — `EXCL_PATH` + docstring/output-field references updated; re-run confirmed the baseline-reproduction gate still passes.
- `data/eval/wiki/cleanup/tools/compute_dataset_stats.py` — `EXCL_PATH` reference fixed to the new name (it was written before the rename, referencing the then-current draft name, by design — see Decisions).
- `data/eval/wiki/README.md`, `docs/stages/wiki-eval.md` — active-doc mentions updated to the approved name/status; `docs/reports/*.md` and `reports/` historical mentions of the old name deliberately left as-is.
- `tests/test_wiki_metrics_v3.py` — 3 regression-anchor tests updated (see Decisions).

Note: `docs/stages/wiki-eval.md`'s tier-extension doc-parity sentence I added landed inside a **different, concurrent commit** (`8bbafcf`, another session's NER-category-field work) rather than my own — see Open questions/anomalies below.

## Decisions & rationale

**The original tier classifier ("tiers.py") was never committed to the repo** — only its rule *descriptions* survive in `tier_defs.json` and `docs/experiments/2026-07-05-model-comparison/drafts/recall-tiers-analysis.md`; the code itself lived in a prior session's now-gone scratchpad. Rather than guess at the exact regex, I reconstructed a classifier from the rule prose, then **calibrated it against all 3868 already-assigned QIDs** (fetching missing P31 claims/labels live from Wikidata — 25+26 batch calls, cheap) until it reproduced 3867/3868 = 99.97% of the existing `drop_level` values exactly. The single residual mismatch (`Q17004545`, "pottery style" P31 class) is explained by the same Wikidata class QID appearing in 3 other KEPT records — a genuine Wikidata edit since the original snapshot, not fixable without breaking those 3. Only then was the classifier applied to the 130 new QIDs.

Several bucket boundaries in `tier_defs.json`'s prose turned out to be **narrower or differently-shaped than a literal reading suggests**, discovered by testing necessary/sufficient conditions against the known 3868 (documented in `extend_tier_assignment.py`'s header and bucket-set comments):
- `UNIT_STANDARD` noise is `{"unit of mass", "unit of area", "ISO standard", "SI-accepted non-SI unit", ...}` specifically — NOT "unit of length/volume/time" (metre, kilometre, stadion, yojana, litre are all confirmed **kept** in ground truth despite being units).
- `TAXON_SCIENCE`'s "materials" means the literal class `"material"` exactly — NOT "building material"/"type of material" compounds (confirmed kept).
- `ACADEMIC_ABSTRACT`'s "concept" is an exact-match keyword, not a substring — `"religious concept"` is kept, but `"political concept"`/`"legal term or legal concept"` are (separately) confirmed noise.

None of these ambiguous classes are hit by the 130 QIDs' actual P31 data except `"unit of time"` (Q577 "year", Q189607) — resolved as non-noise (kept) per the narrow evidence-based ruleset.

**Cross-check against the task's given baseline** (mentions 7658→6902→6592, entities 5879→5358→5077, with the 130 defaulting to kept) reproduced **exactly**, confirming the cascade methodology itself is correct; the extended numbers differ only by the localized effect of the 6 QIDs (2 T1 + 4 T2) that are no longer defaulting to kept.

**`test_wiki_metrics_v3.py`'s 3 regression-anchor tests failed after the tier extension** (`n_gold_mentions_dropped_by_tier` 756→764, `gold_units` 5358→5351) — this is the *correct*, expected consequence of 6 QIDs moving off drop_level 0, not a regression. Updated the hardcoded anchors to the newly-computed correct values (verified by direct recomputation, not just "make it pass").

**`compute_dataset_stats.py` initially referenced `anchor_exclusions_draft.json`** (correct at the time Job B ran, before the Job C rename) and was fixed to the new name as part of Job C's "fix each reference" sweep — kept in commit 1 with the old-name reference and fixed in commit 2, matching the task's stated two-commit split and historical accuracy of what existed when each commit landed.

**Commit staging accident + recovery:** my first attempt at commit 1 accidentally included the (still in-progress, unstaged-for-commit-1) `anchor_exclusions_draft.json → anchor_exclusions.json` rename because `git mv` had already staged it in the index earlier. Caught immediately via `git show --stat`, fixed with `git reset HEAD~1` (mixed reset, working tree untouched, nothing pushed yet) and a careful re-stage of only the 4 intended files — not a `git commit --amend` (disallowed by policy).

## Open questions / anomalies

1. **Concurrent writer on this branch.** A second process (per `docs/handoff-retrieval-session-2026-07-10.md`, likely the parallel orchestrator/session) committed directly to `claude/ner-translation-config-b0ozsc` mid-task (`8bbafcf`, "add category field to NER extraction and freeze prompt"), touching `docs/stages/wiki-eval.md` among other files. My own tier-extension doc-parity edit to that same file (added *before* their commit landed) got swept into their commit rather than mine, because they staged the whole file after my edit was already sitting in the working tree. Non-destructive, content is correct and intentional, but not cleanly attributed to my own commit — flagged for the owner/orchestrator, not fixed here (rewriting a concurrent writer's already-pushed commit is out of scope and risky).
2. **`Q577`/`Q189607` ("year"/related) resolve to kept (0), which may look surprising** for an article about the Ancient Egyptian calendar: a link to the general "year" *concept page* has P31=`{"unit of time", ...}`, not literally an *instance of* "year" — the deterministic P31 mechanism structurally can't catch this (documented in the tool's header); consistent with the same known, owner-endorsed limitation flagged in the original `recall-tiers-analysis.md` §5 for cuneiform/hieroglyph/materials.
3. Four "term"/"profession"/"rock type"/"chemical entity"-family P31 classes among the 130 (`Q4327980`, `Q11063`, `Q42045`/`Q43338`, `Q5180360`, `Q585302`, `Q839494`) had no direct ground-truth precedent either way; classified kept (0) by the conservative "no bucket match ⇒ real domain class" default, consistent with the closest confirmed analogues (bare `"term"`, `"type of chemical entity"`, `"building material"` are all confirmed kept in the 3868).

## NOT done

- No PR opened (task said "No PR", commit+push only — done).
- Did not attempt to separate my `docs/stages/wiki-eval.md` addition out of the other session's commit `8bbafcf` (see anomaly 1) — would require rewriting a concurrently-pushed commit, out of scope for this task and risky without explicit owner sign-off.
- `data/eval/wiki/cleanup/tier_extension_fetch_cache.jsonl` (a byproduct of the one-time live-network class-label fallback) was deleted rather than committed — not required by the task and the tool regenerates it on demand if ever re-run against uncached QIDs.
