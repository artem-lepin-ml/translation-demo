# NER prompt v2.2 — mechanical application report

## Scope

Mechanical, verbatim application of orchestrator-authored edits to
`NER_SYSTEM_PROMPT` (`src/palimpsest/terminology/extract.py`), encoding the
2026-07-10 owner hand-labeling ruling on the 64-miss review: materials
(«латунь»-like), language/culture adjectives («хеттскому»,
«индоиранские»-like) and specialized realia nouns («геммы», «рельефы»,
«дань»-like) ARE terms; modern brands/websites and natural-science
vocabulary are OUT of scope. No prompt design/analysis performed by this
agent — text supplied verbatim by the orchestrator (Fable), same protocol
as reference commit `6039325`.

## Files changed

- `src/palimpsest/terminology/extract.py` — `NER_SYSTEM_PROMPT`: added
  `language` and `realia` categories to `<categories>`; added a
  modern-entity/natural-science exclusion bullet to `<do_not_extract>`;
  added two rules bullets (lowercase realia-are-terms, adjective-named
  language extraction) to `## Rules`; replaced the second `<example>`
  block (Дарий) with an extended version covering `подать`, `электрумом`,
  `арамейском языке`.
- `docs/paper/sections/appendix-prompt-ner.tex` — synced the embedded
  figure verbatim to the same four edits; `\caption`/`\label` untouched.
- `docs/superpowers/specs/2026-07-10-wiki-eval-experiment-v2.md` §3.1 —
  added a second `[AMENDED 2026-07-10 (2), …]` blockquote note directly
  under the existing amendment note; the pilot's original prompt snapshot
  in the fenced block below is left untouched (code remains SSOT).

## Decisions & rationale

- **Verbatim application, no rewording.** Per task instructions this is a
  mechanical task; the orchestrator authored the exact text. My only
  active decisions were placement precision (matching existing anchor
  strings exactly) and the doc-parity verification step below.
- **`.tex` sync verified programmatically**, not by eye: extracted both the
  Python triple-quoted string and the LaTeX `\begin{prompt}"..."\end{prompt}`
  block and diffed them character-for-character — exact match confirmed
  (see Run artifacts).
- **Grep sweep for other true copies**: re-ran the same class of search the
  reference commit used. 32 files matched fragments of the changed text,
  but all are either (a) the two files already synced above, (b)
  `docs/superpowers/specs/2026-07-01-terminology-extract-design.md` — a
  frozen v2 historical design doc that was untouched even by the reference
  commit (single commit in its git log, the initial import; not a live
  SSOT-tracked copy), or (c) unrelated data: wiki-eval `pred.jsonl`/
  `traces.jsonl` run artifacts, `data/seed/*.jsonl` gold data, and
  `external/gse-translation/prompts/**` (a different, unrelated scoring
  pipeline). Confirmed: still true that only the `.tex` file needs sync,
  matching the task's expectation from the prior round.

## Open questions

None — this was a fully specified mechanical task with no design
decisions left to this agent.

## NOT done (explicit)

- No LLM API calls were made (per task authorization — no live NER re-run
  against the new prompt, no re-scoring of the 64-miss cases against v2.2).
- No new eval/pilot run was triggered to measure the effect of the v2.2
  prompt changes on the wiki-eval miss rate — that is a separate
  `experiment-runner`-gated activity, out of scope for this mechanical
  task.
- Did not re-open or re-review the original 64-miss case list; the
  category/rule wording was authored by the orchestrator from the owner's
  hand-labeling, not derived independently by this agent.
