"""Spec 2026-07-05-export-xlsx: GET /api/documents/{id}/export?format=xlsx|md."""
from __future__ import annotations

import io

import openpyxl

from palimpsest.webapp import db
from palimpsest.webapp.export import SCORE_GREEN

from .conftest import _body


def _mk_doc(client, title="My Report"):
    body = _body(title=title, paragraphs=[
        {"source": "Erster Absatz.", "target": "First paragraph."},
        {"source": "Zweiter Absatz.", "target": "Second paragraph."},
    ])
    return client.post("/api/documents", json=body).json()


def test_export_404_unknown_document(client):
    r = client.get("/api/documents/999999/export?format=xlsx")
    assert r.status_code == 404


def test_export_422_unknown_format(client):
    doc = _mk_doc(client)
    r = client.get(f"/api/documents/{doc['id']}/export?format=pdf")
    assert r.status_code == 422


def test_export_xlsx_round_trips_and_headers(client):
    doc = _mk_doc(client)
    r = client.get(f"/api/documents/{doc['id']}/export?format=xlsx")
    assert r.status_code == 200
    assert r.headers["content-type"] == (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    assert "attachment" in r.headers["content-disposition"]
    assert f"-{doc['id']}.xlsx" in r.headers["content-disposition"]
    assert len(r.content) > 0

    wb = openpyxl.load_workbook(io.BytesIO(r.content))
    ws = wb["Translation"]
    assert ws["A1"].value == "¶"
    assert "Source" in ws["B1"].value
    assert "Translation" in ws["C1"].value
    assert ws["D1"].value == "Score"
    assert "My Report" in ws["A2"].value
    # header(1) + meta(2) + 2 data rows = 4
    assert ws.max_row == 4
    assert ws["A3"].value == 1
    assert ws["B3"].value == "Erster Absatz."
    assert ws["C3"].value == "First paragraph."


def test_export_xlsx_empty_target_cell_is_blank(client, monkeypatch):
    from palimpsest.webapp import translate
    monkeypatch.setattr(translate, "launch", lambda *a, **kw: None)
    body = {"title": "Draft", "sourceLang": "ru", "targetLang": "en", "precompute": False,
            "translate": True, "paragraphs": [{"source": "src", "target": ""}]}
    doc = client.post("/api/documents", json=body).json()
    translate._translating.discard(doc["id"])  # the no-op'd auto-launch never actually ran
    r = client.get(f"/api/documents/{doc['id']}/export?format=xlsx")
    wb = openpyxl.load_workbook(io.BytesIO(r.content))
    ws = wb["Translation"]
    assert ws["C3"].value in (None, "")


def test_export_xlsx_score_thresholds_colored(client):
    doc = _mk_doc(client)
    conn = db.connect()
    conn.execute("INSERT INTO criterion(id,name,weight,scale_min,scale_max,enabled) "
                 "VALUES('accuracy','Accuracy',1.0,1,10,1)")
    pid = doc["paragraphs"][0]["id"]
    conn.execute("INSERT INTO score(paragraph_id,criterion_id,value,aggregate,kind,created_at) "
                 "VALUES(?,'accuracy',9,9.0,'live','2026-01-01T00:00:00Z')", (pid,))
    conn.commit()
    r = client.get(f"/api/documents/{doc['id']}/export?format=xlsx")
    wb = openpyxl.load_workbook(io.BytesIO(r.content))
    ws = wb["Translation"]
    assert ws["D3"].value == 9.0
    # score 9.0 >= 8 → green band (_score_color); rgb carries an alpha prefix
    # openpyxl adds on save/reload, so match on the hex tail, not the full ARGB.
    assert ws["D3"].font.color.rgb.upper().endswith(SCORE_GREEN)


def test_export_md_table_and_escaping(client):
    body = _body(title="Esc", paragraphs=[
        {"source": "a | b", "target": "line1\nline2"},
    ])
    doc = client.post("/api/documents", json=body).json()
    r = client.get(f"/api/documents/{doc['id']}/export?format=md")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/markdown")
    assert f"-{doc['id']}.md" in r.headers["content-disposition"]
    text = r.content.decode("utf-8")
    assert "# Esc" in text
    assert "a \\| b" in text
    assert "line1<br>line2" in text


def test_export_slug_from_title_and_cyrillic_fallback(client):
    doc = client.post("/api/documents", json=_body(title="Тест документ")).json()
    r = client.get(f"/api/documents/{doc['id']}/export?format=md")
    disp = r.headers["content-disposition"]
    assert f"document-{doc['id']}.md" in disp
