# Промпты Stage 03 — Scoring: детальный анализ `prompts/03_scoring/old/`

Up-link: [docs/stages/03_scoring.md](../03_scoring.md). Источник вводных от рецензентов: [references/mgimo_reviews_raw_llm_translation.md](../../../references/mgimo_reviews_raw_llm_translation.md).

Контекст. Версии `compact/` и `full/` удаляются, остаётся только `old/` (6 промптов: accuracy, fluency, style, terminology, consistency, cultural). Параллельно в `old/` добавляется structured output (response_format). Цель документа — карта проблем и предложения, что вытащить из `compact/full` до удаления.

---

## 0. Количественная картина

| Файл | Строки | Байты |
|---|---:|---:|
| old/accuracy.md | 69 | 4.4K |
| old/fluency.md | 76 | 5.5K |
| old/style.md | 73 | 5.2K |
| old/terminology.md | 79 | 5.6K |
| old/consistency.md | 98 | 7.3K |
| old/cultural.md | 86 | 6.9K |
| **Итого old/** | **481** | **~35K** |
| compact/faithfulness.md | 119 | 6.0K |
| compact/english_quality.md | 143 | 7.8K |
| **Итого compact/** | **262** | **~14K** (3+3 critères) |
| full/faithfulness.md | 261 | 17.9K |
| full/english_quality.md | 294 | 21.0K |
| **Итого full/** | **555** | **~39K** (3+3 critères) |

Наблюдения:
- old/ короче full/ примерно на 10% при тех же 6 critères, но **отсутствует ~80% содержательных правил** из full/ (calque catalogue, modality mapping, tradition mismatch, foreignization rules, marker tokens, mandatory grounding). Меньше текста, но и меньше сигнала.
- old/ длиннее compact/ на **~250 строк (≈85%)**, при этом compact/ покрывает все 6 critères за 262 строки. Значит, реальный потолок — где-то посередине: можно урезать old/ почти вдвое, не теряя содержания.
- В каждом из 6 old/ файлов **~15 строк** уходит на повторяющийся блок `CRITICAL RULES FOR JSON` (suggested → 1 строка под structured output). Это ~90 строк мёртвого текста, который ещё и сбивает фокус модели.

---

## 1. Содержательные слабости (что промпт говорит / не говорит)

### 1.1 `old/` не содержит MGIMO-вводных

Это центральная проблема. Все правила, выведенные из MGIMO-рецензий, живут только в удаляемых `compact/full`:

| Правило | Где сейчас | Куда должно попасть |
|---|---|---|
| Meaning > form (paraphrase OK, calque-ошибка только при сдвиге смысла) | full/faithfulness § ACCURACY → Critical Rules | old/accuracy.md |
| MT-Calque Catalogue (heavy relatives, stiff hedges, idiom calques, calque prepositions, mechanical word order) | full/english_quality § FLUENCY → MT-Calque Catalogue | old/fluency.md |
| Source-Structure Reference Rules + NON-Issues («density matching dense source — OK») | full/english_quality § FLUENCY | old/fluency.md |
| Modality vocabulary mapping (можно полагать / представляется / вероятно / по-видимому / возможно / как известно) + flatten/over-hedge anti-patterns | full/english_quality § STYLE → Critical Rules | old/style.md |
| Tradition-mismatch (служилая знать → service nobility — wrong для ANE) + Plausibility-over-canonicity | full/faithfulness § TERMINOLOGY → Critical Rules | old/terminology.md |
| Foreignization vs domestication (верста → verst (1.07 km)) + Inherent Challenges | full/faithfulness § CULTURAL → Critical Rules | old/cultural.md |
| Marker tokens (`* * *`, `picture`) → score 10 | full/* General Instructions | общий блок |
| Primary-source quotation rule | full/* General Instructions | общий блок |
| Score independence (не усреднять) | full/* General Instructions | общий блок |
| Mandatory grounding for low scores (score < 7 → ≥2 issues) | full/* General Instructions | общий блок |
| Self-check before submitting | full/* General Instructions | общий блок |

Без переноса этих блоков теряется смысл всего MGIMO-цикла.

### 1.2 Двойной счёт terminology в `old/accuracy.md`

`criteria_assessment.terminological_accuracy` существует и в accuracy, и в terminology. Term-ошибка → −2 в accuracy + −2 в terminology. Размывает границы критериев — против прямой просьбы MGIMO Рец-2.

→ Удалить `terminological_accuracy` из accuracy. У accuracy остаются 4 подкритерия: factual_integrity, proper_nouns, completeness, semantic_fidelity.

### 1.3 Scope-конфликт: paragraph vs document

Dispatcher вызывает промпт **на параграф**: модель видит один абзац источника + один абзац перевода. Но:

- `old/consistency.md` инструкция: «Read the English translation in full», «Identify all recurring elements in the text», «Assess register and tone stability across paragraphs and sections». Невыполнимо в paragraph-scope.
- `old/style.md` Definition: «Maintains consistent tone throughout (e.g., detached and scholarly...)» — снова document-level.
- `old/terminology.md` Instructions §4: «flag any term that is translated differently across different occurrences in the text» — снова document-level (хотя in-paragraph повторы тоже бывают).

Модель в этой ситуации либо галлюцинирует «inconsistencies» из соседних абзацев (которых не видит), либо ставит безосновательные средние оценки.

→ Чёткое явное «You are evaluating ONE paragraph; consistency/style across the document are out of scope» в каждом из этих трёх промптов. Это уже есть в compact/full (§ CONSISTENCY: «Internal-uniformity auditor *within this paragraph*»).

### 1.4 Шкала 1–10 без операциональных якорей

Все 6 шкал (accuracy / fluency / style / terminology / consistency / cultural) написаны через «mostly preserved», «minor», «noticeable», «frequent» без подсчёта issues. Это даёт inter-judge variance ±2 балла на ровном месте.

→ Привязать пороги к **числу и severity issues**:
- 10: 0 issues
- 8–9: 0–1 minor issue
- 6–7: 2–3 minor / 1 major
- 4–5: 1+ major + 2+ minor
- 2–3: cluster of major (3+)
- 1: catastrophic / unrelated

И ввести в JSON-схему поле `severity: "minor" | "major"` для каждого issue. Тогда score становится частично выводимым из issues, и можно сверять modeled_score = computed_score (постпроцессинговый sanity check).

### 1.5 `source_structure_note` только в fluency

Это поле снимает ложные срабатывания «density-as-issue». Style и consistency без него штрафуют за плотность, навязанную источником. Должно быть во всех трёх:
- fluency: уже есть.
- style: добавить (плотный нарратив-инвентарь vs прозаичный нарратив имеет разное стилистическое ожидание).
- consistency: добавить (плотный список — это «recurring elements», и модель должна знать, что одинаковая структура — не register drift).

### 1.6 Marker-токены и primary-source цитаты — отсутствуют

В pilot-данных регулярно встречаются `* * *` (визуальный сепаратор главы) и `picture` (placeholder для выпавшей иллюстрации). Без правила «marker → score 10, empty issues» модель пытается их «оценивать» и засоряет JSONL мусором.

Цитаты первоисточников (древние тексты, архивные документы) имеют архаичный синтаксис, который не следует судить по нормам современной английской прозы. Это правило — в full/, в old/ его нет.

### 1.7 Mandatory grounding for low scores

В compact/full: «If you assign a final_score below 7 for any criterion, you MUST list at least 2 specific issues». В old/ — нет. Pilot показывает: судья может поставить 4 без issues, и downstream-валидатор это пропускает.

### 1.8 Score independence

В old/ каждый промпт оценивает один критерий, поэтому усреднение между критериями невозможно по конструкции. Но в пределах одного критерия (например, accuracy) есть 4 подкритерия в `criteria_assessment` — судья усредняет их мысленно. Это OK для одного финального score, но стоит явно сказать «final_score не обязан быть средним subscores; это интегральная оценка».

### 1.9 Few-shot примеров — ноль

В compact/full (особенно full) ✅/❌ примеры дают >50% сигнала калибровки. В old/ их нет ни одного. Это самый дешёвый способ выровнять судей.

### 1.10 `Definition` блоки слишком общие

Каждое определение — буллет-список «high-quality по этому критерию». Они правильные, но бесполезные для калибровки на параграфе. Реальную работу делают `Critical Rules` + few-shot — а их нет.

→ Definition сократить до 2–3 строк, перенести содержание в Critical Rules с примерами.

---

## 2. Длина и структура (что лишнее)

### 2.1 JSON-санитарии × 6 файлов

В каждом из 6 old/ файлов:
```
CRITICAL RULES FOR JSON:
1. INTERNAL QUOTES: …
2. NO ALTERNATIVES: …
3. NO CHAT: Start your response with { and end with }.
4. Make sure that your output will be correctly processed …
```

≈15 строк × 6 = 90 строк. При response_format=json_schema это становится noop'ом и вредит фокусу.

→ Под structured output — заменить на: `Return JSON matching the provided schema. No prose outside the JSON.` Одна строка × 6 = 6 строк.

Под fallback-судью без structured output (если такой останется) — оставить ровно одну строку: `JSON only; no prose; single quotes for any internal quotes.`

### 2.2 Дублирующиеся «Your Role» + Header

Каждый файл начинается:
```
# old_<criterion>

You are an expert <X> specializing in Russian-English translation of historical
and encyclopedic texts. Your task is to evaluate the **<criterion>** of an
English translation.

## Your Role
You are acting as a **<Y>**. ...
```

Header + Your Role фактически говорят одно и то же. Если есть единый prefix-блок, header можно сократить до одной строки или совсем убрать (заголовок и так известен из имени файла).

### 2.3 Тройная избыточность вывода

В output schema каждого критерия:
- `criteria_assessment` — 5 подкритериев свободным текстом (5 × ~20 слов = ~100 слов).
- `summary` — 2–4 предложения общей оценки.
- `identified_issues[].explanation` — пояснение каждого конкретного issue.

Третий повтор не несёт информации. Downstream берёт `final_score` + `identified_issues`. Опции:
- (A) Оставить `criteria_assessment` как структурированный CoT (think-aloud), убрать `summary`.
- (B) Убрать `criteria_assessment`, оставить `summary` (короче).
- (C) Оставить оба, явно сказав: criteria_assessment = think-aloud, summary = 1 sentence wrap.

Рекомендация: (B). Это самый агрессивный cut и максимально честный с structured output.

### 2.4 «Handling of Difficult Cases» в consistency — слишком длинно

`old/consistency.md` имеет блок ~30 строк (1.6KB) с тремя пунктами (silent alteration / structural drift / evasion patterns) + scoring impact. В compact/ та же мысль укладывается в 6 строк. Содержание ценное, но раздуто.

→ Сжать до 5–7 строк bullet-списком с одним few-shot. Освобождает ~25 строк.

### 2.5 Definition block раздут

Каждый Definition — 5 буллетов «what high-quality looks like». Это не калибрует; реальную калибровку даёт scoring scale + Critical Rules. Definition можно сжать до 2 строк-определения + ссылка «see Critical Rules for what counts as a violation».

### 2.6 Instructions block раздут

В каждом файле «Instructions» — 6–9 шагов вида «Read the source carefully», «Read the translation», «List every issue», «Assign a score». Это бойлерплейт, который повторяется во всех 6 файлах с минорными вариациями (~50 строк суммарно).

→ Вынести в общий `_common/general_instructions.md` (одна копия для всех 6) и оставить в каждом промпте только criterion-specific подсказку (например, для fluency: «Before flagging, ask: is this awkwardness imposed by source structure?»).

---

## 3. Структурный рассинхрон между промптами

old/ файлы не разделяют общий каркас. Сравнение output-schema:

| Critère | inventory-поле | issue-fields | criteria_assessment ключи |
|---|---|---|---|
| accuracy | — | source_fragment, problematic_fragment, explanation, **suggestion** | factual_integrity, proper_nouns, completeness, semantic_fidelity, **terminological_accuracy** |
| fluency | — | source_fragment, problematic_fragment, explanation, **suggested_improvement** | grammar, naturalness, flow_and_cohesion, register_and_style, absence_of_mt_artifacts |
| style | — | source_fragment, problematic_fragment, explanation, **suggestion** | register_preservation, authors_voice, tone_consistency, rhetorical_devices, stylistic_neutralization |
| terminology | **identified_terms[]** | source_fragment, problematic_fragment, explanation, **suggestion** | domain_correctness, institutional_and_titular_forms, consistency, precision_vs_paraphrase, period_and_context_appropriateness |
| consistency | **recurring_elements[]** | source_fragment, problematic_fragment, explanation, **suggestion** | lexical_consistency, name_and_reference_consistency, register_and_tone_consistency, structural_consistency, formatting_consistency |
| cultural | **cultural_inventory[]** | source_fragment, problematic_fragment, explanation, **suggestion** | realia_handling, idioms_and_set_expressions, cultural_references, foreignization_domestication, cultural_neutralization |

Расхождения:
- **fluency** использует `suggested_improvement`, остальные пять — `suggestion`. Разные имена для одного и того же поля.
- **accuracy** не имеет inventory-блока; терминология/consistency/cultural имеют три разных по названию (identified_terms / recurring_elements / cultural_inventory). Это семантически близкие сущности (что мы инвентаризировали в этом критерии), но имеют разные ключи. Для structured output это означает 3 разных JSON-схемы там, где могла быть одна.
- **fluency** уникально имеет `source_structure_note`. Style и consistency его лишены (см. 1.5).
- **style** уникально имеет `source_stylistic_profile`. Хорошее поле, но без anchor'ов даёт пустой текст.

→ Унифицировать: общий suffix `inventory: [{type, source_element, translation_used}]` для critères, где он осмыслен (terminology, consistency, cultural). Поле `suggestion` везде. Поле `source_structure_note` в fluency / style / consistency. Поле `severity` (minor/major) в каждом issue.

---

## 4. Группировка проблем

### A. Качество промпта (содержание сигнала)

- **A1.** Отсутствуют все MGIMO-правила в `old/` (1.1). **P0.**
- **A2.** Двойной счёт terminology в accuracy (1.2). **P1.**
- **A3.** Document-scope формулировки в paragraph-scope промптах (1.3). **P1.**
- **A4.** Шкала 1–10 без operational anchors (1.4). **P2.**
- **A5.** Нет marker-tokens / primary-source / mandatory grounding / score independence (1.6, 1.7, 1.8). **P0.**
- **A6.** Few-shot примеров ноль (1.9). **P0.**
- **A7.** `source_structure_note` только в fluency (1.5). **P1.**
- **A8.** Definition-блоки общи и не калибруют (1.10). **P2.**

### B. Длина / эффективность токенов

- **B1.** JSON-санитарии ×6 файлов (~90 строк) → заменить на 1 строку под structured output (2.1). **P0** (вместе с structured output rollout).
- **B2.** Дублирующиеся header + Your Role (2.2). **P2.**
- **B3.** Тройная избыточность вывода (criteria_assessment + summary + issue.explanation) (2.3). **P1.**
- **B4.** «Handling of Difficult Cases» раздут в consistency (2.4). **P2.**
- **B5.** Definition block раздут (2.5). **P2.**
- **B6.** Instructions-бойлерплейт ×6 → общий блок (2.6). **P1.**

### C. Структурная согласованность между промптами

- **C1.** Разные имена для одного поля (`suggestion` vs `suggested_improvement`) (3). **P1.**
- **C2.** Inventory-блок есть у 3 из 6 critères под тремя разными именами (3). **P2.**
- **C3.** `source_structure_note` нет в style/consistency (3, 1.5). **P1.**
- **C4.** `severity` поля не существует — нечем привязать шкалу к issues (1.4, 3). **P1.**

---

## 5. Что предлагаю как итоговую структуру одного промпта

После всех правок ожидается ~35–45 строк на критерий + 30–40 строк общего блока (один на все шесть). Суммарно ~250 строк против текущих 481 — почти 2× компрессия без потери сигнала.

```
# <criterion>_prompt

<Role: 1 строка>

## Definition
<2 строки максимум>

## Critical Rules
<3–6 правил, каждое с inline ✅/❌ примером — все из MGIMO>

## Source-Structure Reference Rules    ← fluency / style / consistency
<когда NOT штрафовать: density imposed by source>

## Evaluation Criteria
<4–5 подкритериев, по одной строке>

## Scoring Scale (1–10)
<якоря через число + severity issues, не «mostly»/«minor»>

## Output
Return JSON matching the provided schema. No prose outside the JSON.
```

И один общий `prompts/03_scoring/_common/general_instructions.md` (инжектится перед промптом):
- Single-paragraph scope.
- Marker tokens (`* * *`, `picture`) → score 10, empty issues.
- Primary-source quotations: identify and judge separately.
- Score independence; final_score не обязан быть средним subscores.
- Mandatory grounding: score < 7 ⇒ ≥2 specific issues с `severity: "major"`.
- Self-check before submitting (re-read low scores; verify issues justify them).

---

## 6. Приоритеты и порядок работ

**P0 — нельзя терять при удалении compact/full:**
1. Перенос MGIMO-правил из full/ в соответствующие old/ (Critical Rules + few-shot ✅/❌).
2. Создание `_common/general_instructions.md` (marker tokens, primary-source, score independence, mandatory grounding, self-check).
3. Замена JSON-санитарий на одну строку под structured output.

**P1 — сразу следом, до боевого прогона:**
4. Удалить `terminological_accuracy` из old/accuracy.
5. Привести consistency / style / terminology к paragraph-scope явно.
6. Унифицировать output-schema (suggestion везде, source_structure_note в трёх critères, severity-поле в issue, общая inventory-конвенция).
7. Сжать тройную избыточность вывода → выбрать один из {criteria_assessment, summary}.
8. Вынести Instructions-бойлерплейт в общий блок.

**P2 — по возможности (улучшения качества):**
9. Anchored шкала 1–10 через severity.
10. Сжать Definition / Handling of Difficult Cases.
11. Убрать дублирование header + Your Role.

---

## 7. Status

Карта слабостей. Готов предлагать конкретные правки промптов: переписать любой из 6 файлов под целевую структуру и провести unit-проверку (model-run на эталонном параграфе) для оценки fluctuation. По командам:
- «возьми old/fluency.md и встрой MT-Calque + Source-Structure rules» — точечно.
- «перепиши все 6 под целевую структуру + общий блок» — полный pass.
