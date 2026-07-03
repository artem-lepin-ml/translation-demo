# Suggestion Guard (advice-text guard) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent any Accept/apply-edit from splicing a judge's advice-text ("Consider...", "Use 'X', which is the standard...") into a translation by adding a pure guard on all three issue-ingest paths, backed by a prompt contract.

**Architecture:** A pure function `looks_like_advice(suggestion) -> bool` plus a `sanitize_issue(issue) -> issue` normalizer live in `judge.py`. `_issue_from()` (covers live evaluate + precompute) and the seed insert loop in `seed.py` both route freshly-ingested issues through the guard: a flagged suggestion is emptied and appended to the explanation as `Advice: ...`, so the existing empty-suggestion machinery (server 422 `no_suggestion` + three React renders that gate on `iss.suggestion` truthiness) hides Accept with zero UI change. A preamble line added to `scoring_system_prompt()` supplies the upstream contract so the judge stops emitting advice in the first place. The guard is idempotent (re-running it on an already-sanitized issue is a no-op). No response schema change, no re-scoring of existing issues, no frontend edits.

**Tech Stack:** Python 3.11 (FastAPI webapp under `src/palimpsest/webapp/`), SQLite (`data/demo.db`), pytest via `uv run pytest`, React/TS frontend (read-only for this plan).

---

## Preconditions (orchestrator, NOT part of this plan)

Branch + worktree creation is the orchestrator's step. This plan assumes it runs inside an existing worktree at `/Users/a1111/Projects/Work/worktrees/suggestion-guard`, on branch `feat/suggestion-guard` cut from `dev-demo`. All paths below are relative to that worktree root. Confirm before starting:

```bash
git -C /Users/a1111/Projects/Work/worktrees/suggestion-guard branch --show-current
# Expected: feat/suggestion-guard
git -C /Users/a1111/Projects/Work/worktrees/suggestion-guard log --oneline -1 dev-demo
```

Run all commands from the worktree root. Tests run with `uv run pytest` (the repo uses `uv`; see `README.md`).

---

## Deviations from spec

Verified against the code in the same worktree content as `dev-demo`. No design-level contradictions found. Two clarifications the executor must honor:

1. **Frontend needs no change.** The spec says the UI already hides Accept. Confirmed: `InspectorPanel.tsx:250,255`, `IssuesPanel.tsx:58,62`, `IssuePopover.tsx:51,57` all gate the suggestion/Accept render on the truthiness of `iss.suggestion`. Emptying `suggestion` server-side is sufficient. No `.tsx` edits are in this plan.
2. **Spec "195 non-empty suggestions" and the two advice cases are exactly reproduced.** Local `data/demo.db` audit yields 240 issues / 195 non-empty suggestions / 2 advice-flagged (`id=46` "Replace with 'city-states'..." and `id=47` "Use 'debt bondage', which is the standard..." = the named prod issue). All 240 local issues are `status='open'`, so there is no local `seed_target` contamination. The prod audit (Task 1) still runs to confirm the same on the live DB.

---

## File Structure

- **Modify** `src/palimpsest/webapp/judge.py` - add `looks_like_advice()` + `sanitize_issue()`; call `sanitize_issue` inside `_issue_from()`; extend `scoring_system_prompt()` preamble with the suggestion contract.
- **Modify** `src/palimpsest/webapp/seed.py` - route each seed issue dict through `sanitize_issue` before INSERT.
- **Create** `tests/test_suggestion_guard.py` - guard unit tests (3 real cases, structural, idempotency, negatives) + `_issue_from` integration + apply-edit e2e.
- **Create** `tests/test_seed_guard.py` - seed-path integration (planted advice -> suggestion empty, explanation carries `Advice:`).
- **Modify** `docs/subsystems/webapp.md` - doc-parity: suggestion contract + guard behavior.
- **Create (report only, git-tracked)** `docs/reports/2026-07-02-suggestion-guard-audit.md` - corpus audit output (Task 1), gates heuristic tuning.

---

## Task 1: Systematic-debugging corpus audit (FIRST - gates heuristic tuning)

REQUIRED SUB-SKILL mindset: `superpowers:systematic-debugging`. Root cause before fixes. This task produces the audit report whose numbers the later heuristic must reproduce. Do **not** tune the heuristic in Tasks 3-4 to anything the audit did not justify.

**Files:**
- Create: `docs/reports/2026-07-02-suggestion-guard-audit.md`

- [ ] **Step 1: Audit the local corpus (`data/demo.db`, read-only)**

Run this one-off analysis (read-only SELECTs only - do not write to the DB):

```bash
uv run python - <<'PY'
import sqlite3, re
c = sqlite3.connect("data/demo.db"); c.row_factory = sqlite3.Row
tot = c.execute("SELECT COUNT(*) n FROM issue").fetchone()["n"]
nonempty = c.execute("SELECT COUNT(*) n FROM issue WHERE TRIM(COALESCE(suggestion,''))<>''").fetchone()["n"]
status = {r["status"]: r["n"] for r in c.execute("SELECT status,COUNT(*) n FROM issue GROUP BY status")}
print("issues:", tot, "| non-empty suggestion:", nonempty, "| status:", status)
starts = re.compile(r"^\s*(Consider|Use|Retain|Prefer|Keep|Avoid|Note|Try|Opt for|Replace|Perhaps)\b", re.I)
meta = re.compile(r"(the translation|if needed|if context requires|gloss|standard|which is|would be|you (?:could|might))", re.I)
flagged = []
for r in c.execute("SELECT id,paragraph_id,criterion_id,status,suggestion FROM issue WHERE TRIM(COALESCE(suggestion,''))<>''"):
    s = r["suggestion"]
    if starts.search(s) or meta.search(s):
        flagged.append(dict(id=r["id"], pid=r["paragraph_id"], crit=r["criterion_id"], status=r["status"], sug=s))
print("flagged:", len(flagged))
for f in flagged:
    print(f"  id={f['id']} pid={f['pid']} {f['crit']} [{f['status']}]: {f['sug'][:100]}")
for f in flagged:
    if f["status"] == "accepted":
        p = c.execute("SELECT target,seed_target FROM paragraph WHERE id=?", (f["pid"],)).fetchone()
        print("  ACCEPTED", f["id"], "in target?", f["sug"][:30] in (p["target"] or ""),
              "in seed_target?", f["sug"][:30] in (p["seed_target"] or ""))
PY
```

Expected output (baseline - must match before proceeding):
```
issues: 240 | non-empty suggestion: 195 | status: {'open': 240}
flagged: 2
  id=46 pid=3 cultural [open]: Replace with 'city-states' or 'city-state polities' throughout to align with standard English histor
  id=47 pid=3 cultural [open]: Use 'debt bondage', which is the standard anthropological and historical term that accurately convey
```
(No `ACCEPTED ...` lines locally -> no local `seed_target` contamination.)

- [ ] **Step 2: Audit the prod corpus (read-only ssh + docker exec)**

Dump the prod DB counts and advice candidates without mutating anything. Pipe the Python via stdin so quoting stays sane:

```bash
ssh -i /Users/a1111/.ssh/id_ed25519_grader root@72.56.109.228 \
  'docker exec -i gse-demo python -' <<'PY'
import sqlite3, re
c = sqlite3.connect("/app/data/demo.db"); c.row_factory = sqlite3.Row
tot = c.execute("SELECT COUNT(*) n FROM issue").fetchone()["n"]
nonempty = c.execute("SELECT COUNT(*) n FROM issue WHERE TRIM(COALESCE(suggestion,''))<>''").fetchone()["n"]
status = {r["status"]: r["n"] for r in c.execute("SELECT status,COUNT(*) n FROM issue GROUP BY status")}
print("issues:", tot, "nonempty:", nonempty, "status:", status)
starts = re.compile(r"^\s*(Consider|Use|Retain|Prefer|Keep|Avoid|Note|Try|Opt for|Replace|Perhaps)\b", re.I)
meta = re.compile(r"(the translation|if needed|if context requires|gloss|standard|which is|would be|you (?:could|might))", re.I)
for r in c.execute("SELECT id,paragraph_id,criterion_id,status,suggestion FROM issue WHERE TRIM(COALESCE(suggestion,''))<>''"):
    s = r["suggestion"]
    if starts.search(s) or meta.search(s):
        print("FLAG", r["id"], r["paragraph_id"], r["criterion_id"], r["status"], s[:80])
        if r["status"] == "accepted":
            p = c.execute("SELECT target,seed_target FROM paragraph WHERE id=?", (r["paragraph_id"],)).fetchone()
            print("  ACCEPTED in target?", s[:30] in (p["target"] or ""), "in seed_target?", s[:30] in (p["seed_target"] or ""))
PY
```

Notes for the executor:
- This is READ-ONLY. `docker exec -i ... python -` runs the piped script in-container; it opens the DB read-then-print only. Do not run `UPDATE`/`DELETE`; do not write any file on the server.
- If `/app/data/demo.db` is not the container's DB path, discover it read-only first: `ssh -i /Users/a1111/.ssh/id_ed25519_grader root@72.56.109.228 'docker exec gse-demo sh -c "ls -la /app/data/*.db"'`.
- Record whether any `FLAG ... accepted` row shows `in seed_target? True`. If yes, note in the report that `POST reset` will NOT heal it and seed-refresh (`feat/seed-refresh`) is required - the spec's data-repair condition.

- [ ] **Step 3: Write the audit report**

Create `docs/reports/2026-07-02-suggestion-guard-audit.md` with:
- The baseline table: total issues, non-empty suggestions, status breakdown (local + prod).
- The full list of flagged rows (local ids 46, 47 + any prod-only ids), with criterion + status + first 100 chars.
- An explicit "accepted advice rows" section: which (if any) have advice text already spliced into `target` and/or `seed_target`. If any are in `seed_target`, state that reset is insufficient and seed-refresh is required.
- Frequency by criterion / model observed (from the flagged list).
- A closing line: "Heuristic target set: this report's flagged set is the ground truth. Tasks 3-4 must flag exactly these non-empty suggestions and zero honest ones."

- [ ] **Step 4: Commit**

```bash
git add docs/reports/2026-07-02-suggestion-guard-audit.md
git commit -m "docs(scoring): corpus audit of advice-text suggestions (local+prod)"
```

---

## Task 2: Suggestion contract in the scoring prompt preamble

**Files:**
- Test: `tests/test_suggestion_guard.py`
- Modify: `src/palimpsest/webapp/judge.py` (`scoring_system_prompt`, lines 58-68)

- [ ] **Step 1: Write the failing test**

Create `tests/test_suggestion_guard.py` with (only this test for now - later tasks append):

```python
"""Guard against advice-text leaking into apply-edit: prompt contract + heuristic."""
from __future__ import annotations

from palimpsest import paths
from palimpsest.webapp.judge import scoring_system_prompt


def test_preamble_states_suggestion_contract():
    p = scoring_system_prompt("accuracy", "ru", "en")
    disk = (paths.PROMPTS / "scoring" / "accuracy.md").read_text(encoding="utf-8")
    contract = p[: len(p) - len(disk)]
    assert "drop-in replacement" in contract
    assert "problematic_fragment" in contract
    assert "Consider" in contract and "if needed" in contract
    assert "empty string" in contract
    assert p.endswith(disk)


def test_preamble_contract_present_for_non_ru_en_pair():
    p = scoring_system_prompt("style", "de", "fr")
    assert "drop-in replacement" in p
    assert "This rubric was written for Russian" in p
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_suggestion_guard.py -v`
Expected: FAIL - `assert "drop-in replacement" in contract` fails (contract not present yet).

- [ ] **Step 3: Implement the preamble contract**

In `src/palimpsest/webapp/judge.py`, replace the `scoring_system_prompt` body (currently lines 58-68) with:

```python
_SUGGESTION_CONTRACT = (
    "SUGGESTION FIELD CONTRACT. The `suggestion` field is a drop-in replacement "
    "for `problematic_fragment`, written in the target language, that can be pasted "
    "verbatim in place of the flagged text. It is NOT advice. Do not write meta or "
    "advisory phrasing (\"Consider ...\", \"Use 'X' ...\", \"if needed\", \"if context "
    "requires\", \"which is the standard ...\", \"add a gloss\"). If you have no single "
    "concrete replacement, set `suggestion` to an empty string and put the advice in "
    "`explanation` instead.\n\n"
)


def scoring_system_prompt(criterion_id: str, source_lang: str = "ru", target_lang: str = "en") -> str:
    src, tgt = lang_name(source_lang), lang_name(target_lang)
    preamble = f"You are evaluating a translation from {src} into {tgt}.\n\n"
    if (src.lower(), tgt.lower()) != ("russian", "english"):
        preamble += (
            f"This rubric was written for Russian->English. Read every mention of Russian "
            f"as {src} (the source language) and every mention of English as {tgt} (the "
            f"target language). Ignore Cyrillic-specific transliteration rules when the "
            f"source is not Russian.\n\n"
        )
    return preamble + _SUGGESTION_CONTRACT + _scoring_prompt(criterion_id)
```

Preserve the existing arrow glyph in the adapter string exactly as it is on disk (the current file uses the Unicode right-arrow in "Russian->English"); do not downgrade it to ASCII - `test_judge_lang.py::test_other_pair_gets_adapter_preamble` asserts the literal "Russian->English." with the Unicode arrow. Copy the adapter block verbatim from the current source; only the `_SUGGESTION_CONTRACT` insertion is new.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_suggestion_guard.py tests/test_judge_lang.py -v`
Expected: PASS - both new preamble tests pass and all `test_judge_lang.py` tests still pass (the on-disk rubric remains the suffix, so `p.endswith(disk)` holds; `startswith` assertions unaffected).

- [ ] **Step 5: Commit**

```bash
git add tests/test_suggestion_guard.py src/palimpsest/webapp/judge.py
git commit -m "feat(scoring): add suggestion drop-in-replacement contract to prompt preamble"
```

---

## Task 3: `looks_like_advice` heuristic + `sanitize_issue` normalizer

**Files:**
- Test: `tests/test_suggestion_guard.py` (append)
- Modify: `src/palimpsest/webapp/judge.py` (add functions after `derive_severity`, before `_parse_json`)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_suggestion_guard.py`:

```python
from palimpsest.webapp.judge import looks_like_advice, sanitize_issue


def test_flags_debt_bondage_prod_case():
    assert looks_like_advice(
        "Use 'debt bondage', which is the standard anthropological and historical term "
        "that accurately conveys the temporary nature."
    )


def test_flags_city_states_case():
    assert looks_like_advice(
        "Replace with 'city-states' or 'city-state polities' throughout to align with "
        "standard English historiography."
    )


def test_flags_temple_centers_gloss_case():
    assert looks_like_advice("Consider 'temple centers' with a brief gloss if needed.")


def test_flags_quoted_alternatives_slash():
    assert looks_like_advice("'polis'/'city-state', depending on the register you prefer")


def test_flags_long_relative_to_fragment_with_quoted_alt():
    frag = "raby"
    sug = "'slaves' or 'bondservants' - the latter is more accurate for the period described"
    assert looks_like_advice(sug, fragment=frag)


def test_honest_single_replacement_not_flagged():
    assert not looks_like_advice("city-states")


def test_honest_multiword_replacement_not_flagged():
    assert not looks_like_advice("were partly incorporated into the land market")


def test_honest_replacement_with_word_use_inside_not_flagged():
    assert not looks_like_advice("the use of cuneiform script")


def test_empty_suggestion_not_flagged():
    assert not looks_like_advice("")
    assert not looks_like_advice("   ")


def test_sanitize_moves_advice_to_explanation():
    issue = {
        "targetFragment": "city states",
        "sourceFragment": "goroda-gosudarstva",
        "explanation": "Term is inconsistent.",
        "suggestion": "Use 'debt bondage', which is the standard term.",
        "severity": "minor",
        "mqmCategory": None,
    }
    out = sanitize_issue(issue)
    assert out["suggestion"] == ""
    assert out["explanation"].endswith("Advice: Use 'debt bondage', which is the standard term.")
    assert out["explanation"].startswith("Term is inconsistent.")


def test_sanitize_leaves_honest_suggestion_untouched():
    issue = {
        "targetFragment": "city states",
        "sourceFragment": "goroda-gosudarstva",
        "explanation": "Should be hyphenated.",
        "suggestion": "city-states",
        "severity": "minor",
        "mqmCategory": None,
    }
    out = sanitize_issue(issue)
    assert out["suggestion"] == "city-states"
    assert out["explanation"] == "Should be hyphenated."


def test_sanitize_is_idempotent():
    issue = {
        "targetFragment": "raby",
        "sourceFragment": "raby-ru",
        "explanation": "Wrong term.",
        "suggestion": "Consider 'bondservants' if needed.",
        "severity": "major",
        "mqmCategory": None,
    }
    once = sanitize_issue(issue)
    twice = sanitize_issue(dict(once))
    assert once == twice
    assert twice["suggestion"] == ""
    assert twice["explanation"].count("Advice:") == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_suggestion_guard.py -v -k "advice or sanitize or honest or flags or empty_suggestion"`
Expected: FAIL - `ImportError: cannot import name 'looks_like_advice'`.

- [ ] **Step 3: Implement the heuristic and normalizer**

In `src/palimpsest/webapp/judge.py`, insert after `derive_severity` (after line 24) and before `_parse_json`:

```python
# advice-text guard (spec 2026-07-02-suggestion-guard).
# A `suggestion` must be a drop-in replacement, not advice. These heuristics flag
# advice so _issue_from / seed can empty it (moving the text to explanation).
# ru->en completeness via the English advisory lexicon; other pairs rely on the
# language-agnostic STRUCTURAL signals only.
_ADVICE_START = re.compile(
    r"^\s*(consider|use|retain|prefer|keep|avoid|note|try|opt for|replace|perhaps)\b",
    re.IGNORECASE,
)
_ADVICE_META = re.compile(
    r"\b(the translation|if needed|if context requires|which is the standard|"
    r"gloss|you (?:could|might|may)|would be better|instead of)\b",
    re.IGNORECASE,
)
_QUOTES = "'\"‘’“”"
# Structural (language-agnostic): a quoted alternative offered via '...'/'...' or
# '...' or '...' - i.e. two quoted spans separated by a slash or the word "or".
_QUOTED_ALT = re.compile(
    rf"[{_QUOTES}][^{_QUOTES}]+[{_QUOTES}]\s*(?:/|\bor\b)\s*[{_QUOTES}]"
)
# A single quoted span followed by an explanatory clause introduced by a dash.
_QUOTED_THEN_CLAUSE = re.compile(
    rf"[{_QUOTES}][^{_QUOTES}]+[{_QUOTES}].*[—–-]\s+\w"
)


def looks_like_advice(suggestion: str, fragment: str = "") -> bool:
    """True if `suggestion` reads as advice rather than a drop-in replacement.

    English lexicon (advisory starts + meta markers) gives ru->en completeness;
    the quoted-alternative structural signals are language-agnostic.
    """
    s = (suggestion or "").strip()
    if not s:
        return False
    if _ADVICE_START.match(s) or _ADVICE_META.search(s):
        return True
    if _QUOTED_ALT.search(s):
        return True
    if _QUOTED_THEN_CLAUSE.search(s):
        return True
    if fragment and len(s) > 3 * max(len(fragment.strip()), 1) and \
            any(q in s for q in _QUOTES) and (" or " in s or "/" in s):
        return True
    return False


def sanitize_issue(issue: dict[str, Any]) -> dict[str, Any]:
    """Idempotently move an advice `suggestion` into `explanation` (as ``Advice: ...``)
    and empty the field, so downstream apply-edit refuses it (422 no_suggestion) and
    the UI hides Accept. No-op on honest suggestions and on already-sanitized dicts.
    """
    sug = (issue.get("suggestion") or "").strip()
    if not sug or not looks_like_advice(sug, issue.get("targetFragment", "")):
        return issue
    expl = (issue.get("explanation") or "").rstrip()
    advice = f"Advice: {sug}"
    if advice not in expl:
        expl = f"{expl}\n{advice}".strip() if expl else advice
    issue["explanation"] = expl
    issue["suggestion"] = ""
    return issue
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_suggestion_guard.py -v`
Expected: PASS - all heuristic, structural, negative, and idempotency tests green.

- [ ] **Step 5: Cross-check the heuristic against the audit (no false positives)**

The heuristic must flag exactly the audit's non-empty flagged set and nothing else among the 195 non-empty suggestions:

```bash
uv run python - <<'PY'
import sqlite3
from palimpsest.webapp.judge import looks_like_advice
c = sqlite3.connect("data/demo.db"); c.row_factory = sqlite3.Row
flagged = []
for r in c.execute("SELECT id,target_fragment,suggestion FROM issue WHERE TRIM(COALESCE(suggestion,''))<>''"):
    if looks_like_advice(r["suggestion"], r["target_fragment"] or ""):
        flagged.append((r["id"], r["suggestion"][:70]))
print("heuristic flagged:", len(flagged))
for i, s in flagged:
    print("  ", i, s)
PY
```

Expected: `heuristic flagged: 2` with ids 46 and 47 - identical to the Task 1 audit. If the count differs, STOP and reconcile against the audit report (systematic-debugging: the report is ground truth, not the heuristic).

- [ ] **Step 6: Commit**

```bash
git add tests/test_suggestion_guard.py src/palimpsest/webapp/judge.py
git commit -m "feat(scoring): add looks_like_advice guard and sanitize_issue normalizer"
```

---

## Task 4: Wire the guard into `_issue_from` (live evaluate + precompute)

**Files:**
- Test: `tests/test_suggestion_guard.py` (append)
- Modify: `src/palimpsest/webapp/judge.py` (`_issue_from`, lines 92-101)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_suggestion_guard.py`:

```python
from palimpsest.webapp.judge import _issue_from


def test_issue_from_sanitizes_advice_suggestion():
    raw = {
        "problematic_fragment": "city states",
        "source_fragment": "goroda-gosudarstva",
        "explanation": "Inconsistent term.",
        "suggestion": "Use 'debt bondage', which is the standard term.",
    }
    out = _issue_from(raw)
    assert out["suggestion"] == ""
    assert "Advice: Use 'debt bondage'" in out["explanation"]
    assert out["explanation"].startswith("Inconsistent term.")


def test_issue_from_keeps_honest_suggestion():
    raw = {
        "problematic_fragment": "city states",
        "source_fragment": "goroda-gosudarstva",
        "explanation": "Hyphenate.",
        "suggestion": "city-states",
    }
    out = _issue_from(raw)
    assert out["suggestion"] == "city-states"
    assert out["explanation"] == "Hyphenate."
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_suggestion_guard.py -v -k issue_from`
Expected: FAIL - `test_issue_from_sanitizes_advice_suggestion` fails: `suggestion` still carries the advice text.

- [ ] **Step 3: Route `_issue_from` through `sanitize_issue`**

In `src/palimpsest/webapp/judge.py`, replace `_issue_from` (lines 92-101) with:

```python
def _issue_from(it: Mapping[str, Any]) -> dict[str, Any]:
    explanation = it.get("explanation", "")
    issue = {
        "targetFragment": it.get("problematic_fragment", ""),
        "sourceFragment": it.get("source_fragment", ""),
        "explanation": explanation,
        "suggestion": it.get("suggestion", ""),
        "severity": derive_severity(explanation),
        "mqmCategory": None,
    }
    return sanitize_issue(issue)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_suggestion_guard.py tests/test_judge_parse.py -v`
Expected: PASS - new `_issue_from` tests pass and existing `judge_one`/parse tests remain green.

- [ ] **Step 5: Commit**

```bash
git add tests/test_suggestion_guard.py src/palimpsest/webapp/judge.py
git commit -m "feat(scoring): sanitize advice suggestions on live+precompute ingest (_issue_from)"
```

---

## Task 5: Wire the guard into the seed insert loop (third path)

**Files:**
- Test: `tests/test_seed_guard.py`
- Modify: `src/palimpsest/webapp/seed.py` (import line 18 + issue INSERT loop lines 103-109)

- [ ] **Step 1: Write the failing test**

Create `tests/test_seed_guard.py`:

```python
"""Seed-path guard: planted advice suggestion is emptied and moved to explanation."""
from __future__ import annotations

import json
import sqlite3

from palimpsest.webapp.judge import sanitize_issue


def test_seed_row_shape_after_sanitize():
    out = sanitize_issue({
        "targetFragment": "city states",
        "sourceFragment": "goroda-gosudarstva",
        "explanation": "Inconsistent term.",
        "suggestion": "Use 'debt bondage', which is the standard term.",
        "severity": "minor",
        "mqmCategory": None,
    })
    assert out["suggestion"] == ""
    assert "Advice: Use 'debt bondage'" in out["explanation"]


def test_seed_inserts_no_advice_suggestion(tmp_path, monkeypatch):
    from palimpsest.webapp import db, seed as seed_mod

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "demo.db")
    monkeypatch.setattr(db, "_conn", None)

    seed_file = tmp_path / "seed.jsonl"
    row = {
        "source": "goroda-gosudarstva",
        "translated": "city states",
        "cultural": {
            "final_score": 5.0,
            "summary": "s",
            "identified_issues": [{
                "problematic_fragment": "city states",
                "source_fragment": "goroda-gosudarstva",
                "explanation": "Inconsistent term.",
                "suggestion": "Use 'debt bondage', which is the standard term.",
            }],
        },
    }
    seed_file.write_text(json.dumps(row) + "\n", encoding="utf-8")
    monkeypatch.setattr(seed_mod, "SEED_FILE", seed_file)

    seed_mod.seed()

    conn = sqlite3.connect(str(tmp_path / "demo.db"))
    conn.row_factory = sqlite3.Row
    r = conn.execute("SELECT suggestion, explanation FROM issue WHERE criterion_id='cultural'").fetchone()
    assert r is not None
    assert (r["suggestion"] or "") == ""
    assert "Advice: Use 'debt bondage'" in r["explanation"]
```

Executor note: confirm the `db` attribute name that `seed.py` writes to is `DB_PATH` (the `conftest.py` fixture already monkeypatches `db.DB_PATH` and `db._conn`, so this matches the established pattern). `seed_mod.seed()` calls `db.init_db(reset=True)` which honors the patched path.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_seed_guard.py -v`
Expected: FAIL - `test_seed_inserts_no_advice_suggestion` fails: seeded `suggestion` still carries the advice (seed.py inserts the raw suggestion).

- [ ] **Step 3: Route each seed issue through `sanitize_issue`**

In `src/palimpsest/webapp/seed.py`:

3a. Update the import on line 18 from:
```python
from .judge import derive_severity
```
to:
```python
from .judge import derive_severity, sanitize_issue
```

3b. Replace the issue INSERT loop (lines 103-109) with:
```python
            for it in (payload.get("identified_issues") or []):
                expl = it.get("explanation", "")
                issue = sanitize_issue({
                    "targetFragment": it.get("problematic_fragment", ""),
                    "sourceFragment": it.get("source_fragment", ""),
                    "explanation": expl,
                    "suggestion": it.get("suggestion", ""),
                    "severity": derive_severity(expl),
                    "mqmCategory": None,
                })
                conn.execute(
                    "INSERT INTO issue(paragraph_id,criterion_id,target_fragment,source_fragment,explanation,"
                    "suggestion,severity,mqm_category,status,kind,created_at) VALUES(?,?,?,?,?,?,?,?,'open','seed',?)",
                    (pid, cid, issue["targetFragment"], issue["sourceFragment"], issue["explanation"],
                     issue["suggestion"], issue["severity"], issue["mqmCategory"], ts))
```

Note: `severity` is still derived from the original explanation (before the `Advice:` line is appended), because `derive_severity(expl)` runs on the pre-sanitize text and `sanitize_issue` never re-derives severity. This preserves today's severity classification for honest issues.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_seed_guard.py tests/test_seed_registry.py -v`
Expected: PASS - the seed guard tests pass and existing `test_seed_registry.py` remains green.

- [ ] **Step 5: Commit**

```bash
git add tests/test_seed_guard.py src/palimpsest/webapp/seed.py
git commit -m "feat(webapp): sanitize advice suggestions on seed ingest (third path)"
```

---

## Task 6: Byte-identical no-mutation validation (honest suggestions untouched)

Proves the guard changes ONLY the two advice rows and leaves the other 193 non-empty suggestions byte-identical. Systematic-debugging discipline: verify the fix does not regress honest data.

**Files:** none created - a validation gate.

- [ ] **Step 1: Re-seed the local DB under the new guard**

```bash
uv run python -m palimpsest.webapp.seed
```
Expected tail: `seeded 16 paragraphs, doc_id=1, model_key=...`

- [ ] **Step 2: Assert honest suggestions are byte-identical to the raw seed file**

```bash
uv run python - <<'PY'
import json, sqlite3
from palimpsest.webapp.judge import looks_like_advice

rows = [json.loads(l) for l in open("data/seed/seed_paragraphs.jsonl", encoding="utf-8").read().splitlines() if l.strip()]
crits = ["accuracy", "fluency", "style", "cultural", "terminology"]
raw = []
for d in rows:
    for c in crits:
        p = d.get(c)
        if not isinstance(p, dict):
            continue
        for it in (p.get("identified_issues") or []):
            s = (it.get("suggestion") or "")
            if s.strip():
                raw.append((it.get("problematic_fragment", ""), s))

conn = sqlite3.connect("data/demo.db"); conn.row_factory = sqlite3.Row
db_sug = [r["suggestion"] for r in conn.execute("SELECT suggestion FROM issue")]
db_empty_with_advice = conn.execute(
    "SELECT COUNT(*) n FROM issue WHERE TRIM(COALESCE(suggestion,''))='' AND explanation LIKE '%Advice:%'").fetchone()["n"]

honest = [s for frag, s in raw if not looks_like_advice(s, frag)]
flagged = [s for frag, s in raw if looks_like_advice(s, frag)]
missing = [s for s in honest if s not in db_sug]
print("raw non-empty:", len(raw), "honest:", len(honest), "flagged:", len(flagged))
print("honest suggestions missing byte-identical from DB:", len(missing))
print("DB issues with empty suggestion + Advice: in explanation:", db_empty_with_advice)
assert len(missing) == 0, missing[:3]
assert len(flagged) == db_empty_with_advice == 2
print("BYTE-IDENTICAL OK")
PY
```

Expected:
```
raw non-empty: 195 honest: 193 flagged: 2
honest suggestions missing byte-identical from DB: 0
DB issues with empty suggestion + Advice: in explanation: 2
BYTE-IDENTICAL OK
```

- [ ] **Step 2b: Restore the pristine local DB (avoid committing a re-seeded db)**

`data/demo.db` is tracked. Restore it so the re-seed is not accidentally committed:
```bash
git checkout -- data/demo.db
git status --short
# Expected: no line for data/demo.db
```

- [ ] **Step 3: No commit** (validation-only task; nothing to add).

---

## Task 7: Full suite + doc-parity (same-commit webapp.md)

**Files:**
- Modify: `docs/subsystems/webapp.md` (Subtleties section around lines 195-199)

- [ ] **Step 1: Run the whole test suite**

Run: `uv run pytest -q`
Expected: all tests pass (new `test_suggestion_guard.py`, `test_seed_guard.py` + the existing suite, including `test_judge_lang.py`, `test_judge_parse.py`, `test_seed_registry.py`, `test_apply_edit.py`).

- [ ] **Step 2: Update `docs/subsystems/webapp.md` for doc-parity**

In `docs/subsystems/webapp.md`, in the "Subtleties" block, immediately AFTER the existing bullet that begins **"Accept with empty suggestion is rejected (not destructive)."** (currently line 195), add:

```markdown
- **Advice-text guard (2026-07-02).** A judge sometimes puts *advice* in `suggestion` ("Consider 'temple centers' with a brief gloss if needed", "Use 'debt bondage', which is the standard...") instead of a drop-in replacement - accepting it splices the advice into the translation. Two defenses: (1) `scoring_system_prompt()` preamble states the **suggestion contract** - `suggestion` is a verbatim, target-language replacement for `problematic_fragment`; advice goes in `explanation`; no concrete replacement -> empty string. (2) A pure `looks_like_advice()` heuristic (English advisory lexicon for ru->en completeness + language-agnostic quoted-alternative structural signals) drives `sanitize_issue()`, which is called on **all three ingest paths** - `_issue_from()` (live `/evaluate` + precompute) and the seed INSERT loop in `seed.py`. A flagged suggestion is moved to the end of `explanation` as `Advice: ...` and the field is emptied, so `apply-edit` returns 422 `no_suggestion` and all three issue renders (`InspectorPanel`, `IssuesPanel`, `IssuePopover`) hide Accept - no frontend change. `sanitize_issue()` is idempotent (a second pass is a no-op; `Advice:` is not duplicated). Full data repair is the `feat/seed-refresh` re-seed (guard merges first); `POST reset` reopens seed issues so the seed-time guard keeps reopened advice un-acceptable.
```

- [ ] **Step 3: Verify the doc references match the code**

Run: `uv run pytest tests/test_suggestion_guard.py tests/test_seed_guard.py -q`
Expected: PASS (sanity re-run - confirms the names cited in the doc, `looks_like_advice`/`sanitize_issue`, exist).

- [ ] **Step 4: Commit (doc-parity in the feature's final commit)**

```bash
git add docs/subsystems/webapp.md
git commit -m "docs(webapp): document advice-text suggestion guard and contract"
```

---

## Task 8: e2e - Accept on the advice paragraph does not splice advice

Success criterion: Accept on an advice-issue must not insert advice text. After the guard, both suggestions are empty, so apply-edit must 422 and never insert "Use 'debt bondage'..." or "Replace with 'city-states'..." into the target.

**Files:**
- Test: `tests/test_suggestion_guard.py` (append) - uses the API `client` fixture from `tests/conftest.py`.

- [ ] **Step 1: Write the guarding test**

Append to `tests/test_suggestion_guard.py`:

```python
def test_apply_edit_rejects_sanitized_advice_issue(client):
    body = {
        "title": "advice guard", "sourceLang": "ru", "targetLang": "en", "precompute": False,
        "paragraphs": [{"source": "goroda-gosudarstva", "target": "city states"}],
    }
    doc = client.post("/api/documents", json=body).json()
    pid = doc["paragraphs"][0]["id"]

    from palimpsest.webapp.judge import _issue_from
    issue = _issue_from({
        "problematic_fragment": "city states",
        "source_fragment": "goroda-gosudarstva",
        "explanation": "Inconsistent term.",
        "suggestion": "Use 'debt bondage', which is the standard term.",
    })
    assert issue["suggestion"] == ""

    from palimpsest.webapp import db
    conn = db.connect()
    with db._lock:
        iid = conn.execute(
            "INSERT INTO issue(paragraph_id,criterion_id,target_fragment,source_fragment,explanation,"
            "suggestion,severity,mqm_category,status,kind,created_at) "
            "VALUES(?,?,?,?,?,?,?,?, 'open','live', datetime('now'))",
            (pid, "cultural", issue["targetFragment"], issue["sourceFragment"],
             issue["explanation"], issue["suggestion"], issue["severity"], None)).lastrowid
        conn.commit()

    r = client.post(f"/api/paragraphs/{pid}/apply-edit", json={"issueId": str(iid)})
    assert r.status_code == 422
    assert r.json()["detail"]["error"] == "no_suggestion"

    para = client.get(f"/api/paragraphs/{pid}").json()
    assert para["target"] == "city states"
    assert "debt bondage" not in para["target"]
```

Executor note: confirm the create route (`POST /api/documents`) response exposes `paragraphs[0].id` and that `GET /api/paragraphs/{pid}` returns a `target` key - inspect `tests/test_documents_create.py` and `app.py` (create handler around line 288, paragraph GET handler) and adjust the key access if the shapes differ. The fixed contract to assert: 422 `no_suggestion` and byte-identical `target`.

- [ ] **Step 2: Run the test**

Run: `uv run pytest tests/test_suggestion_guard.py::test_apply_edit_rejects_sanitized_advice_issue -v`
Expected: PASS - the sanitized (empty) suggestion yields 422 `no_suggestion` and the target is byte-identical.

- [ ] **Step 3: Commit**

```bash
git add tests/test_suggestion_guard.py
git commit -m "test(webapp): e2e advice-suggestion cannot be applied via apply-edit"
```

---

## Task 9: Re-validation trigger note (post seed-refresh)

The post-seed-refresh re-validation is a *future* trigger (fires when `feat/seed-refresh` re-seeds under this contract). Record the exact re-run so the follow-up branch knows what to do - no code here.

**Files:**
- Modify: `docs/reports/2026-07-02-suggestion-guard-audit.md` (append a "Re-validation trigger" section)

- [ ] **Step 1: Append the re-validation section**

Append to `docs/reports/2026-07-02-suggestion-guard-audit.md`:

```markdown
## Re-validation trigger (post `feat/seed-refresh`)

After the seed-refresh re-seed lands, re-run the Task 3 Step 5 cross-check and the
Task 6 Step 2 byte-identical validation against the NEW corpus, and diff the flagged
set to this baseline (local ids 46, 47). Expected under the merged contract: the
regenerated suggestions carry no advice, so the heuristic flags 0 (or only genuinely
new advice, which the guard still empties). Record the new counts and any diff here.
```

- [ ] **Step 2: Commit**

```bash
git add docs/reports/2026-07-02-suggestion-guard-audit.md
git commit -m "docs(scoring): record post-seed-refresh re-validation trigger"
```

---

## Final verification checklist (before handoff)

- [ ] `uv run pytest -q` - full suite green.
- [ ] Task 3 Step 5 cross-check: heuristic flags exactly ids 46, 47 locally (matches audit).
- [ ] Task 6: 193 honest suggestions byte-identical, 2 advice rows emptied with `Advice:` in explanation, `data/demo.db` restored (no stray re-seed committed).
- [ ] Guard called on all three paths: `_issue_from` (test_issue_from_*), seed loop (test_seed_guard), and the apply-edit e2e proves the downstream effect.
- [ ] `docs/subsystems/webapp.md` updated (doc-parity) - committed with the feature.
- [ ] No frontend files modified.
- [ ] No `Co-Authored-By` trailers on any commit.

## Self-Review notes (author)

- **Spec coverage:** layer 1 (systematic-debugging audit, local + prod, accepted-rows + seed_target check) -> Task 1; layer 2 (prompt contract in `scoring_system_prompt` preamble, not the 5 md files; fluency out of scope - confirmed no `suggestion` in `prompts/scoring/fluency.md` schema block) -> Task 2; layer 3 (`looks_like_advice` pure fn in judge.py + `sanitize_issue`, idempotent, English lexicon + structural signals, move to `Advice:` explanation) -> Tasks 3-5. All-three-paths (`_issue_from` for live+precompute, seed loop) -> Tasks 4-5. Data-repair (reset reopens seed issues -> seed-time guard) -> Task 5 + doc note. Success criteria 1 (guard units incl. idempotency + negatives + all-3-paths) -> Tasks 3-5; 2 (heuristic run over corpus, 0 false positives, byte-identical) -> Task 3 Step 5 + Task 6; 3 (e2e apply-edit) -> Task 8; 4 (post-refresh re-validation) -> Task 9; 5 (doc-parity same commit) -> Task 7.
- **Placeholder scan:** every code step contains complete code; every command has expected output. No TBD/TODO.
- **Type consistency:** `sanitize_issue(issue: dict) -> dict` and `looks_like_advice(suggestion: str, fragment: str = "") -> bool` used with identical signatures in judge.py, seed.py, and all tests. Issue dict keys (`targetFragment`, `sourceFragment`, `explanation`, `suggestion`, `severity`, `mqmCategory`) match `_issue_from`'s existing shape.
