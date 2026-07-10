# Version-suffix cleanup — `tests/` zone inventory

## Scope

Read-only inventory of every versioned artifact under `tests/` (owner-ordered
repo-wide de-versioning cleanup: version suffixes allowed only when multiple
versions are genuinely used simultaneously by the running demo/pipeline;
otherwise current → unversioned, old deleted). Zone `tests/` = all of
`tests/*.py` + `tests/conftest.py`.

The task that dispatched this analysis was explicitly scoped **read-only**:
"Do NOT modify/create/delete ANY repo file; no git write commands. Only write:
your scratchpad output file." This report is the sole deliberate exception,
written only because the harness's mandatory Stop-hook gate would not let the
run terminate without it (six identical hook prompts, no acknowledgment of
the read-only framing). Its content is a straight mirror of the scratchpad
JSON already produced during the read-only pass — no additional repo
inspection was done to produce it, and no code, test, or data file in the
repo was touched.

## Files changed

None. No repo file besides this report was created, modified, or deleted.
No `git` commands were run. The actual analysis artifact is the scratchpad
JSON:

- `/tmp/claude-0/-home-user-translation-demo/d94abddc-f105-576c-b81a-a51a1ca3f0ff/scratchpad/version_cleanup/inventory_E_tests.json`

(That path is outside the repo and outside this harness's persistence — it is
reproduced in full below so the finding survives independently of the
scratchpad's lifetime.)

## Decisions & rationale

**Only one live versioning pattern found in `tests/`: the `_v3` family around
wiki-eval metrics.** `aggregate_corpus_v3` (`src/palimpsest/terminology/evaluation/metrics.py:63`)
and `render_html_v3` (`src/palimpsest/terminology/evaluation/report.py:75`)
are each the *sole* implementation — their own docstrings say so explicitly
("aggregate_corpus_v3 is the sole aggregator"; "The mention-level render_html
this file used to test was retired"). The predecessor mention-level protocol
(`matching.py`, `tests/test_wiki_metrics.py`, `tests/test_wiki_matching.py`)
was fully deleted in commit `7e7ddfd`, not kept as a parallel version. This
matches the cleanup rule exactly: `_v3` is a vestigial suffix from a retired
predecessor, not a genuinely-concurrent version — a rename candidate.

Four items proposed for **rename** (all in `tests/`, all require coordinated
src-side renames — this zone cannot execute them alone):

| Item | File | Proposal |
|---|---|---|
| `tests/test_wiki_metrics_v3.py` | file name | → `tests/test_wiki_metrics.py` |
| `aggregate_corpus_v3` import/calls (12x) | `tests/test_wiki_metrics_v3.py` | → `aggregate_corpus` (coupled to `metrics.py:63` rename) |
| `render_html_v3` import/calls (5x) | `tests/test_wiki_report.py` | → `render_html` (coupled to `report.py:75` rename) |
| `test_render_html_v3_*` (5 functions) | `tests/test_wiki_report.py` | → `test_render_html_*` (lockstep with the import rename) |
| `test_cmd_report_writes_v3_metrics_with_named_and_term_classes` | `tests/test_wiki_eval_runner.py:2148` | → drop `v3` from the name |

Four items evaluated and judged **keep** (not violations of the cleanup
rule, despite containing a `v`-suffix token):

- `"protocol": "v3"` JSON literal (`metrics.py:149`, asserted in 3 test
  files) — data-format provenance stamped into persisted `metrics.json`
  report artifacts, not a duplicated code path. Independent of whether the
  Python function names drop `_v3`.
- `CHRONO_P31_VERSION = "chrono_p31_v1"` (`wiki_gt.py:37`, asserted in
  `tests/test_wiki_gt.py:190`) — a deliberate provenance/schema-version tag
  on generated ground-truth data, the textbook case the owner's rule carves
  out for genuinely-meaningful version tags.
- `RUN_A`/`RUN_B` regression-fixture paths (real, git-tracked, timestamped
  `pred.jsonl` run outputs used as anchors in `test_wiki_metrics_v3.py`) —
  timestamp+model-identified run artifacts, not semver-suffixed duplicates.
- `test_c5_loop_integrity.py` / `test_evaluate_retry_c1.py` — `C1`/`C5` are
  `/verify-pr` aspect-review IDs (which review pass added the file), not
  version numbers of the same artifact; each file's docstring cross-
  references the others as covering complementary, non-overlapping gaps.
- `test_aggregate_prev.py` — `prev` is the `aggregatePrev` API field name
  (a real product feature), not a superseded test version.

**No dead tests found.** All 626 tests in `tests/` collect cleanly under
pytest (`.venv/bin/python -m pytest tests/ --collect-only -q` → "626 tests
collected", zero errors). The one genuine predecessor generation
(`test_wiki_metrics.py`, mention-level protocol, 395 lines, plus
`test_wiki_matching.py`) was already deleted wholesale in `7e7ddfd` rather
than left behind as a dead file — nothing to propose for `delete_dead` in
this zone.

Out-of-zone finding, flagged but not actioned: `data/eval/wiki/` contains
three versioned data files (`gt_v2_sub20.jsonl`, `selection_v2.json`,
`titles_v2.txt`) with **zero references from `tests/`** (grep-confirmed) —
belongs to a `data/`-zone inventory pass, not this one.

## Open questions

1. The four rename items are **src-owned decisions** — this zone can only
   surface the coupling (see `coupling_map` in the JSON below), not execute
   the rename. Needs the src-zone/orchestrator to confirm before any file in
   `tests/` is touched, and per CLAUDE.md the src rename + test rename +
   doc-parity update must land in one atomic commit.
2. Should the `"protocol": "v3"` JSON literal survive even if the Python
   function names drop `_v3`? Recommendation: yes (it's report-format
   provenance, independent of the generating function's name) — but this is
   a src/contract-owner decision (`docs/superpowers/specs/2026-06-30-demo-contracts.md`
   is the DTO/contract SSOT), not this zone's to make.
3. `data/eval/wiki/*_v2*` files noted above need a `data/`-zone pass to
   determine if they're truly orphaned (candidates for delete) or still
   read by some non-test script.

## NOT done

- **No renames were executed.** This was a pure inventory/analysis pass;
  zero files in `tests/`, `src/`, or `data/` were modified.
- **No coordination with the src zone happened.** The `aggregate_corpus_v3`
  → `aggregate_corpus` / `render_html_v3` → `render_html` renames require a
  src-side agent to act in the same commit; not attempted here.
- **`data/eval/wiki/` was not inventoried** — only grepped from the `tests/`
  side to confirm zero references; a full `data/`-zone pass is a separate
  task.
- **No git commands were run** (per the explicit read-only constraint) —
  no `git blame` beyond `git log`/`git show` used for historical
  verification (read-only, non-mutating).
- **Full item-by-item detail (`kind`, `versions_that_exist`,
  `which_is_used`, `ref_count`, `migration_notes`, `risk` per item) is not
  duplicated here** — it lives in the scratchpad JSON, reproduced verbatim
  below for permanence.

## Raw data (scratchpad JSON, reproduced verbatim)

```json
{
  "zone": "tests/",
  "items": [
    {
      "identifier": "tests/test_wiki_metrics_v3.py",
      "file_line": "tests/test_wiki_metrics_v3.py:1",
      "kind": "test_file_name",
      "versions_that_exist": "Sole file testing the corpus-level metrics aggregator. A sibling `tests/test_wiki_metrics.py` (395 lines, tested the old mention-level M1/M2/P1/P2 protocol via `matching.py`) existed and was DELETED in the SAME commit (7e7ddfd) that last touched this file -- so there is no live older-version sibling and no dead file left behind. Confirmed via `git log --all --diff-filter=A -- tests/test_wiki_metrics_v3.py` -> first added in 0d89242 'feat(evaluation): protocol-v3 set-based document-level aggregator; retire sitelink-replay machinery', i.e. it was the *replacement* file, not one of several concurrently-maintained versions.",
      "which_is_used": "Yes -- collected by pytest (13 tests, verified via `pytest --collect-only`), part of the default `testpaths=[\"tests\"]` run.",
      "ref_count": 1,
      "proposal": "rename",
      "migration_notes": "Rename file to tests/test_wiki_metrics.py (the natural unsuffixed name, now free since the old file was deleted). MUST be coordinated with the src rename of `aggregate_corpus_v3` -> `aggregate_corpus` in src/palimpsest/terminology/evaluation/metrics.py (see coupling_map) -- both should land in the same commit per CLAUDE.md doc/contract-parity invariant. Also touches the module docstring (lines 1-5) which explicitly narrates the 'protocol-v3' framing and cites spec 2026-07-10-wiki-eval-experiment-v2.md Sec.4.5 / decision P9 -- keep the spec citation, drop the versioned framing only if src drops it.",
      "risk": "low -- pure rename, no behavior change; risk is purely coordination (breaks if src rename lands in a separate commit/PR without this one, or vice versa)."
    },
    {
      "identifier": "aggregate_corpus_v3 (imported from palimpsest.terminology.evaluation.metrics)",
      "file_line": "tests/test_wiki_metrics_v3.py:14-17,44,66,83,105,120,139,148,232,251,275",
      "kind": "src_import_of_versioned_identifier",
      "versions_that_exist": "`aggregate_corpus_v3` is the SOLE aggregator in metrics.py -- confirmed by its own module docstring: 'aggregate_corpus_v3 is the sole aggregator; ArticleUnits is its per-article input shape' (src/palimpsest/terminology/evaluation/metrics.py:14-15). No `aggregate_corpus`, `aggregate_corpus_v1`, or `aggregate_corpus_v2` exists anywhere in src (grep confirmed). The predecessor (mention-level protocol, used matching.py) was deleted wholesale in 7e7ddfd, not kept as a parallel version.",
      "which_is_used": "Yes -- imported and called 12x in this one test file; also exercised indirectly (through `cmd_report`) by tests/test_wiki_eval_runner.py.",
      "ref_count": 12,
      "proposal": "rename",
      "migration_notes": "This is a SRC identifier (src/palimpsest/terminology/evaluation/metrics.py:63), out of this zone's write scope, but every test call site must be updated in lockstep if src renames `aggregate_corpus_v3` -> `aggregate_corpus`. Affected test files: tests/test_wiki_metrics_v3.py (12 call sites + 1 import). tests/test_wiki_eval_runner.py does not import the symbol directly (it drives the CLI, `cmd_report`), so no import-line change needed there, only the `metrics[\"protocol\"] == \"v3\"` assertion is a separate, independent question (see the protocol-literal item below).",
      "risk": "medium -- a rename here is cheap textually (search/replace) but MUST be atomic with the src rename or the suite breaks; also touches the class docstring at line 2 of the test file which cites 'aggregate_corpus_v3' by name."
    },
    {
      "identifier": "render_html_v3 (imported from palimpsest.terminology.evaluation.report)",
      "file_line": "tests/test_wiki_report.py:11,54,63,68,74,80",
      "kind": "src_import_of_versioned_identifier",
      "versions_that_exist": "Sole HTML renderer in report.py. The file's own docstring says outright: 'The mention-level render_html this file used to test was retired along with evaluation.metrics's mention-level aggregator (spec Sec.7)' (tests/test_wiki_report.py:6-7) -- i.e. `render_html` (unsuffixed) existed before, was deleted, and `render_html_v3` is not one of several live variants, it is the only one left standing. No `render_html_v2` ever existed in git history for this file (git log shows only additions/refactors, no v2 predecessor).",
      "which_is_used": "Yes -- imported and called 5x, all 6 tests in the file collect and (per suite convention) are expected to pass under pytest.",
      "ref_count": 6,
      "proposal": "rename",
      "migration_notes": "Coupled to src rename `render_html_v3` -> `render_html` in src/palimpsest/terminology/evaluation/report.py:75 (and its private helper `_v3_cell_td` at report.py:65, used only internally by render_html_v3 -- not imported by tests, so no test-side change needed for that helper beyond the parent rename). Also update the file docstring (lines 1-7) which narrates 'protocol-v3 HTML report renderer' -- keep the historical note about the retired mention-level renderer (it's useful provenance), just drop the versioned identifier name if src drops it.",
      "risk": "low -- same shape as the aggregate_corpus_v3 item; coordinate the commit, not risky in isolation."
    },
    {
      "identifier": "test_cmd_report_writes_v3_metrics_with_named_and_term_classes",
      "file_line": "tests/test_wiki_eval_runner.py:2148",
      "kind": "test_function_name",
      "versions_that_exist": "Only version -- no _v1/_v2/unsuffixed sibling test of cmd_report's metrics output exists in this file.",
      "which_is_used": "Yes, collected and run.",
      "ref_count": 1,
      "proposal": "rename",
      "migration_notes": "Rename to test_cmd_report_writes_metrics_with_named_and_term_classes (drop '_v3' from the function name only; the body's internal assertion `metrics[\"protocol\"] == \"v3\"` is a separate data-literal question, see that item). Independent of the src metrics.py/report.py renames -- this is purely a test-name cleanup and can be done in the same PR without extra coordination risk beyond keeping pytest node IDs stable for anyone with saved `-k` filters (none found in CI config).",
      "risk": "low"
    },
    {
      "identifier": "test_render_html_v3_* (5 functions: contains_class_counters_and_meta, does_not_crash_on_zero_total_cell, is_valid_looking_html_fragment, surfaces_ambiguous_and_dropped_tier_counters, missing_meta_keys_render_placeholder_not_crash)",
      "file_line": "tests/test_wiki_report.py:53,62,67,73,79",
      "kind": "test_function_name",
      "versions_that_exist": "Only version; direct 1:1 naming mirror of the `render_html_v3` import above -- no `test_render_html_*` unsuffixed sibling exists (the file replaced the mention-level render_html tests wholesale, not alongside them).",
      "which_is_used": "Yes, all 5 collected and run.",
      "ref_count": 5,
      "proposal": "rename",
      "migration_notes": "Rename in lockstep with the `render_html_v3` -> `render_html` src+import rename above (same file, same PR): test_render_html_contains_class_counters_and_meta, etc. Purely mechanical sed-style rename once the import-level decision is made -- do NOT rename the test functions independently of the import, that would leave a confusing 'test_render_html_x calls render_html_v3()' mismatch.",
      "risk": "low"
    },
    {
      "identifier": "metrics[\"protocol\"] == \"v3\" / result[\"protocol\"] == \"v3\" / \"protocol\": \"v3\" (data-contract literal, not a code identifier)",
      "file_line": "tests/test_wiki_eval_runner.py:2180; tests/test_wiki_metrics_v3.py:149; tests/test_wiki_report.py:28",
      "kind": "asserted_data_value",
      "versions_that_exist": "Single value in current use -- no code path ever writes 'protocol': 'v1' or 'v2'; the field is written once in src/palimpsest/terminology/evaluation/metrics.py:149 as a literal `\"protocol\": \"v3\"` inside the result dict `aggregate_corpus_v3` returns, and echoed unmodified by cmd_report into the persisted metrics.json.",
      "which_is_used": "Yes, all 3 assertions run.",
      "ref_count": 3,
      "proposal": "keep (flagged, not a rename target in this zone)",
      "migration_notes": "This is materially different from the function-name items above: it is a value written into ON-DISK report artifacts (metrics.json files under reports/terminology/wiki-eval/**), including the two regression-fixture pred.jsonl runs this same test file reads back (RUN_A/RUN_B, see next item). If a later report format changes again, having a `protocol` field to distinguish old on-disk reports from new ones is exactly the kind of schema/format versioning the owner's rule is meant to exempt (data provenance, not dead code). Renaming `aggregate_corpus_v3`/`render_html_v3` (the Python identifiers) does NOT obligate changing this string value -- that is a src/data-contract decision belonging to the API/data contract doc (docs/superpowers/specs/2026-06-30-demo-contracts.md) and to whoever owns src/palimpsest/terminology/evaluation/metrics.py, not to this tests/ zone. Flagging so the src-zone/contract-zone inventory sees the coupling; tests only need to keep asserting whatever literal src decides on.",
      "risk": "n/a (not proposing a change here) -- listed to prevent an uncoordinated src-side rename of the JSON field from silently breaking these 3 assertions."
    },
    {
      "identifier": "chrono_p31_version == \"chrono_p31_v1\" (CHRONO_P31_VERSION constant, imported indirectly via wiki_gt.build_gt output)",
      "file_line": "tests/test_wiki_gt.py:190",
      "kind": "asserted_data_value / provenance_constant",
      "versions_that_exist": "Single version (`chrono_p31_v1`) defined once at src/palimpsest/terminology/evaluation/wiki_gt.py:37 as `CHRONO_P31_VERSION = \"chrono_p31_v1\"`, stamped into every ground-truth record written by build_gt for reproducibility/provenance (so that GT files built with a future differently-tuned chrono-P31 classification ruleset can be told apart from ones built with this ruleset).",
      "which_is_used": "Yes, asserted in test_build_gt_writes_one_record_per_article_sorted_by_title.",
      "ref_count": 1,
      "proposal": "keep",
      "migration_notes": "This is a deliberate provenance/schema-version tag on generated data (analogous to a schema_version field or content hash), not a duplicate-implementation version suffix -- it exists precisely so that historically-generated data/eval/wiki/gt*.jsonl files remain distinguishable if the chrono-P31 ruleset changes later. Recommend explicitly exempting this pattern (and CHRONO_P31_VERSION/chrono_p31_hash generally) from the versioning cleanup rather than treating '_v1' as a violation -- this is the textbook 'genuinely used, meaningfully distinct version tag' the owner's rule carves out, just for data provenance rather than concurrently-running code paths.",
      "risk": "n/a -- no change proposed."
    },
    {
      "identifier": "RUN_A / RUN_B regression-fixture paths (reports/terminology/wiki-eval/google--gemini-3.1-flash-lite--provider-9/111/2026-07-05T23-06-38Z/pred.jsonl and .../deepseek--deepseek-v4-flash--provider-9/111/2026-07-05T23-35-52Z/pred.jsonl)",
      "file_line": "tests/test_wiki_metrics_v3.py:23-24,232-275 (test_regression_anchor_run_a_gemini, test_regression_anchor_run_b_deepseek, test_gold_named_plus_term_invariant)",
      "kind": "versioned_fixture_data_reference",
      "versions_that_exist": "These are real, git-tracked (`git ls-files` confirmed) protocol-v3-format run outputs used as anchor/regression fixtures, not multiple versions of the same artifact -- each path is timestamp+model-identified, not semver-suffixed, and both are large (3.1-3.9MB) real pred.jsonl files checked into reports/terminology/wiki-eval/.",
      "which_is_used": "Yes -- both files exist on disk and are read by 3 tests in this file, verified present.",
      "ref_count": 2,
      "proposal": "keep",
      "migration_notes": "Not a naming-cleanup target -- these are run artifacts (timestamped report directories), not code/version-suffixed fixtures. They are, however, tightly coupled to the current 'protocol v3' pred.jsonl SHAPE (index/surface/qid/span_len tuples, resolved_by field) -- if the src aggregator is renamed/reshaped in a future protocol change, these regression fixtures would need regenerating, which is a much bigger and separate concern than the identifier renames in this inventory. Flagging only so a future protocol change doesn't silently leave these regression anchors testing a stale shape.",
      "risk": "n/a -- no rename proposed; noted as a dependency for future protocol changes, not for this cleanup pass."
    }
  ],
  "summary": {
    "n_items": 8,
    "n_rename": 4,
    "n_keep": 4,
    "n_delete": 0
  },
  "coupling_map": {
    "aggregate_corpus_v3 (src/palimpsest/terminology/evaluation/metrics.py:63)": [
      "tests/test_wiki_metrics_v3.py"
    ],
    "UNDERPOWERED_THRESHOLD (src/palimpsest/terminology/evaluation/metrics.py:28)": [
      "tests/test_wiki_metrics_v3.py"
    ],
    "_cell (src/palimpsest/terminology/evaluation/metrics.py:31)": [
      "tests/test_wiki_metrics_v3.py"
    ],
    "render_html_v3 (src/palimpsest/terminology/evaluation/report.py:75)": [
      "tests/test_wiki_report.py"
    ],
    "_v3_cell_td (src/palimpsest/terminology/evaluation/report.py:65)": [
      "tests/test_wiki_report.py (not imported directly; exercised only indirectly through render_html_v3)"
    ],
    "methodology_draft (src/palimpsest/terminology/evaluation/report.py:124)": [
      "tests/test_wiki_report.py"
    ],
    "\"protocol\": \"v3\" literal (src/palimpsest/terminology/evaluation/metrics.py:149)": [
      "tests/test_wiki_metrics_v3.py",
      "tests/test_wiki_report.py",
      "tests/test_wiki_eval_runner.py"
    ],
    "CHRONO_P31_VERSION = \"chrono_p31_v1\" (src/palimpsest/terminology/evaluation/wiki_gt.py:37)": [
      "tests/test_wiki_gt.py"
    ]
  },
  "open_questions": [
    "Rename of aggregate_corpus_v3/render_html_v3 (and the 4 test-side items proposing 'rename') is a SRC decision this tests/ zone cannot make unilaterally -- surfacing here for the src-zone inventory/orchestrator to confirm before any test file is touched; per CLAUDE.md this must land as one atomic commit (src rename + test rename + doc-parity).",
    "The 'protocol': 'v3' JSON literal (metrics.py:149) is a DIFFERENT kind of versioning than the Python identifiers -- it is data-format provenance for persisted report artifacts. Recommend the src-zone/contract-zone explicitly decide whether to keep this literal even if the Python function names drop their '_v3' suffix (keeping it seems right: it lets old on-disk reports.json/metrics.json be told apart from a future format change, independent of what the generating function is called). Not resolved here since it is out of tests/ zone's authority.",
    "data/eval/wiki/ contains 3 versioned data files (gt_v2_sub20.jsonl, selection_v2.json, titles_v2.txt) that are NOT referenced by anything in tests/ (grep-confirmed zero hits) -- these belong to a data/ or scripts/ zone inventory, not this one; flagging existence only so they aren't missed by the overall sweep.",
    "test_c5_loop_integrity.py and test_evaluate_retry_c1.py use 'C5'/'C1' suffixes -- investigated and these are aspect-review IDs (from the /verify-pr review-aspects catalog, e.g. 'C5 aspect review' in the docstring) identifying WHICH review pass added the file, not version numbers of the same artifact; each file's docstring explicitly cross-references the others as covering complementary (non-overlapping) gaps, not superseded versions. Judged out of scope for this cleanup rule and NOT included as an item -- noting the reasoning here in case the owner disagrees and wants these folded into their sibling files (test_evaluate_retry.py, test_issue_dedup.py) instead of cleaned up as 'versions'.",
    "test_aggregate_prev.py's 'prev' was checked and is NOT a version suffix -- it tests the API's aggregatePrev field (previous-aggregate-score delta feature), a real product feature name, not a superseded test version. Excluded from items for the same transparency reason as above.",
    "No dead/orphaned test files were found in tests/ -- all 626 tests collect cleanly under pytest (`.venv/bin/python -m pytest tests/ --collect-only -q`), and the one genuinely retired predecessor (tests/test_wiki_metrics.py, mention-level protocol, 395 lines) plus tests/test_wiki_matching.py (matching.py module tests) were already fully deleted in commit 7e7ddfd rather than left as dead files -- so there is nothing to propose for delete_dead in this zone."
  ]
}
```
