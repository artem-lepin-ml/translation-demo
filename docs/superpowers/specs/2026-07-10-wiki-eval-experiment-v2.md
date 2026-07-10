# Спека: передел эксперимента NER + Wikidata grounding (прогоны v2, протокол метрик v3)

Дата: 2026-07-10. Статус: черновик на ревью владельца.
Предшественники: [2026-07-10-gt-canonicalization.md](2026-07-10-gt-canonicalization.md) (выполнена),
[2026-07-03-wiki-eval-design.md](2026-07-03-wiki-eval-design.md) (историческая, протокол v1/v2).
Аудиты-основания: [debugger-wiki-eval-llm-truncation-audit.md](../../reports/debugger-wiki-eval-llm-truncation-audit.md),
[code-reviewer-wiki-eval-harness.md](../../reports/code-reviewer-wiki-eval-harness.md),
инвентарь чистки (в этой спеке, § 7).

## 1. Цель и мотивация

Полный передел прогонов эксперимента «NER-извлечение → Wikidata grounding» на
WikiHist (100 статей), потому что в существующих прогонах найдены дефекты,
искажающие результат:

1. **Обрыв генерации.** `max_tokens` extraction-вызовов молча равен 4096
   ([client.py:46](../../../src/palimpsest/llm/client.py#L46)); судья ограничен 512
   ([wiki_eval.py:72](../../../scripts/wiki_eval.py#L72)). `finish_reason` не
   читается нигде в кодовой базе. Усечённый JSON у extraction молча
   превращается в «0 упоминаний» (`parse_surfaces` → `[]`,
   [extract.py:110-133](../../../src/palimpsest/terminology/extract.py#L110)) —
   тихая потеря recall. У deepseek на 512-токенном капе судьи reasoning-токены
   съедали бюджет ответа: `judge_unavailable` 2.70% против 0.42% у gemini при
   идентичном сетапе (6.4x) — старые числа deepseek смещены вниз.
2. **Контекст судьи — не предложение,** а окно ±40 символов
   (`CONTEXT_PAD=40`, [extract.py:91](../../../src/palimpsest/terminology/extract.py#L91)):
   судья видел обрывки вида «…Малатья, Мальдия, Милидия, М».
3. **Промпт NER на русском** (в статью нужен английский), весь уходит юзером
   при пустом system; у судьи Role-секция лежит в user, а не в system.
4. **Промпт NER сужал задачу** («чей перевод стоит проверить» + перечень глав
   конкретных цивилизаций) — извлекать надо ВСЕ имена и термины по древней
   истории вообще.
5. **Наблюдаемости нет:** ни один run-артефакт не хранит `finish_reason`,
   `completion/reasoning tokens`, фактического провайдера, эффективного
   `extra_body` — параметры прогона невозможно проверить постфактум.

Метрики уже переведены на протокол v3 (сетовые документные R/P, сплит
named/terms — [eval-metrics-terminology.tex](../../paper/sections/eval-metrics-terminology.tex)),
но v3-агрегатор существует только как scratchpad-скрипт — его надо
продакшнизировать.

## 2. Зафиксированные решения владельца (2026-07-10, не пересматриваются)

| # | Решение |
|---|---|
| Р1 | Облачные прогоны: **3 модели — gemini-3.1-flash-lite, deepseek-v4-flash и gemma-4-31b-it** (добавлена владельцем 2026-07-10: open-weights модель, гоняется через OpenRouter; родственный мостик к локальной Gemma-3-27B-it). **GPT-5.4 исключён из эксперимента полностью**: не гоним и не покажем — строка удаляется из Table C. Локальная тройка — по обновлённому runbook (Р12). **[поправка 2026-07-10 (5), санкция владельца: отдельная задача (не замена Table C) — NER-extraction-only cost-run для ВСЕХ 5 моделей через OpenRouter, включая локальную пару Gemma-3-27B-it и Qwen3.6-27B (роутинг через OpenRouter вместо sr004 явно авторизован владельцем для ЭТОЙ задачи — сама эта авторизация и есть правка спеки, не тихое решение исполнителя; sr004-раннбук по Р12 не отменяется и остаётся планом для Table C). Провайдер-пины для этих двух — см. поправку к Р14 ниже. Прогон использует `run --no-judge` (judge-free extraction, отдельный код-патч, без изменений промпта/`extract.py`) и хранится под `reports/terminology/wiki-eval/<slug>/111/` как обычно; статус и цифры — `docs/stages/wiki-eval.md` Status, 2026-07-10.]** |
| Р2 | **Оба прогона через стандартный OpenRouter** (`https://openrouter.ai/api/v1`), ключ владельца из env; НЕ через `OPENROUTER_BASE_URL`-гейтвей. Ключ после сессии ротируется. |
| Р3 | **Сэмплинг — повендорный, от единой 0.7 отходим** (решение владельца 2026-07-10). Явные параметры по моделям: **deepseek-v4-flash — temperature=1.0, top_p=1.0** (HF-карточка дословно: «For local deployment, we recommend setting the sampling parameters to temperature = 1.0, top_p = 1.0. For the Think Max reasoning mode, we recommend setting the context window to at least 384K tokens» — используем обычный think-режим, контекст Novita 1M, ограничение неактуально); **gemma-4-31b-it — temperature=1.0, top_p=0.95, top_k=64** (HF-карточка); **gemini-3.1-flash-lite — temperature=1.0** (решение исполнителя по поручению владельца: вендорский дефолт Gemini; top_p не передаём, провайдерский дефолт логируется). `max_tokens=20000` у всех моделей и обеих ролей. Все фактические параметры каждого вызова пишутся в run-артефакты (Р8). |
| Р15 | **Превышение лимита ответа = ошибка.** `finish_reason == "length"` (или пустой content при ненулевых reasoning-токенах) — НЕ толерируется и НЕ ретраится молча: вызов кидает исключение с диагностикой (модель, роль, статья/абзац, usage), прогон останавливается громко (чекпойнт цел, резюмируем после разбора), событие считается в meta. Прежняя формулировка «length → retry как transient» отменена. |
| Р13 | **Reasoning ВКЛЮЧЁН у всех трёх моделей** (решение владельца 2026-07-10): deepseek `reasoning: {"enabled": true}` (rt=51 на пробе с 1.0/1.0), gemini `reasoning: {"effort": "medium"}` (у gemini `enabled: true` без effort reasoning НЕ зажигает — проверено, rt=0 против rt=81…89 с effort), gemma `reasoning: {"enabled": true}` (rt=82 на пробе). Гейт на каждый вызов: `reasoning_tokens > 0`. |
| Р14 | **Провайдер-пины зафиксированы в спеке** (решение владельца: сейчас, не «на пилоте»): deepseek-v4-flash → **Novita**, gemini-3.1-flash-lite → **Google AI Studio**, gemma-4-31b-it → **WandB** (uptime 99.93, ctx/max_out 262k, самый дешёвый тир; Venice дисквалифицирован — max_out 8192 < 20000; на пробе один 429-флик — транзиент, покрывается ретраями, устойчивость подтвердит пилот). Всегда `provider: {"order": [<pin>], "allow_fallbacks": false}`. Основание — § 4.6. Смена пина = правка этой спеки, не тихое решение исполнителя. **[поправка 2026-07-10 (6): пины для Gemma-3-27B-it/Qwen3.6-27B на OpenRouter (проба исполнителя через живой `GET /v1/models/{id}/endpoints`, а не HF-карточка — эти две модели раньше на облаке не гонялись): gemma-3-27b-it → **DeepInfra** ($0.08/$0.16 за Mtok, uptime 99.8%+, самый дешёвый и самый надёжный из 5 проверенных провайдеров; не reasoning-модель — `extra_body` без ключа `reasoning`, сэмплинг как у gemma-4-31b-it: temperature=1.0/top_p=0.95/top_k=64); qwen3.6-27b → **Io Net** ($0.285/$2.40 за Mtok, uptime 99.97%, самый дешёвый и самый надёжный из 6 проверенных провайдеров; гибридная thinking-модель, reasoning включён по умолчанию — локальный vLLM-раннбук (Р12) гасит его через `chat_template_kwargs.enable_thinking=false`, недоступный через нормализованный API OpenRouter; единственный рычаг здесь — `reasoning: {"enabled": false}`, живой пробный вызов подтвердил `reasoning_tokens=0`). Оба добавлены в `MODEL_PARAMS` в коде тем же коммитом, что и эта поправка. Побочный фикс той же поправки: `_resolve_route`'s `expect_reasoning` раньше проверял только наличие ключа `"reasoning"`, не его `enabled`-значение — для `{"enabled": false}` это ошибочно требовало бы `reasoning_tokens > 0` (Р13-гейт бы падал на КАЖДОМ вызове qwen3.6-27b). Исправлено: `expect_reasoning` теперь `False`, когда `reasoning.enabled` явно `false`.]** |
| Р4 | Контекст судьи = **полное предложение** с упоминанием. `CONTEXT_PAD` удаляется из кода и документации полностью. |
| Р5 | NER-промпт переводится на английский (примеры остаются русскими), неизменяемая часть уходит в system prompt. Домен: «ancient history» без перечня глав. Задача: извлекать все имена собственные и термины. |
| Р6 | Категорий в СХЕМЕ ВЫВОДА больше нет (решение владельца 2026-07-10: детерминированно категория нигде не используется — только косметический бейдж в демо; следствие для демо принято). Схема вывода: `{surface, lemma}`. Блок категорий в промпте остаётся как **определение объёма задачи** («What to extract (examples)»), с добавленными `deity`, `work`, `religion` и расширенным `place`. |
| Р12 | **Runbook локальных прогонов** ([sr004-local-eval-runbook.md](../../runbooks/sr004-local-eval-runbook.md)) обновляется этой же спекой: новый EN-промпт с system/user-разбивкой, схема `{surface, lemma}`, `temperature=0.7` / `max_tokens=20000` (vLLM-эквиваленты), контекст-предложение, v3-скоринг команды, снос `--p3`. Локальная тройка гонится по тем же параметрам, что облачная пара — иначе строки таблицы несравнимы. **[поправка 2026-07-10: единой 0.7 нет — повендорный сэмплинг и для локальной тройки, см. Р3/обновлённый runbook]** |
| Р7 | У судьи Role + контракт вывода переезжают в system prompt; в user — только данные (surface, lemma, полное предложение, кандидаты). |
| Р8 | Пер-вызовная наблюдаемость обязательна: `finish_reason`, prompt/completion/reasoning tokens, фактический served provider, эффективный `extra_body`, стоимость — в run-артефакты. |
| Р9 | Label-credit precision (`P_label`/P3/`label_exists`) выброшена из статьи и удаляется из кода. Метрики статьи: сетовые `R_doc`/`P_doc` со сплитом named/terms (протокол v3). |
| Р10 | `gt_v2.jsonl` удалён (выполнено этой спекой, дубль канонического `gt.jsonl`). |
| Р11 | Старый код и доки протокола v2 вычищаются (§ 7); 15 старых run-директорий остаются архивом и получают SUPERSEDED-маркер после приземления новых прогонов. |

## 3. Промпты (финальные тексты)

После мержа единственный источник истины — код (`extract.py`,
`label_first.py`, `wiki_eval.py`); тексты приведены здесь для ревью решения.

### 3.1 NER extraction

**SYSTEM** (неизменяемая часть; `{{source}}` в system не входит):

> [AMENDED 2026-07-10, post-pilot owner decision: the NER prompt was strengthened after the 64-miss span-level review — oblique case forms are never skipped, coordinated lists extract every member, multiword geographic names are extracted whole, one new invented few-shot example. Code is the SSOT: src/palimpsest/terminology/extract.py::NER_SYSTEM_PROMPT. Pilot runs before this note used the original v2 prompt text below; comparability of future runs with the 2026-07-10 pilot is affected.]
>
> [AMENDED 2026-07-10 (2), owner hand-labeling of the 64-miss review: added language and realia categories, specialized-realia and adjective-named-language rules, modern-entity/natural-science exclusion; second few-shot example extended. Code remains the SSOT.]
>
> [AMENDED 2026-07-10 (3), owner decision: supersedes §2 Р6 and §4.4 item 10 below (both remain in this document unmodified as the historical record of that decision, per the doc-parity convention of appending rather than rewriting). Р6's "no category in the output schema" is revisited -- the owner needs the per-category error distribution for the paper's appendix. `category` is added back as a MANDATORY field: `{surface, lemma, category}`, one of the `<categories>` tokens below (`person`, `place`, `people`, `title`, `social`, `institution`, `dynasty`, `culture`, `language`, `realia`, `event`, `deity`, `work`, `religion`) or `"other"`; category never changes whether an item is extracted, only how the result is labelled. `parse_surfaces` normalizes an unrecognized/missing value to `"other"`, preserving the raw value as `category_raw` only when it differed from a present value -- an otherwise-valid extraction is never rejected/retried over the category value. Both invented few-shot examples below are updated with `category` values (their invented content is otherwise unchanged); code is the SSOT for the exact text (`extract.py::NER_SYSTEM_PROMPT`). **This is the LAST edit to this prompt before the full evaluation runs -- the prompt is now FROZEN** (see the freeze comment above `NER_SYSTEM_PROMPT` in code): do not modify without a further owner-approved spec amendment. Consequence for the demo: the `TermPopover`/Glossary category pill (fed by `Term.note = m.category or ""`, per `pipeline.py`) will populate again for freshly-extracted terms once this prompt is used live -- `docs/stages/terminology.md`'s Interface section and the demo-seed regeneration decision (§9) are unaffected by this note and still describe the pre-amendment state; they are not updated in this commit (out of this task's write scope) and are flagged here for a follow-up doc-parity pass.]

```
## Role
You are a source-criticism historian and linguist. You annotate Russian
academic texts on ancient history and extract TERMS and PROPER NAMES.

## Task
From <source>, extract ALL historical entities and terms REGARDLESS of
capitalization. Russian writes entire classes of important terms in
LOWERCASE (peoples, titles, social strata). Extract them as carefully as
capitalized names. This is the main goal of the annotation.

## What to extract (examples)
The classes below define the scope of the task with examples. They are
not an exhaustive list.
<categories>
- person      — persons: Хаммурапи, Саргон, Кадашман-Харбе
- place       — cities/countries/rivers/regions, incl. archaeological
                sites and tombs: Лагаш, Евфрат, Вавилония, Арслантепе
- people      — peoples/tribes/ethnic groups (often lowercase): амореи, кутии, касситы, шумеры
- title       — titles/offices/administrative units (often lowercase): лугаль, энси, претор, ном
- social      — social strata (lowercase): авилум, мушкенум, вардум
- institution — institutions/law codes/associations: Законы Хаммурапи, принципат, клерухия
- dynasty     — dynasties: III династия Ура, Чжоу
- culture     — cultures/periods: старовавилонский период
- event       — battles/wars/treaties/reforms: битва при Кадеше
- deity       — deities/mythological beings: Мардук, Осирис, эпимелиды
- work        — texts/inscriptions/literary works: упанишады, амарнские письма
- religion    — religions/cults/religious practices: вишну-бхакти, шраута
</categories>

## What NOT to extract
<do_not_extract>
- Ordinary words and roles in their generic sense that are not a name or a
  term: город, царь, война, страна, знать, люди, вещи, дороги, имущество,
  гражданство, глава, магистрат, молодцы, бойцы.
- Descriptive and bureaucratic phrases («государственные поставки
  продовольствия», «военное дело», «малая семья»). Extract only the
  established term inside, if there is one.
- Standalone adjectives and verbs (докерамический, доземледельческий,
  завоёванный).
- Standalone dates, years, numbers.
- Principle: extract CONCRETE terms (names, titles, peoples, social strata,
  institutions, cultures), not general concepts. If it is a general word
  used descriptively, skip it.
</do_not_extract>

## Rules
- surface is the EXACT substring from <source>, in the form and case it has
  in the text (for example «Лагаше», not «Лагаш»). Do NOT normalize, do NOT
  translate, do NOT invent.
- lemma is the agreed NOMINATIVE form of the term: for a single word, the
  nominative case («Лагаше» → «Лагаш»); for a phrase, ALL words agree in
  the nominative («династии Цин» → «династия Цин», «авилумов» → «авилум»).
  If surface is already in the nominative, lemma equals surface.
- One record per UNIQUE surface (do not duplicate repeats).

## Good example
<example>
<source>В Лагаше, одном из номов, правитель-лугаль опирался на авилумов, тогда как амореи наступали с запада.</source>
<output>[{"surface":"Лагаше","lemma":"Лагаш"},{"surface":"номов","lemma":"ном"},{"surface":"лугаль","lemma":"лугаль"},{"surface":"авилумов","lemma":"авилум"},{"surface":"амореи","lemma":"амореи"}]</output>
</example>

## Bad example (do NOT do this)
<bad_example>
<source>В Лагаше правитель опирался на воинов.</source>
<bad_output>[{"surface":"правитель","lemma":"правитель"},{"surface":"воинов","lemma":"воин"},{"surface":"Lagash","lemma":"Lagash"}]</bad_output>
<why_bad>«правитель» and «воинов» are ordinary words, not terms. «Lagash» is a translation, while surface must be the Russian substring «Лагаше».</why_bad>
</bad_example>

## Output format
A JSON array of {surface, lemma} objects only. No explanations and no
markdown fences.
```

**USER:** `<source>\n{{source}}\n</source>` — и ничего больше.

### 3.2 Disambiguation judge

**SYSTEM** (вместо нынешней однострочки; Role + контракт вывода):

```
## Role
You are a Wikidata disambiguation judge for a Russian-to-English historical
translation pipeline. Given a Russian term, its lemma, the sentence it
occurs in, and a numbered list of Wikidata candidates, decide which
candidate (if any) the term refers to.

## Output
Return strict JSON only, no other text:
{"qid": "Q..." or null, "reason": "<one sentence>"}

Use null when no candidate genuinely fits the context.
```

**USER** (только данные; `{context}` = полное предложение):

```
Surface form: {surface}
Lemma: {lemma}
Sentence context: {context}

Candidates:
{candidates}
```

Reask-система сохраняется как корректирующая надстройка над новым system.

## 4. Изменения кода

### 4.1 Генерация и транспорт
1. `LLMConfig`/вызовы: `max_tokens` extraction и judge → **20000**;
   сэмплинг — повендорный из таблицы Р3 (deepseek 1.0/1.0, gemma
   1.0/0.95/64, gemini 1.0), задаётся пер-модельным конфигом; CLI-флаги
   `--temperature`, `--max-tokens`, `--top-p`, `--top-k` добавляются, все
   эффективные значения пишутся в meta (ревью-finding 4).
2. `--extra-body` **мержится** с провайдер-пином, а не заменяет его
   (finding 4, [wiki_eval.py:108-111](../../../scripts/wiki_eval.py#L108)).
3. Транспорт прогонов: стандартный OpenRouter. Провайдер-политика: живая
   проба схемы `provider: {order: [...], allow_fallbacks: false}` через наш
   OpenAI-compat клиент; если работает — пин лучшего провайдера по пилоту,
   если нет — `auto` + обязательный пер-вызовный лог served provider и
   пост-фильтр аномалий. CloseRouter-пины (`provider-9`) на OR не валидны.
4. **`finish_reason` проверяется на каждом вызове.** `length` (или пустой
   content при ненулевых reasoning-токенах) → **громкое исключение по Р15**:
   вызов НЕ ретраится молча, прогон останавливается с диагностикой
   (модель, роль, статья/абзац, usage), чекпойнт цел, событие посчитано в
   meta. Обычные transient-ошибки (сеть, 429, 5xx) ретраятся как раньше.

### 4.2 Надёжность парсинга и учёт отказов (по ревью)
5. `parse_surfaces` перестаёт молчать (finding 1): parse-fail отличим от
   честного пустого списка; каждый parse-fail считается
   (`n_extraction_parse_failures` per-article в meta), жадный
   `re.search(r"\[.*\]")` заменяется на устойчивое выделение первого
   сбалансированного JSON-массива.
6. Исчерпание бюджета судьи → отдельный `resolved_by="budget_exhausted"`
   или громкая остановка прогона, не `judge_unavailable` (finding 2).
7. `--resume` восстанавливает `calls_by_kind`/`spent_by_kind`, метрики
   spend в meta становятся самосогласованными (finding 3).
8. `judge_cache` остаётся scope-уровневым (осознанное допущение «one sense
   per discourse»), допущение документируется у ключа (finding 5).
   Устаревший комментарий про temperature=0 у reask переписывается
   (finding 6). Счётчик дропов `validate_surfaces` сохраняется в meta
   (finding 8).

### 4.3 Контекст предложения (Р4)
9. Новый построитель контекста: полное предложение (или предложения, если
   упоминание пересекает границу), разбиение с гвардом русских сокращений
   («до н. э.», «н. э.», «в.», «вв.», «г.», «гг.», «др.», «т. д.», «т. п.»,
   инициалы). `CONTEXT_PAD`/`_context()` удаляются. Юнит-тесты на
   сокращения и упоминание в первом/последнем предложении абзаца.

### 4.4 Категории (Р6)
10. Поле `category` удаляется из схемы вывода и парсинга (`parse_surfaces`
    ждёт `{surface, lemma}`; category-ветка `validate_surfaces` и константа
    `CATEGORIES` удаляются из eval-пути). Поле `TermMention.category`
    остаётся для legacy demo-сида, в новых извлечениях оно `None` —
    следствие: категория-бейдж в TermPopover/Glossary пустеет для новых
    извлечений (принято владельцем, Р6).

### 4.5 Метрики v3 в продакшн (Р9)
11. Новый агрегатор в `evaluation/metrics.py` (или `metrics_v3.py`):
    сетовые документные метрики — дедуп до уникальных (article, QID),
    tier-фильтр лексических классов, micro TP/FP/FN, `R_doc`/`P_doc`,
    сплит named/terms по капитализации анкора (gold) и поверхностей (pred,
    класс TP берётся от gold). Wilson CI от пулов. Юнит-тесты, включая
    анкеры текущих чисел (gemini pre-redo: named 3265/4032, term 621/1530 —
    как регрессионный тест агрегатора на старых pred-файлах).
12. `report.py` переписывается под v3; `methodology_draft()` и её копия в
    `docs/stages/wiki-eval.md` § Methodology схлопываются: единственный
    источник методологии — [eval-metrics-terminology.tex](../../paper/sections/eval-metrics-terminology.tex),
    доки ссылаются, не копируют.
13. `tier_assignment.json` + `tier_defs.json` переезжают из
    `docs/experiments/.../drafts/` в `data/eval/wiki/` (данные фильтра —
    рядом с gold).

### 4.6 Резолюция вопроса temperature (проверено живьём 2026-07-10)

- OpenRouter `/models`: обе модели заявляют `temperature` в
  `supported_parameters`; `max_completion_tokens` = 65536 (наш 20000
  влезает).
- Поведенческая проба (5 вызовов на модель, один промпт):
  gemini-3.1-flash-lite через Google AI Studio — при T=0.7 ответы
  варьируются, при T=0 два вызова побайтно идентичны → температура
  применяется; deepseek-v4-flash на route `auto` — ответы меняются, но
  вперемешку с провайдер-вариативностью (GMICloud/Novita/Venice/Alibaba),
  причём **Venice и Alibaba вернули `finish_reason=length` с пустым
  content** (reasoning-по-умолчанию съел малый кап пробы) — живое
  подтверждение и reasoning-трапа, и необходимости пина.
- HF-карточка [deepseek-ai/DeepSeek-V4-Flash](https://huggingface.co/deepseek-ai/DeepSeek-V4-Flash):
  «For local deployment, we recommend setting the sampling parameters to
  temperature = 1.0, top_p = 1.0» (единая рекомендация для всех режимов).
  0.7 — осознанно консервативнее вендорской рекомендации и совпадает с
  Hyperparameters-секцией статьи.
- Пин-проба (2026-07-10, живые вызовы с `allow_fallbacks: false`):
  синтаксис `provider: {"order": ["Novita"]}` работает (served_by
  эхо-подтверждается, slug и display-имя равнозначны). Первопартийный
  провайдер «DeepSeek» НЕпинуем (HTTP 404 «No endpoints found» на обе
  формы слага) — из explicit-роутинга исключён. DeepInfra в момент пробы
  429 (rate-limited upstream). Novita: uptime 99.80, max_out 393216,
  reasoning подтверждён (finish=stop). GMICloud — рабочий запасной
  (99.47). Gemini: Google AI Studio uptime 99.23 против 95.81 у
  Vertex-канала, пин работает, reasoning зажигается ТОЛЬКО формой
  `{"effort": ...}` (`{"enabled": true}` даёт rt=0 — форма зафиксирована
  в Р13).
- Gemma-4-31b-it (добавлена Р1): HF-карточка рекомендует temperature=1.0,
  top_p=0.95, top_k=64; thinking поддержан. Эндпоинты OR: WandB uptime
  99.93 / ctx и max_out 262144 / самый дешёвый тир; Venice max_out 8192
  (< кап 20000 — дисквалифицирован); Novita 97.9. Проба на пине WandB:
  served_by=WandB, finish=stop, rt=82, вендорские параметры приняты; на
  повторе один транзиентный 429.
- Финальные пробы вендорских параметров (все на своих пинах, finish=stop):
  deepseek@Novita T=1.0/top_p=1.0 rt=51; gemini@AI Studio T=1.0
  effort=medium rt=81; gemma@WandB 1.0/0.95/64 rt=82.
- Итог: **повендорный сэмплинг (Р3), reasoning ON у всех трёх (Р13), пины
  (Р14): deepseek → Novita, gemini → Google AI Studio, gemma → WandB.**
  Гейт на каждый вызов прогона: `reasoning_tokens > 0`, `finish_reason !=
  length` (нарушение = ошибка по Р15), served_by == пину.

## 5. План прогона

1. **Пробы — ВЫПОЛНЕНЫ 2026-07-10 (§ 4.6):** temperature, пин-синтаксис,
   reasoning-формы, выбор пинов (Р14). Остался только smoke 3 реальных
   вызова на роль с финальными промптами перед пилотом.
2. **Пилот: 10 статей, gemini.** Гейты: `finish_reason=length` = 0 (одно
   событие = ошибка по Р15, стоп и разбор); `reasoning_tokens > 0` на 100%
   вызовов; served_by == пину на 100% вызовов;
   `n_extraction_parse_failures` < 1% абзацев; экстраполяция стоимости на
   3×100 статей ≤ $15 (иначе стоп и доклад). После gemini-пилота — мини-
   пилот 3 статьи на deepseek и gemma (проверка пинов/reasoning на
   реальной нагрузке).
3. **Полные прогоны: 3 модели параллельно** (три фоновых процесса,
   `article-workers` по нагрузке OR; настройки идентичны кроме модели и её
   повендорного сэмплинга). Прогоны — свежие run-директории; старые не
   перезаписываются.
4. **Скоринг:** v3-агрегатор → `metrics.json` нового формата + числа для
   Table C (4 ячейки на модель + counts).
5. **SUPERSEDED-маркеры** на 15 старых run-директорий (после приземления).

## 6. Верификация

- Юнит-тесты нового кода (sentence-context, parse-fail учёт, v3-агрегатор,
  resume-счётчики) + зелёный полный `pytest tests/`.
- Пилотные гейты § 5.2.
- Пост-ран аудит наблюдаемости: в run-артефактах каждого вызова есть
  `finish_reason`/tokens/provider/effective extra_body; доля `length` = 0.
- Доли named/terms в gold неизменны (5562 = 4032 + 1530) — инвариант
  эталона, прогоны его не трогают.
- Doc-parity в тех же коммитах; `/verify-pr` перед финишем.

## 7. Чистка (по инвентарю 2026-07-10)

- **DELETE код:** `scripts/sitelink_contamination.py`,
  `scripts/sitelink_clean_full_metrics.py`,
  `scripts/replay_sitelink_contamination.py` (мёртвый импорт из чужого
  scratchpad), `--p3`/`_label_exists_fn`/p3-ветки в `wiki_eval.py`,
  p3/label-credit и mention-level M1/M2/P1/P2 ветки в
  `evaluation/metrics.py`+`matching.py` (`match_m3` — допустимая основа
  v3-дедупа), соответствующие тесты (`test_wiki_matching.py` M1/M2,
  p3-блоки в `test_wiki_metrics.py`/`test_wiki_report.py`/`test_wiki_eval_runner.py`).
- **DELETE данные:** label_exists-кэши (4 шт.) и кандидатные кэши в
  `drafts/sitelink_replay/`, `sitelink-clean-full-metrics.json`,
  `drafts/sitelink_replay/{gemini,deepseek}.json`. (Это кэши Wikidata-API и
  производные метрики, не LLM-предсказания — инвариант «никогда не удалять
  предсказания» не задет; `pred.jsonl` всех прогонов остаются.)
- **UPDATE доки:** `docs/stages/wiki-eval.md` (переписать под v3 + новые
  промпты/параметры), `docs/paper/paper-state.md` (сейчас дрейфует — v2
  нарратив при v3 tex), `docs/known_issues.md` (резолюции + новая запись
  про finish_reason).
- **UPDATE runbook (Р12):** `docs/runbooks/sr004-local-eval-runbook.md` —
  полная ревизия Table C части: команды с новым промптом (system/user),
  схемой `{surface, lemma}`, `temperature=0.7`/`max_tokens=20000` в
  vLLM-эквивалентах, контекст-предложением и v3-скорингом; `--p3` и
  P_label-шаги удаляются; пилот-гейт (10 статей) тот же, что у облачных.
- **ARCHIVE-BANNER:** `docs/experiments/2026-07-05-model-comparison/drafts/`
  прозовые файлы («paper-section-en-final.md» и др.) получают баннер
  «superseded by docs/paper/sections/ (protocol v3)».
- **Выполнено этой спекой:** `gt_v2.jsonl` + summary удалены (Р10).

## 8. Статья (deliverables)

- Appendix-фигуры обоих промптов в template-виде (стиль `\begin{prompt}`
  как у translation-промпта; NER-промпт содержит worked example внутри).
- Table C: **6 строк** (локальные: Qwen3-4B-Instruct, Gemma-3-27B-it,
  Qwen3.6-27B; облачные: Gemma-4-31B-it, Gemini-3.1-Flash-Lite,
  DeepSeek-V4-Flash); строка GPT-5.4 удаляется (Р1); облачная тройка
  заполняется числами v2-прогонов, локальная тройка — после sr004.
- §5.1 findings переписываются от новых чисел (сплит named vs terms —
  главный финдинг; разложение recall на покрытие извлечения × точность
  grounding — кандидат второго, пересчитать на новых данных).

## 9. Вне области действия

- GPT-5.4: исключён из эксперимента полностью (Р1) — ни прогона, ни строки
  в таблице.
- Локальная тройка (Qwen3-4B / Gemma-3-27B / Qwen3.6-27B) — на sr004 по
  обновлённому раннбуку, вне этой спеки.
- Table A/B (BOUQUET-судьи, refinement) — не затрагиваются.
- Регенерация demo-сида `data/seed/terminology_terms.jsonl` под новый
  промпт: **отдельное решение владельца.** Прямо флагуется: смена
  `DEFAULT_NER_PROMPT` меняет и живой webapp-путь extraction
  (`extract_paragraph_terms`, `scripts/term_pipeline.py`) — консистентно с
  Invariant 9 (English-only), но сид демо пересобирается не здесь.
- Пересбор корпуса/gold — эталон не меняется.
