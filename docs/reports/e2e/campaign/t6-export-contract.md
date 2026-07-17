# T6 — Экспорт: новый .md-контракт (прод https://glossa-mt.com)

**Дата:** 2026-07-17, 10:55–11:20 MSK · **Агент:** e2e-tester (сессия playwright-cli `-s=t6`, эфемерный клон, golden не тронут, X-Golden-Session не использовался) · **Контракт:** commit `6e52919` + SSOT [2026-06-30-demo-contracts.md § export](../../../superpowers/specs/2026-06-30-demo-contracts.md).

## Вердикт: PASS-WITH-FINDINGS

Все 8 подпунктов (а)–(з) выполнены и доказаны артефактами; новый .md-контракт соблюдён на проде побайтово во всех состояниях (создание, warming, refine, restore, ручная правка, mid-translate). Багов уровня HIGH/MEDIUM не найдено; 2 находки LOW-уровня (слаг имени файла для CJK-заголовка, case-sensitive `format`). 0 JS-ошибок от приложения за весь прогон.

## План сценария и статус

| Подпункт | Статус |
|---|---|
| Setup: свой документ через upload modal (UI only) | executed |
| (а) .md сразу после создания = `# {title}` + плоский текст | executed — PASS |
| (б) refine ¶ → re-export = новая ревизия | executed — PASS |
| (в) restore старой ревизии → export отражает | executed — PASS |
| (г) ручная правка (TipTap) → export отражает | executed — PASS |
| (д) export во время warming (термы running) | executed — PASS |
| (е) .xlsx скачивается и открывается | executed — PASS |
| (ж) 404/422 на несуществующий док / формат (+3 edge-кейса сверх плана) | executed — PASS |
| (з) CJK-документ → .md валиден в UTF-8 | executed — PASS |
| Бонус (сверх плана): mid-translate skip пустых target (клауза контракта) | executed — PASS, 5 промежуточных состояний |
| Cleanup: удаление всех созданных доков через UI | executed |

## Данные и provenance

| Значение | Источник |
|---|---|
| Источник RU (8 ¶, 1743 chars) | `docs/testing/e2e-campaign/t5-ru-source.txt` (манифест, campaign fixtures) |
| Перевод EN (8 ¶, 1963 chars) | `docs/testing/e2e-campaign/t5-en-translation.txt` |
| CJK-источник (5 ¶) | `docs/testing/e2e-campaign/t2-zh-source.txt` |
| CJK→EN перевод (5 ¶) | `docs/testing/e2e-campaign/t2-en-translation.txt` |
| Заголовки «T6 Export Contract», «秦汉历史», «T6 Mid-Translate(-8p)» | GENERATED: метаданные тестовых документов (заголовок — свободное поле модалки; «秦汉历史» выбран намеренно чисто-CJK для атаки на слаг имени файла) |
| Текст ручной правки ¶2 («…is on display in London, at the British Museum.») | GENERATED: минимальная редакторская перефразировка фикстурного ¶2 — нужен детерминированный дифф для (г) |

## Таблица шагов

| # | Шаг | Ожидание | Факт | Вердикт | Артефакт |
|---|---|---|---|---|---|
| 1 | Открыть прод | landing отвечает | пикер: World History + Blank document | pass | `shots/campaign/t6/01-landing.png` |
| 2 | Blank document → модалка, title/langs/paste t5 RU+EN | 8 ¶ = 8 ¶, Next активен | «8 ¶ · 1743» / «8 ¶ · 1963» | pass | `02-modal-filled.png` |
| 3 | Step 2: выравнивание, precompute checked (~$0.10) | Create активен | Source: 8 ¶ · Translation: 8 ¶ | pass | `03-modal-step2-aligned.png` |
| 4 | Create → док id=18, warming | badge warming + Extracting terminology | «warming 3/8 ¶…» + «Extracting terminology…» видны | pass | `04-doc-created-warming.png` |
| 5 | (а)+(д) Export→Markdown ВО ВРЕМЯ warming/термов | корректный файл, без ошибки | скачан `t6-export-contract-18.md`, HTTP download ok | pass | `05-export-menu.png`, `t6-files/export-a-initial.md` |
| 6 | (а) контракт файла | `# {title}` + 8 блоков = фикстура, без таблиц/`\|`/`<br>` | first line `# T6 Export Contract`; 8 блоков **побайтово** = t5-en-translation.txt; has_pipe=False, has_br=False, table_dash=False | **PASS** | python-проверка (лог ниже) |
| 7 | (б) выбрать §2 → Refine paragraph ✦ | 200, новая ревизия | POST `/api/paragraphs/117/refine` → 200; ревизия 295 `origin=refine, isCurrent` («is kept elsewhere»→«is housed elsewhere») | pass | `06-para2-selected.png`, `07-para2-refined.png`, `t6-files/para2-before-refine.json` |
| 8 | (б) re-export → дифф | ровно ¶2 = новая ревизия | diff a↔b: единственная строка 5 (см. ниже) | **PASS** | `t6-files/export-b-after-refine.md` |
| 9 | (в) Scores → Revision history → Restore (upload-ревизия) | export = восстановленный текст | ревизия 296 `origin=restore, isCurrent` (append, не overwrite); export-c **байт-в-байт = export-a**; на §2 честный бейдж «stale» | **PASS** | `08-revision-history.png`, `09-restored-revision.png`, `t6-files/export-c-after-restore.md` |
| 10 | (г) TipTap: Ctrl+A + новый текст ¶2, blur | ревизия origin=edit, export отражает | ревизия 297 `origin=edit, isCurrent`; diff c↔d: одна строка 5, «…is on display in London, at the British Museum.» | **PASS** | `10-manual-edit.png`, `t6-files/export-d-after-edit.md` |
| 11 | (е) Export→Excel (.xlsx) | скачивается и открывается | `t6-export-contract-18.xlsx` 8.3 KB; openpyxl: sheet «Translation», A1:D10, header `['¶','Source · Russian','Translation · English','Score']`, meta-строка, ¶2 = актуальная ручная правка | **PASS** | `t6-files/export-e.xlsx` |
| 12 | (ж) негативные GET (интерфейс экспорта) | 404/422 | id=99999→**404** `document not found`; format=pdf→**422** `unknown format`; format=MD→422; без format→200 xlsx (дефолт); id=-1→404; id=abc→422 int_parsing | **PASS** | `t6-files/negative-checks.json` |
| 13 | (з) CJK-док id=19 (秦汉历史, zh→en, t2-фикстуры, precompute OFF) | .md валиден UTF-8 | скачан **`document-19.md`**; UTF-8 decode ok; `# 秦汉历史`; 5 блоков побайтово = t2-en-translation.txt; без `\|`/`<br>` | **PASS** (+находка F1 об имени файла) | `11-cjk-step2.png`, `12-cjk-doc.png`, `t6-files/export-z-cjk.md` |
| 14 | Бонус: skip пустых target mid-translate (док 21, Create & translate, 8 ¶) | пропуск непереведённых, без пустых блоков | при done=1,2,3,5,7 export 200 и **mdBlocks ровно = done**, tripleNL=0 (нет пустых блоков); при done=8 — 8 блоков | **PASS** | `13-midtranslate.png`, `14-midtranslate-8p-done.png`, `t6-files/midtranslate-8p-samples.json`, `export-midtranslate-8p-final.md` |
| 15 | Заголовки позитивного экспорта | контрактные CT/CD | md: `text/markdown; charset=utf-8`, `attachment; filename="world-history-selected-passages-10.md"`; xlsx: openxml CT + CD | pass | `t6-files/positive-headers.json` |
| 16 | Cleanup через UI (select → 🗑 → confirm) | удалены только свои | доки 21, 20, 19, 18 удалены; остался только «World History — Selected Passages» | pass | `15-before-cleanup-dropdown.png`, `16-after-cleanup.png` |
| 17 | Консоль после каждого крупного шага | 0 ошибок приложения | итог: 10 ERROR — **все 10 = мои собственные негативные fetch-запросы из шага 12** (2 прогона × 5 кейсов, 404/422 resource-load); от приложения — 0 | pass | лог консоли в тексте |

## Доказательства диффов (б)–(г) построчно

**(б) a → b (после refine), единственное изменение — строка 5 (= ¶2):**
```
5c5
< …The Standard of Ur with its lapis lazuli inlay is kept elsewhere: London, the British Museum.
---
> …The Standard of Ur with its lapis lazuli inlay is housed elsewhere: London, the British Museum.
```

**(в) b → c (после restore): строка 5 вернулась к исходной; `diff -q export-a export-c` → идентичны (побайтово).**

**(г) c → d (после ручной правки), строка 5:**
```
< …lapis lazuli inlay is kept elsewhere: London, the British Museum.
---
> …lapis lazuli inlay is on display in London, at the British Museum.
```

## Первые строки приложенных файлов

`export-a-initial.md` (= b-, c-, d- отличаются только строкой 5):
```
# T6 Export Contract

The Stele of Naram-Suen, erected to commemorate the victory over the Lullubi, is one of the masterpieces of Akkadian art. Late 23rd century BC. Paris, the Louvre.
```
`export-z-cjk.md`:
```
# 秦汉历史

In 221 BC, the Qin dynasty unified China. Qin Shi Huang abolished the feudal enfeoffment system, …
```
`export-midtranslate-8p-final.md`:
```
# T6 Mid-Translate 8p

The Stele of Naram-Sin, erected in honor of the victory over the Lullubi, is one of the masterpieces of Akkadian art. Late 23rd century BC. Paris, Louvre.
```
`export-e.xlsx` (openpyxl): sheet `Translation`, header `¶ | Source · Russian | Translation · English | Score`, meta `"T6 Export Contract" · Russian → English · exported 2026-07-17 · Glossa-MT`.

Контрактная python-проверка (а): `first line: '# T6 Export Contract'; total blocks: 9 (= 1 title + 8); has pipe: False; has <br>: False; table dash row: False; body == fixture paragraphs in order: True`.

## Находки

| # | Severity | Находка | Репро | Артефакт |
|---|---|---|---|---|
| F1 | LOW | Чисто-CJK заголовок теряется в имени файла: `slugify('秦汉历史')` → fallback `document`, файл скачивается как `document-19.md`. Гипотеза атаки из спеки («имя файла с не-ASCII слагом») не привела к поломке — fallback отработал, но заголовок в имени файла утрачен полностью. Для смешанных заголовков останутся только ASCII-фрагменты. | Создать док с заголовком «秦汉历史» → Export → Markdown | `t6-files/export-z-cjk.md` (имя при скачивании `document-19.md`), лог download |
| F2 | LOW (наблюдение) | `format=MD` (uppercase) → 422 `unknown format`. Формально по контракту (`format=xlsx\|md` — литерально), но case-insensitive матч был бы дружелюбнее для прямых ссылок. | `GET /api/documents/{id}/export?format=MD` | `t6-files/negative-checks.json` |
| F3 | SUSPECTED (tooling, не продукт) | `playwright-cli select` по ref комбобокса документов дважды молча не менял выбор (value оставался прежним); `page.locator('select').selectOption()` через run-code работает стабильно. Наиболее вероятная причина — устаревшие refs после ре-рендера React; продуктового бага не зафиксировано. | см. лог сессии | — |

Позитивные наблюдения: после restore на §2 появляется честный бейдж «stale: scores refer to an earlier version»; ревизии только аппендятся (295 refine → 296 restore → 297 edit), ничего не перезаписано — инвариант «never delete predictions» соблюдён; экспорт в момент «Extracting terminology…» + «warming 3/8 ¶» не 500-ит (гипотеза атаки не подтвердилась).

## Ran vs didn't run

**Ran:** все подпункты (а)–(з); 6 UI-скачиваний экспорта (5×.md, 1×.xlsx) через меню Export; refine/restore/edit через UI; 2 документа через upload modal (paste) + 2 через Create & translate; негативные GET (6 кейсов); бонусная проверка mid-translate skip (5 промежуточных снимков); cleanup через UI; консоль-чек после каждого крупного шага.

**Didn't run:**
- Глубокая проверка структуры .xlsx (стили, ширины, цвета Score) — спека прямо разрешает: «структура не проверяется глубоко — не менялась»; проверено открытие, sheet, header, meta и соответствие ¶2 текущей ревизии.
- Mid-translate export ЧЕРЕЗ UI-меню — окно гонки ~1 сек/¶ физически не ловится кликами; выполнено прямым GET того же эндпоинта из сессии браузера (тот же интерфейс экспорта, UI-скачивание этого же эндпоинта доказано 6 раз). Первая попытка (док 20, 2 ¶) окно пропустила — перевод завершился быстрее экспорта; повторено на 8 ¶ (док 21) с парным опросом status+export.
- Export на самом golden-доке 10 скачиванием — только header-check GET (read-only), чтобы не плодить лишние скачивания; контент-проверки выполнены на собственных доках.
- zh→ru пара (t2-ru-translation) — принадлежит T2, для (з) достаточно zh→en.

## LLM-операции (бюджет)

Логические операции, инициированные прогоном: precompute дока 18 — 8 ¶ (чекбокс «~$0.10»); авто-извлечение терминологии доков 18 и 19 (live pipeline); refine ×1 + авто re-evaluate ×1; AI-translate: 2 ¶ (док 20) + 8 ¶ (док 21). Итого **≈ 21 операция** (flash-lite-класс, в пределах общего капа $5). Док 19 создан с precompute OFF, док 20/21 — translate-режим (precompute принудительно off по контракту).

## Скриншоты

16 шт. в `docs/reports/e2e/shots/campaign/t6/` (01–16, перечислены в таблице шагов); ключевые (04 warming, 08 revision history) дополнительно верифицированы визуально.
