# Palimpsest demo — контракты (data · API · DB)

Up-link: [архитектура](2026-06-30-demo-architecture-design.md) · дата: 2026-06-30 · ревизия 2 (после адверсариального ревью, см. changelog внизу)

> Единый источник истины по контрактам нового демо. TypeScript-типы = wire-DTO (frontend ↔ backend), ниже — SQLite-DDL и REST. Код на английском (идиоматично), пояснения на русском.

## Что уточнил контекст УЦП

Терминология — это **ДВА независимых сигнала 🟢🟡🔴**, а не один вердикт:

1. **Сложность термина** (`difficulty`) — грундинг RU-термина по Wikidata: 🟢 подтверждён (одна сущность) · 🟡 многозначный (омонимы) · 🔴 не найден. Рисуется **на исходном слове** (RU).
2. **Точность пары** (`pairAccuracy`) — правильно ли перевод выбрал эквивалент «ровно по тому же смыслу»: 🟢 верный · 🟡 спорный · 🔴 неверный. Рисуется **на паре** (RU↔EN). При `difficulty='red'` грундинга нет → `pairAccuracy = null` (оценивать не от чего).

Это контракт с term-агентом (роудмапа п.1 и п.3).

## 1. Доменные типы (wire-DTO)

```ts
// ───────── общие ─────────
type Verdict = 'green' | 'yellow' | 'red';
type CriterionId = string;          // произвольный, задаётся пользователем; PK критерия, неизменяем
type IssueStatus = 'open' | 'accepted' | 'dismissed';
type Severity = 'minor' | 'major';

interface WikidataRef {
  qid: string;          // "Q35355"
  label: string;        // EN-лейбл сущности
  description: string;  // краткая дизамбигуация
  url: string;          // https://www.wikidata.org/wiki/Q...
}

// ───────── контрибьюшен 1: терминология ─────────
interface Term {
  id: string;
  paragraphId: number;
  // источник (RU) — одна строка на КАЖДОЕ вхождение термина
  sourceSurface: string;        // словоформа как в тексте
  sourceLemma: string;          // каноническая RU-форма (демо предполагает RU-источник)
  context: string;              // фраза-контекст предложения, по которой выбран смысл (стиль KD-MT);
                                // КЛЮЧ дизамбигуации — не географический/категориальный тип
  charStart: number;            // смещение sourceSurface в paragraph.source (read-only → стабильно)
  charEnd: number;
  // ① СЛОЖНОСТЬ — грундинг Wikidata
  difficulty: Verdict;          // 🟢 подтверждён · 🟡 многозначен · 🔴 не найден
  grounded: WikidataRef | null; // выбранная сущность (🟢/🟡); null для 🔴
  candidates: WikidataRef[];    // конкурирующие смыслы (🟡); иначе []
  // ② ТОЧНОСТЬ ПАРЫ — правильный ли эквивалент «по тому же смыслу»
  targetSurface: string | null; // EN-эквивалент в переводе (null = отсутствует)
  pairAccuracy: Verdict | null; // 🟢 верный · 🟡 спорный · 🔴 неверный; null при difficulty='red'
  recommended: string | null;   // рекомендуемый EN-эквивалент (🟡/🔴); null при difficulty='red'
  note: string;
}

// ───────── контрибьюшен 2: оценщики и находки ─────────
interface Criterion {
  id: CriterionId;     // PK, неизменяем (URL-параметр авторитетен; в теле PUT игнорируется)
  name: string;        // имя оценщика (user-facing)
  modelName: string;   // ссылка на ModelRegistryEntry.name
  prompt: string;      // промпт оценивания (включает определение шкалы)
  scaleMin: number;    // напр. 1
  scaleMax: number;    // напр. 10
  weight: number;      // вес во взвешенной сумме
  color: string;       // цвет подчёркивания (не 🟢🟡🔴 — те зарезервированы за терминологией)
  enabled: boolean;    // soft-disable: скрыть критерий, не ломая историю скоров
}

interface Issue {              // grammarly-style находка
  id: string;
  paragraphId: number;
  criterionId: CriterionId;
  targetFragment: string;      // точный EN-спан для подсветки (анкор = левое вхождение в target)
  sourceFragment: string;      // соответствующий RU (контекст)
  explanation: string;
  suggestion: string;
  severity: Severity;
  mqmCategory: string | null;  // MQM-категория ошибки (напр. 'Accuracy/Mistranslation'); судья эмитит в tool-схеме
  status: IssueStatus;
}

interface Score {
  criterionId: CriterionId;
  value: number;               // в пределах [scaleMin, scaleMax]
  summary: string;
  // «текущий» = строка с максимальным created_at для (paragraphId, criterionId).
  // Версии не нумеруются — порядок определяет created_at.
}

// ───────── контрибьюшен 3: абзац и документ ─────────
interface Paragraph {
  id: number;
  idx: number;                  // порядок в документе
  source: string;               // RU (read-only)
  target: string;               // EN (редактируемый)
  scores: Score[];              // последняя версия на критерий
  scoresPrev: Score[] | null;   // предпоследняя на критерий → дельта «к прошлому шагу»
  scoresBaseline: Score[] | null; // самая первая (seed) на критерий → дельта «к оригиналу»
  aggregate: number | null;     // взвешенная сумма по enabled-критериям, ЗАМОРОЖЕНА на момент оценки
  aggregateBaseline: number | null; // взвешенная сумма на baseline
  issues: Issue[];              // только status='open' + те, что accepted/dismissed (для истории)
  terms: Term[];
}

interface DocumentSummary { id: number; title: string; sourceLang: string; targetLang: string; nParagraphs: number; }
interface Document extends DocumentSummary {
  sourceModel: string;
  aggregate: number | null;     // среднее paragraph.aggregate (на лету, из замороженных)
  paragraphs: Paragraph[];
}

// ───────── реестр моделей (роудмапа п.4) ─────────
// name = строка модели, уходящая в API ВЕРБАТИМ (демо сознательно схлопывает
// различение «ключ конфига vs имя модели» из старого пайплайна).
// params — ОТКРЫТЫЙ мешок: у разных LLM разные параметры (temperature, max_tokens,
// reasoning_effort, top_p, thinking, structured_output, ...). Уходит в
// LLMClient.complete(**params) как есть. Так гетерогенные модели не ломают контракт.
interface ModelRegistryEntry {       // тело POST/PUT (с ключом)
  name: string;        // PK = wire model id (e.g. "openai/gpt-5.5"); неизменяем на PUT
  baseUrl: string;     // https://openrouter.ai/api/v1
  apiKey: string;      // write-only — НИКОГДА не возвращается в GET
  params: Record<string, unknown>;   // моки: {temperature, max_tokens}; позже — реальные per-model
}
interface ModelRegistryEntryPublic {  // ответ GET (без ключа)
  name: string; baseUrl: string; apiKeyMasked: string; params: Record<string, unknown>;
}

// ответ POST /api/models/{name}/test — реальный зонд-вызов (тратит деньги)
interface TestModelResult {
  ok: boolean;                 // (нет ошибки) И share >= 0.5
  extracted: string[];         // сырые термины, как вернула модель
  reference: string[];         // нормализованные surface-формы seed-термина абзаца idx=1 (slash-split)
  matched: number;
  total: number;
  share: number;               // matched/total
  tokens: { prompt: number; completion: number; reasoning: number };
  costUsd: number | null;      // null если стоимость не пришла от провайдера
  latencyMs: number;
  message: string;             // 'ok' | причина ok=false (напр. 'budget', 'share below 0.5', текст ошибки)
}
```

## 2. REST API (frontend ↔ backend)

```
# чтение
GET    /api/documents                          -> DocumentSummary[]
GET    /api/documents/{id}                      -> Document

# редактирование перевода
PATCH  /api/paragraphs/{id}        {target}     -> Paragraph            # ручная правка, persist
POST   /api/documents/{id}/reset                -> Document             # вернуть документ к seed-состоянию (кнопка «сброс»)

# контрибьюшен 3 — цикл улучшения (ЕДИНСТВЕННЫЙ живой вызов LLM)
POST   /api/paragraphs/{id}/evaluate {criterionIds?}
       -> { scores: Score[], scoresPrev: Score[]|null, scoresBaseline: Score[]|null,
            aggregate: number, aggregateBaseline: number|null,
            issues: Issue[], failedCriterionIds: CriterionId[],
            cached: boolean, cachedAt: string|null, docVersion: number }
       # target из БД; полный «до/после» без второго GET; cached=true → отдан предрасчёт (preview, не персистится)
POST   /api/paragraphs/{id}/apply-edit {issueId}
       -> {target: string, issue: Issue, siblingIssues: Issue[]}        # 422 если фрагмент не найден или issue.status != 'open'
PATCH  /api/issues/{id}             {status: 'open'|'dismissed'}
       -> Issue | 404 | 409 (accepted) | 422 (invalid status)           # персист Dismiss/Undo; открыт, как и цикл evaluate/apply-edit

# контрибьюшен 2 — пул оценщиков (Settings)
GET    /api/criteria                            -> Criterion[]
POST   /api/criteria               {Criterion}  -> Criterion
PUT    /api/criteria/{id}          {Criterion}  -> Criterion            # id из тела игнорируется
DELETE /api/criteria/{id}                       -> 204 | 409            # 409 если есть скоры/issues; используй enabled=false

# роудмапа п.4 — пул LLM (Settings)
GET    /api/models                              -> ModelRegistryEntryPublic[]   # без apiKey
POST   /api/models                 {entry}      -> ModelRegistryEntryPublic
PUT    /api/models/{name}          {entry}      -> ModelRegistryEntryPublic     # name неизменяем; apiKey опущен = оставить прежний
DELETE /api/models/{name}                       -> 204 | 409
POST   /api/models/{name}/test  {effort?}       -> TestModelResult             # реальный вызов (тратит деньги); 404 только для неизвестного name

# контрибьюшен 1 — терминология (заполняет term-агент; роудмапа п.1,3)
POST   /api/paragraphs/{id}/terms               -> Term[]               # DELETE прежних term-строк абзаца → INSERT новых

# бюджет (guard над реальными LLM-вызовами)
GET    /api/budget                              -> {spentUsd, capUsd, calls, callCap}
POST   /api/budget/reset                        -> {spentUsd, capUsd, calls, callCap}   # открыт (admin-гейт удалён в wave-4)
```

**Аутентификация и секреты (демо-уровень):** ⚠️ **admin-гейт удалён в wave-4 (2026-07-03) — ВСЕ роуты открыты, настройки правит любой посетитель** (владелец так решил осознанно). `DEMO_ADMIN_TOKEN`, `_require_admin`, `GET /api/admin/check` и unlock-UI больше не существуют. `POST /api/models/{name}/test` тратит реальные деньги (живой вызов модели) — единственная защита трат теперь бюджет-cap. `apiKeyMasked` = **первые 4 символа + «…»** (НЕ суффикс — иначе утечёт хвост ключа). **`params`-мешок валидируется на запись:** ключи, матчащие `/api.?key|token|secret|password|auth/i`, отклоняются (иначе секрет, положенный в `params`, утечёт через `GET /api/models`). Шифрование ключей в БД не делаем (плейнтекст в SQLite на доверенном хосте достаточен).

**Параллельность `/evaluate`:** реализация ОБЯЗАНА звать LLM по критериям параллельно (`asyncio.gather`), а не последовательно — wall-time = самый медленный критерий (~8–12 с), не сумма.

## 3. Семантика цикла и персистентности (острые углы — зафиксировано)

- **Пересчёт `/evaluate`:** для каждого оценённого критерия — `DELETE` его `issue`-строк со `status='open'`, затем `INSERT` свежих (status='open'). Строки `accepted`/`dismissed` **не трогаются никогда** (принятые/отклонённые правки переживают пересчёт). Скоры — `INSERT` новой строки (старые остаются). Ответ возвращает свежие open-issues + последние scores + замороженный `aggregate`.
- **`/apply-edit`:** применяет `issue.suggestion`, заменяя **левое** вхождение `issue.targetFragment` в текущем `target`; ставит `issue.status='accepted'`; возвращает `{target, issue, siblingIssues}`. Если `targetFragment` отсутствует в текущем тексте → `422 {error:'fragment_not_found'}`, без мутаций. **Guard:** запрос обязан загрузить issue и проверить `status=='open'` ДО любой мутации — accept на уже `accepted`/`dismissed`/`outdated` issue → `422 {error:'not_open'}`, target и статус не трогаются (никакого повторного сплайса). Весь блок записи (UPDATE paragraph, UPDATE issue, цикл инвалидации соседей) — одна транзакция: исключение в середине цикла откатывает всё, частичная запись никогда не персистится.
- **«До/после»:** `scores` = max(created_at) на критерий; `scoresPrev` = предпоследняя; `scoresBaseline` = первая (seed). UI рисует прирост и «к прошлому шагу», и «к оригиналу» (заголовочное «8.4 → 9» — это `aggregate` vs `aggregateBaseline`).
- **Агрегат — один общий хелпер, всегда по ВСЕМ enabled-критериям:** `aggregate = Σ( norm(value)·weight ) / Σ weight`, `norm(value)=(value−scaleMin)/(scaleMax−scaleMin)` (показ ×10). Нормализация обязательна (шкалы критериев разные). **`seed.py` и `/evaluate` зовут ОДИН и тот же `compute_aggregate()`** — иначе baseline и latest несравнимы. При частичном/подмножественном `/evaluate` агрегат считается по ВСЕМ enabled-критериям, подставляя **последний доступный** score для не-переоценённых (а не по подмножеству). Заморожен в момент оценки; правка весов задним числом не меняет показанное «до».
- **Сравнимость наборов:** каждая оценка хранит `criteria_key` (отсортированные id enabled-критериев на момент оценки). UI сравнивает `criteria_key` baseline и latest; **различаются → бейдж «набор критериев изменился, дельта не сравнима»** (иначе прирост — артефакт включения/выключения критерия, а не качества).
- **Частичный сбой `/evaluate`:** упавший критерий отсутствует в `scores` и попадает в `failedCriterionIds` (явное поле ответа); HTTP 200.
- **Живой + кеш-фолбэк (решение владельца):** `/evaluate` идёт в LLM с таймаутом T (≈20 с). На этапе seed для показательных абзацев вставляются строки `kind='cache'` (ожидаемый результат после правок). При таймауте/сбое, если у абзаца есть `kind='cache'` — возвращаем его значения с `cached:true`, **НИЧЕГО не вставляя** в score/issue (read-only passthrough, «preview»). Cache-строки **исключены** из выбора «текущего»: `latest = max(created_at) WHERE kind IN ('seed','live')`. Так документ не открывается уже-улучшенным и cached-ответ не инвертирует дельту.
- **Reset (решение владельца):** `POST /api/documents/{id}/reset` удаляет score/issue-строки c `kind='live'` по документу и восстанавливает `paragraph.target = paragraph.seed_target` (immutable). Baseline (`kind='seed'`) и cache (`kind='cache'`) переживают. Reset также **принудительно реоткрывает** все `kind='seed'` issue-строки (`status='open'`), независимо от их предыдущего статуса — ранее dismissed seed-issue снова становится open после сброса. Возвращает свежий `Document`. Гонка с живым `/evaluate`: документ несёт `version`; `/evaluate` и `reset` его инкрементят; `reset` отдаёт `409`, если по документу есть незавершённый `/evaluate` (in-memory guard). 
- **`/apply-edit` цепочкой:** на `422 fragment_not_found` статус issue **НЕ меняется** (остаётся `open`), UI показывает ошибку «текст изменился — пересчитайте». Цепочка accept применяется в порядке `charStart` (меньше шанс сдвига фрагментов). При INSERT нового open-issue, если уже есть `accepted`/`dismissed` issue с тем же `(paragraphId, criterionId, targetFragment)` — новый **не вставляется** (без дублей-наложений на спан).
- **`POST /api/models/{name}/test` — зонд-вызов (роудмапа п.4):** `404` только для неизвестного `name`; любой другой исход — `200`. Отсутствие api-ключа/env, таймаут (общий `EVAL_TIMEOUT`≈20 с), ошибка API, ошибка парсинга JSON-ответа модели или блок бюджета — все дают `200 TestModelResult{ok:false, message:<причина>}` (та же философия, что у кеш-фолбэка `/evaluate`: неудачный реальный вызов — не 5xx). Модели даётся русский абзац `idx=1` с просьбой извлечь термины JSON-массивом; `reference` = нормализованные surface-формы seed `term`-строк этого абзаца (slash-split на составные формы вроде «марту/амурру»); `share = matched/total`; `ok = (нет ошибки) И share ≥ 0.5`. Реальный вызов идёт через `_client_for` + `LLMClient.complete`, под тем же бюджетным гардом (`budget.py`, жёсткий кап $2, pre-call резервирование), что и `/evaluate`.

## 4. SQLite-DDL

```sql
PRAGMA foreign_keys = ON;                  -- обязательно: SQLite иначе не проверяет FK

CREATE TABLE document (
  id INTEGER PRIMARY KEY, title TEXT, source_lang TEXT, target_lang TEXT,
  source_model TEXT, seed_model TEXT, seed_prompt_variant TEXT,   -- провенанс seed-скоров (для статьи)
  version INTEGER DEFAULT 0,                                       -- optimistic guard для evaluate/reset
  created_at TEXT
);
CREATE TABLE paragraph (
  id INTEGER PRIMARY KEY, document_id INTEGER REFERENCES document(id),
  idx INTEGER, source TEXT, target TEXT,
  seed_target TEXT                          -- immutable исходный перевод; reset восстанавливает target отсюда
);
CREATE TABLE score (                       -- «текущий» = max(created_at) WHERE kind IN ('seed','live')
  id INTEGER PRIMARY KEY, paragraph_id INTEGER REFERENCES paragraph(id),
  criterion_id TEXT REFERENCES criterion(id), value REAL, summary TEXT,
  aggregate REAL,                          -- замороженный агрегат абзаца (один хелпer для seed и /evaluate)
  criteria_key TEXT,                        -- отсортированные enabled criterion_id на момент оценки → сравнимость
  kind TEXT DEFAULT 'live',                 -- 'seed' | 'live' | 'cache'
  created_at TEXT
);
CREATE TABLE issue (
  id INTEGER PRIMARY KEY, paragraph_id INTEGER REFERENCES paragraph(id),
  criterion_id TEXT REFERENCES criterion(id), target_fragment TEXT, source_fragment TEXT,
  explanation TEXT, suggestion TEXT, severity TEXT, mqm_category TEXT,
  status TEXT DEFAULT 'open', kind TEXT DEFAULT 'live', created_at TEXT
);
CREATE TABLE term (                        -- заполняет term-агент; до него — моки
  id INTEGER PRIMARY KEY, paragraph_id INTEGER REFERENCES paragraph(id),
  source_surface TEXT, source_lemma TEXT, char_start INTEGER, char_end INTEGER,
  difficulty TEXT,                         -- green|yellow|red (грундинг)
  grounded_json TEXT, candidates_json TEXT,
  target_surface TEXT, pair_accuracy TEXT, -- green|yellow|red|NULL (пара; NULL при difficulty=red)
  recommended TEXT, note TEXT,
  trace_json TEXT NOT NULL DEFAULT '{}',   -- GroundingTrace v1 (G6), полный лог решения граундинга
  UNIQUE (paragraph_id, char_start, char_end)   -- защита от дублей при ре-грундинге
);
CREATE TABLE criterion (
  id TEXT PRIMARY KEY, name TEXT, model_name TEXT REFERENCES model(name),
  prompt TEXT, scale_min REAL, scale_max REAL, weight REAL, color TEXT, enabled INTEGER
);
CREATE TABLE model (
  name TEXT PRIMARY KEY, base_url TEXT, api_key TEXT, params_json TEXT   -- открытый мешок per-model
);
CREATE TABLE glossary (                    -- store term-агента; ключ дизамбигуации = context, НЕ тип
  id INTEGER PRIMARY KEY, term TEXT, context TEXT, target_equivalent TEXT,
  wikidata_url TEXT NOT NULL,              -- ссылка на узел — обязательна
  wikidata_id TEXT,                        -- QID — опционально
  UNIQUE (term, context)                   -- много записей на один term, различает context
);
CREATE TABLE grounding_config (            -- singleton (G6): judge-модель + промпт + params, зеркало NerConfig
  id INTEGER PRIMARY KEY CHECK (id = 1),
  model_name TEXT REFERENCES model(name),
  prompt TEXT,
  params_json TEXT
);
```

`criterion_id`/`model_name` — FK с `ON DELETE RESTRICT` (по умолчанию): удалить критерий/модель, на которые ссылается история, нельзя — вернётся 409, прячь через `enabled=false`. `id`/`name` неизменяемы (rename = пересоздание не поддерживаем). Запуск: `uvicorn app:app --workers 1` (SQLite — один писатель).

## 5. Контракт term-агента (граница интеграции)

На вход `{paragraphId, source(RU), target(EN)}`, на выход `Term[]` ровно по типу §1 — файлом `term_pairs.json` для seed или ответом `POST /terms`. Правила:
- Одна `Term`-строка на **каждое вхождение** термина (свои `charStart/charEnd`, свой `targetSurface`/`pairAccuracy`).
- При `difficulty='red'` → `grounded=null`, `pairAccuracy=null`, `recommended=null`.
- **Амендмент (G6, 2026-07-03):** `difficulty='yellow'` с `resolved_by='judge_unavailable'` тоже даёт `grounded=null` — задокументированное расширение правила «red → null», не нарушение. Причина: judge был недоступен на эскалации, QID честно не выбран, но difficulty остаётся 🟡 (путь дошёл до эскалации, а не оборвался на пустых кандидатах). Фронтовые truthiness-проверки вида `term.grounded && …` трактуют `null` как «нет узла» независимо от `difficulty` — ветку `yellow`+`grounded=null` не нужно отличать от `red` на уровне рендера.
- Агент предполагает RU-источник (морфология `sourceLemma`); другая пара языков — вне scope демо.
- Фронт/бэкенд демо в его внутренности не лезут — только этот тип.

**Глоссарий term-агента** (его knowledge store; формат по аналогии с KD-MT, EMNLP 2024 — дизамбигуация по контексту, а не по типу):

```ts
interface GlossaryEntry {
  term: string;             // RU лемма/поверхность
  context: string;          // фраза-контекст, различающая смысл — КЛЮЧ (омонимы И однофамильцы)
  targetEquivalent: string; // EN-эквивалент именно для этого контекста
  wikidataUrl: string;      // ссылка на узел Wikidata — ОБЯЗАТЕЛЬНА
  wikidataId: string | null;// QID узла (напр. "Q35355") — опционально
}
```

Много записей на один `term`, различает их `context`. Матчинг в абзаце: найти термин → выбрать запись с наиболее близким `context` к предложению → её `targetEquivalent`/`wikidata` дают `difficulty`/`pairAccuracy`/`recommended` для `Term`. Этот же store — **backbone согласованности между абзацами и документами**: одинаковый (`term`,`context`) → одинаковый эквивалент везде.

**Детерминированность (заявка статьи «детерминированная терминология»):**
- Метод ретрива по `context` — назвать до реализации term-агента: косинус по dense-эмбеддингам контекста ИЛИ BM25; порог `θ`: `max_sim < θ` → `difficulty='yellow'` (неоднозначно) **независимо от числа кандидатов** — закрывает однофамильцев с бедным контекстом без ложного 🟢. Тай-брейк при равенстве — детерминированный (напр. по `qid`). *(Точную формулу из KD-MT, EMNLP 2024, зафиксируем при сборке term-агента; могу поднять статью веб-поиском для строгого соответствия.)*
- Term-агент = LLM; механизм идемпотентности: `temperature=0` + structured output, результат на пару (`term`,`context`) кешируется в `glossary` (источник истины — БД, не повторный вызов LLM). *(Формулировка заявки для статьи — «детерминированная» vs «grounded/verifiable» — открыта, форк #1.)*
- **Scope:** сам term-агент (роудмапа п.1, п.3) — **вне объёма первой сборки демо**; контрибьюшен 1 показываем на моках/seed за контрактом `Term`/`GlossaryEntry`. Эти правила — ТЗ агенту на потом.

## 6. Маппинг на подсветку UI

| Сигнал | Где рисуется | Источник |
|---|---|---|
| `Term.difficulty` 🟢🟡🔴 | на RU-слове (`sourceSurface` по `charStart/charEnd`) | грундинг Wikidata |
| `Term.pairAccuracy` 🟢🟡🔴 | на паре RU↔EN; ховер связывает | точность перевода |
| `Term` с `targetSurface=null` | только RU-бейдж (difficulty); EN-спан не рисуется, тултип «термин отсутствует в переводе» | — |
| `targetSurface` не найден в текущем `target` (после правки) | EN-половина подсветки гасится, RU-бейдж остаётся; авто-ре-грундинг НЕ запускается | — |
| `Issue` (критерий) | EN-спан `targetFragment`, стопкой при пересечении | LLM-as-judge |

Критерии — холодная палитра; 🟢🟡🔴 только у терминологии. В текущем прототипе Variant A термин имеет один `verdict` — при переходе на этот контракт UI разводит его на два сигнала (правка фронта, не контракта).

**Анкеринг EN-спанов (решение расхождения ревью):** RU-сторона якорится по `charStart/charEnd` (source read-only, стабильно). EN-сторона (`targetSurface` у `Term`, `targetFragment` у `Issue`) якорится **поиском левого вхождения подстроки в текущем `target`** — offset-полей для EN НЕ храним (target редактируемый, они бы устаревали). «Устарел» = подстрока не найдена → EN-половина гасится. Это согласовано с правилом левого вхождения в `/apply-edit`. (Aspect-6 предлагал `targetCharStart/End`; отклонено — поиск по подстроке проще и не устаревает; при повторах берём левое, как в `/apply-edit`.)

**UX статусов issue (aspect-6):** `accepted`/`dismissed` issue в инспекторе — зачёркнут, в EN-панели не подсвечивается, переживает пересчёт. `targetSurface=null` — только RU-бейдж, ховер без EN-пары. Стабильные `data-testid` для шага-8 — в плане (инвентарь UI-поверхностей), не в контракте данных.

## Changelog ревизии 2 (после адверсариального ревью)

Адверсариальный разбор: 5 оптик × критика + скептик-верификация (28 находок выжило). Применено:
- **Issue-идентичность при пересчёте** (§3): пересчёт удаляет только open-issues, accepted/dismissed переживают; `created_at` добавлен.
- **Скоры без `version`** (§1,§4): «текущий» = max(created_at); добавлены `scoresPrev`/`scoresBaseline` (дельта к шагу и к оригиналу).
- **Документный агрегат** (§1,§3): `aggregate`/`aggregateBaseline`, заморожен бэкендом — правка весов не ломает «до».
- **FK-целостность** (§4): `criterion_id`/`model_name` → REFERENCES + PRAGMA; DELETE → 409; PK неизменяемы.
- **Терминология edge-cases** (§1,§5,§6): `pairAccuracy: Verdict|null` (null при red); правила рендера для `targetSurface=null` и устаревшего спана; строка-на-вхождение.
- **Безопасность** (§1,§2): apiKey убран из GET (`ModelRegistryEntryPublic`); опциональный bearer на мутации конфига.
- **API-надёжность** (§2,§3): убран `target?` у `/evaluate` (читает БД); `/apply-edit` → 422 + левое вхождение, возвращает `issue`; частичный сбой = 200 без упавшего критерия; параллельный `asyncio.gather`; `--workers 1`.
- **Реестр моделей** (§1): добавлен `maxTokens`; `name` = wire-id.

**Отклонено как оверинжиниринг/мимо:** двойной учёт «терминология-критерий vs Wikidata-слой» (граница уже закрыта решением); запрет non-empty `candidates` на green (комментарий достаточен); расхождение с `TermPair` старого прототипа (его в дереве нет); поле `version` контракта; отдельный MQM-эндпоинт (это деталь схемы вывода судьи, не API).

**Решения владельца (3 критичных, подтверждены):** (1) **живой `/evaluate` + кеш-фолбэк** для seed-абзацев → `cached:boolean` + таймаут T; (2) **сброс к seed кнопкой** → `POST /api/documents/{id}/reset` (общее состояние, не изоляция по сессии); (3) **два сигнала терминологии** (`difficulty` + `pairAccuracy`) — подтверждено.

**Ревизия 3 (тонкости домена):** (a) **LLM-параметры** → открытый `params: Record<string,unknown>` вместо плоских `temperature`/`maxTokens` (у разных моделей разные параметры; уходит в `complete(**params)`); (b) **глоссарий** — формат `GlossaryEntry{term, context, targetEquivalent, wikidata}`, дизамбигуация по контексту (KD-MT), не по типу; покрывает омонимы и однофамильцев; `Term.context` добавлен, `domain`-как-ключ убран; (c) **агрегат нормирован** по шкале каждого критерия перед взвешиванием (разные шкалы несравнимы сырыми).

**Ревизия 4 (после `/verify-spec`, 5 аспектов):** закрыты CRITICAL/HIGH механики: (a) **агрегат** — один `compute_aggregate()` для seed и `/evaluate`, всегда по ВСЕМ enabled (подстановка последнего score), `criteria_key` для сравнимости baseline/latest; (b) **кеш-фолбэк** — `kind='cache'` строки, read-only passthrough, исключены из «текущего» (нет фантомного прироста/инверсии дельты); (c) **reset** — `kind!='seed'` удаляется, `paragraph.seed_target` восстанавливается, `document.version` + 409 при гонке с `/evaluate`; (d) **`/evaluate` ответ** — полный «до/после» (`scoresPrev`/`scoresBaseline`/`aggregateBaseline`) + `failedCriterionIds`/`cachedAt`; (e) **анкер EN** — поиск левого вхождения, без offset-полей (разрешение расхождения ревью); (f) **секреты** — валидация `params` от secret-ключей, формат `apiKeyMasked` (префикс); (g) **MQM** — `Issue.mqmCategory`; (h) **детерминированность глоссария** — назван метод+порог+temp=0+кеш; (i) провенанс seed (`seed_model`/`seed_prompt_variant`); apply-edit цепочка/дедуп.

## Статус и гейт

Ревизия 4. Механические CRITICAL/HIGH из verify-spec закрыты. Решения владельца: **#4 — курируемый срез ~15–20 показательных абзацев + опц. второй документ для A/B** (принято); глоссарий — `wikidataUrl` обязателен, `wikidataId` опционален (принято). **#1** (формулировка «детерминированность»), **#2** (сила MQM-заявки), **#3** (семантика судейского `terminology` vs `pairAccuracy`), **#5** (деплой) — **оставлены открытыми** (research/paper/scope), НЕ блокируют сборку сайта. **Гейт пройден → автономная реализация** (`writing-plans` → ветка `feat/demo` → execute).
