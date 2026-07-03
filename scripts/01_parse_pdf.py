"""Parse a source volume PDF into Markdown and split into paragraphs.

Usage:
    uv run python scripts/01_parse_pdf.py data/raw/vol01.pdf --volume 1 --chapter 1
    uv run python scripts/01_parse_pdf.py data/raw/vol01.pdf --parser docling
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import typer

from palimpsest import paths
from palimpsest.io.paragraphs import split_paragraphs, write_paragraphs_jsonl
from palimpsest.io.parsers import get_parser
from palimpsest.io.pdf import strip_images_to_placeholder

app = typer.Typer(add_completion=False)


@app.command()
def main(
    pdf: Path,
    volume: int = 1,
    chapter: int = 1,
    parser: str = "pymupdf",
) -> None:
    p = get_parser(parser)
    with tempfile.TemporaryDirectory() as tmp:
        result = p.parse(pdf, Path(tmp))
        md = result.markdown_path.read_text(encoding="utf-8")

    md = strip_images_to_placeholder(md)

    interim = paths.INTERIM / f"vol{volume:02d}_ch{chapter:02d}.md"
    interim.parent.mkdir(parents=True, exist_ok=True)
    interim.write_text(md, encoding="utf-8")

    chapter_dir = paths.chapter_dir(volume, chapter)
    chapter_dir.mkdir(parents=True, exist_ok=True)
    (chapter_dir / "source.md").write_text(md, encoding="utf-8")

    paragraphs = split_paragraphs(md, volume=volume, chapter=chapter)
    write_paragraphs_jsonl(chapter_dir / "paragraphs.jsonl", paragraphs)
    typer.echo(f"[{result.parser_name}] {len(paragraphs)} paragraphs -> {chapter_dir}")


if __name__ == "__main__":
    app()
