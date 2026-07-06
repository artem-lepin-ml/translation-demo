# docs-keeper — повторная doc-parity сверка, wave-5 (второй проход)

Ветка: `claude/emlp-2026-website-fixes-muih1x`. Диапазон: коммиты wave-5 (от `12f8ce1`/`7b2f835` до `b862e3a`, HEAD). Это ВТОРОЙ независимый аудит той же волны — первый прошёл в коммите `7f3b56a` (см. [docs-keeper-wave5-doc-parity.md](docs-keeper-wave5-doc-parity.md)). Коммит не делался (задание — аудит + докс).

## Scope

Задание владельца — 4 пункта:
1. SSOT-контракт (`2026-06-30-demo-contracts.md`) против реального кода: новые роуты (`/api/translator-config`, `/api/documents/{id}/translate`, `/api/paragraphs/{pid}/revisions`+`/restore`, `/api/documents/{id}/export`), новые таблицы (`translator_config`, `target_revision`), `score.revision_id`, `Term.traceJson`.
2. `webapp.md` и `docs/stages/*` — переводчик, история ревизий, экспорт, редизайн глоссария.
3. Согласованность `CLAUDE.md`/`docs/README.md` — dangling links, устаревшие ссылки (в т.ч. проверка `Makefile serve` → `scripts/04_serve_webapp.py`).
4. `known_issues.md` — лимитация live-LLM в песочнице.

Метод: построчное чтение `app.py`/`db.py`/`migrate.py`/`translate.py`/`export.py` и сверка с текстом SSOT; `git log -S`/`git blame` для разделения "в зоне wave-5" vs "унаследовано из initial import"; скрипт-чекер markdown-ссылок по изменённым докам.

## Files changed

- `docs/superpowers/specs/2026-06-30-demo-contracts.md`:
  - §1: добавлено поле `traceJson: Record<string, unknown>` в интерфейс `Term` — реально отдаётся с backend, но в контракте отсутствовало.
  - §7.2: переписан абзац "Not implemented despite being spec'd — `Term.traceJson`" → он был **фактически неверен** (см. находку №1 ниже); заменён на корректирующую запись с объяснением, откуда взялась ошибка.
  - §7.2: добавлен абзац о `document.origin` — поле реально на wire, использовано самой же rev-5-дельтой (`origin==='upload'`), но никогда не было в §1/§4 базового контракта (унаследованный пробел, не бэкфиллил целиком — только зафиксировал).
- `docs/known_issues.md` — удалена запись "CRITICAL — `Term.traceJson` is never sent to the frontend" (баг фактически уже исправлен в том же коммите, где эта запись была добавлена; см. находку №1).
- `docs/subsystems/webapp.md` — строка про `GlossaryTab.tsx`/степпер путей граундинга: убрана ссылка на теперь-удалённую критическую запись `known_issues.md`, текст скорректирован под факт "поле есть, деградация — только когда `trace_json='{}'`".
- `docs/README.md` — L1-индекс: добавлены 6 wave-5-спек (`translator`, `score-history-best`, `export-xlsx`, `settings-fixes`, `glossary-redesign-impl`, `upload-modal-polish`) и финальный HTML-отчёт `2026-07-06-wave5.html` — были в дереве, но не в индексе.
- `docs/testing/e2e-data.md` — новый раздел "Journey: AI-translate / revision history / export" — три новых пользовательских сценария wave-5 (AI-перевод, restore из истории, экспорт xlsx/md) реализованы, спек'нуты и даже прогнаны e2e-тестером (`wave5-run.md`), но ни разу не попали в канонический e2e-манифест, из которого по конвенции CLAUDE.md обязан работать `e2e-tester`. Включает ссылку на уже найденный e2e-тестером реальный баг (History не обновляется сразу после Restore).

## Decisions & rationale

### Находка №1 (главная) — контракт и known_issues лгали про уже исправленный баг

Коммит `7f3b56a` ("fix(webapp): emit traceJson in term DTO + final doc-parity pass") одновременно:
- добавил код-фикс: `app.py::_term_dict` теперь отдаёт `"traceJson": json.loads(r["trace_json"]) if r["trace_json"] else {}` (строка 114) + регрессионный тест `tests/test_term_dict.py::test_trace_json_serialized_as_parsed_object` (подтверждено чтением файла — тест реально проверяет непустой `traceJson`);
- но **в том же коммите** записал в `known_issues.md` (CRITICAL) и в контракт (§7.2) текст "это никогда не было сделано" — как будто фикс не применён.

Это классический докс-код рассинхрон внутри одного коммита: предыдущий проход docs-keeper зафиксировал находку до того, как код был исправлен параллельно (или наоборот — порядок операций внутри коммита не совпал с порядком записи текста), и никто не вернулся откорректировать сам текст находки. Три следующих коммита (`461a93a`, `a1146a2`, `b862e3a`) не трогали ни `known_issues.md`, ни этот раздел контракта — рассинхрон дожил до HEAD.

Проверено:
- `grep -n "traceJson" src/palimpsest/webapp/app.py` → строка 114, реально в `_term_dict`.
- `SELECT * FROM term` (app.py:203,1334) — `trace_json` попадает в `sqlite3.Row`, парсится.
- `tests/test_term_dict.py:51-75` — `test_trace_json_serialized_as_parsed_object` явно проверяет `{"decision": {"resolved_by": "exact_label"}}`.
- Фронт (`GlossaryTab.tsx`, `glossary-grouping.ts`) уже читает `term.traceJson` — код готов был принимать поле ещё до фикса backend (задел на будущее), сейчас конец-в-конец рабочий.

Исправлено в докс (см. выше). **Не правил** сам код/тесты — фикс уже стоит, только доки лгали о его отсутствии.

Остаточный, честно не устранённый пробел (отметил, не чинил): `frontend/src/demo/api-client.ts`'s собственный интерфейс `Term` (строки 24-41) **не объявляет** `traceJson` — поле используется только через доп. тип `TermWithTrace` (`glossary-grouping.ts`). Комментарии в `glossary-grouping.ts` (строки 10-14, 41-44) всё ещё написаны в будущем времени ("forward-looking", "once the backend lane adds traceJson") — это устаревшие комментарии в TS-коде, не в докс-файле; docs-keeper код не редактирует, флагирую для следующего, кто коснётся этого файла.

### Находка №2 — `document.origin` не в SSOT, хотя rev-5-дельта на него опирается

`document.origin: 'seed'|'upload'` реально отдаётся (`app.py` строки 219, 240, 371, 414, 840), задокументирован в `webapp.md` строка 45, используется фронтом (`api-client.ts` строка 135, `DocumentSummary.origin`). Но контракт §1 (`DocumentSummary`/`Document`) и §4 (DDL `document`) никогда его не содержали — поле в БД с самого initial-импорта (`2493ec4`), т.е. это унаследованный, вне-wave-5 пробел. Однако сама rev-5-дельта (§7.2, "origin==='upload'") **опирается** на это неопределённое поле, не давая ему определения — усугубляет пробел новой зависимостью. Добавил однострочную честную сноску в §7.2 (не бэкфиллил весь §1/§4 — это отдельная, более широкая задача вне периметра wave-5).

### Находка №3 — новые пользовательские фичи wave-5 не попали в e2e-манифест

`docs/testing/e2e-data.md` правился в wave-5 (коммит `7f3b56a`, только цифра критериев 5→4), но три новых пользовательских журни — AI-перевод, restore из истории ревизий, экспорт xlsx/md — не были добавлены как канонические сценарии, хотя CLAUDE.md прямо требует, что `e2e-tester` (шаги 6/8) работает **только** по данным из этого манифеста и обязан покрыть "ALL scenarios described in the PR". По факту e2e-тестер эти сценарии всё равно прогнал (см. `docs/reports/e2e/wave5-run.md` — Restore, экспорт xlsx/md, AI-translate CTA, все с скриншотами) и даже нашёл реальный баг (History не обновляется сразу после Restore, §4.1 там же) — но сделал это без опоры на манифест, а "по наитию" из спек. Добавил раздел с этими тремя журни в манифест, включая честную ссылку на уже найденный баг restore-history.

### Проверено построчно и совпадает 1:1 (без правок)

- `GET/PUT /api/translator-config` ↔ `_translator_config_dict`/`TranslatorConfigBody` (app.py:1127-1148).
- `POST /api/documents/{doc_id}/translate` ↔ `translate_document` (202; 403 `seed_document`; 409 `translation_in_progress`/`no_api_key`/`budget_exhausted`) (app.py:834-863).
- `GET /api/paragraphs/{pid}/revisions` ↔ `list_revisions` (app.py:791-809) — форма ответа `{revisions:[{id,origin,createdAt,text,aggregate,isBest,isCurrent}]}` совпадает с контрактом буква в букву.
- `POST /api/paragraphs/{pid}/restore` ↔ `restore_paragraph` (404 неизвестная ревизия, 409 чужой абзац) (app.py:816-829).
- `GET /api/documents/{doc_id}/export` ↔ `export_document`+`export.py` (422 неизвестный формат, 404, content-type xlsx/md) (app.py:868-886).
- DDL `target_revision`/`translator_config`, `score.revision_id` ↔ `db.py::SCHEMA` (строки 40-45, 71-84) — идентично контракту §7.1.
- `migrate.py` (`_create_target_revision`, `_create_translator_config`, `_add_score_revision_column`, `_backfill_paragraph_revisions`) ↔ описание в контракте §7.1 — идентично, включая FK-guard "только если модель уже существует".
- `webapp.md` — переводчик/история/экспорт/глоссарий-редизайн уже полноценно описаны отдельными разделами ("Translate", "Revision history & best", "Export", таблица компонентов с `GlossaryTab.tsx`/`glossary-grouping.ts`) — предыдущий проход это уже закрыл, здесь только сверил и не нашёл расхождений.
- `README.md`/`docs/goals/demo-positioning.md` — 15 абзацев / 4 критерия, актуально (тоже закрыто предыдущим проходом).

### Пункт 3 задания — Makefile / routing / dangling links

- **Подтверждено, вне зоны**: `Makefile` target `serve` (`uv run python scripts/04_serve_webapp.py`) — файл `scripts/04_serve_webapp.py` не существует (`scripts/` не содержит такого файла). `git log --follow` показывает, что `Makefile` не менялся с самого `2493ec4` (initial import) — это дефект унаследован, не появился в wave-5. Реальный способ запуска (`uvicorn palimpsest.webapp.app:app`) уже задокументирован в `webapp.md` "Run instructions" — `make serve` просто мёртв. **Не правил** (вне диффа wave-5, требует отдельного решения владельца: удалить target или починить путь).
- `CLAUDE.md` routing table — все 14 ссылок резолвятся на существующие файлы, включая новые L4/спеки. Без нареканий.
- `docs/README.md`/`known_issues.md` — 5 dangling-ссылок на HTML/MD отчёты (`2026-07-02-ner-model-tournament.html`, `2026-07-01-terminology-consolidation.html`, `2026-07-01-terminology.html`, `2026-07-02-suggestion-guard-audit.md`), которые никогда не существовали ни в одном коммите ни одной ветки (`git log --all --diff-filter=A` — пусто). Унаследовано из initial import, не тронуто в wave-5. **Не правил.**

### Пункт 4 задания — live-LLM sandbox limitation в known_issues.md

Подтверждено — присутствует и актуально: `known_issues.md` строка 52-53, "Live LLM path not exercised end-to-end" — `OPENROUTER_API_KEY` отсутствует в демо-окружении по дизайну, `/evaluate` всегда идёт по cache-fallback ветке, живой судья покрыт только юнит-тестами с фейковым клиентом. Формулировка точная и не устарела.

## Out-of-zone drift (найдено, НЕ правил)

1. `Makefile:22-23` — `serve` target зовёт несуществующий `scripts/04_serve_webapp.py` (initial import, не wave-5).
2. `docs/README.md` + `known_issues.md` — 5 ссылок на никогда не существовавшие HTML/MD-отчёты (initial import).
3. `docs/testing/e2e-data.md:58` — "column headers `Original (German)` / `Translation (French)`" нарушает Hard Invariant 11 (naming: "Source"/"Translation", никогда "Original") — но добавлено ещё в initial import и ни разу не редактировалось с тех пор; реальная UI-таблица (`VariantA.tsx`, задокументировано в `webapp.md` строка 59) давно использует `Source · <Language>`/`Translation · <Language>`. Не в диффе wave-5 — не правил, флагирую отдельно.
4. `docs/stages/wiki-eval.md` существует и упомянут в `CLAUDE.md` routing, но отсутствует в `docs/README.md` L1-индексе — появился в коммите `dcd4e0b`, задолго до wave-5. Не правил.

## Open questions (для владельца)

1. `document.origin` — стоит ли поручить полноценный бэкфилл §1/§4 контракта отдельной задачей (не только rev-5-сноска, которую я добавил)? Поле старое, но контракт как SSOT должен его формально объявлять.
2. `Makefile serve` — удалить target или починить путь на `uvicorn palimpsest.webapp.app:app`? Решение вне мандата docs-keeper (правка Makefile — это код/тулинг, не докс).
3. 5 dangling-ссылок на несуществующие HTML-отчёты — это унаследованный technical debt на 4 дня старше wave-4; убрать ссылки или сгенерировать отчёты?
4. Restore-history refresh bug (`wave5-run.md §4.1`) — уже задокументирован e2e-тестером как найденный баг, но не заведён явно в `known_issues.md` как открытый пункт (сейчас есть только в отчёте прогона и в новом абзаце e2e-манифеста, который я добавил). Стоит ли поднять его в `known_issues.md` как отдельный Open-пункт?

## NOT done (явно)

- Код (`app.py`, `api-client.ts`, `glossary-grouping.ts`, `Makefile`) не редактировался — только докс, как и предписано роли docs-keeper.
- Коммит не создавался.
- Полный бэкфилл `document.origin` в §1/§4 контракта — сделал только точечную сноску в rev-5-разделе, не переписывал базовые интерфейсы/DDL (см. Open Q1).
- `Makefile`, `docs/README.md`/`known_issues.md`'s 5 dangling-ссылок, `e2e-data.md`'s "Original (German)" — все три зафиксированы как out-of-zone, не правились (требуют отдельного согласия владельца на более широкую уборку вне wave-5-диффа).
- `known_issues.md` Restore-history refresh bug — не заведён отдельным Open-пунктом (только упомянут в новом e2e-журни); решение оставлено владельцу (Open Q4).
- Исторические отчёты (`wave5-run.md`, `html/2026-07-06-wave5.html`, `docs-keeper-wave5-doc-parity.md`), которые тоже содержат теперь-устаревший диагноз про `traceJson`, не переписывались — это снимки состояния на момент прогона, конвенция их не корректирует задним числом.
