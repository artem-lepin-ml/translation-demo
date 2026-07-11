# Task Report: NER Translation Config LaTeX Appendix Files

## Scope

Mechanical file-creation task: extract two Python string constants verbatim (byte-for-byte fidelity, no paraphrasing or reformatting) and embed them in LaTeX appendix figure files. Additionally, update comment paths in two existing LaTeX files.

**Deliverables:**
1. Create `docs/paper/sections/appendix-prompt-ner.tex` with `NER_SYSTEM_PROMPT` from `src/palimpsest/terminology/extract.py`
2. Create `docs/paper/sections/appendix-prompt-judge.tex` with `DEFAULT_GROUNDING_JUDGE_SYSTEM_PROMPT` and `DEFAULT_GROUNDING_JUDGE_USER_TEMPLATE` from `src/palimpsest/terminology/grounding/label_first.py`
3. Fix comment paths in `docs/paper/sections/eval-metrics-terminology.tex` (replace `drafts/tier_assignment.json` with `data/eval/wiki/tier_assignment.json (moved 2026-07-10)`)
4. Fix and augment comment in `docs/paper/sections/table-c-grounding.tex` (append aggregator regression anchors reference)

No commits to be created.

## Files Changed

### Created

- **`docs/paper/sections/appendix-prompt-ner.tex`** (88 lines, 3691-byte prompt payload)
  - Structure: comment block + `\begin{figure*}[ht!]...\end{figure*}` wrapper with `\begin{prompt}...\end{prompt}` environment
  - Prompt text: `NER_SYSTEM_PROMPT` from extract.py, lines 36–107 (unmodified, includes Russian text, « » guillemets, → arrows)
  - Includes integration note for placement in `\section{LLM prompts}` and caption directing to Appendix~\ref{appx:ner-prompt}

- **`docs/paper/sections/appendix-prompt-judge.tex`** (34 lines, 514-byte total prompt payload)
  - Structure: comment block + `\begin{figure}[ht!]...\end{figure}` wrapper with two `\begin{prompt}...\end{prompt}` environments (system + user template)
  - Prompt 1: `DEFAULT_GROUNDING_JUDGE_SYSTEM_PROMPT` from label_first.py, lines 31–42 (421 bytes)
  - Prompt 2: `DEFAULT_GROUNDING_JUDGE_USER_TEMPLATE` from label_first.py, lines 44–50 (93 bytes)
  - Caption includes placeholders (`\texttt{\{candidates\}}`, `\texttt{\{context\}}`) matching template variables

### Modified

- **`docs/paper/sections/eval-metrics-terminology.tex`** (line 32)
  - Old: `% drafts/tier_assignment.json;`
  - New: `% data/eval/wiki/tier_assignment.json (moved 2026-07-10);`
  - Context: comment block tracking data provenance for gold terminology set (tier filter source)

- **`docs/paper/sections/table-c-grounding.tex`** (after line 16, new line added)
  - Added: `% Aggregator regression anchors (raw-pred, no sitelink replay) now live in tests/test_wiki_metrics_v3.py; the sitelink-clean pre-redo numbers above differ slightly by construction and will be replaced by v2-run numbers.`
  - Context: comment block documenting methodology and data provenance for Table C

## Decisions & Rationale

**LaTeX structure:** Quote placement follows existing `appendix/acl_latex-2026-07-10.tex` convention (line 1072–1174 translation-prompt figure) — opening quote `"` on same line as first character of text, closing quote `"` on same line as last character. This ensures regex extraction and visual alignment.

**Verbatim fidelity:** All prompt text copied via `f-string` interpolation in Python, preserving:
- Exact whitespace and line breaks
- Russian Cyrillic text (no transliteration)
- Guillemets («») and em-dash (—) as-is
- Unicode arrows (→) as-is (note in comment explains pdfLaTeX literate config if needed)
- JSON structure and code examples exactly

**Verification method:** Python regex extraction (`r'\\begin\{prompt\}\n"(.*?)"\n\\end\{prompt\}'` with `re.DOTALL`) matched against source constants to confirm byte-for-byte identity. No silent truncation or normalization.

**Comment path update:**
- `drafts/tier_assignment.json` → `data/eval/wiki/tier_assignment.json (moved 2026-07-10)` reflects repository reorganization
- Minimal change: only path component replaced, date annotation added for traceability
- Second file: no tier_assignment reference found; only aggregator comment appended as specified

## Open Questions

None. Task is fully specified and completed; all verification checks passed.

## NOT Done

- No commits created (as instructed)
- No report artifacts (screenshots, test runs) — task is deterministic file creation with byte-level verification, not iterative testing
- No Scenario A/B process needed (mechanical task, no design/brainstorm/planning phases)
- No subagent dispatch (single-thread Python constant extraction and LaTeX formatting)
