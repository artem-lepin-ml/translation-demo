# План: фиксы по аудиту сайта + редизайн Evaluators (2026-07-02)

Up-link: [docs/README.md](../../README.md) · Основание: [отчёт аудита 2026-07-02](../../reports/2026-07-02-site-audit.html) (доказательства: file:line и скриншоты в `docs/reports/audit-shots/`).

## Цель

Закрыть **все** находки аудита (5 HIGH + 5 MEDIUM) и выполнить запрошенный владельцем редизайн секции **Evaluators** в Settings (горизонтальные full-width строки как у Model Registry, клик → инлайн-редактор, вес — только числовое поле, без ползунка). Дедлайн-контекст: демо EMNLP ~10 июля.

## Архитектура (что меняем)

| Слой | Файлы | Что происходит |
|---|---|---|
| Frontend (variant-a) | `frontend/src/demo/variant-a/*` , `frontend/src/demo/store.ts`, `frontend/src/demo/api-client.ts` | CSS-фикс difficulty, редизайн Evaluators, error-стейт evaluate, скролл из Ranking, confirm-диалоги, батч re-judge |
| Frontend (удаление) | `frontend/src/demo/variant-b/`, `frontend/src/demo/data.ts`, `frontend/src/Router.tsx` | Полное удаление legacy-UI (~1 700 LOC) ПОСЛЕ портирования паттерна expand-строк в variant-a |
| Backend | `src/palimpsest/webapp/app.py`, `budget.py` | Новый `PATCH /api/issues/{id}` (персист Dismiss), `GET /api/budget` + admin-reset, `settle()` под локом |
| Тесты | `tests/test_issue_status.py`, `tests/test_budget.py`, `frontend/src/demo/*.test.ts(x)` | Backend-юниты + минимальный vitest-смоук фронта |
| Доки | `docs/subsystems/webapp.md`, `docs/superpowers/specs/2026-06-30-demo-contracts.md`, `docs/known_issues.md`, спеки/goals | Doc-parity в том же коммите, что и код (правило sync) |

## Технологии

- Frontend: React 19 + TypeScript 5.7 + Vite 6 + Zustand 5 + TipTap 3; тесты — **vitest + jsdom + @testing-library/react** (добавляются в задаче 11).
- Backend: FastAPI + SQLite (`src/palimpsest/webapp/`), тесты `uv run pytest -q` (базовая линия: **126 passed**).
- Браузерные проверки: `playwright-cli` сессия `-s=fixplan`, приложение уже запущено: frontend `http://localhost:5173/`, backend `:8000`.

## Как выполнять

- Рабочая копия: `/Users/a1111/Projects/Work/worktrees/term-consolidated` (ветка `dev-demo`). Для работы создать ветку `feat/audit-fixes` от `dev-demo` (инвариант репо №5), PR в `dev-demo`.
- Задачи выполнять **по порядку** (задача 5 зависит от 2; задача 11 — от 3, 4, 9). Один коммит на задачу; сообщение коммита указано в каждой задаче (Conventional Commits, английский, императив, **без** трейлера `Co-Authored-By`).
- **Глобальные ограничения:** не редактировать `data/raw/` и `factowl/`; LLM-вызовы только через `palimpsest.llm.client.LLMClient` (новых LLM-вызовов в этом плане нет); тесты НЕ ходят в реальный OpenRouter (вся сеть мокается); wire-DTO из `2026-06-30-demo-contracts.md` меняются только аддитивно (новые эндпоинты/поля, ничего не ломаем).
- **Платные действия в браузере запрещены:** не нажимать Evaluate/Test; Accept вызывает платный re-judge — при браузерных проверках использовать только бесплатные операции (Dismiss, Reset, Ranking, Settings-правки, PATCH текста).

---

## Задача 1. Difficulty-светофор терминов: дописать CSS-правила `difficulty-*` (HIGH H1)

**Причина (1 строка):** компоненты вешают классы `difficulty-green|yellow|red` ([EditorParagraph.tsx:256,267](../../../frontend/src/demo/variant-a/EditorParagraph.tsx#L256), [TermPopover.tsx:37](../../../frontend/src/demo/variant-a/TermPopover.tsx#L37)), а CSS определяет только `.va-term-dot.green/.yellow/.red` ([variant-a.css:450–452](../../../frontend/src/demo/variant-a/variant-a.css#L450)) и `.va-term-span-source.verdict-*` ([variant-a.css:416–432](../../../frontend/src/demo/variant-a/variant-a.css#L416)) — все 269 точек серые, рамки спанов бесцветные.

**Файл:** `frontend/src/demo/variant-a/variant-a.css`

**Что сделать:** после строки 452 (`.va-term-dot.red { background: var(--va-red); }`) добавить:

```css
/* RU-side terms emit difficulty-* (see SourceWithTerms / TermPopover);
   keep colours identical to the verdict-* rules above. */
.va-term-dot.difficulty-green { background: var(--va-green); }
.va-term-dot.difficulty-yellow { background: var(--va-yellow); }
.va-term-dot.difficulty-red { background: var(--va-red); }

.va-term-span-source.difficulty-green {
  border-color: var(--va-green);
  background: rgba(61, 220, 132, 0.07);
}
.va-term-span-source.difficulty-yellow {
  border-color: var(--va-yellow);
  background: rgba(224, 175, 104, 0.08);
}
.va-term-span-source.difficulty-red {
  border-color: var(--va-red);
  background: rgba(247, 118, 142, 0.08);
}
```

(rgba-значения — точная копия существующих `verdict-*` правил, чтобы обе стороны выглядели одинаково.)

**Проверка:**
1. `cd frontend && npm run build` → exit 0.
2. Браузер (playwright-cli, `-s=fixplan`): открыть `http://localhost:5173/`, вкладка Document, выполнить JS:
   ```js
   [...document.querySelectorAll('.va-term-dot')]
     .map(d => getComputedStyle(d).backgroundColor)
     .filter((v, i, a) => a.indexOf(v) === i)
   ```
   Ожидаемо: **≥2 различных непрозрачных цвета** (до фикса — один `rgba(0, 0, 0, 0)`). Скриншот Document: точки у терминов зелёные/жёлтые/красные, рамки RU-спанов подцвечены.

**Коммит:** `fix(frontend): add difficulty-* CSS rules so the term difficulty signal renders`

---

## Задача 2. Редизайн Evaluators: full-width строки + клик → инлайн-редактор, вес без ползунка (запрос владельца)

**Причина (1 строка):** текущая секция ([SettingsTab.tsx:91–225](../../../frontend/src/demo/variant-a/SettingsTab.tsx#L91)) — узкий левый список + постоянно открытый правый редактор со слайдером веса (строки 182–190); владелец требует паттерн Model Registry (полноширинные строки, раскрытие по клику, «ползунок — это оверкил»).

**Паттерн-источник:** секция Model Registry в том же файле (строки 230–282) — `<table className="va-table">` + `<Fragment>` с дополнительной `<tr>` (colSpan) при `expanded` (так вставляется TestResultCard). Из старого variant-b ([VariantB.tsx:388–414](../../../frontend/src/demo/variant-b/VariantB.tsx#L388)) портируем стоящее: **свёрнуто по умолчанию** (`openEvalId: null`), клик по заголовку-строке — toggle, **шеврон-индикатор** (`vb-eval-chevron` → новый `va-eval-chevron`), **числовой инпут веса без слайдера** (VariantB.tsx:455–466). Новых дизайн-токенов не вводим — только существующие `--va-*`.

**Макет (открыть в браузере):** [docs/reports/mockups/evaluators-redesign.html](../../reports/mockups/evaluators-redesign.html) — pixel-real: токены и `va-*` стили скопированы из `variant-a.css`, данные — реальный сид (`seed.py: CRITERIA`, модель `openai/gpt-5.4-mini`). На одной странице оба состояния: (A) всё свёрнуто, (B) Terminology раскрыта, плюс референс Model Registry; строки кликабельны (аккордеон на инлайн-JS) — интеракцию можно пощупать. Проверен в Chromium: аккордеон, toggle, чекбокс без раскрытия, отсутствие слайдера — все проверки зелёные.

### 2.0 Детализация дизайна (утверждаемая спецификация)

**Анатомия строки** (слева направо, колонки `va-table`):

| # | Колонка | Ширина | Содержимое и стиль |
|---|---|---|---|
| 1 | Цвет | 24px | дот `va-evaluator-color-swatch` 12×12, `background: c.color` |
| 2 | Name | авто (основная) | `font-weight: 600`, цвет `--va-text` |
| 3 | Model | авто | `--va-font-mono` 12px, цвет `--va-text-dim` |
| 4 | Weight | 70px | число как есть (`0.3`, `0.15`) |
| 5 | Enabled | 70px | нативный `checkbox`, кликается в строке |
| 6 | Шеврон | 24px | `va-eval-chevron` ▶, в раскрытом — поворот 90° |

Обрезание/переносы: специального truncation не вводим — поведение как у соседней Model Registry (та же `va-table`, при нехватке места ячейка переносит строку). Отступы — стандартные `va-table th/td` (8px/10px × 12px), ничего не переопределяем.

**Раскрытый редактор** (вложенная `<tr>` c `colSpan={6}`, контейнер `va-evaluator-detail` без рамки): порядок полей Name → Color → Model (select из живого реестра) → Weight → Scale (read-only «1 – 10») → Prompt (read-only preview) → строка действий с **Remove** (слева внизу, `va-btn-secondary`). **Enabled в редакторе НЕ дублируется** — он живёт только в строке.

**Правила интеракции:**
- Свёрнуто по умолчанию: `const [expandedId, setExpandedId] = useState<string | null>(null)`.
- Аккордеон: раскрыта максимум **одна** строка; клик по другой строке закрывает предыдущую; повторный клик по раскрытой — сворачивает.
- Hover строки: подсветка ячеек `--va-surface2` (как у Model Registry); курсор `pointer`.
- Чекбокс Enabled: `stopPropagation` — переключает критерий (`PUT /api/criteria/{id}`) **без раскрытия**; у выключенного критерия вся строка притушена (`opacity: 0.55`).
- «+ Add evaluator»: полноширинная пунктирная кнопка `va-add-eval-btn` **под таблицей**, видна всегда независимо от раскрытий; поведение прежнее (заглушка-no-op, не в скоупе этой задачи).

**Weight — числовое поле (слайдер удалён):** `type="number"`, `min={0}`, `max={1}`, `step={0.05}`, `lang="en"` (десятичная точка вместо локальной запятой — попутно закрывает LOW-замечание аудита про «0,3»), парсинг `parseFloat(e.target.value) || 0`.

**Файлы:** `frontend/src/demo/variant-a/SettingsTab.tsx`, `frontend/src/demo/variant-a/variant-a.css`, `docs/subsystems/webapp-ui-design.md`. Макет: `docs/reports/mockups/evaluators-redesign.html` (уже создан, менять только при отклонении реализации от него).

### 2.1 SettingsTab.tsx

а) Заменить состояние выбора (строки 36–37):

```tsx
// было:
//   const [selectedId, setSelectedId] = useState<string | null>(criteria[0]?.id ?? null);
//   const selected = criteria.find((c) => c.id === selectedId) ?? null;
const [expandedId, setExpandedId] = useState<string | null>(null); // collapsed by default
```

б) Удалить функцию `updateField` (строки 82–85) — она переезжает в `EvaluatorEditor` (ниже).

в) Заменить весь JSX секции Evaluators (строки 89–225, от `<div className="va-settings-section-title">Evaluators</div>` до закрытия `</div>` блока `va-settings-layout` включительно) на:

```tsx
      {/* ─── Criteria (Evaluators) — full-width rows, Model Registry pattern ── */}
      <div className="va-settings-section-title">Evaluators</div>
      <table className="va-table">
        <thead>
          <tr>
            <th style={{ width: 24 }} />
            <th>Name</th>
            <th>Model</th>
            <th>Weight</th>
            <th>Enabled</th>
            <th style={{ width: 24 }} />
          </tr>
        </thead>
        <tbody>
          {criteria.map((c) => {
            const isOpen = expandedId === c.id;
            return (
              <Fragment key={c.id}>
                <tr
                  className={`va-eval-row${!c.enabled ? ' disabled' : ''}`}
                  onClick={() => setExpandedId(isOpen ? null : c.id)}
                >
                  <td>
                    <span className="va-evaluator-color-swatch" style={{ background: c.color }} />
                  </td>
                  <td style={{ fontWeight: 600 }}>{c.name}</td>
                  <td style={{ fontFamily: 'var(--va-font-mono)', fontSize: 12, color: 'var(--va-text-dim)' }}>
                    {c.modelName}
                  </td>
                  <td>{c.weight}</td>
                  <td onClick={(e) => e.stopPropagation()}>
                    <input
                      type="checkbox"
                      checked={c.enabled}
                      onChange={(e) => void onUpdateCriterion({ ...c, enabled: e.target.checked })}
                    />
                  </td>
                  <td>
                    <span className={`va-eval-chevron${isOpen ? ' open' : ''}`}>▶</span>
                  </td>
                </tr>
                {isOpen && (
                  <tr>
                    <td colSpan={6} style={{ padding: 0, borderBottom: '1px solid var(--va-border)' }}>
                      <EvaluatorEditor
                        criterion={c}
                        models={models}
                        onUpdate={onUpdateCriterion}
                        onRemove={() => {
                          setExpandedId(null);
                          void onRemoveCriterion(c.id);
                        }}
                      />
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
      <button className="va-add-eval-btn" onClick={() => {}}>
        + Add evaluator
      </button>
```

г) После компонента `SettingsTab` (перед `TestResultCard`) добавить редактор — это прежний правый блок минус слайдер:

```tsx
// ─── EvaluatorEditor — inline expanded editor (Model Registry expand pattern) ──

interface EvaluatorEditorProps {
  criterion: Criterion;
  models: ModelRegistryEntryPublic[];
  onUpdate: (c: Criterion) => Promise<void>;
  onRemove: () => void;
}

function EvaluatorEditor({ criterion, models, onUpdate, onRemove }: EvaluatorEditorProps) {
  function updateField<K extends keyof Criterion>(field: K, value: Criterion[K]) {
    void onUpdate({ ...criterion, [field]: value });
  }

  return (
    <div className="va-evaluator-detail" style={{ border: 'none', borderRadius: 0 }}>
      {/* Name */}
      <div>
        <div className="va-field-label">Name</div>
        <input
          className="va-field-input"
          value={criterion.name}
          onChange={(e) => updateField('name', e.target.value)}
        />
      </div>

      {/* Color */}
      <div>
        <div className="va-field-label">Color</div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <input
            type="color"
            value={criterion.color}
            onChange={(e) => updateField('color', e.target.value)}
            style={{ width: 36, height: 28, border: 'none', background: 'none', cursor: 'pointer', padding: 0 }}
          />
          <span style={{ fontSize: 12, color: 'var(--va-text-muted)', fontFamily: 'var(--va-font-mono)' }}>
            {criterion.color}
          </span>
        </div>
      </div>

      {/* Model picker — by name from registry */}
      <div>
        <div className="va-field-label">Model</div>
        <select
          className="va-field-input va-field-select"
          value={criterion.modelName}
          onChange={(e) => updateField('modelName', e.target.value)}
        >
          {models.map((m) => (
            <option key={m.name} value={m.name}>
              {m.name}
            </option>
          ))}
        </select>
      </div>

      {/* Weight — numeric input only (owner: no slider); lang="en" forces the
          dot decimal separator regardless of browser locale (audit LOW «0,3») */}
      <div>
        <div className="va-field-label">Weight (0–1)</div>
        <input
          type="number"
          lang="en"
          className="va-field-input va-weight-input"
          min={0}
          max={1}
          step={0.05}
          value={criterion.weight}
          onChange={(e) => updateField('weight', parseFloat(e.target.value) || 0)}
        />
      </div>

      {/* Scale */}
      <div>
        <div className="va-field-label">Scale</div>
        <span style={{ fontSize: 13, color: 'var(--va-text-muted)' }}>
          {criterion.scaleMin} – {criterion.scaleMax}
        </span>
      </div>

      {/* Prompt preview */}
      <div>
        <div className="va-field-label">Prompt (read-only preview)</div>
        <div className="va-prompt-preview">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{criterion.prompt}</ReactMarkdown>
        </div>
      </div>

      {/* Actions */}
      <div style={{ display: 'flex', gap: 8 }}>
        <button className="va-btn-secondary" onClick={onRemove}>
          Remove
        </button>
      </div>
    </div>
  );
}
```

Примечание: чекбокс Enabled остаётся и в строке (быстрый toggle, `stopPropagation`), и его больше нет в редакторе — из редактора блок «Enabled toggle» (бывшие строки 126–135) не переносить.

### 2.2 variant-a.css

а) Добавить рядом с блоком `.va-evaluator-*` (после строки 1129):

```css
/* Evaluators as full-width table rows (Model Registry pattern) */
.va-eval-row { cursor: pointer; }
.va-eval-row:hover td { background: var(--va-surface2); }
.va-eval-row.disabled td { opacity: 0.55; }

.va-eval-chevron {
  display: inline-block;
  font-size: 10px;
  color: var(--va-text-muted);
  transition: transform 0.15s;
}
.va-eval-chevron.open { transform: rotate(90deg); }
```

б) Удалить осиротевшие правила (перед удалением каждого — `grep -rn '<класс>' frontend/src` должен давать 0 использований): `.va-settings-layout` (строки 1065–1069), `.va-evaluator-list` (1085–1089), `.va-evaluator-row`, `.va-evaluator-row:hover`, `.va-evaluator-row.selected` (1091–1110), `.va-evaluator-name` (1119–1123), `.va-evaluator-model-tag` (1125–1129), `.va-weight-row` (1224–1228). **Оставить:** `.va-evaluator-color-swatch`, `.va-evaluator-detail`, `.va-weight-input`, `.va-add-eval-btn`.

### 2.3 Доки (тот же коммит)

`docs/subsystems/webapp-ui-design.md`, секция «Component class conventions»: заменить упоминание списка/строк эвалюаторов (`va-evaluator-list`/`va-evaluator-row`) на новый паттерн: «Evaluators = `va-table` строки (`va-eval-row`) + раскрытие по клику во вложенную строку с `va-evaluator-detail`; шеврон `va-eval-chevron`; тот же паттерн, что у Model Registry».

**Проверка:**
1. `cd frontend && npm run build` → exit 0 (tsc поймает забытые `selectedId`/`updateField`).
2. Браузер: Settings. Ожидаемо: (а) эвалюаторы — полноширинные строки таблицы с колонками цвет/имя/модель/вес/enabled, всё свёрнуто; (б) клик по строке → под ней инлайн-редактор, повторный клик — свернулся, при клике по другой строке раскрыта только она (аккордеон); (в) `document.querySelector('.va-tab-content input[type=range]') === null` (слайдера нет); (г) изменить Weight с 0.3 на 0.35 → в network `PUT /api/criteria/{id}` 200 (бесплатно), вернуть обратно; (д) чекбокс Enabled в строке переключает критерий без раскрытия.
3. Визуальная сверка с макетом: открыть [docs/reports/mockups/evaluators-redesign.html](../../reports/mockups/evaluators-redesign.html) рядом с живым Settings — состояние A и раскрытая строка должны совпадать по структуре и токенам (допустимая разница — реальный полный промпт вместо обрезанного превью). Скриншоты обоих в артефакты PR.

**Коммит:** `feat(frontend): evaluators as full-width expandable rows with numeric weight input`

---

## Задача 3. Персист Dismiss: `PATCH /api/issues/{id}` + асинхронный store-экшен (HIGH H2)

**Причина (1 строка):** `dismissIssue` меняет статус только в Zustand ([store.ts:85–86](../../../frontend/src/demo/store.ts#L85) — «no API call until evaluate», реализация 321–332) — после reload бэкенд снова отдаёт issue как `open`; Accept при этом персистится через apply-edit.

**Файлы:** `src/palimpsest/webapp/app.py`, `frontend/src/demo/api-client.ts`, `frontend/src/demo/store.ts`, `frontend/src/demo/variant-a/VariantA.tsx`, `tests/test_issue_status.py` (новый), доки.

### 3.1 Backend — app.py

Вставить после `apply_edit` (после строки 384), по образцу его же обработки id/404:

```python
class IssueStatusBody(BaseModel):
    status: str


@app.patch("/api/issues/{iid}")
def patch_issue_status(iid: int, body: IssueStatusBody) -> dict:
    if body.status not in ("open", "dismissed"):
        # 'accepted' is only reachable via apply-edit (it also rewrites the target)
        raise HTTPException(422, {"error": "invalid_status"})
    conn = db.connect()
    with db._lock:
        iss = conn.execute("SELECT * FROM issue WHERE id=?", (iid,)).fetchone()
        if not iss:
            raise HTTPException(404, "issue not found")
        if iss["status"] == "accepted":
            raise HTTPException(409, {"error": "already_accepted"})
        conn.execute("UPDATE issue SET status=? WHERE id=?", (body.status, iid))
        conn.commit()
        return _issue_dict(conn.execute("SELECT * FROM issue WHERE id=?", (iid,)).fetchone())
```

Персистентность дальше бесплатна: `_para_issues` (app.py:121–133) уже всегда возвращает не-open issues как историю, а `reset_document` (app.py:402) реоткрывает seed-issues — т.е. Reset остаётся полным «откатом» дизмиссов.

### 3.2 api-client.ts

После `applyEdit` (строка 242):

```ts
export function patchIssueStatus(id: string, status: 'open' | 'dismissed'): Promise<Issue> {
  return patch(`/issues/${id}`, { status });
}
```

### 3.3 store.ts

а) Импортировать `patchIssueStatus` в блоке импортов из `./api-client`.
б) Интерфейс (строки 85–86) — заменить сигнатуру и комментарий:

```ts
  /** Dismiss an issue: optimistic UI + PATCH /api/issues/{id}; rollback on failure */
  dismissIssue: (issueId: string) => Promise<void>;
```

в) Реализацию (строки 321–332) заменить на:

```ts
  dismissIssue: async (issueId) => {
    const setStatus = (status: 'open' | 'dismissed') =>
      set((s) => {
        const doc = s.document;
        if (!doc) return {};
        const paragraphs = doc.paragraphs.map((p) => ({
          ...p,
          issues: p.issues.map((iss) => (iss.id === issueId ? { ...iss, status } : iss)),
        }));
        return { document: { ...doc, paragraphs } };
      });
    setStatus('dismissed');                       // optimistic
    try {
      await patchIssueStatus(issueId, 'dismissed');
    } catch {
      setStatus('open');                          // server did not confirm → rollback
    }
  },
```

г) `VariantA.tsx`, `handleDismissIssue` (строки 165–168): `dismissIssue(issue.id);` → `void dismissIssue(issue.id);`.

### 3.4 Тест — tests/test_issue_status.py (новый файл)

```python
"""Dismiss persistence: PATCH /api/issues/{iid} must survive a document reload."""
from __future__ import annotations

import pytest
from fastapi import HTTPException


@pytest.fixture
def seeded(tmp_path, monkeypatch):
    from palimpsest.webapp import db
    from palimpsest.webapp import seed as seedmod
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(db, "_conn", None)
    seedmod.seed()
    yield db
    if db._conn is not None:
        db._conn.close()
        db._conn = None


def test_dismiss_persists_in_document(seeded):
    from palimpsest.webapp.app import IssueStatusBody, get_document, patch_issue_status

    conn = seeded.connect()
    r = conn.execute("SELECT id, paragraph_id FROM issue WHERE status='open' LIMIT 1").fetchone()
    out = patch_issue_status(r["id"], IssueStatusBody(status="dismissed"))
    assert out["status"] == "dismissed"

    doc_id = conn.execute("SELECT document_id FROM paragraph WHERE id=?",
                          (r["paragraph_id"],)).fetchone()["document_id"]
    doc = get_document(doc_id)
    statuses = {i["id"]: i["status"] for p in doc["paragraphs"] for i in p["issues"]}
    assert statuses[str(r["id"])] == "dismissed"


def test_dismiss_can_be_reopened(seeded):
    from palimpsest.webapp.app import IssueStatusBody, patch_issue_status

    conn = seeded.connect()
    iid = conn.execute("SELECT id FROM issue WHERE status='open' LIMIT 1").fetchone()["id"]
    patch_issue_status(iid, IssueStatusBody(status="dismissed"))
    out = patch_issue_status(iid, IssueStatusBody(status="open"))
    assert out["status"] == "open"


def test_accepted_issue_is_409(seeded):
    from palimpsest.webapp.app import IssueStatusBody, patch_issue_status

    conn = seeded.connect()
    iid = conn.execute("SELECT id FROM issue LIMIT 1").fetchone()["id"]
    conn.execute("UPDATE issue SET status='accepted' WHERE id=?", (iid,))
    conn.commit()
    with pytest.raises(HTTPException) as e:
        patch_issue_status(iid, IssueStatusBody(status="dismissed"))
    assert e.value.status_code == 409


def test_invalid_status_is_422(seeded):
    from palimpsest.webapp.app import IssueStatusBody, patch_issue_status

    with pytest.raises(HTTPException) as e:
        patch_issue_status(1, IssueStatusBody(status="accepted"))
    assert e.value.status_code == 422


def test_unknown_issue_is_404(seeded):
    from palimpsest.webapp.app import IssueStatusBody, patch_issue_status

    with pytest.raises(HTTPException) as e:
        patch_issue_status(999999, IssueStatusBody(status="dismissed"))
    assert e.value.status_code == 404
```

### 3.5 Доки (тот же коммит)

- `docs/superpowers/specs/2026-06-30-demo-contracts.md` §2 (REST-список после `POST /api/paragraphs/{pid}/apply-edit`): добавить строку
  `PATCH /api/issues/{id}  {status: 'open'|'dismissed'}  -> Issue | 404 | 409 (accepted) | 422 (invalid status)` с пометкой «открыт, как и цикл evaluate/apply-edit».
- `docs/subsystems/webapp.md`: строка в таблицу «REST surface» (`PATCH /api/issues/{iid} — persist reviewer dismiss/undo; accepted only via apply-edit`) + одно предложение в «Improvement-loop semantics»: «Dismiss персистится этим PATCH; reset реоткрывает seed-issues (kind='live' dismissed удаляются вместе с live-строками)».

**Проверка:**
1. `uv run pytest tests/test_issue_status.py -q` → `5 passed`; `uv run pytest -q` → `131 passed` (126 + 5).
2. Браузер: Document → Dismiss на любой карточке → в network `PATCH /api/issues/{id}` 200 → reload страницы → карточка осталась зачёркнутой (dismissed). Затем Reset (бесплатно) → issue снова активна.

**Коммит:** `feat(webapp): persist issue dismiss via PATCH /api/issues/{id}`

---

## Задача 4. Ошибки /evaluate видимы: поле `error` в ParaEvalState + баннер (HIGH H3)

**Причина (1 строка):** голый `catch {}` в [store.ts:250–256](../../../frontend/src/demo/store.ts#L250) и отсутствие поля ошибки в `ParaEvalState` (store.ts:41–46) — при 500/сетевом сбое/обрыве бюджета спиннер гаснет молча.

**Файлы:** `frontend/src/demo/store.ts`, `frontend/src/demo/variant-a/InspectorPanel.tsx`, `frontend/src/demo/variant-a/VariantA.tsx`.

а) `store.ts` — интерфейс (строки 41–46):

```ts
export interface ParaEvalState {
  loading: boolean;
  cached: boolean;
  cachedAt: string | null;
  failedCriterionIds: CriterionId[];
  /** last /evaluate failure (network/5xx/budget cut-off); null = no error */
  error: string | null;
}
```

б) `defaultParaEval()` (строка 115): `return { loading: false, cached: false, cachedAt: null, failedCriterionIds: [], error: null };`

в) `evaluateParagraph`: в стартовом `set` добавить `error: null`; в успешном `set` — `error: null`; `catch` заменить на:

```ts
    } catch (e) {
      set((s) => ({
        paraEvalState: {
          ...s.paraEvalState,
          [paraIdx]: {
            ...(s.paraEvalState[paraIdx] ?? defaultParaEval()),
            loading: false,
            error: String(e),
          },
        },
      }));
    }
```

г) `VariantA.tsx` — два инлайн-литерала fallback-стейта (строки 344–349 и 400–405): добавить `error: null` (tsc не даст забыть).

д) `InspectorPanel.tsx` — после блока «Failed criteria warning» (строки 84–88) добавить (класс `va-inspector-warning` уже существует):

```tsx
      {/* ── Evaluate failure (network / 5xx / budget cut-off) ── */}
      {evalState.error && !isCollapsed && (
        <div className="va-inspector-warning">
          Evaluate failed: {evalState.error}
        </div>
      )}
```

**Проверка:**
1. `cd frontend && npm run build` → exit 0.
2. Юнит-регрессия появится в задаче 11 (store.test.ts, кейс H3). Ручная проверка без платного вызова: остановить бэкенд (`kill` uvicorn) НЕЛЬЗЯ трогать, поэтому проверяем логикой: в devtools выполнить
   `fetch('/api/paragraphs/999999/evaluate', {method:'POST'})` → 404; полноценный UI-путь покрывает vitest-тест (мок reject) — там `paraEvalState[0].error` содержит текст ошибки.

**Коммит:** `feat(frontend): surface /evaluate failures via ParaEvalState.error and inspector banner`

---

## Задача 5. Удалить legacy variant-b + мёртвый data.ts + упростить роутинг (HIGH H4; строго ПОСЛЕ задачи 2)

**Причина (1 строка):** `#/b` рендерит второй UI на мок-данных — [Router.tsx:23](../../../frontend/src/Router.tsx#L23) импортирует `variant-b/VariantB.tsx` (992 LOC) + `variant-b.css` (874) + `variant-b/review-extension.ts` (161), а `data.ts` (546 LOC) импортируется только оттуда; всё ценное (паттерн expand-строк, числовой вес) уже портировано в задаче 2.

**Что сделать:**

```bash
git rm -r frontend/src/demo/variant-b
git rm frontend/src/demo/data.ts
git rm frontend/src/Router.tsx
```

`frontend/src/main.tsx` — новое содержимое целиком:

```tsx
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import VariantA from './demo/variant-a/VariantA';
import './index.css';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <VariantA />
  </StrictMode>,
);
```

Контроль хвостов: `grep -rn "variant-b\|VariantB\|from '\.\./data'\|from '\./data'" frontend/src` → 0 строк.

**Доки (тот же коммит):**
- `docs/known_issues.md`, запись «Frontend ships as a single large bundle»: убрать фразу про «code-split the two variants» (варианта теперь один); при желании обновить размер бандла фактическим числом из `npm run build`.
- `grep -rn 'variant-b\|#/b' docs/subsystems docs/README.md` — если есть упоминания живого роута `#/b`, убрать; исторические e2e-отчёты в `docs/reports/e2e/` НЕ трогаем.

**Проверка:**
1. `cd frontend && npm run build` → exit 0 (tsc поймал бы висячие импорты); в выводе размер чанка заметно меньше прежних ~886 kB.
2. Браузер: `http://localhost:5173/#/b` → рендерится variant-a (роут исчез, дефолт); Document работает.

**Коммит:** `refactor(frontend): remove legacy variant-b UI, mock data.ts and hash router`

---

## Задача 6. Doc-parity после мержей: статус model-registry, as-built secrets_guard, закрытие кросс-веточной записи, битые ссылки (HIGH H5 + часть M7)

**Причина (1 строка):** [2026-07-01-model-registry-design.md:5](../../specs/2026-07-01-model-registry-design.md#L5) до сих пор утверждает «реализации в коде пока нет» после мержа `e592be1`; `secrets_guard.py` не упомянут ни в одном доке; запись `known_issues.md:18` о кросс-веточном контракте не разрешена; 5+ битых относительных ссылок.

Это чисто документационный коммит (код уже смержен раньше) — по замечанию аудита допустим отдельным коммитом.

### 6.1 Статус спеки model-registry

`docs/superpowers/specs/2026-07-01-model-registry-design.md`, строка 5 — заменить статусную строку на:

```
Статус: ✅ реализовано и смержено в `dev-demo` (merge `e592be1` + калибровка Test-эндпоинта `0dc1caf`/`eb97124`). As-built описание — [docs/subsystems/webapp.md](../../subsystems/webapp.md). Этот документ — исторический дизайн (T1–T8), при расхождениях истина — webapp.md.
```

### 6.2 As-built: model registry + secrets_guard в webapp.md

`docs/subsystems/webapp.md`, секция «Backend (`src/palimpsest/webapp/`)» (строки 24–37): убедиться, что перечислены модули `model_matrix.py`, `model_params.py`, `budget.py`, и **добавить** пункт:

```
- `secrets_guard.py` — boundary-aware детектор секретных ключей (`api_key`/`token`/`secret`/…): валидация params-мешка на запись (`_guard_params` в app.py) и вычистка секретов из cost-лога (`budget.log_call`).
```

Там же (или в «Subtleties») добавить 2–3 предложения as-built о реестре моделей: строки `model` в SQLite, маскирование ключа «первые 4 символа + …», env-fallback `OPENROUTER_API_KEY` только для OpenRouter-моделей (`_client_for`, app.py:206–220), Test-зонд `POST /api/models/{name}/test` никогда не 5xx. Отдельный файл `docs/subsystems/model-registry.md` НЕ создавать — единый источник webapp.md, спека ссылается на него.

### 6.3 Закрыть кросс-веточную запись в known_issues (M7)

`docs/known_issues.md`, буллет «NerConfig / extract endpoint contract is asserted, not yet cross-verified» (строка 18) — заменить целиком на:

```
- **NerConfig / extract endpoint contract — RESOLVED 2026-07-02.** Кросс-сверка после мержей `feat/terminology-extract` и `feat/model-registry` в `dev-demo` выполнена: эндпоинтов `POST /api/paragraphs/{id}/extract` и `GET/PUT /api/ner-config` в живом API **нет и не планируется для демо** — термины загружаются в БД офлайн (`scripts/load_terms.py` / `scripts/term_pipeline.py`), веб-приложение читает готовую таблицу `term`. `NerConfig{modelName, prompt, params}` остаётся контрактом уровня скриптов (см. [terminology stage doc](stages/terminology.md)); если живой re-extract понадобится, потребуется новая спека с budget-guard'ом.
```

### 6.4 Битые ссылки

Найдены скриптом (перепроверить им же после правок):

```bash
python3 - <<'EOF'
import re, os, glob
for f in glob.glob('docs/**/*.md', recursive=True):
    if '/reports/' in f: continue
    base = os.path.dirname(f)
    for m in re.finditer(r'\[[^\]]*\]\(([^)#]+?)(#[^)]*)?\)', open(f).read()):
        t = m.group(1).strip()
        if t.startswith(('http', 'mailto')) or not t: continue
        if not os.path.exists(os.path.normpath(os.path.join(base, t))):
            print(f, '->', t)
EOF
```

Правки (цели ссылок отсутствуют на `dev-demo` — остались в ветке `old-gse-translating`):

| Файл | Битая ссылка | Фикс |
|---|---|---|
| `docs/testing/e2e-data.md` | `../pipeline.md` | заменить на `subsystems/webapp.md` (относительно файла: `../subsystems/webapp.md`) |
| `docs/superpowers/specs/2026-07-01-terminology-e2e-design.md` | `../../pipeline.md` | заменить на `../../stages/terminology.md` |
| `docs/superpowers/specs/2026-06-30-demo-architecture-design.md` | `../../pipeline.md`, `2026-06-30-keep-minimum.md`, `2026-06-30-repo-reorg.md` | ссылки → плоский текст с пометкой «(документ в ветке `old-gse-translating`)» |
| `docs/superpowers/specs/2026-07-01-terminology-extract-design.md` | `../../experiments/2026-05-18-terminology-glossary-research.md` | ссылка → плоский текст «(в ветке `old-gse-translating`)» |
| `docs/goals/2026-07-01-grounding-overnight.md`, `docs/goals/2026-07-01-pairing-overnight.md` | `../pipeline.md`, `../experiments/2026-07-01-*-research.md` | то же: плоский текст с пометкой ветки |
| `docs/superpowers/specs/2026-07-02-custom-pair-upload-design.md` | `(url)` | посмотреть контекст: это плейсхолдер `[text](url)` — вписать реальный адрес или убрать синтаксис ссылки |

**Проверка:** повторный запуск скрипта из 6.4 → пустой вывод; `grep -n 'реализации в коде пока нет' docs/superpowers/specs/2026-07-01-model-registry-design.md` → 0; `grep -rn 'secrets_guard' docs/subsystems/webapp.md` → ≥1.

**Коммит:** `docs(webapp): flip model-registry spec status, document secrets_guard as-built, close cross-branch contract entry, fix broken links`

---

## Задача 7. Переход из Ranking скроллит документ к параграфу (MEDIUM, находка 6 / M1)

**Причина (1 строка):** `handleRankingRowClick` ([VariantA.tsx:149–156](../../../frontend/src/demo/variant-a/VariantA.tsx#L149)) переключает вкладку и `selectedParaIdx`, но никогда не скроллит `.va-paragraphs-area` — сайдбар показывает §3, текст остаётся на §1.

**Файл:** `frontend/src/demo/variant-a/VariantA.tsx`.

а) Заменить `handleRankingRowClick`:

```tsx
  const pendingScrollRef = useRef(false);

  const handleRankingRowClick = useCallback(
    (idx: number) => {
      setSelectedParaIdx(idx);
      setInspectorTab('issues');
      pendingScrollRef.current = true;
      setActiveTab('document');
    },
    [setSelectedParaIdx, setInspectorTab],
  );
```

б) Рядом с остальными эффектами добавить:

```tsx
  // Scroll the Document view to the paragraph picked in Ranking. The Document
  // tab has just been re-mounted, so wait one frame for layout before scrolling.
  useEffect(() => {
    if (activeTab !== 'document' || !pendingScrollRef.current) return;
    pendingScrollRef.current = false;
    requestAnimationFrame(() => {
      window.document
        .querySelector('.va-para-row.selected')
        ?.scrollIntoView({ block: 'center', behavior: 'smooth' });
    });
  }, [activeTab, selectedParaIdx]);
```

(`window.document` — потому что идентификатор `document` в компоненте переиспользован под стор: `document: doc`. Класс `.selected` уже ставится на `va-para-row` по `selectedParaIdx` — EditorParagraph.tsx, корневой div.)

**Проверка:** браузер: Ranking → клик по строке §12 → открылся Document, параграф §12 в центре вьюпорта (`window.scrollY > 0` / визуально), сайдбар показывает §12. Скриншот. Бесплатно.

**Коммит:** `feat(frontend): scroll document to the paragraph picked in ranking`

---

## Задача 8. Confirm-диалог на Reset (MEDIUM, находка 7 / M2)

**Причина (1 строка):** `handleReset` ([VariantA.tsx:191–195](../../../frontend/src/demo/variant-a/VariantA.tsx#L191)) немедленно вызывает `resetDoc()` — один мисклик на сцене стирает весь показанный прогресс.

**Файл:** `frontend/src/demo/variant-a/VariantA.tsx` — заменить функцию:

```tsx
  async function handleReset() {
    const ok = window.confirm(
      'Reset the document to its seed state?\n' +
      'All accepted edits, dismissals and live scores will be lost.',
    );
    if (!ok) return;
    setResetting(true);
    await resetDoc();
    setResetting(false);
  }
```

(`window.confirm` — осознанно: демо-скоуп, нативный диалог, ноль нового UI-кода; тот же приём в задаче 9.)

**Проверка:** браузер: Document → Reset → появился нативный confirm; Cancel → ничего не изменилось (нет POST в network); OK → `POST /api/documents/1/reset` 200, документ вернулся к seed (бесплатно).

**Коммит:** `feat(frontend): confirm dialog before destructive document reset`

---

## Задача 9. Accept-каскад: один re-judge на параграф при batch-accept + confirm с оценкой стоимости (MEDIUM, находка 8 / M3)

**Причина (1 строка):** `acceptAllIssues` ([store.ts:334–339](../../../frontend/src/demo/store.ts#L334)) последовательно вызывает `acceptIssue`, каждый из которых заканчивается полным платным `evaluateParagraph` ([store.ts:304](../../../frontend/src/demo/store.ts#L304)) — «Accept all 240» = лавина judge-вызовов и полная замена sibling-issues после каждого клика.

**Выбранный подход (одно решение из двух):** **(б) единый re-judge после батча + confirm с оценкой стоимости** — а не дебаунс на каждый одиночный Accept. Обоснование: одиночный Accept оставляем как есть (немедленный re-judge — это ядро интерпретируемой истории демо: правка → живой пересчёт → дельта ▲, и дебаунс тут только добавил бы непредсказуемую задержку на сцене); батчевые же пути (`Accept all` в инспекторе и в шапке) сначала применяют ВСЕ правки через apply-edit и лишь потом судят параграф один раз — стоимость падает с O(issues × criteria) до O(paragraphs × criteria) (для «Accept all 240» при 5 критериях: ~1200 → ~80 вызовов), список issues перестаёт «прыгать» под руками после каждого клика, а confirm-диалог с числом платных вызовов даёт прозрачность цены и защиту от мисклика. Дебаунс-вариант отвергнут: он усложняет стор таймерами, не убирает промежуточные пересуды при быстрой серии кликов по разным параграфам и ухудшает главный демо-момент.

**Файлы:** `frontend/src/demo/store.ts`, `frontend/src/demo/variant-a/VariantA.tsx`, доки.

### 9.1 store.ts

а) В интерфейс `DemoStore` (после `acceptIssue`, строка 83) добавить:

```ts
  /** Apply one issue's suggestion (apply-edit) WITHOUT the re-judge. True = edit applied. */
  applyIssueEdit: (paraId: number, paraIdx: number, issueId: string) => Promise<boolean>;
```

б) Реализация: тело нынешнего `acceptIssue` (строки 262–319) становится `applyIssueEdit` с тремя правками — ранние выходы возвращают `false`, успех — `true`, вызов `evaluateParagraph` убран:

```ts
  applyIssueEdit: async (paraId, paraIdx, issueId) => {
    // Skip applies that would fail server-side anyway — empty suggestion, or the
    // fragment is gone after a prior edit (state is re-read on every call, so a
    // batch sees the target updated by the previous apply).
    const para0 = get().document?.paragraphs.find((p) => p.id === paraId);
    const iss0 = para0?.issues.find((i) => i.id === issueId);
    if (
      !iss0 ||
      !iss0.suggestion ||
      (iss0.targetFragment && !para0!.target.includes(iss0.targetFragment))
    ) {
      return false;
    }

    // Optimistically mark status=accepted in UI
    set((s) => {
      const doc = s.document;
      if (!doc) return {};
      const updatedDoc = patchParaInDoc(doc, paraIdx, (p) => ({
        ...p,
        issues: p.issues.map((iss) =>
          iss.id === issueId ? { ...iss, status: 'accepted' as const } : iss,
        ),
      }));
      return { document: updatedDoc };
    });

    try {
      const result = await apiApplyEdit(paraId, issueId);
      set((s) => {
        const doc = s.document;
        if (!doc) return {};
        const updatedDoc = patchParaInDoc(doc, paraIdx, (p) => ({
          ...p,
          target: result.target,
          issues: p.issues.map((iss) => (iss.id === issueId ? result.issue : iss)),
        }));
        return { document: updatedDoc };
      });
      return true;
    } catch {
      // On 422 fragment_not_found: revert status to open
      set((s) => {
        const doc = s.document;
        if (!doc) return {};
        const updatedDoc = patchParaInDoc(doc, paraIdx, (p) => ({
          ...p,
          issues: p.issues.map((iss) =>
            iss.id === issueId ? { ...iss, status: 'open' as const } : iss,
          ),
        }));
        return { document: updatedDoc };
      });
      return false;
    }
  },
```

в) Новые тонкие `acceptIssue` / `acceptAllIssues`:

```ts
  acceptIssue: async (paraId, paraIdx, issueId) => {
    const applied = await get().applyIssueEdit(paraId, paraIdx, issueId);
    if (applied) await get().evaluateParagraph(paraId, paraIdx);   // single accept keeps the live demo moment
  },

  acceptAllIssues: async (paraId, paraIdx, issueIds) => {
    let applied = false;
    for (const id of issueIds) {
      applied = (await get().applyIssueEdit(paraId, paraIdx, id)) || applied;
    }
    if (applied) await get().evaluateParagraph(paraId, paraIdx);   // ONE paid re-judge per paragraph
  },
```

### 9.2 VariantA.tsx — confirm с оценкой стоимости

Заменить `handleAcceptAll` и `handleAcceptAllDoc` (строки 170–189):

```tsx
  function handleAcceptAll() {
    if (!selectedPara) return;
    const ids = openInspectorIssues.filter((i) => i.suggestion).map((i) => i.id);
    if (ids.length === 0) return;
    const nCalls = criteria.filter((c) => c.enabled).length;
    const ok = window.confirm(
      `Accept ${ids.length} issue(s) in §${selectedPara.idx + 1}?\n` +
      `All suggestions are applied, then the paragraph is re-judged once (~${nCalls} paid LLM calls).`,
    );
    if (!ok) return;
    void acceptAllIssues(selectedPara.id, selectedParaIdx, ids);
  }

  function handleAcceptAllDoc() {
    const byPara = new Map<number, { paraId: number; idx: number; ids: string[] }>();
    for (const iss of allOpenIssues) {
      if (!iss.suggestion) continue;            // nothing to apply
      const idx = paragraphs.findIndex((p) => p.id === iss.paragraphId);
      if (idx === -1) continue;
      if (!byPara.has(iss.paragraphId)) byPara.set(iss.paragraphId, { paraId: iss.paragraphId, idx, ids: [] });
      byPara.get(iss.paragraphId)!.ids.push(iss.id);
    }
    if (byPara.size === 0) return;
    const nIssues = [...byPara.values()].reduce((n, g) => n + g.ids.length, 0);
    const nCalls = byPara.size * criteria.filter((c) => c.enabled).length;
    const ok = window.confirm(
      `Accept ${nIssues} issues across ${byPara.size} paragraphs?\n` +
      `Each paragraph is re-judged once after its edits — ~${nCalls} paid LLM calls total.`,
    );
    if (!ok) return;
    for (const { paraId, idx, ids } of byPara.values()) {
      void acceptAllIssues(paraId, idx, ids);
    }
  }
```

### 9.3 Доки (тот же коммит)

- `docs/subsystems/webapp.md`, «Improvement-loop semantics»: абзац о новой семантике — «одиночный Accept = apply-edit + немедленный re-judge; Accept all = все apply-edit параграфа, затем ОДИН re-judge; обе кнопки Accept all показывают confirm с оценкой числа платных вызовов».
- `docs/known_issues.md`, запись «Accept-all re-scores per issue (cost cascade)» (строка 47) — пометить решённой: «RESOLVED 2026-07-02: batch accept делает один re-judge на параграф + confirm с оценкой стоимости (см. webapp.md)».

**Проверка:**
1. `cd frontend && npm run build` → exit 0.
2. Юнит-регрессия — задача 11 (кейс M3: `applyEdit` ×2, `evaluate` ×1).
3. Браузер (бесплатно): кнопка «Accept all» в инспекторе → появился confirm с текстом «…re-judged once (~N paid LLM calls)» → **Cancel** (не платить!) → network пуст. То же для шапочной «Accept all».

**Коммит:** `feat(frontend): batch accept re-judges once per paragraph + cost-estimate confirm`

---

## Задача 10. Budget guard: `settle()` под локом, `GET /api/budget`, admin-reset (MEDIUM, находка 9 / M5)

**Причина (1 строка):** `settle()` мутирует `_STATE["spent"]` без `_lock` ([budget.py:87–90](../../../src/palimpsest/webapp/budget.py#L87) против reserve на :77–84), а сброс трат возможен только рестартом uvicorn — после капа $2 всё молча падает в кэш.

**Файлы:** `src/palimpsest/webapp/budget.py`, `src/palimpsest/webapp/app.py`, `tests/test_budget.py`, доки.

### 10.1 budget.py

Заменить `settle` и добавить `snapshot`:

```python
async def settle(reserved: float, actual: float | None) -> None:
    if actual is None:
        return                              # keep the worst-case reservation
    async with _lock:
        _STATE["spent"] += (actual - reserved)


def snapshot() -> dict:
    return {"spentUsd": round(_STATE["spent"], 6), "capUsd": _CAP_USD,
            "calls": _STATE["calls"], "callCap": _CALL_CAP}
```

### 10.2 app.py

а) 4 вызова `budget.settle(...)` → `await budget.settle(...)`: строки 240, 244 (внутри `_judge_live`, он async) и 603, 610 (внутри async Test-эндпоинта).

б) Новые роуты (рядом с reset_document, после строки 406):

```python
# ─────────────────────────── budget ───────────────────────────

@app.get("/api/budget")
def get_budget() -> dict:
    return budget.snapshot()


@app.post("/api/budget/reset")
def reset_budget(authorization: str | None = Header(None)) -> dict:
    _require_admin(authorization)           # free-money switch → admin-gated like config writes
    budget.reset()
    return budget.snapshot()
```

### 10.3 tests/test_budget.py

Синхронные вызовы `budget.settle(...)` (строки 51 и 85) обернуть: `asyncio.run(budget.settle(0.01, 0.004))` и `asyncio.run(budget.settle(est, actual))`. Добавить тест:

```python
def test_budget_endpoints_snapshot_and_reset():
    from palimpsest.webapp import budget
    from palimpsest.webapp.app import get_budget, reset_budget

    budget.reset()
    asyncio.run(budget.reserve(0.001))
    snap = get_budget()
    assert snap["calls"] == 1 and snap["spentUsd"] > 0
    out = reset_budget(authorization=None)   # ADMIN_TOKEN unset → open, like other config writes
    assert out["calls"] == 0 and out["spentUsd"] == 0.0
```

### 10.4 Доки (тот же коммит)

- `docs/subsystems/webapp.md`, таблица «REST surface»: `GET /api/budget — spend snapshot (spent/cap/calls)`; `POST /api/budget/reset — admin-token required when DEMO_ADMIN_TOKEN set`. В «Subtleties» — фраза «settle() берёт тот же asyncio.Lock, что и reserve(); сброс трат — без рестарта процесса».
- `docs/superpowers/specs/2026-06-30-demo-contracts.md` §2: две строки эндпоинтов бюджета (аддитивно).

**Проверка:**
1. `uv run pytest tests/test_budget.py -q` → все пройдены (было 6+, стало +1).
2. `curl -s localhost:8000/api/budget` → `{"spentUsd": ..., "capUsd": 2.0, "calls": ..., "callCap": 200}` (после рестарта бэкенда с новым кодом; если рестарт нежелателен сейчас — достаточно юнитов, отметить в PR).

**Коммит:** `fix(webapp): take the lock in budget.settle + GET /api/budget and admin reset endpoint`

---

## Задача 11. Смоук-тесты фронтенда: vitest + @testing-library/react (MEDIUM, находка 10 / M8; после задач 3, 4, 9)

**Причина (1 строка):** во фронтенде ноль `*.test.ts*` — весь React/Zustand/TipTap-слой, включая пути H2/H3 и оптимистичные откаты, не проверяется ничем, кроме рук.

**Минимальный сетап (решение):** vitest (нативен для Vite, конфиг в том же vite.config.ts) + jsdom + @testing-library/react; без jest-dom и setup-файла — матчеров `toBeTruthy`/`getByText` достаточно для смоука. Сеть не трогаем: `./api-client` мокается через `vi.mock` целиком.

### 11.1 Установка и конфиг

```bash
cd frontend && npm i -D vitest jsdom @testing-library/react
```

`frontend/package.json`, в `scripts` добавить: `"test": "vitest run"`.

`frontend/vite.config.ts` — новое содержимое целиком:

```ts
/// <reference types="vitest/config" />
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
  test: {
    environment: 'jsdom',
    css: false,
  },
});
```

### 11.2 `frontend/src/demo/store.test.ts` (новый) — 4 кейса

```ts
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { Document, EvaluateResponse, Issue, Paragraph } from './api-client';

vi.mock('./api-client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./api-client')>();
  return {
    ...actual,
    patchIssueStatus: vi.fn(),
    applyEdit: vi.fn(),
    evaluate: vi.fn(),
  };
});

import { applyEdit, evaluate, patchIssueStatus } from './api-client';
import { useDemoStore } from './store';

function issue(id: string, over: Partial<Issue> = {}): Issue {
  return {
    id, paragraphId: 1, criterionId: 'accuracy', targetFragment: '', sourceFragment: '',
    explanation: 'x', suggestion: '', severity: 'minor', mqmCategory: null, status: 'open',
    ...over,
  };
}

function makeDoc(issues: Issue[]): Document {
  const para: Paragraph = {
    id: 1, idx: 0, source: 'ru', target: 'aaa bbb', scores: [], scoresPrev: null,
    scoresBaseline: null, aggregate: null, aggregateBaseline: null, issues, terms: [],
  };
  return {
    id: 1, title: 't', sourceLang: 'ru', targetLang: 'en', nParagraphs: 1,
    sourceModel: 'm', aggregate: null, paragraphs: [para],
  };
}

const evalResponse: EvaluateResponse = {
  scores: [], scoresPrev: null, scoresBaseline: null, aggregate: 7, aggregateBaseline: null,
  issues: [], failedCriterionIds: [], cached: false, cachedAt: null, docVersion: 1,
};

beforeEach(() => {
  vi.clearAllMocks();
  useDemoStore.setState({
    document: makeDoc([
      issue('1', { targetFragment: 'aaa', suggestion: 'xxx' }),
      issue('2', { targetFragment: 'bbb', suggestion: 'yyy' }),
    ]),
    paraEvalState: {
      0: { loading: false, cached: false, cachedAt: null, failedCriterionIds: [], error: null },
    },
  });
});

describe('dismissIssue (H2)', () => {
  it('persists via PATCH and keeps status=dismissed', async () => {
    vi.mocked(patchIssueStatus).mockResolvedValue(issue('1', { status: 'dismissed' }));
    await useDemoStore.getState().dismissIssue('1');
    expect(patchIssueStatus).toHaveBeenCalledWith('1', 'dismissed');
    expect(useDemoStore.getState().document!.paragraphs[0].issues[0].status).toBe('dismissed');
  });

  it('rolls back to open when the PATCH fails', async () => {
    vi.mocked(patchIssueStatus).mockRejectedValue(new Error('HTTP 500'));
    await useDemoStore.getState().dismissIssue('1');
    expect(useDemoStore.getState().document!.paragraphs[0].issues[0].status).toBe('open');
  });
});

describe('evaluateParagraph (H3)', () => {
  it('exposes the failure via paraEvalState.error', async () => {
    vi.mocked(evaluate).mockRejectedValue(new Error('boom'));
    await useDemoStore.getState().evaluateParagraph(1, 0);
    const st = useDemoStore.getState().paraEvalState[0];
    expect(st.loading).toBe(false);
    expect(st.error).toContain('boom');
  });
});

describe('acceptAllIssues (M3)', () => {
  it('applies every edit but re-judges the paragraph once', async () => {
    vi.mocked(applyEdit)
      .mockResolvedValueOnce({ target: 'xxx bbb', issue: issue('1', { status: 'accepted' }) })
      .mockResolvedValueOnce({ target: 'xxx yyy', issue: issue('2', { status: 'accepted' }) });
    vi.mocked(evaluate).mockResolvedValue(evalResponse);
    await useDemoStore.getState().acceptAllIssues(1, 0, ['1', '2']);
    expect(applyEdit).toHaveBeenCalledTimes(2);
    expect(evaluate).toHaveBeenCalledTimes(1);
  });
});
```

### 11.3 `frontend/src/demo/variant-a/InspectorPanel.test.tsx` (новый) — 1 кейс

```tsx
import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import InspectorPanel from './InspectorPanel';

describe('InspectorPanel error banner (H3)', () => {
  it('renders the evaluate failure', () => {
    render(
      <InspectorPanel
        tab="issues"
        onTabChange={vi.fn()}
        paragraph={null}
        activeCriteria={new Set()}
        evalState={{
          loading: false,
          cached: false,
          cachedAt: null,
          failedCriterionIds: [],
          error: 'POST /paragraphs/1/evaluate → 500',
        }}
        criteria={[]}
        isCollapsed={false}
        onToggleCollapse={vi.fn()}
        onAccept={vi.fn()}
        onDismiss={vi.fn()}
        onAcceptAll={vi.fn()}
        visibleIssues={[]}
      />,
    );
    expect(screen.getByText(/Evaluate failed/)).toBeTruthy();
    expect(screen.getByText(/500/)).toBeTruthy();
  });
});
```

### 11.4 Доки (тот же коммит)

`docs/subsystems/webapp.md`, секция «Run instructions» (или Frontend): команда `cd frontend && npm test` и одно предложение, что покрывается (store: dismiss-персист/rollback, error-стейт evaluate, батч-accept; компонент: баннер ошибки).

**Проверка:** `cd frontend && npm test` → `Test Files  2 passed (2)`, `Tests  5 passed (5)`; сети нет (api-client замокан); `npm run build` → exit 0 (tsc типизирует и тестовые файлы).

**Коммит:** `test(frontend): vitest smoke tests for dismiss persistence, evaluate errors and batch accept`

---

## Задача 12. Финальная сквозная проверка

**Причина:** verification-before-completion — все заявления подтверждаем прогонами.

1. `make test` (= `uv run pytest -q`) → **132 passed** (126 базовых + 5 issue_status + 1 budget), 0 failed.
2. `cd frontend && npm run build` → exit 0; `npm test` → 5 passed.
3. Скрипт битых ссылок из задачи 6.4 → пустой вывод.
4. Браузер (`playwright-cli -s=fixplan`, всё бесплатно): difficulty-точки цветные → Settings: строки-эвалюаторы с раскрытием, без слайдера → Dismiss + reload (персист) → Ranking-клик скроллит → Reset показывает confirm → Accept all показывает confirm с ценой (Cancel!) → `#/b` больше не рендерит второй UI → `curl localhost:8000/api/budget` отвечает. ≥6 скриншотов в артефакты PR.
5. `git log --oneline dev-demo..feat/audit-fixes` — 11 коммитов из плана, у каждого кодового коммита доки в том же коммите (правило sync).

Коммитов у задачи 12 нет (или `docs(reports): ...`, если по итогам пишется отчёт).

---

## Сводная таблица

| № | Задача | Закрывает находку | Усилие | Файлы |
|---|---|---|---|---|
| 1 | CSS `difficulty-*` | HIGH-1 (H1) | **S** | variant-a.css |
| 2 | Evaluators: строки + expand, вес без слайдера ([макет](../../reports/mockups/evaluators-redesign.html)) | Запрос владельца | **M** | SettingsTab.tsx, variant-a.css, webapp-ui-design.md, reports/mockups/evaluators-redesign.html |
| 3 | Персист Dismiss (`PATCH /api/issues/{id}`) | HIGH-2 (H2) | **M** | app.py, api-client.ts, store.ts, VariantA.tsx, test_issue_status.py, webapp.md, demo-contracts.md |
| 4 | Ошибки /evaluate: `error` + баннер | HIGH-3 (H3) | **S** | store.ts, InspectorPanel.tsx, VariantA.tsx |
| 5 | Удаление variant-b + data.ts + Router | HIGH-4 (H4) | **M** | variant-b/*, data.ts, Router.tsx, main.tsx, known_issues.md |
| 6 | Doc-parity: статус спеки, secrets_guard, M7, битые ссылки | HIGH-5 (H5) + MED-7 | **S** | model-registry-design.md, webapp.md, known_issues.md, 7 md-файлов со ссылками |
| 7 | Скролл из Ranking к параграфу | MED-6 (M1) | **S** | VariantA.tsx |
| 8 | Confirm на Reset | MED-7 по нумерации промпта (M2) | **S** | VariantA.tsx |
| 9 | Батч-accept: один re-judge + confirm с ценой | MED-8 (M3) | **M** | store.ts, VariantA.tsx, webapp.md, known_issues.md |
| 10 | Budget: settle под локом + GET/reset | MED-9 (M5) | **S** | budget.py, app.py, test_budget.py, webapp.md, demo-contracts.md |
| 11 | Vitest-смоук фронта (5 тестов) | MED-10 (M8) | **M** | package.json, vite.config.ts, store.test.ts, InspectorPanel.test.tsx, webapp.md |
| 12 | Финальная сквозная проверка | — | **S** | — |

**Итоговая оценка:** 5×M + 7×S ≈ 1.5–2 рабочих дня одного исполнителя (S ≈ 0.5–1 ч, M ≈ 2–4 ч), включая браузерные проверки и доки.
