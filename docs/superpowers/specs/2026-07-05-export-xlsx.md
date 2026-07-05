# Спека S6 — Экспорт перевода (Excel с выравниванием по абзацам + Markdown)

Дата: 2026-07-05. Ветка: `claude/emlp-2026-website-fixes-muih1x`.
Владельческое требование: «Должна быть возможность выгрузить перевод. Как вариант — в Excel с выравниванием по абзацам (так делали на каком-то другом сайте из демки)».

## 0. Grounding
- Экспорта нет вообще: ни route, ни кнопки, ни xlsx-зависимости (разведка §6). `python-docx` есть (только чтение). `openpyxl` в pyproject отсутствует — добавить.

## 1. Цель
Одна кнопка — файл с параллельным текстом «абзац к абзацу», готовый отправить коллеге. Два формата: `.xlsx` (основной, как просил владелец) и `.md` (дешёвый бонус для копипасты; 2 строки кода поверх той же выборки).

## 2. Контракт (дельта SSOT)
- `GET /api/documents/{doc_id}/export?format=xlsx|md` → файл:
  - 200, `Content-Disposition: attachment; filename="{slug(title)}-{doc_id}.{ext}"`; mime `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` / `text/markdown; charset=utf-8`.
  - 404 незнакомый документ; 422 незнакомый format.
- Никаких изменений схемы БД.

## 3. Формат xlsx (openpyxl, модуль `src/palimpsest/webapp/export.py`)
- Лист `Translation`. Колонки: `A ¶` (номер, ширина 6), `B Source · {Source_lang}` (58), `C Translation · {Target_lang}` (58), `D Score` (9).
- Строка 1 — заголовок: жирный, фон `1F2035`, текст `C0CAF5` (фирменный тёмный стиль), freeze `A2`.
- Данные: по абзацу на строку, idx по порядку; wrap_text=True, vertical=top; Score = latest aggregate (1 знак после точки) или пусто; `D` — цветной шрифт по порогам: ≥8 зелёный `3DDC84`, 6–8 жёлтый `E0AF68`, <6 красный `F7768E` (совпадает с UI-порогами score-чипа).
- Строка 2 (мета, серым, merged A:D, НЕ фильтруется): `"{title}" · {source_lang} → {target_lang} · exported {UTC ISO date} · Palimpsest` (кавычки прямые — в EN-копирайте гильеметов нет, инвариант 9).
- Пустой target (недопереведённый S4-документ) → ячейка C пустая — честно.

## 4. Формат md
```
# {title}

| ¶ | Source ({sl}) | Translation ({tl}) |
|---|---|---|
| 1 | … | … |
```
Экранирование `|` и переводов строк (`<br>`) в ячейках.

## 5. Frontend
- Кнопка `Export` в топ-баре документа, справа, рядом с существующими действиями (Reset/score): `va-btn-secondary` + иконка-глиф download (inline SVG, стиль как UploadIcon S3). Клик → маленькое va-popover-меню из двух пунктов: `Excel (.xlsx)` / `Markdown (.md)`.
- Реализация скачивания: `window.location.assign(url)` не годится (SPA), использовать `<a href={url} download>` программно (fetch не нужен — same-origin GET). Disabled, пока документ пуст.
- UI-копирайт: `Export`, `Excel (.xlsx)`, `Markdown (.md)`.

## 6. Тесты
- Pytest: xlsx открывается openpyxl-ом обратно (round-trip), кол-во строк = ¶+2, заголовки/мета верны, score-пороги красятся, 404/422-ветки; md-таблица с экранированием.
- Vitest: меню открывается, href верный per format, disabled на пустом doc.
- E2E: скачать оба формата на seed-документе (проверить размер >0 и имя файла), скриншот меню.

## 7. Риски
- openpyxl: ревью подтвердило — `openpyxl==3.1.5` УЖЕ разрешён в uv.lock (транзитивно через docling); `uv add openpyxl` — тривиальное повышение до прямой зависимости, нулевой риск конфликтов.
- Большие тексты в ячейках Excel (лимит 32767 симв.) — абзацы ≤4000, запас 8×.
