"""Split a Markdown chapter into paragraphs with stable IDs."""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

_BLOCK_SPLIT = re.compile(r"\n{2,}")


@dataclass(slots=True)
class SourceParagraph:
    id: str
    ru: str
    index: int


def split_paragraphs(markdown: str, *, volume: int, chapter: int) -> list[SourceParagraph]:
    """Split on blank lines, skip headings and <picture> placeholders."""
    out: list[SourceParagraph] = []
    idx = 0
    for raw in _BLOCK_SPLIT.split(markdown):
        block = raw.strip()
        if not block or block.startswith("#") or block == "<picture>":
            continue
        out.append(
            SourceParagraph(
                id=f"vol{volume:02d}/ch{chapter:02d}/p{idx:04d}",
                ru=block,
                index=idx,
            )
        )
        idx += 1
    return out


def write_paragraphs_jsonl(path: Path, paragraphs: list[SourceParagraph]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for p in paragraphs:
            f.write(json.dumps(asdict(p), ensure_ascii=False) + "\n")


def read_paragraphs_jsonl(path: Path) -> list[SourceParagraph]:
    return [
        SourceParagraph(**json.loads(line))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
