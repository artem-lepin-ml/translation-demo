"""Dark-theme HTML report + EN methodology draft for wiki-eval (W5).

``render_html`` turns a ``metrics.aggregate``-shaped dict into an HTML
fragment (project report palette, Tokyo Night dark, inline CSS only) showing
recall (3 modes), precision (P1/P2 unsliced, P3 only inside the
``resolved_by`` slice per spec Sec.4, plus the "P3\\exact" headline cell when
``metrics["precision"]`` carries a ``"p3_ex"`` key — see
``evaluation.metrics.aggregate_corpus``'s ``label_exists`` parameter), and
the stratum/resolved_by/type slice tables with raw n + Wilson CI; cells
below the underpowered threshold (``metrics.UNDERPOWERED_THRESHOLD``, n<30)
are greyed and flagged.

``methodology_draft`` returns the EN paper-draft paragraph verbatim, per the
project's "preserve chat formulations" convention. Canonical copy also in
docs/stages/wiki-eval.md § Methodology; keep byte-identical.
"""
from __future__ import annotations

import html as _html

MODE_LABELS = {"m1": "M1 strict", "m2": "M2 span-overlap", "m3": "M3 document"}
PRECISION_LABELS = {
    "p1": "P1 base",
    "p2": "P2 unique-word",
    "p3": "P3 label-justified",
    "p3_ex": "P3 label-justified (excl. exact-label path)",
}


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

def _cell_td(cell: dict) -> str:
    flag = ' <span class="flag">underpowered n&lt;30</span>' if cell.get("underpowered") else ""
    return (
        f'<td class="{_cell_class(cell)}">'
        f"{_fmt_value(cell)}"
        f'<div class="n">n={cell["total"]} matched={cell["matched"]} ci={_fmt_ci(cell)}{flag}</div>'
        f"</td>"
    )


def _recall_table(recall: dict, *, title: str) -> str:
    rows = "".join(
        f"<tr><td>{MODE_LABELS.get(mode, mode)}</td>{_cell_td(recall[mode])}</tr>"
        for mode in ("m1", "m2", "m3")
        if mode in recall
    )
    return (
        f"<h3>{_html.escape(title)}</h3>"
        '<table class="metrics"><thead><tr><th>mode</th><th>recall</th></tr></thead>'
        f"<tbody>{rows}</tbody></table>"
    )


def _precision_table(precision: dict, *, title: str) -> str:
    rows = "".join(
        f"<tr><td>{PRECISION_LABELS.get(variant, variant)}</td>{_cell_td(precision[variant])}</tr>"
        for variant in ("p1", "p2", "p3", "p3_ex")
        if variant in precision
    )
    return (
        f"<h3>{_html.escape(title)}</h3>"
        '<table class="metrics"><thead><tr><th>variant</th><th>precision</th></tr></thead>'
        f"<tbody>{rows}</tbody></table>"
    )


def _slice_section(axis: str, axis_slices: dict) -> str:
    parts = [f'<h2>Slice: {_html.escape(axis)}</h2>']
    for value, slice_result in sorted(axis_slices.items()):
        parts.append(f'<div class="slice-block">')
        parts.append(f"<h3>{_html.escape(axis)} = {_html.escape(str(value))}</h3>")
        parts.append(_recall_table(slice_result.get("recall", {}), title="Recall"))
        precision = slice_result.get("precision", {})
        if precision:
            note = ""
            if axis == "resolved_by":
                note = (
                    '<p class="note">P3 is reported only inside this resolved_by slice '
                    "(tautological on exact_label by construction, spec Sec.4).</p>"
                )
            parts.append(note + _precision_table(precision, title="Precision"))
        parts.append("</div>")
    return "".join(parts)


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


def render_html(metrics: dict, meta: dict) -> str:
    """Render the wiki-eval metrics report as a self-contained HTML fragment.

    ``metrics`` is shaped like ``evaluation.metrics.aggregate``'s output:
    ``{"recall": {...}, "precision": {...}, "slices": {"stratum": ..., "resolved_by": ..., "type": ...}}``.
    ``meta`` carries run identity (``run_id``, ``config``, article/tuple counts).
    Never raises on an empty (n=0) or underpowered (n<30) cell — both render
    as ``n/a`` / a greyed, flagged cell rather than crashing.
    """
    parts = [f"<style>{_CSS}</style>", '<div class="wiki-eval-report">']
    parts.append("<h1>Wiki-eval report</h1>")
    parts.append(
        '<div class="meta">'
        f'config <code>{_html.escape(str(meta.get("config", "?")))}</code> · '
        f'run_id <code>{_html.escape(str(meta.get("run_id", "?")))}</code> · '
        f'{_html.escape(str(meta.get("n_articles", "?")))} articles · '
        f'{_html.escape(str(meta.get("n_gt_tuples", "?")))} GT tuples · '
        f'generated {_html.escape(str(meta.get("generated_at", "?")))}'
        "</div>"
    )

    parts.append("<h2>Overall</h2>")
    parts.append(_recall_table(metrics.get("recall", {}), title="Recall (primary metric)"))
    precision = metrics.get("precision", {})
    precision_title = "Precision (P1/P2, unsliced)"
    precision_note = ""
    if "p3_ex" in precision:
        precision_title = "Precision (P1/P2 unsliced; P3\\exact headline)"
        precision_note = (
            '<p class="note">P3\\exact = label-justified precision over every prediction '
            "EXCEPT those resolved via exact_label (that path is tautologically justified "
            "by construction, spec Sec.4); the denominator excludes exact-label predictions, "
            "so this headline is not tautological.</p>"
        )
    parts.append(precision_note + _precision_table(precision, title=precision_title))

    slices = metrics.get("slices", {})
    for axis in ("stratum", "resolved_by", "type"):
        if axis in slices:
            parts.append(_slice_section(axis, slices[axis]))

    parts.append("</div>")
    return "".join(parts)


_V3_CLASS_LABELS = {"named": "Named entities", "term": "Terms (common-noun)"}


def _v3_cell_td(cell: dict) -> str:
    flag = ' <span class="flag">underpowered n&lt;30</span>' if cell.get("underpowered") else ""
    return (
        f'<td class="{_cell_class(cell)}">'
        f"{_fmt_value(cell)}"
        f'<div class="n">ci={_fmt_ci(cell)}{flag}</div>'
        f"</td>"
    )


def render_html_v3(result: dict, meta: dict) -> str:
    """Render a ``metrics.aggregate_corpus_v3``-shaped result as a
    self-contained HTML fragment (protocol v3, spec Sec.4.5/Р9): a header
    with run identity from ``meta``, and one table with a row per class
    (named/term) — gold_units, TP, FN, FP, R_doc, P_doc (value + Wilson CI).

    Methodology prose SSOT: docs/paper/sections/eval-metrics-terminology.tex
    (this renderer only formats numbers, it doesn't restate the formalism).
    """
    classes = result.get("classes", {})
    rows = "".join(
        f"<tr><td>{_html.escape(_V3_CLASS_LABELS.get(cls, cls))}</td>"
        f'<td class="cell">{s["gold_units"]}</td>'
        f'<td class="cell">{s["tp"]}</td>'
        f'<td class="cell">{s["fn"]}</td>'
        f'<td class="cell">{s["fp"]}</td>'
        f"{_v3_cell_td(s['R_doc'])}"
        f"{_v3_cell_td(s['P_doc'])}"
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
    parts.append("</div>")
    return "".join(parts)


def methodology_draft() -> str:
    """EN paper-draft methodology paragraph, verbatim.

    Kept verbatim per the project's "preserve chat formulations" convention —
    do not paraphrase or reflow. Canonical copy also in
    docs/stages/wiki-eval.md § Methodology; keep byte-identical.
    """
    return (
        "**Evaluation against Wikipedia link annotations.** We evaluate the "
        "terminology extraction-and-grounding component against human hyperlink "
        "annotations on 100 full Russian Wikipedia articles on ancient history, "
        "organised into ten fixed thematic sections (Sumer/Mesopotamia, Ancient "
        "Egypt, Assyria, the Hittite kingdom, Phoenicia, Achaemenid Iran, Ancient "
        "India, Ancient China, Ancient Greece, Ancient Rome), ten articles per "
        "section. Candidates from each section's category subtree pass a "
        "deterministic gate — at least 30 unique main-namespace links in body "
        "paragraphs, an earliest associated Wikidata date before 500 CE with "
        "undated pages kept, and a small instance-of blacklist for off-topic "
        "media pages — with a fixed random seed and first-section binding for "
        "pages reachable from several sections; because Wikipedia's category "
        "partition is noisy, a small off-period residue (≈3/100) survives the "
        "gate and is disclosed rather than curated post hoc. Each internal link "
        "whose target carries a Wikidata item yields a gold tuple *(token index, "
        "surface, QID)*; chronology targets (years, centuries) are excluded by "
        "target *P31*. We compare gold and predicted tuple sets under three "
        "matching modes — strict index, span overlap (primary), and "
        "document-level *(lemma, QID)* — normalizing surfaces with a shared "
        "casefold/ё-е/dash normalizer; the strict mode is a deliberate lower "
        "bound sensitive to multi-word anchor boundaries. Because human "
        "annotation is precise but incomplete, we treat **recall** as the "
        "primary metric; precision, measured against Wikipedia's non-exhaustive "
        "\"don't over-link\" convention, is a conservative lower bound and is "
        "reported under three complementary denominators: raw, unique-word (to "
        "offset the convention of not linking repeat mentions), and "
        "label-justified (a prediction absent from gold is credited when its "
        "surface exists as a Wikidata label — reported only per resolution "
        "path, since on the deterministic exact-label path it holds by "
        "construction). Reporting is sliced by thematic section, by the "
        "system's own resolution path (exact-label vs. LLM-disambiguated), and "
        "by entity type (named vs. lowercase term), each with per-cell Wilson "
        "95 % confidence intervals; underpowered cells are flagged and "
        "differences within the interval are not interpreted. A full ablation "
        "over the three retrieval/matching toggles (lemma expansion, search "
        "fallbacks, alias matching) estimates each component's marginal "
        "contribution via leave-one-in / leave-one-out. This gives a "
        "transparent, reproducible measurement of a deterministic-first "
        "grounding system without recourse to a black-box entity linker as "
        "the reference."
    )
