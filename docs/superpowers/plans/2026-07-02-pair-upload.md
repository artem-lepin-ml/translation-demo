# План реализации: загрузка собственной пары «оригинал — перевод»

Up-link: [спека rev-4](../specs/2026-07-02-custom-pair-upload-design.md) · [docs/subsystems/webapp.md](../../subsystems/webapp.md)

**Цель:** пользователь загружает свою пару «оригинал — перевод» (вставка или файл .docx/.md/.txt), явно задаёт языки — и получает полноценный документ с оценкой, issues, reset и фоновым прогревом кеша.

**Архитектура:** бекенд получает три эндпоинта (`POST /api/documents`, `DELETE /api/documents/{id}`, `POST /api/documents/extract-text`), колонку `document.origin`, каскадные FK и фоновый модуль `precompute.py`; судья принимает языковую пару. Фронтенд получает переключатель документов, двухшаговую модалку загрузки (панели с textarea + файл, превью выравнивания) и правило дельты «только старый → новый». Все контракты, строки ошибок, testid'ы и правила UI зафиксированы в [спеке rev-4](../specs/2026-07-02-custom-pair-upload-design.md) — план ссылается на её разделы.

**Стек:** FastAPI + SQLite (`--workers 1`), python-docx, python-multipart; React + Zustand + TipTap, vite; pytest, vitest.

**Порядок и параллелизм:** задачи 1→7 — бекенд (цепочка 1→2→3, задачи 4–6 независимы после 1, задача 7 после 2+5+6); задачи 8→13 — фронтенд (8 можно начинать параллельно с бекендом по контрактам спеки; 9–11 после 8; 12 после 6+8; 13 после 10–11). Задача 14 (доки) — сквозная: строка в webapp.md добавляется в том же коммите, что и эндпоинт (задачи 2–4, 7); задача 14 — финальная сверка. Задача 15 — последняя.

⚠️ Задачи 7 и частично 2 (create → прогрев) — budget-critical: на этапе verify ревьюить с особым вниманием (реальные деньги).

---

## Задача 1: DDL — `origin` + `ON DELETE CASCADE` + сериализаторы [S]

**Спека:** §5.2, решение №8.
**Файлы:** Modify [src/palimpsest/webapp/db.py](../../../src/palimpsest/webapp/db.py), [src/palimpsest/webapp/seed.py](../../../src/palimpsest/webapp/seed.py), [src/palimpsest/webapp/app.py](../../../src/palimpsest/webapp/app.py); Test `tests/test_db.py` (дописать).

**Шаг 1 — тест (TDD, падает):** добавить в `tests/test_db.py`:

```python
def test_document_origin_default_and_cascade(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(db, "_conn", None)
    conn = db.init_db(reset=True)
    conn.execute("INSERT INTO criterion(id,name) VALUES('accuracy','Accuracy')")
    doc = conn.execute(
        "INSERT INTO document(title,source_lang,target_lang,version,created_at) "
        "VALUES('t','ru','en',0,'now')").lastrowid
    assert conn.execute("SELECT origin FROM document WHERE id=?", (doc,)).fetchone()["origin"] == "seed"
    pid = conn.execute(
        "INSERT INTO paragraph(document_id,idx,source,target,seed_target) VALUES(?,0,'s','t','t')",
        (doc,)).lastrowid
    conn.execute(
        "INSERT INTO score(paragraph_id,criterion_id,value,kind,created_at) VALUES(?,'accuracy',5,'seed','now')",
        (pid,))
    conn.execute(
        "INSERT INTO issue(paragraph_id,criterion_id,explanation,status,kind,created_at) "
        "VALUES(?,'accuracy','e','open','seed','now')", (pid,))
    conn.execute(
        "INSERT INTO term(paragraph_id,source_surface,char_start,char_end) VALUES(?,'x',0,1)", (pid,))
    conn.execute("DELETE FROM document WHERE id=?", (doc,))
    conn.commit()
    for table in ("paragraph", "score", "issue", "term"):
        assert conn.execute(f"SELECT COUNT(*) c FROM {table}").fetchone()["c"] == 0
```

`uv run pytest tests/test_db.py -q` → падает (`IntegrityError` / нет колонки `origin`).

**Шаг 2 — реализация.** В `db.py` SCHEMA:

```sql
CREATE TABLE document (
  id INTEGER PRIMARY KEY, title TEXT, source_lang TEXT, target_lang TEXT,
  source_model TEXT, seed_model TEXT, seed_prompt_variant TEXT,
  version INTEGER DEFAULT 0, origin TEXT DEFAULT 'seed', created_at TEXT
);
CREATE TABLE paragraph (
  id INTEGER PRIMARY KEY, document_id INTEGER REFERENCES document(id) ON DELETE CASCADE,
  idx INTEGER, source TEXT, target TEXT, seed_target TEXT
);
```

и в `score`/`issue`/`term`: `paragraph_id INTEGER REFERENCES paragraph(id) ON DELETE CASCADE`.

В `seed.py` — INSERT документа получает колонку:

```python
doc_id = conn.execute(
    "INSERT INTO document(title,source_lang,target_lang,source_model,seed_model,"
    "seed_prompt_variant,version,origin,created_at) VALUES(?,?,?,?,?,?,0,'seed',?)",
    ("Mesopotamia — ancient Near East (pilot)", "ru", "en", "gpt-5.4-mini",
     "gpt-5.5-low", "v2", ts)).lastrowid
```

В `app.py` `_doc_summary` — добавить в возвращаемый dict:

```python
    return {"id": d["id"], "title": d["title"], "sourceLang": d["source_lang"],
            "targetLang": d["target_lang"], "nParagraphs": n, "origin": d["origin"]}
```

(`_doc_dict` наследует через `**_doc_summary(...)`; поле `precompute` добавит задача 7.)

**Шаг 3 — пересид и тесты:**

```
uv run python -m palimpsest.webapp.seed        # пересоздаёт demo.db с новой схемой
uv run pytest tests/test_db.py tests/test_seed_registry.py -q   # ожидаем: all passed
```

**Коммит:** `feat(webapp): add document.origin and ON DELETE CASCADE to child FKs`

---

## Задача 2: `POST /api/documents` [M]

**Спека:** §5.1 (тело, коды, семантика вставки), §5.7 (валидации).
**Файлы:** Modify `src/palimpsest/webapp/app.py`, [docs/subsystems/webapp.md](../../subsystems/webapp.md) (строка в таблицу API — тот же коммит); Create `tests/test_documents_create.py`.

**Шаг 1 — тест (падает):**

```python
import pytest
from fastapi.testclient import TestClient

from palimpsest.webapp import db
from palimpsest.webapp.app import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "demo.db")
    monkeypatch.setattr(db, "_conn", None)
    db.init_db(reset=True)
    return TestClient(app)


def _body(**over):
    base = {"title": "Test pair", "sourceLang": "de", "targetLang": "fr", "precompute": False,
            "paragraphs": [{"source": "Ein Absatz.", "target": "Un paragraphe."}]}
    base.update(over)
    return base


def test_create_201_full_doc(client):
    r = client.post("/api/documents", json=_body())
    assert r.status_code == 201
    doc = r.json()
    assert doc["origin"] == "upload"
    assert (doc["sourceLang"], doc["targetLang"]) == ("de", "fr")
    assert doc["aggregate"] is None and len(doc["paragraphs"]) == 1
    # seed_target = загруженный перевод → reset совместим (спека §2 п.9)
    pid = doc["paragraphs"][0]["id"]
    row = db.connect().execute("SELECT * FROM paragraph WHERE id=?", (pid,)).fetchone()
    assert row["seed_target"] == "Un paragraphe."


def test_same_language_422(client):
    r = client.post("/api/documents", json=_body(targetLang="de"))
    assert r.status_code == 422 and r.json()["detail"] == "same_language"


def test_bad_lang_422(client):
    assert client.post("/api/documents", json=_body(sourceLang="xx")).json()["detail"] == "bad_lang_code"


def test_empty_cell_422_with_index(client):
    r = client.post("/api/documents", json=_body(
        paragraphs=[{"source": "a", "target": "b"}, {"source": "c", "target": "  "}]))
    assert r.status_code == 422 and r.json()["detail"] == "empty_cell:1"


def test_too_many_paragraphs_422(client):
    paras = [{"source": f"s{i}", "target": f"t{i}"} for i in range(41)]
    assert client.post("/api/documents", json=_body(paragraphs=paras)).json()["detail"] == "too_many_paragraphs"


def test_paragraph_too_long_422(client):
    paras = [{"source": "x" * 4001, "target": "t"}]
    assert client.post("/api/documents", json=_body(paragraphs=paras)).json()["detail"] == "paragraph_too_long:0"


def test_title_required_422(client):
    assert client.post("/api/documents", json=_body(title="  ")).json()["detail"] == "title_required"


def test_listed_in_documents(client):
    client.post("/api/documents", json=_body())
    docs = client.get("/api/documents").json()
    assert [d["origin"] for d in docs] == ["upload"]
```

**Шаг 2 — реализация** (в `app.py`, рядом с document-роутами; `async def` — задача 7 добавит сюда `asyncio.create_task`):

```python
LANG_CODES = {"ru", "en", "de", "fr", "es", "it", "pt", "pl", "uk", "zh", "ja", "ar"}
MAX_PARAGRAPHS = 40
MAX_PARA_CHARS = 4000


class ParagraphPairBody(BaseModel):
    source: str
    target: str


class CreateDocumentBody(BaseModel):
    title: str
    sourceLang: str
    targetLang: str
    precompute: bool = True
    paragraphs: list[ParagraphPairBody]


@app.post("/api/documents", status_code=201)
async def create_document(body: CreateDocumentBody) -> dict:
    if not body.title.strip() or len(body.title) > 120:
        raise HTTPException(422, "title_required")
    if body.sourceLang not in LANG_CODES or body.targetLang not in LANG_CODES:
        raise HTTPException(422, "bad_lang_code")
    if body.sourceLang == body.targetLang:
        raise HTTPException(422, "same_language")
    if not body.paragraphs:
        raise HTTPException(422, "empty_paragraphs")
    if len(body.paragraphs) > MAX_PARAGRAPHS:
        raise HTTPException(422, "too_many_paragraphs")
    for i, pair in enumerate(body.paragraphs):
        if not pair.source.strip() or not pair.target.strip():
            raise HTTPException(422, f"empty_cell:{i}")
        if len(pair.source) > MAX_PARA_CHARS or len(pair.target) > MAX_PARA_CHARS:
            raise HTTPException(422, f"paragraph_too_long:{i}")
    conn = db.connect()
    with db._lock:
        doc_id = conn.execute(
            "INSERT INTO document(title,source_lang,target_lang,source_model,version,origin,created_at) "
            "VALUES(?,?,?,'user',0,'upload',?)",
            (body.title.strip(), body.sourceLang, body.targetLang, _now())).lastrowid
        for idx, pair in enumerate(body.paragraphs):
            conn.execute(
                "INSERT INTO paragraph(document_id,idx,source,target,seed_target) VALUES(?,?,?,?,?)",
                (doc_id, idx, pair.source.strip(), pair.target.strip(), pair.target.strip()))
        conn.commit()
        d = conn.execute("SELECT * FROM document WHERE id=?", (doc_id,)).fetchone()
        return _doc_dict(conn, d)
```

**Шаг 3:** `uv run pytest tests/test_documents_create.py -q` → `8 passed`. Строка в webapp.md (таблица API): `| POST | /api/documents | Создать пользовательский документ (публичный; спека §5.1) |`.

**Коммит:** `feat(webapp): add public POST /api/documents for user-uploaded pairs`

---

## Задача 3: `DELETE /api/documents/{doc_id}` [S]

**Спека:** §5.1 (коды, дискриминаторы L1), решение №8.
**Файлы:** Modify `src/palimpsest/webapp/app.py`, webapp.md (строка API); Create `tests/test_documents_delete.py`.

**Шаг 1 — тест (падает):**

```python
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
```

(фикстуры `client`/`_body` — импортом из `tests/test_documents_create.py` или общий `tests/conftest.py`; предпочесть conftest.)

**Шаг 2 — реализация:**

```python
@app.delete("/api/documents/{doc_id}", status_code=204)
def delete_document_route(doc_id: int):
    conn = db.connect()
    if doc_id in _evaluating:
        return JSONResponse({"error": "evaluate_in_flight"}, status_code=409)
    with db._lock:
        d = conn.execute("SELECT * FROM document WHERE id=?", (doc_id,)).fetchone()
        if not d:
            raise HTTPException(404, "document not found")
        if d["origin"] == "seed":
            return JSONResponse({"error": "seed_document"}, status_code=409)
        conn.execute("DELETE FROM document WHERE id=?", (doc_id,))
        conn.commit()
```

Имя `delete_document_route` — чтобы не конфликтовать с существующим `delete_model`-стилем и `deleteDocument` фронта. Бегущий прогрев останавливать явно не нужно: его цикл проверяет существование документа перед каждым абзацем (задача 7).

**Шаг 3:** `uv run pytest tests/test_documents_delete.py -q` → `3 passed`. Строка в webapp.md.

**Коммит:** `feat(webapp): add DELETE /api/documents/{doc_id} for uploaded docs`

---

## Задача 4: `POST /api/documents/extract-text` + зависимости [M]

**Спека:** §5.1, §5.4 (.docx — сервер), решение №6 (таблицы вне скоупа).
**Файлы:** Modify `pyproject.toml` (через uv), `src/palimpsest/webapp/app.py`, webapp.md; Create `tests/test_extract_text.py`.

**Шаг 1 — зависимости:**

```
uv add python-docx python-multipart
```

Ожидаем: обе появляются в `[project.dependencies]` (в `uv.lock` уже были транзитивно).

**Шаг 2 — тест (падает):**

```python
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
```

**Шаг 3 — реализация** (импорты `io`, `docx` — на верх модуля):

```python
MAX_DOCX_BYTES = 5 * 1024 * 1024


@app.post("/api/documents/extract-text")
async def extract_text(file: UploadFile = File(...)) -> dict:
    name = (file.filename or "").lower()
    if name.endswith(".doc"):
        raise HTTPException(415, "unsupported_type:doc")   # UI: «Сохраните как .docx…» (спека §5.5)
    if not name.endswith(".docx"):
        raise HTTPException(415, "unsupported_type")
    data = await file.read()
    if len(data) > MAX_DOCX_BYTES:
        raise HTTPException(413, "file_too_large")
    try:
        document = docx.Document(io.BytesIO(data))
    except Exception as exc:                     # python-docx кидает разные типы на битом zip
        raise HTTPException(422, "unparseable_file") from exc
    paras = [p.text.strip() for p in document.paragraphs if p.text.strip()]
    return {"text": "\n\n".join(paras), "nParagraphs": len(paras)}
```

Stateless: в БД не пишет. Таблицы/колонтитулы/картинки не извлекаются (решение №6).

**Шаг 4:** `uv run pytest tests/test_extract_text.py -q` → `5 passed`. Строка в webapp.md.

**Коммит:** `feat(webapp): add POST /api/documents/extract-text for .docx ingestion`

---

## Задача 5: языковая пара в судье [M]

**Спека:** §5.3, решение №4.
**Файлы:** Modify `src/palimpsest/webapp/judge.py`, `src/palimpsest/webapp/app.py`; Create `tests/test_judge_lang.py`.

**Шаг 1 — тест (падает):**

```python
from palimpsest import paths
from palimpsest.webapp.judge import judge_one, scoring_system_prompt


class FakeClient:
    def __init__(self):
        self.calls = []

    def complete(self, system, user):
        self.calls.append((system, user))

        class R:
            content = '{"final_score": 7, "summary": "s", "identified_issues": []}'
            usage = None
        return R()


def test_ru_en_prompt_byte_identical():
    disk = (paths.PROMPTS / "scoring" / "accuracy.md").read_text(encoding="utf-8")
    assert scoring_system_prompt("accuracy", "ru", "en") == disk


def test_other_pair_gets_adapter_preamble():
    p = scoring_system_prompt("accuracy", "de", "fr")
    assert p.startswith("This rubric was written for Russian→English.")
    assert "German→French" in p
    assert p.endswith((paths.PROMPTS / "scoring" / "accuracy.md").read_text(encoding="utf-8"))


def test_user_message_labels():
    c = FakeClient()
    judge_one(c, "accuracy", "Quelltext", "cible", source_lang="de", target_lang="fr")
    _, user = c.calls[0]
    assert user.startswith("[SOURCE DE]\nQuelltext")
    assert "[TRANSLATION FR]\ncible" in user


def test_default_is_ru_en():
    c = FakeClient()
    judge_one(c, "accuracy", "рус", "eng")
    _, user = c.calls[0]
    assert "[SOURCE RU]" in user and "[TRANSLATION EN]" in user
```

**Шаг 2 — реализация в `judge.py`:**

```python
LANG_NAMES = {"ru": "Russian", "en": "English", "de": "German", "fr": "French",
              "es": "Spanish", "it": "Italian", "pt": "Portuguese", "pl": "Polish",
              "uk": "Ukrainian", "zh": "Chinese", "ja": "Japanese", "ar": "Arabic"}


def _adapter_preamble(source_lang: str, target_lang: str) -> str:
    src = LANG_NAMES.get(source_lang, source_lang)
    tgt = LANG_NAMES.get(target_lang, target_lang)
    return (f"This rubric was written for Russian→English. You are evaluating a "
            f"{src}→{tgt} translation: read every mention of Russian as the source "
            f"language and English as the target language. Ignore Cyrillic-specific "
            f"transliteration rules when the source is not Russian.\n\n")


def scoring_system_prompt(criterion_id: str, source_lang: str = "ru", target_lang: str = "en") -> str:
    base = _scoring_prompt(criterion_id)
    if (source_lang, target_lang) == ("ru", "en"):
        return base                                # v2-файлы байт-в-байт (решение №4)
    return _adapter_preamble(source_lang, target_lang) + base


def judge_one(client: LLMClient, criterion_id: str, source: str, target: str, *,
              source_lang: str = "ru", target_lang: str = "en") -> dict[str, Any]:
    system = scoring_system_prompt(criterion_id, source_lang, target_lang)
    user = (f"[SOURCE {source_lang.upper()}]\n{source}\n\n"
            f"[TRANSLATION {target_lang.upper()}]\n{target}")
    result = client.complete(system, user)
    ...
```

(тело дальше без изменений; параметры `ru, en` переименованы в `source, target`).

**Шаг 3 — `app.py`:** `_judge_live` получает языки и использует их и для оценки токенов, и для вызова:

```python
async def _judge_live(conn, criterion, source: str, target: str,
                      source_lang: str, target_lang: str):
    ...
    system = scoring_system_prompt(criterion["id"], source_lang, target_lang)
    prompt_tok = (budget.count_tokens(system) + budget.count_tokens(source)
                  + budget.count_tokens(target))
    ...
        res = await asyncio.wait_for(
            asyncio.to_thread(judge_one, client, criterion["id"], source, target,
                              source_lang=source_lang, target_lang=target_lang), EVAL_TIMEOUT)
```

В обработчике `/evaluate` — языки читаются один раз из документа (спека M2):

```python
    doc = conn.execute("SELECT * FROM document WHERE id=?", (doc_id,)).fetchone()
    ...
        results = await asyncio.gather(
            *[_judge_live(conn, c, p["source"], p["target"],
                          doc["source_lang"], doc["target_lang"]) for c in crits],
            return_exceptions=True)
```

Импорт в app.py: `from .judge import judge_one, scoring_system_prompt` (заменяет `_scoring_prompt`).

**Шаг 4:** `uv run pytest tests/test_judge_lang.py tests/test_judge_parse.py -q` → all passed.

**Коммит:** `feat(judge): thread source/target language pair into prompts and labels`

---

## Задача 6: `aggregatePrev` в `/evaluate` и `_cache_response` [S]

**Спека:** §5.1 (хук M1, F4), §5.7 (M8), решение №7.
**Файлы:** Modify `src/palimpsest/webapp/app.py`; Create `tests/test_aggregate_prev.py`.

**Шаг 1 — тест (падает):**

```python
async def _fake_judge(conn, criterion, source, target, source_lang, target_lang):
    return {"value": 8.0, "summary": "ok", "issues": [], "usage": None}


@pytest.fixture()
def scored_client(client, monkeypatch):
    from palimpsest.webapp import app as app_mod
    monkeypatch.setattr(app_mod, "_judge_live", _fake_judge)
    conn = db.connect()
    conn.execute("INSERT INTO criterion(id,name,weight,scale_min,scale_max,enabled) "
                 "VALUES('accuracy','Accuracy',1.0,1,10,1)")
    conn.commit()
    return client


def test_first_evaluate_aggregate_prev_null(scored_client):
    doc = scored_client.post("/api/documents", json=_body()).json()
    pid = doc["paragraphs"][0]["id"]
    ev = scored_client.post(f"/api/paragraphs/{pid}/evaluate").json()
    assert ev["aggregatePrev"] is None            # первая оценка → без дельты (решение №7)


def test_second_evaluate_aggregate_prev_set(scored_client):
    doc = scored_client.post("/api/documents", json=_body()).json()
    pid = doc["paragraphs"][0]["id"]
    first = scored_client.post(f"/api/paragraphs/{pid}/evaluate").json()
    second = scored_client.post(f"/api/paragraphs/{pid}/evaluate").json()
    assert second["aggregatePrev"] == first["aggregate"]


def test_cache_fallback_carries_aggregate_prev(scored_client, monkeypatch):
    from palimpsest.webapp import app as app_mod

    async def boom(*a, **kw):
        raise RuntimeError("no api key")
    monkeypatch.setattr(app_mod, "_judge_live", boom)
    doc = scored_client.post("/api/documents", json=_body()).json()
    pid = doc["paragraphs"][0]["id"]
    conn = db.connect()
    conn.execute("INSERT INTO score(paragraph_id,criterion_id,value,aggregate,kind,created_at) "
                 "VALUES(?,'accuracy',6.0,6.0,'cache','2026-07-02T00:00:00')", (pid,))
    conn.commit()
    ev = scored_client.post(f"/api/paragraphs/{pid}/evaluate").json()
    assert ev["cached"] is True
    assert ev["aggregatePrev"] is None            # seed/live-строк нет → первая оценка (F4+M8)
```

**Шаг 2 — реализация.** В `evaluate()` пре-insert вызов уже существует ([app.py:284](../../../src/palimpsest/webapp/app.py#L284)) — захватить агрегат:

```python
        latest, _, _, agg_prev, _ = _para_score_views(conn, pid)
```

и добавить в возвращаемый dict ответа: `"aggregatePrev": agg_prev,`. В `_cache_response` ([app.py:323](../../../src/palimpsest/webapp/app.py#L323)):

```python
    _, prev, baseline, agg_prev, agg_base = _para_score_views(conn, pid)
```

и в его dict: `"aggregatePrev": agg_prev,` (значение из seed/live-строк, от cache-значений не зависит — спека §5.1). Путь «все судьи упали, кеша нет» проходит через тот же общий блок ответа → `aggregatePrev` попадает и туда (M8) без отдельного кода.

**Шаг 3:** `uv run pytest tests/test_aggregate_prev.py -q` → `3 passed`.

**Коммит:** `feat(webapp): expose aggregatePrev in evaluate and cache-fallback responses`

---

## Задача 7: модуль прогрева `precompute.py` [L] ⚠️ budget-critical

**Спека:** §5.6 целиком, решения №2, №5, №9, №10.
**Файлы:** Create `src/palimpsest/webapp/precompute.py`, `tests/test_precompute.py`; Modify `src/palimpsest/webapp/app.py` (wiring + `endpoint`-параметр `_judge_live` + `precompute` в `_doc_dict`), webapp.md (раздел + строка в таблицу модулей — тот же коммит).

**Шаг 1 — модуль:**

```python
"""Background first-pass scoring for uploaded documents (spec §5.6).

One paid judge pass over the first PRECOMPUTE_PARAS paragraphs. Each paragraph
atomically writes kind='seed' (baseline scores + open issues) and kind='cache'
score copies (same values, no uplift). Budget-critical: every call goes through
budget.reserve()/settle() plus the global precompute sub-cap below.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

from . import budget, db
from .aggregate import compute_aggregate

PRECOMPUTE_PARAS = 12
_CALL_CAP = int(os.environ.get("PALIMPSEST_PRECOMPUTE_CALLS", "80"))

# In-memory status per document; absent after restart (accepted risk, spec §5.6).
_status: dict[int, dict] = {}


def status_for(doc_id: int) -> dict | None:
    return _status.get(doc_id)


def mark_skipped(doc_id: int) -> None:
    _status[doc_id] = {"status": "skipped", "done": 0, "planned": 0}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _take_call_slot() -> bool:
    """Sub-cap check-and-increment BEFORE the call, under budget's own lock
    (решение №10 — no second locking scheme)."""
    async with budget._lock:
        used = budget._STATE.get("precompute_calls", 0)
        if used >= _CALL_CAP:
            return False
        budget._STATE["precompute_calls"] = used + 1
        return True


def _already_scored(conn, pid: int) -> bool:
    return conn.execute("SELECT 1 FROM score WHERE paragraph_id=? LIMIT 1", (pid,)).fetchone() is not None


def _write_paragraph(conn, pid: int, enabled, results: dict) -> bool:
    """Paragraph-atomic write of seed + cache rows. Returns False if a live
    /evaluate slipped in during the LLM calls (TOCTOU re-check, решение №9)."""
    values = {cid: r["value"] for cid, r in results.items()}
    aggregate, criteria_key = compute_aggregate(values, enabled)
    ts = _now()
    with db._lock:
        if _already_scored(conn, pid):
            return False                       # discard judged results, no write
        for cid, res in results.items():
            for kind in ("seed", "cache"):
                conn.execute(
                    "INSERT INTO score(paragraph_id,criterion_id,value,summary,aggregate,"
                    "criteria_key,kind,created_at) VALUES(?,?,?,?,?,?,?,?)",
                    (pid, cid, res["value"], res["summary"], aggregate, criteria_key, kind, ts))
            for it in res["issues"]:
                conn.execute(
                    "INSERT INTO issue(paragraph_id,criterion_id,target_fragment,source_fragment,"
                    "explanation,suggestion,severity,mqm_category,status,kind,created_at) "
                    "VALUES(?,?,?,?,?,?,?,?,'open','seed',?)",
                    (pid, cid, it["targetFragment"], it["sourceFragment"], it["explanation"],
                     it["suggestion"], it["severity"], it["mqmCategory"], ts))
        conn.commit()                          # единственный commit на границе абзаца (M3)
    return True


async def run(doc_id: int, judge_live) -> None:
    """Sequential precompute loop. ``judge_live`` is app._judge_live (passed in
    to avoid a circular import)."""
    conn = db.connect()
    d = conn.execute("SELECT * FROM document WHERE id=?", (doc_id,)).fetchone()
    if d is None:
        return
    paras = conn.execute(
        "SELECT * FROM paragraph WHERE document_id=? ORDER BY idx LIMIT ?",
        (doc_id, PRECOMPUTE_PARAS)).fetchall()
    enabled = conn.execute("SELECT * FROM criterion WHERE enabled=1").fetchall()
    _status[doc_id] = {"status": "running", "done": 0, "planned": len(paras)}
    for p in paras:
        if conn.execute("SELECT 1 FROM document WHERE id=?", (doc_id,)).fetchone() is None:
            _status.pop(doc_id, None)          # документ удалён во время прогрева
            return
        if _already_scored(conn, p["id"]):     # дешёвый пре-чек: не тратить деньги
            _status[doc_id]["done"] += 1
            continue
        results: dict[str, dict] = {}
        failed = False
        for c in enabled:
            if not await _take_call_slot():
                _status[doc_id]["status"] = "stopped"
                return
            try:
                results[c["id"]] = await judge_live(
                    conn, c, p["source"], p["target"],
                    d["source_lang"], d["target_lang"], endpoint="precompute")
            except Exception:
                failed = True                  # BudgetExceeded/сеть → абзац не пишется
                break
        if not failed:
            _write_paragraph(conn, p["id"], enabled, results)
        _status[doc_id]["done"] += 1
    _status[doc_id]["status"] = "done"
```

**Шаг 2 — wiring в `app.py`:**

- `from . import precompute`
- `_judge_live(..., endpoint: str = "evaluate")` — и обе строки `budget.log_call({... "endpoint": endpoint ...})` используют параметр.
- В `create_document` после `return`-блока (до возврата результата):

```python
    if body.precompute:
        asyncio.create_task(precompute.run(doc_id, _judge_live))
    else:
        precompute.mark_skipped(doc_id)
    return result
```

- В `_doc_dict` — статус только для загрузок (спека §5.1):

```python
    out = {**_doc_summary(conn, d), "sourceModel": d["source_model"], "version": d["version"],
           "aggregate": ..., "paragraphs": para_dicts}
    if d["origin"] == "upload":
        out["precompute"] = precompute.status_for(d["id"])
    return out
```

**Шаг 3 — тесты** (`tests/test_precompute.py`, без реального LLM):

```python
import asyncio

import pytest

from palimpsest.webapp import db, precompute


async def _fake_judge(conn, criterion, source, target, source_lang, target_lang, endpoint="evaluate"):
    assert endpoint == "precompute"
    return {"value": 7.0, "summary": "ok",
            "issues": [{"targetFragment": "t", "sourceFragment": "s", "explanation": "e",
                        "suggestion": "sg", "severity": "minor", "mqmCategory": None}],
            "usage": None}


def _mk_doc(client, n=2):
    paras = [{"source": f"s{i}", "target": f"t{i}"} for i in range(n)]
    return client.post("/api/documents", json=_body(paragraphs=paras)).json()


def test_precompute_writes_seed_and_cache(scored_client):
    doc = _mk_doc(scored_client)
    asyncio.run(precompute.run(doc["id"], _fake_judge))
    conn = db.connect()
    seed = conn.execute("SELECT COUNT(*) c FROM score WHERE kind='seed'").fetchone()["c"]
    cache = conn.execute("SELECT COUNT(*) c FROM score WHERE kind='cache'").fetchone()["c"]
    issues = conn.execute("SELECT COUNT(*) c FROM issue WHERE kind='seed' AND status='open'").fetchone()["c"]
    assert seed == 2 and cache == 2 and issues == 2       # 2 абзаца × 1 критерий
    assert precompute.status_for(doc["id"]) == {"status": "done", "done": 2, "planned": 2}


def test_skip_already_scored_paragraph(scored_client):
    doc = _mk_doc(scored_client)
    pid = doc["paragraphs"][0]["id"]
    conn = db.connect()
    conn.execute("INSERT INTO score(paragraph_id,criterion_id,value,kind,created_at) "
                 "VALUES(?,'accuracy',9,'live','now')", (pid,))
    conn.commit()
    asyncio.run(precompute.run(doc["id"], _fake_judge))
    seeds = conn.execute("SELECT COUNT(*) c FROM score WHERE paragraph_id=? AND kind='seed'",
                         (pid,)).fetchone()["c"]
    assert seeds == 0                                     # пропущен, деньги не потрачены


def test_toctou_recheck_discards_results(scored_client):
    doc = _mk_doc(scored_client, n=1)
    pid = doc["paragraphs"][0]["id"]

    async def racing_judge(conn, criterion, source, target, sl, tl, endpoint="evaluate"):
        # имитируем live /evaluate, успевший записаться ВО ВРЕМЯ LLM-вызова
        conn.execute("INSERT INTO score(paragraph_id,criterion_id,value,kind,created_at) "
                     "VALUES(?,'accuracy',9,'live','now')", (pid,))
        conn.commit()
        return await _fake_judge(conn, criterion, source, target, sl, tl, endpoint)

    asyncio.run(precompute.run(doc["id"], racing_judge))
    conn = db.connect()
    kinds = [r["kind"] for r in conn.execute("SELECT kind FROM score WHERE paragraph_id=?", (pid,))]
    assert kinds == ["live"]                              # прогрев ничего не перекрыл (решение №9)


def test_sub_cap_stops_run(scored_client, monkeypatch):
    monkeypatch.setattr(precompute, "_CALL_CAP", 1)
    from palimpsest.webapp import budget
    budget._STATE.pop("precompute_calls", None)
    doc = _mk_doc(scored_client, n=3)
    asyncio.run(precompute.run(doc["id"], _fake_judge))
    assert precompute.status_for(doc["id"])["status"] == "stopped"


def test_precompute_false_status_skipped(scored_client):
    doc = scored_client.post("/api/documents", json=_body()).json()  # precompute=False в _body
    got = scored_client.get(f"/api/documents/{doc['id']}").json()
    assert got["precompute"] == {"status": "skipped", "done": 0, "planned": 0}
```

**Шаг 4:** `uv run pytest tests/test_precompute.py -q` → `5 passed`; полный прогон `uv run pytest -q` → all passed. Раздел «Precompute» в webapp.md (5–7 строк, ссылка на спеку §5.6) в этом же коммите.

**Коммит:** `feat(webapp): background precompute pass for uploaded documents`

---

## Задача 8: api-client + store — мульти-документность [M]

**Спека:** §5.1 (DTO), §5.5 (store-действия), F5(а).
**Файлы:** Modify `frontend/src/demo/api-client.ts`, `frontend/src/demo/store.ts`.

**api-client.ts** (типы + функции; хелперы `get/post/del` уже существуют):

```ts
export interface ParagraphPair { source: string; target: string }

export interface CreateDocumentBody {
  title: string;
  sourceLang: string;
  targetLang: string;
  precompute: boolean;
  paragraphs: ParagraphPair[];
}

export interface PrecomputeStatus {
  status: 'running' | 'done' | 'stopped' | 'skipped';
  done: number;
  planned: number;
}

// DocumentSummary: добавить поле
//   origin: 'seed' | 'upload';
// Document: добавить поле
//   precompute?: PrecomputeStatus | null;
// EvaluateResponse: добавить поле
//   aggregatePrev: number | null;
// Paragraph: добавить client-side поле (заполняется applyEvalToParag, с бекенда не приходит)
//   aggregatePrev?: number | null;

export function createDocument(body: CreateDocumentBody): Promise<Document> {
  return post('/documents', body);
}

export function deleteDocument(id: number): Promise<void> {
  return del(`/documents/${id}`);
}

export async function extractText(file: File): Promise<{ text: string; nParagraphs: number }> {
  const form = new FormData();
  form.append('file', file);
  const res = await fetch('/api/documents/extract-text', { method: 'POST', body: form });
  if (!res.ok) throw new Error(`extract-text → ${res.status}: ${await res.text()}`);
  return res.json();
}
```

**store.ts** — состояние и действия:

```ts
// state:
documents: DocumentSummary[];            // = [] изначально
uploadModalOpen: boolean;                // = false

// actions (добавить в DemoStore и реализовать):
openUploadModal: () => void;             // set({ uploadModalOpen: true })
closeUploadModal: () => void;
refreshDocuments: () => Promise<void>;   // documents ← getDocuments()

switchDocument: async (id: number) => {
  set({ documentLoading: true, documentError: null });
  try {
    const doc = await getDocument(id);
    set({
      document: doc,
      selectedParaIdx: 0,
      documentLoading: false,
      paraEvalState: Object.fromEntries(doc.paragraphs.map((_, i) => [i, defaultParaEval()])),
    });
  } catch (e) {
    set({ documentLoading: false, documentError: String(e) });
  }
},

createDoc: async (body: CreateDocumentBody) => {
  const doc = await apiCreateDocument(body);        // ошибки пробрасываются в модалку
  await get().refreshDocuments();
  set({ uploadModalOpen: false });
  await get().switchDocument(doc.id);
},

deleteDoc: async (id: number) => {
  await apiDeleteDocument(id);
  await get().refreshDocuments();
  const first = get().documents[0];
  if (first) await get().switchDocument(first.id);
},

refreshDocument: async () => {                       // для поллинга прогрева (задача 12)
  const cur = get().document;
  if (!cur) return;
  const doc = await getDocument(cur.id);
  set({ document: doc });                            // paraEvalState сохраняем
},
```

`init()` дополняется: `set({ documents: summaries, ... })`. В `applyEvalToParag` — одна строка (F5-а):

```ts
    aggregate: ev.aggregate,
    aggregatePrev: ev.aggregatePrev,
    aggregateBaseline: ev.aggregateBaseline,
```

**Тест:** `cd frontend && npm run build` → `tsc -b` без ошибок (типовая проверка контрактов). Логика store покрывается e2e (задача 15) и vitest-тестами задачи 13.

**Коммит:** `feat(demo): multi-document api client and store actions`

---

## Задача 9: топ-бар — переключатель, удаление, динамические заголовки, empty-state [M]

**Спека:** §5.5 (топ-бар, F6-а), решение №3.
**testid:** `doc-dropdown`, `upload-open`.
**Файлы:** Modify `frontend/src/demo/variant-a/VariantA.tsx`, `frontend/src/demo/variant-a/GlossaryTab.tsx`, `frontend/src/demo/variant-a/variant-a.css`.

**VariantA.tsx** — в тулбар (рядом с вкладками):

```tsx
const anyEvaluating = Object.values(paraEvalState).some((s) => s.loading);

<div className="va-doc-switcher">
  <select
    data-testid="doc-dropdown"
    value={document?.id ?? ''}
    disabled={anyEvaluating}                     /* F6-а: не переключать посреди оценки */
    onChange={(e) => switchDocument(Number(e.target.value))}
  >
    {documents.map((d) => (
      <option key={d.id} value={d.id}>
        {d.title} · {d.sourceLang.toUpperCase()}→{d.targetLang.toUpperCase()} · {d.nParagraphs}§
      </option>
    ))}
  </select>
  {document?.origin === 'upload' && (
    <button
      className="va-icon-btn"
      title="Удалить документ"
      onClick={() => {
        if (window.confirm(`Удалить «${document.title}»?`)) deleteDoc(document.id);
      }}
    >
      🗑
    </button>
  )}
  <button className="va-chip" data-testid="upload-open" onClick={openUploadModal}>
    + Загрузить пару
  </button>
</div>
```

Заголовки колонок ([VariantA.tsx:337–338](../../../frontend/src/demo/variant-a/VariantA.tsx#L337)):

```tsx
<div className="va-col-header">Original ({document.sourceLang.toUpperCase()})</div>
<div className="va-col-header">Translation ({document.targetLang.toUpperCase()})</div>
```

Чип Terms ([VariantA.tsx:321–324](../../../frontend/src/demo/variant-a/VariantA.tsx#L321)):

```tsx
<button
  className={`va-chip terms-chip${showTerms ? ' on' : ''}`}
  disabled={allTerms.length === 0}
  title={allTerms.length === 0
    ? 'Terminology signals are precomputed offline and available for the seeded RU→EN document'
    : undefined}
  onClick={() => setShowTerms(!showTerms)}
>
  Terms
</button>
```

**GlossaryTab.tsx** — empty-state перед таблицей:

```tsx
if (terms.length === 0) {
  return (
    <div className="va-tab-content">
      <div className="va-section-title">Terminology Glossary</div>
      <p className="va-empty-note">
        Terminology signals are precomputed offline and available for the seeded RU→EN document.
      </p>
    </div>
  );
}
```

Заголовки таблицы Glossary — из документа: `Source ({sourceLang.toUpperCase()})` / `Target ({targetLang.toUpperCase()})` (пропс `document` или пара строк-пропсов). CSS: `.va-doc-switcher` (flex, gap 8px), `.va-icon-btn`, `.va-empty-note` — только из токенов `--va-*`.

**Тест:** `npm run build` без ошибок; визуально — задача 15 (скриншоты §5.8 п.1, 9, 13).

**Коммит:** `feat(demo): document switcher, dynamic language headers, terms empty states`

---

## Задача 10: модалка, шаг 1 — панели, файлы, счётчики [L]

**Спека:** §5.4 (ingestion), §5.5 (макет шага 1, строки ошибок M5, счётчики M6, `va-modal-wide` M9, L3).
**testid:** `panel-source`, `panel-target`, `panel-source-textarea`, `panel-target-textarea`, `panel-source-file-btn`, `panel-target-file-btn`, `panel-source-error`, `panel-target-error`.
**Файлы:** Create `frontend/src/demo/variant-a/upload/md-strip.ts`, `frontend/src/demo/variant-a/upload/file-ingest.ts`, `frontend/src/demo/variant-a/upload/UploadModal.tsx`; Modify `variant-a.css`, `VariantA.tsx` (рендер `{uploadModalOpen && <UploadModal />}`).

**md-strip.ts** (полностью):

```ts
/** Markdown → чистый текст (спека §5.4): владелец просил "чистый текст". */
export function stripMarkdown(md: string): string {
  let t = md.replace(/\r\n/g, '\n');
  t = t.replace(/^```[^\n]*$/gm, '');                        // маркеры код-фенсов (содержимое остаётся)
  t = t.replace(/!\[[^\]]*\]\([^)]*\)/g, '');                // картинки — выбрасываем
  t = t.replace(/\[([^\]]*)\]\(([^)]*)\)/g, '$1');           // ссылки → текст
  t = t.replace(/<[^>\n]+>/g, '');                           // HTML-теги
  t = t.replace(/^#{1,6}\s+/gm, '');                         // заголовки
  t = t.replace(/^>\s?/gm, '');                              // цитаты
  t = t.replace(/^([-*_]){3,}\s*$/gm, '');                   // горизонтальные линии
  t = t.replace(/^\|(.+)\|\s*$/gm, (_, row: string) =>       // строки таблиц → « — »
    row.split('|').map((c) => c.trim()).filter(Boolean).join(' — '));
  t = t.replace(/^\|?[\s:|-]+\|[\s:|-]*$/gm, '');            // разделители таблиц
  t = t.replace(/(\*\*|__)(.*?)\1/g, '$2');                  // жирный
  t = t.replace(/(\*|_)(?=\S)(.*?)(?<=\S)\1/g, '$2');        // курсив
  t = t.replace(/`([^`]*)`/g, '$1');                         // инлайн-код
  t = t.replace(/\n{3,}/g, '\n\n');
  return t.trim();
}
```

**file-ingest.ts** (полностью):

```ts
import { extractText } from '../../api-client';
import { stripMarkdown } from './md-strip';

export const ACCEPT = '.docx,.md,.txt';

const ERRORS: Record<number, string> = {
  415: 'Формат не поддерживается. Сохраните документ как .docx и загрузите снова',
  422: 'Файл повреждён или не является документом Word (.docx)',
  413: 'Файл больше 5 МБ — разбейте документ или вставьте текст частями',
};

export function errorMessage(status: number): string {
  return ERRORS[status] ?? `Не удалось обработать файл (HTTP ${status})`;
}

/** UTF-8 → retry windows-1251 при U+FFFD (спека §5.4, старые RU-тексты). */
export function decodeText(buf: ArrayBuffer): string {
  const utf8 = new TextDecoder('utf-8').decode(buf);
  if (!utf8.includes('�')) return utf8;
  try {
    return new TextDecoder('windows-1251').decode(buf);
  } catch {
    return utf8; // вставляем как есть + warning в UI
  }
}

/** Файл любого поддерживаемого типа → чистый текст для textarea (SSOT). */
export async function ingestFile(file: File): Promise<string> {
  const name = file.name.toLowerCase();
  if (name.endsWith('.docx')) {
    const { text } = await extractText(file);              // сервер, python-docx
    return text;
  }
  if (name.endsWith('.doc')) {
    throw Object.assign(new Error(errorMessage(415)), { status: 415 });
  }
  const raw = decodeText(await file.arrayBuffer());
  return name.endsWith('.md') ? stripMarkdown(raw) : raw;
}

export function splitParagraphs(text: string): string[] {
  return text.split(/\n\s*\n/).map((p) => p.trim()).filter(Boolean);
}
```

**UploadModal.tsx** — шаг 1 (панель как подкомпонент; шаг 2 — задача 11):

```tsx
import { useRef, useState } from 'react';
import { useDemoStore } from '../../store';
import { ACCEPT, errorMessage, ingestFile, splitParagraphs } from './file-ingest';

const LANGS = ['ru', 'en', 'de', 'fr', 'es', 'it', 'pt', 'pl', 'uk', 'zh', 'ja', 'ar'];
const MAX_PARAS = 40;
const MAX_PARA_CHARS = 4000;

interface SideState { text: string; lang: string; busy: boolean; error: string | null }

function SidePanel(props: {
  id: 'source' | 'target';
  label: string;
  state: SideState;
  onChange: (patch: Partial<SideState>) => void;
}) {
  const { id, label, state, onChange } = props;
  const fileRef = useRef<HTMLInputElement>(null);
  const paras = splitParagraphs(state.text);

  const loadFile = async (file: File | undefined) => {
    if (!file) return;
    if (state.text.trim() && !window.confirm('Заменить вставленный текст содержимым файла?')) return;
    onChange({ busy: true, error: null });
    try {
      onChange({ text: await ingestFile(file), busy: false });
    } catch (e: unknown) {
      const status = (e as { status?: number }).status;
      onChange({ busy: false, error: status ? errorMessage(status) : String(e) });
    }
  };

  return (
    <div className="va-upload-panel" data-testid={`panel-${id}`}>
      <div className="va-upload-panel-head">
        <span>{label}</span>
        <select value={state.lang} onChange={(e) => onChange({ lang: e.target.value })}>
          {LANGS.map((l) => <option key={l} value={l}>{l.toUpperCase()}</option>)}
        </select>
      </div>
      <textarea
        data-testid={`panel-${id}-textarea`}
        dir="auto"
        disabled={state.busy}
        placeholder={'Вставьте текст\nили перетащите файл сюда (.docx, .md, .txt)'}
        value={state.text}
        onChange={(e) => onChange({ text: e.target.value })}
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => {
          e.preventDefault();
          if (e.dataTransfer.files.length > 1) onChange({ error: 'Загружен только первый файл' });
          void loadFile(e.dataTransfer.files[0]);
        }}
      />
      {state.busy && <div className="va-upload-busy">Извлекаем текст…</div>}
      <div className="va-upload-panel-foot">
        <button data-testid={`panel-${id}-file-btn`} onClick={() => fileRef.current?.click()}>
          📄 Загрузить файл
        </button>
        <input ref={fileRef} type="file" accept={ACCEPT} hidden
               onChange={(e) => void loadFile(e.target.files?.[0])} />
        <span className="va-upload-counter">{paras.length} § · {state.text.length} симв.</span>
      </div>
      {state.error && <div className="va-upload-error" data-testid={`panel-${id}-error`}>{state.error}</div>}
    </div>
  );
}

export default function UploadModal() {
  const closeUploadModal = useDemoStore((s) => s.closeUploadModal);
  const [title, setTitle] = useState('');
  const [src, setSrc] = useState<SideState>({ text: '', lang: 'ru', busy: false, error: null });
  const [tgt, setTgt] = useState<SideState>({ text: '', lang: 'en', busy: false, error: null });
  const [step, setStep] = useState<1 | 2>(1);

  const srcParas = splitParagraphs(src.text);
  const tgtParas = splitParagraphs(tgt.text);
  const tooLong = [...srcParas, ...tgtParas].some((p) => p.length > MAX_PARA_CHARS);
  const tooMany = srcParas.length > MAX_PARAS || tgtParas.length > MAX_PARAS;
  const sameLang = src.lang === tgt.lang;
  const canNext = !!title.trim() && !!src.text.trim() && !!tgt.text.trim()
    && !sameLang && !tooLong && !tooMany && !src.busy && !tgt.busy;

  const problems = [
    sameLang && 'Языки оригинала и перевода должны различаться',
    tooMany && `Не больше ${MAX_PARAS} абзацев с каждой стороны`,
    tooLong && `Абзац длиннее ${MAX_PARA_CHARS} символов — разбейте его`,
  ].filter(Boolean) as string[];

  return (
    <div className="va-popover-backdrop" onClick={closeUploadModal}>
      <div className="va-modal-wide" onClick={(e) => e.stopPropagation()}>
        {step === 1 ? (
          <>
            <div className="va-modal-title">Новая пара «оригинал — перевод»</div>
            <input className="va-modal-title-input" placeholder="Название"
                   value={title} onChange={(e) => setTitle(e.target.value)} />
            <div className="va-upload-panels">
              <SidePanel id="source" label="Оригинал" state={src}
                         onChange={(p) => setSrc((s) => ({ ...s, ...p }))} />
              <SidePanel id="target" label="Перевод" state={tgt}
                         onChange={(p) => setTgt((s) => ({ ...s, ...p }))} />
            </div>
            {problems.map((p) => <div key={p} className="va-upload-error">⚠ {p}</div>)}
            <div className="va-modal-actions">
              <button onClick={closeUploadModal}>Отмена</button>
              <button className="va-primary" disabled={!canNext} onClick={() => setStep(2)}>
                Далее →
              </button>
            </div>
          </>
        ) : (
          <Step2 title={title} srcLang={src.lang} tgtLang={tgt.lang}
                 srcParas={srcParas} tgtParas={tgtParas} onBack={() => setStep(1)} />
        )}
      </div>
    </div>
  );
}
```

(`Step2` — задача 11; на время задачи 10 — заглушка `() => null` в том же файле, удаляется в задаче 11.)

**variant-a.css** — только токены `--va-*` (M9):

```css
.va-modal-wide {
  width: min(920px, 90vw);
  max-height: 88vh;
  overflow-y: auto;
  background: var(--va-surface2);
  border: 1px solid var(--va-border);
  border-radius: var(--va-radius, 10px);
  box-shadow: var(--va-shadow, 0 12px 40px rgba(0, 0, 0, 0.5));
  padding: 20px;
}
.va-upload-panels { display: flex; gap: 16px; }
.va-upload-panel { flex: 1; display: flex; flex-direction: column; border: 1px solid var(--va-border); border-radius: 8px; }
.va-upload-panel textarea { min-height: 220px; resize: vertical; }
.va-upload-error { color: var(--va-red, #f7768e); font-size: 12px; }
.va-upload-counter { margin-left: auto; opacity: 0.7; font-size: 12px; }
```

**Тест:** `npm run build` без ошибок; юнит-тесты md-strip/decode — задача 13; скриншоты §5.8 п.2–6 — задача 15.

**Коммит:** `feat(demo): upload modal step 1 — paste/file panels with extraction`

---

## Задача 11: модалка, шаг 2 — превью выравнивания + сабмит [M]

**Спека:** §5.5 (макет шага 2), §5.7 (сироты, пустые ячейки).
**testid:** `step2-merge-src-<i>`, `step2-merge-tgt-<i>`, `precompute-checkbox`, `upload-submit`.
**Файлы:** Modify `frontend/src/demo/variant-a/upload/UploadModal.tsx`, `variant-a.css`.

**Step2 (полностью, заменяет заглушку):**

```tsx
export function mergeUp(list: string[], i: number): string[] {
  if (i === 0) return list;
  const next = [...list];
  next[i - 1] = `${next[i - 1]}\n${next[i]}`;
  next.splice(i, 1);
  return next;
}

function Step2(props: {
  title: string; srcLang: string; tgtLang: string;
  srcParas: string[]; tgtParas: string[]; onBack: () => void;
}) {
  const createDoc = useDemoStore((s) => s.createDoc);
  const [src, setSrc] = useState(props.srcParas);
  const [tgt, setTgt] = useState(props.tgtParas);
  const [precompute, setPrecompute] = useState(true);        // default ON (решение №5)
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const n = Math.max(src.length, tgt.length);
  const aligned = src.length === tgt.length && src.length > 0;

  const submit = async () => {
    setSubmitting(true);
    setSubmitError(null);
    try {
      await createDoc({
        title: props.title, sourceLang: props.srcLang, targetLang: props.tgtLang,
        precompute, paragraphs: src.map((s, i) => ({ source: s, target: tgt[i] })),
      });
    } catch (e) {
      setSubmitError(String(e));
      setSubmitting(false);
    }
  };

  return (
    <>
      <div className="va-modal-title">Выравнивание абзацев</div>
      <div className="va-step2-counts">
        Оригинал: {src.length} § · Перевод: {tgt.length} §
        {!aligned && <span className="va-upload-error"> ⚠ количество не совпадает</span>}
      </div>
      <table className="va-step2-table">
        <tbody>
          {Array.from({ length: n }, (_, i) => (
            <tr key={i} className={src[i] === undefined || tgt[i] === undefined ? 'orphan' : ''}>
              <td>{i + 1}</td>
              <td dir="auto">
                {src[i] ?? '— (нет пары)'}
                {i > 0 && src[i] !== undefined && (
                  <button data-testid={`step2-merge-src-${i}`} onClick={() => setSrc(mergeUp(src, i))}>
                    ⇧ склеить с пред.
                  </button>
                )}
              </td>
              <td dir="auto">
                {tgt[i] ?? '— (нет пары)'}
                {i > 0 && tgt[i] !== undefined && (
                  <button data-testid={`step2-merge-tgt-${i}`} onClick={() => setTgt(mergeUp(tgt, i))}>
                    ⇧ склеить с пред.
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <label className="va-step2-precompute">
        <input type="checkbox" data-testid="precompute-checkbox"
               checked={precompute} onChange={(e) => setPrecompute(e.target.checked)} />
        Оценить документ и прогреть кеш-фолбэк после создания (первые 12 §, ~$0.2, идёт в фоне)
      </label>
      {submitError && <div className="va-upload-error">{submitError}</div>}
      <div className="va-modal-actions">
        <button onClick={props.onBack}>← Назад</button>
        <button className="va-primary" data-testid="upload-submit"
                disabled={!aligned || submitting} onClick={() => void submit()}>
          Создать документ
        </button>
      </div>
    </>
  );
}
```

«Назад» не переписывает textarea — шаг 2 пересобирается из текста заново (спека §5.5). CSS: `.va-step2-table` (ширина 100%, `td` с рамкой `--va-border`), `tr.orphan td { background: color-mix(in srgb, var(--va-red, #f7768e) 12%, transparent); }`.

**Тест:** `npm run build`; юнит `mergeUp` — задача 13; скриншоты §5.8 п.7–8 — задача 15.

**Коммит:** `feat(demo): upload modal step 2 — alignment preview, merge, submit`

---

## Задача 12: правило дельты + поллинг прогрева [M]

**Спека:** §5.5 (правило дельты, F5 б–г, F6-б), §5.6 (бейдж).
**Файлы:** Modify `frontend/src/demo/variant-a/VariantA.tsx`, `frontend/src/demo/variant-a/InspectorPanel.tsx`.

**chipDelta** ([VariantA.tsx:352–355](../../../frontend/src/demo/variant-a/VariantA.tsx#L352)) — предпочитает `aggregatePrev`, ноль/`null` не рендерится:

```tsx
const agg = para.aggregate;
const prev = para.aggregatePrev !== undefined ? para.aggregatePrev : para.aggregateBaseline;
const chipDelta =
  agg !== null && prev !== null && prev !== undefined && agg !== prev
    ? Math.round((agg - prev) * 10) / 10
    : null;
```

**InspectorPanel** ([InspectorPanel.tsx:306–308](../../../frontend/src/demo/variant-a/InspectorPanel.tsx#L306)):

```tsx
{selectedPara?.aggregatePrev != null ? (
  <span className="va-insp-agg-baseline" title="Previous score">
    {' '}(prev {selectedPara.aggregatePrev.toFixed(1)})
  </span>
) : (
  aggregateBaseline !== null && (
    <span className="va-insp-agg-baseline" title="Baseline">
      {' '}(base {aggregateBaseline.toFixed(1)})
    </span>
  )
)}
```

Пер-критерийная логика ([InspectorPanel.tsx:252–272](../../../frontend/src/demo/variant-a/InspectorPanel.tsx#L252)) уже null-safe — **не трогать** (F5-г).

**Поллинг прогрева (F6-б)** — в VariantA рядом с топ-баром; принадлежит топ-бару, живёт при переключении вкладок, сворачивается при смене документа (deps по `id`), останавливается на `done`/`stopped`:

```tsx
useEffect(() => {
  if (!document || document.origin !== 'upload') return;
  if (document.precompute?.status !== 'running') return;
  const t = setInterval(() => void refreshDocument(), 3000);
  return () => clearInterval(t);
}, [document?.id, document?.precompute?.status]);
```

Бейдж рядом с селектором:

```tsx
{document?.precompute?.status === 'running' && (
  <span className="va-precompute-badge">
    прогрев {document.precompute.done}/{document.precompute.planned} §…
  </span>
)}
```

Toast деградации (спека §5.5): в месте, где `evaluateParagraph` завершился с `failedCriterionIds.length === criteria.length && !cached` — показать «Live-оценка не удалась; для этого абзаца нет прогретого кеша. Повторите» (использовать существующий механизм уведомлений VariantA; если его нет — строка в InspectorPanel над списком).

**Тест:** `npm run build`; поведенчески — §5.8 п.10–12 в задаче 15.

**Коммит:** `feat(demo): old-to-new delta rule and precompute badge polling`

---

## Задача 13: vitest — юнит-тесты фронтовой логики + `dir="auto"` в документе [S]

**Спека:** §5.4 (md-стриппер, декодирование), §5.5 (mergeUp), §5.7 (RTL).
**Файлы:** Modify `frontend/package.json`, `frontend/src/demo/variant-a/EditorParagraph.tsx` (`dir="auto"` на контейнерах текста абзаца); Create `frontend/src/demo/variant-a/upload/__tests__/md-strip.test.ts`, `.../file-ingest.test.ts`, `.../merge-up.test.ts`.

**Vitest:** параллельная ветка audit-fixes (её план, Task 11) вводит vitest. Если к моменту мержа `npm run test` уже есть — ничего не добавлять. Если нет — добавить идентичную минимальную конфигурацию (те же версии devDeps, что в плане audit-fixes Task 11, чтобы не ловить конфликт мержа):

```json
"scripts": { "test": "vitest run" },
"devDependencies": { "vitest": "^3.2.4" }
```

**md-strip.test.ts:**

```ts
import { describe, expect, it } from 'vitest';
import { stripMarkdown } from '../md-strip';

describe('stripMarkdown', () => {
  it('strips headings, emphasis, links; drops images', () => {
    expect(stripMarkdown('# Заголовок\n\n**жирный** и [ссылка](http://x) и ![img](y.png)'))
      .toBe('Заголовок\n\nжирный и ссылка и');
  });
  it('keeps code fence content, drops markers', () => {
    expect(stripMarkdown('```py\nprint(1)\n```')).toBe('print(1)');
  });
  it('joins table cells with em-dash', () => {
    expect(stripMarkdown('| a | b |\n|---|---|\n| c | d |')).toBe('a — b\nc — d');
  });
});
```

**file-ingest.test.ts:**

```ts
import { describe, expect, it } from 'vitest';
import { decodeText, splitParagraphs } from '../file-ingest';

describe('decodeText', () => {
  it('falls back to windows-1251 on U+FFFD', () => {
    const cp1251 = new Uint8Array([0xcf, 0xf0, 0xe8, 0xe2, 0xe5, 0xf2]); // «Привет»
    expect(decodeText(cp1251.buffer)).toBe('Привет');
  });
  it('keeps valid utf-8', () => {
    expect(decodeText(new TextEncoder().encode('Привет').buffer)).toBe('Привет');
  });
});

describe('splitParagraphs', () => {
  it('splits on blank lines, trims, drops empties', () => {
    expect(splitParagraphs('a\n\n  \n\nb\nc\n\n')).toEqual(['a', 'b\nc']);
  });
});
```

**merge-up.test.ts:**

```ts
import { describe, expect, it } from 'vitest';
import { mergeUp } from '../UploadModal';

describe('mergeUp', () => {
  it('merges into previous, keeps rest', () => {
    expect(mergeUp(['a', 'b', 'c'], 1)).toEqual(['a\nb', 'c']);
  });
  it('no-op at index 0', () => {
    expect(mergeUp(['a', 'b'], 0)).toEqual(['a', 'b']);
  });
});
```

**Тест:** `cd frontend && npm run test` → ожидаем `Test Files 3 passed`, все зелёные; `npm run build`.

**Коммит:** `test(demo): unit-test md stripper, decoding, paragraph merge; add dir=auto`

---

## Задача 14: документация — финальная сверка [S]

**Спека:** вся; правило sync (CLAUDE.md).
**Файлы:** Modify [docs/subsystems/webapp.md](../../subsystems/webapp.md) (свести: 3 новых эндпоинта в таблице API — добавлены задачами 2–4; строка `precompute.py` в таблице модулей + короткий раздел «Precompute» — задача 7; DDL-примечание про `origin`/CASCADE), [docs/testing/e2e-data.md](../../testing/e2e-data.md) (новый journey «Загрузка своей пары» = 15 состояний из [спеки §5.8](../specs/2026-07-02-custom-pair-upload-design.md)), [docs/known_issues.md](../../known_issues.md) (две записи: «загрузки не переживают пересид», «суб-кап прогрева обнуляется при рестарте — принятый риск»).

Проверка: каждая строка webapp.md соответствует коду; ссылки из README/CLAUDE.md не дублируют, а ссылаются (single source of truth).

**Коммит:** `docs(webapp): document pair-upload endpoints, precompute and e2e journeys`

---

## Задача 15: финальный сквозной прогон [M]

**Спека:** §5.8 (чек-лист скриншотов).

1. Бекенд: `uv run python -m palimpsest.webapp.seed && uv run uvicorn palimpsest.webapp.app:app --port 8000 --workers 1`
2. Фронтенд: `cd frontend && npm run dev` (проксирует `/api` → :8000).
3. Полные тесты: `uv run pytest -q` → all passed, 0 failures; `cd frontend && npm run test && npm run build` → зелёные.
4. Браузерный проход `playwright-cli` (сессия `-s=pair-upload`): все 15 состояний из спеки §5.8, скриншот на каждое, сверка testid'ов из задач 9–11. Живые пункты (10–12: прогрев, дельты) — с реальным `OPENROUTER_API_KEY` и малым документом (2 абзаца), расход ≤ $0.05.
5. Особая проверка budget-critical (задачи 2, 7): `budget_calls.jsonl` содержит записи `"endpoint": "precompute"`; суммарный расход прогона в пределах ожидания; повторная загрузка после исчерпания `PALIMPSEST_PRECOMPUTE_CALLS=3` (env для теста) даёт `status: "stopped"` без падения.

Коммит не нужен (верификация); дефекты → `superpowers:systematic-debugging` → фикс-коммиты `fix(...)`.

---

## Сводная таблица

| № | Что | Спека | Оценка | Файлы |
|---|---|---|---|---|
| 1 | DDL: `origin`, `ON DELETE CASCADE`, сериализаторы | §5.2, №8 | S | db.py, seed.py, app.py, test_db.py |
| 2 | `POST /api/documents` | §5.1 | M | app.py, webapp.md, test_documents_create.py |
| 3 | `DELETE /api/documents/{id}` | §5.1, L1 | S | app.py, webapp.md, test_documents_delete.py |
| 4 | `extract-text` + python-docx/multipart | §5.1, §5.4 | M | pyproject.toml, app.py, webapp.md, test_extract_text.py |
| 5 | Языковая пара в судье | §5.3 | M | judge.py, app.py, test_judge_lang.py |
| 6 | `aggregatePrev` (evaluate + cache) | §5.1, №7 | S | app.py, test_aggregate_prev.py |
| 7 | ⚠️ Прогрев `precompute.py` + суб-кап + TOCTOU | §5.6, №9–10 | L | precompute.py, app.py, webapp.md, test_precompute.py |
| 8 | api-client + store: мульти-док | §5.1, §5.5 | M | api-client.ts, store.ts |
| 9 | Топ-бар: селектор, удаление, заголовки, empty-state | §5.5, №3 | M | VariantA.tsx, GlossaryTab.tsx, variant-a.css |
| 10 | Модалка шаг 1: панели + файлы | §5.4–5.5, M5–M6, M9 | L | upload/*, variant-a.css, VariantA.tsx |
| 11 | Модалка шаг 2: превью + merge + сабмит | §5.5 | M | UploadModal.tsx, variant-a.css |
| 12 | Дельты (F5) + поллинг прогрева (F6) | §5.5–5.6, №7 | M | VariantA.tsx, InspectorPanel.tsx |
| 13 | vitest-юниты + dir=auto | §5.4, §5.7 | S | package.json, upload/__tests__/*, EditorParagraph.tsx |
| 14 | Документация: финальная сверка | все | S | webapp.md, e2e-data.md, known_issues.md |
| 15 | Финальный сквозной прогон (§5.8) | §5.8 | M | — |

Итого: ~3–4 дня одним исполнителем; двумя параллельными (бекенд 1–7, фронтенд 8–13 по контрактам спеки) — ~2 дня + день на 14–15 и verify.
