import { useMemo, useState, type ReactNode } from 'react';
import { langLabel } from '../lang';
import type { Paragraph, TermsStatus } from '../api-client';
import {
  candidatesForDisplay,
  findMatchSpan,
  findSentenceContaining,
  groupSearchQueries,
  groupTerms,
  resolveBadge,
  summarizeGroups,
  type BadgeTone,
  type GlossaryGroup,
  type TermWithTrace,
  type TraceJson,
} from './glossary-grouping';

interface Props {
  terms: TermWithTrace[];
  paragraphs: Paragraph[];
  sourceLang: string;
  targetLang: string;
  /** Optional: jump to the Document tab at a mention's paragraph (wired by the
   *  parent — VariantA's handleRankingRowClick pattern, spec S2 §2.3). */
  onMentionClick?: (paragraphIdx: number) => void;
  /** Background terminology-extraction status — drives the empty-state copy
   *  (running/failed/none) instead of the old unconditional "precomputed
   *  offline" text. Optional so pre-existing callers/tests don't all need
   *  updating; undefined behaves like 'none'. */
  termsStatus?: TermsStatus;
}

/** Single source of truth for "why is there no terminology to show" prose,
 *  shared by this tab's empty state and the top-chrome Terms chip tooltip
 *  (VariantA.tsx) — both used to duplicate the same "precomputed offline /
 *  seeded pilot document" string, which stopped being true once terminology
 *  became a live, per-document background pipeline. */
export function termsStatusEmptyMessage(status: TermsStatus | undefined): string {
  switch (status) {
    case 'running':
      return 'Terminology pipeline is running — terms appear as paragraphs complete.';
    case 'failed':
      return 'Terminology extraction failed for this document.';
    default:
      return 'No terminology extracted for this document.';
  }
}

// `DisplayCandidate` / `candidatesForDisplay` moved to glossary-grouping.ts
// (frontend-developer-stability-wave2) — TermPopover's "Ambiguous senses"
// block needed the same dead-field fix as this tab's Candidates table (BUG-6),
// so the shaping logic now lives in the shared React-free module instead of
// this component file.

const highlightClass = 't'; // mark.t — EN (target) context highlight, per mockup

function highlighted(text: string, needle: string, markClass?: string): ReactNode {
  const span = findMatchSpan(text, needle);
  if (!span) return text;
  return (
    <>
      {span.before}
      <mark className={markClass}>{span.match}</mark>
      {span.after}
    </>
  );
}

/** `trace_json.queries[].strategy` → short display label (#4, grounding
 *  trace) — names which escalating Wikidata search backend made the call, so
 *  5 query rows read as distinct strategies instead of repeated
 *  "lemma «…»" noise. Unrecognized values pass through as-is (defensive: a
 *  future backend strategy still shows *something* rather than disappearing). */
const SEARCH_STRATEGY_LABEL: Record<string, string> = {
  prefix: 'prefix',
  cirrus: 'full-text',
  sitelink: 'sitelink',
  guess: 'AI guess',
};

function viaChipClass(matchKind: string | null): string {
  if (!matchKind) return 'va-gl-via no';
  if (matchKind === 'alias') return 'va-gl-via al';
  return 'va-gl-via';
}

function pathHeading(tone: BadgeTone): string {
  switch (tone) {
    case 'det':
      return 'Grounding path — unambiguous, no LLM call';
    case 'llm':
      return 'Grounding path — context-resolved by AI';
    case 'rej':
      return 'Grounding path — unresolved, candidates found but rejected by AI';
    default:
      return 'Grounding path — unresolved, nothing found, no LLM call';
  }
}

interface StepPresentation {
  state: 'done' | 'warn' | 'fail' | 'skip';
  title: string;
  body: ReactNode;
}

type StepKey = 'search' | 'candidates' | 'exact' | 'decision';

/** Step-stepper header text (paper §2.1's mechanism naming: SEARCH →
 *  CANDIDATES → EXACT → DISAMBIGUATION, step iii). `key` stays `'decision'`
 *  everywhere else (StepKey/StepPresentation/trace shape) — only the
 *  rendered header text follows the paper's vocabulary. */
const STEP_HEADER_LABEL: Record<StepKey, string> = {
  search: 'SEARCH',
  candidates: 'CANDIDATES',
  exact: 'EXACT',
  decision: 'DISAMBIGUATION',
};

/** Renders the "Grounding path" panel from `trace_json`'s REAL flat shape
 *  (`label_first.py::_result` — `{v, config, queries, search_source,
 *  candidates, exact_matches, resolved_by, judge, chosen_qid, canon_en,
 *  n_api_calls, latency_ms}`, confirmed against live prod
 *  `docs/reports/debugger-glossary-reddot-trace.md` §2c).
 *
 *  This replaces an earlier version that read a nested `query`/`search`/
 *  `label_match`/`decision` shape (`TraceStep`, still kept on `TraceJson` for
 *  `resolveBadge`'s heuristic fallback) which never existed in real backend
 *  output — every step rendered "Skipped — no trace" for every live-pipeline
 *  term. */
function stepPresentation(tone: BadgeTone, key: StepKey, trace: TraceJson | undefined): StepPresentation {
  const state: 'done' | 'warn' | 'fail' =
    tone === 'det' ? 'done' : tone === 'none' ? 'fail' : key === 'decision' && tone === 'rej' ? 'fail' : 'warn';

  switch (key) {
    case 'search': {
      const queries = trace?.queries ?? [];
      if (queries.length === 0) return { state: 'skip', title: 'Skipped', body: 'no trace' };
      // Collapse true duplicate rows (same strategy+kind+q+hits) into one row
      // with a ×N multiplier — old traces predating the `strategy` field (or
      // repeated fallback escalations) otherwise render several visually
      // identical "lemma «…» 0 hits" lines (owner screenshots: 3× for
      // "Ханейское царство", 5× for «царя Приморья»). Distinct strategies stay
      // their own labeled rows since those ARE informative.
      const groupedQueries = groupSearchQueries(queries);
      return {
        state,
        title: trace?.search_source && trace.search_source !== 'none' ? trace.search_source : 'No hits',
        body: (
          <>
            {groupedQueries.map((q, i) => (
              <div key={i}>
                {q.strategy && (
                  <span className="va-gl-strategy">{SEARCH_STRATEGY_LABEL[q.strategy] ?? q.strategy} · </span>
                )}
                {q.kind} <code>{q.q}</code>{' '}
                <span className={q.n_hits ? 'va-gl-hit' : 'va-gl-miss'}>{q.n_hits ?? 0} hits</span>
                {q.count > 1 && <span className="va-gl-qmult"> ×{q.count}</span>}
              </div>
            ))}
          </>
        ),
      };
    }
    case 'candidates': {
      const n = trace?.candidates?.length ?? 0;
      if (n === 0 && !trace?.queries?.length) return { state: 'skip', title: 'Skipped', body: 'no trace' };
      return {
        state,
        title: n === 1 ? '1 candidate found' : `${n} candidates found`,
        body: (
          <>
            <span className={n ? 'va-gl-hit' : 'va-gl-miss'}>{n} candidate{n === 1 ? '' : 's'}</span>
            {trace?.n_api_calls !== undefined && (
              <> · {trace.n_api_calls} Wikidata call{trace.n_api_calls === 1 ? '' : 's'}</>
            )}
          </>
        ),
      };
    }
    case 'exact': {
      const exact = trace?.exact_matches ?? [];
      if (!trace?.queries?.length) return { state: 'skip', title: 'Skipped', body: 'no trace' };
      return {
        state,
        title: exact.length === 1 ? 'Exactly 1 exact match' : `${exact.length} exact matches`,
        body: (
          <>
            exact matches: <code>{exact.length}</code>
            {exact.length > 0 && (
              <>
                {' — '}
                {exact.map((m, i) => (
                  <span key={m.qid}>
                    {m.matched.kind}
                    {i < exact.length - 1 ? ', ' : ''}
                  </span>
                ))}
              </>
            )}
          </>
        ),
      };
    }
    case 'decision':
    default: {
      if (!trace?.resolved_by) return { state: 'skip', title: 'Skipped', body: 'no trace' };
      const judge = trace.judge;
      return {
        state,
        title: trace.resolved_by.replace(/_/g, ' '),
        body: (
          <>
            <code>resolved_by: {trace.resolved_by}</code>
            {trace.chosen_qid && (
              <>
                <br />
                chosen: <code>{trace.chosen_qid}</code>
              </>
            )}
            {judge?.error && (
              // `judge.error` also carries a search-layer message for the rare
              // wikidata_unavailable path (backend reuses the same trace key,
              // label_first.py::ground's except clause) — kept generic rather
              // than "judge error" so it doesn't misattribute a Wikidata
              // outage to the disambiguation judge.
              <>
                <br />
                error: {judge.error}
              </>
            )}
            {trace.latency_ms !== undefined && <> · {(trace.latency_ms / 1000).toFixed(2)}s</>}
          </>
        ),
      };
    }
  }
}

function hasTrace(term: TermWithTrace): boolean {
  return Boolean(term.traceJson && Object.keys(term.traceJson).length > 0);
}

/** Per-paragraph lookup built once from the `paragraphs` prop: display index
 *  (for §N mention labels / Document-tab navigation) and target text (for the
 *  EN context sentence, spec S2 §2.3). */
type ParaInfo = { idx: number; target: string };

interface GroupRowProps {
  group: GlossaryGroup;
  isOpen: boolean;
  onToggle: () => void;
  paraInfoById: Map<number, ParaInfo>;
  onMentionClick?: (paragraphIdx: number) => void;
}

function GroupRow({ group, isOpen, onToggle, paraInfoById, onMentionClick }: GroupRowProps) {
  const badge = resolveBadge(group.primary);

  return (
    <>
      <tr className={`va-gl-row${isOpen ? ' va-gl-open' : ''}`} onClick={onToggle}>
        <td>
          <span className="va-gl-chev">▶</span>
        </td>
        <td>
          <span className={`va-verdict-dot ${group.difficulty}`} title={`Difficulty: ${group.difficulty}`} />
        </td>
        <td>
          {group.pair ? (
            <span className={`va-verdict-dot ${group.pair}`} title={`Pair accuracy: ${group.pair}`} />
          ) : (
            <span className="va-gl-dash" title="No grounding — cannot assess pair">
              —
            </span>
          )}
        </td>
        <td className="va-gl-src">
          {group.sourceSurface}
          {group.category && <span className="va-gl-cat">{group.category}</span>}
        </td>
        <td className="va-gl-tgt">
          {group.translation ?? <span className="va-gl-dash">—</span>}
        </td>
        <td>
          {group.grounded ? (
            <>
              <a
                className="va-gl-wd"
                href={group.grounded.url}
                target="_blank"
                rel="noopener noreferrer"
                title={group.grounded.description}
                onClick={(e) => e.stopPropagation()}
              >
                {group.grounded.label}
              </a>
              <span className="va-gl-qid">{group.grounded.qid}</span>
            </>
          ) : (
            <span className="va-gl-dash">—</span>
          )}
        </td>
        <td>
          <span className={`va-gl-badge ${badge.tone}`}>{badge.label}</span>
        </td>
        <td className="va-gl-mentions">×{group.mentions.length}</td>
      </tr>
      {isOpen && (
        <GroupDetail group={group} badge={badge} paraInfoById={paraInfoById} onMentionClick={onMentionClick} />
      )}
    </>
  );
}

interface GroupDetailProps {
  group: GlossaryGroup;
  badge: { tone: BadgeTone; label: string };
  paraInfoById: Map<number, ParaInfo>;
  onMentionClick?: (paragraphIdx: number) => void;
}

function GroupDetail({ group, badge, paraInfoById, onMentionClick }: GroupDetailProps) {
  const primary = group.primary;
  const traced = hasTrace(primary);
  const trace = primary.traceJson;
  const primaryTarget = paraInfoById.get(primary.paragraphId)?.target ?? '';

  const enSentence = primary.targetSurface ? findSentenceContaining(primaryTarget, primary.targetSurface) : null;

  const candidates = candidatesForDisplay(primary);
  // The judge's reason lives at `trace.judge.response.reason` (real flat
  // shape) — `trace.judge_reason` (the old nested-shape guess) is never
  // populated by the live pipeline, which made this block dead for every
  // real llm_disambiguation term (same root cause as the Matched column and
  // the Grounding-path steps — debugger-glossary-reddot-trace.md §2).
  const judgeReason = trace?.judge?.response?.reason;
  const showJudge = badge.tone === 'llm' && trace?.resolved_by === 'llm_disambiguation' && Boolean(judgeReason);
  const showMentions = group.mentions.length > 1;

  return (
    <tr className="va-gl-detail">
      <td colSpan={8}>
        <div className="va-gl-panel">
          <div className="va-gl-blk">
            <h4>{group.mentions.length > 1 ? `Context — mention 1 of ${group.mentions.length}` : 'Context'}</h4>
            <div className="va-gl-ctx">
              <span className="va-gl-lang">RU</span>
              {highlighted(primary.context, primary.sourceSurface)}
            </div>
            {enSentence && (
              <div className="va-gl-ctx">
                <span className="va-gl-lang">EN</span>
                {highlighted(enSentence, primary.targetSurface ?? '', highlightClass)}
              </div>
            )}
          </div>

          {traced && (
            <div className="va-gl-blk">
              <h4>{pathHeading(badge.tone)}</h4>
              <div className="va-gl-path">
                {(['search', 'candidates', 'exact', 'decision'] as const).map((key, i) => {
                  const p = stepPresentation(badge.tone, key, trace);
                  return (
                    <div key={key} className={`va-gl-step ${p.state}`}>
                      <div className="va-gl-step-n">
                        {i + 1} · {STEP_HEADER_LABEL[key]}
                      </div>
                      <div className="va-gl-step-t">{p.title}</div>
                      <div className="va-gl-step-b">{p.body}</div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {(candidates.length > 0 || showJudge || showMentions) && (
            <div className="va-gl-cols">
              {candidates.length > 0 && (
                <div className="va-gl-blk">
                  <h4>
                    Candidates ({candidates.length}) · {badge.tone === 'det' ? 'matched via' : 'offered to the judge'}
                  </h4>
                  <table className="va-gl-cand">
                    <thead>
                      <tr>
                        <th></th>
                        <th>QID</th>
                        <th>Label · description</th>
                        <th>Matched</th>
                      </tr>
                    </thead>
                    <tbody>
                      {candidates.map((c) => {
                        const chosen = c.qid === group.qid;
                        const consideredByLlm = badge.tone === 'llm' || badge.tone === 'rej';
                        return (
                          <tr key={c.qid} className={chosen ? 'va-gl-chosen' : undefined}>
                            <td>
                              {chosen ? (
                                <span className="va-gl-pick">✓</span>
                              ) : consideredByLlm ? (
                                <span className="va-gl-rejx">✗</span>
                              ) : null}
                            </td>
                            <td>
                              <a
                                className="va-gl-wd"
                                href={c.url}
                                target="_blank"
                                rel="noopener noreferrer"
                              >
                                {c.qid}
                              </a>
                            </td>
                            <td>
                              <b>{c.label}</b>
                              {c.description ? <> — {c.description}</> : null}
                            </td>
                            <td>
                              {c.matchKind ? (
                                <span className={viaChipClass(c.matchKind)}>{c.matchKind}</span>
                              ) : (
                                <span className="va-gl-dash" title="No match provenance recorded for this candidate">—</span>
                              )}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}

              {showJudge && (
                <div className="va-gl-blk">
                  <h4>Judge decision</h4>
                  {/* Owner: drop the "model: … · Settings › Grounding" line and
                      its accent box — keep only the judge's reasoning quote,
                      rendered plain per the design system. */}
                  {/* Paper Figure 1 shows the selection "alongside the model's
                      justification" — plain muted label, no box/accent. */}
                  <div className="va-gl-judge-label">Justification</div>
                  <div className="va-gl-judge-r">&ldquo;{judgeReason}&rdquo;</div>
                </div>
              )}

              {showMentions && (
                <div className="va-gl-blk">
                  <h4>All mentions ({group.mentions.length})</h4>
                  <div className="va-gl-occ">
                    {group.mentions.map((m) => {
                      const mIdx = paraInfoById.get(m.paragraphId)?.idx;
                      return (
                        <div key={m.id}>
                          <span
                            className="va-gl-occ-p"
                            onClick={() => mIdx !== undefined && onMentionClick?.(mIdx)}
                          >
                            §{mIdx !== undefined ? mIdx + 1 : '?'}
                          </span>
                          {highlighted(m.context, m.sourceSurface)}
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </td>
    </tr>
  );
}

export default function GlossaryTab({
  terms,
  paragraphs,
  sourceLang,
  targetLang,
  onMentionClick,
  termsStatus,
}: Props) {
  const [openKeys, setOpenKeys] = useState<Set<string>>(new Set());

  const groups = useMemo(() => groupTerms(terms, paragraphs), [terms, paragraphs]);
  const summary = useMemo(() => summarizeGroups(groups), [groups]);
  const paraInfoById = useMemo(
    () => new Map<number, ParaInfo>(paragraphs.map((p) => [p.id, { idx: p.idx, target: p.target }])),
    [paragraphs],
  );

  if (terms.length === 0) {
    return (
      <div className="va-tab-content">
        <div className="va-section-title">Terminology Glossary</div>
        <p className="va-empty-note">{termsStatusEmptyMessage(termsStatus)}</p>
      </div>
    );
  }

  function toggle(key: string) {
    setOpenKeys((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  return (
    <div className="va-tab-content">
      <div className="va-section-title">Terminology Glossary</div>
      <div className="va-gl-summary">
        Grouped by lemma + entity · {summary.groups} terms · {summary.mentions} mentions · unambiguous:{' '}
        {summary.deterministic} · context-resolved: {summary.llm} · unresolved: {summary.notGrounded}
      </div>
      <table className="va-gl-table">
        <thead>
          <tr>
            <th></th>
            <th title="Difficulty (Wikidata grounding)">Difficulty</th>
            <th title="Pair accuracy (translation quality)">Pair</th>
            <th>Source · {langLabel(sourceLang)}</th>
            <th>Translation · {langLabel(targetLang)}</th>
            <th>Wikidata</th>
            <th>Grounding</th>
            <th>Mentions</th>
          </tr>
        </thead>
        <tbody>
          {groups.map((g) => (
            <GroupRow
              key={g.key}
              group={g}
              isOpen={openKeys.has(g.key)}
              onToggle={() => toggle(g.key)}
              paraInfoById={paraInfoById}
              onMentionClick={onMentionClick}
            />
          ))}
        </tbody>
      </table>
      <div className="va-gl-legend">
        ◆ unambiguous · label match — exact Wikidata label/alias match, no LLM call · ◇ context-resolved · AI — judge
        disambiguated among candidates by paragraph context (model name shown when known) · ◇ unresolved · AI
        abstained — candidates existed, none fit the context · ◇ unresolved · N candidates — candidates found, no
        exact match and no judge run · ○ unresolved · no candidates — search + enabled fallbacks returned nothing.
        <br />
        Row = unique (lemma, entity); Mentions ×N aggregates per-occurrence rows. Click any row to expand context,
        path, candidates and all mentions.
      </div>
    </div>
  );
}
