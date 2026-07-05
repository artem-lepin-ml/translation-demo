# Спека S2 — Glossary: реализация редизайна по мокапу 2026-07-03

Дата: 2026-07-05. Ветка: `claude/emlp-2026-website-fixes-muih1x`.
Канон дизайна: [2026-07-03-glossary-redesign-mockup.html](2026-07-03-glossary-redesign-mockup.html) — открыть в браузере, реализация обязана совпадать пиксельно по структуре/классам/цветам (токены `--va-*` уже совпадают с variant-a.css).

## 0. Grounding

- Текущий `GlossaryTab.tsx` — плоская таблица per-occurrence: Difficulty / Pair / Source / Translation / Wikidata / ¶ / Note; куча дублей («Тигра», «Евфрата» по 2-3 раза — видно на скрине владельца), нет группировки, нет деталей граундинга.
- Данные: таблица `term` (`db.py`): `source_surface, source_lemma, context, char_start/end, difficulty, grounded_json, candidates_json, target_surface, pair_accuracy, recommended, note, trace_json` (NOT NULL DEFAULT '{}'). Seed = 204 реальных терма (G3+P3, spec 2026-07-02-seed-refresh).
- Мокап-структура: группировка по (lemma, entity); строка = чипы Difficulty+Pair, Source (+категория-пилюля), Translation, Wikidata (label-ссылка + QID моно), Grounding-бейдж (◆ label match / ◇ LLM · model / ◇ LLM rejected all / ○ no candidates), Mentions ×N; раскрытие → Context RU/EN с `<mark>`, 4-шаговый path-степпер (QUERY → SEARCH → LABEL MATCH → DECISION; состояния done/warn/fail/skip), таблица кандидатов (chosen/rejected, via-чипы `label·ru`/`alias`/`none`), карточка judge-решения, список всех mentions.

## 1. Цель

Вкладка Glossary = витрина методологии NER+Wikidata-grounding: сгруппированный глоссарий с раскрываемым «путём заземления» каждого терма. Это ключевой экран для видео EMLP.

## 2. Данные: маппинг term → UI

### 2.1 Группировка (frontend, чистая функция + тесты)
- Ключ группы: `groupKey = (source_lemma || source_surface.toLowerCase(), qid || 'ungrounded:' + lemma)`, где `qid` из `grounded_json.qid`.
- Группа агрегирует: mentions = все term-строки группы (пронумерованы по ¶ = paragraph.idx+1); difficulty группы = худшая (red > yellow > green); pair = худшая среди строк с pair_accuracy, `—` если ни у одной нет; Translation = `recommended || target_surface` первой залинкованной строки, `absent`-строки показывают перевод из любой mention с target_surface, иначе `—`.
- Сортировка: по первому появлению (min paragraph.idx, потом char_start).
- Саммари-строка под заголовком: `Grouped by lemma + entity · {G} terms · {M} mentions · resolved deterministically: {d} · via LLM: {l} · not grounded: {n}` — счётчики из §2.2.

### 2.2 Grounding-бейдж из `grounded_json` / `trace_json`
Читать `resolved_by` (в grounded_json или trace_json — фактическое поле проверить на seed-данных, взять то, что заполнено):
- `exact_label` (или синоним `label_match`) → `◆ label match` (класс badge det, зелёный тон);
- `llm_disambiguation` → `◇ LLM · {model}` (badge llm, жёлтый; model из trace_json, fallback — grounding_config.model_name, fallback — `LLM`);
- `llm_rejected`/кандидаты были, выбора нет → `◇ LLM rejected all` (badge rej);
- нет кандидатов / grounded_json пуст → `○ no candidates` (badge none).
- **Graceful degradation:** если trace_json = '{}' (старые/чужие данные) и grounded_json есть → бейдж `◆ grounded` (det) без пути; если и его нет → `○ no candidates`. Ничего не падает, консоль чистая.

### 2.3 Раскрытая панель
- **Context**: RU = `term.context` с `<mark>` на source_surface (уже есть char_start/end — но они относятся к абзацу; в контекст-сниппете маркировать вхождение surface поиском, без regex-инъекций); EN = предложение из paragraph.target вокруг target_surface с `<mark class="t">` (найти первое вхождение target_surface; нет — панель без EN-строки).
- **Path-степпер**: строится из `trace_json` (шаги: query {lemma_hits, surface_hits}, search {method: wbsearchentities|cirrus|title, hits}, label_match {exact_matches}, decision {resolved_by, api_calls, llm_calls, elapsed_s}). Отсутствующие поля → шаг серый `skip` с текстом `no trace`. Состояния шагов ровно как в мокапе: цепочка от done (все ок) / warn (fallback/LLM) / fail (0 hits) / skip.
- **Candidates**: из `candidates_json` [{qid, label, description, matched_via}] — chosen = qid из grounded_json (строка `chosen` с ✓ и зелёной левой рамкой), отклонённые LLM-ом — ✗. via-чипы: `label·ru` / `alias` (класс al) / `none` (класс no).
- **Judge decision**: если resolved_by = llm_disambiguation и trace_json.judge_reason есть → карточка judge (модель + цитата-обоснование). Нет — блок не рендерится.
- **All mentions**: список `§{n} {context c <mark>}`, клик по mention → переход на Document-таб к этому абзацу (реюз `handleRankingRowClick`-паттерна из VariantA).

## 3. UI-детали (соответствие мокапу — обязательное)

- Классы/токены: перенести стили мокапа в `variant-a.css` с префиксом `va-gl-` (`va-gl-table`, `va-gl-badge det|llm|rej|none`, `va-gl-step done|warn|fail|skip`, `va-gl-cand`, `va-gl-judge`, `va-gl-occ`, `va-gl-cat`, `va-gl-qid`, `va-gl-via`), значения (цвета, радиусы, паддинги, размеры шрифтов) — ровно из мокапа; ничего нового не изобретать.
- Колонки: `[chevron] Difficulty · Pair · Source · Russian · Translation · English · Wikidata · Grounding · Mentions` (языки в заголовках — из document.source_lang/target_lang, capitalized, как сейчас).
- Wikidata-ячейка: ссылка = английский label entity (из grounded_json.label, fallback — QID), `target="_blank"`, рядом QID моноширинным `va-gl-qid`. Не «Mesopotamia» 6 раз подряд синим на полстраницы, как сейчас: ссылка компактная.
- Категория-пилюля (`Geographical`/`Onomastics`/…): из `term.note` (сейчас там `place` и т.п.) — Title Case, в пилюле `va-gl-cat` после source-текста. Пустая note → без пилюли.
- Раскрытие: аккордеон, несколько строк могут быть открыты одновременно (как в мокапе), chevron поворачивается, `tr.detail` с фоном `--va-surface`.
- Legend-строка внизу — дословно из мокапа.
- Empty-state (uploaded doc без термов): текущий `va-empty` («offline terminology») сохранить.
- Виртуализация не нужна (≤ ~120 групп на seed): обычный рендер, но раскрытая панель — ленивый mount (детали строятся при первом открытии).

## 4. Backend

Изменений API нет: `GET /api/documents/{id}` уже отдаёт terms с нужными json-полями. Проверить, что terms-DTO включает `source_lemma`, `candidates_json`, `trace_json`, `grounded_json` целиком (если что-то отрезано в сериализации — добавить, контракт-SSOT дополнить в том же коммите).

## 5. Тесты

- Vitest: группировка (дубли «Тигр/Тигра» сливаются по лемме; худший difficulty; счётчики саммари); бейдж-выбор по resolved_by; degradation при trace='{}'; mention-клик вызывает переход.
- E2E: скриншоты collapsed-таблицы и всех 4 видов раскрытых панелей (det/llm/rej/none) на seed-документе; клик mention → Document; сравнение глазом с мокапом (агент прикладывает мокап-скрин рядом).

## 6. Риски / открытое

- Реальное наполнение `trace_json` в seed-данных неизвестно до реализации — первым шагом исполнитель делает дамп 3-5 строк term и фиксирует фактические поля в коммит-сообщении; при пустоте trace работает degradation-ветка §2.2/2.3 (это НЕ провал спеки).
- Если `resolved_by` в данных отсутствует вовсе — вычислять эвристикой: qid есть + candidates>1 → llm; qid есть + candidates==1 → label match; qid нет + candidates>0 → rejected; иначе none. Зафиксировать выбор в коде комментарием у эвристики.
