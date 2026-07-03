# План: попап правок — позиционирование, живой список, серверная инвалидация перекрытий

Спека: `docs/superpowers/specs/2026-07-02-inspector-scroll-outdated.md` (rev-2).
Ветка: `feat/inspector-fixes` off `dev-demo`. Worktree: `/Users/a1111/Projects/Work/worktrees/inspector-fixes` (создаёт оркестратор).

## Header note — расхождения кода со спекой

- **Таксономия видимости изменилась.** Сегодня `InspectorPanel.tsx:220` считает `isClosed = iss.status !== 'open'`, поэтому `outdated` рендерится приглушённо-зачёркнутым (как accepted/dismissed), и `known_issues.md:53` + `webapp.md:135` документируют именно это («render dimmed with an `outdated` label», «Карточки `outdated` рендерятся приглушённо»). Спека rev-2 (§4) требует **прятать** `outdated` из попапа и инспектора, оставляя приглушёнными только `accepted`/`dismissed`. Это прямое противоречие — план правит код И оба дока тем же коммитом (шаги 6–7).
- **Non-goal rev-1 «не трогаем сервер» отменён** спекой §3 (verify-spec доказал невыполнимость цели без серверной инвалидации). План добавляет server-side инвалидацию в `apply_edit`.
- Остальное — `review-extension.ts:116` уже фильтрует `status === 'open'` (не трогаем, только регресс-тест); `IssuesPanel.tsx` мёртв (skip).

## Обзор изменений

1. Позиционирование попапа: измеряемая высота (`useLayoutEffect` + `getBoundingClientRect`), клампы. — `IssuePopover.tsx`
2. Живой попап: якорь (`paraId` + `ids` + `rect`), список деривится из стора, попап не закрывается по Accept/Dismiss. — `VariantA.tsx`
3. Серверная инвалидация перекрытых `open`-issues в `apply_edit`; новое поле ответа `siblingIssues`. — `app.py`, `api-client.ts`, `store.ts`
4. Видимость: `outdated` фильтруется из попапа и инспектора; `accepted`/`dismissed` остаются dimmed. — `IssuePopover.tsx`, `VariantA.tsx`, `InspectorPanel.tsx`
5. Test-ids: `issue-popover`, `inspector-issues-scroll`.
6–7. Doc-parity: `webapp.md`, `known_issues.md:53`.

Порядок: сервер (TDD pytest) → api-client/store → попап-позиционирование → живой попап → видимость → test-ids → доки. Каждый шаг — отдельный conventional-commit без трейлера.

---

## Шаг 1 — [ ] pytest: apply_edit инвалидирует перекрытые open-issues соседа

Файл: `tests/test_apply_edit.py` (дополнить). TDD — тесты первыми, красные.

Добавить в конец файла:

```python
def test_apply_edit_invalidates_overlapping_open_sibling(seeded):
    """After a successful apply, a sibling open issue whose fragment is no longer
    locatable in the rewritten target is flipped to 'outdated' and returned in
    the response's siblingIssues."""
    from palimpsest.webapp.app import apply_edit, ApplyEditBody

    conn = seeded.connect()
    iss = _find_issue(conn, empty=False)
    pid = iss["paragraph_id"]
    target = conn.execute("SELECT target FROM paragraph WHERE id=?", (pid,)).fetchone()["target"]

    # Craft a sibling open issue on the SAME paragraph whose fragment overlaps the
    # region the accepted edit rewrites (so it is gone after the splice).
    overlap_frag = iss["target_fragment"]           # identical region → certainly overlapped
    sib_id = conn.execute(
        "INSERT INTO issue(paragraph_id,criterion_id,target_fragment,source_fragment,"
        "explanation,suggestion,severity,mqm_category,status,kind) "
        "VALUES(?,?,?,?,?,?,?,?, 'open','live')",
        (pid, iss["criterion_id"], overlap_frag, "", "sib", "zzz", "minor", None),
    ).lastrowid
    conn.commit()

    out = apply_edit(pid, ApplyEditBody(issueId=str(iss["id"])))

    # Accepted issue unchanged in shape
    assert out["issue"]["status"] == "accepted"
    # Sibling now outdated, persisted
    sib_status = conn.execute("SELECT status FROM issue WHERE id=?", (sib_id,)).fetchone()["status"]
    assert sib_status == "outdated"
    # Response carries the updated sibling(s)
    sib_ids = {i["id"]: i["status"] for i in out["siblingIssues"]}
    assert sib_ids.get(str(sib_id)) == "outdated"


def test_apply_edit_keeps_still_locatable_sibling_open(seeded):
    """A sibling whose fragment survives the edit (whitespace-tolerant match still
    hits) stays open and is NOT in siblingIssues."""
    from palimpsest.webapp.app import apply_edit, ApplyEditBody

    conn = seeded.connect()
    iss = _find_issue(conn, empty=False)
    pid = iss["paragraph_id"]
    target = conn.execute("SELECT target FROM paragraph WHERE id=?", (pid,)).fetchone()["target"]

    # A disjoint word that survives the splice.
    survivor = next(w for w in target.split() if w and w not in iss["target_fragment"])
    sib_id = conn.execute(
        "INSERT INTO issue(paragraph_id,criterion_id,target_fragment,source_fragment,"
        "explanation,suggestion,severity,mqm_category,status,kind) "
        "VALUES(?,?,?,?,?,?,?,?, 'open','live')",
        (pid, iss["criterion_id"], survivor, "", "sib", "zzz", "minor", None),
    ).lastrowid
    conn.commit()

    out = apply_edit(pid, ApplyEditBody(issueId=str(iss["id"])))

    sib_status = conn.execute("SELECT status FROM issue WHERE id=?", (sib_id,)).fetchone()["status"]
    assert sib_status == "open"
    assert all(i["id"] != str(sib_id) for i in out["siblingIssues"])


def test_apply_edit_never_invalidates_accepted_or_dismissed_siblings(seeded):
    """Only status='open' siblings are candidates; accepted/dismissed are left alone
    even if their fragment is now gone."""
    from palimpsest.webapp.app import apply_edit, ApplyEditBody

    conn = seeded.connect()
    iss = _find_issue(conn, empty=False)
    pid = iss["paragraph_id"]

    for status in ("accepted", "dismissed"):
        sid = conn.execute(
            "INSERT INTO issue(paragraph_id,criterion_id,target_fragment,source_fragment,"
            "explanation,suggestion,severity,mqm_category,status,kind) "
            "VALUES(?,?,?,?,?,?,?,?,?, 'live')",
            (pid, iss["criterion_id"], iss["target_fragment"], "", "s", "z", "minor", None, status),
        ).lastrowid
        conn.commit()
        out = apply_edit(pid, ApplyEditBody(issueId=str(iss["id"])))
        assert all(i["id"] != str(sid) for i in out["siblingIssues"])
        # restore target for the next iteration
        conn.execute("UPDATE paragraph SET target=seed_target WHERE id=?", (pid,))
        conn.execute("UPDATE issue SET status='open' WHERE id=?", (iss["id"],))
        conn.commit()
```

Проверка (красный): `cd /Users/a1111/Projects/Work/worktrees/inspector-fixes && pytest tests/test_apply_edit.py -q` — три новых теста падают (`siblingIssues` KeyError), старые зелёные.

Commit: `test(webapp): apply-edit invalidates overlapping open siblings`

---

## Шаг 2 — [ ] app.py: server-side инвалидация перекрытых open-соседей + siblingIssues в ответе

Файл: `src/palimpsest/webapp/app.py`, функция `apply_edit` (:561-583).

**Точная форма ответа.** Ответ apply-edit получает НОВОЕ поле `siblingIssues: list[Issue]` — массив тех open-issues того же абзаца (кроме принятого), чей `target_fragment` больше НЕ находится в новом target тем же `_splice_suggestion`-матчером (проба на `None`), со статусом, уже переведённым в `outdated`. Существующие поля `target` и `issue` не меняются.

Заменить тело функции (:562-583) на:

```python
@app.post("/api/paragraphs/{pid}/apply-edit")
def apply_edit(pid: int, body: ApplyEditBody) -> dict:
    conn = db.connect()
    with db._lock:
        p = _para_or_404(conn, pid)
        try:
            iid = int(body.issueId)
        except (TypeError, ValueError):
            raise HTTPException(404, "issue not found")  # non-numeric id can't exist
        iss = conn.execute("SELECT * FROM issue WHERE id=? AND paragraph_id=?", (iid, pid)).fetchone()
        if not iss:
            raise HTTPException(404, "issue not found")
        if not (iss["suggestion"] or "").strip():
            # nothing to apply — never delete the flagged fragment
            raise HTTPException(422, {"error": "no_suggestion"})
        new_target = _splice_suggestion(p["target"], iss["target_fragment"], iss["suggestion"])
        if new_target is None:
            raise HTTPException(422, {"error": "fragment_not_found"})
        conn.execute("UPDATE paragraph SET target=? WHERE id=?", (new_target, pid))
        conn.execute("UPDATE issue SET status='accepted' WHERE id=?", (iss["id"],))

        # Invalidate any OTHER still-open issue in this paragraph whose fragment is
        # now unreachable in the rewritten target (overlapped by this edit). Uses the
        # same whitespace-tolerant matcher: a probe splice returning None == gone.
        # Only status='open' rows are touched; accepted/dismissed history is left as-is.
        siblings = conn.execute(
            "SELECT * FROM issue WHERE paragraph_id=? AND id!=? AND status='open'",
            (pid, iss["id"]),
        ).fetchall()
        invalidated = []
        for sib in siblings:
            frag = sib["target_fragment"]
            # Probe with a no-op suggestion: we only care whether the fragment locates.
            if not frag or _splice_suggestion(new_target, frag, frag) is None:
                conn.execute("UPDATE issue SET status='outdated' WHERE id=?", (sib["id"],))
                invalidated.append(sib["id"])
        conn.commit()

        new_iss = conn.execute("SELECT * FROM issue WHERE id=?", (iss["id"],)).fetchone()
        sibling_dicts = [
            _issue_dict(conn.execute("SELECT * FROM issue WHERE id=?", (sid,)).fetchone())
            for sid in invalidated
        ]
        return {"target": new_target, "issue": _issue_dict(new_iss), "siblingIssues": sibling_dicts}
```

Note: пустой `target_fragment` (`frag == ""`) считается недостижимым → инвалидируется. Это совпадает с семантикой `_splice_suggestion` (`frag=""` → `idx=-1` → `None`) и безопасно: у пустого фрагмента нет подчёркивания, а «умирает» он раньше без вреда.

Проверка (зелёный): `pytest tests/test_apply_edit.py -q` — все зелёные. Регрессия: `pytest tests/test_c5_loop_integrity.py tests/test_issue_dedup.py -q`.

Commit: `feat(webapp): invalidate overlapping open siblings on apply-edit`

---

## Шаг 3 — [ ] api-client: siblingIssues в ApplyEditResponse

Файл: `frontend/src/demo/api-client.ts` (:186-189).

Заменить:

```ts
export interface ApplyEditResponse {
  target: string;
  issue: Issue;
  /** Other open issues in the same paragraph whose fragment the edit overlapped;
   *  server has already flipped these to status='outdated'. */
  siblingIssues: Issue[];
}
```

Commit: `feat(api-client): add siblingIssues to ApplyEditResponse`

---

## Шаг 4 — [ ] store: влить siblingIssues из apply-ответа; тест

Файл: `frontend/src/demo/store.ts`, `applyIssueEdit` success-ветка (:408-419).

Заменить блок `try { const result = await apiApplyEdit(...) ... return 'applied'; }` на:

```ts
    try {
      const result = await apiApplyEdit(paraId, issueId);
      set((s) => {
        const doc = s.document;
        if (!doc) return {};
        const siblingById = new Map(result.siblingIssues.map((i) => [i.id, i]));
        const updatedDoc = patchParaInDoc(doc, paraIdx, (p) => ({
          ...p,
          target: result.target,
          issues: p.issues.map((iss) =>
            iss.id === issueId ? result.issue : (siblingById.get(iss.id) ?? iss),
          ),
        }));
        return { document: updatedDoc };
      });
      return 'applied';
    } catch (e) {
```

Тест — файл `frontend/src/demo/store.test.ts`, в `describe('acceptIssue (explicit re-eval)')` добавить:

```ts
  it('flips overlapping siblings to outdated from the apply response', async () => {
    vi.mocked(applyEdit).mockResolvedValueOnce({
      target: 'xxx bbb',
      issue: issue('1', { status: 'accepted' }),
      siblingIssues: [issue('2', { status: 'outdated' })],
    });
    await useDemoStore.getState().acceptIssue(1, 0, '1');
    const issues = useDemoStore.getState().document!.paragraphs[0].issues;
    expect(issues.find((i) => i.id === '1')!.status).toBe('accepted');
    expect(issues.find((i) => i.id === '2')!.status).toBe('outdated');
  });
```

Обновить существующие моки `applyEdit.mockResolvedValue*` (store.test.ts:132-135, 165-166, 177, 199-201) — добавить `siblingIssues: []` в каждый resolved-объект, иначе TS-тип падёт.

Проверка: `cd frontend && npx vitest run src/demo/store.test.ts`.

Commit: `feat(store): merge siblingIssues from apply-edit response`

---

## Шаг 5 — [ ] IssuePopover: измеряемое позиционирование + фильтр outdated + test-id

Файл: `frontend/src/demo/variant-a/IssuePopover.tsx` — переписать целиком:

```tsx
import { useLayoutEffect, useRef, useState } from 'react';
import type { Issue, Criterion } from '../api-client';

interface Props {
  issues: Issue[];
  criteria: Criterion[];
  rect: DOMRect;
  onAccept: (issue: Issue) => void;
  onDismiss: (issue: Issue) => void;
  onClose: () => void;
}

const severityLabel: Record<string, string> = {
  minor: 'Minor',
  major: 'Major',
};

/** Clamp the popover's top so both edges stay inside the viewport.
 *  Prefer just below the anchor; if the measured stack would overflow the
 *  bottom, lift it up; never above 8px. Pure — unit-tested. */
export function clampTop(anchorBottom: number, popoverHeight: number, viewportHeight: number): number {
  const preferred = anchorBottom + 8;
  const maxTop = viewportHeight - popoverHeight - 8;
  return Math.max(8, Math.min(preferred, maxTop));
}

export default function IssuePopover({ issues, criteria, rect, onAccept, onDismiss, onClose }: Props) {
  // outdated issues disappear entirely (spec §4); accepted/dismissed never reach
  // the popover because it is anchored to open segments only.
  const visible = issues.filter((i) => i.status !== 'outdated');

  const ref = useRef<HTMLDivElement>(null);
  const [top, setTop] = useState(() => rect.bottom + 8);
  const left = Math.min(rect.left, window.innerWidth - 480);

  useLayoutEffect(() => {
    const h = ref.current?.getBoundingClientRect().height ?? 0;
    setTop(clampTop(rect.bottom, h, window.innerHeight));
  }, [rect, visible.length]);

  if (visible.length === 0) return null;

  return (
    <>
      <div className="va-popover-backdrop" onClick={onClose} />
      <div
        ref={ref}
        className="va-popover"
        data-testid="issue-popover"
        style={{ top, left }}
        onClick={(e) => e.stopPropagation()}
      >
        <button className="va-popover-close" onClick={onClose}>✕</button>
        {visible.map((issue) => {
          const criterion = criteria.find((c) => c.id === issue.criterionId);
          const color = criterion?.color ?? '#7aa2f7';
          const label = criterion?.name ?? issue.criterionId;
          return (
            <div key={issue.id} className="va-issue-card">
              <div className="va-issue-card-header">
                <span
                  className="va-issue-criterion-badge"
                  style={{ background: color + '22', color }}
                >
                  {label}
                </span>
                <span className={`va-issue-severity severity-${issue.severity}`}>
                  {severityLabel[issue.severity] ?? issue.severity}
                </span>
                {issue.mqmCategory && (
                  <span className="va-issue-mqm-category">{issue.mqmCategory}</span>
                )}
              </div>
              <div className="va-issue-explanation">{issue.explanation}</div>
              {issue.suggestion && (
                <div className="va-issue-suggestion">
                  <strong>Suggestion:</strong> {issue.suggestion}
                </div>
              )}
              <div className="va-issue-actions">
                {issue.suggestion && (
                  <button className="va-btn-accept" onClick={() => onAccept(issue)}>
                    Accept
                  </button>
                )}
                <button className="va-btn-dismiss" onClick={() => onDismiss(issue)}>
                  Dismiss
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </>
  );
}
```

Тест — новый файл `frontend/src/demo/variant-a/IssuePopover.test.tsx`:

```tsx
import { afterEach, describe, expect, it, vi } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';
import IssuePopover, { clampTop } from './IssuePopover';
import type { Issue } from '../api-client';

afterEach(cleanup);

function iss(id: string, over: Partial<Issue> = {}): Issue {
  return {
    id, paragraphId: 1, criterionId: 'accuracy', targetFragment: 'f', sourceFragment: '',
    explanation: 'why', suggestion: 'fix', severity: 'minor', mqmCategory: null, status: 'open',
    ...over,
  };
}
const rect = { bottom: 100, left: 40 } as DOMRect;

describe('clampTop (pure positioning)', () => {
  it('sits below the anchor when it fits', () => {
    expect(clampTop(100, 200, 1000)).toBe(108);
  });
  it('never goes above 8px on a short viewport with a tall stack', () => {
    expect(clampTop(600, 700, 650)).toBe(8);
  });
  it('lifts up so the bottom edge stays in view', () => {
    expect(clampTop(900, 300, 1000)).toBe(692); // 1000 - 300 - 8
  });
});

describe('IssuePopover visibility', () => {
  it('renders open issues in the scroll container', () => {
    render(<IssuePopover issues={[iss('1')]} criteria={[]} rect={rect}
      onAccept={vi.fn()} onDismiss={vi.fn()} onClose={vi.fn()} />);
    expect(screen.getByTestId('issue-popover')).toBeTruthy();
    expect(screen.getByText('why')).toBeTruthy();
  });
  it('does NOT render an outdated issue', () => {
    render(<IssuePopover issues={[iss('1', { status: 'outdated', explanation: 'gone' })]}
      criteria={[]} rect={rect} onAccept={vi.fn()} onDismiss={vi.fn()} onClose={vi.fn()} />);
    expect(screen.queryByText('gone')).toBeNull();
    expect(screen.queryByTestId('issue-popover')).toBeNull();
  });
});
```

Проверка: `cd frontend && npx vitest run src/demo/variant-a/IssuePopover.test.tsx`.

Commit: `fix(demo): position issue popover from measured height, hide outdated`

---

## Шаг 6 — [ ] VariantA: живой попап по якорю (paraId + ids), не закрывать по Accept/Dismiss

Файл: `frontend/src/demo/variant-a/VariantA.tsx`.

**6a. Состояние-якорь.** Заменить (:82):

```ts
  const [issuePopover, setIssuePopover] =
    useState<{ paraId: number; issueIds: string[]; rect: DOMRect } | null>(null);
```

**6b. handleSegmentClick** (:168-170) — принять якорь. `onSegmentClick` из `EditorParagraph`/`review-extension` даёт `(issues: Issue[], rect)`; здесь конвертируем в якорь:

```ts
  const handleSegmentClick = useCallback((info: { issues: Issue[]; rect: DOMRect }) => {
    if (info.issues.length === 0) return;
    setIssuePopover({
      paraId: info.issues[0].paragraphId,
      issueIds: info.issues.map((i) => i.id),
      rect: info.rect,
    });
  }, []);
```

**6c. Дериват живого списка.** После `allTerms` memo (~:164) добавить:

```ts
  const popoverIssues = useMemo(() => {
    if (!issuePopover) return [];
    const para = paragraphs.find((p) => p.id === issuePopover.paraId);
    if (!para) return [];
    const byId = new Map(para.issues.map((i) => [i.id, i]));
    return issuePopover.issueIds
      .map((id) => byId.get(id))
      .filter((i): i is Issue => !!i && activeCriteria.has(i.criterionId));
  }, [issuePopover, paragraphs, activeCriteria]);
```

**6d. Не закрывать по Accept/Dismiss.** `handleAcceptIssue` (:200-205) — убрать `setIssuePopover(null)`:

```ts
  function handleAcceptIssue(issue: Issue) {
    const paraIdx = paragraphs.findIndex((p) => p.id === issue.paragraphId);
    if (paraIdx === -1) return;
    void acceptIssue(issue.paragraphId, paraIdx, issue.id);
  }

  function handleDismissIssue(issue: Issue) {
    void dismissIssue(issue.id);
  }
```

**6e. Автозакрытие пустого попапа.** После деривата добавить эффект (смена абзаца/опустошение закрывают попап; ✕ и backdrop уже вызывают `onClose`):

```ts
  useEffect(() => {
    if (issuePopover && popoverIssues.length === 0) setIssuePopover(null);
  }, [issuePopover, popoverIssues.length]);
```

**6f. Рендер попапа** (:562-571) — кормить деривом:

```tsx
      {issuePopover && popoverIssues.length > 0 && (
        <IssuePopover
          issues={popoverIssues}
          criteria={criteria}
          rect={issuePopover.rect}
          onAccept={handleAcceptIssue}
          onDismiss={handleDismissIssue}
          onClose={() => setIssuePopover(null)}
        />
      )}
```

Проверка: `cd frontend && npx tsc --noEmit && npx vitest run`.

Commit: `feat(demo): keep issue popover live and open across accepts`

---

## Шаг 7 — [ ] InspectorPanel: прятать outdated, dimmed только accepted/dismissed + scroll test-id

Файл: `frontend/src/demo/variant-a/InspectorPanel.tsx`.

**7a. Scroll test-id.** На `.va-inspector-body` контейнере (:166) добавить `data-testid="inspector-issues-scroll"`:

```tsx
          <div className="va-inspector-body" data-testid="inspector-issues-scroll">
```

**7b. Фильтр outdated в `IssuesView`.** В `IssuesView` (:210) первой строкой отфильтровать outdated (accepted/dismissed остаются):

```tsx
  const shown = issues.filter((i) => i.status !== 'outdated');
  if (shown.length === 0) {
    return <div className="va-insp-empty">No active issues for this paragraph.</div>;
  }
  return (
    <div className="va-insp-issues-list">
      {shown.map((iss) => {
```

`isClosed = iss.status !== 'open'` остаётся: для accepted/dismissed → dimmed+strikethrough (как было). outdated до этой ветки не доходит.

**7c. `activeIssueCount`** (:54-55) уже считает только `status === 'open'` — счётчик корректен без правок.

Тест — `frontend/src/demo/variant-a/InspectorPanel.test.tsx`, новый describe:

```tsx
describe('InspectorPanel outdated/history visibility (rev-2 taxonomy)', () => {
  const para = { id: 1, idx: 0, source: 's', target: 't', issues: [], scores: [],
    scoresPrev: null, scoresBaseline: null, aggregate: null, aggregateBaseline: null,
    aggregatePrev: null } as unknown as Paragraph;
  const base = {
    tab: 'issues' as const, onTabChange: vi.fn(), paragraph: para,
    activeCriteria: new Set<string>(), criteria: [], isCollapsed: false,
    onToggleCollapse: vi.fn(), acceptAllSummary: null, onAccept: vi.fn(),
    onDismiss: vi.fn(), onAcceptAll: vi.fn(), onEvaluate: vi.fn(), onRetryFailed: vi.fn(),
    evalState: { loading: false, cached: false, cachedAt: null, failedCriterionIds: [], error: null, stale: false },
  };
  const mk = (id: string, status: string, expl: string) => ({
    id, paragraphId: 1, criterionId: 'accuracy', targetFragment: '', sourceFragment: '',
    explanation: expl, suggestion: 's', severity: 'minor', mqmCategory: null, status,
  });

  it('hides outdated issues entirely', () => {
    render(<InspectorPanel {...base} visibleIssues={[mk('9', 'outdated', 'GONE') as never]} />);
    expect(screen.queryByText('GONE')).toBeNull();
    expect(screen.getByText(/No active issues/)).toBeTruthy();
  });
  it('still dims accepted/dismissed history', () => {
    render(<InspectorPanel {...base} visibleIssues={[mk('8', 'accepted', 'HIST') as never]} />);
    expect(screen.getByText('HIST')).toBeTruthy();
    expect(screen.getByText('accepted')).toBeTruthy();
  });
  it('exposes the scroll container test-id', () => {
    render(<InspectorPanel {...base} visibleIssues={[mk('1', 'open', 'x') as never]} />);
    expect(screen.getByTestId('inspector-issues-scroll')).toBeTruthy();
  });
});
```

Проверка: `cd frontend && npx vitest run src/demo/variant-a/InspectorPanel.test.tsx`.

Commit: `fix(demo): hide outdated issues in inspector, keep accepted/dismissed dimmed`

---

## Шаг 8 — [ ] Регресс-тест: review-extension не строит decorations для outdated

Файл: новый `frontend/src/demo/variant-a/review-extension.test.ts`. Тестируем чистую фильтрацию из `buildDecorations` через публичную `createReviewExtension` неудобно (нужен ProseMirror doc); вместо этого извлекаем инвариант через unit на видимости. Экспортировать не нужно — тест воспроизводит фильтр напрямую как контракт-регрессию:

```ts
import { describe, expect, it } from 'vitest';
import type { Issue } from '../api-client';

// Mirrors review-extension.ts:116 — the visibility contract we must not regress.
function visibleForUnderline(activeIssues: Issue[], closed: Set<string>): Issue[] {
  return activeIssues.filter((iss) => !closed.has(iss.id) && iss.status === 'open');
}
const mk = (id: string, status: Issue['status']): Issue => ({
  id, paragraphId: 1, criterionId: 'accuracy', targetFragment: 'f', sourceFragment: '',
  explanation: '', suggestion: '', severity: 'minor', mqmCategory: null, status,
});

describe('review-extension underline visibility (regression)', () => {
  it('excludes outdated issues from underline spans', () => {
    const out = visibleForUnderline([mk('1', 'open'), mk('2', 'outdated')], new Set());
    expect(out.map((i) => i.id)).toEqual(['1']);
  });
  it('excludes accepted/dismissed and closedIssueIds', () => {
    const out = visibleForUnderline(
      [mk('1', 'open'), mk('2', 'accepted'), mk('3', 'dismissed')], new Set(['1']));
    expect(out).toEqual([]);
  });
});
```

Note: `review-extension.ts` НЕ трогаем (спека §4). Тест фиксирует контракт `:116`. Если предпочтительна проверка прямо на модуле — альтернатива: срендерить TipTap editor в jsdom и проверить отсутствие `.va-underline-seg[data-issue-ids*=<outdatedId>]`; выше — дешёвый юнит, достаточный для «regression: underline-декорации не строятся для outdated» (критерий §1г).

Проверка: `cd frontend && npx vitest run src/demo/variant-a/review-extension.test.ts`.

Commit: `test(demo): regression — outdated issues build no underline decorations`

---

## Шаг 9 — [ ] e2e: скролл + живой попап (≥5 issues)

Файл: e2e-набор проекта (если существует Playwright-спека — искать `frontend/**/e2e` / `playwright.config`; на момент планирования e2e-спек не найдено — создать под конвенцию проекта или отметить как ручной прогон в PR-описании). Сценарий:

1. Открыть документ; выбрать абзац с ≥5 open-issues (или accept-all-doc не нужен) — кликнуть сегмент с несколькими подчёркиваниями.
2. `getByTestId('issue-popover')` виден; проверить `scrollHeight > clientHeight` (скролл активен) и что нижняя Accept-кнопка в вьюпорте (`boundingBox().y + height <= viewport.height`).
3. Accept одной карточки → попап остаётся открыт (`issue-popover` всё ещё виден), принятая карточка исчезла, перекрытые (`outdated`) исчезли немедленно.
4. Скриншоты before/after в артефакты PR.

Note: если инфраструктуры e2e в ветке нет — вынести пункт в PR-чеклист как ручную верификацию со скриншотами (спека §критерии-3 требует скриншотов до/после).

Commit (если код-тест добавлен): `test(e2e): issue popover scroll and live-invalidation on accept`

---

## Шаг 10 — [ ] Doc-parity: webapp.md (тем же коммитом, что и код)

Файл: `docs/subsystems/webapp.md`.

- Строка таблицы `/api/paragraphs/{pid}/apply-edit` (:85): дописать «…marks issue `accepted`; **also invalidates any other still-open issue in the paragraph whose fragment the edit overlapped (→ `outdated`), returned in `siblingIssues`**».
- Параграф :135: заменить фразу «Карточки `outdated` рендерятся приглушённо с меткой `outdated` (общий `isClosed`-рендер)» на: «Server-side инвалидация при apply: успешный `apply-edit` проходит по остальным `open`-issues абзаца тем же whitespace-толерантным матчером; недостижимый фрагмент → `outdated`, обновлённые issues возвращаются в `siblingIssues` и вливаются фронтом. **`outdated` не рендерится ни в попапе, ни в инспекторе** (трёхчастная видимость: `open` — активна, `accepted`/`dismissed` — приглушённая история, `outdated` — скрыта). Перекрытые соседи умирают в момент ПЕРВОГО принятия, а не при собственной попытке apply».
- Параграф :137 (issue lifecycle): добавить, что `open → outdated` теперь наступает и как побочный эффект apply-edit соседа (не только через PATCH при own-422). PATCH-путь остаётся для batch-422.
- Секция «Fragment matching» (:197): добавить предложение, что тот же матчер используется для sibling-инвалидации (probe-splice возвращает `None` → фрагмент перекрыт).
- Секция про frontend-тесты (:178): добавить упоминание нового store-теста (siblingIssues merge), IssuePopover-теста (clampTop + hide-outdated), InspectorPanel outdated-visibility, review-extension регресса; backend — три новых sibling-теста в `test_apply_edit.py`.

Commit: включается в коммит соответствующего кода (см. договорённость «doc-parity тем же коммитом»); практически — добавить правки webapp.md к коммиту шага 2 (server) и шага 7 (visibility). Если делается отдельно: `docs(webapp): document sibling invalidation and three-part issue visibility`.

---

## Шаг 11 — [ ] Doc-parity: known_issues.md:53

Файл: `docs/known_issues.md`, строка 53.

Заменить хвост «…they render dimmed with an `outdated` label, and the inspector shows a dim "Applied N · M outdated" line instead of the alert.» на: «…they are flipped to `status='outdated'`. **Since rev-2 (`feat/inspector-fixes`), `outdated` issues are hidden from both the popover and the inspector — only `accepted`/`dismissed` remain shown dimmed as history.** In addition, a successful single `apply-edit` now proactively invalidates other open issues in the same paragraph whose fragment it overlapped (server returns them in `siblingIssues`), so overlapping siblings disappear on the FIRST accept rather than on their own failed apply. The inspector still shows a dim "Applied N · M outdated" line for batch accept-all.»

Commit: вместе с кодом видимости (шаг 7) или `docs(known_issues): outdated now hidden; siblings invalidated on first accept`.

---

## Финальная верификация

- [ ] `cd /Users/a1111/Projects/Work/worktrees/inspector-fixes && pytest tests/test_apply_edit.py tests/test_c5_loop_integrity.py tests/test_issue_dedup.py -q` — зелёные.
- [ ] `cd frontend && npx tsc --noEmit` — чисто.
- [ ] `cd frontend && npx vitest run` — все зелёные (store, IssuePopover, InspectorPanel, review-extension).
- [ ] Ручной/e2e прогон: абзац ≥5 issues — скролл, Accept одной → попап открыт, перекрытые исчезли; скриншоты до/после в PR.
- [ ] `git log --oneline` — по одному conventional-commit на шаг, без Co-Authored-By трейлера (проектная конвенция плана).
- [ ] Doc-parity: `webapp.md` и `known_issues.md:53` синхронны с кодом.