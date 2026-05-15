import type { CSSProperties } from 'react';
import type { LocationStressHistory } from '@/types/dashboard';
import { Eyebrow } from '@/components/editorial';
import { STATUS_HEX, statusLabel } from './shared';

function trendArrow(trend: LocationStressHistory['trend']): { glyph: string; color: string } {
  if (trend === 'improving') return { glyph: '↗', color: 'var(--color-signal-open)' };
  if (trend === 'worsening') return { glyph: '↘', color: 'var(--color-signal-hedge)' };
  return { glyph: '→', color: 'var(--ink-light)' };
}

function StressBars({ history }: { history: string[] }) {
  return (
    <span className="inline-flex items-end gap-0.75">
      {history.map((s, i) => {
        const isStress = s === 'stress';
        const isDegraded = s === 'degraded';
        const h = isStress ? 14 : isDegraded ? 9 : 5;
        return (
          <span
            key={i}
            title={statusLabel(s)}
            style={{
              display: 'inline-block',
              width: 4,
              height: h,
              background: STATUS_HEX[s] ?? 'var(--rule)',
              opacity: 0.92,
            }}
          />
        );
      })}
    </span>
  );
}

function thStyle(align: 'left' | 'right'): CSSProperties {
  return {
    fontFamily: 'var(--font-mono)',
    fontSize: 9,
    fontWeight: 600,
    letterSpacing: '0.2em',
    textTransform: 'uppercase',
    color: 'var(--ink-light)',
    padding: align === 'left' ? '0 12px 10px 0' : '0 0 10px 12px',
    textAlign: align,
  };
}

export default function StressHistoryBlock({ history }: { history: LocationStressHistory[] }) {
  const ordered = [...history].sort((a, b) => {
    if (a.country !== b.country) return a.country.localeCompare(b.country);
    return a.location_name.localeCompare(b.location_name);
  });

  return (
    <div style={{ marginBottom: 40 }}>
      <div
        className="flex items-baseline justify-between mb-4 pb-2.5"
        style={{ borderBottom: '1px solid var(--ink)' }}
      >
        <Eyebrow as="h3" tone="primary" size={11} tracking="0.22em" style={{ fontWeight: 700 }}>
          Stress hydrique — 7 jours
        </Eyebrow>
        <Eyebrow tone="subtle" size={9} tracking="0.18em">
          Évolution récente
        </Eyebrow>
      </div>

      <div className="overflow-x-auto">
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ borderBottom: '2px solid var(--ink)' }}>
              <th style={thStyle('left')}>Origin</th>
              <th style={thStyle('left')}>Pays</th>
              <th style={thStyle('left')}>Tendance 7j</th>
              <th style={thStyle('left')}>Streak</th>
              <th style={thStyle('left')}>Trend</th>
              <th style={thStyle('right')}>Statut</th>
            </tr>
          </thead>
          <tbody>
            {ordered.map((z) => {
              const isStress = z.current_status === 'stress';
              const isDegraded = z.current_status === 'degraded';
              const tone =
                isStress
                  ? STATUS_HEX.stress
                  : isDegraded
                    ? STATUS_HEX.degraded
                    : 'var(--ink-light)';
              const trend = trendArrow(z.trend);
              return (
                <tr key={z.location_name} style={{ borderBottom: '1px dotted var(--rule)' }}>
                  <td
                    style={{
                      padding: '12px 12px 12px 0',
                      fontFamily: 'var(--font-editorial)',
                      fontSize: 14,
                      color: 'var(--ink)',
                      fontWeight: isStress ? 700 : 600,
                    }}
                  >
                    {z.location_name}
                  </td>
                  <td
                    style={{
                      padding: '12px',
                      fontFamily: 'var(--font-sans)',
                      fontSize: 12,
                      color: 'var(--ink-mid)',
                    }}
                  >
                    {z.country === 'CIV' ? "Côte d'Ivoire" : 'Ghana'}
                  </td>
                  <td style={{ padding: '12px' }}>
                    <StressBars history={z.history} />
                  </td>
                  <td
                    className="tabular-nums"
                    style={{
                      padding: '12px',
                      fontFamily: 'var(--font-mono)',
                      fontSize: 12,
                      color: 'var(--ink-dark)',
                    }}
                  >
                    {z.streak_days > 1 ? `${z.streak_days}j` : '—'}
                  </td>
                  <td
                    style={{
                      padding: '12px',
                      fontFamily: 'var(--font-mono)',
                      fontSize: 14,
                      color: trend.color,
                      fontWeight: 600,
                    }}
                    title={z.trend}
                  >
                    {trend.glyph}
                  </td>
                  <td style={{ padding: '12px 0 12px 12px', textAlign: 'right' }}>
                    <Eyebrow
                      size={9}
                      tracking="0.18em"
                      style={{
                        display: 'inline-block',
                        color: tone,
                        background:
                          isStress
                            ? 'rgba(239,68,68,0.08)'
                            : isDegraded
                              ? 'rgba(245,158,11,0.10)'
                              : 'rgba(153,153,153,0.08)',
                        padding: '3px 9px',
                      }}
                    >
                      {statusLabel(z.current_status)}
                    </Eyebrow>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
