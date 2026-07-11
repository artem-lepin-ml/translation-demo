# prompt-engineer: NER category field + prompt freeze

## Scope

Add a mandatory `category` field to the WikiHist NER extraction (prompt +
output schema + parsing + tests + doc-parity), then mark
`NER_SYSTEM_PROMPT` FROZEN as the last edit before the full evaluation runs.
Branch: `claude/ner-translation-config-b0ozsc` (not switched, per constraint).
Write scope was explicitly limited to: `src/palimpsest/terminology/extract.py`,
its tests, `docs/paper/sections/appendix-prompt-ner.tex`,
`docs/stages/wiki-eval.md` (schema section only), and a spec amendment note.

## Files changed

- `src/palimpsest/terminology/extract.py` — module docstring rewritten;
  FROZEN comment added above `NER_SYSTEM_PROMPT`; prompt body edited
  (new `category` Rules bullet, both good-example JSON payloads carry
  `category`, Output-format line updated to `{surface, lemma, category}`);
  new `NER_CATEGORIES` tuple + `_normalize_category` helper;
  `parse_surfaces` now emits `category` (normalized) and `category_raw`
  (only when a present value was unknown); `validate_surfaces` fixed to
  pass `category`/`category_raw` through instead of silently dropping them
  (this was the one real "strict-validates-the-shape" consumer found);
  `mentions_from_surfaces` docstring updated to drop the stale "no
  category" claim.
- `tests/test_terminology.py` — updated existing parse/validate assertions
  for the new field; added `test_parse_surfaces_valid_category_passes`,
  `test_parse_surfaces_unknown_category_normalizes_with_raw_preserved`,
  `test_parse_surfaces_missing_category_normalizes_to_other_no_raw`,
  `test_parse_surfaces_never_rejects_over_category_value`,
  `test_validate_surfaces_passes_category_through_untouched`,
  `test_ner_system_prompt_requires_category_and_is_frozen`; strengthened
  `test_llm_surfaces_validates_against_source` to assert category
  passthrough.
- `docs/paper/sections/appendix-prompt-ner.tex` — regenerated to the frozen
  prompt text verbatim (byte-for-byte match with `NER_SYSTEM_PROMPT`,
  verified programmatically), updated integration comment and caption.
- `docs/stages/wiki-eval.md` — extraction schema bullet rewritten:
  `{surface, lemma}` / "no category" → `{surface, lemma, category}` +
  normalization rule + FROZEN note.
- `docs/superpowers/specs/2026-07-10-wiki-eval-experiment-v2.md` — appended
  amendment note (3) to §3.1's existing 2-note log, in the same style,
  documenting the category re-addition, the freeze, and that it supersedes
  §2 Р6 / §4.4 item 10 (both left unmodified as historical record).

Commit `8bbafcf` ("feat(terminology): add category field to NER extraction
and freeze prompt"), staged exactly these 5 files, pushed to
`claude/ner-translation-config-b0ozsc` on the first attempt. No PR opened
(per instructions).

## Decisions & rationale

**Spec conflict, surfaced not silently overridden.** Reading `extract.py`
before editing turned up a real conflict: the module docstring and the
project's own spec (`2026-07-10-wiki-eval-experiment-v2.md` §2, decision
Р6: "category removed from the output schema, not to be revisited," made
the same day at commit `421c99d` 07:40 UTC, spec still `status: draft under
owner review`) both say the opposite of this task. I did not treat the code
comment as authoritative on its own — a stray comment could be stale or
wrong — but the spec is the project's actual decision record, so this was a
genuine tension between my task and the canonical spec, not a prompt
injection. The task's own instruction #7 ("append a dated amendment note …
in the same style as its existing amendment notes") is exactly the
project's sanctioned mechanism for revising a "final" decision without
rewriting history, so I used it: amendment (3) documents the reversal and
its rationale (owner needs per-category error distribution for the paper's
appendix) without touching the Р6 row or §4.4 item 10 text themselves,
consistent with both my narrow write scope and the "append, don't
silently rewrite" doc convention already used by amendments (1) and (2).

**Canonical category tokens = the prompt's own labels.** The 14 tokens
(`person, place, people, title, social, institution, dynasty, culture,
language, realia, event, deity, work, religion`) were extracted verbatim
from the `<categories>` block already in the prompt — no categories were
invented. They're already snake_case-compatible single words, so no
separate token-mapping layer was needed; the prompt text says "use the
token before the dash."

**`validate_surfaces` was the real strict-shape bug.** Task step 4 asked me
to verify consumers pass the extra key through untouched and fix only what
strict-validates. `grounding/label_first.py` and `pipeline.py` only touch
`TermMention` attributes and were already fine. `validate_surfaces`,
however, reconstructed each dict as `{"surface": s, "lemma": ...}`,
silently dropping `category`/`category_raw` even though `mentions_from_surfaces`
downstream already reads `item.get("category")`. Fixed by conditionally
copying both keys through when present, without re-validating the category
value itself (normalization only happens once, at `parse_surfaces` time).

**No counter added for missing-category.** The task's ask was conditional
("log counter if there's an existing counters pattern"). The terminology
module has no `logging` usage anywhere, and the only counter-like
precedent (`validate_surfaces`'s `dropped: int` return) can't be extended
without changing `parse_surfaces`'s public return signature — which would
break `scripts/term_pipeline.py` and `scripts/wiki_eval.py` callers outside
my write scope. Since no compatible pattern exists, I implemented the
normalization behavior fully (tested) but added no counter, rather than
introduce a speculative one-off abstraction.

**Verified concurrent-agent isolation.** Before committing, `git status`
confirmed a concurrent agent's uncommitted work in `data/eval/wiki/*`
(exactly the disjoint lane flagged in the task). 3 pre-existing failures in
`tests/test_wiki_metrics_v3.py` were reproduced identically with my changes
stashed out, confirming they're unrelated to this change; staged and
committed exactly the 5 allowed files (never `-A`).

## Open questions

- Should `docs/stages/terminology.md`'s Interface section (still narrates
  "no category field," Р6) be updated in a follow-up doc-parity pass? It's
  a direct doc-parity gap created by this change but was outside my write
  scope.
- Should the Glossary/TermPopover category pill behavior (now populated
  again once live extraction runs with this prompt) be re-reviewed by the
  frontend/product owner, given it was deliberately emptied under Р6 as an
  accepted demo consequence?
- Does the owner want the Р6 row in §2 and §4.4 item 10 of the spec
  formally struck through/rewritten, or is the appended amendment note (3)
  sufficient as the permanent record?

## NOT done (explicit)

- `docs/stages/terminology.md` — not updated (out of write scope), now
  stale on the category-field narrative.
- `src/palimpsest/terminology/base.py`'s `Extractor` type-alias comment
  (`# source text -> [{surface, lemma}]`) — not updated; file self-declares
  "Frozen shared types" and is outside write scope.
- No counter/logging added for the missing-category normalization case
  (see rationale above).
- The 3 pre-existing `tests/test_wiki_metrics_v3.py` failures were not
  fixed — they belong to the concurrent agent's `data/eval/wiki/*` lane.
- No PR opened (per instructions, push only).
