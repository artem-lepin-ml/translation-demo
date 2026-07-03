"""Canonical filesystem paths for the project."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

DATA = ROOT / "data"
RAW = DATA / "raw"
INTERIM = DATA / "interim"
PROCESSED = DATA / "processed"
EXTERNAL = DATA / "external"
FEEDBACK = DATA / "feedback"

GLOSSARY_DIR = ROOT / "glossary"
PROMPTS = ROOT / "prompts"
CONFIGS = ROOT / "configs"
REPORTS = ROOT / "reports"
REFERENCES = ROOT / "references"


def chapter_dir(volume: int, chapter: int, stage: str | None = None) -> Path:
    base = PROCESSED / f"vol{volume:02d}" / f"ch{chapter:02d}"
    return base / stage if stage else base
