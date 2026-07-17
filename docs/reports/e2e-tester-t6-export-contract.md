# e2e-tester — T6 «Экспорт: новый .md-контракт» (прод glossa-mt.com)

## Scope

Сценарий T6 e2e-мегакампании ([спека](../superpowers/specs/2026-07-17-e2e-mega-campaign.md)) против живого прода https://glossa-mt.com: проверка нового .md-контракта экспорта (commit `6e52919`, SSOT — [demo-contracts § export](../superpowers/specs/2026-06-30-demo-contracts.md)) на всех стадиях жизненного цикла документа. Подпункты (а)–(з) все выполнены: экспорт после создания, во время warming, после refine/restore/ручной правки, .xlsx, негативные 404/422, CJK. Сессия playwright-cli `-s=t6`, эфемерный клон, golden не мутирован. Основной отчёт с таблицей шагов, диффами и provenance: **[docs/reports/e2e/campaign/t6-export-contract.md](e2e/campaign/t6-export-contract.md)**.

Вердикт: **PASS-WITH-FINDINGS** (2 LOW-находки продукта + 1 tooling-наблюдение; багов HIGH/MEDIUM нет; 0 JS-ошибок приложения).

## Files changed

- `docs/reports/e2e/campaign/t6-export-contract.md` — основной evidence-first отчёт (новый).
- `docs/reports/e2e/campaign/t6-files/` — 12 артефактов: `export-a-initial.md`, `export-b-after-refine.md`, `export-c-after-restore.md`, `export-d-after-edit.md`, `export-e.xlsx`, `export-z-cjk.md`, `export-midtranslate-8p-final.md`, `export-midtranslate-raw.txt`, `midtranslate-8p-samples.json`, `negative-checks.json`, `positive-headers.json`, `para2-before-refine.json` (все новые).
- `docs/reports/e2e/shots/campaign/t6/` — 16 скриншотов 01–16 (новые).
- `docs/reports/e2e-tester-t6-export-contract.md` — этот файл.
- Память агента: `~/.claude/agent-memory/e2e-tester/translation-demo-bugs.md` + `MEMORY.md` — паттерны прогона.
- Код/доки продукта НЕ менялись; на проде созданы и затем удалены через UI 4 документа (id 18–21), остался только golden «World History».

## Decisions & rationale

- **(а) и (д) совмещены в одном экспорте**: скачивание .md выполнено в момент «warming 3/8 ¶» + «Extracting terminology…» (скрин 04) — одно действие покрывает оба подпункта, состояние доказано скриншотом до клика.
- **Mid-translate skip проверен парным опросом, а не UI-кликом**: окно гонки ~1 с/абзац не ловится через меню Export; один browser-eval цикл `Promise.all([GET document, GET export])` записал пары (done, mdBlocks) — блоки точно равны done в 5 промежуточных точках. UI-скачивание того же эндпоинта доказано 6 раз отдельно.
- **Заголовок CJK-дока выбран чисто-CJK («秦汉历史») намеренно** — атака на слаг имени файла из гипотез спеки; она и дала находку F1.
- **Precompute включён только для основного дока 18** (~$0.10, нужен для warming-состояния и скоров под refine); CJK-док создан без precompute, translate-доки — принудительно без него (контракт) — экономия бюджета.
- **Негативные проверки — прямым GET из сессии браузера** (разрешено заданием: это и есть интерфейс экспорта), плюс 3 edge-кейса сверх плана (uppercase MD, id=-1, id=abc).

## Open questions

- F1: считать ли generic-fallback `document-{id}.md` для не-ASCII заголовков приемлемым UX или добавить транслитерацию/percent-encoding в `Content-Disposition` (filename*)? Решение за владельцем.
- F2: стоит ли делать `format` case-insensitive? Контракт-литерал сейчас честно 422.
- `playwright-cli select` на React-комбобоксе молча не срабатывает при устаревшем ref — воспроизводимость на других контролах приложения не исследована (tooling, не продукт).

## NOT done (explicit)

- Глубокая проверка структуры .xlsx (стили, ширины колонок, цвета Score) — спека прямо исключает («структура не менялась»); проверено открытие, sheet, header, meta, актуальность ¶2.
- Mid-translate экспорт через само UI-меню Export — окно гонки физически не ловится кликами (причина выше).
- Скачивание экспорта golden-дока 10 — только read-only header-check (CT/CD), контентные проверки — на собственных доках.
- Пара zh→ru (`t2-ru-translation.txt`) — зона T2, для (з) достаточно zh→en.
- Независимый аудит отчёта (sonnet) — по протоколу кампании выполняется оркестратором, не самим агентом.

LLM-ops: ≈21 (precompute 8¶, терм-пайплайны ×2, refine 1, re-evaluate 1, AI-translate 10¶) — flash-lite, в пределах капа $5.
