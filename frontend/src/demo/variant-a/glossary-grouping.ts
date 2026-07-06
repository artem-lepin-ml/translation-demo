/**
 * glossary-grouping.ts — pure data-shaping helpers for the Glossary tab redesign.
 * Spec: docs/superpowers/specs/2026-07-05-glossary-redesign-impl.md §2.1-2.3.
 *
 * Deliberately React-free so grouping / badge-resolution logic stays unit
 * testable without mounting anything.
 */
import type { Paragraph, Term, Verdict, WikidataRef } from '../api-client';

// ─── trace_json shape (forward-looking) ─────────────────────────────────────
// The backend DTO field is `traceJson` (§4 of the spec). Today's seed data
// ships `trace_json='{}'` for every row (mock — see spec §0), so every field
// below is optional and callers MUST degrade gracefully when it's empty or
// missing entirely.

export interface TraceStep {
  method?: string;
  hits?: number;
  lemma?: string;
  lemma_hits?: number;
  surface?: string;
  surface_hits?: number;
  exact_matches?: number;
  resolved_by?: string;
  model?: string;
  api_calls?: number;
  llm_calls?: number;
  elapsed_s?: number;
}

export interface TraceJson {
  resolved_by?: string;
  model?: string;
  judge_reason?: string;
  query?: TraceStep;
  search?: TraceStep;
  label_match?: TraceStep;
  decision?: TraceStep;
}

/** `Term` once the backend lane adds `traceJson` to the DTO. A plain `Term`
 *  (no `traceJson` key at all) is still structurally assignable here since
 *  the field is optional — safe to use whether or not the backend field has
 *  landed yet in `api-client.ts`. */
export type TermWithTrace = Term & { traceJson?: TraceJson };

export type BadgeTone = 'det' | 'llm' | 'rej' | 'none';

export interface Badge {
  tone: BadgeTone;
  label: string;
}

const DEFAULT_MODEL_LABEL = 'LLM';

function isEmptyTrace(trace: TraceJson | undefined): boolean {
  return !trace || Object.keys(trace).length === 0;
}

/**
 * Grounding badge — STRICT priority order (spec §2.2, the §2.2/§6 ambiguity
 * closed by review). First matching rule wins:
 *   1. `trace.resolved_by` set → map directly to a badge.
 *   2. trace empty (`{}` or absent) but a qid is grounded → "grounded" with
 *      no path info — the main case for today's seed data.
 *   3. trace non-empty but `resolved_by` missing → heuristic from qid +
 *      candidate count.
 *   4. nothing at all → "no candidates".
 * Never throws; an unrecognized `resolved_by` value degrades to "none"
 * rather than propagating an unknown state.
 *
 * Rule-3 note: the spec's literal text ("candidates>1 → llm; candidates==1 →
 * det; qid нет и candidates>0 → rej; иначе none") is unreachable as a plain
 * switch on count alone — once >1 and ==1 are excluded, count is always 0,
 * so "qid нет и candidates>0" could never fire. Read as implicitly gated on
 * qid presence (the only reading under which every clause is reachable and
 * each maps to a real real-world grounding state), it becomes: qid present +
 * candidates>1 → llm (disambiguated among several); qid present +
 * candidates==1 → det (single deterministic match); qid absent + candidates>0
 * → rej (candidates existed, none survived); otherwise → none.
 */
export function resolveBadge(term: TermWithTrace): Badge {
  const trace = term.traceJson;
  const resolvedBy = trace?.resolved_by ?? trace?.decision?.resolved_by;

  if (resolvedBy) {
    const model = trace?.model ?? trace?.decision?.model ?? DEFAULT_MODEL_LABEL;
    switch (resolvedBy) {
      case 'exact_label':
      case 'label_match':
        return { tone: 'det', label: '◆ label match' };
      case 'llm_disambiguation':
        return { tone: 'llm', label: `◇ LLM · ${model}` };
      case 'llm_rejected':
        return { tone: 'rej', label: '◇ LLM rejected all' };
      case 'no_candidates':
        return { tone: 'none', label: '○ no candidates' };
      default:
        // Defensive: unrecognized value from a future backend — degrade quietly.
        return { tone: 'none', label: '○ no candidates' };
    }
  }

  if (isEmptyTrace(trace)) {
    if (term.grounded?.qid) {
      return { tone: 'det', label: '◆ grounded' };
    }
    return { tone: 'none', label: '○ no candidates' };
  }

  const hasQid = Boolean(term.grounded?.qid);
  const candidateCount = term.candidates.length;
  const model = trace?.model ?? DEFAULT_MODEL_LABEL;
  if (hasQid && candidateCount > 1) {
    return { tone: 'llm', label: `◇ LLM · ${model}` };
  }
  if (hasQid && candidateCount === 1) {
    return { tone: 'det', label: '◆ label match' };
  }
  if (!hasQid && candidateCount > 0) {
    return { tone: 'rej', label: '◇ LLM rejected all' };
  }
  return { tone: 'none', label: '○ no candidates' };
}

// ─── Grouping (§2.1) ─────────────────────────────────────────────────────────

export interface GlossaryGroup {
  key: string;
  lemma: string;
  qid: string | null;
  category: string | null;
  sourceSurface: string;
  translation: string | null;
  grounded: WikidataRef | null;
  difficulty: Verdict;
  pair: Verdict | null;
  /** All per-occurrence rows in the group, sorted by first appearance. */
  mentions: TermWithTrace[];
  /** mentions[0] — the row the detail panel builds context/path/candidates from. */
  primary: TermWithTrace;
}

export interface GlossarySummary {
  groups: number;
  mentions: number;
  deterministic: number;
  llm: number;
  notGrounded: number;
}

const SEVERITY_RANK: Record<Verdict, number> = { green: 0, yellow: 1, red: 2 };

function worseVerdict(a: Verdict, b: Verdict): Verdict {
  return SEVERITY_RANK[b] > SEVERITY_RANK[a] ? b : a;
}

/** `term.note` categories ("place" etc.) → Title Case pill text, or null for
 *  an empty note (no pill rendered). */
export function titleCase(raw: string): string | null {
  const trimmed = raw.trim();
  if (!trimmed) return null;
  return trimmed
    .split(/\s+/)
    .map((w) => w[0].toUpperCase() + w.slice(1))
    .join(' ');
}

function paragraphIdxOf(term: Term, idxById: Map<number, number>): number {
  return idxById.get(term.paragraphId) ?? Number.POSITIVE_INFINITY;
}

function byAppearance(idxById: Map<number, number>) {
  return (a: Term, b: Term): number => {
    const ai = paragraphIdxOf(a, idxById);
    const bi = paragraphIdxOf(b, idxById);
    return ai !== bi ? ai - bi : a.charStart - b.charStart;
  };
}

/**
 * Groups per-occurrence `term` rows into per-entity glossary rows (spec §2.1).
 * Key = (lemma, qid || 'ungrounded:' + lemma) so distinct entities that share
 * a lemma stay separate, while inflected surface forms of the same lemma
 * merge — fixes the "Тигр"/"Тигра" duplicate rows the flat table showed.
 */
export function groupTerms(terms: TermWithTrace[], paragraphs: Paragraph[]): GlossaryGroup[] {
  const idxById = new Map(paragraphs.map((p) => [p.id, p.idx]));
  const compareByAppearance = byAppearance(idxById);

  const byKey = new Map<string, TermWithTrace[]>();
  for (const term of terms) {
    const lemma = (term.sourceLemma || term.sourceSurface).toLowerCase();
    const qid = term.grounded?.qid ?? null;
    const key = `${lemma}::${qid ?? `ungrounded:${lemma}`}`;
    const bucket = byKey.get(key);
    if (bucket) bucket.push(term);
    else byKey.set(key, [term]);
  }

  const groups: GlossaryGroup[] = [];
  for (const [key, bucket] of byKey) {
    const mentions = [...bucket].sort(compareByAppearance);
    const primary = mentions[0];

    let difficulty: Verdict = primary.difficulty;
    let pair: Verdict | null = null;
    for (const m of mentions) {
      difficulty = worseVerdict(difficulty, m.difficulty);
      if (m.pairAccuracy) pair = pair ? worseVerdict(pair, m.pairAccuracy) : m.pairAccuracy;
    }

    // Translation = recommended||targetSurface of the first mention that has
    // a target mapping at all; siblings with no target of their own inherit
    // it. Only truly all-absent groups fall back to '—' (spec §2.1).
    const linked = mentions.find((m) => m.targetSurface);
    const translation = linked ? linked.recommended ?? linked.targetSurface : null;

    const grounded = mentions.find((m) => m.grounded)?.grounded ?? null;

    groups.push({
      key,
      lemma: (primary.sourceLemma || primary.sourceSurface).toLowerCase(),
      qid: primary.grounded?.qid ?? null,
      category: titleCase(primary.note),
      sourceSurface: primary.sourceSurface,
      translation,
      grounded,
      difficulty,
      pair,
      mentions,
      primary,
    });
  }

  groups.sort((a, b) => compareByAppearance(a.mentions[0], b.mentions[0]));
  return groups;
}

/** Summary-line counters (spec §2.1): "resolved deterministically / via LLM /
 *  not grounded" — the latter folds both `rej` and `none` badge tones since
 *  the summary line has no separate "rejected" bucket. */
export function summarizeGroups(groups: GlossaryGroup[]): GlossarySummary {
  let mentions = 0;
  let deterministic = 0;
  let llm = 0;
  let notGrounded = 0;
  for (const g of groups) {
    mentions += g.mentions.length;
    const { tone } = resolveBadge(g.primary);
    if (tone === 'det') deterministic++;
    else if (tone === 'llm') llm++;
    else notGrounded++;
  }
  return { groups: groups.length, mentions, deterministic, llm, notGrounded };
}

// ─── Context highlighting (§2.3) ────────────────────────────────────────────

export interface MatchSpan {
  before: string;
  match: string;
  after: string;
}

/** Splits `text` around the first case-insensitive occurrence of `needle`.
 *  Plain substring search — spec §2.3 explicitly calls for marking the
 *  occurrence "without regex injection" from arbitrary surface/target text.
 *  Returns null when `needle` isn't found (or is empty). */
export function findMatchSpan(text: string, needle: string): MatchSpan | null {
  if (!needle) return null;
  const idx = text.toLowerCase().indexOf(needle.toLowerCase());
  if (idx === -1) return null;
  return {
    before: text.slice(0, idx),
    match: text.slice(idx, idx + needle.length),
    after: text.slice(idx + needle.length),
  };
}

/** Best-effort sentence extraction around `needle` in `text`, for the EN
 *  context row (spec §2.3: "предложение из paragraph.target вокруг
 *  target_surface"). Returns null when `needle` isn't found — the panel then
 *  omits the EN row entirely. */
export function findSentenceContaining(text: string, needle: string): string | null {
  if (!needle) return null;
  const lower = text.toLowerCase();
  const matchIdx = lower.indexOf(needle.toLowerCase());
  if (matchIdx === -1) return null;

  const boundaries: number[] = [];
  const re = /[.!?]\s+/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text)) !== null) {
    boundaries.push(m.index + m[0].length);
  }

  let start = 0;
  let end = text.length;
  for (const b of boundaries) {
    if (b <= matchIdx) start = b;
    else {
      end = b;
      break;
    }
  }
  return text.slice(start, end).trim();
}
