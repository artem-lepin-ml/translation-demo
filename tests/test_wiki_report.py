"""Tests for the wiki-eval protocol-v3 HTML report renderer.

Offline only: builds a fixture ``result`` dict shaped like
``metrics.aggregate_corpus``'s output and checks ``render_html`` embeds
the key numbers and survives a zero-total cell without crashing. The
mention-level ``render_html`` this file used to test was retired along with
``evaluation.metrics``'s mention-level aggregator (spec §7).
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


def _fixture_result() -> dict:
    return {
        "protocol": "v3",
        "n_ambiguous_gold_units": 3,
        "n_gold_mentions_dropped_by_tier": 12,
        "classes": {
            "named": {
                "tp": 100, "fn": 20, "fp": 30, "gold_units": 120,
                "R_doc": _cell(100, 120), "P_doc": _cell(100, 130),
            },
            "term": {
                # deliberately zero-total -> uninformative P_doc, not a crash
                "tp": 0, "fn": 0, "fp": 0, "gold_units": 0,
                "R_doc": _cell(0, 0), "P_doc": _cell(0, 0),
            },
        },
    }


def _fixture_meta() -> dict:
    return {
        "model": "google/gemini-3.1-flash-lite",
        "provider": "Google AI Studio",
        "run_id": "2026-07-10T00-00-00Z",
    }


def test_render_html_contains_class_counters_and_meta():
    html = render_html(_fixture_result(), _fixture_meta())
    assert "<html" not in html.lower()  # fragment, not a full document
    assert "120" in html  # named gold_units
    assert "Google AI Studio" in html
    assert "2026-07-10T00-00-00Z" in html
    assert "google/gemini-3.1-flash-lite" in html


def test_render_html_does_not_crash_on_zero_total_cell():
    html = render_html(_fixture_result(), _fixture_meta())
    assert "n/a" in html.lower()  # term class's zero-total P_doc/R_doc


def test_render_html_is_valid_looking_html_fragment():
    html = render_html(_fixture_result(), _fixture_meta())
    assert html.count("<table") == html.count("</table>")
    assert html.count("<div") == html.count("</div>")


def test_render_html_surfaces_ambiguous_and_dropped_tier_counters():
    html = render_html(_fixture_result(), _fixture_meta())
    assert "n_ambiguous_gold_units=3" in html
    assert "n_gold_mentions_dropped_by_tier=12" in html


def test_render_html_missing_meta_keys_render_placeholder_not_crash():
    html = render_html(_fixture_result(), {})
    assert "?" in html


def test_methodology_draft_returns_nonempty_string_matching_spec_phrase():
    text = methodology_draft()
    assert isinstance(text, str)
    assert len(text) > 200
    # distinctive phrase from spec Sec.7 (EN paper-draft section), verbatim
    assert "Evaluation against Wikipedia link annotations" in text
    assert "recall" in text.lower()
