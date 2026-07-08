"""Stage 2 CLI: translate source paragraphs using a chunking strategy.

Reads a JSON file containing a list of strings (one paragraph per string),
picks the code path by user-prompt placeholder ({paragraph} or {chunk}),
and writes
`data/pilot/translating[/<bucket>]/<run_name>/{translation.json,config.json[,failures.jsonl]}`.

Exit code 0 if all chunks succeeded, 1 if any chunk hit `[TRANSLATION FAILED]`.
"""
from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import typer
from dotenv import load_dotenv

from palimpsest.config import load_models, load_translate
from palimpsest.llm.client import LLMClient, LLMConfig
from palimpsest.paths import PROMPTS, REPO_ROOT
from palimpsest.translate_json import (
    ProgressLog,
    load_prompt,
    translate_per_paragraph,
    write_run_artifacts,
)

# Load .env from CWD (repo root). Silently does nothing if file is absent.
load_dotenv()

app = typer.Typer(add_completion=False)


def _build_out_dir(*, run_name: str, bucket: str) -> Path:
    """Return data/pilot/translating[/<bucket>]/<run_name>/.

    Empty bucket keeps the legacy flat layout; "small"/"large"/"local"
    nest under the matching subdirectory.
    """
    root = REPO_ROOT / "data" / "pilot" / "translating"
    if bucket:
        root = root / bucket
    return root / run_name


async def _run(
    *,
    run_name: str,
    bucket: str,
    model_key: str,
    system_prompt_rel: str,
    user_prompt_rel: str,
    max_concurrency: int,
    input_json: Path,
):
    models = load_models()
    if model_key not in models:
        typer.echo(f"unknown model key: {model_key}; check configs/models.yaml", err=True)
        raise typer.Exit(2)
    model_cfg = models[model_key]
    client = LLMClient(LLMConfig.from_model_config(model_cfg))
    typer.echo(f"[02_translate] yaml endpoint={model_cfg.base_url}", err=True)
    typer.echo(f"[02_translate] actual base_url={client.config.base_url}", err=True)
    typer.echo(f"[02_translate] api key prefix={client.config.api_key[:12]}...", err=True)
    semaphore = asyncio.Semaphore(max_concurrency)

    system_prompt = load_prompt(system_prompt_rel) if system_prompt_rel else None
    user_prompt = load_prompt(user_prompt_rel)

    # Read source paragraphs from JSON file (list of strings)
    paragraphs: list[str] = json.loads(input_json.read_text(encoding="utf-8"))

    out_dir = _build_out_dir(run_name=run_name, bucket=bucket)
    out_dir.mkdir(parents=True, exist_ok=True)
    progress_log = ProgressLog(out_dir / "progress.jsonl")
    done_chunks, done_paragraphs = progress_log.load()
    if done_chunks or done_paragraphs:
        typer.echo(
            f"[02_translate] resuming from progress.jsonl: "
            f"{len(done_chunks)} chunks, {len(done_paragraphs)} paragraphs already done",
            err=True,
        )

    # mode = dispatch_mode(PROMPTS / user_prompt_rel)
    failures = []

    # if mode == "chunked":
    #     chunks = json.loads(chunking.read_text(encoding="utf-8"))
    #     results, failures = await translate_chunked(
    #         paragraphs=paragraphs,
    #         chunks=chunks,
    #         client=client,
    #         system_prompt=system_prompt,
    #         user_prompt=user_prompt,
    #         semaphore=semaphore,
    #         max_retries=1,
    #         progress_log=progress_log,
    #     )
    # else:  # per_paragraph
    #     chunks = json.loads(chunking.read_text(encoding="utf-8"))
    #     # Each chunk span is [a, b] inclusive; `a != b` means it covers multiple paragraphs.
    #     if any(span[0] != span[1] for span in chunks.values()):
    #         typer.echo(
    #             "user-prompt is per-paragraph but chunking has multi-paragraph chunks. "
    #             "Use a {chunk}-based prompt or pass par_by_par.json.",
    #             err=True,
    #         )
    #         raise typer.Exit(2)
    results = await translate_per_paragraph(
        paragraphs=paragraphs,
        client=client,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        semaphore=semaphore,
        context_paragraphs=0,
        progress_log=progress_log,
    )

    if "openrouter.ai" in model_cfg.base_url:
        cache_strategy = "openrouter_ephemeral"
    elif "api.openai.com" in model_cfg.base_url:
        cache_strategy = "openai_auto"
    else:
        cache_strategy = "none"

    config = {
        "run_name": run_name,
        # "chunking_name": chunking.stem,
        "model_key": model_key,
        "model_name": model_cfg.name,
        "endpoint": model_cfg.base_url,
        "prompt_path": system_prompt_rel,
        "user_prompt_path": user_prompt_rel,
        "prompt_text": system_prompt,
        "user_prompt_text": user_prompt,
        "hyperparameters": {
            "temperature": model_cfg.temperature,
            "top_p": model_cfg.top_p,
            "top_k": model_cfg.top_k,
            "min_p": model_cfg.min_p,
            "reasoning_effort": model_cfg.reasoning_effort,
            "max_tokens": model_cfg.max_tokens,
            "extra_body": model_cfg.extra_body,
        },
        "cache_strategy": cache_strategy,
        "created_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    write_run_artifacts(
        out_dir=out_dir,
        results=results,
        failures=failures,
        config=config,
    )

    # if failures:
    #     n_chunks = len(chunks)
    #     n_failed_pars = sum(len(f.ru_paragraph_ids) for f in failures)
    #     typer.echo(
    #         f"{run_name}: {n_chunks - len(failures)}/{n_chunks} chunks ok, "
    #         f"{len(failures)} chunks ({n_failed_pars} paragraphs) failed; "
    #         f"see {(out_dir / 'failures.jsonl').relative_to(REPO_ROOT)}"
    #     )
    #     return 1
    # if mode == "chunked":
    #     typer.echo(f"{run_name}: {len(chunks)}/{len(chunks)} chunks ok")
    # else:
    #     typer.echo(f"{run_name}: {len(paragraphs)} paragraphs translated ok")
    # return 0


@app.command()
def main(
    chunking: Path = typer.Option(..., "--chunking", help="Path to chunking JSON."),  # noqa: B008
    run_name: str = typer.Option(..., "--run-name", help="Output subdir name."),  # noqa: B008
    bucket: str = typer.Option(  # noqa: B008
        "", "--bucket",
        help="Subfolder under data/pilot/translating/: small|large|local. Empty = legacy flat.",
    ),
    model: str | None = typer.Option(None, "--model", help="Model key from configs/models.yaml."),  # noqa: B008
    system_prompt: str | None = typer.Option(None, "--system-prompt", help="Path under prompts/."),  # noqa: B008
    user_prompt: str | None = typer.Option(None, "--user-prompt", help="Path under prompts/."),  # noqa: B008
    max_concurrency: int = typer.Option(32, "--max-concurrency"),  # noqa: B008
    input_json: Path = typer.Option(  # noqa: B008
        REPO_ROOT / "data" / "pilot" / "pilot_original.json",
        "--input",
        help="Source JSON file: a list of strings (one paragraph per string).",
    ),
) -> None:
    cfg = load_translate()
    code = asyncio.run(
        _run(
            # chunking=chunking,
            run_name=run_name,
            bucket=bucket,
            model_key=model or cfg.translator_model,
            system_prompt_rel=system_prompt or cfg.system_prompt,
            user_prompt_rel=user_prompt or cfg.user_prompt,
            max_concurrency=max_concurrency,
            input_json=input_json,
        )
    )
    raise typer.Exit(code)


if __name__ == "__main__":
    app()