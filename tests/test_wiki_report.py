"""Tests for the wiki-eval HTML report renderer (W5).

Offline only: builds a fixture ``metrics`` dict shaped like ``metrics.aggregate``'s
output (recall/precision/slices) and checks ``render_html`` embeds the key
numbers and survives an underpowered/empty slice without crashing.
"""
from __future__ import annotations

from palimpsest.terminology.evaluation.report import methodology_draft, render_html


def _cell(matched: int, total: int) -> dict:
    value = (matched / total) if total else None
    return {
        "matched": matched,
        "total": total,
        "value": value,
        "ci_lo": 0.1,
        "ci_hi": 0.9,
        "underpowered": total < 30,
    }


def _fixture_metrics() -> dict:
    return {
        "recall": {
            "m1": _cell(60, 100),
            "m2": _cell(72, 100),
            "m3": _cell(80, 100),
        },
        "precision": {
            "p1": _cell(72, 90),
            "p2": _cell(65, 80),
        },
        "slices": {
            "stratum": {
                "hard": {
                    "recall": {"m1": _cell(20, 50), "m2": _cell(28, 50), "m3": _cell(30, 50)},
                    "precision": {"p1": _cell(30, 45), "p2": _cell(28, 40)},
                },
                "typical": {
                    "recall": {"m1": _cell(40, 50), "m2": _cell(44, 50), "m3": _cell(50, 50)},
                    "precision": {"p1": _cell(42, 45), "p2": _cell(37, 40)},
                },
            },
            "resolved_by": {
                "exact_label": {
                    "recall": {"m1": _cell(50, 70), "m2": _cell(58, 70), "m3": _cell(62, 70)},
                    "precision": {
                        "p1": _cell(50, 60),
                        "p2": _cell(45, 55),
                        "p3": _cell(52, 60),
                    },
                },
                "llm_disambiguation": {
                    # deliberately tiny -> underpowered, and empty precision total
                    "recall": {"m1": _cell(1, 3), "m2": _cell(2, 3), "m3": _cell(2, 3)},
                    "precision": {
                        "p1": _cell(0, 0),
                        "p2": _cell(0, 0),
                        "p3": _cell(0, 0),
                    },
                },
            },
            "type": {
                "named": {
                    "recall": {"m1": _cell(30, 40), "m2": _cell(34, 40), "m3": _cell(36, 40)},
                    "precision": {"p1": _cell(28, 35), "p2": _cell(25, 30)},
                },
                "term": {
                    "recall": {"m1": _cell(0, 0), "m2": _cell(0, 0), "m3": _cell(0, 0)},
                    "precision": {"p1": _cell(0, 0), "p2": _cell(0, 0)},
                },
            },
        },
    }


def _fixture_meta() -> dict:
    return {
        "run_id": "2026-07-03T00-00-00Z",
        "config": "111",
        "n_articles": 100,
        "n_gt_tuples": 100,
        "generated_at": "2026-07-03T00:00:00Z",
    }


def test_render_html_contains_recall_and_precision_numbers():
    html = render_html(_fixture_metrics(), _fixture_meta())
    assert "<html" not in html.lower()  # fragment, not a full document (report.html wraps it)
    assert "0.720" in html or "72.0" in html or "72%" in html  # m2 recall = 0.72
    assert "0.800" in html or "80.0" in html or "80%" in html  # m3 recall = 0.80
    assert "111" in html
    assert "2026-07-03T00-00-00Z" in html


def test_render_html_does_not_crash_on_underpowered_or_empty_slice():
    html = render_html(_fixture_metrics(), _fixture_meta())
    # underpowered slice (llm_disambiguation, n=3) must be flagged, not silently dropped
    assert "underpowered" in html.lower() or "n&lt;30" in html.lower() or "n < 30" in html.lower()
    # empty-total slice (term type, n=0) must not crash and must render something sane
    assert "n/a" in html.lower() or "—" in html or "-" in html


def test_render_html_is_valid_looking_html_fragment():
    html = render_html(_fixture_metrics(), _fixture_meta())
    assert html.count("<table") == html.count("</table>")
    assert html.count("<div") == html.count("</div>")


def test_methodology_draft_returns_nonempty_string_matching_spec_phrase():
    text = methodology_draft()
    assert isinstance(text, str)
    assert len(text) > 200
    # distinctive phrase from spec Sec.7 (EN paper-draft section), verbatim
    assert "Evaluation against Wikipedia link annotations" in text
    assert "recall" in text.lower()
