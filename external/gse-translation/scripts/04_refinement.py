"""Stage 4 llm translation correction

Usage:
     uv run python scripts/04_refinement.py \\
        data/bouquet/evaluation/qwen-27b-bouquet/universal/reports/qwen3_6-27b.jsonl \\
        data/bouquet/translation/qwen-27b-bouquet-refined/translation.json

"""
from __future__ import annotations

import asyncio
from pathlib import Path

import typer

from palimpsest.refinement import run_refinement


app = typer.Typer(add_completion=False)


@app.command()
def main(
    scores_jsonl: Path,
    output: Path,
    max_concurrency: int = 256,
) -> None:
    asyncio.run(
        run_refinement(
            scores_jsonl=scores_jsonl,
            output=output,
            max_concurrency=max_concurrency,
        )
    )


if __name__ == '__main__':
    app()
