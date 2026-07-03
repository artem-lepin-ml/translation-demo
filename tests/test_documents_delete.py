from palimpsest.webapp import db

from .conftest import _body


def test_delete_upload_204_and_cascade(client):
    doc = client.post("/api/documents", json=_body()).json()
    r = client.delete(f"/api/documents/{doc['id']}")
    assert r.status_code == 204
    assert client.get(f"/api/documents/{doc['id']}").status_code == 404
    conn = db.connect()
    assert conn.execute("SELECT COUNT(*) c FROM paragraph").fetchone()["c"] == 0


def test_delete_seed_409(client):
    conn = db.connect()
    conn.execute("INSERT INTO document(title,source_lang,target_lang,version,origin,created_at) "
                 "VALUES('seed doc','ru','en',0,'seed','now')")
    conn.commit()
    r = client.delete("/api/documents/1")
    assert r.status_code == 409 and r.json() == {"error": "seed_document"}


def test_delete_missing_404(client):
    assert client.delete("/api/documents/999").status_code == 404
