"""Canonical filesystem paths for the project."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = ROOT

DATA = ROOT / "data"
RAW = DATA / "raw"
INTERIM = DATA / "interim"
PROCESSED = DATA / "processed"

PROMPTS = ROOT / "prompts"
CONFIGS = ROOT / "configs"
REPORTS = ROOT / "reports"
REFERENCES = ROOT / "references"


def chapter_dir(volume: int, chapter: int, stage: str | None = None) -> Path:
    base = PROCESSED / f"vol{volume:02d}" / f"ch{chapter:02d}"
    return base / stage if stage else base


def _split_run(run: str) -> tuple[str, str]:
    """`<bucket>/<run_name>` -> ('bucket', 'run_name'). Raises if malformed."""
    parts = run.split("/")
    if len(parts) != 2:
        raise ValueError(f"run must be '<bucket>/<run_name>', got {run!r}")
    return parts[0], parts[1]


def translation_md(base_dir: Path, translations_subdir: str, run: str) -> Path:
    bucket, run_name = _split_run(run)
    return base_dir / translations_subdir / bucket / run_name / "translation.md"


def evaluation_run_dir(base_dir: Path, evaluation_subdir: str, run: str) -> Path:
    """data/pilot/evaluation/<run_name>/   (bucket dropped — run_name globally unique)"""
    _, run_name = _split_run(run)
    return base_dir / evaluation_subdir / run_name


def variant_dir(base_dir: Path, evaluation_subdir: str, run: str, variant: str) -> Path:
    return evaluation_run_dir(base_dir, evaluation_subdir, run) / variant


def judge_dir(
    base_dir: Path, evaluation_subdir: str, run: str, variant: str, judge: str
) -> Path:
    return variant_dir(base_dir, evaluation_subdir, run, variant) / judge


def criterion_jsonl(
    base_dir: Path,
    evaluation_subdir: str,
    run: str,
    variant: str,
    judge: str,
    criterion: str,
) -> Path:
    return judge_dir(base_dir, evaluation_subdir, run, variant, judge) / f"{criterion}_scores.jsonl"


def parse_failures_jsonl(
    base_dir: Path, evaluation_subdir: str, run: str, variant: str, judge: str
) -> Path:
    """Diagnostic log for criterion-prompt parse failures. Append-only."""
    return judge_dir(base_dir, evaluation_subdir, run, variant, judge) / "parse_failures.jsonl"


def reports_dir(base_dir: Path, evaluation_subdir: str, run: str, variant: str) -> Path:
    return variant_dir(base_dir, evaluation_subdir, run, variant) / "reports"


def report_jsonl(
    base_dir: Path, evaluation_subdir: str, run: str, variant: str, judge: str
) -> Path:
    """Per-judge full-report jsonl. Derived from criterion_jsonl files (spec S8)."""
    return reports_dir(base_dir, evaluation_subdir, run, variant) / f"{judge}.jsonl"


def comparison_jsonl(
    base_dir: Path, evaluation_subdir: str, run: str, variant: str
) -> Path:
    """Side-by-side judge comparison jsonl. Derived (spec S8)."""
    return variant_dir(base_dir, evaluation_subdir, run, variant) / "comparison.jsonl"


def factcheck_dir(base_dir: Path, evaluation_subdir: str, run: str) -> Path:
    """Outside variant scope — factcheck is shared across variants."""
    return evaluation_run_dir(base_dir, evaluation_subdir, run) / "factcheck"


def factcheck_jsonl(base_dir: Path, evaluation_subdir: str, run: str) -> Path:
    return factcheck_dir(base_dir, evaluation_subdir, run) / "factcheck_scores.jsonl"
