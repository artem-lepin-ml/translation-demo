# План: Полировка загрузки пар (upload-polish)

> **Для агента-исполнителя без контекста:** ветка `feat/upload-polish` от `dev-demo`, worktree `/Users/a1111/Projects/Work/worktrees/upload-polish`. Все пути ниже — относительно корня repo. Дизайн-спека фичи: [docs/superpowers/specs/2026-07-02-custom-pair-upload-design.md](../specs/2026-07-02-custom-pair-upload-design.md). Тесты: фронт `cd frontend && npm test` (vitest run), бэк `uv run pytest -q`. Не трогать `data/raw/`, `factowl/`, запущенные серверы на 5173/8000.

## Цель

Четыре правки по фидбэку владельца к фиче загрузки пар «оригинал — перевод»:

1. **Инвариант: продуктовый UI — только английский.** В демо ушли русские строки (модалка загрузки, кнопки, баннеры). Все user-facing строки → английский.
2. **Свободный ввод языков** вместо дропдауна из 12 кодов; введённые названия текстом доходят до промптов судьи, каждый scoring-промпт явно называет пару языков.
3. **Визуальные фиксы:** кнопка «Загрузить файл» выбивается из системы кнопок; поле «Название» вылезает за контейнер; новые текстовые поля языков — в стиле поля Название.
4. **Упрощение кода** фичи по конвенциям repo (idiomatic-first, без спекулятивных абстракций).

## Root cause русского UI (для отчёта)

Подтверждено: спека [2026-07-02-custom-pair-upload-design.md](../specs/2026-07-02-custom-pair-upload-design.md) написана по-русски (по языковой политике CLAUDE.md — owner-facing доки на русском) и **цитирует UI-копирайт дословно по-русски**: список data-testid фиксирует «`upload-open` («+ Загрузить пару»)», «`upload-submit` («Создать документ»)»; §5.5 задаёт подсказку «Сохраните как .docx и загрузите снова»; чек-лист граничных случаев — «Шаг 1: „Далее" неактивна…». Исполнитель перенёс копирайт из спеки в код буквально. Языковая политика различает owner-facing доки (русский) и продуктовый UI (английский), но спека этого разграничения для UI-строк не проговорила. Вывод в отчёт: русскоязычные спеки должны помечать UI-копирайт как «copy: EN» с английским текстом в кавычках.

## Находка: как языки доходят до судьи сегодня

Цепочка (проверена по коду):

- `UploadModal.tsx:46-48` — `<select>` из `LANGS` (12 ISO-кодов, `UploadModal.tsx:5`) → `createDoc({sourceLang, targetLang, …})` ([store.ts:278](../../../frontend/src/demo/store.ts#L278)) → `POST /api/documents`.
- `app.py:237` — валидация `body.sourceLang not in LANG_CODES` (жёсткий сет из 12 кодов, `app.py:42`) → 422 `bad_lang_code`; затем INSERT в `document(source_lang, target_lang)`.
- `/evaluate` (`app.py:393+`) и `precompute._run` (`precompute.py:142`) читают `doc["source_lang"]/["target_lang"]` и передают в `_judge_live` → `scoring_system_prompt()` + `judge_one()`.
- `judge.py:61-65`: для пары `(ru, en)` системный промпт = файл `prompts/scoring/<id>.md` **байт-в-байт** (без упоминания пары языков — рубрики сами захардкожены на Russian→English прозой); для любой другой пары добавляется префикс-адаптер `_adapter_preamble` (judge.py:52-58), который через `LANG_NAMES` (12 кодов → полные названия) пишет «You are evaluating a {src}→{tgt} translation…».
- User-сообщение: `[SOURCE {source_lang.upper()}]` / `[TRANSLATION {target_lang.upper()}]` — сырой код капсом (judge.py:76-77).

То есть интерполяция уже есть, но (а) вход ограничен 12 кодами в трёх продублированных списках, (б) для ru→en промпт вообще не называет языки, (в) `LANG_NAMES.get(x, x)` уже пропускает неизвестное значение как есть — свободный текст ляжет в эту схему без миграций (колонки `source_lang/target_lang` — TEXT).

**Wikidata/терминология:** grounding живёт только в `seed.py` (сид-документ: синтетические QID + 3 записи глоссария с wikidata.org URL). При загрузке term-строки не создаются, precompute пишет только scores/issues, терминологический стейдж для загрузок не запускается. Языкового параметра в grounding-путях webapp нет → для загрузок **N/A, изменений не требуется**. Единственный языко-зависимый терминологический промпт — `TEST_EXTRACT_PROMPT` (`app.py:~709`, «From the Russian paragraph…») в пробе моделей на Settings; он по дизайну гоняется на сид-абзаце idx=1 (русский пилот) и от загрузок не зависит — не трогаем.

**Решение по ru→en байт-в-байт (отступление от решения №4 спеки):** владелец требует, чтобы **каждый** scoring-промпт называл пару языков. Значит преамбула «You are evaluating a translation from X into Y.» добавляется всегда, включая ru→en; рубрико-адаптер (про «read Russian as…») остаётся только для не-Russian→English пар. Сид-демо это не ломает (кеш прогрет, live-переоценка получит преамбулу — семантически нейтральную для ru→en).

---

## Задача 1 — judge.py: язык в каждом scoring-промпте

**Файлы:** `src/palimpsest/webapp/judge.py`, `tests/test_judge_lang.py`.

1.1. В `judge.py` заменить блок `LANG_NAMES` + `_adapter_preamble` + `scoring_system_prompt` (строки 43-65) на:

```python
LANG_NAMES = {"ru": "Russian", "en": "English", "de": "German", "fr": "French",
              "es": "Spanish", "it": "Italian", "pt": "Portuguese", "pl": "Polish",
              "uk": "Ukrainian", "zh": "Chinese", "ja": "Japanese", "ar": "Arabic"}


def lang_name(lang: str) -> str:
    """ISO code -> full name; free-text language names pass through as typed."""
    lang = lang.strip()
    return LANG_NAMES.get(lang.lower(), lang)


def _scoring_prompt(criterion_id: str) -> str:
    return (paths.PROMPTS / "scoring" / f"{criterion_id}.md").read_text(encoding="utf-8")


def scoring_system_prompt(criterion_id: str, source_lang: str = "ru", target_lang: str = "en") -> str:
    src, tgt = lang_name(source_lang), lang_name(target_lang)
    preamble = f"You are evaluating a translation from {src} into {tgt}.\n\n"
    if (src.lower(), tgt.lower()) != ("russian", "english"):
        preamble += (
            f"This rubric was written for Russian→English. Read every mention of Russian "
            f"as {src} (the source language) and every mention of English as {tgt} (the "
            f"target language). Ignore Cyrillic-specific transliteration rules when the "
            f"source is not Russian.\n\n"
        )
    return preamble + _scoring_prompt(criterion_id)
```

1.2. В `judge_one` (judge.py:76-77) заменить user-сообщение на полные названия:

```python
    user = (f"[SOURCE — {lang_name(source_lang)}]\n{source}\n\n"
            f"[TRANSLATION — {lang_name(target_lang)}]\n{target}")
```

1.3. Переписать `tests/test_judge_lang.py` (4 теста):

```python
def test_ru_en_prompt_states_languages():
    p = scoring_system_prompt("accuracy", "ru", "en")
    assert p.startswith("You are evaluating a translation from Russian into English.")
    disk = (paths.PROMPTS / "scoring" / "accuracy.md").read_text(encoding="utf-8")
    assert p.endswith(disk)                      # рубрика нетронута, преамбула — префикс
    assert "This rubric was written" not in p    # адаптер только для не-ru->en

def test_other_pair_gets_adapter_preamble():
    p = scoring_system_prompt("accuracy", "de", "fr")
    assert p.startswith("You are evaluating a translation from German into French.")
    assert "This rubric was written for Russian→English." in p

def test_free_text_language_passes_verbatim():
    p = scoring_system_prompt("accuracy", "Serbian", "English")
    assert p.startswith("You are evaluating a translation from Serbian into English.")
    assert "This rubric was written" in p        # Serbian != Russian -> адаптер есть

def test_user_message_labels_full_names():
    # используем существующий в файле фейк-клиент; проверяем шапки user-сообщения
    ...
    assert user.startswith("[SOURCE — German]\nQuelltext")
    assert "[TRANSLATION — French]" in user
```

(Тест `test_user_message_labels` в файле уже перехватывает user-сообщение через фейковый клиент — сохранить его механику, поменять только ожидания; `test_default_is_ru_en` — ожидания `[SOURCE — Russian]` / `[TRANSLATION — English]`.)

1.4. Проверка: `uv run pytest tests/test_judge_lang.py -q` — зелёный; `uv run pytest -q` — без новых падений.

1.5. Коммит: `feat(webapp): state source/target language in every scoring prompt`.

## Задача 2 — app.py: свободный ввод языков в API

**Файлы:** `src/palimpsest/webapp/app.py`, `tests/test_documents_create.py`.

2.1. Удалить `LANG_CODES` (`app.py:42`). В `create_document` заменить проверки языков (строки ~237-240):

```python
    src, tgt = body.sourceLang.strip(), body.targetLang.strip()
    if not src or not tgt or len(src) > 40 or len(tgt) > 40:
        raise HTTPException(422, "lang_required")
    if src.lower() == tgt.lower():
        raise HTTPException(422, "same_language")
```

и в INSERT подставлять `src, tgt` (вместо `body.sourceLang, body.targetLang`), чтобы в БД не попадали хвостовые пробелы.

2.2. `tests/test_documents_create.py`:
- `test_bad_lang_422` → заменить на:

```python
def test_empty_lang_422(client):
    assert client.post("/api/documents", json=_body(sourceLang="  ")).json()["detail"] == "lang_required"

def test_overlong_lang_422(client):
    assert client.post("/api/documents", json=_body(sourceLang="x" * 41)).json()["detail"] == "lang_required"

def test_free_text_lang_201(client):
    r = client.post("/api/documents", json=_body(sourceLang="Serbian", targetLang="English"))
    assert r.status_code == 201 and r.json()["sourceLang"] == "Serbian"

def test_same_language_case_insensitive_422(client):
    r = client.post("/api/documents", json=_body(sourceLang="Russian", targetLang="russian"))
    assert r.status_code == 422 and r.json()["detail"] == "same_language"
```

- `test_same_language_422` оставить (проверяет точное совпадение).

2.3. Проверка: `uv run pytest tests/test_documents_create.py tests/test_precompute.py -q`.

2.4. Коммит: `feat(webapp): accept free-text language names in POST /api/documents`.

## Задача 3 — UploadModal: текстовые поля языков + английский копирайт

**Файлы:** `frontend/src/demo/variant-a/upload/UploadModal.tsx`, `frontend/src/demo/variant-a/upload/UploadModal.test.tsx`.

3.1. Удалить `const LANGS = […]` (строка 5). В `SidePanel` добавить проп `langPlaceholder: string` и заменить `<select>` (строки 46-48) на:

```tsx
        <input
          className="va-lang-input"
          data-testid={`panel-${id}-lang`}
          placeholder={langPlaceholder}
          value={state.lang}
          onChange={(e) => onChange({ lang: e.target.value })}
        />
```

3.2. В `UploadModal` начальные значения языков — пустые, плейсхолдеры подсказывают полные названия:

```tsx
  const [src, setSrc] = useState<SideState>({ text: '', lang: '', busy: false, error: null });
  const [tgt, setTgt] = useState<SideState>({ text: '', lang: '', busy: false, error: null });
```

вызовы: `<SidePanel id="source" label="Original" langPlaceholder="Russian" … />`, `<SidePanel id="target" label="Translation" langPlaceholder="English" … />`.

3.3. Валидация шага 1 (строки 90-98) — языки обязательны, сравнение без регистра:

```tsx
  const srcLang = src.lang.trim();
  const tgtLang = tgt.lang.trim();
  const sameLang = !!srcLang && srcLang.toLowerCase() === tgtLang.toLowerCase();
  const canNext = !!title.trim() && !!src.text.trim() && !!tgt.text.trim()
    && !!srcLang && !!tgtLang && !sameLang && !tooLong && !tooMany && !src.busy && !tgt.busy;

  const problems = [
    sameLang && 'Source and target languages must differ',
    tooMany && `At most ${MAX_PARAS} paragraphs per side`,
    tooLong && `A paragraph exceeds ${MAX_PARA_CHARS} characters — split it`,
  ].filter(Boolean) as string[];
```

в `Step2` передавать trimmed: `srcLang={srcLang} tgtLang={tgtLang}`.

3.4. Полная замена русских строк на английские (точный копирайт):

| Строка (файл:строка) | Было | Станет |
|---|---|---|
| UploadModal.tsx:28 | `Заменить вставленный текст содержимым файла?` | `Replace the pasted text with the file contents?` |
| UploadModal.tsx:54 | `Вставьте текст\nили перетащите файл сюда (.docx, .md, .txt)` | `Paste text\nor drop a file here (.docx, .md, .txt)` |
| UploadModal.tsx:60 | `Загружен только первый файл` | `Only the first file was loaded` |
| UploadModal.tsx:65 | `Извлекаем текст…` | `Extracting text…` |
| UploadModal.tsx:68 | `📄 Загрузить файл` | `📄 Upload file` |
| UploadModal.tsx:72 | `{paras.length} § · {state.text.length} симв.` | `` {paras.length} ¶ · {state.text.length} chars `` |
| UploadModal.tsx:113 | `Новая пара «оригинал — перевод»` | `New source–translation pair` |
| UploadModal.tsx:114 | placeholder `Название` | `Title` |
| UploadModal.tsx:117/119 | label `Оригинал` / `Перевод` | `Original` / `Translation` |
| UploadModal.tsx:124 | `Отмена` | `Cancel` |
| UploadModal.tsx:126 | `Далее →` | `Next →` |
| UploadModal.tsx:188 | `Выравнивание абзацев` | `Paragraph alignment` |
| UploadModal.tsx:190 | `Оригинал: {n} § · Перевод: {m} §` | `Original: {src.length} ¶ · Translation: {tgt.length} ¶` |
| UploadModal.tsx:191 | ` ⚠ количество не совпадает` | ` ⚠ counts do not match` |
| UploadModal.tsx:199/207 | `— (нет пары)` | `— (no pair)` |
| UploadModal.tsx:202/210 | `⇧ склеить с пред.` | `⇧ merge with previous` |
| UploadModal.tsx:221-222 | `Оценить документ и прогреть кеш-фолбэк после создания (первые {n} §, ~$X, в фоне)` | `Score the document and warm the cache fallback after creation (first {precomputePlanned} ¶, ~${…}, in background)` |
| UploadModal.tsx:226 | `← Назад` | `← Back` |
| UploadModal.tsx:229 | `Создать документ` | `Create document` |

Русские комментарии в файле (`(решение №5)` и т.п.) перевести на английский (`// default ON (spec decision #5)`).

3.5. `UploadModal.test.tsx`: обновить ожидания — `label="Оригинал"` → `label="Original"` + добавить обязательный `langPlaceholder="Russian"`; регексы `/первые 3 §, ~\$0\.06, в фоне/` → `/first 3 ¶, ~\$0\.06, in background/` (аналогично для 12 ¶); добавить тест «Next заблокирована при пустом поле языка»:

```tsx
  it('keeps Next disabled until both languages are typed', () => {
    render(<UploadModal />);
    fireEvent.change(screen.getByTestId('panel-source-textarea'), { target: { value: 'Текст абзаца' } });
    fireEvent.change(screen.getByTestId('panel-target-textarea'), { target: { value: 'Paragraph text' } });
    fireEvent.change(screen.getByPlaceholderText('Title'), { target: { value: 'Doc' } });
    expect(screen.getByText('Next →').closest('button')).toHaveProperty('disabled', true);
    fireEvent.change(screen.getByTestId('panel-source-lang'), { target: { value: 'Russian' } });
    fireEvent.change(screen.getByTestId('panel-target-lang'), { target: { value: 'English' } });
    expect(screen.getByText('Next →').closest('button')).toHaveProperty('disabled', false);
  });
```

**Важно:** русские текстовые ФИКСТУРЫ в тестах (`'Текст абзаца'`, `'один'`, cp1251-кейсы) — не UI-строки, а тестовые данные RU-контента; их НЕ переводить.

3.6. Проверка: `cd frontend && npm test`.

3.7. Коммит: `feat(upload): free-text language inputs + English UI copy in upload modal`.

## Задача 4 — file-ingest.ts / md-strip.ts: английские сообщения и комментарии

**Файлы:** `frontend/src/demo/variant-a/upload/file-ingest.ts`, `frontend/src/demo/variant-a/upload/md-strip.ts`, их тесты.

4.1. `file-ingest.ts` — карта ошибок (строки 6-14):

```ts
const ERRORS: Record<number, string> = {
  415: 'Unsupported format. Save the document as .docx and upload again',
  422: 'The file is corrupted or is not a Word document (.docx)',
  413: 'File exceeds 5 MB — split the document or paste the text in parts',
};

export function errorMessage(status: number): string {
  return ERRORS[status] ?? `Could not process the file (HTTP ${status})`;
}
```

4.2. Все русские комментарии/докстроки в `file-ingest.ts` (строки 16-17, 31-34, 48, 52, 56, 59) и `md-strip.ts` (строки 1, 4-16) перевести на английский, сохраняя смысл WHY (пример: `/** UTF-8 -> retry windows-1251 on U+FFFD (spec §5.4, legacy RU texts). If even the cp1251 fallback is mostly control chars (a binary, not text), treat the file as unreadable instead of silently pasting mojibake into the textarea. */`).

4.3. В тестах `file-ingest.test.ts` / `md-strip.test.ts` обновить ожидания сообщений об ошибках на новые английские строки; русские входные фикстуры оставить.

4.4. Проверка: `cd frontend && npm test`; контрольный grep — `grep -rn '[А-Яа-яЁё]' frontend/src/demo/variant-a/upload/` должен находить Cyrillic **только** в тестовых фикстурах.

4.5. Коммит: `fix(upload): English error messages and comments in file ingest`.

## Задача 5 — остальные русские UI-строки + отображение языков

**Файлы:** `frontend/src/demo/variant-a/VariantA.tsx`, `InspectorPanel.tsx`, `SettingsTab.tsx`, `frontend/src/demo/store.ts`, `frontend/src/demo/variant-a/GlossaryTab.tsx`, новый `frontend/src/demo/lang.ts`, тест `SettingsTab.test.tsx`.

5.1. Новый модуль отображения языков `frontend/src/demo/lang.ts` (пилотные документы хранят коды `ru`/`en`, загрузки — свободный текст):

```ts
/** Pilot documents store ISO codes; uploads store free-text names. Map the
 *  two known codes to full names, pass anything else through as typed. */
const LANG_LABELS: Record<string, string> = { ru: 'Russian', en: 'English' };

export function langLabel(lang: string): string {
  return LANG_LABELS[lang.toLowerCase()] ?? lang;
}
```

5.2. Заменить все `sourceLang.toUpperCase()` / `targetLang.toUpperCase()` на `langLabel(…)` (иначе свободный текст отрисуется капсом «SERBIAN»):
- `VariantA.tsx:314`: `{d.title} · {langLabel(d.sourceLang)} → {langLabel(d.targetLang)} · {d.nParagraphs}¶`
- `VariantA.tsx:433-434`: `Original ({langLabel(doc.sourceLang)})` / `Translation ({langLabel(doc.targetLang)})`
- `GlossaryTab.tsx:42-43`: `Source ({langLabel(sourceLang)})` / `Target ({langLabel(targetLang)})`

5.3. Русские строки:
- `VariantA.tsx:321`: `title="Удалить документ"` → `title="Delete document"`
- `VariantA.tsx:323`: `` `Удалить «${doc.title}»?` `` → `` `Delete “${doc.title}”?` ``
- `VariantA.tsx:330`: `+ Загрузить пару` → `+ Upload pair`
- `VariantA.tsx:334`: `прогрев {done}/{planned} §…` → `warming {doc.precompute.done}/{doc.precompute.planned} ¶…`
- `InspectorPanel.tsx:74`: `title="Пересчитать оценки этого абзаца"` → `title="Re-score this paragraph"`
- `InspectorPanel.tsx:76`: `Оценить ↻` → `Evaluate ↻`
- `InspectorPanel.tsx:104`: `Live-оценка не удалась; для этого абзаца нет прогретого кеша. Повторите` → `Live evaluation failed and no warmed cache exists for this paragraph. Try again`
- `SettingsTab.tsx:181,246`: `` `Удалить «${…}»?` `` → `` `Delete “${c.name}”?` `` / `` `Delete “${m.name}”?` ``
- `store.ts:459-460`: alert → `` `Applied ${appliedCount} of ${issueIds.length}; ${skipped} fragment${skipped === 1 ? '' : 's'} not found in the text.` ``

5.4. `SettingsTab.test.tsx:78`: ожидание confirm-текста → `` `Delete “${criterion.name}”?` ``. Прогнать `cd frontend && npm test`; затем финальный контроль инварианта:

```
grep -rn '[А-Яа-яЁё]' frontend/src/demo/ --include='*.ts' --include='*.tsx' \
  | grep -v '.test.' | grep -v 'TermPopover'
```

— ноль строк (TermPopover.test и фикстуры — легитимный RU-контент данных).

5.5. Коммит: `fix(demo): English-only product UI + language display labels`.

## Задача 6 — CSS: кнопки, переполнение Название, поля языков

**Файлы:** `frontend/src/demo/variant-a/variant-a.css`, `frontend/src/demo/variant-a/upload/UploadModal.tsx` (className).

Диагноз:
- **Переполнение «Название»:** `.va-modal-wide` — flex-колонка (align-items: stretch), а у `.va-modal-title-input` дефолтный `box-sizing: content-box` → растянутый инпут добавляет свои `padding: 8px 10px` + border ПОВЕРХ ширины контейнера и вылезает за него.
- **Кнопка файла:** `.va-upload-panel-foot button` — самописный стиль, не совпадающий с системой кнопок (`va-btn-secondary`); внешний вид с фокус-обводкой браузера читается как «жёлтая рамка».

6.1. Фикс переполнения (variant-a.css:1367):

```css
.va-modal-title-input {
  box-sizing: border-box;
  background: var(--va-bg);
  border: 1px solid var(--va-border2);
  border-radius: var(--va-radius-sm);
  color: var(--va-text);
  font-family: var(--va-font);
  font-size: 13px;
  padding: 8px 10px;
}
```

6.2. Стиль текстовых полей языка — как у поля Название, компактный (заменить блок `.va-upload-panel-head select`, variant-a.css:1406-1413):

```css
.va-lang-input {
  box-sizing: border-box;
  width: 110px;
  background: var(--va-bg);
  border: 1px solid var(--va-border2);
  border-radius: var(--va-radius-sm);
  color: var(--va-text);
  font-family: var(--va-font);
  font-size: 12px;
  font-weight: 400;
  padding: 4px 8px;
}

.va-lang-input:focus {
  outline: none;
  border-color: var(--va-accent);
}
```

6.3. Кнопки — переиспользовать систему вместо самописных стилей:
- в JSX: кнопке файла (`UploadModal.tsx:67`) и кнопкам склейки (`:201,209`) добавить `className="va-btn-secondary"`;
- удалить блоки `.va-upload-panel-foot button` и `.va-upload-panel-foot button:hover…` (variant-a.css:1445-1459);
- от `.va-step2-table button` оставить только layout (`display: block; margin-top: 6px; margin-left: auto;`), декоративные свойства удалить (их даёт `va-btn-secondary`);
- добавить видимый фокус в системе кнопок:

```css
.va-btn-secondary:focus-visible,
.va-modal-actions button:focus-visible {
  outline: 2px solid var(--va-accent);
  outline-offset: 1px;
}
```

6.4. Проверка: `cd frontend && npm test` (klassName-зависимые тесты); визуально — открыть http://localhost:5173, модалка: поле Title не вылезает, кнопка Upload file в стиле остальных, поля языков в стиле Title. Ничего не рестартовать: vite подхватит HMR.

6.5. Коммит: `fix(upload): align modal controls with the va button/input system`.

## Задача 7 — Упрощения кода (безопасные, из ревью)

Каждый пункт — отдельный маленький коммит; после каждого `npm test` / `uv run pytest -q`.

7.1. **Мёртвый try/catch в декодере** (`file-ingest.ts:44-50`). `new TextDecoder('windows-1251')` поддержан всеми целевыми браузерами, а `decode()` без `fatal: true` не бросает — catch недостижим. Инлайн:

```ts
export function decodeText(buf: ArrayBuffer): string {
  const utf8 = new TextDecoder('utf-8').decode(buf);
  const decoded = utf8.includes('�') ? new TextDecoder('windows-1251').decode(buf) : utf8;
  if (controlCharRatio(decoded) > UNREADABLE_CONTROL_CHAR_RATIO) {
    throw Object.assign(new Error(errorMessage(422)), { status: 422 });
  }
  return decoded;
}
```

(функция `decodeCp1251Fallback` удаляется). Коммит: `refactor(upload): inline dead cp1251 fallback wrapper`.

7.2. **Двойная установка warning при drop** (`UploadModal.tsx:60-62`). `onChange({ error: warning })` перед `loadFile` бессмыслен: `loadFile` тут же ставит `error: null` и на успехе снова ставит warning. Удалить строку `if (warning) onChange({ error: warning });`. Коммит: `refactor(upload): drop redundant pre-set of drop warning`.

7.3. **Захардкоженная копия бэкенд-констант** (`UploadModal.tsx:8-12`): `PRECOMPUTE_CRITERIA_COUNT = 5` дрейфует от реального числа включённых критериев (store уже их держит). В `Step2`:

```tsx
  const criteriaCount = useDemoStore((s) => s.criteria.filter((c) => c.enabled).length);
  const precomputeCostUsd = Math.round(precomputePlanned * criteriaCount * PRECOMPUTE_COST_PER_CALL * 100) / 100;
```

константу `PRECOMPUTE_CRITERIA_COUNT` удалить; тест с `~$0.06`/`~$0.24` обеспечить фикстурой store с 5 включёнными критериями (или пересчитать ожидания под мок). Коммит: `refactor(upload): derive precompute cost from enabled criteria`.

7.4. **app.py лезет в приватное состояние precompute** (`app.py:265-277`: `precompute._status[doc_id] = …`, `precompute._tasks[doc_id] = t`). Инкапсулировать в `precompute.py` двумя функциями (статус ставится ДО сборки 201-ответа под локом, задача стартует ПОСЛЕ — семантику сохранить):

```python
def mark_started(doc_id: int, n_paragraphs: int) -> None:
    """Pre-set status so the 201 body already carries it; run() refines later."""
    _status[doc_id] = {"status": "running", "done": 0,
                       "planned": min(n_paragraphs, PRECOMPUTE_PARAS)}


def launch(doc_id: int, judge_live) -> None:
    t = asyncio.create_task(run(doc_id, judge_live))
    _tasks[doc_id] = t
    t.add_done_callback(lambda _: _tasks.pop(doc_id, None))
```

в `create_document`: `precompute.mark_started(doc_id, len(body.paragraphs))` внутри лока, `precompute.launch(doc_id, _judge_live)` после. Проверить, что `tests/test_precompute.py` и `tests/test_documents_create.py` зелёные. Коммит: `refactor(webapp): encapsulate precompute start behind mark_started/launch`.

7.5. **Утроенный список языков** — `LANGS` (UploadModal.tsx:5) и `LANG_CODES` (app.py:42) уже удалены задачами 2-3; `LANG_NAMES` в judge.py остаётся единственным словарём (нормализация кодов сида) + `LANG_LABELS` из 2 записей на фронте для отображения. Отдельного коммита не требует — зафиксировать факт в PR-описании.

Кандидаты, которые ревью сознательно НЕ берёт (чтобы не раздувать диff): двойной guard `submitting`+`inFlight` (оба нужны: state — для рендера, ref — синхронный барьер, уже задокументировано комментарием); `_read_body_capped` (проверка Content-Length до чтения тела — дешёвый отказ, спека требует 413 до pydantic); повторный SELECT документа после INSERT (идиоматично, дешевле ручной сборки dict).

## Задача 8 — Синхронизация документации

**Файлы:** `docs/subsystems/webapp.md`, `docs/superpowers/specs/2026-07-02-custom-pair-upload-design.md`.

8.1. `docs/subsystems/webapp.md`: обновить контракт `POST /api/documents` (языки — свободный текст, `lang_required` вместо `bad_lang_code`, `same_language` без регистра) и описание scoring-промпта (преамбула «You are evaluating a translation from X into Y.» теперь во всех парах, включая ru→en). Проверить `docs/testing/e2e-data.md` — если там упомянуты русские подписи модалки или дропдауны языков, обновить на английский копирайт и текстовые поля.

8.2. В спеку `2026-07-02-custom-pair-upload-design.md` добавить в начало блок:

```markdown
> ⚠️ Актуализация 2026-07-02 (upload-polish): решение №4 (байт-в-байт для ru→en)
> заменено — языковая преамбула добавляется во ВСЕ scoring-промпты; дропдауны
> языков заменены свободным текстовым вводом; UI-копирайт — английский
> (русские строки из этой спеки в UI не попадают). См.
> [план](../plans/2026-07-02-upload-polish.md).
```

8.3. Коммит: `docs(webapp): sync upload contract with free-text languages and EN copy`.

## Задача 9 — Финальная проверка

9.1. `cd frontend && npm test` — все vitest зелёные.
9.2. `uv run pytest -q` — все pytest зелёные.
9.3. Контроль инварианта: grep из задачи 5.4 — ноль user-facing Cyrillic.
9.4. Ручной smoke в браузере (серверы 5173/8000 уже запущены): открыть модалку → напечатать языки текстом («Russian»/«English») → шаг 2 → создать пару из 2-3 абзацев с `precompute` OFF (без трат) → документ появился, заголовки колонок «Original (Russian)». Один платный вызов Evaluate — проверить, что live-оценка прошла (промпт с преамбулой).

## Критерии приёмки

- [ ] `grep -rn '[А-Яа-яЁё]' frontend/src/demo --include='*.ts' --include='*.tsx'` — совпадения только в тестовых фикстурах RU-контента.
- [ ] Языки вводятся любым текстом; введённое значение дословно (после trim) попадает в `document.source_lang/target_lang` и в преамбулу scoring-промпта.
- [ ] Каждый scoring-промпт (включая ru→en) начинается с «You are evaluating a translation from {X} into {Y}.».
- [ ] Пилотные `ru`/`en` отображаются как «Russian»/«English» во всех местах показа языков.
- [ ] Поле Title не переполняет модалку; кнопка Upload file и поля языков — в системе `--va-*`.
- [ ] Упрощения 7.1-7.4 применены, все тесты зелёные.
