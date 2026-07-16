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

/** One candidate as delivered inside `trace_json.candidates`
 *  (`label_first.py`'s `candidates_traced`) — richer than the top-level
 *  `Term.candidates` (`WikidataRef[]`, wire-DTO): it carries a real `matched`
 *  verdict per candidate (label/alias match, or `null` when that candidate
 *  never matched anything). The top-level field has no such provenance, and
 *  for a `judge_rejected` term it can even be `[]` while this array still
 *  holds every candidate that was actually considered and rejected (BUG-6,
 *  frontend-developer-stability-wave1). */
export interface TraceCandidate {
  qid: string;
  label_ru?: string | null;
  label_en?: string | null;
  description?: string;
  matched?: { kind: string; value: string; query: string } | null;
}

/** One entry of `trace_json.queries` (`generate_candidates`'s `queries` list,
 *  `terminology/grounding/candidates.py`) — a single Wikidata search call.
 *  `strategy` names which of the escalating search backends made this call
 *  ("prefix" | "cirrus" | "sitelink" — added alongside the fastapi-developer
 *  lane's grounding-pipeline work); optional because older trace rows were
 *  written before the field existed and callers must degrade gracefully. */
export interface TraceQueryEntry {
  q: string;
  kind: string;
  mechanism: string;
  n_hits: number;
  strategy?: string;
}

// ─── SEARCH-step query grouping (FIX 2, glossary trace polish) ─────────────
// Old traces predating `strategy` (or repeated fallback escalations) render
// several visually identical rows — e.g. three "lemma «Ханейское царство» 0
// hits" rows (prefix→cirrus→sitelink escalation with no strategy label), or
// five alternating lemma/surface rows for «царя Приморья». Collapse rows
// that are true duplicates (same strategy+kind+q+n_hits) into one, tagged
// with a ×N count; distinct strategies/kinds/queries stay their own rows
// since those genuinely differ.

/** One collapsed SEARCH-step row: `count` is 1 for a unique query, >1 when N
 *  identical entries were folded together. */
export interface GroupedSearchQuery {
  strategy?: string;
  kind: string;
  q: string;
  n_hits: number;
  count: number;
}

/** Groups `trace_json.queries` for display, preserving first-seen order. */
export function groupSearchQueries(queries: TraceQueryEntry[]): GroupedSearchQuery[] {
  const order: string[] = [];
  const byKey = new Map<string, GroupedSearchQuery>();
  for (const entry of queries) {
    const key = `${entry.strategy ?? ''}::${entry.kind}::${entry.q}::${entry.n_hits}`;
    const existing = byKey.get(key);
    if (existing) {
      existing.count += 1;
      continue;
    }
    byKey.set(key, { strategy: entry.strategy, kind: entry.kind, q: entry.q, n_hits: entry.n_hits, count: 1 });
    order.push(key);
  }
  return order.map((key) => byKey.get(key)!);
}

/** `trace_json.judge` (label_first.py's `judge_trace`) — present only when a
 *  judge call was actually made (absent for `exact_label`/`no_candidates`/
 *  `wikidata_unavailable`, which never escalate). */
export interface TraceJudge {
  response?: { qid?: string | null; reason?: string } | null;
  error?: string | null;
  latency_ms?: number;
  cache_hit?: boolean;
}

export interface TraceJson {
  resolved_by?: string;
  model?: string;
  judge_reason?: string;
  query?: TraceStep;
  search?: TraceStep;
  label_match?: TraceStep;
  decision?: TraceStep;
  /** Full candidate list with per-item match provenance (see
   *  `TraceCandidate`) — absent on legacy/seed rows shipping `trace_json={}`. */
  candidates?: TraceCandidate[];
  // ─── real flat fields (`label_first.py::_result`) — confirmed against live
  // prod trace_json, docs/reports/debugger-glossary-reddot-trace.md §2c. The
  // fields above this line (`query`/`search`/`label_match`/`decision`/`model`/
  // `judge_reason`) are a nested shape that was written *ahead of* the
  // real backend and never matches live-pipeline output — kept only because
  // `resolveBadge`'s heuristic fallback path and its tests still exercise
  // them; the "Grounding path" panel below reads the real fields instead. ──
  queries?: TraceQueryEntry[];
  search_source?: string;
  /** Subset of `candidates` that exact-matched a query (`match.py::exact_match`),
   *  each annotated with its own `matched` (never `null` here, unlike the
   *  general `TraceCandidate.matched`). */
  exact_matches?: (TraceCandidate & { matched: NonNullable<TraceCandidate['matched']> })[];
  judge?: TraceJudge | null;
  chosen_qid?: string | null;
  canon_en?: string[];
  n_api_calls?: number;
  latency_ms?: number;
}

/** `Term` once the backend lane adds `traceJson` to the DTO. A plain `Term`
 *  (no `traceJson` key at all) is still structurally assignable here since
 *  the field is optional — safe to use whether or not the backend field has
 *  landed yet in `api-client.ts`. */
export type TermWithTrace = Term & { traceJson?: TraceJson };

// ─── candidate display shaping ──────────────────────────────────────────────
// Shared by GlossaryTab (Candidates table) and TermPopover ("Ambiguous senses")
// — moved here from GlossaryTab.tsx (frontend-developer-stability-wave2) so a
// second view doesn't have to import display-shaping logic out of another
// React component. Single source of truth for "which candidate list is
// actually true" (BUG-6, frontend-developer-stability-wave1).

/** Normalized shape any "candidates" view renders, whichever backend field it
 *  came from (see `candidatesForDisplay` — BUG-6, frontend-developer-stability-wave1).
 *  `matchKind` is `null` when there is no real match provenance to report —
 *  callers should render an honest "—", never a fabricated "none" (the old
 *  bug: a `matched_via` field the backend never sends). `url` is always a
 *  real or Wikidata-QID-derived link (`terminology/base.py`'s
 *  `f"https://www.wikidata.org/wiki/{qid}"` convention). */
export interface DisplayCandidate {
  qid: string;
  label: string;
  description: string;
  matchKind: string | null;
  url: string;
}

/** `trace_json.candidates` (label_first.py's `candidates_traced`) is the
 *  richer, ground-truth candidate list: same entities as the top-level
 *  `Term.candidates` for most resolutions, but it never drops to `[]` for a
 *  `judge_rejected` term (the top-level field does — see `TraceCandidate`'s
 *  doc comment) and it carries real per-candidate match provenance. Prefer
 *  it; fall back to the plain `WikidataRef` list only for legacy/seed rows
 *  shipping `trace_json={}`, where match provenance honestly isn't known. */
export function candidatesForDisplay(primary: TermWithTrace): DisplayCandidate[] {
  const traced = primary.traceJson?.candidates;
  if (traced && traced.length > 0) return traced.map(fromTraceCandidate);
  return primary.candidates.map(fromWikidataRef);
}

function fromTraceCandidate(c: TraceCandidate): DisplayCandidate {
  return {
    qid: c.qid,
    label: c.label_en || c.label_ru || c.qid,
    description: c.description ?? '',
    matchKind: c.matched ? matchKindLabel(c.matched.kind) : null,
    url: `https://www.wikidata.org/wiki/${c.qid}`,
  };
}

function fromWikidataRef(c: WikidataRef): DisplayCandidate {
  return { qid: c.qid, label: c.label, description: c.description, matchKind: null, url: c.url };
}

/** `matched.kind` is `label_ru` | `alias_ru` | `alias_en` (match.py's
 *  `exact_match`) — collapse the two alias kinds to one short "alias" label,
 *  matching the "matched via" language `viaChipClass` was already styled for. */
function matchKindLabel(kind: string): string {
  return kind.startsWith('alias') ? 'alias' : 'label';
}

export type BadgeTone = 'det' | 'llm' | 'rej' | 'none';

export interface Badge {
  tone: BadgeTone;
  label: string;
}

const DEFAULT_MODEL_LABEL = 'LLM';

function isEmptyTrace(trace: TraceJson | undefined): boolean {
  return !trace || Object.keys(trace).length === 0;
}

/** Yellow (AI-resolved) badge label (#5, owner review: "◇ LLM · LLM" read as
 *  a confusing double). When the per-term model name isn't in the trace,
 *  `model` falls back to `DEFAULT_MODEL_LABEL` ('LLM') — in that case drop
 *  the now-redundant "· LLM" suffix entirely instead of doubling the word.
 *  When a real model name IS known, show it, with "AI" (not "LLM") as the
 *  leading word so a known model never reads "LLM · LLM" again either. */
function llmBadgeLabel(model: string): string {
  return model === DEFAULT_MODEL_LABEL ? '◇ resolved by AI' : `◇ AI · ${model}`;
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

  const knownCandidates = term.candidates.length;

  if (resolvedBy) {
    const model = trace?.model ?? trace?.decision?.model ?? DEFAULT_MODEL_LABEL;
    switch (resolvedBy) {
      case 'exact_label':
      case 'label_match':
        return { tone: 'det', label: '◆ label match' };
      case 'llm_disambiguation':
        return { tone: 'llm', label: llmBadgeLabel(model) };
      case 'llm_rejected':
        return { tone: 'rej', label: '◇ LLM rejected all' };
      // Deterministic enrichment stops here: candidates found but no exact
      // label match and no judge was run — honest "unresolved", NOT "none".
      case 'ambiguous_candidates':
      case 'judge_unavailable':
        return { tone: 'rej', label: `◇ ambiguous · ${knownCandidates || '?'} candidates` };
      case 'no_candidates':
        return { tone: 'none', label: '○ no candidates' };
      default:
        // Defensive: unrecognized value from a future backend — degrade
        // honestly by what the data shows rather than always claiming "none".
        return knownCandidates > 0
          ? { tone: 'rej', label: `◇ ambiguous · ${knownCandidates} candidates` }
          : { tone: 'none', label: '○ no candidates' };
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
    return { tone: 'llm', label: llmBadgeLabel(model) };
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

// ─── Display-level Russian case-ending stemmer (heuristic fallback) ────────
//
// This is NOT lemmatization. It exists purely to patch grouping when the
// upstream terminology module ships an unnormalized `source_lemma` — i.e.
// `source_lemma === source_surface`, meaning the extractor never reduced the
// word to its dictionary form at all (docs/reports/e2e/wave5-run.md §5, e.g.
// `{"sourceSurface": "Тигра", "sourceLemma": "Тигра"}` next to a properly
// grounded `{"sourceSurface": "Тигр", "sourceLemma": "Тигр"}`). Grouping
// strictly by `source_lemma` then leaves inflected forms of the same word as
// separate glossary rows — the exact duplicate-row complaint the redesign
// was meant to fix. Strips at most one trailing case ending, longest-first,
// from words over 4 chars, keeping a stem of >=3 chars. The real fix belongs
// in the terminology module's lemma extraction upstream — see
// docs/known_issues.md for the limits of this heuristic (it is not a
// morphological analyzer and can both over- and under-stem).
const RU_CASE_ENDINGS = [
  'иями', 'ями', 'ами', 'иях', 'ях', 'ах', 'ием', 'ем', 'ом',
  'ой', 'ей', 'ий', 'ый', 'ая', 'яя', 'ое', 'ее', 'ую', 'юю',
  'ым', 'им', 'ых', 'их',
  'а', 'я', 'о', 'е', 'у', 'ю', 'ы', 'и', 'ь',
];

function stripOneCaseEnding(word: string): string {
  if (word.length <= 4) return word;
  for (const ending of RU_CASE_ENDINGS) {
    const stemLen = word.length - ending.length;
    if (stemLen >= 3 && word.endsWith(ending)) return word.slice(0, stemLen);
  }
  return word;
}

/** One stemming pass per word (multi-word phrases stem word-by-word and
 *  rejoin) — a phrase like "Среднем Тигре" stays its own distinct stem
 *  ("средн тигр"), never colliding with the single-word "тигр". */
function stemPhrase(phrase: string): string {
  return phrase.toLowerCase().split(/\s+/).map(stripOneCaseEnding).join(' ');
}

/** Grouping-key component for one term: the normalized lemma lowercased when
 *  the upstream extractor produced one, or the heuristic stem when it didn't
 *  (`sourceLemma === sourceSurface`, i.e. lemma not normalized at all). Also
 *  reports whether the heuristic path was actually used — the cross-bucket
 *  merge below only ever applies to buckets that needed it. */
function groupingStem(term: Term): { stem: string; isRaw: boolean } {
  const lemma = term.sourceLemma || term.sourceSurface;
  const isRaw = term.sourceLemma === term.sourceSurface;
  return { stem: isRaw ? stemPhrase(lemma) : lemma.toLowerCase(), isRaw };
}

/**
 * Groups per-occurrence `term` rows into per-entity glossary rows (spec §2.1).
 * Key = (stem, qid || 'ungrounded:' + stem) so distinct entities that share a
 * stem stay separate, while inflected surface forms of the same word merge —
 * fixes the "Тигр"/"Тигра" duplicate rows the flat table showed.
 *
 * A second, conservative pass then folds an *ungrounded* stem-group into a
 * *grounded* one when their stems agree AND the ungrounded side actually hit
 * the raw/unnormalized-lemma case (e.g. "Тигра" merges into "Тигр"/Q35591) —
 * this is what closes the wave5 §5 gap, since an unnormalized lemma keeps
 * the grounded and ungrounded mentions of the same word in two different
 * per-term keys (one carries a qid, the other doesn't). The raw-only gate
 * matters: an ungrounded candidate whose lemma was already properly
 * normalized and simply failed to ground is a genuine "rejected" case (S2
 * §2.1) and must stay separate from an unrelated grounded entity that
 * happens to share the same lemma — this pass never touches that case. Two
 * grounded groups are never merged into each other, and an ambiguous stem
 * shared by more than one grounded qid is left unmerged — different
 * real-world entities must never collapse into one row.
 */
export function groupTerms(terms: TermWithTrace[], paragraphs: Paragraph[]): GlossaryGroup[] {
  const idxById = new Map(paragraphs.map((p) => [p.id, p.idx]));
  const compareByAppearance = byAppearance(idxById);

  const byKey = new Map<string, TermWithTrace[]>();
  const stemOfKey = new Map<string, string>();
  const rawOfKey = new Map<string, boolean>();
  for (const term of terms) {
    const { stem, isRaw } = groupingStem(term);
    const qid = term.grounded?.qid ?? null;
    const key = `${stem}::${qid ?? `ungrounded:${stem}`}`;
    stemOfKey.set(key, stem);
    rawOfKey.set(key, (rawOfKey.get(key) ?? false) || isRaw);
    const bucket = byKey.get(key);
    if (bucket) bucket.push(term);
    else byKey.set(key, [term]);
  }

  // `qid`: the group's own grounded qid (null for an ungrounded group). When
  // set, `difficulty` folds only mentions that actually grounded to THAT
  // entity — an ungrounded raw-lemma sibling merged in purely for dedup (see
  // the merge pass below) must never paint a grounded group's headline
  // dot red (red-dot-with-QID bug, 3rd recurrence — see
  // docs/reports/debugger-glossary-reddot-trace.md Defect 1). `pair` is
  // exempt from this gate: a red-difficulty mention already has
  // `pairAccuracy=null` by contract (Term dataclass, terminology/base.py),
  // so it can never itself skew `pair` — no separate filtering needed there.
  function buildFields(mentions: TermWithTrace[], qid: string | null) {
    const primary = mentions[0];
    const difficultySource = qid ? mentions.filter((m) => m.grounded?.qid === qid) : mentions;
    let difficulty: Verdict = (difficultySource[0] ?? primary).difficulty;
    for (const m of difficultySource) {
      difficulty = worseVerdict(difficulty, m.difficulty);
    }
    let pair: Verdict | null = null;
    for (const m of mentions) {
      if (m.pairAccuracy) pair = pair ? worseVerdict(pair, m.pairAccuracy) : m.pairAccuracy;
    }
    // Translation = recommended||targetSurface of the first mention that has
    // a target mapping at all; siblings with no target of their own inherit
    // it. Only truly all-absent groups fall back to '—' (spec §2.1).
    const linked = mentions.find((m) => m.targetSurface);
    const translation = linked ? linked.recommended ?? linked.targetSurface : null;
    return { difficulty, pair, translation };
  }

  const drafts: GlossaryGroup[] = [];
  const stemOfDraft = new Map<GlossaryGroup, string>();
  for (const [key, bucket] of byKey) {
    const mentions = [...bucket].sort(compareByAppearance);
    const primary = mentions[0];
    const draftQid = primary.grounded?.qid ?? null;
    const { difficulty, pair, translation } = buildFields(mentions, draftQid);
    const grounded = mentions.find((m) => m.grounded)?.grounded ?? null;

    const draft: GlossaryGroup = {
      key,
      lemma: (primary.sourceLemma || primary.sourceSurface).toLowerCase(),
      qid: draftQid,
      category: titleCase(primary.note),
      sourceSurface: primary.sourceSurface,
      translation,
      grounded,
      difficulty,
      pair,
      mentions,
      primary,
    };
    stemOfDraft.set(draft, stemOfKey.get(key)!);
    drafts.push(draft);
  }

  // Index grounded drafts by stem; only a *single* grounded candidate per
  // stem is eligible as a merge target (an ambiguous stem shared by two
  // different qids must never guess which one an ungrounded mention meant).
  const groundedByStem = new Map<string, GlossaryGroup[]>();
  for (const d of drafts) {
    if (!d.qid) continue;
    const stem = stemOfDraft.get(d)!;
    const list = groundedByStem.get(stem);
    if (list) list.push(d); else groundedByStem.set(stem, [d]);
  }

  const groups: GlossaryGroup[] = [];
  for (const d of drafts) {
    if (d.qid) { groups.push(d); continue; }
    const candidates = rawOfKey.get(d.key) ? groundedByStem.get(stemOfDraft.get(d)!) : undefined;
    if (candidates && candidates.length === 1) {
      const target = candidates[0];
      const allMentions = [...target.mentions, ...d.mentions].sort(compareByAppearance);
      const { difficulty, pair, translation } = buildFields(allMentions, target.qid);
      target.mentions = allMentions;
      target.difficulty = difficulty;
      target.pair = pair;
      target.translation = translation;
      continue; // folded into `target` — drop this standalone ungrounded row
    }
    groups.push(d);
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
