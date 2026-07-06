# Спека S3 — Upload modal: полировка внешнего вида + функциональная надёжность

Дата: 2026-07-05. Ветка: `claude/emlp-2026-website-fixes-muih1x`.
Базовая спека: [2026-07-02-custom-pair-upload-design.md](2026-07-02-custom-pair-upload-design.md) (дизайн 2-шаговой модалки остаётся в силе; здесь — точечная полировка по скрину 3 владельца). Связана: S4 [2026-07-05-translator.md](2026-07-05-translator.md) добавляет в эту же модалку режим source-only.

## 0. Grounding

- `UploadModal.tsx:69-71`: кнопка `📄 Upload file` — эмодзи, вид «стандартной некрасивой иконки» (жалоба владельца, скрин 3). На Source-панели кнопка в фокус-стиле с синей рамкой, на Translation — dashed: непоследовательно.
- Ингест (`file-ingest.ts`): .docx → `POST /api/documents/extract-text` (python-docx, 5MB, .doc → 415 с подсказкой), .md → клиентский strip, .txt → decodeText (UTF-8 → windows-1251 fallback). Рабочее, нужен e2e-прогон.
- Multi-drop: грузится только первый файл + предупреждение (ок), лимиты 40¶/4000 симв. продублированы в двух константах (client `UploadModal.tsx:5-6`, server `app.py:51-52`) — риск дрейфа.

## 1. Цель

Окно загрузки выглядит цельно в дизайн-системе variant-a (никаких эмодзи и браузерных дефолтов) и проверенно работает на всех трёх форматах + всех ошибочных путях.

## 2. UI-изменения

### 2.1 Кнопка Upload file
- Заменить эмодзи на inline-SVG (16×16, `stroke=currentColor`, без заливки): стрелка-вверх из лотка (классический upload-глиф). SVG кладётся компонентом `UploadIcon` рядом с модалкой, без внешних иконок-пакетов.
- Единый стиль обеих панелей: `va-btn-secondary` (transparent, `--va-border2`, muted → hover accent), иконка слева, 8px gap. Никаких синих фокус-рамок по умолчанию (только реальный `:focus-visible`).
- Hint `.docx · .md · .txt` — рядом, `--va-text-dim`, 12px, моно.

### 2.2 Drag-and-drop состояние
- При dragover над textarea панель получает класс `va-upload-drop-active`: рамка `1px dashed var(--va-accent)` + фон `rgba(122,162,247,.06)` + плейсхолдер меняется на `Drop file to load` — сейчас визуального отклика нет.
- Плейсхолдер обеих textarea: `Paste text or drop a file here (.docx, .md, .txt)` — как сейчас, проверить идентичность панелей.

### 2.3 Мелочи консистентности
- Счётчик `0 ¶ · 0 chars` — выравнивание по правому краю футера панели, моно, `--va-text-muted` (сейчас ок — зафиксировать e2e-скрином).
- Кнопка `Next →` disabled-состояние: тултип-подсказка не нужна, но подпись-хелпер под модалкой (`Enter source and target languages to continue`) должна называть РЕАЛЬНУЮ блокирующую причину: если языки заполнены, а текста нет → `Add source and translation text to continue`; при активном S4-режиме source-only → см. S4 §3.2. Реализация: одна функция `nextBlockReason()` возвращает string|null, рендерится в один слот.
- Лимиты: вынести 40/4000 в один модуль `frontend/src/demo/limits.ts` + отдать их с бэка в `GET /api/health` (`limits:{max_paragraphs,max_para_chars}`) и на старте синхронизировать store (SSOT — сервер). Контракт дополнить.

## 3. Функциональная проверка (входит в Definition of Done)

E2E (playwright, шаг 6/8): 
1. .txt (UTF-8 ru) → Source, текст появился, счётчик ¶ верный;
2. .md → strip разметки (заголовки/ссылки исчезли);
3. .docx (сгенерировать python-docx в тест-фикстуру) → извлечение через API;
4. .doc → 415, дружелюбная ошибка в `va-upload-error`;
5. файл > 5MB → ошибка размера;
6. windows-1251 .txt → корректная кириллица;
7. drag-and-drop файла → dropzone-подсветка → загрузка;
8. 2 файла разом → предупреждение «Only the first file was loaded»;
9. полный happy-path: пара RU/EN → Step 2 alignment → merge-up → Create → документ открыт.
Каждый пункт — скриншот. Фикстуры в `tests/fixtures/upload/` (маленькие, в репо).

## 4. Тесты
- Vitest: `nextBlockReason()` все ветки; UploadIcon рендер; dropzone-класс на dragover/dragleave.
- Pytest: `/api/health` limits; extract-text негативные ветки уже покрыты — проверить и дополнить 415/413.

## 5. Риски
- python-docx фикстура: генерировать в conftest (не хранить бинарь) — детерминированно.
- Дизайн-ревью: скрин обновлённой модалки сравнить с мокапом S4 (общий мокап Settings/Upload, см. S4 §5) перед merge.
