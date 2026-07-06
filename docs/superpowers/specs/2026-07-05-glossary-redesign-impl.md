# Спека S2 — Glossary: реализация редизайна по мокапу 2026-07-03

Дата: 2026-07-05. Ветка: `claude/emlp-2026-website-fixes-muih1x`.
Канон дизайна: [2026-07-03-glossary-redesign-mockup.html](2026-07-03-glossary-redesign-mockup.html) — открыть в браузере, реализация обязана совпадать пиксельно по структуре/классам/цветам (токены `--va-*` уже совпадают с variant-a.css).

## 0. Grounding

- Текущий `GlossaryTab.tsx` — плоская таблица per-occurrence: Difficulty / Pair / Source / Translation / Wikidata / ¶ / Note; куча дублей («Тигра», «Евфрата» по 2-3 раза — видно на скрине владельца), нет группировки, нет деталей граундинга.
- Данные: таблица `term` (`db.py`): `source_surface, source_lemma, context, char_start/end, difficulty, grounded_json, candidates_json, target_surface, pair_accuracy, recommended, note, trace_json` (NOT NULL DEFAULT '{}'). Seed = 204 терма.
- **Факт о seed-данных (ревью, дамп `seed.py::_seed_terms:151-184`):** сегодня это «mock terms» — `candidates_json=[]` и `trace_json='{}'` у ВСЕХ 204 строк, `grounded_json` без `resolved_by`, QID синтетический (`Q{100000+hash(...)%900000}`), т.е. Wikidata-ссылки текущего глоссария не настоящие. Difficulty/pairAccuracy — реальные выходы G3/P3, но трассы решений в данных нет. Отсюда двухчастный план: §2.2-degradation как основной путь + §7 обогащение данных как отдельный шаг.
- Мокап-структура: группировка по (lemma, entity); строка = чипы Difficulty+Pair, Source (+категория-пилюля), Translation, Wikidata (label-ссылка + QID моно), Grounding-бейдж (◆ label match / ◇ LLM · model / ◇ LLM rejected all / ○ no candidates), Mentions ×N; раскрытие → Context RU/EN с `<mark>`, 4-шаговый path-степпер (QUERY → SEARCH → LABEL MATCH → DECISION; состояния done/warn/fail/skip), таблица кандидатов (chosen/rejected, via-чипы `label·ru`/`alias`/`none`), карточка judge-решения, список всех mentions.

## 1. Цель

Вкладка Glossary = витрина методологии NER+Wikidata-grounding: сгруппированный глоссарий с раскрываемым «путём заземления» каждого терма. Это ключевой экран для видео EMLP.

## 2. Данные: маппинг term → UI

### 2.1 Группировка (frontend, чистая функция + тесты)
- Ключ группы: `groupKey = (source_lemma || source_surface.toLowerCase(), qid || 'ungrounded:' + lemma)`, где `qid` из `grounded_json.qid`.
- Группа агрегирует: mentions = все term-строки группы (пронумерованы по ¶ = paragraph.idx+1); difficulty группы = худшая (red > yellow > green); pair = худшая среди строк с pair_accuracy, `—` если ни у одной нет; Translation = `recommended || target_surface` первой залинкованной строки, `absent`-строки показывают перевод из любой mention с target_surface, иначе `—`.
- Сортировка: по первому появлению (min paragraph.idx, потом char_start).
- Саммари-строка под заголовком: `Grouped by lemma + entity · {G} terms · {M} mentions · resolved deterministically: {d} · via LLM: {l} · not grounded: {n}` — счётчики из §2.2.

### 2.2 Grounding-бейдж — строгий приоритет правил (разночтение §2.2/§6 закрыто ревью)
Единая функция `resolveBadge(term)`; правила применяются СТРОГО по порядку, первое сработавшее побеждает:
1. `trace_json.resolved_by` задан → маппинг: `exact_label|label_match` → `◆ label match` (det); `llm_disambiguation` → `◇ LLM · {model}` (llm; model из trace, fallback `LLM`); `llm_rejected` → `◇ LLM rejected all` (rej); `no_candidates` → `○ no candidates` (none).
2. trace_json пуст (`'{}'`), но grounded qid есть → `◆ grounded` (det-тон, без пути) — это основной случай текущих seed-данных.
3. trace_json непуст, но `resolved_by` отсутствует → эвристика: candidates>1 → llm; candidates==1 → det; qid нет и candidates>0 → rej; иначе none.
4. Ничего нет → `○ no candidates`.
Ничего не падает, консоль чистая; правило зафиксировать комментарием у функции.

### 2.3 Раскрытая панель
- **Context**: RU = `term.context` с `<mark>` на source_surface (уже есть char_start/end — но они относятся к абзацу; в контекст-сниппете маркировать вхождение surface поиском, без regex-инъекций); EN = предложение из paragraph.target вокруг target_surface с `<mark class="t">` (найти первое вхождение target_surface; нет — панель без EN-строки).
- **Path-степпер**: строится из `trace_json` (шаги: query {lemma_hits, surface_hits}, search {method: wbsearchentities|cirrus|title, hits}, label_match {exact_matches}, decision {resolved_by, api_calls, llm_calls, elapsed_s}). Отсутствующие поля → шаг серый `skip` с текстом `no trace`. Состояния шагов ровно как в мокапе: цепочка от done (все ок) / warn (fallback/LLM) / fail (0 hits) / skip.
- **Candidates**: из `candidates_json` [{qid, label, description, matched_via}] — chosen = qid из grounded_json (строка `chosen` с ✓ и зелёной левой рамкой), отклонённые LLM-ом — ✗. via-чипы: `label·ru` / `alias` (класс al) / `none` (класс no).
- **Judge decision**: если resolved_by = llm_disambiguation и trace_json.judge_reason есть → карточка judge (модель + цитата-обоснование). Нет — блок не рендерится.
- **All mentions**: список `§{n} {context c <mark>}`, клик по mention → переход на Document-таб к этому абзацу (реюз `handleRankingRowClick`-паттерна из VariantA).

## 3. UI-детали (соответствие мокапу — обязательное)

- Классы/токены: перенести стили мокапа в `variant-a.css` с префиксом `va-gl-` (`va-gl-table`, `va-gl-badge det|llm|rej|none`, `va-gl-step done|warn|fail|skip`, `va-gl-cand`, `va-gl-judge`, `va-gl-occ`, `va-gl-cat`, `va-gl-qid`, `va-gl-via`), значения (цвета, радиусы, паддинги, размеры шрифтов) — ровно из мокапа; ничего нового не изобретать.
- Колонки — ровно 7 data-колонок + chevron, сдвоенные заголовки как в мокапе (строка 113) и текущем GlossaryTab: `[chevron]` · `Difficulty` · `Pair` · `"Source · {SourceLang}"` · `"Translation · {TargetLang}"` · `Wikidata` · `Grounding` · `Mentions` (языки из document.source_lang/target_lang, capitalized).
- Wikidata-ячейка: ссылка = английский label entity (из grounded_json.label, fallback — QID), `target="_blank"`, рядом QID моноширинным `va-gl-qid`. Не «Mesopotamia» 6 раз подряд синим на полстраницы, как сейчас: ссылка компактная.
- Категория-пилюля (`Geographical`/`Onomastics`/…): из `term.note` (сейчас там `place` и т.п.) — Title Case, в пилюле `va-gl-cat` после source-текста. Пустая note → без пилюли.
- Раскрытие: аккордеон, несколько строк могут быть открыты одновременно (как в мокапе), chevron поворачивается, `tr.detail` с фоном `--va-surface`.
- Legend-строка внизу — дословно из мокапа.
- Empty-state (uploaded doc без термов): текущий `va-empty` («offline terminology») сохранить.
- Виртуализация не нужна (≤ ~120 групп на seed): обычный рендер, но раскрытая панель — ленивый mount (детали строятся при первом открытии).

## 4. Backend

Одно обязательное изменение (факт, подтверждён ревью): `_term_dict` (`app.py:91-101`) отдаёт `sourceLemma`, `grounded` (распарсенный grounded_json), `candidates` (распарсенный candidates_json), но **`trace_json` в DTO отсутствует вовсе** — а на нём весь степпер. Добавить `"traceJson": json.loads(r["trace_json"] or "{}")` (camelCase, распарсенный объект — конвенция как у grounded/candidates). Контракт-SSOT дополнить в том же коммите. Больше изменений API нет.

## 5. Тесты

- Vitest: группировка (дубли «Тигр/Тигра» сливаются по лемме; худший difficulty; счётчики саммари); `resolveBadge` — все 4 правила §2.2, включая llm/rej на СИНТЕТИЧЕСКИХ фикстурах (в юнитах, без претензии на seed-происхождение); degradation при trace='{}'; mention-клик вызывает переход.
- E2E на seed-документе — только реально достижимые состояния: collapsed-таблица, раскрытая панель `◆ grounded` (degradation: контекст + mentions, без степпера), `○ no candidates`. Если §7-обогащение успело лечь в данные — добавить скриншоты det/llm/rej с полным степпером. Клик mention → Document. Сравнение глазом с мокапом (агент прикладывает мокап-скрин рядом).

## 6. Честность подачи

В отчёте и доках прямо пишем: редизайн — это реальный UI поверх имеющихся полей term; полнота «пути заземления» зависит от наполненности trace_json. Сегодняшний seed трассы не содержит (mock из _seed_terms) — поэтому §7.

## 7. Обогащение seed-данных (отдельный шаг ПОСЛЕ приземления UI, time-box 30 мин)

Попытаться прогнать существующий терминологический модуль (G3-grounding с Wikidata-кэшем `reports/terminology/wikidata_cache.jsonl`, если кэш есть в чекауте; иначе живые вызовы Wikidata — они бесплатные и покрыты polite-кэшем) на уникальных леммах seed-документа и записать в term реальные `qid/candidates_json/trace_json` (+ `resolved_by`). Скрипт кладём в `scripts/enrich_seed_terms.py`, обновление данных — идемпотентный UPDATE по (paragraph_id, char_start, char_end); данные в `data/seed/seed_paragraphs.jsonl` тоже обновить (чтобы reseed воспроизводился). Не успели/не вышло → остаёмся на degradation (это осознанный fallback, не провал); фиксируем состояние в known_issues.
