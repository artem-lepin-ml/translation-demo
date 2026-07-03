"""Run a single PDF parser on the pilot source and write output under
data/pilot/<name>/<parser>/{output.md, images/}.

Usage:
    uv run python scripts/pilot/run_parser.py --parser pymupdf
    uv run python scripts/pilot/run_parser.py --parser docling --name ancient_egypt
    uv run python scripts/pilot/run_parser.py --parser mineru
"""
from __future__ import annotations

import typer

from palimpsest import paths
from palimpsest.io.parsers import available_parsers, get_parser

app = typer.Typer(add_completion=False)


@app.command()
def main(
    parser: str = typer.Option(..., help=f"one of: {', '.join(available_parsers())}"),
    name: str = typer.Option("ancient_egypt", help="pilot slug under data/pilot/"),
) -> None:
    src = paths.DATA / "pilot" / name / "source.pdf"
    if not src.exists():
        raise typer.BadParameter(f"{src} not found; run extract_pages.py first")

    out_dir = paths.DATA / "pilot" / name / parser
    p = get_parser(parser)
    result = p.parse(src, out_dir)

    typer.echo(
        f"[{result.parser_name}] "
        f"md={result.markdown_path.relative_to(paths.ROOT)} "
        f"images={result.images_dir.relative_to(paths.ROOT)} "
        f"meta={result.metadata}"
    )


if __name__ == "__main__":
    app()
