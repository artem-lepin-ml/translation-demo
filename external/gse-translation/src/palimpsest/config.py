"""Typed access to YAML configs in configs/."""
from __future__ import annotations

import sys
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, model_validator

from .paths import CONFIGS


class ModelConfig(BaseModel):
    """Connection parameters for one model endpoint (OpenAI-compatible)."""

    name: str
    base_url: str
    api_key_env: str

    # Provider routing. None ⇒ infer from base_url (anthropic.com → anthropic SDK,
    # everything else → OpenAI-compatible chat/completions). Explicit "anthropic"
    # forces the Anthropic SDK path even when base_url points at a proxy
    # (CloseRouter, OpenRouter) — needed because OpenAI-compat bridges silently
    # drop tool-use / extended thinking semantics for Claude models.
    provider: str | None = None

    # Standard sampling params — all optional, sent only if explicitly set.
    # Optional because some models (e.g. Opus 4.7) reject `temperature` outright;
    # we don't want to fabricate a default the provider then rejects.
    # Qwen recommends top_k=20, min_p=0 for non-thinking mode.
    temperature: float | None = None
    top_p: float | None = None
    top_k: int | None = None
    min_p: float | None = None

    # OpenAI-specific top-level Chat Completions param.
    # Values: "minimal" | "low" | "medium" | "high" | "xhigh".
    # GPT-5.x reasoning > minimal forces temperature=1.0.
    reasoning_effort: str | None = None

    # Required — no default to avoid silent truncation when a yaml entry forgets it.
    max_tokens: int

    # Catch-all for provider-specific non-standard params (OR `reasoning` object,
    # vLLM `chat_template_kwargs`, etc.).
    extra_body: dict | None = None

    # Whether the underlying provider honors `response_format={"type":"json_object"}`
    # (OpenAI JSON mode / OpenRouter structured outputs). When True, callers that
    # pass `response_format` get JSON-mode constraint; when False, the param is
    # silently dropped at LLMClient layer so the call stays compatible with
    # providers that 400 on unknown params (e.g. local vLLM started without
    # guided-decoding). Default False — opt-in per model in models.yaml.
    supports_structured_output: bool = False

    # Whether to enable streaming responses (per-token chunks) for this model.
    # Off by default; callers that want streaming opt in per model in models.yaml.
    stream: bool = False


class FactcheckStageConfig(BaseModel):
    """Stage 03 standalone factcheck pipeline (configs/factcheck.yaml)."""

    extractor_model: str
    judge_model: str
    extraction_temperature: float = 0.0
    judge_temperature: float = 0.0
    few_shot_k: int = 3


class JudgeConfig(BaseModel):
    """One judge entry in a ScoringConfig — model_key from configs/models.yaml."""

    model_config = {"extra": "forbid"}

    model: str


class FactcheckConfig(BaseModel):
    """Factcheck stage — single fixed judge, independent of `judges` list."""

    enabled: bool = False
    judge: str = "gpt-5.4-mini-low"


class ScoringConfig(BaseModel):
    """Stage 04 scoring pipeline configuration."""

    base_dir: Path
    original_json: Path | None = None
    translation_json: Path | None = None
    translations_subdir: str = "translating"
    evaluation_subdir: str = "evaluation"
    prompts_root: Path = Path("prompts/03_scoring")
    prompts_variant: str = "v1"
    paragraph_subset: str | None = None
    max_concurrency: int = 64
    factcheck: FactcheckConfig = FactcheckConfig()
    judges: list[JudgeConfig] = Field(..., min_length=1)
    runs: list[str] = Field(..., min_length=1)

    @model_validator(mode="after")
    def _warn_if_variant_dir_missing(self) -> "ScoringConfig":
        variant_dir = self.prompts_root / self.prompts_variant
        if not variant_dir.is_dir() or not list(variant_dir.glob("*.md")):
            print(
                f"warning: prompts variant directory {variant_dir} "
                f"is missing or empty — load_prompts() will raise at runtime",
                file=sys.stderr,
                flush=True,
            )
        return self


class TranslateConfig(BaseModel):
    translator_model: str
    system_prompt: str | None
    user_prompt: str


class RefinementConfig(BaseModel):
    editor_model: str
    system_prompt: str
    refinement_criterias: list[str]


def _load_yaml(name: str) -> dict:
    return yaml.safe_load((CONFIGS / name).read_text(encoding="utf-8"))


def load_models() -> dict[str, ModelConfig]:
    data = _load_yaml("models.yaml")
    return {key: ModelConfig(**spec) for key, spec in data["models"].items()}


def load_factcheck() -> FactcheckStageConfig:
    return FactcheckStageConfig(**_load_yaml("factcheck.yaml"))


def load_translate() -> TranslateConfig:
    return TranslateConfig(**_load_yaml("translation.yaml"))


def load_refinement() -> RefinementConfig:
    return RefinementConfig(**_load_yaml("refinement.yaml"))


def load_scoring(path: Path) -> ScoringConfig:
    """Load Stage 04 scoring config from an explicit YAML path."""
    with path.open("r", encoding="utf-8") as f:
        return ScoringConfig(**yaml.safe_load(f))
