"""Stage 04 scoring CLI: run multi-judge evaluation from a YAML config."""

from __future__ import annotations

import asyncio
from pathlib import Path

import typer
from dotenv import load_dotenv

from palimpsest.config import load_scoring
from palimpsest.paths import evaluation_run_dir
from palimpsest.scoring import run_scoring

load_dotenv()

app = typer.Typer(add_completion=False)


@app.command()
def main(
    config: Path = typer.Option(..., "--config", "-c", help="Path to scoring config YAML."),
    force: bool = typer.Option(False, "--force", help="Re-run paragraphs that already have non-error rows."),
    max_paragraphs: int = typer.Option(
        0, "--max-paragraphs", "-n",
        help="If > 0, score only the first N paragraphs of every run (smoke).",
    ),
    max_concurrency: int = typer.Option(
        0, "--max-concurrency",
        help="Override max_concurrency from the config (0 = keep yaml value).",
    ),
) -> None:
    """Run multi-judge scoring as defined in CONFIG."""
    cfg = load_scoring(config)
    if max_concurrency > 0:
        cfg = cfg.model_copy(update={"max_concurrency": max_concurrency})
    if force:
        for run in cfg.runs:
            d = evaluation_run_dir(cfg.base_dir, cfg.evaluation_subdir, run)
            if d.exists():
                for jsonl in d.rglob("*.jsonl"):
                    jsonl.unlink()
    asyncio.run(run_scoring(cfg, max_paragraphs=max_paragraphs or None))
    typer.echo(f"Done. Outputs in {cfg.base_dir / cfg.evaluation_subdir}")


if __name__ == "__main__":
    app()
