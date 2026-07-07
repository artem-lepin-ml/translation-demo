/**
 * EditorParagraph — one aligned paragraph row in the Document tab.
 *
 * Left: RU original (read-only, clickable for selection, term spans supported)
 * Right: EN translation (TipTap editor, editable)
 * Meta strip: §N label + score chip (above the body row)
 *
 * Term highlights appear on BOTH sides with cross-hover pairing.
 * RU side: difficulty signal (🟢🟡🔴) via SourceWithTerms
 * EN side: pairAccuracy signal via review-extension decorations
 */

import { useEffect, useRef } from 'react';
import { useEditor, EditorContent } from '@tiptap/react';
import StarterKit from '@tiptap/starter-kit';
import { reviewPluginKey, createReviewExtension } from './review-extension';
import type { Issue, Term, Criterion, Score } from '../api-client';

export interface SegmentClickInfo {
  issues: Issue[];
  rect: DOMRect;
}

interface Props {
  paragraphIndex: number;
  initialText: string;
  sourceText: string;
  activeIssues: Issue[];
  closedIssueIds: Set<string>;
  terms: Term[];
  showTerms: boolean;
  criteria: Criterion[];
  selected: boolean;
  scoreChip: React.ReactNode;
  onSelect: () => void;
  onSegmentClick: (info: SegmentClickInfo) => void;
  onTextChange: (text: string) => void;
  onTermClick: (term: Term, rect: DOMRect) => void;
  hoveredTermId: string | null;
  onTermHover: (termId: string | null) => void;
}

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

export default function EditorParagraph({
  paragraphIndex: _paragraphIndex,
  initialText,
  sourceText,
  activeIssues,
  closedIssueIds,
  terms,
  showTerms,
  criteria,
  selected,
  scoreChip,
  onSelect,
  onSegmentClick,
  onTextChange,
  onTermClick,
  hoveredTermId,
  onTermHover,
}: Props) {
  const currentTextRef = useRef(initialText);

  const criterionColors: Record<string, string> = Object.fromEntries(
    criteria.map((c) => [c.id, c.color]),
  );

  const reviewExt = createReviewExtension({
    activeIssues,
    closedIssueIds,
    onSegmentClick: () => {},
    terms,
    showTerms,
    hoveredTermId,
    criterionColors,
  });

  const editor = useEditor({
    extensions: [StarterKit, reviewExt],
    content: `<p>${escapeHtml(initialText)}</p>`,
    autofocus: false,
    onUpdate({ editor: e }) {
      currentTextRef.current = e.getText();
      onTextChange(e.getText());
    },
  });

  // Sync editor content when the paragraph target changes server-side (e.g.
  // after accepting a fix). useEditor seeds content once, so a changed
  // initialText prop would otherwise never reach the document.
  useEffect(() => {
    if (!editor) return;
    if (initialText === currentTextRef.current) return;
    currentTextRef.current = initialText;
    editor.commands.setContent(`<p>${escapeHtml(initialText)}</p>`, { emitUpdate: false });
  }, [editor, initialText]);

  useEffect(() => {
    if (!editor) return;
    editor.view.dispatch(
      editor.view.state.tr.setMeta(reviewPluginKey, {
        activeIssues,
        closedIssueIds,
        onSegmentClick: () => {},
        terms,
        showTerms,
        hoveredTermId,
        criterionColors,
      }),
    );
  }, [editor, activeIssues, closedIssueIds, terms, showTerms, hoveredTermId]);

  const cssVars = Object.fromEntries(
    criteria.map((c) => [`--va-underline-${c.id}`, c.color]),
  );

  function handleEditorClick(e: React.MouseEvent<HTMLDivElement>) {
    const target = e.target as HTMLElement;
    const termEl = target.closest('[data-term-id]') as HTMLElement | null;
    if (termEl) {
      const termId = termEl.getAttribute('data-term-id');
      const term = terms.find((t) => t.id === termId);
      if (term) {
        onTermClick(term, termEl.getBoundingClientRect());
        return;
      }
    }
    const segEl = target.closest('[data-issue-ids]') as HTMLElement | null;
    if (segEl) {
      const ids = segEl.getAttribute('data-issue-ids')?.split(',') ?? [];
      const issues = activeIssues.filter(
        (iss) => ids.includes(iss.id) && iss.status === 'open' && !closedIssueIds.has(iss.id),
      );
      if (issues.length > 0) {
        e.stopPropagation();
        onSegmentClick({ issues, rect: segEl.getBoundingClientRect() });
        return;
      }
    }
    onSelect();
  }

  function handleEditorHover(e: React.MouseEvent<HTMLDivElement>) {
    const termEl = (e.target as HTMLElement).closest('[data-term-id]') as HTMLElement | null;
    onTermHover(termEl ? termEl.getAttribute('data-term-id') : null);
  }

  return (
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
  );
}

// ─── ScoreChip ────────────────────────────────────────────────────────────────

interface ScoreChipProps {
  label: string;               // §N — always visible, incl. loading state
  score: number | null;
  loading: boolean;
  delta: number | null;
  cached?: boolean;
  stale?: boolean;
  /** Enabled criteria + this paragraph's per-criterion scores — drives the
   * hover tooltip's breakdown. Optional/defaulted so existing chip call
   * sites (and the pre-existing unit tests) that only care about the
   * aggregate keep working unchanged; omitting them just shortens the
   * tooltip to the aggregate line. */
  criteria?: Criterion[];
  scores?: Score[];
}

/** Builds the score chip's hover-tooltip text: the aggregate line, one line
 * per enabled criterion (name + value), then any provenance notes (cached /
 * stale). A criterion value is rendered "…" while a rescore is in flight and
 * "—" when the paragraph genuinely has no score yet for that criterion —
 * same pending/absent convention the chip itself and InspectorPanel already
 * use, so no row is ever left blank or shows a broken/undefined value. */
export function buildScoreChipTooltip(
  label: string,
  score: number | null,
  loading: boolean,
  criteria: Criterion[],
  scores: Score[],
  cached?: boolean,
  stale?: boolean,
): string {
  const lines: string[] = [];
  const aggText = loading ? '…' : score !== null ? score.toFixed(1) : '—';
  lines.push(`${label} aggregate: ${aggText}`);
  for (const c of criteria.filter((c) => c.enabled)) {
    const v = scores.find((s) => s.criterionId === c.id)?.value ?? null;
    const valText = loading ? '…' : v !== null ? v.toFixed(1) : '—';
    lines.push(`${c.name}: ${valText}`);
  }
  if (cached) lines.push('Cached: offline fallback estimate, not a live judgment');
  if (stale) lines.push('Stale: scores refer to an earlier version of this paragraph');
  return lines.join('\n');
}

export interface DeltaBadge {
  glyph: '▲' | '▼';
  magnitude: string;
}

/** Old→new score delta for the chip badge: prefers aggregatePrev (set by a
 * live /evaluate), falling back to aggregateBaseline (precompute seed) when
 * aggregatePrev is undefined (e.g. straight from GET, before any /evaluate
 * call). Null when there's nothing to compare against, or when both sides
 * are equal (no visible change to badge). */
export function computeChipDelta(
  agg: number | null,
  aggregatePrev: number | null | undefined,
  aggregateBaseline: number | null,
): number | null {
  const prev = aggregatePrev !== undefined ? aggregatePrev : aggregateBaseline;
  if (agg === null || prev === null || prev === undefined || agg === prev) return null;
  return Math.round((agg - prev) * 10) / 10;
}

/** delta → badge decision. ``delta`` is null when there is no previous score
 * to compare against (first-ever score) or when a fallback rule already
 * suppressed it (e.g. cached === prev). Zero is suppressed here too — no
 * badge for an unchanged score. */
export function deltaBadge(delta: number | null): DeltaBadge | null {
  if (delta === null || delta === 0) return null;
  return { glyph: delta > 0 ? '▲' : '▼', magnitude: Math.abs(delta).toFixed(1) };
}

export function ScoreChip({
  label,
  score,
  loading,
  delta,
  cached,
  stale,
  criteria = [],
  scores = [],
}: ScoreChipProps) {
  const band = score !== null ? (score >= 8 ? 'green' : score >= 6 ? 'yellow' : 'red') : null;
  const badge = loading ? null : deltaBadge(delta);
  const tooltip = buildScoreChipTooltip(label, score, loading, criteria, scores, cached, stale);
  return (
    <span
      className={`va-score-chip${band ? ' ' + band : ''}`}
      data-testid="score-chip"
      title={tooltip}
    >
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
      {stale && (
        <span className="va-stale-badge" title="Scores refer to an earlier version of this paragraph">
          stale
        </span>
      )}
    </span>
  );
}

// ─── SourceWithTerms ──────────────────────────────────────────────────────────

/**
 * Renders the RU source text with term spans interleaved.
 * Shows difficulty signal (dashed outline colour) on each source term.
 * Uses charStart/charEnd from Term for exact positioning.
 */
interface SourceWithTermsProps {
  text: string;
  terms: Term[];
  hoveredTermId: string | null;
  onTermHover: (id: string | null) => void;
  onTermClick: (term: Term, rect: DOMRect) => void;
}

export interface Segment {
  kind: 'text' | 'term';
  content: string;
  term?: Term;
  pairIndex?: number;
  /** One level of nesting only: present on a 'term' segment that fully
   * contains another term's range (e.g. 'титулы эдикта' containing
   * 'эдикт'). When set, render children instead of `content` directly. */
  children?: Segment[];
}

function SourceWithTerms({ text, terms, hoveredTermId, onTermHover, onTermClick }: SourceWithTermsProps) {
  const segments: Segment[] = buildSourceSegments(text, terms);

  function renderTermSegment(seg: Segment, key: React.Key) {
    const term = seg.term!;
    const isHovered = hoveredTermId === term.id;
    // React's onMouseEnter/onMouseLeave don't bubble (unlike native
    // mouseover), so a nested span's handlers fire independently of its
    // parent's — hovering the inner span highlights only the inner term,
    // hovering the outer region highlights only the outer term. No
    // closest()-based delegation is used on this side (that pattern is
    // EN-only, see handleEditorHover below).
    return (
      // RU intentionally stays on difficulty-* (Wikidata grounding signal);
      // the EN pair-accuracy verdict is a separate signal, rendered via
      // verdict-* in review-extension.ts's buildDecorations.
      <span
        key={key}
        className={`va-term-span-source difficulty-${term.difficulty}${isHovered ? ' term-cross-highlight' : ''}`}
        data-term-id={term.id}
        data-difficulty={term.difficulty}
        onMouseEnter={() => onTermHover(term.id)}
        onMouseLeave={() => onTermHover(null)}
        onClick={(e) => {
          e.stopPropagation();
          onTermClick(term, (e.currentTarget as HTMLElement).getBoundingClientRect());
        }}
      >
        {seg.children ? (
          seg.children.map((child, i) =>
            child.kind === 'text' ? (
              <span key={i}>{child.content}</span>
            ) : (
              renderTermSegment(child, i)
            ),
          )
        ) : (
          seg.content
        )}
        <sup className="va-term-pair-idx">{seg.pairIndex}</sup>
      </span>
    );
  }

  return (
    <>
      {segments.map((seg, i) =>
        seg.kind === 'text' ? <span key={i}>{seg.content}</span> : renderTermSegment(seg, i),
      )}
    </>
  );
}

/**
 * Builds RU source segments from authoritative charStart/charEnd offsets
 * (never occurrence-search — RU offsets are ground truth).
 *
 * Supports exactly one level of nesting: when term B's range lies fully
 * inside term A's range, B renders as a nested <span> inside A's, splitting
 * A's text around it (so text is never double-rendered). Seed data only
 * ever produces single-level nesting (e.g. 'эдикт' ⊂ 'титулы эдикта'), so a
 * term nested inside an already-nested term is still dropped, same as a
 * partial (non-containment) overlap — both are ill-formed extractor output
 * rather than a shape this UI needs to represent.
 */
type TermOcc = { from: number; to: number; term: Term; pairIndex: number };

function isFullyInside(inner: TermOcc, outer: TermOcc): boolean {
  return inner.from >= outer.from && inner.to <= outer.to && inner !== outer;
}

export function buildSourceSegments(text: string, terms: Term[]): Segment[] {
  const termOccs: TermOcc[] = terms
    .map((term, idx) => ({
      from: term.charStart,
      to: term.charEnd,
      term,
      pairIndex: idx + 1,
    }))
    .filter((o) => o.from >= 0 && o.to <= text.length && o.from < o.to)
    // Widest-first so a containing term is considered before terms nested
    // inside it; ties broken by range width (wider = outer).
    .sort((a, b) => a.from - b.from || b.to - a.to);

  // Assign each occurrence to at most one containing occurrence (one level
  // of nesting only — a term nested inside an already-nested term has no
  // "grandparent" slot and is dropped, same as a partial overlap).
  const nestedIn = new Map<TermOcc, TermOcc>();
  for (const occ of termOccs) {
    const parent = termOccs.find((o) => !nestedIn.has(o) && isFullyInside(occ, o));
    if (parent) nestedIn.set(occ, parent);
  }

  const childrenOf = new Map<TermOcc, TermOcc[]>();
  for (const [child, parent] of nestedIn) {
    // Guard against the (seed data never produces this) case of 2+ terms
    // nested in the same parent: only the first-encountered (leftmost,
    // widest-first) child is kept, since the render side supports exactly
    // one nested span.
    if (!childrenOf.has(parent)) childrenOf.set(parent, [child]);
  }

  const segments: Segment[] = [];
  let cursor = 0;
  for (const occ of termOccs) {
    if (nestedIn.has(occ)) continue; // rendered as a child of its parent below
    if (occ.from < cursor) continue; // partial overlap with a prior top-level term — ill-formed data, drop
    if (occ.from > cursor) {
      segments.push({ kind: 'text', content: text.slice(cursor, occ.from) });
    }

    const nested = childrenOf.get(occ)?.[0];
    if (nested) {
      const children: Segment[] = [];
      if (nested.from > occ.from) {
        children.push({ kind: 'text', content: text.slice(occ.from, nested.from) });
      }
      children.push({
        kind: 'term',
        content: text.slice(nested.from, nested.to),
        term: nested.term,
        pairIndex: nested.pairIndex,
      });
      if (nested.to < occ.to) {
        children.push({ kind: 'text', content: text.slice(nested.to, occ.to) });
      }
      segments.push({
        kind: 'term',
        content: text.slice(occ.from, occ.to),
        term: occ.term,
        pairIndex: occ.pairIndex,
        children,
      });
    } else {
      segments.push({
        kind: 'term',
        content: text.slice(occ.from, occ.to),
        term: occ.term,
        pairIndex: occ.pairIndex,
      });
    }
    cursor = occ.to;
  }
  if (cursor < text.length) {
    segments.push({ kind: 'text', content: text.slice(cursor) });
  }
  return segments;
}
