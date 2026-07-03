import { useState } from 'react';
import type { Paragraph, Criterion } from '../api-client';
import { scoreBand } from '../store';

interface Props {
  paragraphs: Paragraph[];
  criteria: Criterion[];
  onSelectParagraph?: (idx: number) => void;
}

type SortKey = 'idx' | 'aggregate' | 'issues' | string;

export default function RankingTab({ paragraphs, criteria, onSelectParagraph }: Props) {
  const [sortKey, setSortKey] = useState<SortKey>('idx');
  const [sortAsc, setSortAsc] = useState(true);

  function handleSort(key: SortKey) {
    if (sortKey === key) {
      setSortAsc((v) => !v);
    } else {
      setSortKey(key);
      setSortAsc(true);
    }
  }

  function getValue(para: Paragraph, key: SortKey): number {
    if (key === 'idx') return para.idx;
    if (key === 'aggregate') return para.aggregate ?? 0;
    if (key === 'issues') return para.issues.filter((i) => i.status === 'open').length;
    // criterionId key
    return para.scores.find((s) => s.criterionId === key)?.value ?? 0;
  }

  const sorted = [...paragraphs].sort((a, b) => {
    const av = getValue(a, sortKey);
    const bv = getValue(b, sortKey);
    return sortAsc ? av - bv : bv - av;
  });

  function SortTh({ label, colKey }: { label: string; colKey: SortKey }) {
    const active = sortKey === colKey;
    return (
      <th className="va-sortable-th" onClick={() => handleSort(colKey)}>
        {label}
        {active && <span className="va-sort-arrow">{sortAsc ? ' ↑' : ' ↓'}</span>}
      </th>
    );
  }

  const enabledCriteria = criteria.filter((c) => c.enabled);

  return (
    <div className="va-tab-content">
      <div className="va-section-title">
        Paragraph Ranking
        {onSelectParagraph && (
          <span style={{ fontSize: 11, fontWeight: 400, color: 'var(--va-text-muted)', marginLeft: 12 }}>
            Click a row to jump to Document tab
          </span>
        )}
      </div>
      <table className="va-table">
        <thead>
          <tr>
            <SortTh label="#" colKey="idx" />
            <th>Source snippet</th>
            <th>Translation snippet</th>
            {enabledCriteria.map((c) => (
              <SortTh key={c.id} label={c.name} colKey={c.id} />
            ))}
            <SortTh label="Aggregate" colKey="aggregate" />
            <SortTh label="Issues" colKey="issues" />
          </tr>
        </thead>
        <tbody>
          {sorted.map((para) => {
            const agg = para.aggregate;
            const band = agg !== null ? scoreBand(agg) : 'yellow';
            const issueCount = para.issues.filter((i) => i.status === 'open').length;
            return (
              <tr
                key={para.id}
                className={onSelectParagraph ? 'va-ranking-row-clickable' : ''}
                onClick={() => onSelectParagraph?.(para.idx)}
                title={onSelectParagraph ? 'Click to view in Document tab' : undefined}
              >
                <td style={{ color: 'var(--va-text-muted)', fontSize: 12 }}>§{para.idx + 1}</td>
                <td>
                  <div className="va-snippet" title={para.source}>{para.source.slice(0, 60)}</div>
                </td>
                <td>
                  <div className="va-snippet" title={para.target}>{para.target.slice(0, 60)}</div>
                </td>
                {enabledCriteria.map((c) => {
                  const sc = para.scores.find((s) => s.criterionId === c.id);
                  return (
                    <td key={c.id} style={{ color: c.color, fontWeight: 600, fontSize: 13 }}>
                      {sc ? sc.value.toFixed(1) : '—'}
                    </td>
                  );
                })}
                <td>
                  <span
                    className={`va-agg-badge ${band}`}
                    style={{ fontWeight: 600, fontSize: 13 }}
                  >
                    {agg !== null ? agg.toFixed(1) : '—'}
                  </span>
                </td>
                <td style={{ color: issueCount > 0 ? 'var(--va-red)' : 'var(--va-text-muted)', fontSize: 13 }}>
                  {issueCount}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
