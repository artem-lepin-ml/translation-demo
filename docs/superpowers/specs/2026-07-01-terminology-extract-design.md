# Stage 1 Extract — реальный извлекатель терминов (design)

Дата: 2026-07-01 · Ветка: `feat/terminology-extract` (от `dev-demo` @ 2bcbaf1) · Автор: агент terminology-extract · Ревизия: v2 (после `/verify-spec`, 5 аспектов)

Up-link: [docs/README.md](../../README.md) (L1-индекс) · Стадия-док: [docs/stages/terminology.md](../../stages/terminology.md) · Контракт: [demo contracts §1](2026-06-30-demo-contracts.md) · Известные проблемы: [docs/known_issues.md](../../known_issues.md).

**Смежный prior art (НЕ эта стадия):** research-бриф docs/experiments/2026-05-18-terminology-glossary-research.md (в ветке `old-gse-translating`) описывает *другую, ещё не построенную* стадию — Stage-3 post-edit подмену терминов в переводе (RU-терм → EN-primary). Мы заимствуем из него только (а) таксономию типов сущностей (§2 брифа) и (б) рекомендацию LLM-based NER для редких лемм (§5 п.5/п.7). Это **не** реализация алгоритма брифа.

## 1. Цель (проверяемое состояние)

Стадия `extract` надёжно извлекает исторические термины из RU-источника **независимо от регистра** — включая строчные народы, титулы, социальные слои, институты, культуры, предметы — как воспроизводимый код, а не как заглушку по заглавным буквам + ручной JSON. Достигнуто ⇔ выполнены измеримые критерии §6 (SC1–SC7).

## 2. Проблема (что реально происходит)

- Единственный код-метод `deterministic_extract` ([extract.py:55](../../../src/palimpsest/terminology/extract.py#L55)) матчит регексом `_PROPER` **только заглавные** кириллические слова/цепочки. Целые классы терминов в русском строчные → структурно невидимы.
- Этот метод **не подключён к пайплайну**: `grep` по `scripts/`+`src/`+`tests/` не находит ни одного вызова `deterministic_extract` вне юнит-тестов. Реальный вход пайплайна — захардкоженный вручную `data/seed/extracted_surfaces.json`, который `scripts/term_pipeline.py mentions` разворачивает в `terminology_terms.jsonl` через `mentions_from_surfaces`.
- В тесте и в known_issues это признано: *«E0 is a coarse fallback… The precise extractor is the E1 subagent»* ([test_terminology.py:122](../../../tests/test_terminology.py#L122)); *«Extraction precision unmeasured… the E1 subagent extractor is not scored»* ([known_issues.md:15](../../known_issues.md)). «E1 subagent» в коде отсутствует.

Итог: стадия — заглушка по заглавным + замороженный ручной JSON, а не извлекатель.

### 2.1. Доказательство (данные владельца, проверено вживую через Wikidata API)

Строчные термины, которые **есть** в Wikidata (невидимы текущему экстрактору): `лугаль`→Q854642, `энси`→Q932495 (ensí), `кутии`→Q549531 (Gutian people), `амореи`→Q203507 (Amorites), `клерухии`→Q1774212 (cleruchy), `преторы`→Q172907 (praetor), `касситы`→Q243312 (Kassites), `иллирийцы`→Q146715.

Строчные термины, которых **нет** в Wikidata (пустой поиск подтверждён вживую): `гермокопиды`, `шанъиньцы`, `наши бильтим`, `сутии-амореи`, `шаньдунский архипелаг`.

Нюанс на границе с grounding: `мушкенум`→Q1586330 **существует**, но наивный RU-поиск по нему пуст (нужна транслитерация; already known — [known_issues.md:12](../../known_issues.md) перечисляет авилум/мушкенум как recall-floor). Отсюда принцип: **extract = высокий recall, grounding = точность** (живой Wikidata-фильтр решает, реальная ли сущность и её difficulty). Мерить их надо **раздельно**.

Источник примеров: `data/seed/terminology_gold.jsonl` (99 верифицированных вручную терминов, 32 строчных) + живые `wbsearchentities`/`wbgetentities`.

## 3. Scope

**В scope (только эти пути — не пересекаются с веткой model-registry):** `src/palimpsest/terminology/` (extract.py, base.py — новый тип), `scripts/` (term_pipeline.py, новый eval_extraction.py), `data/seed/` (extracted_surfaces.json, terminology_terms.jsonl, terminology_out.json, lemmas.json, новый hist_term_lexicon.json), демо-БД (per-worktree артефакт), `docs/` (stages/terminology.md, known_issues.md, README.md, этот спек), `tests/`, `reports/terminology/`.

**Вне scope:** файлы agent-а model-registry (`configs/models.yaml`, `src/palimpsest/webapp/*`, `src/palimpsest/llm/client.py`, `frontend/*`); grounding/pairing verdict-логика (`verdict.py`, `wikidata.py`, стратегии — только чтение `grounding/candidates.py` как read-only хелпера); GPU-стратегии; `glossary/main.json` (не трогаем, SSOT Stage-3); `data/raw/`; живой вызов LLM в демо-рантайме (по дизайну — персист).

## 4. Архитектура и интерфейсы

Extract остаётся набором функций-модуля (без `ExtractionStrategy`-протокола — правило «не вводить общий интерфейс, пока его не требуют ≥2 места одновременно»). Единица извлечения — **surface** `{surface, category}`; разворот в `TermMention[]` — существующий `mentions_from_surfaces`.

**Схема surface — только `{surface, category}`.** Поле `lemma` НЕ эмитим: `cmd_mentions` ([term_pipeline.py:49](../../../scripts/term_pipeline.py#L49)) всё равно перезаписывает лемму из `lemmas.json` (`[{**s, "lemma": lemmas.get(s["surface"], s["surface"])}]`), так что `lemma` из экстрактора — dead on arrival. Единый источник лемм остаётся `lemmas.json`; см. §5 про его расширение.

Новый тип инъекции в `base.py` (рядом с `Judge`):

```python
# base.py — отдельный алиас: отличается арностью возврата (list[dict] vs Judge's dict),
# но следует той же схеме subagent-инъекции, что Judge для grounding/pairing.
Extractor = Callable[[str], list[dict]]   # source text -> [{surface, category}]
```

`extract.py`:

```python
EXTRACT_PROMPT: str    # NER-инструкция + few-shot, живёт в src/; исполняет её subagent (не openai)

def llm_surfaces(source: str, *, extractor: Extractor | None = None) -> list[dict]:
    """Настоящий извлекатель («E1»). Параметр назван `extractor` (не совпадает с типом Extractor).
    extractor=None → деградирует к deterministic_surfaces (импортируемо/тестируемо без модели, как G3).
    ВАЛИДАЦИЯ: каждый возвращённый surface должен быть буквальной подстрокой source
    (re.search(re.escape(surface), source)); не-подстроки ОТБРАСЫВАЮТСЯ и считаются
    (surfaces_dropped_not_in_source) — иначе mentions_from_surfaces молча даёт 0 упоминаний."""

def deterministic_surfaces(source: str) -> list[dict]:
    """Офлайн-floor. Заглавные цепочки (существующая логика _PROPER, включая drop
    одиночного заглавного в начале предложения) + газеттир + суффиксные правила этнонимов.
    Детерминирован, дедуплицирован (seen-set), стабильный порядок. Возвращает [{surface, category}]."""

def deterministic_extract(source: str) -> list[TermMention]:   # сигнатуру СОХРАНЯЕМ (её ждут тесты)
    return mentions_from_surfaces(source, deterministic_surfaces(source))
    # drop-правило sentence-initial-single-word мигрирует ВНУТРЬ deterministic_surfaces без изменения поведения

# без изменений: mentions_from_surfaces, load_mentions, _context
```

**Газеттир** — данные в `data/seed/hist_term_lexicon.json` (`[{lemma, category, forms}]`), матч-логика в `extract.py`. Записи — **только recall-подсказки (surface+category), без QID/notability**: решение «реальная ли сущность» остаётся исключительно за grounding (живой Wikidata-поиск в `candidates.py`), газеттир не становится вторым несинхронизированным источником истины. Покрывает классы, реально встречающиеся в корпусе (титулы: лугаль/энси/ном/патеси; соц. слои: авилум/мушкенум/вардум; народы). Суффиксные правила этнонимов (`-цы/-яне/-ане/-еи`) **защищены от ложных срабатываний**: минимальная длина основы + курируемый allowlist основ, чтобы не ловить обычные слова (`молодцы`, `бойцы`). Матч морфологически-толерантный через `forms` + `lemmas.json`, **без hard-зависимости на pymorphy** (stdlib). Потолок офлайна честно в stage-доке — LLM-путь основной для незнакомых лемм.

Инвариант: `src/palimpsest/terminology/` **не импортирует** `openai`/`LLMClient` (SC4, grep-тест). `EXTRACT_PROMPT` исполняется subagent-ом из `scripts/term_pipeline.py extract` (бэкает `Extractor`), не из `src/`.

### 4a. Контроль over-capture — рассмотренная альтернатива two-pass

Аспект R&D справедливо указал: `grounding/candidates.py::generate_candidates(wd, mention)` — уже готовый read-only Wikidata-зонд (wbsearchentities→CirrusSearch→wiki-langlink). Возможен two-pass: propose surfaces → зонд → **выкинуть zero-candidate до персиста**, снижая red-rate.

**Решение: НЕ авто-выкидываем zero-candidate.** difficulty=🔴 на реальном термине без Wikidata-статьи (`гермокопиды`, `шанъиньцы`) — это **фича демо** (сигнал «нет сущности»), а не шум; зонд не отличает «настоящий red-терм» от «мусора» (оба zero-candidate), так что авто-drop убил бы легитимную red-демонстрацию. Точность контролируем иначе:
1. LLM-промпт с жёсткой категорийной схемой («только исторические термины, не обычные слова») → высокая precision by construction (LLM знает, что `молодцы` — не термин).
2. Детерминированные суффиксы под guard (min-основа + allowlist) — см. §4.
3. `generate_candidates` используем только как **диагностику**: `eval_extraction.py` репортит, какие предложенные surfaces дают zero candidates (для спот-чека precision), но не фильтрует автоматически. Grounding остаётся единственным авторитетом существования (консистентно с §4).

Так альтернатива осознанно рассмотрена и ограниченно принята (диагностика), не проигнорирована.

## 5. Данные, воспроизводимость и не-цикличный gold

Воспроизводимость — по образцу G3 (`rebuild_demo_g3.py` читает персист `reports/terminology/g3_groundings.json`; живой LLM в rebuild не нужен):

1. `scripts/term_pipeline.py extract` прогоняет извлекатель по 16 seed-абзацам; subagent бэкает `Extractor`. Валидные surfaces (§4) персистятся в `data/seed/extracted_surfaces.json` (тот же демо-вход, схема `{paragraph_id, surfaces:[{surface,category}]}` — не меняется). Без subagent — `deterministic_surfaces`.
2. **Расширение `lemmas.json`:** для новых строчных форм, найденных извлекателем, добавляем `форма→лемма` (ключ — инфлектированный surface, как уже устроен `lemmas.json`), чтобы `cmd_mentions` резолвил лемму. Иначе новые surfaces получат `lemma=surface` и рассинхронизируются с golden-merge по лемме.
3. Далее существующая цепочка без изменений: `mentions` → `run`/`rebuild_demo_g3` → `load_terms` → демо-БД. Контракт цел (null-rule, `candidates_json` всегда `'[]'`).

**Gold для измерения — нецикличный:** surfaces из `data/seed/terminology_gold.jsonl`. Провенанс подтверждён: `scripts/merge_goldens.py` собирает его из трёх независимых hand-authored источников (`gold_sources/*`), сверенных с живой Wikidata; **ни один код-путь не читает `extracted_surfaces.json` при сборке gold** → регенерация surfaces его не загрязняет. Все 99 строк имеют `surface`+`paragraph_id`, покрыты все 16 абзацев, внутри абзаца дублей surface нет.

**`scripts/eval_extraction.py`** (метрика):
- строит `{pid: {gold surfaces}}` из `terminology_gold.jsonl`;
- гоняет три извлекателя (СТАРЫЙ cap-only `_PROPER`, НОВЫЙ `deterministic_surfaces`, `llm_surfaces`) по каждому абзацу;
- `extraction_prf` ([eval_harness.py:103](../../../src/palimpsest/terminology/eval_harness.py#L103)) — вход **строго raw SURFACE-строки с обеих сторон** (НЕ леммы: gold — инфлектированные `лугаля`/`Лагаше`, извлекатель тоже отдаёт surfaces). Это **type-level recall** (уникальные surface-строки на абзац; `set()` схлопывает повторные вхождения — так и задумано, gold без внутри-абзацных дублей). Case-split: `surface[0].islower()` (строчные vs заглавные). Агрегация — **micro-pooling** по всем 16 абзацам (макро на малых per-para наборах шумит);
- пишет `reports/terminology/extraction_metrics.json` (в т.ч. `surfaces_dropped_not_in_source`, zero-candidate-диагностику из §4a).

Спорные «spurious» LLM-находки вне gold спот-чекаются; кто адъюдицирует — **отдельный проход, не тот, что тюнит пороги SC1** (иначе мягкая цикличность). Остаточный риск фиксируем в known_issues (non-blocking).

## 6. Success criteria (измеримые)

- **SC1 (главное).** Type-level recall по **строчным** surfaces (vs gold, micro-pooled) растёт с baseline cap-only (`_PROPER` ≈ 0.0 на строчных) до: `deterministic_surfaces` ≥ 0.5, `llm_surfaces` ≥ 0.8. Числа измеренные, в `extraction_metrics.json`.
- **SC2.** Общий recall растёт; **precision измерена** для всех трёх извлекателей (закрыт «future work» из [known_issues.md:15](../../known_issues.md)).
- **SC3.** `llm_surfaces(extractor=None)` импортируемо и работает без модели (деградация к `deterministic_surfaces`), как G3.
- **SC4.** `src/palimpsest/terminology/` не импортирует `openai`/`LLMClient` (grep-тест).
- **SC5.** Демо регенерировано: ≥ 8 ранее пропущенных **строчных** терминов присутствуют в демо-БД как `Term` (green/yellow/red по решению grounding); контракт цел (null-rule, `candidates_json='[]'`, валидные spans). Легитимные red-термины (гермокопиды) допустимы (фича); проверяем, что **мусорных** новых surfaces нет.
- **SC6.** Все существующие юнит-тесты terminology зелёные + новые тесты: строчные in/out, газеттир, суффиксный guard (молодцы НЕ ловится), fallback-деградация (`extractor=None`), no-openai-import, surface-not-in-source отбрасывается, дубль/overlap LLM-surfaces деградируют штатно (longest-first, без double-count/исключений), сохранение drop sentence-initial-single-word.
- **SC7 (precision-потолок — конкретный и falsifiable).** Порог зафиксирован ЗДЕСЬ, до прогона извлечения (не подгоняется post-hoc); владелец решения — агент terminology-extract на шаге execute.
  - **new-red-rate:** `new_red / (new_red + new_green) ≤ 0.35`, где new_* — термины, добавленные новым извлечением поверх старого демо. Якорь: в gold среди 32 строчных 9🔴/23🟢 ≈ **0.28**, порог даёт headroom на легитимные историзмы, но ловит мусор.
  - **surfaces_dropped_not_in_source** ≤ **5%** предложенных LLM-surfaces (иначе промпт/валидация теряют recall молча).
  - Ни один известный не-groundable мусор (молодцы-класс) не попал в демо.
  - **Remediation при превышении:** ужесточить газеттир/суффиксный guard и/или курировать surfaces, перепрогнать `eval_extraction` — и только затем регенерировать демо-БД. Демо на проваленном пороге НЕ регенерируем.
  - Следствие: низкоточный извлекатель не может тихо пройти SC1, ломая green/red-баланс демо.

## 7. Риски и честные потолки

- **Over-capture / red-rate.** Ожидаемо: новые строчные добавят и 🟢 (лугаль/амореи/касситы), и несколько 🔴 (реальные не-Wikidata: гермокопиды/шанъиньцы). Красные на реальных терминах — фича (честный сигнал), не баг; мусор ограничен **конкретным порогом SC7** (`new_red/(new_red+new_green) ≤ 0.35`, якорь 0.28 по gold) + §4-guard-ами + LLM-precision. Дельту red-rate измеряем и указываем в отчёте/known_issues; порог задан числом до прогона, при превышении — remediation (SC7), а не подгонка.
- **Surface-not-in-source.** LLM может вернуть перефраз/иную форму → `mentions_from_surfaces` молча даёт 0. Снято валидацией+счётчиком (§4, SC7).
- **Офлайн-потолок.** `deterministic_surfaces` не обобщается на незнакомые редкие леммы вне газеттира — floor, не ceiling. Явно в stage-доке.
- **Цикличность gold.** Снята: `terminology_gold.jsonl` собран `merge_goldens.py` из трёх независимых источников, не из `extracted_surfaces.json`. Остаточная мягкая цикличность (рост gold из spurious) — отдельный адъюдикатор + запись в known_issues.
- **Дестабилизация демо.** Изоляция: своя ветка/worktree/БД, слияние в `dev-demo` независимо, файлы не пересекаются с model-registry. Контрактные тесты + e2e (шаг 6) ловят регрессии.
- **Стоимость/недетерминизм LLM.** Прогон один раз, `temperature=0`, персист; демо-рантайм без LLM.
- **Газеттир-дисциплина.** `hist_term_lexicon.json` — hand-authored, курируется как gold (не растёт молча из LLM-выхлопа); провенанс/дисциплина в stage-доке. Авто-LFS покрыт (`.gitattributes: data/**/*.json`).

## 8. План (высокоуровнево; детализация — в writing-plans)

1. **base.py:** тип `Extractor`. **extract.py:** `EXTRACT_PROMPT`, `llm_surfaces(*, extractor=None)` c валидацией surface∈source, `deterministic_surfaces` (заглавные + газеттир + guarded-суффиксы, детерминизм/дедуп), рефактор `deterministic_extract` поверх surfaces с сохранением sentence-initial drop. Газеттир `data/seed/hist_term_lexicon.json`.
2. **Тесты (TDD, до реализации):** список из SC6; существующие остаются зелёными.
3. **scripts/term_pipeline.py:** подкоманда `extract` (бэкает `Extractor` subagent-ом; фолбэк deterministic). **scripts/eval_extraction.py:** метрика §5 → `extraction_metrics.json`. Прогон измерения.
4. **Регенерация демо:** subagent-прогон извлечения по 16 абзацам → `extracted_surfaces.json` (+ расширить `lemmas.json`) → `mentions`→`run`/`rebuild_demo_g3`→`load_terms` → демо-БД.
5. **Doc-parity (в тех же коммитах):**
   - [docs/stages/terminology.md](../../stages/terminology.md): Interface (extract теперь код: `llm_surfaces`/`deterministic_surfaces`), Subtleties (recall/precision по регистру, газеттир, surface-валидация), **обновить устаревшие числа** — recall `0.81`, `19🟡/9🔴`, red-rate — на измеренные; добавить ссылку на `merge_goldens.py` как провенанс gold.
   - [docs/known_issues.md](../../known_issues.md): строка :15 «Extraction precision unmeasured» → переписать (теперь измерена, E1 реализован); строка :12 (red-rate) сверить; добавить остаточную мягкую-цикличность.
   - [docs/README.md](../../README.md): добавить строку про этот extract-спек в routing-таблицу.
6. **Верификация:** `/verify-pr` (≥5 аспектов) + e2e-tester по демо (строчные термины видны, grounded, контракт цел, red-rate в норме).

## 9. Реальный OpenRouter в e2e — ключ, вызовы, учёт расходов

Владелец кладёт ключ OR; e2e гоняет **настоящий** LLM-API (тот же внешний OpenRouter, что у оценщиков демо), а не Claude-subagent-симуляцию. Требование владельца: следить за корректностью вызовов и расходами; расходы — **реальные из ответов OR**, не самооценка.

### 9.1. Модель и промпт — из Settings/registry, не хардкод (уточнение владельца)
NER-экстрактор конфигурируется **в Settings рядом с оценщиками**: модель выбирается из registry, промпт редактируется в окне. Контракт и текст промпта — §10. Здесь — как это питает e2e:
- **Модель** — зарегистрированная запись registry (`ModelRegistryEntry{name, base_url, api_key_env, params}`), выбранная как NER-модель в Settings. Harness резолвит `NerConfig.modelName` → registry-запись → `LLMConfig.from_model_config(entry)` (существующий путь: `base_url` из registry, ключ из `os.environ[entry.api_key_env]`). Для OR владелец регистрирует OR-модель с `api_key_env=OPENROUTER_API_KEY`.
- **Ключ** — в **gitignored** `.env` (`.gitignore:12`): `OPENROUTER_API_KEY=sk-or-…`. Читается только из env (как весь проект). **Никогда** не логируется/коммитится; в отчётах — маскированный хвост (первые 4 + «…», как `apiKeyMasked` в demo-контракте).
- **Промпт** — `NerConfig.prompt` (default — авторский из §10). Harness читает `NerConfig` из демо-БД/`GET /api/ner-config` (когда surface от model-registry готов) **с фолбэком на встроенный default + выбранную модель**, чтобы extractor и офлайн-тесты не блокировались на UI (не строю пререквизиты — [[feedback_make_existing_work]]).
- `configs/models.yaml` и `client.py` (файлы model-registry) **не редактирую**. `terminology/` чист: `Extractor` инъектируется, LLM-вызов — в `scripts/` через `LLMClient` (Invariant #6 цел).

### 9.2. Вызовы (корректность)
Extractor бэкается OR: на каждый из 16 абзацев — один `LLMClient.complete(EXTRACT_SYSTEM, EXTRACT_USER(source), temperature=0)`, ответ → `parse_surfaces` (JSON) → валидация `llm_surfaces` (surface ∈ source). Логирую per-paragraph в `reports/terminology/extract_llm_calls.jsonl`: `{pid, model, finish_reason, n_surfaces, n_dropped_not_in_source, n_bad_category, latency_ms}`. Корректность вызова = валидный JSON + finish_reason=`stop` (не обрезано) + surfaces-подстроки + категории из enum. Битый ответ → 1 ретрай с backoff, затем фиксируется как ошибка (не молча).

### 9.3. Расходы (реальные из OR, не мои оценки)
`LLMClient.complete()` на baseline возвращает только `content` (usage выбрасывает), а `client.py` — не мой. Поэтому реальную стоимость беру из **самого OpenRouter**:
- `GET https://openrouter.ai/api/v1/credits` (или `/key`) **до и после** батча → `usage_after − usage_before` = фактический потрачено-USD (число OR, не моё). Это billing/observability REST-GET (`urllib`), не LLM-completion и не через openai-SDK → Invariant #6 не нарушает. **Оговорка о точности:** баланс OR отдаётся с центовой точностью, суб-центовая дельта может округлиться до `$0.00` — тогда фиксирую честно «< $0.01 (ниже разрешения credits-API)» и, если OR вернёт `usage` в теле ответа, дополнительно суммирую per-call токены как corroborating-сигнал.
- Если ветка model-registry добавит usage-возврат в `complete()` — дополнительно пишу per-call usage; **но не завишу** от их in-flight изменений.
- В отчёте раздельно: (а) **оценка-потолок ДО прогона** (помечена «estimate»), (б) **фактический OR-spend ПОСЛЕ** (из credits-delta). Claude-side токены (если fallback-subagent) — отдельной строкой, не смешиваю с OR.

### 9.4. Безопасность бюджета (жёсткие лимиты)
- `--dry-run`: печатает точные промпты + оценку-потолок, тратит $0.
- Хард-кап **`N_CALLS ≤ 20` считает только first-attempts** (16 абзацев + запас); ретраи (§9.2, ≤1/абзац) считаются отдельным `N_RETRIES ≤ N_CALLS`, чтобы транзиентные ретраи не выбивали кап ложным abort.
- `--max-usd 0.10`: проверка credits-delta по ходу, abort при превышении. Ожидаемая оценка: 16 вызовов ≈ 24k in + 6k out ≈ **< $0.01** на gpt-4o-mini (реальное — из §9.3).
- Прогон **один раз**: результат персистится в `extracted_surfaces.json`; повторные сборки/демо идут из персиста, **новых трат нет** (демо-рантайм без LLM по дизайну §5).

### 9.5. e2e-поток (реальный сквозной — build-time сид + live re-extract)
- **Сид (build-time, без live-LLM на загрузке):** `term_pipeline.py extract --real` → OR-NER 16 абзацев → валидация → `extracted_surfaces.json` (+ credits-delta, correctness-лог) → `mentions`→`run`→демо-БД. Демо стартует из персиста.
- **Live-путь (главная демо-интеракция, §10.2):** браузерный e2e (`e2e-tester`/`playwright-cli`) правит `NerConfig` в Settings → жмёт **«Re-extract stale (N)»** → `POST …/extract` делает **живой OR-вызов только для stale** → новые строчные термины появляются, grounded (живая Wikidata), `cached`-бейдж при повторе; точечная ↻ в Inspector переизвлекает один абзац. Проверяем: термины видны/grounded, контракт цел, red-rate в норме SC7, кеш не делает лишних OR-вызовов.
- **Отчёт:** correctness-таблица + **реальный OR-spend** (credits-delta, из OR) + отдельно Claude-side + «выполнено vs не выполнено».

Так реальный OR используется в LLM-части моей стадии (extraction), а e2e честно прогоняет весь путь на настоящем внешнем LLM + живой Wikidata + браузере.

## 10. NER-конфиг в Settings — контракт, промпт, граница с model-registry

Владелец: NER настраивается в Settings **аналогично оценщикам** (модель из registry + промпт в окне). Оценщик уже = `Criterion{modelName→registry, prompt, …}` (таблица `criterion`, `/api/criteria`, редактор в SettingsTab). NER — **сиблинг-сущность по тому же паттерну**, но singleton (один экстрактор, не список).

### 10.1. Контракт `NerConfig` (мой — я его потребляю; хранение/UI — model-registry)
```ts
NerConfig {
  modelName: string;   // → ModelRegistryEntry.name (та же registry, что у оценщиков)
                       // РЕКОМЕНДУЕМЫЙ seed-default: "anthropic/claude-haiku-4.5"
                       // (победитель турнира 2026-07-02; бюджетная замена — "google/gemini-2.5-flash-lite")
  prompt: string;      // редактируемый; default — §10.3
  params?: Record<string, unknown>;  // temperature и т.п.; default temperature:0
  enabled?: boolean;
}
// singleton: GET /api/ner-config -> NerConfig ; PUT /api/ner-config {NerConfig} -> NerConfig
// хранение: одна строка (напр. таблица ner_config или k/v в существующей config-таблице)
```
**Граница (минимализм, [[feedback_make_existing_work]]):** UI (окно рядом с оценщиками: model-picker + prompt-textarea) и хранение/`/api/ner-config` — это **малое расширение существующего evaluator-паттерна в файлах model-registry** (`SettingsTab.tsx`, `webapp/app.py`, `db.py`). **Я это не строю** (иначе — пререквизит-скаффолдинг, за который владелец уже останавливал). Мой вклад: (а) контракт `NerConfig`, (б) авторский default-промпт §10.3, (в) extractor, потребляющий `{modelName, prompt}`. Кто именно вписывает UI — координирует владелец; extractor работает и без UI (фолбэк на default, §9.1), так что моя ветка не блокирована.

### 10.2. Режим: live re-extract с кешем (решение владельца)
Выбрано **live re-extract, кеш-осознанно** — по образцу существующего `evaluate`-кеша (`cached`/`cachedAt`/`docVersion`).
- **Кеш-ключ (стабильный, НЕ питоновский `hash()`):** `extract_key = sha256((source + "|" + modelName + "|" + prompt + "|" + json.dumps(params, sort_keys=True, separators=(",",":"))).encode()).hexdigest()`. Питоновский `hash()` солится per-process (`PYTHONHASHSEED`) → после рестарта uvicorn всё стало бы stale — поэтому `hashlib.sha256` + **канонизация `params` через `sort_keys=True`** (иначе разный порядок ключей = разный хэш = лишние OR-вызовы). Параграф хранит свой `extract_key`. **Stale** = `extract_key(параграф, текущий NerConfig) ≠ сохранённый`.
- **Инкрементально:** переизвлекаются ТОЛЬКО stale-параграфы (смена конфига / новый контент) — минимум OR-вызовов.
- **Старт демо — persisted-сид** (`extracted_surfaces.json`→БД, без LLM на загрузке). Живой OR-вызов — **только по кнопке и только для stale**. Инвариант «нет live-LLM на загрузке» сохранён; «поиграть промптом» работает on-demand.
- **Кнопки (гибрид, решение владельца):** (1) главная **«Re-extract stale (N)»** в Settings рядом с редактором `NerConfig`; (2) точечная **↻** в Inspector выбранного параграфа; (3) **stale-бейдж** на параграфах со старым `extract_key`. Без кнопок на каждой строке Document (чтение не засоряется).

### 10.2a. Граница и мой контракт (кто что строит)
- **Model-registry (их файлы, малое расширение evaluator-паттерна):** endpoint `POST /api/paragraphs/{id}/extract` (+ опц. `POST /api/documents/{id}/reextract-stale`), кеш-поля `extract_key`/`extracted_at`, кнопки в `SettingsTab`/Inspector, stale-бейдж, `GET/PUT /api/ner-config`.
- **Моё (`terminology/` + `scripts/`):**
  - `extract_key(source, ner_config) -> str` — **sha256**-формула выше (стабильна между процессами, `sort_keys`); её же зовёт и сид, и endpoint (байт-идентичные ключи);
  - `extract_paragraph_terms(source, target, ner_config, *, grounder, pairer, extractor=None) -> list[Term]` — собирает `Term[]` через существующий `pipeline.run` (extractor бэкается OR из выбранной модели; grounding = живая Wikidata с кешем; без модели — deterministic fallback); `Term`/null-rule + `candidates_json != NULL` сохранены;
  - `DEFAULT_NER_PROMPT` (§10.3), газеттир, eval, **сид пишет `extract_key`** для каждого параграфа (иначе на первой загрузке всё stale).
- Endpoint **зовёт мою `extract_paragraph_terms`**; в их файлы я не пишу. Контракт самодостаточен → обе ветки идут параллельно и вливаются в `dev-demo` независимо.
- **Поведение endpoint:** stale/force → `extract_paragraph_terms` → заменить термины параграфа, записать `extract_key`+`extracted_at` (+`cached:false`); не stale → вернуть cached (**0 OR-вызовов**). **Бюджет-гард на endpoint (сторона model-registry):** live-путь делает реальные платные OR-вызовы, поэтому endpoint нужен свой per-request/-batch кап + отказ выше порога — гарды §9.4 покрывают только мой CLI, не их endpoint.
- **NerConfig.params** валидируется на запись тем же secret-key-rejection, что `ModelRegistryEntry.params` (demo-contracts §2: ключи `/api.?key|token|secret|password|auth/i` отклоняются).

### 10.3. Default NER-промпт (авторский, Anthropic-техники: роль, ## разделы, XML-теги, хороший/плохой пример, few-shot)
Живёт как seed-default `NerConfig.prompt` (в Settings редактируется). `{{source}}` подставляется harness-ом; выход валидируется (`surface ∈ source`, §4).

```text
## Роль
Ты — историк-источниковед и лингвист. Ты размечаешь русский академический
исторический текст (Древний мир: Египет, Месопотамия, античность, Древний
Китай/Индия) и извлекаешь ТЕРМИНЫ и ИМЕНА СОБСТВЕННЫЕ, чей перевод на английский
стоит проверить.

## Задача
Из <source> извлеки ВСЕ исторические сущности-термины ВНЕ зависимости от регистра.
Русский пишет СТРОЧНЫМИ целые классы важных терминов (народы, титулы, соц. слои) —
извлекай их так же тщательно, как имена с заглавной. Это главная цель разметки.

## Категории
<categories>
- person      — лица: Хаммурапи, Саргон, Кадашман-Харбе
- place       — города/страны/реки/области: Лагаш, Евфрат, Вавилония
- people      — народы/племена/этносы (ЧАСТО строчные): амореи, кутии, касситы, шумеры
- title       — титулы/должности/адм. единицы (ЧАСТО строчные): лугаль, энси, претор, ном
- social      — социальные слои (строчные): авилум, мушкенум, вардум
- institution — институты/своды законов/объединения: Законы Хаммурапи, принципат, клерухия
- dynasty     — династии: III династия Ура, Чжоу
- culture     — культуры/периоды: старовавилонский период
- event       — битвы/войны/договоры/реформы: битва при Кадеше
</categories>

## Чего НЕ извлекать
<do_not_extract>
- Обычные слова и роли в общем смысле, не являющиеся именем/термином: город, царь, война,
  страна, знать, люди, вещи, дороги, имущество, гражданство, глава, магистрат, молодцы, бойцы.
- Описательные и бюрократические словосочетания («государственные поставки продовольствия»,
  «военное дело», «малая семья») — извлекай только устойчивый термин внутри, если он есть.
- Отдельные прилагательные и глаголы (докерамический, доземледельческий, завоёванный).
- Отдельные даты/годы/числа.
- Принцип: извлекай КОНКРЕТНЫЕ термины (имена, титулы, народы, соц. слои, институты, культуры),
  а не общие понятия. Если это общее слово в описательном смысле — пропусти.
</do_not_extract>

## Правила
- surface — ТОЧНАЯ подстрока из <source>, в той форме и падеже, как в тексте
  (например «Лагаше», а не «Лагаш»). НЕ нормализуй, НЕ переводи, НЕ придумывай.
- Одна запись на каждый УНИКАЛЬНЫЙ surface (повторы не дублируй).

## Хороший пример
<example>
<source>В Лагаше, одном из номов, правитель-лугаль опирался на авилумов, тогда как амореи наступали с запада.</source>
<output>[{"surface":"Лагаше","category":"place"},{"surface":"номов","category":"title"},{"surface":"лугаль","category":"title"},{"surface":"авилумов","category":"social"},{"surface":"амореи","category":"people"}]</output>
</example>

## Плохой пример (так НЕ делать)
<bad_example>
<source>В Лагаше правитель опирался на воинов.</source>
<bad_output>[{"surface":"правитель","category":"title"},{"surface":"воинов","category":"people"},{"surface":"Lagash","category":"place"}]</bad_output>
<why_bad>«правитель»/«воинов» — обычные слова, не термины; «Lagash» — перевод, а surface обязан быть русской подстрокой «Лагаше».</why_bad>
</bad_example>

## Формат вывода
Только JSON-массив объектов {surface, category}. Без пояснений и без markdown-ограды.

<source>
{{source}}
</source>
```

Тестируемость промпта: few-shot-пример совпадает с реальным seed-абзацем «Лагаш» (paragraph_id=40), так что расхождение default-промпта с ожиданием ловится юнит-тестом/eval.

## Приложение — разрешение находок `/verify-spec` (v1→v2)

| # | Аспект/severity | Находка | Разрешено в v2 |
|---|---|---|---|
| 1 | engineering HIGH | LLM surface не-подстрока source → молчаливый 0 | §4 валидация + счётчик `surfaces_dropped_not_in_source`; SC6/SC7 |
| 2 | system HIGH | параметр `extract: Extractor` шэдоуит тип | §4: параметр переименован в `extractor` |
| 3 | rnd HIGH | two-pass grounding-filter не рассмотрен | §4a: рассмотрен, ограниченно принят как диагностика (не авто-drop) |
| 4 | rnd HIGH | red-rate over-capture без чисел | §7+SC7: конкретный порог `new_red/(new_red+new_green) ≤ 0.35` (якорь 0.28), зафиксирован до прогона, remediation-путь при превышении |
| 4b | rnd MED (re-review) | «согласованный порог» не falsifiable (можно подогнать post-hoc) | SC7: число задано в спеке, владелец+тайминг+remediation указаны |
| 5 | rnd MED | terminology.md:62 числа устареют | §8 шаг 5 явно называет 0.81/19🟡9🔴/red-rate |
| 6 | rnd MED | бриф — другая стадия (Stage-3) | header переформулирован «смежный prior art» |
| 7 | rnd MED | не проверяем, не всплывёт ли мусор в демо | SC5/SC7 явные проверки |
| 8 | system MED | `lemma?` в схеме discarded cmd_mentions | §4: `lemma` убран из схемы; §5 расширяем lemmas.json |
| 9 | system MED | Extractor vs Judge не обоснован | §4: одно предложение (арность возврата) |
| 10 | data MED | extraction_prf: surface vs lemma | §5: строго raw surfaces с обеих сторон |
| 11 | data MED | occurrence vs type recall | §5: явно type-level |
| 12 | goal MED | `docs/pipeline.md` не существует | header/шаг 5 → docs/README.md + stages + known_issues |
| 13 | eng/system/data LOW | газеттир-локация, recall-hints-only, invocation point, case-split/micro, lemmas-асимметрия, газеттир-дисциплина, gold-провенанс | §4/§4a/§5/§7 покрыты |

### §9/§10 re-verify (2-й проход, 3 аспекта)
| # | severity | Находка | Разрешено |
|---|---|---|---|
| 14 | caching **CRITICAL** | `hash()` солится per-process → всё stale после рестарта | §10.2: `hashlib.sha256`, стабилен между процессами |
| 15 | caching/contract **HIGH** | `params` в хэше без канонизации → ложный stale | §10.2: `json.dumps(params, sort_keys=True)` |
| 16 | caching **HIGH** | сид не пишет `extract_key` → всё stale на 1-й загрузке | §10.2a: сид обязан писать `extract_key` |
| 17 | ops **HIGH** | ретрай выбивает `N_CALLS ≤ 20` ложным abort | §9.4: кап считает first-attempts, ретраи отдельно |
| 18 | ops **HIGH** | live-endpoint не покрыт бюджет-гардами | §10.2a: свой бюджет-гард на endpoint (сторона model-registry) |
| 19 | ops MED / contract LOW | credits суб-цент → $0.00; `NerConfig.params` secret-reject | §9.3 оговорка о точности; §10.2a secret-key rejection |
| 20 | contract LOW | model-registry ещё не подтвердил имена контракта | → запись в `docs/known_issues.md` (assert, сверить при merge в dev-demo) |
