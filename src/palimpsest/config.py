"""Typed access to YAML configs in configs/."""
from __future__ import annotations

import yaml
from pydantic import BaseModel

from .paths import CONFIGS


class ModelConfig(BaseModel):
    name: str
    base_url: str
    api_key_env: str
    temperature: float = 0.2
    max_tokens: int = 4096


class PipelineConfig(BaseModel):
    volume: int
    chapters: list[int]
    stages: list[str]
    context_window: int = 1
    draft_model: str
    terminology_model: str
    factcheck_model: str
    polish_model: str
    judge_models: list[str]


def _load_yaml(name: str) -> dict:
    return yaml.safe_load((CONFIGS / name).read_text(encoding="utf-8"))


def load_models() -> dict[str, ModelConfig]:
    data = _load_yaml("models.yaml")
    return {key: ModelConfig(**spec) for key, spec in data["models"].items()}


def load_pipeline() -> PipelineConfig:
    return PipelineConfig(**_load_yaml("pipeline.yaml"))
