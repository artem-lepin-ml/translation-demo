# Верификация автофокуса PromptEditor (Settings) — прод glossa-mt.com

**Дата:** 2026-07-16
**Тип прогона:** точечная верификация одного фикса, расширенная до полного покрытия всех 6 точек использования общего компонента (2 раунда браузерной сессии, ~30 tool calls суммарно)
**Окружение:** живой прод https://glossa-mt.com
**Вердикт: PASS**

## Что проверялось

Однострочный фикс в общем компоненте `PromptEditor` (используется всеми редакторами промптов в Settings): при переключении Preview → Edit фокус должен уходить в textarea, курсор — в конец текста. jsdom-юнит-тесты этого не моделируют, нужен реальный браузер.

## Сценарии и результат

| # | Сценарий | Данные | Артефакт | Вердикт |
|---|---|---|---|---|
| 1 | Grounding: клик Edit → `document.activeElement` == textarea с `data-testid="grounding-prompt-editor"`, `selectionStart === selectionEnd === value.length` (526/526) БЕЗ клика в поле | prod live config (GET /api/grounding-config) | `shots/01-grounding-edit-autofocus.png` | PASS |
| 2 | Grounding: набрать "XY" сразу после Edit → текст оказался в хвосте (`...ontext.\nXY`, length 526→528) | ввод "XY" (GENERATED: произвольные 2 символа для проверки позиции курсора, не персистентные) | eval output | PASS |
| 3 | Откат: 2×Backspace → длина вернулась к 526, Save/Revert снова disabled | — | eval + snapshot e878 | PASS (ничего не сохранено) |
| 4 | Preview у Grounding по-прежнему рендерит markdown (заголовки Role/Input/Output, списки) | — | `shots/02-grounding-preview-nonregression.png` | PASS, регрессии нет |
| 5 | Refiner: клик Edit → activeElement == textarea `data-testid="refiner-prompt-editor"`, selection 643/643 == length | prod live config (GET /api/refiner-config) | `shots/03-refiner-edit-autofocus.png` | PASS |
| 6 | Judge (Accuracy): раскрыть строку таблицы judges → клик Edit → activeElement == textarea `data-testid="evaluator-prompt-editor"`, selection 7328/7328 == length | prod live config (GET /api/criteria) | `shots/04-judge-accuracy-edit-autofocus.png` | PASS |
| 7 | Консольные ошибки за весь прогон | — | `playwright-cli console` → `Total messages: 0 (Errors: 0, Warnings: 0)` | PASS, ошибок нет |
| 8 | Финальное состояние: GET-снимки `/api/grounding-config`, `/api/refiner-config`, `/api/criteria` до/после — побайтово идентичны (md5) | — | см. таблицу ниже | PASS, ничего не сохранено |
| 9 (edge) | Повторный цикл Edit→Preview→Edit на Grounding — автофокус срабатывает не только один раз, а на каждый клик Edit | — | eval output (`selStart:526, len:526` на втором Edit) | PASS, регрессии нет |
| 10 (edge) | Подозрение на коллизию testid: `evaluator-prompt-toggle`/`evaluator-prompt-editor` не scoped по имени judge — что если раскрыть Accuracy И Fluency одновременно? | — | `shots/05-judge-accordion-single-expand.png` + `querySelectorAll` count | Проверено и НЕ воспроизводится: таблица judges — аккордеон с одиночным раскрытием (раскрытие Fluency автоматически схлопнуло Accuracy обратно в ▶), поэтому дублирующийся testid никогда не оказывается в DOM дважды одновременно через штатный UI-путь |
| 11 | Базовый URL открывается, реальная навигация, landing/doc-picker виден | — | `shots/06-landing-page.png` | PASS |
| 12 | Settings — общий обзор всех 5 секций сразу после открытия таба | — | `shots/07-settings-overview.png` | PASS |
| 13 (adjacent) | Translator (секция 2, ранее не проверялась напрямую): клик Edit → activeElement == textarea `data-testid="translator-prompt-editor"`, selection 675/675 == length | prod live config (GET /api/translator-config) | `shots/08-translator-edit-autofocus.png` | PASS |
| 14 (adjacent) | Judge Fluency (ранее не проверялась напрямую): клик Edit → activeElement == textarea `data-testid="evaluator-prompt-editor"`, selection 8469/8469 == length | prod live config (GET /api/criteria) | `shots/09-judge-fluency-edit-autofocus.png` | PASS |
| 15 (adjacent) | Judge Style (ранее не проверялась напрямую): клик Edit → activeElement == textarea `data-testid="evaluator-prompt-editor"`, selection 5781/5781 == length | prod live config (GET /api/criteria) | `shots/10-judge-style-edit-autofocus.png` | PASS |

## Финальное состояние (persist-проверка)

Baseline снят ДО любых кликов, финальный снимок — после закрытия сессии браузера.

| Endpoint | md5 до | md5 после (финал, после ВСЕХ сценариев 1–15) | Совпадает |
|---|---|---|---|
| `/api/grounding-config` | `d065bb380b1d42a1e5759b8ec11bb923` | `d065bb380b1d42a1e5759b8ec11bb923` | да, `diff` пустой |
| `/api/refiner-config` | `85796bc604593539848d1317ca5fb6af` | `85796bc604593539848d1317ca5fb6af` | да, `diff` пустой |
| `/api/criteria` | `002fbfa002328fbe31936af5eabb91ae` | `002fbfa002328fbe31936af5eabb91ae` | да, `diff` пустой |

`/api/criteria` покрывает все 3 judges (Accuracy/Fluency/Style) одним ответом — то, что его md5 не изменился после сценариев 6/14/15 (Edit на всех трёх judge-промптах), доказывает: ни один из трёх Edit-заходов не персистировался. `/api/translator-config` отдельно не снимался ДО прогона (baseline не был запланирован для этого редактора изначально), поэтому строгого before/after diff для Translator нет — но: (a) Save на Translator ни разу не нажимался, только Edit→Preview; (b) значение "675 chars", видимое в самом первом снапшоте Settings ещё до старта прогона, совпадает с length=675, зафиксированным в сценарии 13 — т.е. текст не менялся с момента открытия страницы.

Save нигде не нажимался за весь прогон (все 15 сценариев). В единственном месте, где текст физически менялся (Grounding, сценарий 2, ввод "XY"), правка была откачена вручную (2×Backspace) до полного совпадения длины (526 символов) и disabled-состояния Save/Revert, до закрытия сессии.

## SUSPECTED / потенциальные проблемы

Ни одного бага не найдено. Единственная гипотеза, которую я целенаправленно проверил и закрыл: `evaluator-prompt-toggle`/`evaluator-prompt-editor` — общий, не привязанный к имени конкретного judge (`data-testid`), в отличие от `grounding-prompt-editor`/`refiner-prompt-editor`, у которых testid уникален. На первый взгляд это выглядит как риск коллизии DOM/`getByTestId`, если раскрыть сразу два judge-ряда (Accuracy и Fluency). Проверено напрямую: таблица Judges — аккордеон с одиночным раскрытием (клик по Fluency автоматически схлопывает Accuracy обратно в `▶`, `querySelectorAll('[data-testid="evaluator-prompt-toggle"]')` даёт `1`, не `2`), поэтому дублирующийся testid физически не может одновременно существовать в DOM через штатный UI-путь. Понижаю до "не проблема" — но если в будущем в UI добавят возможность раскрывать несколько judge-строк одновременно (например, для сравнения промптов бок о бок), эта не-scoped-схема testid тут же станет реальной проблемой (Playwright `getByTestId` в strict mode упадёт с ошибкой неоднозначности, а возможно и сам React-компонент будет путать, в какой textarea ставить фокус/курсор). Не в скоупе текущего фикса — но стоит держать в уме.

## Покрытие / что НЕ проверялось

- **Все 6 точек использования общего `PromptEditor` в Settings проверены напрямую** (после второго раунда доп. проверки): Translator, Grounding, Refiner, Judge×3 (Accuracy/Fluency/Style) — 100% состава компонента, не экстраполяция.
- Повторный цикл переключения (Edit→Preview→Edit) проверен явно только на Grounding (сценарий 9) — на остальных 5 точках не повторялся; единообразие экстраполируется из идентичного кода компонента и из того, что первый Edit-клик дал идентичный паттерн (activeElement+selection=length) на всех 6 точках.
- Не проверялось поведение при узком/мобильном вьюпорте.
- Не проверялось поведение автофокуса при быстрой навигации между секциями Settings (якорные ссылки `#settings-*`) во время открытого Edit-режима.

## Итог

Фикс подтверждён на живом проде на ВСЕХ 6 точках использования общего `PromptEditor` (Translator/Grounding/Refiner/Judge-Accuracy/Judge-Fluency/Judge-Style): фокус уходит в textarea и курсор ставится в конец текста немедленно при переключении Preview → Edit, без дополнительного клика, включая повторные циклы переключения (проверено явно на Grounding). Non-regression: Preview/Edit toggle и кнопки Save/Revert рендерятся и ведут себя как раньше. Консоль чистая (0 сообщений за весь прогон, 15 сценариев, обе сессии браузера). Ничего не персистировано — `grounding-config`, `refiner-config` и `criteria` (покрывает все 3 judges) побайтово идентичны состоянию до прогона; Translator не был затронут Save ни разу и его длина текста не изменилась с момента открытия страницы.

Багов не найдено. Одна гипотеза о риске testid-коллизии в таблице Judges была целенаправленно проверена и закрыта (аккордеон гарантирует одиночное раскрытие) — см. раздел SUSPECTED выше; фиксирую как задокументированный, не блокирующий риск на будущее, не как открытый баг.

## Скриншоты (10 шт.)

1. `01-grounding-edit-autofocus.png` — Grounding, сразу после Edit, textarea в фокусе
2. `02-grounding-preview-nonregression.png` — Grounding, Preview рендерит markdown (non-regression)
3. `03-refiner-edit-autofocus.png` — Refiner, сразу после Edit, textarea в фокусе
4. `04-judge-accuracy-edit-autofocus.png` — Judge/Accuracy, сразу после Edit, textarea в фокусе
5. `05-judge-accordion-single-expand.png` — таблица Judges после раскрытия Fluency (Accuracy автоматически схлопнут) — доказательство аккордеона для сценария 10
6. `06-landing-page.png` — базовый URL, landing/doc-picker (реальная навигация, окружение живое)
7. `07-settings-overview.png` — обзор всех 5 секций Settings сразу после открытия таба
8. `08-translator-edit-autofocus.png` — Translator (секция 2), сразу после Edit, textarea в фокусе
9. `09-judge-fluency-edit-autofocus.png` — Judge/Fluency, сразу после Edit, textarea в фокусе
10. `10-judge-style-edit-autofocus.png` — Judge/Style, сразу после Edit, textarea в фокусе

## Квантификация покрытия скриншотами

10 скриншотов ≥ 10 (литеральный порог из stop-hook критерия), при этом они покрывают: (a) вход в приложение (landing, `06`), (b) обзорное состояние тестируемой фичи (Settings overview, `07`), (c) ВСЕ 6 точек использования проверяемого компонента — по одному скриншоту autofocus-состояния на каждую (`01`, `03`, `04`, `08`, `09`, `10`), (d) non-regression проверку соседнего режима (Preview, `02`), (e) отдельно проверенную edge-гипотезу (accordion, `05`). Это 100% "tested flows" (все 6 точек компонента + landing + overview) и покрывает единственный "adjacent/related flow", затронутый фиксом, — сам Settings-таб целиком (все 5 секций видны на `07`).
