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
type IssueStatus = 'open' | 'accepted' | 'dismissed' | 'outdated';  // rev-5: 'outdated' — сосед, перекрытый чужим apply-edit (§3, webapp.md "Issue lifecycle"). Backend-only 'superseded'/'archived' НЕ входят сюда: _para_issues их всегда отфильтровывает, на wire они не попадают (webapp.md prediction-preservation invariant)
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
  traceJson: Record<string, unknown>; // rev-5: parsed `term.trace_json` — полный лог решения граундинга (GroundingTrace v1, §4); '{}' пока не проставлено enrichment-скриптом/трейсом
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
  issues: Issue[];              // status='open' + accepted/dismissed/outdated (для истории; rev-5 добавил outdated) — superseded/archived никогда не доходят до wire, см. _para_issues
  terms: Term[];
  best: { aggregate: number; revisionId: number; createdAt: string; isCurrent: boolean } | null;  // rev-5 (score-history-best): argmax(aggregate) среди kind IN ('seed','live') с non-null revision_id; null пока нет ни одной оценённой ревизии
}

interface DocumentSummary {
  id: number; title: string; sourceLang: string; targetLang: string; nParagraphs: number;
  origin: 'seed' | 'upload';    // предшествует rev-5, но не был занесён сюда раньше (app.py сериализует с самого начала) — backfilled по итогам doc-audit 2026-07-07
}
interface Document extends DocumentSummary {
  sourceModel: string;
  aggregate: number | null;     // среднее paragraph.aggregate (на лету, из замороженных)
  paragraphs: Paragraph[];
  precompute: { status: 'running' | 'done' | 'stopped' | 'skipped'; done: number; planned: number; succeeded: number; errorReason?: 'no_api_key' | 'budget_exhausted' | 'all_failed' } | null;  // rev-4 (custom-pair-upload); присутствует для origin='upload', null для origin='seed'
  translation: { status: 'running' | 'done' | 'failed'; done: number; total: number; errorReason?: 'no_api_key' | 'budget_exhausted' | 'all_failed' } | null;  // rev-5 (translator): присутствует, когда присутствует precompute (т.е. origin='upload'); зеркалит форму precompute
  termsStatus: 'none' | 'running' | 'done' | 'failed';  // 2026-07-11 (live terminology, см. дельту внизу файла): присутствует ДЛЯ ВСЕХ документов (в т.ч. origin='seed', там всегда 'done') — в отличие от precompute/translation это колонка БД (document.terms_status), не in-memory реестр
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
  effectiveParams: Record<string, unknown>;   // rev-5: params.for_model() output — what ACTUALLY goes into the call
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

На вход `{paragraphId, source(RU), target(EN)}`, на выход `Term[]` ровно по типу §1 — файлом `data/seed/terminology_out.json` для seed (§1 `Term`-строки, `scripts/load_terms.py`) или, с 2026-07-11, автоматически в фоне при создании документа (`webapp/terminology_live.py`, DELETE прежних term-строк абзаца → INSERT новых; см. дельту внизу файла) — `POST /paragraphs/{id}/terms` как отдельный REST-канал удалён (был stub без вызовов с фронта). Правила:
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

## 7. Rev-5 delta (2026-07-05, wave-5 — settings-fixes / translator / score-history-best / export-xlsx / upload-modal-polish)

Реализовано в ветке `claude/emlp-2026-website-fixes-muih1x`. Полные спеки: [2026-07-05-settings-fixes.md](2026-07-05-settings-fixes.md), [2026-07-05-translator.md](2026-07-05-translator.md), [2026-07-05-score-history-best.md](2026-07-05-score-history-best.md), [2026-07-05-export-xlsx.md](2026-07-05-export-xlsx.md), [2026-07-05-upload-modal-polish.md](2026-07-05-upload-modal-polish.md). Все новые многословные wire-поля — **camelCase**, для консистентности с остальным контрактом (спеки местами писали `error_reason`/`effective_params` snake_case как русскоязычное сокращение — не буквальное имя поля).

### 7.1 Новые таблицы (DDL)

```sql
CREATE TABLE target_revision (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  paragraph_id INTEGER REFERENCES paragraph(id) ON DELETE CASCADE,
  text TEXT NOT NULL,
  origin TEXT NOT NULL,            -- 'seed' | 'upload' | 'edit' | 'apply_edit' | 'translate' | 'restore'
  created_at TEXT NOT NULL
);
CREATE INDEX idx_target_revision_para ON target_revision(paragraph_id, id);

CREATE TABLE translator_config (   -- singleton, mirrors grounding_config
  id INTEGER PRIMARY KEY CHECK (id = 1),
  model_name TEXT REFERENCES model(name),
  prompt TEXT,
  params_json TEXT
);
```

`score` gains `revision_id INTEGER REFERENCES target_revision(id)` (nullable — historical pre-rev-5 rows stay `NULL`, honestly; never backfilled). Stamped at all three INSERT sites: `/evaluate`, `precompute._write_paragraph`, `seed.py`.

**Migration:** `src/palimpsest/webapp/migrate.py::migrate(conn)` — additive, idempotent (`CREATE TABLE IF NOT EXISTS` ×2, guarded `ALTER TABLE score ADD COLUMN revision_id`, seeds `translator_config`'s default row only if its FK-target model already exists, backfills one `origin='seed'` revision per paragraph that has none). Runs on app startup (FastAPI lifespan, before serving) and via `python -m palimpsest.webapp.migrate`. `db.py::SCHEMA` carries the same DDL unconditionally for fresh DBs.

### 7.2 New/changed REST

```
# revision history (score-history-best)
GET  /api/paragraphs/{pid}/revisions
     -> { revisions: [{id, origin, createdAt, text, aggregate: number|null, isBest, isCurrent}] }  # newest first
POST /api/paragraphs/{pid}/restore {revisionId}
     -> Paragraph                  # 404 unknown revision; 409 revision belongs to another paragraph

# translator (S4)
GET  /api/translator-config                     -> {modelName, prompt, params}       # mirrors grounding-config
PUT  /api/translator-config      {same shape}    -> {modelName, prompt, params}       # params: whitelist §7.4
POST /api/documents/{doc_id}/translate           -> 202 {status:'started', total}
     # 403 seed_document; 409 translation_in_progress; 409 {detail:'no_api_key'|'budget_exhausted'} (pre-check)

# export (S6)
GET  /api/documents/{doc_id}/export?format=xlsx|md  -> file (Content-Disposition: attachment)
     # 200 xlsx: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet
     # 200 md:   text/markdown; charset=utf-8
     # 404 unknown document; 422 unknown format

# health limits (S3 §2.3)
GET  /api/health -> {service, status, limits: {maxParagraphs, maxParaChars}}
```

`POST /api/documents` body gains an optional `translate: boolean` (default `false`):
- `translate:true` ⇒ every `paragraphs[].target` MUST be empty (`""`) — a non-empty target on ANY paragraph → `422 {detail:'mixed_targets'}`. Server FORCES `precompute:false` regardless of the body's `precompute` value (translating into empty targets must never trigger a paid judge pass over garbage).
- `translate:true` documents get `target=seed_target=''` at creation; the first `target_revision` (`origin='upload'`) is written once translate.py actually fills a paragraph in (`origin='translate'`), not at creation time.
- Document DTO gains a `translation` block (present whenever `precompute` is, i.e. `origin==='upload'`): `{status:'running'|'done'|'failed', done, total, errorReason?}`, mirroring `precompute`'s shape. (`precompute` itself predates rev-5 — rev-4 custom-pair-upload — and, like `origin` below, was never added to §1's `Document` interface until the 2026-07-07 doc-audit backfill.)
- **Pre-existing gap surfaced by this delta — RESOLVED 2026-07-07 doc-audit.** `document.origin: 'seed'|'upload'` (used above and by `DELETE`/`/reset`/`/translate`'s 403/409 gates) predates rev-5 but was never added to the §1 `DocumentSummary`/`Document` interfaces or the §4 `document` DDL — `app.py` has always serialized it (`"origin": d["origin"]`) and [webapp.md](../../subsystems/webapp.md) documents the column, but this SSOT doc did not. Was flagged here without backfilling (out of the rev-5 delta's own scope); the 2026-07-07 doc-audit closed the gap by adding `origin` to §1 `DocumentSummary` directly, with a comment noting it predates rev-5. Same audit also backfilled §1 with `Paragraph.best`, `Document.precompute`/`translation`, and `IssueStatus`'s `'outdated'` member (all documented by name below/above but previously absent from the §1 interfaces themselves) — chosen treatment: **backfill §1 with an inline rev-tag comment per field**, consistent with how `Term.traceJson` was already handled (§7.2 note below), rather than leaving every non-rev-2 field as §7-prose-only.

`GET /api/documents/{id}` paragraph DTO gains `best: {aggregate, revisionId, createdAt, isCurrent} | null` — the highest-`aggregate` scored revision (`kind IN ('seed','live')` only, `kind='cache'` excluded, tie-break newest); `null` if the paragraph has no scored revision yet. (Backfilled into the §1 `Paragraph` interface — see above.)

`precompute`/`translation` status blocks gain an optional `errorReason: 'no_api_key'|'budget_exhausted'|'all_failed'` — set when `done && succeeded===0` (precompute) or the run terminates with zero translated paragraphs (translate), so the frontend can show *why* instead of a bare unexplained banner.

`GET /api/models` gains `effectiveParams: Record<string,unknown>` per row — `ModelParams.for_model()`'s output, i.e. what the capability filter actually sends to the provider (vs. raw `params`, which is whatever was saved).

`PUT /api/models/{name}` `apiKey` semantics changed from a falsy-check to a **presence-check**: `apiKey` absent from the body ⇒ keep the existing key (unchanged); `apiKey` present (including `""`) ⇒ use it verbatim, so `{apiKey: ""}` now explicitly clears a previously-set key. Previously an empty string was indistinguishable from "omitted" and silently kept the old key (known_issues.md, now resolved).

**`Term.traceJson` (rev-5, corrected 2026-07-06).** [2026-07-05-glossary-redesign-impl.md §4](2026-07-05-glossary-redesign-impl.md) required `_term_dict` to add a `traceJson: Record<string,unknown>` field (parsed `term.trace_json`) to the §1 `Term` interface, to drive the Glossary tab's grounding-path stepper. An earlier revision of this doc claimed this was never done — that was **wrong**: `_term_dict` (`app.py`) does emit `"traceJson": json.loads(r["trace_json"]) if r["trace_json"] else {}` (commit `7f3b56a`, covered by `tests/test_term_dict.py::test_trace_json_serialized_as_parsed_object`), and the `Term` interface above now lists it. The stale "not implemented" note and its `known_issues.md` counterpart were doc-only drift (the code had already shipped the field in the same commit that added the note) — see the 2026-07-06 doc-parity audit report for the full finding. Note frontend `api-client.ts`'s own `Term` interface still does not declare `traceJson` (only the `TermWithTrace` intersection type in `glossary-grouping.ts` does) — a follow-up for whoever next touches that file, not a wire/backend gap.

### 7.3 `_client_for` gains an explicit params override

`app._client_for(conn, model_name, params_override: dict | None = None)` — when `params_override` is given, it REPLACES the model registry row's own `params_json` entirely (used by `translate.py` for `translator_config` params and by `_grounding_judge_live` for `grounding_config` params). Without a caller-supplied override, behavior is unchanged (the model's own row). This also fixes a pre-existing bug where `_grounding_judge_live` computed its budget *estimate* from `grounding_config.params_json` but built its actual `LLMClient` from the model row's own params — the grounding call's configured `max_tokens`/`temperature` were silently ignored (see [known_issues.md](../../known_issues.md)).

### 7.4 Params whitelist (S1 §2.4)

`POST/PUT /api/models`, `PUT /api/grounding-config`, `PUT /api/translator-config` all validate `params` against a fixed key whitelist before the existing secret-key guard's complement: `max_tokens` (int 1..32768), `temperature` (0..2), `top_p` (0..1), `top_k` (int), `min_p` (number), `seed` (int), `enable_thinking` (bool), `reasoning` (`{effort: low|medium|high}` and/or `{max_tokens: int>=0}`). An unrecognized key → `422 {"detail": "unknown param: <key>"}` — previously an unknown key was silently saved then silently dropped downstream by `ModelParams`'s `extra="ignore"`. The pre-existing secret-key guard (`400`) still runs first, since a key can be both secret-like AND off-whitelist (e.g. `api_key`).

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

**Ревизия 5 (2026-07-05, wave-5):** дельта в § 7 выше — `target_revision`/`translator_config` таблицы + `score.revision_id`, ревизии/best-выбор, translate-фича, экспорт xlsx/md, params-whitelist + `effectiveParams`, `apiKey`-presence-check, `error_reason` в precompute/translation, `/api/health` limits. Реализовано и покрыто тестами backend-веткой этой волны; doc-parity в [webapp.md](../../subsystems/webapp.md) и [known_issues.md](../../known_issues.md) обновлена в том же коммите.

## Live terminology delta (2026-07-11, EMNLP-demo sprint — lane B2)

Отдельная секция (не переиспользует нумерацию §7/«ревизия N» во избежание коллизии редактирования с параллельной дельтой критериев/моделей/refiner той же спринт-волны — см. lane B1). Полная реализация: `src/palimpsest/webapp/terminology_live.py`; поведенческие детали (launch-точки, sync/async-мост к живому судье, бюджет) — [webapp.md § Live terminology](../../subsystems/webapp.md#live-terminology); семантика grounding/pairing (переиспользуется без изменений) — [terminology.md § Live trigger](../../stages/terminology.md).

**Что изменилось в контракте:**
- **`Document.termsStatus: 'none'|'running'|'done'|'failed'`** добавлено в §1 `Document` (инлайн-коммент выше) — присутствует для ВСЕХ документов (в т.ч. `origin='seed'` → всегда `'done'`, миграцией). В отличие от `precompute`/`translation` это колонка БД (`document.terms_status`, `db.py::SCHEMA` + `migrate.py`), не in-memory реестр — переживает рестарт процесса.
- **`POST /api/paragraphs/{id}/terms` удалён** (§2, §5) — был stub (`SELECT`-passthrough, ноль вызовов с фронта). `Term[]` абзаца теперь заполняется автоматически: (a) для документов без `translate` — сразу после создания (таргеты уже есть); (b) для `translate:true` — по завершении фонового перевода (`translate.py`'s `_run` получил опциональный `terms_launch` колбэк), чтобы pairing видел финальный, а не пустой, target. Сид-документ никогда не запускается этим путём — у него уже есть precomputed термины (`scripts/load_terms.py`), и миграция ставит `terms_status='done'` явно.
- **`app._grounding_judge_live` теперь реально вызывается** (раньше — мёртвый код с пустым system-сообщением, TODO "no caller in the webapp yet"): шлёт `DEFAULT_GROUNDING_JUDGE_SYSTEM_PROMPT` как system, budget reserve/settle без изменений.

**Что НЕ реализовано этой дельтой (честно, не заявляем больше сделанного):** §5's «глоссарий term-агента» — персистентный `glossary`-стол как **backbone согласованности между документами** (одинаковый `(term, context)` → одинаковый эквивалент везде, dense-embedding/BM25 ретрив) — не построен. Живой пайплайн переиспользует существующие `LabelFirstGrounding`/`LinkLocatePairing` как есть; согласованность решений судьи — только **в пределах одного документа** (`judge_cache`, "one sense per discourse", scope_id=doc_id), не через документы. Также не реализовано: `DELETE /api/documents/{doc_id}` не отменяет уже запущенный `terminology_live`-таск (precompute/translate это умеют через свои `cancel()`; для terms — не подключено, задел на будущее).

## Criteria, model registry & refiner delta (2026-07-11, EMNLP-demo sprint — lane B1)

Separate top-level section (not §7/"ревизия N" numbering, same reasoning as the Live terminology delta above — avoids an edit collision with the parallel lane B2 delta in the same sprint wave). Written in English per this task's explicit instruction (project convention is normally Russian prose for this doc; English here is intentional, not drift). Full implementation: `model_matrix.py`, `seed.py`, `migrate.py`, `app.py` (refiner-config CRUD + `/refine`), `prompts/refiner/default.md`.

### Criteria set: 5 → 3

The judge-criterion set collapses to `{accuracy, fluency, style}`. `terminology` (the LLM-judge scoring dimension — **not** the separate Wikidata term-grounding pipeline in §1's `Term`/lane B2's live-terminology delta, which is untouched) and the already-disabled legacy `cultural` row both retire. Weights move from `accuracy 0.30 / fluency 0.20 / style 0.15 (+ terminology 0.20)` to `accuracy 0.40 / fluency 0.30 / style 0.30`; colors for the 3 survivors are unchanged. `prompts/scoring/terminology.md` is deleted (accuracy/fluency/style prompt files are unchanged).

**Migration (prod data, never deletes predictions):** `score`/`issue` rows for the two retired criterion ids move to `kind='archived'` / `status='archived'` respectively — **not** `dismissed`: `_para_issues` (app.py) unconditionally drops `archived` on every branch, while `dismissed` is still surfaced as inspector history (would leak a dangling `criterionId` once the criterion row is gone) — verified against `_para_issues`'s status handling and this doc's own §1 `IssueStatus` note before picking it. Only then are the two criterion rows deleted (FK from `score`/`issue`.`criterion_id` is default `ON DELETE NO ACTION`, so the migration step scopes `PRAGMA foreign_keys=OFF` around just the `DELETE`, committing immediately before/after to dodge SQLite's "no-op while a transaction is open" pragma behavior). Every surviving `score` row's frozen `aggregate`/`criteria_key` is recomputed over the 3 remaining criteria (`seed`/`cache`: one pass per paragraph; `live`: replayed in `created_at` order, carrying the latest per-criterion value forward pass-to-pass — the same carry-forward `POST /evaluate` itself uses), so `criteria_key` reads `"accuracy,fluency,style"` uniformly and no stale "criterion set changed" badge appears post-migration. A criterion's weight is migrated old-default→new-default only when it still carries the *old* default value — an owner customization via `PUT /api/criteria/{id}` is left alone.

### Model registry: 8 → 5 (paper models)

`model_matrix.MATRIX` becomes exactly 5 rows (was 8): `qwen/qwen3.6-27b` (OpenRouter — new default everywhere), `google/gemma-3-27b-it` (OpenRouter), `TranslateGemma-27B` (local vLLM placeholder, `http://localhost:8001/v1`, display-only — replaces the old `Qwen/Qwen3.6-27B`/`Infomaniak-AI/vllm-translategemma-27b-it` placeholder rows), `deepseek/deepseek-v4-flash` (OpenRouter), `google/gemini-3.1-flash-lite` (OpenRouter). All 4 OpenRouter ids verified live against `GET https://openrouter.ai/api/v1/models` (public, no key) on 2026-07-11 — `qwen/qwen3.6-27b` exists exactly as expected (no fallback substitution needed). Capability flags (`supports_temperature`/`top_k`/`min_p`/`seed`/`reasoning` kind) cross-checked against that same fetch's `supported_parameters` per model; the one deliberate non-metadata call is Gemini's `supports_temperature=False`, carried over from the retired `gemini-3.5-flash` row's empirical finding (an obligatory-reasoning Gemini route ignores temperature in practice) rather than the raw schema, which does list `temperature` as accepted.

`seed.py` now seeds all 5 rows **unconditionally** — the `PALIMPSEST_SEED_DEMO` env flag no longer branches model seeding (the flag itself is unused dead config now; `docs/subsystems/webapp.md`'s description of it is stale pending a docs-keeper pass, flagged not fixed by this delta). `DEFAULT_CRITERION_MODEL` moves from `openai/gpt-5.4-mini` to `qwen/qwen3.6-27b`.

**Migration (prod data):** `_upsert_model_registry_and_remap` runs FIRST in `migrate()` — `INSERT OR IGNORE`s the 5 new rows (never clobbers an owner-edited `api_key`/`params` on a re-run) and repoints every `criterion.model_name` to the new default. `translator_config`/`grounding_config`/`refiner_config.model_name` are repointed the same way once their tables are guaranteed to exist. The 8 obsolete model rows are then deleted (config, not predictions — deletion is fine here, unlike `score`/`issue`) once nothing still references them; a defensive re-check skips (rather than raising) any row a future caller might still reference.

### New: refiner role

Paper: *"a dedicated refiner LLM integrates aggregated corrections in a single pass."* A new singleton config table mirrors `translator_config`/`grounding_config` exactly, plus a paragraph-level action endpoint.

```sql
CREATE TABLE refiner_config (   -- singleton, mirrors translator_config
  id INTEGER PRIMARY KEY CHECK (id = 1),
  model_name TEXT REFERENCES model(name),
  prompt TEXT,
  params_json TEXT
);
```

```ts
interface RefinerConfig { modelName: string | null; prompt: string; params: Record<string, unknown>; }
```

```
GET  /api/refiner-config                        -> RefinerConfig       # mirrors translator/grounding-config
PUT  /api/refiner-config      {RefinerConfig}    -> RefinerConfig       # params: whitelist §7.4 (unchanged)

POST /api/paragraphs/{pid}/refine
     -> Paragraph   # fresh target + gathered open issues flipped to 'accepted', new
                     # target_revision(origin='refine'); scores/aggregate on the response
                     # are the PRE-refine values — refine never writes a `score` row, the
                     # caller (frontend) chains a real /evaluate right after.
     # 404 unknown paragraph
     # 409 {detail:'no_open_issues', message} — the ONLY status the frontend treats as a
     #     silent no-banner outcome (api-client.ts refineParagraph / store.ts's refine
     #     action already gate the button on activeIssueCount>0)
     # 503 'translation_in_progress' | 'no_api_key' — precondition, nothing attempted/billed
     # 429 'budget_exhausted' — budget.reserve() tripped before any network call
     # 502 {detail:'refine_failed', error} — the LLM call itself failed after one transient
     #     retry, or returned empty/whitespace output; nothing is mutated on this path
```

**Default refiner prompt** (`prompts/refiner/default.md`, DB-stored like the translator's, live-read at call time): *"You are an expert translation editor. You receive a source paragraph, its current translation, and a numbered list of reviewer findings (source fragment, problematic translation fragment, explanation, suggested correction). Rewrite the translation as a single improved version: apply every valid suggestion; resolve overlapping or contradictory suggestions in favor of fidelity to the source; keep the current translation's wording wherever no finding applies; do not add information, omit content, or shift style. Output ONLY the revised translation text — no commentary, no quotes, no markup."* Default params: `{"max_tokens": 2048, "temperature": 0.2}`.

**Call semantics:** findings = the paragraph's `status='open'` issues across ALL criteria — the same set `_para_issues` (app.py) surfaces to the inspector, filtered to `open` (accepted/dismissed/outdated history is not re-litigated). Budget reserve/settle + `REFINE_TIMEOUT=60s` + one transient retry mirror the `_judge_live`/`_evaluate` pattern; unlike `/evaluate`, there is **no cache fallback**. On success, in one transaction: `paragraph.target` updated, every gathered finding's `issue.status` set to `'accepted'` (re-checked `AND status='open'` at write time — a TOCTOU guard against a concurrent human dismiss/accept during the LLM call), `target_revision(origin='refine')` written. Model output is defensively stripped of an accidental ```` ``` ````-fence and one layer of wrapping quotes before being accepted; empty/whitespace-only output is rejected as a `502` failure, never written.

**Response-shape note (deliberate, verified against the already-shipped frontend, not a guess):** unlike `/apply-edit`'s `{target, issue, siblingIssues}` shape, `/refine` returns the **full** `Paragraph` dict (`_para_dict`) — matching `api-client.ts`'s `refineParagraph(): Promise<Paragraph>` and `store.ts`'s merge (`{...p, ...updated}`), which already shipped ahead of this backend work.
