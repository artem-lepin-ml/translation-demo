"""MinerU parser — ML layout + reading-order, invoked via its `magic-pdf` CLI.

The Python API of magic-pdf has shifted across minor versions; the CLI contract
is stable. Install via: `uv sync --extra pilot-mineru` on the GPU host (the extra
pulls `magic-pdf` which installs the `magic-pdf` console script).
"""
from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path

from .base import ParseResult


class MinerUParser:
    name = "mineru"

    def parse(self, pdf_path: Path, out_dir: Path) -> ParseResult:
        out_dir.mkdir(parents=True, exist_ok=True)
        raw_dir = out_dir / "_mineru_raw"
        if raw_dir.exists():
            shutil.rmtree(raw_dir)
        raw_dir.mkdir()

        t0 = time.perf_counter()
        subprocess.run(
            ["magic-pdf", "-p", str(pdf_path), "-o", str(raw_dir), "-m", "auto"],
            check=True,
        )
        elapsed = time.perf_counter() - t0

        # magic-pdf writes to: <raw_dir>/<stem>/auto/{<stem>.md, images/}
        stem = pdf_path.stem
        src_md = raw_dir / stem / "auto" / f"{stem}.md"
        src_images = raw_dir / stem / "auto" / "images"

        md_path = out_dir / "output.md"
        images_dir = out_dir / "images"
        if images_dir.exists():
            shutil.rmtree(images_dir)

        shutil.copy2(src_md, md_path)
        if src_images.exists():
            shutil.copytree(src_images, images_dir)
        else:
            images_dir.mkdir()

        return ParseResult(
            parser_name=self.name,
            markdown_path=md_path,
            images_dir=images_dir,
            metadata={"elapsed_s": round(elapsed, 2)},
        )
