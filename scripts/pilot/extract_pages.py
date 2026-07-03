"""Extract a page range from a source PDF into a smaller PDF for pilot parsing.

Page numbers are 1-based PDF indices (as the file orders them), inclusive.

Usage:
    uv run python scripts/pilot/extract_pages.py \
        --source data/raw/vol01_source.pdf \
        --pages 101-139 \
        --name ancient_egypt
"""
from __future__ import annotations

from pathlib import Path

import pymupdf
import typer

from palimpsest import paths

app = typer.Typer(add_completion=False)


@app.command()
def main(
    source: Path = paths.RAW / "vol01_source.pdf",
    pages: str = typer.Option("101-139", help="1-based inclusive page range, e.g. 101-139"),
    name: str = typer.Option("ancient_egypt", help="pilot slug under data/pilot/"),
) -> None:
    start_s, end_s = pages.split("-")
    start, end = int(start_s), int(end_s)
    if start < 1 or end < start:
        raise typer.BadParameter(f"invalid page range: {pages}")

    out_dir = paths.DATA / "pilot" / name
    out_dir.mkdir(parents=True, exist_ok=True)
    dst = out_dir / "source.pdf"

    doc = pymupdf.open(source)
    try:
        if end > doc.page_count:
            raise typer.BadParameter(
                f"end page {end} exceeds source page count {doc.page_count}"
            )
        new = pymupdf.open()
        try:
            new.insert_pdf(doc, from_page=start - 1, to_page=end - 1)
            new.save(dst)
        finally:
            new.close()
    finally:
        doc.close()

    typer.echo(f"Wrote pages {start}-{end} ({end - start + 1} pages) -> {dst}")


if __name__ == "__main__":
    app()
