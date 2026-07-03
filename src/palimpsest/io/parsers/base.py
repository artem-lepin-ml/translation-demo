"""Common interface for PDF -> Markdown parsers.

Every parser writes `output.md` and an `images/` subdir into the caller-provided
output directory. The in-memory `ParseResult` carries back the paths plus light
metadata (timing, page count). Parsers are swappable via `get_parser(name)`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


@dataclass(slots=True)
class ParseResult:
    parser_name: str
    markdown_path: Path
    images_dir: Path
    metadata: dict = field(default_factory=dict)


class PDFParser(Protocol):
    name: str

    def parse(self, pdf_path: Path, out_dir: Path) -> ParseResult: ...
