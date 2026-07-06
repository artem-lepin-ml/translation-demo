# docs-keeper — итоговая doc-parity сверка, wave-5 (шаг 8)

Ветка: `claude/emlp-2026-website-fixes-muih1x`. Диапазон: `origin/dev-demo...HEAD` (106 файлов, 8 коммитов). Коммиты не делались (по заданию).

## Scope

Полная сверка L1→L4 по всему wave-5 diff: контракт-SSOT (`2026-06-30-demo-contracts.md`) против фактических wire-форм в `app.py` для всех новых/изменённых роутов (translator-config, translate, revisions, restore, export, health limits, models.effectiveParams, documents.translate + translation-блок); модуль/REST-таблицы `webapp.md` на предмет `translate.py`/`migrate.py`/`export.py`; компонентная таблица `webapp-ui-design.md` на предмет `va-gl-*`, `va-progress-*`, `PromptEditor`, Translator-карточки, history-блока, export-меню, `UploadIcon`; L1-индекс и `pipeline.md`; SUPERSEDED-баннер §admin в `2026-07-02-settings-rework.md`; отсутствие живых упоминаний graphify/Cultural Adaptation; актуальность README quickstart (15 vs 16 абзацев).

## Files changed

- `README.md` — 16→15 seed-абзацев; 5→4 evaluator criteria.
- `docs/README.md` — L1-строка контракта: Rev-4→Rev-5.
- `docs/goals/demo-positioning.md` — 5→4 критерия, убрано "cultural adaptation" как активный.
- `docs/testing/e2e-data.md` — 3 правки: "5 seeded criteria"→4 (дважды), таблица evaluators 5→4 (убран `cultural`, добавлена пометка "dropped wave-4 Б4"), сценарий 6 "5 evaluators"→4.
- `docs/subsystems/webapp.md` — `seed.py`: "five criteria"→"four criteria (Cultural Adaptation dropped wave-4)"; `GlossaryTab.tsx` описание переписано под фактический wave-5 редизайн (группировка, 7 колонок, степпер, кандидаты, judge-карточка, mentions) + добавлена отдельная строка для нового файла `glossary-grouping.ts` (не была в таблице вообще).
- `docs/subsystems/webapp-ui-design.md` — добавлена строка `va-gl-*` в таблицу компонентных классов (весь namespace редизайна глоссария был не задокументирован).
- `docs/superpowers/specs/2026-06-30-demo-contracts.md` — новый абзац в §7.2: `Term.traceJson` спек'нут (S2 §4), но не реализован — контракт и код молчаливо согласны в отсутствии поля, но расходятся с фронтом.
- `docs/known_issues.md` — новая запись CRITICAL: `Term.traceJson` никогда не уходит на wire, степпер путей граундинга никогда не рендерится (см. ниже).

## Decisions & rationale

**Проверено построчно и совпадает 1:1 (код↔контракт), правок не потребовалось:**
- `GET/PUT /api/translator-config` ↔ `_translator_config_dict`, `TranslatorConfigBody` (app.py:1113-1147)
- `POST /api/documents/{doc_id}/translate` ↔ `translate_document` (202, 403 seed_document, 409 in-progress/no_api_key/budget_exhausted) (app.py:833-862)
- `GET /api/paragraphs/{pid}/revisions` ↔ `list_revisions` (app.py:790-808)
- `POST /api/paragraphs/{pid}/restore` ↔ `restore_paragraph` (404/409) (app.py:815-828)
- `GET /api/documents/{doc_id}/export` ↔ `export_document` + `export.py` (xlsx/md content-type, 404, 422) (app.py:867-885)
- `GET /api/health` ↔ `health()`, `MAX_PARAGRAPHS=40`, `MAX_PARA_CHARS=4000` (app.py:255-258,64-65)
- `GET /api/models` `effectiveParams` ↔ `_model_public` (app.py:132-138)
- `POST /api/documents {translate}` ↔ `create_document`'s `translate`-ветка, forced `precompute:false`, `mixed_targets` 422 (app.py:281-359)
- Document DTO `translation`-блок, `precompute`/`translation.errorReason` camelCase ↔ `_status_public`, `_doc_dict` (app.py:221-241)
- `PUT /api/models/{name}` apiKey presence-check ↔ код (app.py:1057-1062)
- Params whitelist (§7.4) ↔ `_validate_params_whitelist` — все ключи/диапазоны совпадают буква в букву (app.py:976-1014)
- DDL `target_revision`/`translator_config`/`score.revision_id` ↔ `db.py::SCHEMA` — идентично
- `migrate.py` ↔ описание в контракте и `webapp.md` — идентично

**Найдено и исправлено (в зоне диффа):**
1. `GlossaryTab.tsx` в `webapp.md` описывал ДОРЕДИЗАЙНОВУЮ версию (плоская таблица) — реальный код это сгруппированный глоссарий с раскрываемым путём заземления (452 новых строк в диффе). Исправлено; добавлена строка для `glossary-grouping.ts` (409 новых строк, вообще не упоминался).
2. `va-gl-*` — целый CSS-namespace редизайна глоссария (список классов в самом `variant-a.css` под заголовком "wave-5: glossary redesign") отсутствовал в `webapp-ui-design.md` целиком. Добавлена строка.
3. Контракт-SSOT числился "Rev-4" в L1-индексе, хотя содержит §7 "Rev-5 delta" и статус-блок внизу файла явно говорит "Ревизия 5". Поправлено.

**Найдено и исправлено (вне явно перечисленных 7 пунктов, но подпадает под п.6 задания "no doc still claims Cultural Adaptation is active" — фактически обнаружилось 4 места, не 0):**
`seed.py` сеет 4 критерия (Cultural Adaptation убран в wave-4 Б4), но живые документы `README.md`, `docs/goals/demo-positioning.md`, `docs/testing/e2e-data.md` (3 места) и `docs/subsystems/webapp.md` всё ещё говорили "5"/"cultural". Один из этих случаев (`webapp.md:32` "five criteria") ранее уже был найден другим агентом (`docs/reports/pocock-skills-install.md:134`) и **сознательно оставлен как "вне скоупа"** в CONTEXT.md. Поскольку в этом задании владелец явно перечислил проверку Cultural Adaptation пунктом 6, я исправил все найденные вхождения — это расширяет предыдущее решение "не трогать", но соответствует прямой инструкции текущего задания.

**НЕ исправлено намеренно (вне зоны docs-keeper):**
- `docs/reports/e2e/wave5-run.md` (артефакт e2e-прогона) и `docs/reports/html/2026-07-06-wave5.html` (финальный HTML-отчёт) содержат неверный диагноз/оверклейм по степперу граундинга (см. критическую находку ниже) — это чужие артефакты (e2e-tester/report-generator), docs-keeper их не редактирует; отражено вместо этого записью в `known_issues.md` + контракт-споте.
- Историчные споки (`docs/superpowers/specs/2026-07-05-*.md`) и точечные отчёты не трогались — по конвенции доки-снапшоты решений не обновляются задним числом, кроме явно требуемого SUPERSEDED-баннера (см. ниже).

## КРИТИЧЕСКАЯ находка (код-баг, не доко-дрифт, но подробно задокументирована)

`app.py::_term_dict` никогда не отдаёт `traceJson` на wire, хотя спека [2026-07-05-glossary-redesign-impl.md §4](../superpowers/specs/2026-07-05-glossary-redesign-impl.md) явно требовала добавить `"traceJson": json.loads(r["trace_json"] or "{}")` "в том же коммите". `grep trace src/palimpsest/webapp/app.py` — 0 совпадений. Фронт (`GlossaryTab.tsx`) читает `term.traceJson` для степпера пути граундинга (QUERY→SEARCH→LABEL MATCH→DECISION) — из-за отсутствия поля степпер **никогда не рендерится ни для одного терма**, включая термы с реальными непустыми трассами в БД (проверил: "Месопотамия" в `data/seed/seed_paragraphs.jsonl` несёт полную трассу `resolved_by:'exact_label'` от `scripts/enrich_seed_terms.py`). Отчёт `wave5-run.md` (§ строка про `18-mockup-reference.png`) объясняет отсутствие степпера как "осознанную деградацию при пустом `trace_json`" — это неверный диагноз для загруженных термов; причина не в данных, а в отсутствующем поле контракта. Степпер описан в спеке как "ключевой экран для видео EMLP" — он не рендерился ни в одном протестированном билде. Фикс тривиален (одна строка в `_term_dict` + одна строка в контракте), но это код, не докс — задокументировал в `known_issues.md` и добавил перекрёстную ссылку в контракт-споте; в код не лез.

## Out-of-zone drift (найдено, НЕ правил — вне диффа, требует отдельного согласия владельца)

- `docs/subsystems/webapp.md` строка про `document.origin` в `DocumentSummary` — поле `origin` реально отдаётся API (`_doc_summary`), но отсутствует в §1 `DocumentSummary` контракта. Не новое в этом wave (не тронуто в диффе) — не правил.
- `docs/reports/pocock-skills-install.md` — историчный отчёт с устаревшей пометкой "вне скоупа" по Cultural Adaptation; теперь фактически устранено в живых доках, сам отчёт не трогал (точка-в-времени артефакт).

## Open questions (для владельца)

1. Стоит ли поручить `frontend-developer`/`backend-developer` тривиальный фикс `traceJson` отдельным коммитом (одна строка в `app.py` + одна в контракте) — я задокументировал, но не чинил код.
2. README "What the demo does" не упоминает три новых пользовательских фичи wave-5 (AI-перевод, история ревизий/best, экспорт xlsx/md) — сознательно не трогал (задание просило только проверить точность quickstart/paragraph-count, не полный апдейт фичалиста); можно добавить отдельной задачей.

## NOT done (явно)

- Код не редактировался (по заданию — только докс).
- Коммит не создавался (по заданию).
- `docs/reports/e2e/wave5-run.md` и `docs/reports/html/2026-07-06-wave5.html` не правились (не в мандате docs-keeper).
- Полный ре-скан всех specs/plans на предмет остальных возможных дрифтов вне явно перечисленных 7 пунктов не проводился (кроме Cultural Adaptation, который был явно затребован).
