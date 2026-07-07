"""Generate Stage-01 chunking artifacts for the pilot.

Hardcodes the chapter/subchapter boundaries verified manually against
data/pilot/pilot_original.md (see
docs/superpowers/specs/2026-05-08-chunking-format-design.md). On run,
overwrites the five JSON files in data/pilot/chunking/for_translation/.

Validates pilot_original.md line count on startup — bumps loudly if
the file changed length, since the hardcoded boundaries would silently
become wrong.
"""
from __future__ import annotations

from pathlib import Path

from palimpsest.chunking import (
    by_chapter,
    by_k_par,
    by_subchapter,
    dump_chunks,
    par_by_par,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
PILOT_MD = REPO_ROOT / "data" / "pilot" / "pilot_original.md"
OUT_DIR = REPO_ROOT / "data" / "pilot" / "chunking" / "for_translation"

TOTAL_LINES = 549

# 0-indexed chapter starts (verified against pilot_original.md).
CHAPTER_STARTS = [0, 110, 185, 307, 421, 489]

# 0-indexed subchapter starts, flat across all chapters (22 total).
# Includes the "РАННЕДИНАСТИЧЕСКИЙ ПЕРИОД" header at id 21 found
# during manual UPPERCASE-line verification.
SUBCHAPTER_STARTS = [
      0,  14,  21,  42,  53,  81,
    110, 117, 130, 139, 161,
    185, 190, 236, 248, 260,
    307, 378,
    421, 438,
    489, 539,
]


def _validate_pilot_length() -> None:
    actual = sum(1 for _ in PILOT_MD.read_text(encoding="utf-8").splitlines())
    if actual != TOTAL_LINES:
        raise SystemExit(
            f"pilot_original.md has {actual} lines, expected {TOTAL_LINES}. "
            "Update CHAPTER_STARTS / SUBCHAPTER_STARTS / TOTAL_LINES."
        )


def main() -> None:
    _validate_pilot_length()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    dump_chunks(by_chapter(CHAPTER_STARTS, TOTAL_LINES), OUT_DIR / "by_chapter.json")
    dump_chunks(by_subchapter(SUBCHAPTER_STARTS, TOTAL_LINES), OUT_DIR / "by_subchapter.json")
    dump_chunks(par_by_par(TOTAL_LINES), OUT_DIR / "par_by_par.json")
    dump_chunks(by_k_par(5, CHAPTER_STARTS, TOTAL_LINES), OUT_DIR / "by_5_par.json")
    dump_chunks(by_k_par(10, CHAPTER_STARTS, TOTAL_LINES), OUT_DIR / "by_10_par.json")

    print(f"wrote 5 chunking artifacts to {OUT_DIR.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
