# G6 `label_first` — прозрачный Wikidata-граундинг, trace и ablation

Up-link: [docs/pipeline.md](../../pipeline.md) · заменяет grounding-часть [consolidation design](2026-07-01-terminology-consolidation-design.md) и [terminology e2e design](2026-07-01-terminology-e2e-design.md) (их grounding-секции — LEGACY с 2026-07-03). Пейринговые секции этих доков остаются в силе.

Статус: черновик на верификацию (/verify-spec) · Ветка: `feat/grounding-label-first` от `dev-demo` · Мокап UI: [2026-07-03-glossary-redesign-mockup.html](2026-07-03-glossary-redesign-mockup.html)

## 1. Цель и скоуп

**Цель.** Граундинг RU-терминов в Wikidata становится прозрачным, объяснимым и эффективным: одна стратегия с детерминированным ядром, LLM — только на честно неоднозначном подмножестве, полный trace каждого решения. Это фундамент для evaluation-блока (сравнение с разметкой Википедии, EMNLP industrial track) — методология должна описываться в 2–3 предложениях статьи.

**В скоупе:**
- Стратегия G6 `label_first` — единственная; G1/G3/G5/G2 удаляются (git — единственный архив).
- Конфиг-конструктор: три независимых тумблера (`use_lemma`, `use_fallbacks`, `match_aliases`) под ablation.
- `GroundingTrace v1` — schema-versioned trace в новой колонке `term.trace_json`; пишется с первого дня.
- Judge-дизамбигуация через модель из Settings (зеркало NerConfig), ответ `{qid, reason}`.
- Экстрактор отдаёт лемму: `{surface, lemma, category}`.
- Ablation-харнесс на golden-99: 8 конфигураций, две лестницы.
- Редизайн вкладки Glossary — **только дизайн** (формат данных + мокап); реализация UI — отдельный PR позже.
- Документация: stage-doc переписывается, supersession-note.

**Вне скоупа:** evaluation на ~1k страниц Википедии (следующий блок, отдельная спека); реализация Glossary-UI; любые изменения пейринга (P1/P3) и экстракторных метрик.

## 2. Журнал решений

Все решения согласованы с владельцем 2026-07-03.

| # | Решение |
|---|---|
| D1 | Единственная стратегия G6; G1 api_first, G3 llm_judge, G5 hybrid, G2 mgenre и notability-вердикт **удаляются полностью**. В docs — supersession-note «superseded 2026-07-03, см. git». Последние измеренные числа удаляемых стратегий (G3: QID acc 0.78 на golden-99) фиксируются как референс. |
| D2 | **difficulty = путь принятия решения**, не мнение LLM: 🟢 `exact_label` · 🟡 `llm_disambiguation` · 🔴 `no_candidates` / `judge_rejected`. |
| D3 | Тумблеры: `use_lemma`, `use_fallbacks`, `match_aliases`. Блоклист анахронизмов и тип-фильтр удаляются совсем — неоднозначность разрешает judge по description + контексту. |
| D4 | Лемму отдаёт NER-экстрактор (схема `{surface, lemma, category}`); статический `lemmas.json` больше не используется **пайплайном**. Исключение: `merge_goldens.py` (golden-tooling, не пайплайн) продолжает читать `lemmas.json` как вход мерджа — файл остаётся в `data/seed/` как артефакт golden-набора. |
| D5 | Judge настраивается в Settings по паттерну NerConfig: модель из registry + **редактируемый промпт** (Q3) + params; `temperature=0`. |
| D6 | Ничего не теряем: durable JSONL-кэш Wikidata (существующий), trace на каждый термин, полный лог judge-вызовов. Eval-прогоны не перезаписываются. |
| Q1 | Disambiguation-страницы **не фильтруем** — никаких рукотворных списков; judge игнорирует их по описанию. |
| Q2 | Формат trace проектируем сейчас (§5), UI-реализация позже. |
| Q4 | seed-refresh Phase C ждёт G6 и перегенерирует терминологию демки уже новой стратегией (один пересчёт вместо двух). |
| Q5 | Acceptance без жёсткого порога, но с обязательным сравнением G6(111) с референсом G3 = 0.78 QID acc; заметно хуже → разбор по trace до закрытия блока. |
| N1 | Judge возвращает `{qid, reason}` — одно предложение обоснования; хранится в trace, показывается в UI. |
| N2 | EN-контекст **не хранится** — вычисляется при рендере (предложение с `target_surface` в переводе абзаца). RU-контекст уже есть в `term.context`. |
| N3 | Строка глоссария = уникальная пара (лемма, QID) c «Mentions ×N»; per-occurrence строки таблицы `term` не меняются — группировка на уровне UI/API. |
| N4 | Сводка под заголовком Glossary: «resolved deterministically: N · via LLM: N · not grounded: N» — метрика статьи живьём в продукте. |

## 3. Алгоритм G6

### 3.1 Генерация кандидатов

Порядок запросов (для каждого — язык источника, лимит `search_limit=7`):

1. `wbsearchentities(lemma)` — если `use_lemma` и лемма отличается от surface;
2. `wbsearchentities(surface)`;
3. если суммарно 0 хитов и `use_fallbacks`: CirrusSearch full-text (`list=search`) по тем же запросам;
4. если всё ещё 0 и `use_fallbacks`: RU-Wikipedia заголовок → wikibase item.

Дедуп по QID, обогащение топ-`enrich_top=5` через `wbgetentities` (labels ru/en, descriptions ru/en, aliases ru/en, sitelinks), редиректы канонизируются по `entity["id"]`. **Никакой фильтрации кандидатов по типам** (D3, Q1).

`search_limit`/`enrich_top` — фиксированные константы, перенесённые из текущего `candidates.py`; они **не** являются осями ablation (оси — только три тумблера §3.3) и не варьируются нигде в этом блоке. Порядок кандидатов в trace стабилен при реплеях кэша: кэш хранит сырой ранжированный ответ API целиком, merge/dedup сохраняет insertion order — это документируемый инвариант (тест в §12), а не случайность реализации.

### 3.2 Таблица решений

| Исход точного label-матча | Действие | difficulty | `resolved_by` |
|---|---|---|---|
| Ровно 1 точный матч | берём QID детерминированно, LLM не вызываем | 🟢 | `exact_label` |
| ≥2 точных матча | judge: кандидаты (label + description) + предложение-контекст → QID | 🟡 | `llm_disambiguation` |
| 0 точных, но кандидаты есть | judge; выбрал → 🟡, отверг всё → 🔴 | 🟡/🔴 | `llm_disambiguation` / `judge_rejected` |
| 0 кандидатов после включённых фолбэков | красный без LLM | 🔴 | `no_candidates` |

Точный матч: `norm(query) == norm(label_ru)`, где `query` ∈ {lemma, surface}. `norm` = trim + collapse whitespace + casefold + **ё→е** + нормализация Unicode-дефисов (U+2010…U+2015, U+2212 → `-`). Мотивация: RU-labels в Wikidata непоследовательны по ё/е, а дефисы в транслитерированных именах («Кадашман-Харбе») приезжают разными кодпоинтами из OCR/переводов — без фолдинга честные зелёные падают в эскалацию. Риск обратной стороны (две разные сущности, различающиеся только ё/е) считаем пренебрежимым и принимаем осознанно (риск R7); юнит-тесты на оба фолдинга обязательны (§12). При `match_aliases` матч-множество расширяется алиасами ru и en. Кандидат хранит, **чем именно** совпал (`matched`: label или конкретный алиас, и по какой форме запроса) — это основа прозрачности в UI.

**Политика ошибок (полная):**

- **Wikidata недоступна** (клиент исчерпал ретраи, `RuntimeError`): G6 ловит исключение → difficulty 🔴, `resolved_by: wikidata_unavailable`, ошибка в trace. Это **не** `no_candidates`: eval исключает такие строки из всех метрик и репортит их отдельным счётчиком (иначе сетевой сбой маскируется под честный красный и портит accuracy); в демке термин показывается как not grounded.
- **Judge недоступен** (не настроен / транзиентная ошибка после ретраев) при необходимости эскалации → difficulty 🟡, `resolved_by: judge_unavailable`, `judge: {"error": ...}`, `chosen_qid = null`, grounded = null. Термин честно помечен «неразрешённая неоднозначность», а не молча взят топ-1.
- **Кривой JSON от judge** — терминальная ошибка, **не ретраится** (слепые ретраи жгут бюджет; паттерн `_judge_live` в webapp: ретраятся только транзиентные 429/5xx/timeout, максимум 2 с экспоненциальным бэкоффом) → `judge_unavailable`.
- **QID вне списка кандидатов** — нарушение контракта, **не** молчаливый фолбэк на топ-1 (анти-паттерн старого G3): → `judge_unavailable`, ошибка фиксируется в `trace.judge.error`.

Итоговый enum `resolved_by`: `exact_label · llm_disambiguation · judge_rejected · judge_unavailable · wikidata_unavailable · no_candidates`. Ветка difficulty 🟡 с `grounded = null` (judge_unavailable) — **расширение задокументированного null-правила** (`grounded: null` только при 🔴 в demo-contracts.md); контрактный док правится тем же коммитом (§7), фронтовые truthiness-проверки `term.grounded && …` проверяются на этот кейс.

### 3.3 Конфиг

```python
@dataclass(frozen=True)
class GroundingConfig:
    use_lemma: bool = True      # искать по номинативной лемме до surface
    use_fallbacks: bool = True  # CirrusSearch + RU-wiki title при нуле хитов
    match_aliases: bool = True  # точный матч по aliases, не только label_ru
    search_limit: int = 7
    enrich_top: int = 5
```

Каждый тумблер действует ровно в одной точке алгоритма (лемма — §3.1 п.1; фолбэки — §3.1 п.3–4; алиасы — §3.2 матч-множество), поэтому вклад изолируем и интерпретируем.

### 3.4 Почему тумблеры именно эти — трейдофф «качество vs простота методологии»

| Механика | Решение | Трейдофф |
|---|---|---|
| Лемматизация | тумблер, default on | иначе флективный русский обвалит recall; в статье одна строка — “we search the nominative lemma” |
| CirrusSearch / Wikipedia-фолбэки | тумблер, default on | усложняют описание поиска, но спасают ~15–20% редких терминов от красного; вклад покажет ablation |
| Матч по aliases | тумблер, default on | голый label уронит часть зелёных в эскалацию — не ошибка, но дороже (больше LLM-вызовов) |
| Блоклист анахронизмов + тип-фильтр | удалить совсем | описания кандидатов сами говорят “football club” — judge справится; цена: детерминированная ветка теряет защиту (риск R1) |

## 4. Judge-контракт

- Интерфейс прежний: инжектируемый `judge` callable; `terminology/` не импортирует `openai`/`LLMClient` (инвариант №6 репо-CLAUDE.md соблюдается конструкцией вызывающего кода).
- Вход промпта: surface, lemma, предложение-контекст, нумерованный список кандидатов `QID: label — description`. Disambiguation-страницы приходят как есть (Q1).
- Выход — строгий JSON `{"qid": "Q..." | null, "reason": "<одно предложение>"}` (N1). `null` = «ничего не подходит» → `judge_rejected`.
- **Settings-поверхность — конкретно** (паттерна «NerConfig в Settings» не существует: сегодня в Settings только Evaluators и Model Registry, NER-конфиг живёт в CLI). Новая единственная строка конфига: таблица `grounding_config(id=1, model_name REFERENCES model(name), prompt TEXT, params_json TEXT)` + REST `GET/PUT /api/grounding-config` + карточка **Grounding** в Settings (рендер по образцу карточки Evaluator: модель из registry, редактируемый промпт, params). `temperature=0` по умолчанию. Точные имена — на этапе плана, поверхность (таблица + 2 эндпоинта + карточка) — контракт этой спеки.
- **Параметры judge-вызова:** `max_tokens=512` (ответ — один QID + одно предложение); политика reasoning-параметров — по существующей per-model матрице `model_matrix.py` (задокументированный фикс: на reasoning-моделях effort-режим обрезает JSON и удваивает цену — параметр опускается так же, как для NER-экстрактора).
- Eval-харнесс строит judge из CLI-аргументов (OpenRouter) — тот же injection-паттерн, что у экстрактора в `term_pipeline.py`, с его же бюджет-механикой: `--dry-run` (оценка стоимости до прогона, $0) и `--max-usd` (кумулятивный потолок **на весь 8-конфигный прогон**, дефолт $5, проверка каждые N термов).
- **Демо-бюджет:** grounding-judge вызовы в webapp идут через существующий `budget.reserve()/settle()` (жёсткий кап $2/200 вызовов) как `_judge_live`; при вызове из precompute/seeding — под общий precompute sub-cap. Отдельного rate-limit на перегранудинг не вводим — глобального капа достаточно (throwaway-демо).
- Кэш judge-решений — **«one sense per discourse»**: ключ `(scope_id, lemma, candidates_qids, model, prompt_hash)`, где `scope_id` = документ в демке / страница в eval. `config_hash` в ключ **не входит**: конфиг влияет только на генерацию кандидатов, а `candidates_qids` уже в ключе — идентичные judge-входы из разных ablation-конфигов делят одно решение (без смещения: вход побайтово тот же; стоимость прогона не умножается на 8). Внутри документа повторы термина бесплатны; между документами решение не переносится (контексты разные — это и есть смысл контекстной дизамбигуации). Эвристика стандартная для WSD, явно называется в методологии.
- **Конкурентность:** граундинг в демке выполняется последовательно по параграфам; кэш judge — upsert last-write-wins, гонка двух одинаковых промахов в худшем случае стоит один лишний LLM-вызов и не нарушает целостность. Параллелизация пайплайна — вне скоупа, при её появлении ключу нужен уникальный констрейнт.

## 5. GroundingTrace v1 и хранение

Новая колонка: `term.trace_json TEXT NOT NULL DEFAULT '{}'`. Схема версионируется полем `v`.

```json
{
  "v": 1,
  "config": {"use_lemma": true, "use_fallbacks": true, "match_aliases": true},
  "queries": [
    {"q": "Кадашман-Харбе", "kind": "surface", "mechanism": "wbsearchentities", "n_hits": 0},
    {"q": "Кадашман-Харбе", "kind": "surface", "mechanism": "cirrus", "n_hits": 2}
  ],
  "search_source": "cirrus",
  "candidates": [
    {"qid": "Q1721895", "label_ru": "Кадашман-Харбе I", "label_en": "Kadashman-Harbe I",
     "description": "Kassite king of Babylon, 15th c. BC",
     "aliases_ru": [], "aliases_en": [], "matched": null},
    {"qid": "Q1721903", "label_ru": "Кадашман-Харбе II", "label_en": "Kadashman-Harbe II",
     "description": "Kassite king of Babylon, 13th c. BC",
     "aliases_ru": [], "aliases_en": [], "matched": null}
  ],
  "exact_matches": [],
  "resolved_by": "llm_disambiguation",
  "judge": {"model": "gpt-5.5-low", "prompt_hash": "sha256:…",
            "response": {"qid": "Q1721895", "reason": "…"},
            "usage": {"prompt_tokens": 410, "completion_tokens": 42, "reasoning_tokens": 0},
            "cost_usd": 0.00031, "latency_ms": 812, "error": null},
  "chosen_qid": "Q1721895",
  "n_api_calls": 5,
  "latency_ms": 1900
}
```

`n_api_calls` — только сетевые вызовы, кэш-хиты не считаются (семантика существующего `WikidataClient.n_calls`); на прогретом кэше smoke-прогон честно показывает 0. `judge.usage`/`cost_usd` заполняются из usage-метаданных LLM-ответа (схема `budget.log_call`) — колонка «стоимость» в §8 суммируется прямо из traces.jsonl, без сверки с внешним дашбордом.

`matched` у кандидата: `null` или `{"kind": "label_ru" | "alias_ru" | "alias_en", "value": "<совпавшая строка>", "query": "lemma" | "surface"}`.

Хранение:
- **Демка** — trace денормализованно в каждой строке `term` (просто; одинаковые surface разделяют решение через кэш граундинга, но строки независимы).
- **Eval** — `reports/terminology/g6/<config>/<run_id>/traces.jsonl` + `metrics.json`, где `run_id` = ISO-timestamp запуска (не дата: same-day перезапуск после фикса не должен ни перезаписывать, ни падать). Прогоны не перезаписываются (D6). **LFS: существующие правила `.gitattributes` НЕ покрывают `reports/terminology/**`** (покрыт только `data/**`) — тем же коммитом добавляется правило `reports/terminology/**/*.jsonl filter=lfs …`.
- **`metrics.json` v1** (контракт, по образцу trace):

```json
{"v": 1, "config": {"use_lemma": true, "use_fallbacks": true, "match_aliases": true},
 "golden": {"version": "terminology_gold.jsonl@<commit>", "n_total": 99, "n_groundable": 82,
            "n_context_reconstructed": 0, "n_excluded_wikidata_unavailable": 0},
 "qid_accuracy_groundable": {"correct": 61, "total": 78, "value": 0.782, "ci95": [0.68, 0.86]},
 "red_split": {"golden_red_hit": 6, "golden_red_total": 8},
 "difficulty_distribution": {"green": 0, "yellow": 0, "red": 0},
 "resolved_by_distribution": {"exact_label": 0, "llm_disambiguation": 0, "judge_rejected": 0,
                              "judge_unavailable": 0, "wikidata_unavailable": 0, "no_candidates": 0},
 "escalation_rate": 0.0, "n_api_calls": 0, "n_judge_calls": 0,
 "judge_cost_usd": 0.0, "latency_ms_p50": 0, "latency_ms_p95": 0}
```

- **HTTP-кэш Wikidata** — существующий JSONL-кэш `WikidataClient` без изменений.
- Существующие колонки `term` не меняются; contract null-rule расширяется случаем `judge_unavailable` (🟡 + grounded=null, §3.2) — амендмент фиксируется в demo-contracts.md тем же коммитом.

## 6. Экстрактор: лемма

- Схема ответа: `[{surface, lemma, category}]`; промпт `prompts/02_term_extract.md` дополняется требованием номинативной леммы (для словосочетаний — согласованная номинативная форма: «династии Цин» → «династия Цин»).
- Валидация: surface — существующий литеральный substring-guard; lemma — sanity-чек (непустая, ≤ 80 символов, без переводов строки), иначе `lemma = surface`.
- `deterministic_surfaces` (fallback без модели) отдаёт `lemma = surface`.
- Изменение промпта инвалидирует extract-кэш (`extract_key`) — пересчёт сид-параграфов заложен в Phase C (Q4).

## 7. Архитектура: судьба файлов

| Файл | Судьба |
|---|---|
| `grounding/label_first.py` | **новый** — G6, единственная стратегия; реализует §3, пишет trace §5 |
| `grounding/candidates.py` | переписывается: параметризация `GroundingConfig`, без тип-фильтра, `label_ru` отделён от алиасов, трекинг `queries[]` для trace |
| `grounding/api_first.py`, `llm_judge.py`, `hybrid.py`, `mgenre.py` | **удаляются** (+ экспорты `grounding/__init__.py`) |
| `verdict.py` | худеет: минус `difficulty_from_candidates`, `passes_type_filter`, notability; пейринговая часть (fuzzy-локация, head-token guard) остаётся |
| `wikidata.py` | клиент без изменений; минус `ANACHRONISTIC_TYPES`/`DISAMBIGUATION`/`SCHOLARLY_ARTICLE`-константы, если их не использует пейринг (проверить на этапе плана) |
| `base.py` | `GroundingResult` получает поле `trace: dict` (уже есть) — дополняется контрактом v1; `Judge`-протокол уточняется под `{qid, reason}` |
| `webapp/db.py` | DDL: `term.trace_json`; сид/апгрейд через пересоздание демо-БД (throwaway, Phase C) |
| webapp Settings (backend + frontend) | секция **Grounding**: модель + промпт + params (зеркало NER) |
| `scripts/eval_strategies.py` | grounding-часть → `scripts/eval_grounding.py` (ablation 8 конфигов); пейринговый eval сохраняется |
| `scripts/term_pipeline.py`, `rebuild_demo.py`, `emit_demo_grounding.py` | единственный grounder = G6(default); зависимость от `lemmas.json` удаляется |
| `scripts/merge_goldens.py` | **не трогаем**: продолжает читать `lemmas.json` (golden-tooling исключение D4) |
| `webapp/seed.py`, `scripts/load_terms.py` | INSERT-списки колонок дополняются `trace_json`; проверить позиционные `row[i]`-индексации в тестах (`tests/test_terminology.py`) |
| `docs/superpowers/specs/2026-06-30-demo-contracts.md` §4 | **SSOT для DDL** (routing в CLAUDE.md): добавить `trace_json` в DDL-секцию + амендмент null-правила (🟡 judge_unavailable ⇒ grounded=null) — тем же коммитом |
| `.gitattributes` | новое LFS-правило `reports/terminology/**/*.jsonl` |
| `docs/stages/terminology.md`, `docs/pipeline.md` | переписываются в том же коммите, что и код (sync rule); supersession-note D1 |

## 8. Eval на golden-99 и ablation

- **8 конфигураций**: `000, 100, 010, 001, 110, 101, 011, 111` — обе лестницы (leave-one-in от базы `000`, leave-one-out от default `111`). Все 8 делят один прогретый `wikidata_cache.jsonl` и прогоняются одной сессией — Wikidata-состояние идентично для всех конфигураций (иначе ablation конфаундится дрейфом поисковой выдачи).
- Леммы в eval берутся из golden (поле `lemma`, как в старом харнессе) — экстрактор в eval-контур не входит; в проде лемму отдаёт экстрактор (§6). Это разделение фиксируется в отчёте.
- **Контексты golden:** 34/99 строк имеют `context=null` (в т.ч. 3 из 9 жёлтых) — для них контекст **реконструируется** из текста параграфа по позиции surface (паттерн `_mention()` старого харнесса); число реконструированных фиксируется в `metrics.json.golden.n_context_reconstructed`. Строки, где параграф недоступен, не выбрасываются молча — judge получает пустой контекст с пометкой в trace.
- На конфигурацию: **QID accuracy на граундабельных** (главная), red/groundable split vs golden 🔴, доля 🟢/🟡/🔴, распределение `resolved_by`, escalation rate (доля LLM-вызовов), число API-вызовов, judge-вызовов, латентность, стоимость (из `trace.judge.cost_usd`).
- **Малое n — обязательная честность:** каждая доля в таблице — с сырыми счётчиками («61/78»), QID accuracy — с 95% CI (Wilson). Явная оговорка в отчёте и статье: на ~78 граундабельных термах 1 терм ≈ 1.3 п.п. — разницы меньше ~3 термов неотличимы от шума и не интерпретируются.
- **Валидация жёлтого класса (качественная):** 9 golden-🟡 строк (человеческая разметка «заметный омоним») сверяются с фактическим путём G6(111): сколько эскалировало в `llm_disambiguation`, сколько ушло 🟢/🔴 — таблица-приложение в отчёте. Это закрывает вопрос «ваш 🟡 — настоящая амбигуити или шум?» без возврата к difficulty-accuracy.
- **Бюджет прогона:** `--dry-run` печатает оценку (эскалаций × цена вызова, по конфигурациям и суммарно) до старта; `--max-usd` (дефолт $5) — жёсткий кумулятивный потолок на весь 8-конфигный прогон. Worst-case без кэша ≈ 8×99 вызовов; шаринг judge-кэша по `candidates_qids` (§4) режет это в разы.
- «Заметно хуже» из Q5 квантифицируется: падение G6(111) больше чем на 2 терма (>2.5 п.п.) относительно референса 0.78 → обязательный разбор по trace до закрытия блока (разбор обязателен и при меньшем падении, но там он short-form).
- **Методологический сдвиг**: под path-семантикой difficulty — свойство алгоритма, а не термина; difficulty-метки golden (🟡 = «заметный омоним») больше **не** сравниваются с выходом G6 как accuracy. GT из golden: QID + флаг «не должен граундиться» (🔴-строки).
- Референс: G6(111) сопоставляется с G3 = 0.78 QID acc (Q5). Судьбу расхождения решает разбор trace, не откат.
- Выход: `metrics.json` + таблица в HTML-отчёте блока; traces сохраняются (§5).

## 9. Методология для статьи (draft, EN)

> Terms are grounded to Wikidata in two tiers. First, a **deterministic exact-label match**: we query `wbsearchentities` with the term's nominative lemma and surface form; if exactly one candidate's Russian label (or alias) equals the query, it is accepted without any model call. Second, only when the label is **ambiguous** (several exact matches) or **inexact** (candidates exist but none match exactly), an LLM disambiguates over the candidates' one-line Wikidata descriptions given the source sentence, returning a single entity or abstaining. Terms with no candidates after search fallbacks are marked ungroundable. This yields a natural transparency metric — the **share of terms resolved deterministically vs. via LLM** — and each decision carries a per-decision machine-readable trace (queries, candidates, match kind, judge model, rationale, token usage). We ablate the three components of the deterministic tier — two retrieval (lemma search, full-text fallback) and one matching (alias expansion) — in both leave-one-in and leave-one-out ladders. Within a document we cache disambiguation decisions per (lemma, candidate set) — the standard one-sense-per-discourse assumption.

Позиционирование против нейросетевых EL-бейзлайнов (mGENRE, REL и т.п.) — одно предложение в статье: наш вклад — деплоймость и прозрачность при почти нулевой LLM-стоимости для demo-track, а не SOTA-recall нейросетевого линкера; G2 mGENRE был реализован кодом в ранней итерации, не запускался (нет GPU-прогона) и удалён — честно указывается как future work, а не как сравнимый бейзлайн.

Черновик обрастает числами после eval-блока; формулировка «deterministic exact-label match, LLM disambiguation over candidate descriptions only when the label is ambiguous» — канон для секции.

## 10. Редизайн Glossary (design-only)

Мокап: [2026-07-03-glossary-redesign-mockup.html](2026-07-03-glossary-redesign-mockup.html) (реальные `--va-*` токены, UI-строки — английские). Реализация — отдельный PR после этого блока; данные (`trace_json`) пишутся с первого дня.

- Колонки: Difficulty, Pair, Source·RU (+ чип категории), Translation·EN, Wikidata (label + QID), **Grounding** (бейдж пути: ◆ label match / ◇ LLM · model / ◇ LLM rejected all / ○ no candidates; ошибочные пути §3.2 — ⚠ judge error и ⚠ wikidata error — рендерятся жёлтым/красным вариантом бейджа с тултипом ошибки), **Mentions ×N**. Note и Paragraph удаляются.
- Строка = (лемма, QID), N3; сводка-строка N4 под заголовком.
- Раскрытие строки: RU/EN контекст-предложения с подсветкой (EN — на лету, N2); степпер пути из 4 шагов (Query → Search → Label match → Decision) с хитами, механизмом и `resolved_by`; таблица кандидатов с «Matched via» и ✓/✗; карточка Judge decision (модель + reason, N1); листаемый список всех вхождений.

## 11. Риски

| # | Риск | Смягчение |
|---|---|---|
| R1 | Без блоклиста «Спарта → AC Sparta Prague» возможна и в детерминированной ветке (если клуб — единственный точный матч) | масштаб покажет golden-eval; регрессии фиксируем в known_issues.md и обсуждаем точечно; блоклист втихую не возвращаем |
| R2 | Disambiguation-страницы засоряют judge-листы | RU-label обычно с суффиксом «(значения)» — детерминированную ветку не ломают; judge игнорирует по описанию |
| R3 | Воспроизводимость LLM-компонентов (лемма, judge) | temperature=0; model+prompt в каждом trace; кэш judge-решений; модель указывается в методологии статьи |
| R4 | Стоимость LLM на следующем блоке (1k страниц) | escalation rate узнаём на golden-99; бюджет-оценка + пилот до большого прогона; кэш judge |
| R5 | Инвалидация extract-кэша (промпт + lemma) | пересчёт дешёвый (15 параграфов); порядок согласован с Phase C (Q4) |
| R6 | Judge недоступен при эскалации | честный 🟡 без QID + ошибка в trace (§3.2), не молчаливый топ-1 |
| R7 | ё→е-фолдинг теоретически может склеить две разные сущности, различающиеся только ё/е | принято осознанно (§3.2): выигрыш на несогласованности RU-labels заведомо больше; кейс ловится юнит-тестом и, при появлении в данных, фиксируется в known_issues |

### Открытые вопросы, передаваемые следующему блоку (Wikipedia-eval)

1. **First-mention GT × one-sense-per-discourse:** разметка Википедии линкует сущность один раз (первое упоминание), кэш judge наследует решение первого упоминания на всю страницу. Следующая спека обязана решить: не-первые упоминания скорятся против единственной GT-ссылки страницы или исключаются из знаменателя recall.
2. **Дрейф качества лемм экстрактора:** прогнозы escalation rate/стоимости из этого блока (R4) предполагают качество лемм уровня golden; на out-of-domain тексте Википедии лемма от экстрактора может деградировать — риск флагуется здесь, меряется там.

## 12. Тестирование

- **Unit** (fake WikidataClient на фикстурах, judge-стаб): по тесту на каждую строку таблицы решений §3.2; тумблер-матрица — каждый тумблер меняет ровно свою точку алгоритма (запросы/фолбэки/матч-множество); trace-полнота — в каждом пути заполнены все обязательные поля v1; валидация lemma-sanity; политика ошибок §3.2 полностью: judge-недоступен (R6), кривой JSON терминален без ретрая, QID вне кандидатов → judge_unavailable, Wikidata-исключение → wikidata_unavailable; `norm()` — кейсы ё/е («Семён»/«Семен») и Unicode-дефисов («Кадашман-Харбе» с U+2013); стабильность порядка кандидатов на реплее кэша (§3.1).
- **Integration**: `pipeline.run` с G6 — контрактный null-rule на red; `term.trace_json` доезжает до API демки.
- **Eval smoke**: харнесс на подмножестве golden с прогретым кэшем, без сети — детерминированный результат.
- **e2e (шаг 6/8 процесса)**: демка сидится Phase C-пайплайном на G6; Glossary-вкладка показывает текущие колонки без регрессий (редизайн — позже).
- Весь тест-сьют зелёный после переписи (бейзлайн ветки — 298 passed; тесты удалённых стратегий удаляются вместе с кодом, новые G6-тесты добавляются).

## 13. Definition of Done

1. G6 — единственная стратегия в `grounding/`; старый код и пайплайн-зависимость от `lemmas.json` удалены (`merge_goldens.py` — исключение D4); тест-сьют полностью зелёный (бейзлайн ветки: 298 passed, живой прогон pytest на `feat/grounding-label-first` @ 31bb23f, 2026-07-03).
2. Trace v1 пишется в `term.trace_json` и в eval-JSONL; ни одно обязательное поле не пустует ни на одном пути `resolved_by`; `metrics.json` соответствует контракту v1 (§5).
3. Settings-секция Grounding работает (таблица `grounding_config` + `GET/PUT /api/grounding-config` + карточка), judge отвечает `{qid, reason}`; демо-вызовы judge проходят через `budget.reserve()/settle()`.
4. Ablation-таблица 8 конфигов на golden-99 собрана (счётчики + CI, один прогретый кэш, `--dry-run`-оценка и `--max-usd`-кап соблюдены); G6(111) сопоставлен с референсом 0.78 (порог «заметно хуже» = >2 термов); качественная сверка 9 golden-🟡 строк приложена; расхождения разобраны по trace.
5. Доки синхронизированы тем же коммитом: stage-doc, pipeline.md, supersession-note, **demo-contracts.md §4 (DDL + null-rule амендмент)**, `.gitattributes` (LFS-правило); методология-draft §9 включена в stage-doc.
6. HTML-отчёт блока по шаблону Reports подан владельцу с сервировкой на localhost.
