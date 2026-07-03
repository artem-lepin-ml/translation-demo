/**
 * TipTap / ProseMirror extension: stacked-underline decorations.
 *
 * For each active Issue we locate its targetFragment inside the EN paragraph
 * text and compute elementary segments (between sorted boundary points). Each
 * segment gets a Decoration.inline whose inline-style stacks one colored
 * box-shadow underline per covering criterion (stacked for overlaps).
 *
 * Term decorations use targetSurface for the EN side, anchored by claim-based
 * occurrence matching: terms are processed in array order and each claims the
 * first free (unclaimed) EN occurrence of its surface, skipping occurrences
 * that overlap a range already claimed by an earlier term — this keeps a
 * shorter surface (e.g. "York") from matching inside a longer, already
 * decorated term's span (e.g. "New York"). Mirrors the RU pairIndex
 * derivation in SourceWithTerms. difficulty → RU-side dashed outline (handled
 * in SourceWithTerms); pairAccuracy → EN-side `verdict-{color}` outline class
 * + `data-verdict` (null → neutral outline). No separate dot indicator: the
 * dashed outline colour alone carries the signal.
 *
 * Re-applied whenever activeIssues or terms change (via setMeta).
 */

import { Extension } from '@tiptap/core';
import { Plugin, PluginKey } from '@tiptap/pm/state';
import { Decoration, DecorationSet } from '@tiptap/pm/view';
import type { Issue, Term } from '../api-client';

export type SegmentClickHandler = (issues: Issue[], rect: DOMRect) => void;

export interface ReviewExtensionOptions {
  activeIssues: Issue[];
  /** Issue ids whose status is accepted or dismissed (skip EN highlight) */
  closedIssueIds: Set<string>;
  onSegmentClick: SegmentClickHandler;
  terms?: Term[];
  showTerms?: boolean;
  hoveredTermId?: string | null;
  /** criterionId → CSS color string (for underline vars) */
  criterionColors: Record<string, string>;
}

export const reviewPluginKey = new PluginKey<DecorationSet>('reviewUnderlines');

/**
 * Build box-shadow CSS value that stacks N underlines below the text.
 * Each line is 2 px tall; lines are 4 px apart.
 */
function stackedUnderlineStyle(colors: string[]): string {
  const shadows = colors.map((color, i) => {
    const offset = -(2 + i * 4);
    return `inset 0 ${offset}px 0 0 ${color}`;
  });
  const paddingBottom = 2 + (colors.length - 1) * 4 + 2;
  return `box-shadow:${shadows.join(', ')};padding-bottom:${paddingBottom}px;cursor:pointer;border-radius:1px;`;
}

/** Locate all character offsets of `fragment` inside `text` (for issue segments). */
function findOccurrences(text: string, fragment: string): Array<{ from: number; to: number }> {
  const results: Array<{ from: number; to: number }> = [];
  let start = 0;
  while (start < text.length) {
    const idx = text.indexOf(fragment, start);
    if (idx === -1) break;
    results.push({ from: idx, to: idx + fragment.length });
    start = idx + 1;
  }
  return results;
}

export function createReviewExtension(initialOptions: ReviewExtensionOptions): Extension {
  return Extension.create({
    name: 'reviewUnderlines',

    addProseMirrorPlugins() {
      let currentOptions = { ...initialOptions };

      const plugin: Plugin = new Plugin({
        key: reviewPluginKey,

        state: {
          init(_, state) {
            return buildDecorations(state.doc, currentOptions);
          },
          apply(tr, oldSet, _oldState, newState) {
            const meta = tr.getMeta(reviewPluginKey);
            if (meta) {
              currentOptions = meta as ReviewExtensionOptions;
              return buildDecorations(newState.doc, currentOptions);
            }
            if (tr.docChanged) {
              return buildDecorations(newState.doc, currentOptions);
            }
            return oldSet.map(tr.mapping, newState.doc);
          },
        },

        props: {
          decorations(state) {
            return this.getState(state);
          },
        },
      });

      return [plugin];
    },
  });
}

/**
 * Caller contract: `opts.terms` must already be pre-filtered to the paragraph
 * being decorated. This function does not scope terms by paragraph — it
 * matches every given term's targetSurface against every paragraph's text.
 */
export function buildDecorations(
  doc: import('@tiptap/pm/model').Node,
  opts: ReviewExtensionOptions,
): DecorationSet {
  const { activeIssues, closedIssueIds, terms, showTerms, hoveredTermId, criterionColors } = opts;

  // Only underline open issues
  const visible = activeIssues.filter((iss) => !closedIssueIds.has(iss.id) && iss.status === 'open');

  const decos: Decoration[] = [];

  doc.forEach((paraNode, paraOffset) => {
    if (paraNode.type.name !== 'paragraph') return;

    const paraText = paraNode.textContent;
    const base = paraOffset + 1; // +1 for node open

    // ── Issue underline decorations (stacked for overlaps) ──────────────────
    type Span = { issue: Issue; from: number; to: number };
    const spans: Span[] = [];
    for (const issue of visible) {
      // Use targetFragment as the EN text to underline (§6)
      for (const occ of findOccurrences(paraText, issue.targetFragment)) {
        spans.push({ issue, from: occ.from, to: occ.to });
      }
    }

    if (spans.length > 0) {
      const boundaries = new Set<number>();
      for (const sp of spans) {
        boundaries.add(sp.from);
        boundaries.add(sp.to);
      }
      const sorted = Array.from(boundaries).sort((a, b) => a - b);

      for (let i = 0; i < sorted.length - 1; i++) {
        const segFrom = sorted[i];
        const segTo = sorted[i + 1];
        const mid = (segFrom + segTo) / 2;
        const covering = spans.filter((sp) => sp.from <= mid && mid < sp.to);
        if (covering.length === 0) continue;

        // Stable order: sort by criterionId so colors are always consistent
        covering.sort((a, b) => a.issue.criterionId.localeCompare(b.issue.criterionId));
        const colors = covering.map((sp) => {
          const color = criterionColors[sp.issue.criterionId];
          return color ?? '#7aa2f7';
        });
        const issueIds = covering.map((sp) => sp.issue.id).join(',');

        decos.push(
          Decoration.inline(base + segFrom, base + segTo, {
            class: 'va-underline-seg',
            style: stackedUnderlineStyle(colors),
            'data-issue-ids': issueIds,
          }),
        );
      }
    }

    // ── Term EN-side decorations (pairAccuracy signal; claim-based occurrence) ──
    if (showTerms && terms) {
      // Occurrence matching is claim-based, not just per-surface-sequential:
      // a per-paragraph registry of already-claimed [from,to) ranges prevents
      // a shorter surface (e.g. "York") from matching an occurrence that lies
      // inside a longer, already-decorated term's span (e.g. "New York").
      // Terms are still processed in array order (existing greedy design) —
      // the i-th term referencing a surface takes the i-th free, unclaimed
      // occurrence of it (mirrors the RU pairIndex derivation in
      // SourceWithTerms, keeping both sides in sync).
      const claimed: Array<{ from: number; to: number }> = [];
      const overlapsClaimed = (from: number, to: number) =>
        claimed.some((c) => from < c.to && to > c.from);

      terms.forEach((term, idx) => {
        const pairIndex = idx + 1;
        const surface = term.targetSurface;
        if (!surface) return; // no EN equivalent → RU badge only (SourceWithTerms)
        const occ = findOccurrences(paraText, surface).find(
          (o) => !overlapsClaimed(o.from, o.to),
        );
        if (!occ) return; // no free EN occurrence left → EN side dims for this term
        claimed.push(occ);

        const verdict = term.pairAccuracy; // null when difficulty=red → neutral, never green
        const isHovered = hoveredTermId === term.id;
        const cls =
          'va-term-span' +
          (verdict ? ` verdict-${verdict}` : '') +
          (isHovered ? ' term-cross-highlight' : '');
        const attrs: Record<string, string> = {
          class: cls,
          'data-term-id': term.id,
          'data-pair-idx': String(pairIndex),
        };
        if (verdict) attrs['data-verdict'] = verdict;
        decos.push(Decoration.inline(base + occ.from, base + occ.to, attrs));
      });
    }
  });

  return DecorationSet.create(doc, decos);
}
