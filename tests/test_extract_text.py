import io

import docx as docx_lib

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _docx_bytes(paragraphs: list[str]) -> bytes:
    d = docx_lib.Document()
    for p in paragraphs:
        d.add_paragraph(p)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def test_extract_docx_ok(client):
    r = client.post("/api/documents/extract-text",
                    files={"file": ("a.docx", _docx_bytes(["Раз.", "", "Два."]), DOCX_MIME)})
    assert r.status_code == 200
    assert r.json() == {"text": "Раз.\n\nДва.", "nParagraphs": 2}


def test_reject_old_doc_415(client):
    r = client.post("/api/documents/extract-text",
                    files={"file": ("legacy.doc", b"\xd0\xcf\x11\xe0", "application/msword")})
    assert r.status_code == 415 and r.json()["detail"] == "unsupported_type:doc"


def test_reject_other_ext_415(client):
    r = client.post("/api/documents/extract-text", files={"file": ("a.pdf", b"%PDF", "application/pdf")})
    assert r.status_code == 415 and r.json()["detail"] == "unsupported_type"


def test_unparseable_422(client):
    r = client.post("/api/documents/extract-text", files={"file": ("a.docx", b"garbage", DOCX_MIME)})
    assert r.status_code == 422 and r.json()["detail"] == "unparseable_file"


def test_too_large_413(client):
    r = client.post("/api/documents/extract-text",
                    files={"file": ("a.docx", b"0" * (5 * 1024 * 1024 + 1), DOCX_MIME)})
    assert r.status_code == 413
