import { useMemo, useState, type ReactNode } from 'react';
import { langLabel } from '../lang';
import type { Paragraph, WikidataRef } from '../api-client';
import {
  findMatchSpan,
  findSentenceContaining,
  groupTerms,
  resolveBadge,
  summarizeGroups,
  type BadgeTone,
  type GlossaryGroup,
  type TermWithTrace,
  type TraceStep,
} from './glossary-grouping';

interface Props {
  terms: TermWithTrace[];
  paragraphs: Paragraph[];
  sourceLang: string;
  targetLang: string;
  /** Optional: jump to the Document tab at a mention's paragraph (wired by the
   *  parent — VariantA's handleRankingRowClick pattern, spec S2 §2.3). */
  onMentionClick?: (paragraphIdx: number) => void;
}

/** A candidate as delivered by `candidates_json` (spec S2 §2.3) — the wire
 *  `WikidataRef` type has no `matched_via` field, so it's a local, optional
 *  extension rather than a change to the shared DTO type. */
type CandidateWithMatch = WikidataRef & { matched_via?: string };

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

function viaChipClass(matchedVia: string | undefined): string {
  if (!matchedVia || matchedVia === 'none') return 'va-gl-via no';
  if (matchedVia.toLowerCase().includes('alias')) return 'va-gl-via al';
  return 'va-gl-via';
}

function pathHeading(tone: BadgeTone): string {
  switch (tone) {
    case 'det':
      return 'Grounding path — resolved deterministically, no LLM call';
    case 'llm':
      return 'Grounding path — ambiguous, resolved by LLM';
    case 'rej':
      return 'Grounding path — candidates found, rejected by LLM';
    default:
      return 'Grounding path — nothing found, no LLM call';
  }
}

interface StepPresentation {
  state: 'done' | 'warn' | 'fail' | 'skip';
  title: string;
  body: ReactNode;
}

function stepPresentation(
  tone: BadgeTone,
  key: 'query' | 'search' | 'label_match' | 'decision',
  step: TraceStep | undefined,
): StepPresentation {
  if (!step) {
    return { state: 'skip', title: 'Skipped', body: 'no trace' };
  }
  const state: 'done' | 'warn' | 'fail' =
    tone === 'det' ? 'done' : tone === 'none' ? 'fail' : key === 'decision' && tone === 'rej' ? 'fail' : 'warn';

  switch (key) {
    case 'query':
      return {
        state,
        title: 'Lemma, then surface',
        body: (
          <>
            lemma <code>{step.lemma ?? '—'}</code>{' '}
            <span className={step.lemma_hits ? 'va-gl-hit' : 'va-gl-miss'}>{step.lemma_hits ?? 0} hits</span>
            <br />
            surface <code>{step.surface ?? '—'}</code>{' '}
            <span className={step.surface_hits ? 'va-gl-hit' : 'va-gl-miss'}>{step.surface_hits ?? 0} hits</span>
          </>
        ),
      };
    case 'search':
      return {
        state,
        title: step.method ?? 'Search',
        body: (
          <>
            {step.method ?? 'search'}{' '}
            <span className={step.hits ? 'va-gl-hit' : 'va-gl-miss'}>{step.hits ?? 0} hits</span>
          </>
        ),
      };
    case 'label_match':
      return {
        state,
        title:
          step.exact_matches === 1 ? 'Exactly 1 exact match' : `${step.exact_matches ?? 0} exact matches`,
        body: (
          <>
            exact matches: <code>{step.exact_matches ?? 0}</code>
          </>
        ),
      };
    case 'decision':
    default:
      return {
        state,
        title: step.resolved_by ? step.resolved_by.replace(/_/g, ' ') : 'Decision',
        body: (
          <>
            <code>resolved_by: {step.resolved_by ?? '—'}</code>
            <br />
            {step.api_calls ?? 0} API calls
            {step.llm_calls ? ` · ${step.llm_calls} LLM call${step.llm_calls > 1 ? 's' : ''}` : ''}
            {step.elapsed_s !== undefined ? ` · ${step.elapsed_s}s` : ''}
          </>
        ),
      };
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

  const candidates = primary.candidates as CandidateWithMatch[];
  const showJudge = badge.tone === 'llm' && trace?.resolved_by === 'llm_disambiguation' && Boolean(trace?.judge_reason);
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
                {(['query', 'search', 'label_match', 'decision'] as const).map((key, i) => {
                  const p = stepPresentation(badge.tone, key, trace?.[key]);
                  return (
                    <div key={key} className={`va-gl-step ${p.state}`}>
                      <div className="va-gl-step-n">
                        {i + 1} · {key.replace('_', ' ').toUpperCase()}
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
                            <td>{c.qid}</td>
                            <td>
                              <b>{c.label}</b> — {c.description}
                            </td>
                            <td>
                              <span className={viaChipClass(c.matched_via)}>{c.matched_via || 'none'}</span>
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
                  <div className="va-gl-judge">
                    <div className="va-gl-judge-m">model: {trace?.model ?? 'LLM'} · Settings › Grounding</div>
                    <div className="va-gl-judge-r">&ldquo;{trace?.judge_reason}&rdquo;</div>
                  </div>
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

export default function GlossaryTab({ terms, paragraphs, sourceLang, targetLang, onMentionClick }: Props) {
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
        <p className="va-empty-note">
          Terminology signals are precomputed offline and available for the seeded pilot document.
        </p>
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
        Grouped by lemma + entity · {summary.groups} terms · {summary.mentions} mentions · resolved deterministically:{' '}
        {summary.deterministic} · via LLM: {summary.llm} · not grounded: {summary.notGrounded}
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
        ◆ label match — deterministic exact-label decision, no LLM · ◇ LLM — judge disambiguated among candidates
        (model shown) · ◇ LLM rejected all — candidates existed, none fit the context · ◇ ambiguous — candidates
        found, no exact match and no judge run · ○ no candidates — search + enabled fallbacks returned nothing.
        <br />
        Row = unique (lemma, entity); Mentions ×N aggregates per-occurrence rows. Click any row to expand context,
        path, candidates and all mentions.
      </div>
    </div>
  );
}
