"""Tests for scripts/bouquet_judge_rerun.py's `extra_body`/`t0_local` patch
(2026-07-09, docs/runbooks/sr004-local-eval-runbook.md): the minimal addition
that lets a `JudgeSpec` merge arbitrary request-body fields (e.g. vLLM's
`chat_template_kwargs.enable_thinking` toggle) into the payload, needed for
the sr004 local judges Table A wants (Qwen3-4B-Instruct-2507, Gemma-3-27B-it,
Qwen3.6-27B). Narrow, additive coverage -- not a full test suite for the
runner (none existed before this patch; the rest of the module's behavior is
unchanged).

scripts/ isn't a package -- import off its file path, same convention
tests/test_wiki_eval_runner.py already uses for scripts/wiki_eval.py.
"""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import bouquet_judge_rerun as bjr  # noqa: E402, I001


def test_t0_local_regime_sets_temperature_zero_and_no_reasoning_key():
    judge = bjr.JudgeSpec(slug="x", router_id="Qwen/Qwen3-4B-Instruct-2507", regime="t0_local")
    payload = bjr.build_payload(judge, "sys", "user")
    assert payload["temperature"] == 0
    assert "reasoning" not in payload


def test_t0_local_regime_with_extra_body_merges_chat_template_kwargs():
    judge = bjr.JudgeSpec(
        slug="qwen3.6-27b", router_id="Qwen/Qwen3.6-27B", regime="t0_local",
        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
    )
    payload = bjr.build_payload(judge, "sys", "user")
    assert payload["temperature"] == 0
    assert payload["chat_template_kwargs"] == {"enable_thinking": False}


def test_extra_body_none_by_default_is_a_noop_for_existing_regimes():
    judge = bjr.JudgeSpec(slug="x", router_id="deepseek/deepseek-v4-flash", regime="t0_no_reasoning")
    payload = bjr.build_payload(judge, "sys", "user")
    assert payload["temperature"] == 0
    assert payload["reasoning"] == {"enabled": False}
    assert "chat_template_kwargs" not in payload


def test_load_judges_parses_extra_body_from_yaml(tmp_path):
    cfg = tmp_path / "judges.yaml"
    cfg.write_text(
        "judges:\n"
        "  - slug: qwen3.6-27b\n"
        "    router_id: Qwen/Qwen3.6-27B\n"
        "    regime: t0_local\n"
        "    extra_body: {chat_template_kwargs: {enable_thinking: false}}\n"
        "  - slug: gemma-3-27b-it\n"
        "    router_id: google/gemma-3-27b-it\n"
        "    regime: t0_local\n",
        encoding="utf-8",
    )
    judges = bjr.load_judges(cfg)
    assert judges["qwen3.6-27b"].extra_body == {"chat_template_kwargs": {"enable_thinking": False}}
    assert judges["gemma-3-27b-it"].extra_body is None


def test_t0_local_is_a_known_regime():
    assert "t0_local" in bjr._REGIMES
