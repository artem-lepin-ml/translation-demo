"""Helpers that write pipeline artifacts under the per-chapter layout."""
from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

from .. import paths


def stage_md_path(volume: int, chapter: int, stage: str, model: str) -> Path:
    return paths.chapter_dir(volume, chapter, stage) / f"{_safe(model)}.md"


def write_stage_md(volume: int, chapter: int, stage: str, model: str, text: str) -> Path:
    out = stage_md_path(volume, chapter, stage, model)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    return out


def write_jsonl(path: Path, rows: Iterable[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _safe(name: str) -> str:
    return name.replace("/", "__").replace(":", "_")
