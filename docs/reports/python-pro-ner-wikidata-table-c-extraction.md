# Report — NER + Wikidata grounding numbers extraction (paper Table C)

## Scope

Read-only extraction task on branch `claude/ner-translation-config-b0ozsc`: pull every number
needed for the paper's Table C (recall in 3 matching modes with Wilson CI, 3 precision readings,
recall decomposition, gold-filtering tiers, named/term split, sitelink-included vs sitelink-excluded
variants, exact denominators, qwen3.7-plus status) for `gemini-3.1-flash-lite`, `deepseek-v4-flash`,
`qwen3.7-plus`, with file-level provenance for every figure. No code, docs, or data were edited;
`reports/bouquet/` (judge-run agents' working area) was not touched.

## Files changed

None. This was a read-only extraction; no repo files were modified. This report is the only file
written, per the mandatory reporting protocol.

## Decisions & rationale

- **Sourced numbers only from committed run artifacts and drafts**, never recomputed from
  `pred.jsonl`/`gt.jsonl` myself — the task asked for extraction + provenance, not re-derivation.
  Cross-checks (e.g. reading `metrics.json`'s `recall`/`precision`/`slices` blocks directly rather
  than trusting only prose tables in `report-ru-v3.md`) were done to catch drift between the
  narrative drafts and the underlying `metrics.json`, which did surface one real discrepancy
  (see below) — worth flagging rather than silently reconciling.
- **Flagged, did not resolve, the named/term recall discrepancy.** The paper's cited named/term
  R_doc split (gemini 0.828/0.414, deepseek 0.733/0.376) does **not** match `metrics.json`'s own
  `slices.type` field (gemini 0.813/0.343, deepseek 0.704/0.309) — `drafts/recall-tiers-analysis.md`
  itself documents this as an index-keyed-slicing artifact and recommends the corrected
  per-article `match_m3` numbers, which are the ones actually used in the paper drafts. I reported
  both, labeled which is which, rather than picking one as "the" number.
- **Traced the qwen 44/100 checkpoint across branches rather than assuming it was in this
  checkout.** `git log`/`git show`/`git merge-base --is-ancestor` against commit `963b05b` on
  `feat/merge-wikidata-eval-branches` confirmed the 44/100 checkpoint exists there but is not an
  ancestor of the current branch — the current checkout only has the 13/100 prefix. Reported this
  precisely instead of conflating "exists somewhere in the repo history" with "exists on this
  branch."
- **Did not fabricate a PR #14 confirmation.** No `gh` CLI was available in this sandbox; I
  reported the branch/commit identity I could verify and explicitly flagged the PR number as
  unconfirmed by me, rather than presenting the task prompt's PR-14 claim as independently verified.
- **Surfaced the paper-state.md vs paper-section-en-final.md tension on "which variant to cite"**
  instead of resolving it unilaterally: the 07-06 draft's printed Table 1 still shows original
  (sitelink-included) numbers with clean numbers only in prose, while the more recent (07-08)
  `docs/paper/paper-state.md` living doc already records the clean numbers as Table C's per-model
  figures. Recommended the clean numbers per the explicit "should set `use_sitelink=False`"
  guidance in `docs/stages/wiki-eval.md`, but called out the live inconsistency between the two
  docs for the orchestrator/owner to settle rather than silently picking a side.

## Open questions

- Which document is authoritative for Table C's headline numbers going forward:
  `drafts/paper-section-en-final.md` Table 1 (original numbers) or `docs/paper/paper-state.md`
  (clean numbers)? Both are currently committed and disagree.
- Should the named/term split cited in the paper be re-labeled to make clear it is NOT the same
  computation as `metrics.json`'s `slices.type` field, to avoid future confusion for anyone
  reading `metrics.json` directly?
- Is there a plan to compute Wilson CIs for the gold-filtering tiers (R_clean/R_term) and for the
  corrected per-article named/term recall, or are point estimates considered sufficient for
  publication?

## NOT done

- Did not recompute or re-verify any number from raw `pred.jsonl`/`gt.jsonl` — all figures are as
  read from committed `metrics.json`, `sitelink_replay/*.json`, and the analysis drafts.
- Did not resolve the named/term count discrepancy (5312/2647 vs 5309/2650) between
  `recall-tiers-analysis.md` and `metrics.json` — flagged only.
- Did not confirm "PR #14" via GitHub (no `gh` CLI, no network PR lookup attempted).
- Did not compute a sitelink-clean variant for R_strict (M1) or for the R_clean (T1) tier — these
  simply don't exist in the repo; only R_all/T0 and R_term/T2 were replayed by the committed script.
- Did not locate or re-run the script behind the extraction-coverage × grounding-accuracy
  decomposition (0.763/0.632 coverage, 0.814/0.815 accuracy) — only narrative provenance found.
- Did not check out or inspect `feat/merge-wikidata-eval-branches` beyond read-only `git show`
  (no working-tree checkout, per read-only task scope).

## Extracted numbers

Shared denominators for both finished models: **7,959 gold mentions, 3,868 unique QIDs, 100
articles.** Source: `docs/experiments/2026-07-05-model-comparison/drafts/recall-tiers-analysis.md`
§1 ("Headline reproduction"), cross-checked against `meta.n_gt_tuples: 7959` in both models'
`metrics.json`.

### gemini-3.1-flash-lite (provider-9)

Run dir: `reports/terminology/wiki-eval/google--gemini-3.1-flash-lite--provider-9/111/2026-07-05T23-06-38Z/`
(`metrics.json` is the source for every recall/precision figure in this block unless noted).

**Recall — original (sitelink-included) runs:**

| Mode | Value | 95% CI | matched/total |
|---|---|---|---|
| R_strict (M1) | 0.6096 | [0.5989–0.6203] | 4852/7959 |
| R_span (M2) | 0.6296 | [0.6189–0.6401] | 5011/7959 |
| R_doc (M3) | **0.6902** | [0.6799–0.7002] | 5493/7959 |

**Precision:**

| Reading | Value | 95% CI | matched/total |
|---|---|---|---|
| P_mention (P1) | 0.3001 | [0.2932–0.3071] | 5014/16709 |
| P_type (P2) | 0.4513 | [0.4412–0.4614] | 4219/9349 |
| P_label (`p3_ex`, **finalized**, excludes deterministic exact-label path) | **0.5256** | [0.5159–0.5352] | 5399/10272 |

**Recall decomposition** (`SESSION-LOG.md:56`; `drafts/report-ru-v3.md` §3.3 Table 3;
`drafts/paper-section-en-final.md:127-138` — no underlying script/raw-data file found, narrative
numbers only):
- Extraction coverage: **0.763** (6070/7959)
- Grounding accuracy (covered positions): **0.814**
  - exact-label path: 0.921 (n=2453)
  - judge path: 0.847 (n=3165)

**Gold-filtering tiers (R_doc)** — `drafts/recall-tiers-analysis.md` §3:

| Tier | Gold mentions | Unique QIDs | R_doc |
|---|---|---|---|
| R_all (T0, raw) | 7959 | 3868 | 0.690 |
| R_clean (T1) | 7796 | 3760 | 0.704 |
| R_term (T2) | 7174 | 3550 | **0.741** |

**Named/term split — two non-matching sources, both reported (see Decisions & rationale):**

1. *Corrected per-article `match_m3`* (`drafts/recall-tiers-analysis.md` §1/§3 — this is what
   the paper drafts actually cite): named baseline 5312 / term baseline 2647 mentions.
   | Tier | named R_doc | term R_doc (n) |
   |---|---|---|
   | R_all | 0.828 | 0.414 (n=2647) |
   | R_clean | 0.834 | 0.434 (n=2522) |
   | R_term | 0.841 | **0.474** (n=1953) |
2. *Raw `metrics.json` `slices.type`* (index-keyed, under-counts M3 per
   `recall-tiers-analysis.md`'s own note — **not** what the paper cites, included for completeness):
   named 0.8130 [0.8022–0.8232] (4316/5309); term 0.3426 [0.3248–0.3609] (908/2650).

**Sitelink-included (original) vs sitelink-excluded (clean) variants** —
`docs/experiments/2026-07-05-model-comparison/drafts/sitelink_replay/gemini.json` +
`drafts/sitelink-contamination.md` §3:

| Metric | Original | Clean (sitelink off) | Δ (pp) | Recall units lost |
|---|---|---|---|---|
| R_doc (T0, all 7959) | 0.6902 (5493/7959) | **0.6840** (5444/7959) | −0.62 | 49 |
| R_span (T0) | 0.6296 (5011/7959) | 0.6222 (4952/7959) | −0.74 | 59 |
| R_doc (R_term / T2, 7174) | 0.7411 (5317/7174) | 0.7345 (5269/7174) | −0.66 | 48 |
| R_span (R_term / T2) | 0.6880 (4936/7174) | 0.6798 (4877/7174) | −0.82 | 59 |

No sitelink-clean variant exists for R_strict (M1) or for the R_clean tier (T1) — only T0 and T2
were replayed. Sitelink rung supplied 1.22% of grounded predictions (204/16,709), matching GT at
60.3%.

### deepseek-v4-flash (provider-9)

Run dir: `reports/terminology/wiki-eval/deepseek--deepseek-v4-flash--provider-9/111/2026-07-05T23-35-52Z/`.

**Recall — original (sitelink-included):**

| Mode | Value | 95% CI | matched/total |
|---|---|---|---|
| R_strict (M1) | 0.5092 | [0.4982–0.5202] | 4053/7959 |
| R_span (M2) | 0.5236 | [0.5126–0.5345] | 4167/7959 |
| R_doc (M3) | **0.6144** | [0.6037–0.6250] | 4890/7959 |

**Precision:**

| Reading | Value | 95% CI | matched/total |
|---|---|---|---|
| P_mention (P1) | 0.3048 | [0.2972–0.3126] | 4170/13680 |
| P_type (P2) | 0.4584 | [0.4474–0.4694] | 3600/7854 |
| P_label (`p3_ex`, **finalized**) | **0.5302** | [0.5195–0.5408] | 4448/8390 |

**Recall decomposition** (same provenance/caveat as gemini above):
- Extraction coverage: **0.632** (5031/7959)
- Grounding accuracy (covered positions): **0.815**
  - exact-label path: 0.929 (n=2028)
  - judge path: 0.862 (n=2571)

**Gold-filtering tiers (R_doc):**

| Tier | Gold mentions | Unique QIDs | R_doc |
|---|---|---|---|
| R_all (T0) | 7959 | 3868 | 0.614 |
| R_clean (T1) | 7796 | 3760 | 0.627 |
| R_term (T2) | 7174 | 3550 | **0.663** |

**Named/term split — two non-matching sources:**

1. *Corrected per-article `match_m3`* (paper-cited):
   | Tier | named R_doc | term R_doc |
   |---|---|---|
   | R_all | 0.733 | 0.376 |
   | R_clean | 0.738 | 0.395 |
   | R_term | 0.745 | **0.444** |
2. *Raw `metrics.json` `slices.type`* (not paper-cited): named 0.7041 [0.6917–0.7162]
   (3738/5309); term 0.3087 [0.2914–0.3265] (818/2650).

**Sitelink-included vs sitelink-excluded (clean):**

| Metric | Original | Clean | Δ (pp) | Recall units lost |
|---|---|---|---|---|
| R_doc (T0, all 7959) | 0.6144 (4890/7959) | **0.6092** (4849/7959) | −0.52 | 41 |
| R_span (T0) | 0.5236 (4167/7959) | 0.5187 (4128/7959) | −0.49 | 39 |
| R_doc (R_term / T2, 7174) | 0.6631 (4757/7174) | 0.6574 (4716/7174) | −0.57 | 41 |
| R_span (R_term / T2) | 0.5722 (4105/7174) | 0.5668 (4066/7174) | −0.54 | 39 |

Sitelink rung: 1.04% of grounded predictions (142/13,680), matching GT at 52.1%. No R_strict or
R_clean(T1) clean variant exists, same as gemini.

**Deepseek 4.1% coverage caveat**: `meta.n_failed_paragraphs = 108` of `meta.n_paragraphs = 2644`
= 4.09% (≈4.1% as documented), `meta.n_failed_judge_calls = 238`. The "+~0.02 recall correction if
these paragraphs had succeeded" is a prose estimate in `drafts/report-ru-v3.md` §3.4 /
`drafts/paper-section-en-final.md` §6 — not a computed field, no recomputed corrected R_doc exists
in the repo.

### qwen3.7-plus — status (nothing citable)

- **Original run** invalidated:
  `reports/terminology/wiki-eval/qwen--qwen3.7-plus--provider-8/111/2026-07-06T09-55-11Z/metrics.json`
  — forensic R_doc (M3) = 0.1637 (1303/7959). Cause: progress/pred checkpoint desync under a
  provider 429-storm (`docs/PROBLEMS.md:20-66`); real prediction coverage only 65/100 articles;
  735 gold mentions affected by `judge_unavailable` groundings (raw `pred.jsonl` rows with
  `resolved_by=judge_unavailable`: 2929) vs 12 for gemini on the same config. Not usable for
  Table C under any variant.
- **Clean (sitelink-off) re-run**, in progress, not finished:
  - Current branch (`claude/ner-translation-config-b0ozsc`) has only a **13/100-article**
    checkpoint prefix at
    `.../qwen--qwen3.7-plus--provider-8/111/2026-07-06T18-29-18Z/{pred.partial.jsonl,progress.jsonl}`
    — no `metrics.json`, no `pred.jsonl`.
  - A **44/100** extension of the same checkpoint exists on branch
    `feat/merge-wikidata-eval-branches` (commit `963b05b`, merge-forward of
    `origin/claude/ner-wikidata-grounding-eval-bqa4l2`) — confirmed via
    `git show 963b05b:.../progress.jsonl` (44 lines, last article "Кария"). Confirmed via
    `git merge-base --is-ancestor 963b05b HEAD` that this commit is **not** an ancestor of the
    current branch, i.e. it is not present in this checkout.
  - The "PR #14" identity given in the task prompt was **not independently verified** — no `gh`
    CLI in this sandbox, no network PR lookup performed.
  - **Bottom line: no finished/citable qwen3.7-plus numbers exist on any branch inspected.**
    `docs/paper/paper-state.md:56-58` and `docs/stages/wiki-eval.md` §Status both list it as
    re-run-queued/in-progress, consistent with this finding.

### Which variant the paper should cite

`docs/stages/wiki-eval.md` (Subtleties, ~line 71) explicitly recommends `use_sitelink=False`
going forward (annotation-mechanism leakage). `drafts/paper-section-en-final.md`'s own
"Evaluation integrity" paragraph says the same but its **printed Table 1 still shows the original
numbers** (0.690/0.614) with clean numbers only in prose. The more recent (2026-07-08)
`docs/paper/paper-state.md` living doc already records Table C's per-model entries using the
**clean** figures directly (gemini 0.684, deepseek 0.609), with no original-number caveat. Net
read: **cite the clean/sitelink-excluded numbers (gemini 0.684, deepseek 0.609)** — this matches
both the explicit protocol recommendation and the most recently updated paper-tracking doc — but
the two committed docs currently disagree on the printed Table 1, which needs an explicit
reconciliation pass, not a silent pick.

### Compact summary table (headline figures only)

| Model | R_doc (orig.) | R_doc (clean) | R_span (orig.) | R_strict (orig.) | P_mention | P_type | P_label | Coverage | Grounding acc. |
|---|---|---|---|---|---|---|---|---|---|
| gemini-3.1-flash-lite | 0.690 [.680–.700] | 0.684 | 0.630 | 0.610 | 0.300 | 0.451 | 0.526 | 0.763 | 0.814 |
| deepseek-v4-flash | 0.614 [.604–.625] | 0.609 | 0.524 | 0.509 | 0.305 | 0.458 | 0.530 | 0.632 | 0.815 |
| qwen3.7-plus | — invalidated — | — not finished — | — | — | — | — | — | — | — |
