"""Paragraph subset loader for stage 03 scoring (spec S1-S4)."""
from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict


class Subset(BaseModel):
    """A named list of paragraph ids to evaluate.

    Lives at `<base_dir>/scoring_subsets/<name>.json`. Free-form metadata
    keys (`source_runs`, `created_at`, etc.) are tolerated for human use.
    """

    name: str
    description: str = ""
    paragraph_ids: list[int]

    model_config = ConfigDict(extra="allow")


def load_subset(name: str, base_dir: Path) -> Subset:
    """Load `<base_dir>/scoring_subsets/<name>.json` into a Subset."""
    path = base_dir / "scoring_subsets" / f"{name}.json"
    if not path.is_file():
        raise FileNotFoundError(
            f"scoring subset {name!r} not found at {path}"
        )
    return Subset.model_validate_json(path.read_text(encoding="utf-8"))
