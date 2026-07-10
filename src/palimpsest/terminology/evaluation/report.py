"""Dark-theme HTML report + EN methodology draft for wiki-eval (W5).

``render_html`` turns a ``metrics.aggregate_corpus``-shaped dict into
an HTML fragment (project report palette, Tokyo Night dark, inline CSS
only) showing document-level R_doc/P_doc per class (named/term) with raw
counts + Wilson CI; cells below the underpowered threshold
(``metrics.UNDERPOWERED_THRESHOLD``, n<30) are greyed and flagged. Protocol
v3 is the only protocol rendered here (wiki-eval experiment v2, spec
2026-07-10-wiki-eval-experiment-v2.md Р9/§7) — the mention-level recall/
precision/slice renderer this module used to carry was retired along with
``evaluation.metrics``'s mention-level aggregator.

When the ``result`` dict passed to ``render_html`` also carries a
``"survival"`` key (``metrics.aggregate_survival``'s output, pooled
factorized R_NER/R_search/A_disamb/R/R_direct/P), an additional section is
appended after the named/term table -- purely additive, the named/term
table's own markup is unchanged either way.
"""
from __future__ import annotations

import html as _html


def _fmt_value(cell: dict) -> str:
    if cell["value"] is None:
        return "n/a"
    return f"{cell['value']:.3f}"


def _fmt_ci(cell: dict) -> str:
    if cell["value"] is None:
        return "—"
    return f"[{cell['ci_lo']:.3f}, {cell['ci_hi']:.3f}]"


def _cell_class(cell: dict) -> str:
    return "cell underpowered" if cell.get("underpowered") else "cell"


_CSS = """
:root{
  --bg:#1a1b26; --bg2:#1f2335; --panel:#24283b; --line:#2f334d;
  --tx:#c0caf5; --tx2:#a9b1d6; --dim:#565f89; --mut:#787c99;
  --blue:#7aa2f7; --cyan:#2ac3de; --green:#9ece6a; --yel:#e0af68;
  --red:#f7768e; --purple:#bb9af7; --orange:#ff9e64;
}
.wiki-eval-report{background:var(--bg);color:var(--tx);font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;padding:24px}
.wiki-eval-report h1{font-size:24px;margin:0 0 6px}
.wiki-eval-report h2{font-size:18px;margin:32px 0 10px;padding-bottom:6px;border-bottom:1px solid var(--line)}
.wiki-eval-report h3{font-size:14px;margin:16px 0 6px;color:var(--tx2)}
.wiki-eval-report .meta{color:var(--mut);font-size:13px;margin-bottom:16px}
.wiki-eval-report table.metrics{width:100%;max-width:520px;border-collapse:collapse;margin:8px 0;font-size:13.5px}
.wiki-eval-report th,.wiki-eval-report td{border:1px solid var(--line);padding:6px 9px;text-align:left;vertical-align:top}
.wiki-eval-report th{background:var(--bg2);color:var(--tx2);font-weight:600}
.wiki-eval-report td.cell{background:var(--panel);font-weight:600}
.wiki-eval-report td.cell.underpowered{background:rgba(224,175,104,.08);color:var(--mut)}
.wiki-eval-report .n{font-weight:400;color:var(--mut);font-size:11.5px;margin-top:2px}
.wiki-eval-report .flag{color:var(--yel);font-weight:600}
.wiki-eval-report .slice-block{background:var(--bg2);border:1px solid var(--line);border-radius:10px;padding:12px 14px;margin:10px 0}
.wiki-eval-report .note{color:var(--mut);font-size:12.5px;margin:4px 0}
"""


_CLASS_LABELS = {"named": "Named entities", "term": "Terms (common-noun)"}


def _cell_td(cell: dict) -> str:
    flag = ' <span class="flag">underpowered n&lt;30</span>' if cell.get("underpowered") else ""
    return (
        f'<td class="{_cell_class(cell)}">'
        f"{_fmt_value(cell)}"
        f'<div class="n">ci={_fmt_ci(cell)}{flag}</div>'
        f"</td>"
    )


_SURVIVAL_ROWS = (
    ("R_NER", "Recognition survival"),
    ("R_search", "Candidate-search survival"),
    ("A_disamb", "Disambiguation accuracy"),
    ("R", "End-to-end recall (factorized)"),
    ("R_direct", "End-to-end recall (direct)"),
    ("P", "Precision (lower bound)"),
)


def _render_survival(survival: dict) -> str:
    rows = "".join(
        f"<tr><td>{_html.escape(label)}</td><td><code>{key}</code></td>"
        f"{_cell_td(survival[key])}</tr>"
        for key, label in _SURVIVAL_ROWS
    )
    parts = ["<h2>Survival-stage factorized metrics (pooled, unit = gold entity)</h2>"]
    parts.append(
        '<table class="metrics"><thead><tr>'
        "<th>stage</th><th>metric</th><th>value</th>"
        f"</tr></thead><tbody>{rows}</tbody></table>"
    )
    parts.append(
        '<p class="note">'
        f'n_gold_entities={survival.get("n_gold_entities", "?")} · '
        f'n_gold_mentions_dropped_by_tier={survival.get("n_gold_mentions_dropped_by_tier", "?")} · '
        f'n_gold_mentions_dropped_by_exclusion={survival.get("n_gold_mentions_dropped_by_exclusion", "?")} · '
        f'n_pred_linked_entities={survival.get("n_pred_linked_entities", "?")} · '
        f'n_resolved_correct_search_miss={survival.get("n_resolved_correct_search_miss", "?")}'
        "</p>"
    )
    return "".join(parts)


def render_html(result: dict, meta: dict) -> str:
    """Render a ``metrics.aggregate_corpus``-shaped result as a
    self-contained HTML fragment (protocol v3, spec Sec.4.5/Р9): a header
    with run identity from ``meta``, and one table with a row per class
    (named/term) — gold_units, TP, FN, FP, R_doc, P_doc (value + Wilson CI).
    A ``result["survival"]`` key (``metrics.aggregate_survival``'s output),
    when present, adds the pooled factorized-metrics section below it.

    Methodology prose SSOT: docs/paper/sections/eval-metrics-terminology.tex
    (this renderer only formats numbers, it doesn't restate the formalism).
    """
    classes = result.get("classes", {})
    rows = "".join(
        f"<tr><td>{_html.escape(_CLASS_LABELS.get(cls, cls))}</td>"
        f'<td class="cell">{s["gold_units"]}</td>'
        f'<td class="cell">{s["tp"]}</td>'
        f'<td class="cell">{s["fn"]}</td>'
        f'<td class="cell">{s["fp"]}</td>'
        f"{_cell_td(s['R_doc'])}"
        f"{_cell_td(s['P_doc'])}"
        f"</tr>"
        for cls, s in classes.items()
        if cls in ("named", "term")
    )

    parts = [f"<style>{_CSS}</style>", '<div class="wiki-eval-report">']
    parts.append("<h1>Wiki-eval report (protocol v3)</h1>")
    parts.append(
        '<div class="meta">'
        f'model <code>{_html.escape(str(meta.get("model", "?")))}</code> · '
        f'provider <code>{_html.escape(str(meta.get("provider", "?")))}</code> · '
        f'run_id <code>{_html.escape(str(meta.get("run_id", "?")))}</code>'
        "</div>"
    )
    parts.append("<h2>Document-level R_doc / P_doc (set-based, named vs term)</h2>")
    parts.append(
        '<table class="metrics"><thead><tr>'
        "<th>class</th><th>gold_units</th><th>TP</th><th>FN</th><th>FP</th>"
        "<th>R_doc</th><th>P_doc</th>"
        f"</tr></thead><tbody>{rows}</tbody></table>"
    )
    parts.append(
        '<p class="note">'
        f'n_ambiguous_gold_units={result.get("n_ambiguous_gold_units", "?")} · '
        f'n_gold_mentions_dropped_by_tier={result.get("n_gold_mentions_dropped_by_tier", "?")}'
        "</p>"
    )
    survival = result.get("survival")
    if survival is not None:
        parts.append(_render_survival(survival))
    parts.append("</div>")
    return "".join(parts)
