# Спека: guard от advice-текста в suggestion (волна 3, задача 1) — rev-2

Дата: 2026-07-02. Ветка: `feat/suggestion-guard`. Статус: **rev-2 после /verify-spec (3 аспекта: 1 CRITICAL, 2 HIGH закрыты)**.

**Done when:** ни один Accept не может вставить в перевод советы судьи; guard стоит на ВСЕХ ТРЁХ путях инжеста issue; на корпусе (локальная БД + прод) 0 advice-suggestion'ов доступны к Accept; честные suggestion'ы byte-identical не тронуты.

## Проблема (CRITICAL, воспроизведена)

Судья иногда кладёт в `suggestion` **совет, а не текст замены**; apply-edit вклеивает его дословно (кейс владельца: «…Consider 'temple centers' with a brief gloss if needed…» в тексте перевода, метрики рухнули). Подтверждено на данных: в `data/seed/seed_paragraphs.jsonl` 2 advice-кейса из 195 непустых suggestion (включая «Use 'debt bondage', which is the standard…» = прод-issue id=47).

## Архитектура инжеста (verify-spec, 3 агента сошлись)

Путей инжеста **три**, не два: (1) live evaluate и (2) precompute — оба через `judge.py:_issue_from()` (единственная точка сборки issue-dict из сырого JSON судьи); (3) **`seed.py:103-109`** — независимый INSERT из seed JSONL, для демо-документа это ОСНОВНОЙ путь, и каждый `POST reset` реоткрывает seed-issues с нетронутым suggestion.

## Решение — три слоя

1. **Systematic debugging first** (`superpowers:systematic-debugging`): корпус = (а) локальная `data/demo.db` (та самая, 195 suggestion), (б) прод через `ssh … docker exec gse-demo python -c "<dump>"` (read-only). Классифицировать advice-подобные; **отдельно перечислить `status='accepted'` строки с advice-suggestion** и проверить, не въелся ли их текст в `paragraph.target`/`seed_target` (если въелся в seed_target — reset НЕ лечит, только seed-refresh). Частота по критериям/моделям. Корпус = тест-набор слоёв 2–3.
2. **Промпт-контракт — в `judge.py:scoring_system_prompt()` preamble** (единый code-level seam, уже несёт language-контракт), НЕ в 5 md-файлов: «`suggestion` = ТОЛЬКО drop-in замена problematic_fragment на языке перевода; никаких советов/альтернатив/мета („Consider/Use/if needed"); нет конкретной замены → пустая строка (советы — в explanation)». Заметка: `fluency.md` вообще не эмитит suggestion — out of scope; schema-строки 4 остальных файлов не трогаем (preamble их накрывает).
3. **Guard `looks_like_advice(suggestion: str) -> bool`** — чистая функция в `judge.py`, вызывается из: `_issue_from` (накрывает live+precompute) И цикла вставки issue в `seed.py` (как `derive_severity` там же). Эвристика: (а) английский словарь advisory-стартов (Consider|Use|Retain|Prefer|Keep|Avoid|Note|Try|Opt for) и мета-маркеров («the translation», «if needed», «if context requires», «gloss»), (б) языко-независимые структурные сигналы: варианты через `'X'/'Y'` или слэш + пояснительная клауза, длина > 3× фрагмента при наличии кавычек-альтернатив. Скоуп: полноту гарантируем для ru→en; для прочих пар — только структурные сигналы (зафиксировано в Не делаем). Срабатывание → suggestion переносится в конец explanation (`Advice: …`), поле пустеет → UI сам прячет Accept (проверено: сервер 422 no_suggestion + клиент-скип + все 3 рендера кнопки — путь уже отработан на 45 пустых seed-issues). Guard **идемпотентен** (повторный прогон по уже-очищенному dict — no-op; юнит-тест).

## Ремонт данных

Полный ремонт — ресид ветки `feat/seed-refresh` (та спека суперсидит; порядок: guard мержится ПЕРВЫМ, чтобы регенерация шла уже под контрактом). `POST reset` — фолбэк ТОЛЬКО при подтверждённой чистоте `seed_target` (проверка в слое 1); иначе явно ждём seed-refresh. Остаточный риск (реоткрытый seed-issue с advice можно принять снова до seed-refresh) закрывается guard'ом в seed.py — вычистка на вставке.

## Не делаем

- Не меняем схему ответа судьи; не переоцениваем существующие issue задним числом (кроме корпус-отчёта слоя 1 и seed-time вычистки при вставке — это свежий инжест, не re-score).
- Полный мультиязычный словарь advisory-глаголов (12+ языков) — не сейчас; структурные сигналы + ru→en словарь.

## Критерии успеха

1. pytest: guard-юниты (3 реальных кейса + структурные + идемпотентность + негативные на честных заменах); guard вызывается на всех 3 путях (тест на seed: сид с подсаженным advice → suggestion пуст, explanation несёт Advice).
2. Прогон эвристики по корпусу: срабатывания перечислены, 0 ложных (byte-identical чек нефлагнутых), отчёт с числами.
3. e2e: Accept-all на абзаце с advice-suggestion не вставляет советы.
4. После seed-refresh ресида — повторный прогон эвристики по новому корпусу (re-validation trigger, дифф к baseline-отчёту).
5. Doc-parity: webapp.md (контракт suggestion + guard) тем же коммитом.
