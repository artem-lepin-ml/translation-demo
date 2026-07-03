# Реализация rev-3 читальной области (Variant A) — план

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) или superpowers:executing-plans для позадачного исполнения. Шаги отмечены чекбоксами (`- [ ]`).

**Goal:** три точечных улучшения Document-вкладки — компактный чип вместо левого гуттера (вкл. фикс цветов полос), унификация типографики панелей (общий baseline), адаптивные заголовки `Source · <Language>` / `Translation · <Language>` + инвентарь переименований. Правка НЕ меняется: каждый абзац — всегда живой TipTap, как сегодня.

**Architecture:** aligned-вид отменён владельцем (спека rev-3) — ни segment-model, ни режимов, ни store-изменений нет. Меняются: CSS (`variant-a.css`), `lang.ts` (display-резолвер), `EditorParagraph.tsx` (гуттер → мета-строка, горизонтальный `ScoreChip`), ярлыки в `VariantA.tsx`/`GlossaryTab.tsx`/`RankingTab.tsx`. Backend не трогаем.

**Tech Stack:** React 18 + TypeScript, Vitest 4 + `@testing-library/react` + jsdom, `Intl.DisplayNames`, CSS-токены `--va-*`.

**Источник:** спека [docs/superpowers/specs/2026-07-02-reading-pane-redesign.md](../specs/2026-07-02-reading-pane-redesign.md) (rev-3). Отменённые разделы спеки (баннеры «ОТМЕНЕНО») в план НЕ входят.

---

## Предпосылка: ребейз на `dev-demo` (перед Задачей 1)

`feat/upload-polish` **уже влит в `dev-demo`** (проверено: `git merge-base --is-ancestor feat/upload-polish dev-demo` → yes). Известный по rev-2.1 «merge-конфликт lang.ts» выродился в обычный ребейз: наша ветка пока содержит только docs-коммиты — конфликтов не будет.

- [ ] Выполнить `git rebase dev-demo` из worktree `/Users/a1111/Projects/Work/worktrees/reading-pane` (ветка `feat/reading-pane`).
- [ ] Проверить базу: `frontend/src/demo/lang.ts` существует (словарь `{ru: 'Russian', en: 'English'}` + `langLabel`); `VariantA.tsx` и `GlossaryTab.tsx` уже импортируют `langLabel` и используют его в заголовках/свитчере (проверено на dev-demo: VariantA.tsx:439-440 `Original ({langLabel(...)})`, VariantA.tsx:320 свитчер уже без `toUpperCase`).
- [ ] Прогнать `cd frontend && npm test` — зелёный baseline.

**Инвариант:** словарь `LANG_LABELS` остаётся ПЕРВЫМ шагом lookup'а в `langLabel`; наша `Intl.DisplayNames`-детекция добавляется ПОСЛЕ словаря (Задача 2), call-sites не меняются — меняется только тело `langLabel` внутри того же `lang.ts`.

---

## Структура файлов

**Создаются:**
- `frontend/src/demo/__tests__/lang.test.ts` — юниты `langLabel` / `isBcp47Like`.
- `frontend/src/demo/variant-a/__tests__/ScoreChip.test.tsx` — компонентные тесты чипа (полосы, em-dash, shimmer, дельта, cached).

**Модифицируются:**
- `frontend/src/demo/lang.ts` — `isBcp47Like` + `Intl.DisplayNames` поверх словаря (обратный словарь имя→код НЕ добавляется — отменён вместе с сегментацией).
- `frontend/src/demo/variant-a/variant-a.css` — типографика (Задача 1); мета-строка + горизонтальный чип + цвета полос; удаление мёртвых правил гуттера (Задача 3).
- `frontend/src/demo/variant-a/EditorParagraph.tsx` — гуттер → мета-строка над телом абзаца; `ScoreChip` становится горизонтальным (label внутри, em-dash, up/down-дельта, testid).
- `frontend/src/demo/variant-a/VariantA.tsx` — заголовки, tooltip, удаление гуттер-спейсера в шапке колонок, `label`-prop чипа.
- `frontend/src/demo/variant-a/GlossaryTab.tsx`, `RankingTab.tsx` — ярлыки по инвентарю.
- `docs/subsystems/webapp.md` — doc-parity в тех же коммитах.

---

## Задача 1 [S]: Baseline-типографика (самостоятельная, шиппится первой)

Спека §2: source 14px против target 15px даёт ~13px расхождения первой строки. Унификация: обе панели 15px / line-height 1.85 + нулевой верхний отступ.

**Files:**
- Modify: `frontend/src/demo/variant-a/variant-a.css:402-435`

- [ ] **Step 1: Изменить типографику source-панели**

В `variant-a.css` в правиле `.va-para-source` заменить `font-size: 14px;` на `font-size: 15px;` (остальное — italic, `--va-text-muted`, `line-height: 1.85` — не трогать):

```css
.va-para-source {
  flex: 1 1 0;
  min-width: 0;
  font-size: 15px;
  line-height: 1.85;
  color: var(--va-text-muted);
  font-style: italic;
  padding: 0 16px;
  cursor: pointer;
  user-select: text;
}
```

- [ ] **Step 2: Обнулить верхний отступ TipTap-обёртки**

После правила `.va-para-target .ProseMirror p { margin: 0; }` добавить:

```css
.va-para-target .ProseMirror {
  margin-top: 0;
  padding-top: 0;
}
```

(если эти свойства уже эффективно нулевые — правило безвредно и фиксирует контракт baseline).

- [ ] **Step 3: Прогнать suite + визуальная проверка**

Run: `cd frontend && npm test`
Expected: PASS (юниты не завязаны на 14px).
Затем `npm run dev`: первая строка source и первая строка translation стартуют с одного y.

- [ ] **Step 4: Doc-parity + commit**

В `docs/subsystems/webapp.md` в строке `EditorParagraph.tsx` frontend-таблицы дополнить: «source и translation используют унифицированную типографику (15px / line-height 1.85) — общий baseline первой строки».

```bash
git add frontend/src/demo/variant-a/variant-a.css docs/subsystems/webapp.md
git commit -m "fix(webapp): unify source/target typography for shared baseline"
```

---

## Задача 2 [M]: `lang.ts` — `isBcp47Like` + `Intl.DisplayNames` поверх словаря

Display-резолвер имени языка (спека §3). Словарь из dev-demo остаётся первым шагом; BCP-47-детекция + `Intl.DisplayNames` — вторым; свободный текст — с заглавной. Обратный словарь имя→код НЕ добавляется (отменён вместе с резолюцией локали сегментации).

**Files:**
- Modify: `frontend/src/demo/lang.ts`
- Create: `frontend/src/demo/__tests__/lang.test.ts`

- [ ] **Step 1: Написать падающие тесты**

Создать `frontend/src/demo/__tests__/lang.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import { isBcp47Like, langLabel } from '../lang';

describe('isBcp47Like', () => {
  it('accepts 2-letter code', () => expect(isBcp47Like('ru')).toBe(true));
  it('accepts region-tagged code', () => expect(isBcp47Like('de-DE')).toBe(true));
  it('rejects free text with space', () => expect(isBcp47Like('New Guinea')).toBe(false));
  it('rejects malformed', () => expect(isBcp47Like('!!!')).toBe(false));
});

describe('langLabel', () => {
  it('dictionary code → full name (first lookup step)', () => {
    expect(langLabel('ru')).toBe('Russian');
    expect(langLabel('en')).toBe('English');
  });
  it('non-dictionary BCP-47 code → Intl display name', () => {
    expect(langLabel('de')).toBe('German');
  });
  it('free-text language name → passed through capitalized', () => {
    expect(langLabel('russian')).toBe('Russian');
    expect(langLabel('german')).toBe('German');
  });
  it("2-3 letter free text ('she') → no throw, non-empty (accepted boundary, spec §3)", () => {
    const out = langLabel('she');
    expect(typeof out).toBe('string');
    expect(out.length).toBeGreaterThan(0); // echo 'she' OR an ISO name — both accepted
  });
  it('garbage → passed through', () => {
    expect(langLabel('!!!')).toBe('!!!');
  });
});
```

- [ ] **Step 2: Прогнать — убедиться, что падает**

Run: `cd frontend && npx vitest run src/demo/__tests__/lang.test.ts`
Expected: FAIL — `isBcp47Like` не экспортирован; `langLabel('de')` возвращает `'de'` (словарь dev-demo знает только ru/en).

- [ ] **Step 3: Реализация**

Заменить содержимое `frontend/src/demo/lang.ts`:

```ts
/** Language display labels. Pilot documents store ISO codes; uploads store
 *  free-text names. Dictionary stays the FIRST lookup step (upload-polish
 *  heritage); BCP-47-shaped input goes through Intl.DisplayNames; anything
 *  else is echoed capitalized. */

const LANG_LABELS: Record<string, string> = { ru: 'Russian', en: 'English' };

/** Loose BCP-47 shape: 2-3 letter primary subtag + optional dash-joined subtags. */
export function isBcp47Like(raw: string): boolean {
  return /^[a-z]{2,3}(-[A-Za-z0-9]+)*$/i.test(raw);
}

function capitalize(s: string): string {
  return s.length === 0 ? s : s[0].toUpperCase() + s.slice(1);
}

/** raw → human-readable language name.
 *  1) dictionary code→name; 2) BCP-47-like → Intl.DisplayNames (its default
 *  fallback: 'code' echoes unknown-but-well-formed input); 3) free text →
 *  capitalized as-is; any error → raw. */
export function langLabel(raw: string): string {
  const dict = LANG_LABELS[raw.toLowerCase()];
  if (dict) return dict;
  if (isBcp47Like(raw)) {
    try {
      const name = new Intl.DisplayNames(['en'], { type: 'language' }).of(raw);
      if (name) return name;
    } catch {
      return raw;
    }
  }
  return capitalize(raw);
}
```

- [ ] **Step 4: Прогнать — зелёно (весь suite: call-sites уже используют langLabel)**

Run: `cd frontend && npm test && npx tsc --noEmit`
Expected: PASS + чистый tsc. (Замечание к `'she'`: это валидная ISO-639-форма — `Intl.DisplayNames` может вернуть либо echo, либо ISO-имя; тест допускает оба исхода.)

- [ ] **Step 5: Doc-parity + commit**

В `docs/subsystems/webapp.md` (frontend-секция) дополнить упоминание `lang.ts`: «`langLabel`: словарь → `Intl.DisplayNames` для BCP-47-подобных кодов → свободный текст с заглавной; `isBcp47Like` — общий детектор формы».

```bash
git add frontend/src/demo/lang.ts frontend/src/demo/__tests__/lang.test.ts docs/subsystems/webapp.md
git commit -m "feat(webapp): upgrade langLabel with BCP-47 detection + Intl.DisplayNames"
```

---

## Задача 3 [M]: компактный чип + мета-строка вместо гуттера (+ фикс цветов полос, + чистка CSS)

Спека §1: гуттер 72px умирает; над телом абзаца — мета-строка ~24px с горизонтальным чипом `[§2 8.0 ▲0.4] (cached)`. Обязательные цвета полос (сегодня `.va-score-chip.green/.yellow/.red` не стилизованы — попутный фикс). `aggregate=null` → em-dash без layout-сдвига; loading → shimmer при сохранённом §N. data-testid: `para-meta`, `score-chip`.

**Files:**
- Modify: `frontend/src/demo/variant-a/EditorParagraph.tsx` (Props, гуттер ~163-164, `ScoreChip` ~235-249)
- Modify: `frontend/src/demo/variant-a/VariantA.tsx` (спейсер шапки ~438, конструирование чипа в рендере абзацев)
- Modify: `frontend/src/demo/variant-a/variant-a.css`
- Create: `frontend/src/demo/variant-a/__tests__/ScoreChip.test.tsx`

- [ ] **Step 1: Написать падающие тесты чипа**

Создать `frontend/src/demo/variant-a/__tests__/ScoreChip.test.tsx`:

```tsx
import { afterEach, describe, expect, it } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';
import { ScoreChip } from '../EditorParagraph';

afterEach(cleanup);

describe('ScoreChip compact chip', () => {
  it('band classes green/yellow/red for 8.0/6.4/5.7', () => {
    for (const [score, band] of [[8.0, 'green'], [6.4, 'yellow'], [5.7, 'red']] as const) {
      const { unmount } = render(<ScoreChip label="§1" score={score} loading={false} delta={null} />);
      expect(screen.getByTestId('score-chip').className).toContain(band);
      unmount();
    }
  });

  it('null score, not loading → em-dash, §N stays (no layout collapse)', () => {
    render(<ScoreChip label="§2" score={null} loading={false} delta={null} />);
    const chip = screen.getByTestId('score-chip');
    expect(chip.textContent).toContain('§2');
    expect(chip.textContent).toContain('—');
  });

  it('loading → shimmer placeholder, §N stays', () => {
    render(<ScoreChip label="§3" score={7.1} loading={true} delta={null} />);
    const chip = screen.getByTestId('score-chip');
    expect(chip.querySelector('.va-score-chip-loading')).toBeTruthy();
    expect(chip.textContent).toContain('§3');
  });

  it('positive delta → ▲ with .up; negative → ▼ with .down', () => {
    render(<ScoreChip label="§1" score={8.0} loading={false} delta={0.4} />);
    const up = screen.getByTestId('score-chip').querySelector('.va-score-chip-delta');
    expect(up?.className).toContain('up');
    expect(up?.textContent).toContain('▲0.4');
    cleanup();
    render(<ScoreChip label="§1" score={5.7} loading={false} delta={-0.3} />);
    const down = screen.getByTestId('score-chip').querySelector('.va-score-chip-delta');
    expect(down?.className).toContain('down');
    expect(down?.textContent).toContain('▼0.3');
  });

  it('cached badge rendered when cached', () => {
    render(<ScoreChip label="§1" score={8.0} loading={false} delta={null} cached />);
    expect(screen.getByText('cached')).toBeTruthy();
  });
});
```

Проверка фактического ЦВЕТА полос (computed style) — в браузере на этапе скриншотов (Задача 5): jsdom не резолвит `var()` из внешнего CSS-файла, честный юнит здесь — по классам.

- [ ] **Step 2: Прогнать — убедиться, что падает**

Run: `cd frontend && npx vitest run src/demo/variant-a/__tests__/ScoreChip.test.tsx`
Expected: FAIL — у `ScoreChip` нет prop `label`/testid; null score рендерит `null`.

- [ ] **Step 3: Переписать `ScoreChip` (горизонтальный, label внутри)**

В `EditorParagraph.tsx` заменить `ScoreChipProps` и `ScoreChip`:

```tsx
interface ScoreChipProps {
  label: string;               // §N — always visible, incl. loading state
  score: number | null;
  loading: boolean;
  delta: number | null;
  cached?: boolean;
}
```

```tsx
export function ScoreChip({ label, score, loading, delta, cached }: ScoreChipProps) {
  const band = score !== null ? (score >= 8 ? 'green' : score >= 6 ? 'yellow' : 'red') : null;
  const badge = loading ? null : deltaBadge(delta);
  return (
    <span className={`va-score-chip${band ? ' ' + band : ''}`} data-testid="score-chip">
      <span className="va-score-chip-label">{label}</span>
      {loading ? (
        <span className="va-score-chip-loading">…</span>
      ) : score !== null ? (
        <span className="va-score-chip-val">{score.toFixed(1)}</span>
      ) : (
        <span className="va-score-chip-none">—</span>
      )}
      {badge && (
        <span className={`va-score-chip-delta ${delta! > 0 ? 'up' : 'down'}`}>
          {badge.glyph}{badge.magnitude}
        </span>
      )}
      {cached && <span className="va-cached-badge" title="Cached preview">cached</span>}
    </span>
  );
}
```

(`computeChipDelta`/`deltaBadge` не меняются — их тесты в `__tests__/EditorParagraph.test.ts` живут.)

- [ ] **Step 4: Гуттер → мета-строка в `EditorParagraph`**

Из `Props` удалить `paragraphLabel: string;` (label теперь внутри чипа; убрать и из деструктуризации). В JSX заменить гуттер и обернуть панели в body-ряд — содержимое source/target-блоков переносится БЕЗ изменений, меняется только обёртка:

```tsx
    <div
      className={`va-para-row${selected ? ' selected' : ''}`}
      style={cssVars as React.CSSProperties}
    >
      {/* ── Meta strip: compact chip (replaces the 72px gutter) ── */}
      <div className="va-para-meta" data-testid="para-meta" onClick={onSelect}>
        {scoreChip}
      </div>

      <div className="va-para-body">
        {/* ── Left: source (read-only, clickable) ── */}
        <div className="va-para-source" dir="auto" onClick={onSelect}>
          {showTerms && terms.length > 0 ? (
            <SourceWithTerms
              text={sourceText}
              terms={terms}
              hoveredTermId={hoveredTermId}
              onTermHover={onTermHover}
              onTermClick={onTermClick}
            />
          ) : (
            <span>{sourceText}</span>
          )}
        </div>

        {/* ── Right: translation (TipTap editor) ── */}
        <div
          className="va-para-target"
          dir="auto"
          onClick={handleEditorClick}
          onMouseOver={handleEditorHover}
          onMouseLeave={() => onTermHover(null)}
        >
          <EditorContent editor={editor} />
        </div>
      </div>
    </div>
```

- [ ] **Step 5: VariantA — label в чип, удалить спейсер шапки**

В `VariantA.tsx` (рендер абзацев): убрать `paragraphLabel={`§${para.idx + 1}`}` из props `EditorParagraph`, передать label в чип:

```tsx
                      scoreChip={
                        <ScoreChip
                          label={`§${para.idx + 1}`}
                          score={agg}
                          loading={es.loading}
                          delta={chipDelta}
                          cached={es.cached}
                        />
                      }
```

В шапке колонок удалить строку `<div className="va-col-header-gutter" />` (~438) — остаются два `.va-col-header` по 1fr.

- [ ] **Step 6: CSS — мета-строка, горизонтальный чип, полосы, чистка**

В `variant-a.css`:

Заменить `.va-para-row { display: flex; align-items: flex-start; … }` на колонку + body-ряд:

```css
.va-para-row {
  display: flex;
  flex-direction: column;
  gap: 2px;
  border-radius: var(--va-radius);
  padding: 8px 0 12px;
  border: 1.5px solid transparent;
  transition: background 0.15s, border-color 0.15s;
  cursor: default;
  position: relative;
}

.va-para-body {
  display: flex;
  align-items: flex-start;
  gap: 0;
}
```

Добавить мета-строку:

```css
.va-para-meta {
  display: flex;
  align-items: center;
  height: 24px;
  padding: 0 16px;
  cursor: pointer;
}
```

Заменить вертикальный `.va-score-chip` на горизонтальный + слоты + полосы:

```css
.va-score-chip {
  display: inline-flex;
  flex-direction: row;
  align-items: baseline;
  gap: 8px;
  background: var(--va-surface2);
  border: 1px solid var(--va-border);
  border-radius: 6px;
  padding: 2px 8px;
  transition: background 0.3s;
}

.va-score-chip-label {
  font-size: 11px;
  font-weight: 700;
  color: var(--va-text-dim);
  font-variant-numeric: tabular-nums;
  letter-spacing: 0.03em;
}

.va-para-row.selected .va-score-chip-label { color: var(--va-accent); }

.va-score-chip-val {
  font-size: 12px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  line-height: 1;
}

/* Band colours — the missing .green/.yellow/.red fix (spec §1) */
.va-score-chip.green  .va-score-chip-val { color: var(--va-green); }
.va-score-chip.yellow .va-score-chip-val { color: var(--va-yellow); }
.va-score-chip.red    .va-score-chip-val { color: var(--va-red); }

.va-score-chip-none {
  font-size: 12px;
  font-weight: 700;
  color: var(--va-text-dim);
  min-width: 1.5ch;          /* stable width — no layout shift on first score */
  display: inline-block;
  text-align: center;
}
```

Обновить дельту (был hardcoded green) и shimmer:

```css
.va-score-chip-delta {
  font-size: 10px;
  font-weight: 700;
  white-space: nowrap;
  animation: va-pop-in 0.3s ease-out;
}
.va-score-chip-delta.up   { color: var(--va-green); }
.va-score-chip-delta.down { color: var(--va-red); }

.va-score-chip-loading {
  font-size: 12px;
  color: var(--va-text-dim);
  animation: va-pulse 1s ease-in-out infinite;
  line-height: 1;
  min-width: 1.5ch;
  display: inline-block;
  text-align: center;
}
```

Удалить мёртвые правила: `.va-para-gutter`, `.va-para-label`, `.va-para-row.selected .va-para-label`, `.va-col-header-gutter`, `.va-score-chip-val`-дубликат если остался от старого блока. Селектор `.va-para-row.selected` СОХРАНИТЬ (на него завязан scroll из Ranking, [VariantA.tsx:187](../../../frontend/src/demo/variant-a/VariantA.tsx#L187)).

- [ ] **Step 7: Прогнать весь suite + tsc**

Run: `cd frontend && npm test && npx tsc --noEmit`
Expected: PASS (в т.ч. новые ScoreChip-тесты) + чистый tsc (ушедший `paragraphLabel` нигде не остался).

- [ ] **Step 8: Doc-parity + commit**

В `docs/subsystems/webapp.md` обновить строку `EditorParagraph.tsx`: «мета-строка с компактным горизонтальным чипом (`§N + score + Δ + cached`, testid `para-meta`/`score-chip`) над телом абзаца — левый гуттер удалён; цвета полос чипа green/yellow/red стилизованы».

```bash
git add frontend/src/demo/variant-a/EditorParagraph.tsx frontend/src/demo/variant-a/VariantA.tsx frontend/src/demo/variant-a/variant-a.css frontend/src/demo/variant-a/__tests__/ScoreChip.test.tsx docs/subsystems/webapp.md
git commit -m "feat(webapp): replace paragraph gutter with compact meta-strip chip"
```

---

## Задача 4 [M]: адаптивные заголовки + инвентарь переименований (8 строк)

Спека §3 + инвентарь (нейминг Source/Translation подтверждён владельцем). Номера строк — по состоянию dev-demo; после ребейза сверить grep'ом.

**Files:**
- Modify: `frontend/src/demo/variant-a/VariantA.tsx` (~320, ~422, ~439-440 на dev-demo)
- Modify: `frontend/src/demo/variant-a/GlossaryTab.tsx` (~29, ~43-44)
- Modify: `frontend/src/demo/variant-a/RankingTab.tsx` (~67)

- [ ] **Step 1: VariantA — заголовки + tooltip (строки 1, 2, 4 инвентаря)**

Заголовки колонок (dev-demo ~439-440):

```tsx
                <div className="va-col-header">Source · {langLabel(doc.sourceLang)}</div>
                <div className="va-col-header">Translation · {langLabel(doc.targetLang)}</div>
```

Tooltip Terms-чипа (~422):

```tsx
              ? 'Terminology signals are precomputed offline and available for the seeded pilot document'
```

Строка 3 инвентаря (свитчер документов): на dev-demo уже `{langLabel(d.sourceLang)} → {langLabel(d.targetLang)}` без `toUpperCase` — **уже выполнена в базе**; только проверить grep'ом, что языкового `toUpperCase` в свитчере не осталось.

- [ ] **Step 2: GlossaryTab — строки 5, 6, 7 инвентаря**

Empty-note (~29): `…available for the seeded pilot document.`; заголовки таблицы (~43-44):

```tsx
            <th>Source · {langLabel(sourceLang)}</th>
            <th>Translation · {langLabel(targetLang)}</th>
```

- [ ] **Step 3: RankingTab — строка 8 инвентаря**

`<th>Target snippet</th>` → `<th>Translation snippet</th>` (`Source snippet` НЕ трогаем — соответствует конвенции; `TermPopover.tsx` `Source lemma` тоже).

- [ ] **Step 4: Обновить текстовые ассерты существующих тестов**

Run: `cd frontend && grep -rn "Original (\|Source (\|Target (\|Target snippet\|RU→EN" src/demo --include=*.test.tsx --include=*.test.ts`

Найденные ассерты обновить на `Source · Russian` / `Translation · English` / `Translation snippet` / `seeded pilot document`. Также убедиться, что не осталось языкового `toUpperCase`: `grep -rn "Lang.toUpperCase" frontend/src/demo/variant-a/` → пусто.

- [ ] **Step 5: Прогнать suite + tsc**

Run: `cd frontend && npm test && npx tsc --noEmit`
Expected: PASS + чистый tsc.

- [ ] **Step 6: Doc-parity + commit**

В `docs/subsystems/webapp.md` строку `VariantA.tsx` дополнить: «UI-конвенция ярлыков — `Source` / `Translation`; заголовки колонок `Source · <Language>` / `Translation · <Language>` через `langLabel`; код/API остаются `source_*`/`target_*`». В строках `GlossaryTab.tsx`/`RankingTab.tsx` — аналогичные пометки.

```bash
git add frontend/src/demo/variant-a/VariantA.tsx frontend/src/demo/variant-a/GlossaryTab.tsx frontend/src/demo/variant-a/RankingTab.tsx docs/subsystems/webapp.md frontend/src/demo
git commit -m "feat(webapp): adopt Source/Translation labels with adaptive language names"
```

---

## Задача 5 [S]: скриншот-проверка + отчёт

Проектная конвенция e2e: агентный прогон + скриншот-отчёт по манифесту данных, НЕ новый Playwright-раннер. Сценарии — из спеки rev-3 «План скриншотов» (≥7).

**Files:**
- Отчёт: `docs/reports/` (HTML по шаблону из глобального CLAUDE.md, dark-тема)

- [ ] **Step 1: Запустить приложение на реальных данных**

Backend + frontend по инструкции `docs/subsystems/webapp.md` (seed `data/demo.db`, пилотный документ).

- [ ] **Step 2: Отснять сценарии**

1. Document-вкладка §1–§3: компактные чипы всех трёх полос (yellow 6.4 / green 8.0 ▲0.4 / red 5.7), гуттер исчез, панели шире.
2. Крупный план мета-строки: §N + score + дельта + cached; рядом кейс `aggregate=null` с em-dash.
3. Общий baseline: первые строки source/translation стартуют с одного y.
4. Заголовки `Source · Russian` / `Translation · English` (sticky).
5. Загруженная пара со свободным текстом языка: заголовок `Source · German`; та же пара в свитчере (без UPPERCASE).
6. Glossary `Source · …` / `Translation · …`; Ranking `Translation snippet`.
7. Loading-shimmer чипа во время живого eval (layout не дрожит, §N виден).
8. Регрессия правки: текст изменён в TipTap → PATCH ушёл (network), issue/терм-декорации целы.

Поведенческие проверки без скриншота: выбор абзаца кликом по мета-строке; переход из Ranking скроллит к `.va-para-row.selected`. Здесь же — браузерная проверка фактических цветов полос чипа (computed style соответствует `--va-green/--va-yellow/--va-red`), отложенная из Задачи 3.

- [ ] **Step 3: Собрать HTML-отчёт и поднять сервер**

Отчёт в `docs/reports/` по шаблону (Главное → 360 → обзор → находки → артефакты → next steps), скриншоты в `shots/`. Поднять `python3 -m http.server <порт≥8096> --bind 127.0.0.1` из каталога отчёта, дать прямую ссылку.

- [ ] **Step 4: Commit**

```bash
git add docs/reports
git commit -m "docs(reports): add rev-3 reading-pane verification report with screenshots"
```

---

## Self-Review (чеклист writing-plans; результат авторского прогона)

**1. Spec coverage (rev-3):**
- §1 компактный чип + фикс полос + em-dash + shimmer + testid + кликабельная мета → Задача 3; браузерная computed-style проверка → Задача 5.
- §2 типографика/baseline (самостоятельная первая задача) → Задача 1.
- §3 langLabel/isBcp47Like + принятая граница 'she' + разрешение с upload-polish (теперь ребейз на dev-demo) → Предпосылка + Задача 2.
- Инвентарь переименований, 8 строк → Задача 4 (строка 3 уже выполнена в dev-demo — проверка grep'ом).
- «Влияние на тесты» rev-3 (юниты langLabel/чип, ассерты заголовков, смерть `.va-para-gutter`, сохранение `.va-para-row.selected`) → Задачи 2, 3, 4.
- «План скриншотов» rev-3 (8 сценариев) → Задача 5.
- Отменённые разделы (aligned, segment-model, шов режимов, toggle, локаль сегментации) — в плане отсутствуют намеренно.

**2. Placeholder scan:** код приведён в каждом кодовом шаге; TBD/«similar to»/«fill in» отсутствуют.

**3. Type consistency:** `ScoreChipProps.label` (Задача 3 Step 3) = prop `label` в VariantA (Step 5); `isBcp47Like`/`langLabel` (Задача 2) — те же имена в тестах и в Задаче 4; `paragraphLabel` удаляется согласованно из Props, деструктуризации и call-site.
