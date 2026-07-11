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

import argparse
import json
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


def _write_minimal_stats(judge_dir: Path, judge_slug: str) -> None:
    """A one-system/one-criterion stats.json, just enough for
    `build_summary_md` to emit a row (`c["n"] == 0` rows are skipped)."""
    judge_dir.mkdir(parents=True, exist_ok=True)
    stats = {
        "judge_slug": judge_slug,
        "generated_at": "2026-07-09T00:00:00+00:00",
        "n_paragraphs_total": 1,
        "systems": {
            "qwen-27b-bouquet": {
                criterion: {
                    "n": 1 if criterion == "accuracy" else 0,
                    "mean": 8.0 if criterion == "accuracy" else None,
                    "tie_rate_9_10": 0.0 if criterion == "accuracy" else None,
                    "spearman": {
                        "metricx_ref": {"rho": None, "n": 0},
                        "metricx_qe": {"rho": None, "n": 0},
                        "comet": {"rho": None, "n": 0},
                    },
                }
                for criterion in bjr.CRITERIA
            }
        },
    }
    (judge_dir / "stats.json").write_text(json.dumps(stats), encoding="utf-8")


def test_cmd_stats_with_explicit_judge_keeps_other_judges_in_summary(tmp_path, monkeypatch):
    """Regression for the 2026-07-09 bug: `stats --judge <one>` must not wipe
    the other judges' rows from summary.md -- --judge scopes only the stats
    recomputation, summary.md is always rebuilt from every judge dir on disk
    that has a stats.json."""
    out_dir = tmp_path / "judges"
    for slug in ("judge-a", "judge-b"):
        judge_dir = out_dir / slug
        judge_dir.mkdir(parents=True)
        (judge_dir / "scores.jsonl").write_text(
            json.dumps({
                "judge_slug": slug, "system": "qwen-27b-bouquet", "id": 0,
                "criterion": "accuracy", "score": 8,
            }) + "\n",
            encoding="utf-8",
        )
        _write_minimal_stats(judge_dir, slug)

    original = ["source paragraph"]
    monkeypatch.setattr(bjr, "_load_original", lambda: original)

    def fake_compute_stats_for_judge(judge_slug, out_dir, eval_root, systems):
        return json.loads((out_dir / judge_slug / "stats.json").read_text(encoding="utf-8"))

    monkeypatch.setattr(bjr, "compute_stats_for_judge", fake_compute_stats_for_judge)
    # `--judge` is validated against the judge registry YAML before scoping
    # the recomputation -- stub it so the fake "judge-a"/"judge-b" slugs pass.
    monkeypatch.setattr(bjr, "load_judges", lambda path: {"judge-a": object(), "judge-b": object()})
    # cmd_stats logs paths via `.relative_to(ROOT)`; tmp_path lives outside
    # the real repo root, so point ROOT at tmp_path for this test only.
    monkeypatch.setattr(bjr, "ROOT", tmp_path)

    args = argparse.Namespace(
        judge=["judge-a"], config=bjr.DEFAULT_JUDGE_CONFIG, system=None,
        out_dir=out_dir, eval_root=bjr.DEFAULT_EVAL_ROOT,
    )
    rc = bjr.cmd_stats(args)
    assert rc == 0

    summary = (out_dir / "summary.md").read_text(encoding="utf-8")
    assert "judge-a" in summary
    assert "judge-b" in summary, "stats --judge judge-a must not drop judge-b from summary.md"
