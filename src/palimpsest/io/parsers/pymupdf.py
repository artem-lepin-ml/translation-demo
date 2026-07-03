"""PyMuPDF (pymupdf4llm) parser — baseline, CPU, no ML."""
from __future__ import annotations

import time
from pathlib import Path

import pymupdf4llm

from .base import ParseResult


class PyMuPDFParser:
    name = "pymupdf"

    def parse(self, pdf_path: Path, out_dir: Path) -> ParseResult:
        out_dir.mkdir(parents=True, exist_ok=True)
        images_dir = out_dir / "images"
        images_dir.mkdir(exist_ok=True)
        md_path = out_dir / "output.md"

        t0 = time.perf_counter()
        md = pymupdf4llm.to_markdown(
            str(pdf_path),
            write_images=True,
            image_path=str(images_dir),
            image_format="png",
            show_progress=True,
        )
        elapsed = time.perf_counter() - t0

        md_path.write_text(md, encoding="utf-8")
        return ParseResult(
            parser_name=self.name,
            markdown_path=md_path,
            images_dir=images_dir,
            metadata={"elapsed_s": round(elapsed, 2)},
        )
