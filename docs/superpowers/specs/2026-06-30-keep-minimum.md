# Минимум, который оставить — манифест зачистки Palimpsest

Up-link: [docs/pipeline.md](../../pipeline.md) · основания: [teardown-аудит](../../reports/2026-06-emnlp-research-teardown-audit.html), параллельный аудит 3 worktree (11 агентов, 2026-06-30) · сопутствующий: [анализ референсных демо](../../experiments/2026-06-30-reference-demos-analysis.md)

> Статус: **предложение на ревью**. Ничего ещё не удалено и не перемещено. Это карта «что оставляем как чистые компоненты с интерфейсами + доками / что убираем (в архив или delete)».

## Главное

Проект размазан по трём worktree, и «мёртвый код» нельзя оценить на глаз — нужен граф достижимости. Аудит дал чёткий ответ: **держим утверждённый TipTap-UI (DesignApp) + 4 проверенных «семени» из старого дерева** (LLMClient, ядро судьи, рантайм глоссария, io-контракт) **+ артефакт `main.json` и реестр моделей**. Всё остальное (старый pipeline, вендоренный фронт viewer ~98k строк, build-пайплайн глоссария, R&D, планы) — **в архив или delete, ~127k строк суммарно**. Три worktree сводим в один проект.

Ключевое открытие, которого не было в teardown: **«fresh backend» — не чистое поле**. В worktree `demo-skeleton` уже лежит закоммиченный **873-LOC Python-каркас** (FastAPI `app.py`, `evaluation/judge.py` с `LLMJudge`, `glossary.py`-stub, 48-LOC LLM-заглушка). Перенос семян — это **замена тонких заглушек каркаса** проверенным кодом, а не стройка с нуля. Это сильно снижает и объём работы, и риск.

## Рекомендация: Вариант A (с дисциплинированной последовательностью)

Решение сводится к одному выбору — насколько агрессивно резать:

- **Вариант A — агрессивный (рекомендую).** Снести старый pipeline, оставить только fresh-backend seed + новое демо, свести три worktree в один проект. Убирает ~127k строк. Риск: средний — теряется работающий deployed viewer для Андрея/MGIMO до готовности нового backend; семена надо реально портировать с тестами, а не просто скопировать.
- **Вариант B — консервативный.** Оставить работающий pipeline + deployed viewer, срезать только бесспорно мёртвое (вендоренный фронт, orphan-скрипты, R&D). Убирает ~120k строк (почти тот же мёртвый вес). Риск немедленный низкий, но **долговой высокий**: остаются две конкурирующие истины (старый pipeline-продукт vs демо), что нарушает single-source-of-truth и путает агентов ребилда. Консолидации не происходит.

**Почему A.** Цель — ОДИН связный минимальный документированный проект. B этого не достигает: он лишь подметает мёртвый вес и оставляет старый pipeline как параллельную истину. Главный риск A (простой для стейкхолдеров) снимается последовательностью ниже + хранением запускаемого viewer в `_legacy/` на переходный период.

### Последовательность, гасящая риски A
1. **Заинлайнить** `_is_picture_or_dinkus` в `matcher.py` — разрывает кросс-worktree приватный импорт `from ..translate import …` до любого архива `translate.py` (иначе снос translate тихо сломает глоссарий).
2. **Свести три worktree** в один (рекомендация — `feat/demo-skeleton`, там уже backend-каркас + UI; см. открытый вопрос про ветку). Закоммитить `web-prototype` (сейчас не закоммичен).
3. **Портировать 4 семени** поверх заглушек каркаса, **с тестами** (не просто copy).
4. **Только ПОСЛЕ** зелёного нового backend гасить deployed viewer; viewer 4-pack держать в `_legacy/` запускаемым как страховку.

---

## KEEP — минимум как чистые компоненты (9)

| Компонент | Пути | iface / doc сейчас | Целевой интерфейс | Зачем |
|---|---|---|---|---|
| **TipTap UI** (продукт) | `web-prototype/src/{main,Router}.tsx`, `design/DesignApp.tsx`, `design/design.css`, `tiptap-review-extension.ts`, `data.ts`, `index.css` | partial / none | `Router(Variant)`; `ReviewExtension` с `ReviewStorage{activeTab, activeSuggestionIds}`, данные приходят из API (а не из `data.ts`); типы `EvaluatorTab/TermHighlight/Suggestion` → `api-contract.ts` (DTO) | Целевой продукт демо. `ReviewExtension` — ключевой контракт React-state ↔ ProseMirror-декорации. Код **не закоммичен** — коммит первым шагом. |
| **LLMClient** | `src/palimpsest/llm/client.py` (387) | clean / partial | `async LLMClient(config, max_concurrency=0).complete(system, user, *, thinking, tool_schema, **overrides) -> LLMResult(content, usage)`; `LLMConfig.from_model_config()`; экспорт через `llm/__init__.py` | Эмпирически закалённая логика (dual-SDK, retry, cache_control, forced-tool, Opus-unwrap). Заглушка каркаса (48 LOC, sync, без Anthropic/retry) несовместима — полная замена. Инвариант #6. |
| **Judge core** | из `scoring.py` (~80 из 811): `score_paragraph`, `parse_judge_response`, `_JUDGE_TOOL_SCHEMA`; из `correction.py`: `_build_edit_message` | partial / partial | `evaluate_paragraph(client, source, translated, prompts) -> list[SpanCard]`; `parse_judge_response(raw)`; `build_edit_prompt(judge_result)` | Ложится прямо на каркасный `LLMJudge.judge()` (сейчас читает несуществующий `judge.md`, парсит наивным `json.loads`). Остальные ~730 LOC scoring.py (JSONL/resume/агрегация) — мёртвый batch. |
| **Scoring prompts v2** + correction/translate | `prompts/03_scoring/v2/{accuracy,cultural,fluency,style,terminology}.md`, `prompts/04_correction/system.md`, `prompts/02_translate/{system,user}.md` | partial / partial | `load_prompts(root, variant='v2') -> dict[stem,text]`; вывод JSON `{final_score, summary, identified_issues:[{source_fragment, problematic_fragment, explanation, suggestion}]}` | Пять критериев = оценщики по умолчанию мульти-судейской панели; `identified_issues[]` = готовая схема карточек Accept/Dismiss. v2 = обязательное обоснование (score<7 → 2+ issue) + калибровка MGIMO. |
| **Glossary runtime core** | `glossary-overnight: src/palimpsest/glossary/{schema,matcher}.py` + `resources/` (383) | clean / documented | `Glossary.load(path)`; `Matcher(glossary).find(paragraph_id, ru_text) -> list[Match(surface, char_span, entry_id, ambiguous)]`; runtime-only `__init__` | Единственная часть глоссария, нужная демо как backing store для `/api/glossary/match` и подсветки KG-терминов. **Блокер:** приватный импорт из `translate.py` → заинлайнить (2 строки) до порта. |
| **Glossary artifact** (данные) | `glossary-overnight: glossary/main.json` (869 записей) | clean / documented | `glossary/main.json` в корне; схема `{entry_id: GlossaryEntry}`; путь конфигурируем | Единственный источник истины (Инвариант #8), продукт всего offline build. Это **данные, не код** — переезжают без изменений. |
| **io-контракт** | `references/interfaces_agreement.md` | clean / documented | Переписать как API/DB-схему нового backend (FastAPI-эндпоинты + таблицы); сохранить sentinel-конвенции (null vs −1) и usage-блок; добавить `version` | Назван teardown как seed контракта; обкатанная в пилоте JSONL-схема → выводим новую API/DB-схему. |
| **Provider registry** | `configs/models.yaml` (309) + `ModelConfig` | partial / partial | `load_evaluator_registry() -> dict[str, ModelConfig]` | **Расхождение с teardown:** 309 строк кодируют proxy-специфику маршрутизации (effort-алиасы, structured-output, Anthropic SDK), не выводимую ни из какой схемы. **port-seed, не delete.** |
| **CLAUDE.md + провайдерные справочники + teardown-аудит** | `CLAUDE.md`, `references/` (provider-доки), `docs/reports/2026-06-emnlp-research-teardown-audit.html` | partial / documented | — | Рабочие инварианты проекта + источник архитектурных решений ребилда. |

---

## REMOVE — что убираем (11 групп, ~127k строк)

Метод по умолчанию — **archive** (восстановимо: `_legacy/` или legacy git-тег); **delete** — только для бесспорно бесполезного.

| Группа | Метод | ~LOC | Почему (кратко) |
|---|---|---|---|
| Старый pipeline core (`translate` batch-IO, `chunking`, scoring fan-out, `scoring_subsets`) | ARCHIVE | 552 | После извлечения семян остаётся batch-машинерия без потребителя в реальном времени. `chunking.py` мёртв для пивота. Архив — чтобы можно было вернуть batch-режим переоценки. |
| `factcheck` subpackage + промпты (extract+overlap) | ARCHIVE | 294 | Выключен по умолчанию (`enabled=False`). KG-слой покрывает корректность терминов. Двухстадийный extract+overlap + few-shot — семя будущего fact-grounding оценщика. LEGACY-баннер. |
| Glossary offline build-пайплайн (`parse`, `corrections`, `categorize`, `lookup`, `forms`) + build-промпты + audit-артефакты | ARCHIVE | 2002 | В демо глоссарий — статический `main.json`. **Не delete:** S3/S4 coverage=0 — артефакт outage прокси (known_issues §13), ре-ран со здоровым эндпоинтом достроит глоссарий; parser accuracy 33/100 (§14) чинится только при сохранённом коде. |
| Glossary R&D (`metrics`, `reports`, `postedit`) | **DELETE** | 1095 | Хардкоженный six-pair S1-S4 турнир, Jinja HTML-рендер (отчёты уже материализованы), regex-постэдит Stage-04 (вне scope — демо подсвечивает в TipTap, не мутирует текст на сервере). Ни одного пути из продукта. |
| viewer backend (4-pack) + unit-тесты | ARCHIVE | 990 | Единственное, что крутится в задеплоенном контейнере (но НЕ импортирует palimpsest). Несёт переиспользуемую логику (path-traversal guard, JSONL-join, issue-рендер, catalog) — семя нового FastAPI-слоя + страховка MGIMO. 4 unit-теста кодируют инварианты для переэкспрессии. |
| viewer frontend (вендоренный LLM-Comparator) + e2e-тесты + README | **DELETE** | 98480 | Снимок PAIR-code/llm-comparator (MobX+LitElement) — структурно несовместим с React+TipTap. Python-SDK `llm_comparator` — orphan (никогда не импортировался). JS-бандл + `example_arena.json` (84k) — мёртвый вес. Ноль референс-ценности. |
| Старые CLI-скрипты + shell-обёртки + deploy (rsync/docker/caddy) | **DELETE** | 1500 | Операторские CLI старого batch-pipeline + deploy старого viewer. Ценная логика — в семенах. `configs/translation.yaml` битый (ссылается на несуществующий `02_draft/system.md`). **Примечание:** `03_build_judge_reports.py` и `deploy_sync.sh` живые сейчас — удалять только после гашения deployed viewer. |
| Research-провенанс (probes, pilot extract, scoring configs, factcheck config/script) | ARCHIVE | 1190 | Одноразовые R&D-инструменты, чей вывод закоммичен. Ценность как paper trail / EMNLP-appendix. |
| Старые execution-планы (`superpowers/plans/*`) | **DELETE** | 9975 | ~10k строк чеклистов исполнения для уже отгруженного и сносимого кода. Ноль сигнала сверх спек/known_issues. |
| Старые стадийные доки + спеки + experiments/analysis + v1-промпты | ARCHIVE | 6000 | Описывают сносимый pipeline. **v1-промпты — АРХИВ, НЕ delete:** v1 — текущий деплойный дефолт (`prompts_variant='v1'` в 11/12 конфигов), удаление сломает работающий pipeline до перехода на v2. README/стадийные доки → LEGACY-баннер до новых компонентных доков. |
| Мёртвые черновики/бинарники `references` + gemma-промпты + smoke-фикстуры + старые pipeline-тесты | ARCHIVE | 3500 | gemma (модель вне scope) + дубли references — по сути delete, объединены в archive для безопасности; из `mgimo_reviews` извлечь критерии качества в новый scoring-док. Pipeline-coupled тесты — референс паттернов, инварианты переэкспрессируются. |

---

## Целевая карта компонентов (после консолидации)

Чистая архитектура минимума — каждый компонент = одна ответственность + объявленный интерфейс + дом для доки:

| Компонент | Ответственность | Интерфейс | Зависит от | Док |
|---|---|---|---|---|
| **tiptap-ui** | Утв. TipTap-фронт: пары, табы судей, карточки Accept/Dismiss, подсветка KG, drawer конфигурации | `DesignApp` (route `#/design`); `ReviewExtension` + DTO из API | backend-api | `docs/components/tiptap-ui.md` |
| **backend-api** | FastAPI-слой: абзацы, мульти-судейская оценка, glossary-match, применение правок | `create_app()`; `GET /api/chapters`, `POST /api/evaluate`, `GET /api/glossary/match`, `POST /api/apply-edit` | judge-core, glossary-runtime, llm-client, io-contract | `docs/components/backend-api.md` |
| **llm-client** | Единая точка доступа к LLM | `async LLMClient(config).complete(...) -> LLMResult` | provider-registry | `docs/components/llm-client.md` |
| **judge-core** | Оценка абзаца + edit-prompt для Accept | `evaluate_paragraph(...) -> list[SpanCard]`; `build_edit_prompt(...)` | llm-client, scoring-prompts | `docs/components/judge-core.md` |
| **scoring-prompts** | Промпты-критерии v2 + correction/translate | `load_prompts(root, variant='v2')` | — | `docs/components/scoring-prompts.md` |
| **glossary-runtime** | Рантайм-матчинг RU→EN по `main.json` | `Glossary.load(path)`; `Matcher(g).find(...) -> list[Match]` | glossary-data | `docs/components/glossary-runtime.md` |
| **glossary-data** | Статический артефакт терминологии (Инвариант #8) | `glossary/main.json` | — | `docs/components/glossary-runtime.md` |
| **provider-registry** | Реестр моделей/провайдеров + матрица маршрутизации | `load_evaluator_registry() -> dict[str, ModelConfig]` | — | `docs/components/provider-registry.md` |
| **io-contract** | Схема данных/API нового backend | API/DB-схема (выведена из `interfaces_agreement.md`) | — | `docs/components/io-contract.md` |

---

## Критические находки достижимости (грунтуют «мёртвость»)

- **Deployed viewer вообще не трогает `src/palimpsest`.** `uvicorn viewer.backend.main:app` импортирует только `viewer.backend.*` + fastapi + stdlib. То есть старый pipeline «мёртв» для СЕРВИСА, но жив по CLI для генерации данных.
- **`03_build_judge_reports.py` живой** (запускается `deploy_sync.sh` на каждый sync), но это **standalone stdlib-копия**, которая НЕ импортирует `scoring.build_judge_reports` — она переопределяет логику. В деплой вшита именно дублирующая копия, а не библиотечная функция.
- **Кросс-worktree связь:** `matcher.py` делает `from ..translate import _is_picture_or_dinkus` — приватный импорт из старого `translate.py`. Заинлайнить до архива translate (см. шаг 1 последовательности).
- **`03_judge_review_views.py` выглядит живым** (префикс 03_, рядом с деплойным), но **orphan** — ничто не вызывает. Легко ошибочно счесть живым по имени.
- **`viewer/frontend/python/.../llm_comparator/*`** — orphan в живом графе (Dockerfile собирает только JS-фронт; этот Python-trei не ставится и не импортируется).
- **Демо полностью развязано:** `demo-skeleton/web-prototype` — standalone TS/Vite, никакого Python и импортов `src/palimpsest`. Дублирование с viewer — только концептуальное.

## Расхождения с teardown-отчётом

1. «fresh backend» — НЕ чистое поле: уже есть 873-LOC каркас в `demo-skeleton`. Семена = замена заглушек, не стройка с нуля.
2. Старый pipeline «dead» — верно только для сервиса; жив по CLI.
3. scoring seed = `score_paragraph + parse_judge_response` (~80 LOC), а не «fan-out ~50 LOC».
4. v1-промпты: teardown → drop; реально → **archive** (v1 — текущий деплойный дефолт, 11/12 конфигов).
5. `models.yaml`: teardown → «вывести из контракта»; реально → **port-seed** (309 строк proxy-специфики, не выводимы).
6. `lookup/`: teardown → archive/delete; реально → **archive** (coverage=0 — outage прокси, не мёртвый код).
7. viewer e2e-тесты не сохраняемы как запускаемые после сноса фронта — переносятся только 4 unit-файла как контракты.

## Открытые вопросы — решения за владельцем

1. **RU→EN-only или произвольная пара языков?** glossary-runtime и `main.json` жёстко привязаны к русскому (морфология, scope-омонимы по главам). Если демо EMNLP показывает произвольную пару — KG-слой становится RU-специфичным частным случаем; зафиксировать в архитектуре.
2. **Судьба Plate-спайка** (`App.tsx` + `decorate-plugin.tsx`, 334 LOC, помечены delete): подтвердить delete + удаление `platejs` из `package.json` и `initialTranslationValue`/`'platejs'`-импорта из `data.ts`. Бесповоротно убирает Plate.
3. **Куда консолидировать три worktree?** Рекомендация — `feat/demo-skeleton` (там каркас + UI). Эта ветка как новый mainline, или свежая `feat/<topic>` off `main`?
4. **Переходный период deployed viewer:** гасить сразу или держать 4-pack в `_legacy/` запускаемым до покрытия нужд Андрея/MGIMO? Влияет на тайминг удаления deploy-скриптов.
5. **factcheck:** `demo-skeleton` уже имеет дивергентный single-prompt `pipeline/factcheck.py`, старое дерево — двухстадийный extract+overlap. Какой нести вперёд (и нужен ли вообще, если KG закрывает потребность)?
6. **Глубина io-контракта:** PostgreSQL (как намекает teardown) или файловое/JSONL для демо-масштаба? Влияет на объём переписывания.
7. **Метод архива:** `_legacy/` в репо (видно, но засоряет) или legacy git-тег + удаление из дерева (чисто, менее доступно)?

## Статус

Предложение от 2026-06-30 на основе параллельного аудита (11 агентов, 714k токенов). Ничего не удалено. Следующий шаг после ревью — превратить выбранный вариант в plan (`docs/superpowers/plans/`) и исполнить по последовательности.
