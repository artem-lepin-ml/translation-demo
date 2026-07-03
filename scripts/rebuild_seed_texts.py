"""Rebuild demo seed texts from the gemma par-by-par translation (Phase A).

Reads the RU/EN pilot slice from the old `gse-translation` checkout (read-only,
absolute paths — never modified here), applies a mechanical body-paragraph
filter, and writes the first 15 body paragraphs into
``data/seed/seed_paragraphs.jsonl`` as records ``id=1..15``. Criterion blocks
and terminology are initialized as empty placeholders; Phase B/C fill them in.

Idempotent: re-running produces a byte-identical file.

Why an all-caps line filter: ``body_indices`` treats any all-caps line as a
header. This is validated only for the first-15-paragraph slice pinned above.
It is not RU/EN-symmetric in general — a Russian header can carry lowercase
abbreviations (e.g. "гг.", "до", "н.э." in a date range) that keep
``stripped.upper() == stripped`` false, so it is *not* classified as a header,
while the equivalent English line (all-caps, no lowercase abbreviations) is.
For paragraphs beyond this slice that would misclassify RU and EN
differently, so the two indices lists would diverge — the `ru_body != en_body`
guard below catches that loudly rather than silently drifting. The filter
also doesn't model picture-caption prose lines (only the literal "Picture
text" marker) as a distinct category; any real caption text is treated as
body.

Run: ``uv run python scripts/rebuild_seed_texts.py``.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from palimpsest import paths

RU_PATH = Path("/Users/a1111/Projects/Work/gse-translation/data/pilot/pilot_original.md")
EN_PATH = Path(
    "/Users/a1111/Projects/Work/gse-translation/data/pilot/translating/"
    "local/gemma_par_by_par/translation.md"
)

SEED_FILE = paths.DATA / "seed" / "seed_paragraphs.jsonl"
NUM_PARAGRAPHS = 15

CYRILLIC_RE = re.compile(r"[а-яёА-ЯЁ]")

CRITERIA = ("accuracy", "fluency", "style", "cultural", "terminology", "consistency")


def body_indices(lines: list[str]) -> list[int]:
    """Return 1-based line indices that are body paragraphs.

    A line is dropped if, after stripping, it is (a) empty, (b) the literal
    "Picture text", or (c) all-caps (a header). Everything else is body.
    """
    out = []
    for i, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped == "Picture text":
            continue
        if stripped.upper() == stripped and any(c.isalpha() for c in stripped):
            continue
        out.append(i)
    return out


def _placeholder_criterion() -> dict:
    return {"identified_issues": [], "criteria_assessment": "", "summary": "", "final_score": None}


def _placeholder_terminology() -> dict:
    return {"identified_terms": []}


def build_records(ru_lines: list[str], en_lines: list[str], indices: list[int]) -> list[dict]:
    records = []
    for new_id, line_no in enumerate(indices, start=1):
        record: dict = {
            "source": ru_lines[line_no - 1],
            "translated": en_lines[line_no - 1],
        }
        for crit in CRITERIA:
            record[crit] = (
                _placeholder_terminology() if crit == "terminology" else _placeholder_criterion()
            )
        record["id"] = new_id
        records.append(record)
    return records


def _read_lines(path: Path, label: str) -> list[str]:
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        raise SystemExit(f"{label} source file not found: {path}. Stop and ask the owner.")


def main() -> None:
    ru_lines = _read_lines(RU_PATH, "RU_PATH")
    en_lines = _read_lines(EN_PATH, "EN_PATH")

    ru_body = body_indices(ru_lines)[:NUM_PARAGRAPHS]
    en_body = body_indices(en_lines)[:NUM_PARAGRAPHS]

    if ru_body != en_body:
        raise SystemExit(
            "RU/EN body paragraph indices diverge — mechanical filter is not "
            f"1:1 between sources. ru={ru_body} en={en_body}. Manual fix is "
            "out of scope: stop and ask the owner."
        )

    records = build_records(ru_lines, en_lines, ru_body)

    cyrillic_hits = sum(1 for r in records if CYRILLIC_RE.search(r["translated"]))
    if cyrillic_hits:
        raise SystemExit(
            f"{cyrillic_hits} selected EN paragraph(s) contain Cyrillic — "
            "source pairing looks broken. Stop and ask the owner."
        )

    SEED_FILE.parent.mkdir(parents=True, exist_ok=True)
    with SEED_FILE.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    print(
        f"wrote {len(records)} paragraphs, body_indices={ru_body}, "
        f"cyrillic_in_en={cyrillic_hits}"
    )


if __name__ == "__main__":
    main()
