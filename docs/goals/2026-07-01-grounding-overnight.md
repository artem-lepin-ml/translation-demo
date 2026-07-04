# Goal — Term Grounding module (`difficulty` signal), autonomous overnight

**Дата:** 2026-07-01
**Сценарий:** B (autonomous, без вопросов Артёму)
**Бюджет:** ~8 часов wall-clock · токенов не жалеть
**Спонсор:** Артём (R&D lead)
**Branch:** `feat/term-grounding` от `feat/demo` (через `.claude/skills/superpowers/using-git-worktrees/SKILL.md`)
**Железо:** GPU (CUDA) есть · живой публичный API Wikidata/Wikipedia разрешён

Документ — input для агента, который проснётся ночью и работает по сценарию B (8 шагов из [CLAUDE.md](../../CLAUDE.md)). Ключевые решения зафиксированы в §2 — не передумывать. Любую ambiguity решать своим judgment и фиксировать в spec/plan.

Up-link: docs/pipeline.md (документ в ветке `old-gse-translating`). Контракт `Term`/`WikidataRef`: [docs/superpowers/specs/2026-06-30-demo-contracts.md](../superpowers/specs/2026-06-30-demo-contracts.md) §1. Исследование-основа: docs/experiments/2026-07-01-grounding-research.md (документ в ветке `old-gse-translating`; сохранить туда research Doc 2 при старте).

**Роутинг моделей (жёстко):** спеки, план, ВСЕ решения, построение golden-set, осмотр данных, агрегация, финальный отчёт и решение о прунинге — **Opus** (`model: opus`, effort high→xhigh). Весь код стратегий, тесты, e2e-харнесс, документация — **Sonnet** (`model: sonnet`, medium→high). Рекон/grep/механика — **Haiku**. Правило R1: сабагенты НЕ наследуют модель — ставить `model:` явно.

---

## 1. Цель (one sentence, measurable)

Построить модуль **грундинга** RU-термина в Wikidata — вход: уже извлечённый термин (`surface` + опц. `lemma` + опц. предложение-контекст), выход: сигнал `difficulty` (🟢 подтверждён / 🟡 многозначен / 🔴 не найден) + `grounded: WikidataRef|null` + `candidates: WikidataRef[]` ровно по типу `Term` §1 — реализовав **3 полные стратегии + 1 baseline** как swappable за одним интерфейсом, прогнав их на **всех** seed-терминах против golden-set, и выбрав лучшую по accuracy/латентности с числовым сравнением.

Артефакты `src/palimpsest/terminology/grounding/` + `reports/grounding/*` + HTML `docs/reports/2026-07-01-grounding.html` готовы к утреннему ревью.

## 2. Зафиксированные решения — НЕ передумывать

| # | Решение | Резон |
|---|---------|-------|
| 1 | Модуль живёт в **`src/palimpsest/terminology/grounding/`**; тонкий CLI-враппер `scripts/term_ground.py` | «One stage = one module + скрипт» из CLAUDE.md. Отдельный субпакет — нет конфликта с `pairing`-веткой на мёрдже. |
| 2 | Интерфейс: `GroundingStrategy.ground(TermMention) -> GroundingResult` (Protocol в `grounding/base.py`). `TermMention{surface, lemma?, context?, lang="ru"}`; `GroundingResult{difficulty, grounded, candidates, latency_ms, n_api_calls, trace}` | Одна абстракция, стратегии взаимозаменяемы; `trace` — для аудита и HTML-отчёта. |
| 3 | Выход строго по контракту §1: `difficulty ∈ {green,yellow,red}`, `grounded: WikidataRef\|null`, `candidates: WikidataRef[]`. `WikidataRef{qid, url, label}` | Чтобы модуль без переделки писал в `Term` и в `POST /terms`. |
| 4 | **Verdict-логика** (единая для всех стратегий, в `grounding/verdict.py`): 🟢 = ровно 1 уверенный кандидат нужного/совместимого типа; 🟡 = ≥2 правдоподобных кандидата (омонимы) ИЛИ 1 кандидат с низкой уверенностью/слабым контекстом; 🔴 = 0 кандидатов после фильтра | Совпадает с определением сигнала в контракте (§ «Два сигнала»). Тип-фильтр и порог — общие, стратегии отличаются только генерацией/дизамбигуацией кандидатов. |
| 5 | **Тип-фильтр P31/P279** обязателен: выкинуть `P31=Q4167410` (disambiguation) и `P31=Q13442814` (scholarly article); при известном из контекста типе (people/place/deity/…) — оставлять только совместимые по `wdt:P31/wdt:P279*` | Типичный шум `wbsearchentities`; из research Doc 2 §Block 1. |
| 6 | **Живой API, вежливо:** User-Agent `Palimpsest-grounding/1.0 (+https://github.com/<repo>; a.lepin.student@gmail.com) python-requests/2.x`; `maxlag=5` (парсить тело, не только HTTP-код); последовательно, ≤3 конкурентных; батч `wbgetentities` до 50 QID; уважать `Retry-After` при 429/503; **локальный кеш** QID→{labels,aliases,sitelinks,P31} в `reports/grounding/wikidata_cache.jsonl` (переживает рестарты) | Etiquette из research Doc 2 §1.7. Кеш = воспроизводимость + скорость. |
| 7 | **Все LLM-вызовы — через субагента, не через внешний API.** Модуль НЕ импортирует `openai`/не зовёт `LLMClient` — он принимает **инъектируемый** `judge: Callable[[Prompt], StructuredOut]`. Ночной харнесс подставляет реализацию, бэкенд которой — **субагент** (`model: haiku` для нормализации/дешёвого, `model: sonnet` для дизамбигуации), `temperature=0`, structured output. Прямое требование Артёма + держит Hard Invariant #6 чистым (в `src/` вообще нет LLM-зависимости) | Дёшево (бюджет сессии, не платный API), детерминированно, swappable: в проде тот же `judge` можно завести на `LLMClient` без правки стратегии. |
| 8 | Golden-set строит **Opus**, руками, **не циркулярно** (не вывод одной стратегии); при единогласии всех стратегий — сверка третьим источником (VIAF/Britannica/Pleiades/Wikipedia) и пометка | Иначе circular validation. Аналогично §4.golden прошлого goal-цикла. |
| 9 | `factowl/` не трогать; `data/raw/` не трогать; ветку `artem` и прод не трогать | Hard Invariants #7/#9 + правила проекта. |
| 10 | **Не** реализуем `pairing`/`pairAccuracy` здесь — это отдельная ветка `feat/term-pairing`. Тут только `difficulty`-половина `Term` | Чёткое разделение двух ночных циклов. Пара стабится golden-QID в другом цикле. |
| 11 | **Каждый подход независим и проходит свой gate.** Подход «принят» ⇔ (a) его unit/integration/e2e-тесты зелёные И (b) независимый **audit-агент** (fresh context, `model: sonnet`) дал PASS. Аудит проверяет: пересчёт метрик из сырых `results_*.jsonl` (не верить самоотчёту), качество кода (идиоматичность, изоляция, обработка ошибок), покрытие сложных/edge-кейсов (омонимы, somevalue/novalue, редиректы QID, пустой контекст, non-ASCII), полноту документации. FAIL по любому пункту → подход не «зелёный», чинить или обрезать | Прямое требование Артёма: подход валиден только если реально работает и подтверждён со стороны. Аудитор ≠ автор кода (анти-круговая проверка). |
| 12 | **Общий интерфейс и харнесс проектируются ПЕРВЫМИ**, до любой стратегии: `base.py` + `runner.py` + `eval_harness.py` (метрики) + `audit` контракт фиксируются и замораживаются; стратегии пишутся строго под них, параллельно и независимо | Требование Артёма «предварительно спроектировав общие интерфейс и харнесс». Замороженный контракт = стратегии не конфликтуют и сравнимы 1:1. |
| 13 | **Финальное сравнение с прошлой веткой `feat/glossary-overnight`** (`glossary/main.json`: RU-ключ → `{ru,en,strategy,source,notes}`). Для каждого термина, который есть и в глоссарии, и в нашем прогоне — совпал ли QID/EN-эквивалент, что нового наш модуль дал (Wikidata-QID, которого в глоссарии нет), где разошлись | Артём: «сравни результаты с тем, что я уже делал в другой ветке». Глоссарий — не golden (мог быть LLM-сгенерён), а reference-точка: показать прирост. |

## 3. Скоуп

### IN — обязательно к утру

**Код (`src/palimpsest/terminology/grounding/`):**
- `base.py` — `TermMention`, `GroundingResult`, `WikidataRef`, `GroundingStrategy` (Protocol).
- `verdict.py` — общая verdict-логика (§2.4) + тип-фильтр (§2.5).
- `wikidata.py` — тонкий клиент: `wbsearchentities`, `wbgetentities` (батч ≤50), `list=search`/CirrusSearch (`inlabel:@lang`, `haswbstatement:P31=`), SPARQL+mwapi `EntitySearch` с P31/P279-фильтром, Wikipedia `langlinks`/`pageprops.wikibase_item`; UA/maxlag/Retry-After/кеш (§2.6).
- `strategies/api_first.py` — **G1 (дефолт).** wbsearchentities(lang=src) → wbgetentities-обогащение → тип-фильтр → CirrusSearch-фолбэк для редких историзмов → Wikipedia-цепочка как второй генератор кандидатов → verdict.
- `strategies/mgenre.py` — **G2 (GPU).** self-host mGENRE (mBART, 105 языков), constrained beam search → top-N QID → тип-фильтр → verdict. Trie/KB подготовить в setup-шаге; фиксировать версию весов.
- `strategies/llm_judge.py` — **G3.** `wbsearchentities` генерит кандидатов; выбор правильного QID по описанию/типу/контексту предложения делает **инъектируемый `judge`** (§2.7) — субагент, `model: sonnet`, structured output `{qid, confidence, reason}`. Стратегия НЕ импортирует LLM-клиент, только зовёт переданный `judge`.
- `strategies/refined_baseline.py` — **G4 (baseline).** ReFinED (или OpenTapioca live API) для EN-стороны — только для сравнения покрытия там, где одна сторона английская; честно пометить англо-центричность.
- `runner.py` — прогон любой стратегии по списку `TermMention`; сбор `GroundingResult` + trace.
- `eval_harness.py` — **проектируется первым** (§2.12): читает `results_<strategy>.jsonl` + golden → считает все метрики §4 → пишет `metrics.json`. Один харнесс для всех стратегий (сравнимость 1:1). Судья-субагент подключается сюда через `judge`-параметр.

**Данные (committed под LFS в `reports/grounding/` и `data/seed/`):**
- `data/seed/grounding_terms.jsonl` — distinct RU имена собственные/термины, извлечённые из 16 seed-абзацев (`data/seed/seed_paragraphs.jsonl`) с полем `context` (предложение). Ожидаемо ~40–70 уникальных сущностей (Кадашман-Харбе, аморреи/сутии, Месопотамия, шумеры, лугаль, Ур, Исин, Урукагина, Ишби-Эрра, Элам, Симашки, Убейдская культура …).
- `data/seed/grounding_gold.jsonl` — golden-set (Opus): `{surface, lemma, context, gold_qid, gold_difficulty ∈ {green,yellow,red}, category ∈ {ruler,dynasty,place,event,culture,people,deity,ethnic_group,institution}, source_url, notes}`. ≥ **40** записей, non-circular (§2.8).
- `reports/grounding/wikidata_cache.jsonl` — кеш ответов API.
- `reports/grounding/results_<strategy>.jsonl` — по одной строке на (термин × стратегия) с verdict/grounded/candidates/latency/n_api_calls.
- `reports/grounding/metrics.json` — все метрики §4.
- `reports/grounding/audit_<strategy>.md` — вердикт независимого audit-агента по каждой стратегии (§2.11): PASS/FAIL + пересчитанные метрики + замечания по коду/edge-кейсам/докам.
- `reports/grounding/vs_glossary.json` — сравнение с `feat/glossary-overnight` (§2.13): по термину — match/mismatch/new-QID.

**Docs:**
- `docs/stages/term-grounding.md` — по формату CLAUDE.md (Purpose, Design decisions, Interface, Subtleties, Status), ссылка на контракт и research.
- `docs/pipeline.md` — раздел «Term grounding (difficulty)» + линк.
- CLAUDE.md routing — строка «Грундинг терминов | docs/stages/term-grounding.md».
- `docs/known_issues.md` — грабли Wikidata API (разрежённость не-EN лейблов, somevalue/novalue, редиректы QID, maxlag-с-HTTP-200, prefix-only wbsearchentities).

**Tests:**
- unit на `verdict.py` (все три ветки на синтетике), `wikidata.py` (парсинг ответов на зафиксированных фикстурах), тип-фильтр.
- integration: каждая стратегия на 5 «якорных» терминах даёт ожидаемый verdict (Месопотамия→green Q11767; заведомый омоним→yellow; выдуманный термин→red).

**E2E (обязательно, руками осмотреть):**
- прогнать **лучшую** стратегию на всех 16 seed-абзацах → записать `difficulty/grounded/candidates` в `Term`-строки (`data/seed/grounding_out.json`), подгрузить в демо (заменив мок в `POST /terms`/seed) и **открыть в браузере** (`#/a` Glossary + точки на RU-словах): убедиться, что 🟢/🟡/🔴 и Wikidata-ссылки корректны глазами. ≥ **6 скриншотов** в `reports/grounding/shots/`. Провенанс — только seed-данные.
- замерить и показать **скорость** (латентность/термин, p50/p95) и **точность** (vs golden) — это прямое требование Артёма.

### OUT — НЕ делать
- `pairing`/`pairAccuracy`/выравнивание RU↔EN — отдельная ветка.
- Извлечение терминов из сырого текста «с нуля» — здесь термины на входе уже даны (`grounding_terms.jsonl`); построение этого списка из seed — механический шаг, не NER-исследование.
- Произвольные языковые пары на реальных данных: архитектура язык-агностична (`lang` параметр), но e2e гоняем на RU→EN (других данных нет). В отчёте — раздел «как обобщается на другую пару».
- Локальный дамп Wikidata (живой API разрешён).
- Не применять к прод-сайту, не трогать `feat/demo` кроме мёрджа.

## 4. R&D-эксперимент: стратегии + метрики

### 4 стратегии, прогоняются на ВСЕХ терминах `grounding_terms.jsonl`
- **G1 api_first** (дефолт), **G2 mgenre** (GPU, полная), **G3 llm_api** (полная), **G4 refined_baseline** (baseline, EN-сторона).
- Если mGENRE не поднимается за разумное время — задокументировать точную причину, оставить G1/G3 полными + G4, НЕ выкидывать молча.

### Метрики (в `reports/grounding/metrics.json`)
- **Grounding accuracy vs golden** (доля `grounded.qid == gold_qid`) — per strategy, primary + lenient (lenient = QID в пределах редиректа/родителя P279).
- **Verdict accuracy** для `difficulty`: confusion-matrix 🟢🟡🔴 vs `gold_difficulty` + macro-F1 — per strategy.
- **Coverage**: доля терминов с non-null `grounded` — per strategy.
- **Латентность**: p50/p95/max мс на термин + среднее `n_api_calls` — per strategy (кеш прогрет отдельно от холодного).
- **Pairwise agreement** по `grounded.qid` между стратегиями (6 пар).
- **Per-category breakdown** всех метрик выше по `category`.

### Golden-set: как Opus строит
Взять distinct термины из seed, для каждого руками найти правильный QID и verdict (🟡 если реально омоним в Wikidata; 🔴 если сущности нет — напр. узкий домен-термин), сверить по независимому источнику, записать `source_url`. Golden НЕ должен совпадать с выводом одной стратегии by construction.

### Порядок: сначала контракт, потом стратегии (§2.12)
1. Заморозить `base.py` (типы + Protocol) + `runner.py` + `eval_harness.py` + формат `results_*.jsonl` + audit-контракт. Это делает Opus (спека) → Sonnet (код каркаса) → быстрый прогон на 2-3 терминах, что харнесс считает метрики. 2. Только после этого — стратегии, каждая своим Sonnet-агентом, параллельно и независимо, строго под замороженный интерфейс.

### Per-approach gate (§2.11) — каждый подход проходит сам
Подход **G_i принят** ⇔ выполнены ОБА условия:
- **e2e/тесты зелёные:** unit (verdict/wikidata) + integration (5 якорных терминов) + прогон стратегии на всех seed-терминах без падений, результат схематически валиден.
- **audit-агент = PASS:** отдельный субагент (`model: sonnet`, fresh context, ≠ автор стратегии) получает код стратегии + её `results_<strategy>.jsonl` + golden и проверяет 4 оси:
  1. **Метрики** — пересчитывает accuracy/verdict-F1/coverage/latency из сырых результатов, сверяет с заявленными в `metrics.json` (расхождение → FAIL).
  2. **Качество кода** — идиоматичность (CLAUDE.md conventions), изоляция через интерфейс, обработка ошибок API (таймаут/429/пустой ответ), отсутствие прямых `openai`-импортов.
  3. **Сложные/edge-кейсы** — омонимы (→yellow), somevalue/novalue, редиректы QID, пустой/шумный контекст, non-ASCII/диакритика, термин которого нет в Wikidata (→red без падения).
  4. **Документация** — стратегия описана в стейдж-доке, интерфейс совпадает с кодом, subtleties не пусты.
- FAIL по любой оси → подход НЕ зелёный: Opus решает чинить (шаг 7) или обрезать с записью причины. Вердикт → `audit_<strategy>.md`.

### Сравнение с `feat/glossary-overnight` (§2.13)
После выбора лучшей стратегии: загрузить `glossary/main.json` из ветки `feat/glossary-overnight`, сматчить по RU-термину с нашим прогоном, посчитать: сколько терминов пересекается; на скольких QID/EN-эквивалент совпал; сколько QID наш модуль дал там, где в глоссарии их не было (прирост grounding); где разошлись и почему. Результат → `vs_glossary.json` + раздел в HTML-отчёте. Глоссарий — reference, не golden.

## 5. Acceptance criteria — что Артём проверяет утром

### 5.1 Модуль и интерфейс
- [ ] `python -c "from palimpsest.terminology.grounding.base import GroundingStrategy, TermMention, GroundingResult; print('ok')"`.
- [ ] Все 4 стратегии импортируются и реализуют `ground()`; `python -c "from palimpsest.terminology.grounding import runner; print('ok')"`.
- [ ] `wikidata.py` шлёт корректный User-Agent и обрабатывает `maxlag` (unit-тест на фикстуре maxlag-ответа с HTTP 200).

### 5.2 Данные и golden
- [ ] `data/seed/grounding_terms.jsonl` schema-valid, ≥ 40 distinct терминов, у каждого непустой `context`.
- [ ] `data/seed/grounding_gold.jsonl` ≥ 40 записей, каждая с `gold_qid` (или явным `null` для 🔴), `gold_difficulty`, `category`, `source_url`. Auto-check: `python -c "import json; r=[json.loads(l) for l in open('data/seed/grounding_gold.jsonl')]; assert len(r)>=40 and all(x.get('source_url') and x.get('gold_difficulty') in ('green','yellow','red') for x in r), 'gold invalid'; print(len(r))"`.
- [ ] Golden non-circular: в отчёте раздел «как строился golden» + для единогласных терминов указан третий источник.

### 5.3 R&D эксперимент
- [ ] `reports/grounding/metrics.json` содержит ВСЕ метрики §4 для 4 (или задокументированно 3) стратегий: accuracy×N (primary+lenient), verdict confusion + macro-F1, coverage, латентность p50/p95, pairwise agreement (6 пар), per-category. Auto-check: `python -c "import json; m=json.load(open('reports/grounding/metrics.json')); assert {'grounding_accuracy','verdict_f1','coverage','latency','pairwise_agreement','per_category'} <= set(m), set(m); print('ok')"`.
- [ ] `results_<strategy>.jsonl` для каждой стратегии на всех терминах.
- [ ] Выбрана **лучшая стратегия** с письменным обоснованием (accuracy × латентность × стоимость); слабые либо удалены, либо помечены `# BASELINE — not default` с причиной. Решение принимает Opus, зафиксировано в отчёте.

### 5.3b Per-approach gate + аудит (§2.11)
- [ ] Для КАЖДОЙ принятой стратегии есть `reports/grounding/audit_<strategy>.md` с вердиктом PASS от независимого агента (≠ автор кода), покрывающим 4 оси: метрики (пересчёт), качество кода, edge-кейсы, документация.
- [ ] Ни одна стратегия, помеченная «принята/дефолт», не имеет audit=FAIL. Обрезанные стратегии имеют записанную причину.
- [ ] Общий интерфейс/харнесс заморожены ДО стратегий (видно по истории коммитов: `base.py`/`runner.py`/`eval_harness.py` раньше `strategies/*`).

### 5.3c Сравнение с прошлой веткой (§2.13)
- [ ] `reports/grounding/vs_glossary.json` существует; в HTML-отчёте раздел «vs feat/glossary-overnight»: N пересечений, % совпадения QID/EN, сколько новых QID дал модуль. Auto-check: `python -c "import json; d=json.load(open('reports/grounding/vs_glossary.json')); assert 'overlap' in d and 'qid_new' in d; print('ok')"`.

### 5.4 E2E
- [ ] `data/seed/grounding_out.json` — `Term`-строки (difficulty/grounded/candidates) для всех 16 абзацев от лучшей стратегии, подгружены в демо.
- [ ] ≥ 6 скриншотов браузера (`reports/grounding/shots/`): RU-точки 🟢🟡🔴 + Wikidata-ссылки; в отчёте таблица «термин → verdict → QID → скрин».
- [ ] Латентность и accuracy лучшей стратегии на реальном прогоне — числа в отчёте.

### 5.5 Docs
- [ ] `docs/stages/term-grounding.md` по формату; `docs/pipeline.md` + CLAUDE.md routing обновлены; `docs/known_issues.md` пополнен.

### 5.6 Report + PR
- [ ] HTML `docs/reports/2026-07-01-grounding.html` (тёмная тема, 360-радар по аспектам, таблица сравнения стратегий, embed скриншотов, artifacts) + поднят локально на порту 8096+.
- [ ] Один PR `feat/term-grounding` → `feat/demo`; body на русском в стиле владельца (`feedback_pr_body_style`): таблица метрик coverage/accuracy/latency по стратегиям + вывод «какая победила и почему».

## 6. Порядок исполнения (8 шагов сценария B)
1. Спека (Opus) в `docs/superpowers/specs/` из этого goal + research Doc 2 → `/verify-spec` (≥3 аспекта). 2. План (`writing-plans`). 3. Ветка+воркти `feat/term-grounding` от `feat/demo`. 4. **Заморозить каркас** (§2.12): `base.py`+`runner.py`+`eval_harness.py`+audit-контракт (Opus спека → Sonnet код) — коммит РАНЬШЕ стратегий. 5. Golden-set (Opus, руками, с источниками). 6. Стратегии — параллельно, каждая своим Sonnet-агентом под замороженный интерфейс; сразу за каждой — **per-approach gate** (§2.11): тесты + independent audit-агент (`model: sonnet`, ≠ автор) → `audit_<strategy>.md`. 7. `/verify-pr` (≥5 аспектов) + e2e-tester (браузер) + аудит e2e-отчёта. 8. Fix (`systematic-debugging`) провалов gate/verify. 9. Сравнение с `feat/glossary-overnight` (§2.13) + финальный e2e + docs-keeper + HTML-отчёт + PR. Не успел стратегию — честно в known-issues, не молчать. Закончил рано — расширяй golden, гоняй больше кейсов, добавляй стратегию.
