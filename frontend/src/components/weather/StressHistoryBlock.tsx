import type { CSSProperties } from 'react';
import type { LocationStressHistory } from '@/types/dashboard';
import { Eyebrow } from '@/components/editorial';
import { STATUS_HEX, statusLabel } from './shared';

function trendArrow(trend: LocationStressHistory['trend']): { glyph: string; color: string } {
  if (trend === 'improving') return { glyph: '↗', color: 'var(--color-signal-open)' };
  if (trend === 'worsening') return { glyph: '↘', color: 'var(--color-signal-hedge)' };
  return { glyph: '→', color: 'var(--ink-light)' };
}

function StressBars({ history, scale = 1 }: { history: string[]; scale?: number }) {
  return (
    <span className="inline-flex items-end gap-0.75" style={{ height: 18 * scale }}>
      {history.map((s, i) => {
        const isStress = s === 'stress';
        const isDegraded = s === 'degraded';
        const h = (isStress ? 14 : isDegraded ? 9 : 5) * scale;
        return (
          <span
            key={i}
            title={statusLabel(s)}
            style={{
              display: 'inline-block',
              width: 4 * scale,
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

interface Tone {
  color: string;
  bg: string;
}

function toneFor(status: LocationStressHistory['current_status']): Tone {
  if (status === 'stress') return { color: STATUS_HEX.stress, bg: 'rgba(239,68,68,0.08)' };
  if (status === 'degraded') return { color: STATUS_HEX.degraded, bg: 'rgba(245,158,11,0.10)' };
  return { color: 'var(--ink-light)', bg: 'rgba(153,153,153,0.08)' };
}

function StatusPill({ status }: { status: LocationStressHistory['current_status'] }) {
  const t = toneFor(status);
  return (
    <Eyebrow
      size={9}
      tracking="0.18em"
      style={{
        display: 'inline-block',
        color: t.color,
        background: t.bg,
        padding: '3px 9px',
      }}
    >
      {statusLabel(status)}
    </Eyebrow>
  );
}

function StressCard({ zone }: { zone: LocationStressHistory }) {
  const isStress = zone.current_status === 'stress';
  const trend = trendArrow(zone.trend);
  return (
    <li
      style={{
        listStyle: 'none',
        padding: '14px 14px 14px 14px',
        borderTop: '1px dotted var(--rule)',
      }}
    >
      <div className="flex items-start justify-between gap-3 mb-3">
        <div className="min-w-0">
          <div
            style={{
              fontFamily: 'var(--font-editorial)',
              fontStyle: 'italic',
              fontSize: 16,
              fontWeight: isStress ? 700 : 600,
              color: 'var(--ink)',
              lineHeight: 1.2,
            }}
          >
            {zone.location_name}
          </div>
          <div
            style={{
              fontFamily: 'var(--font-sans)',
              fontSize: 11,
              color: 'var(--ink-mid)',
              marginTop: 2,
            }}
          >
            {zone.country === 'CIV' ? "Côte d'Ivoire" : 'Ghana'}
          </div>
        </div>
        <StatusPill status={zone.current_status} />
      </div>
      <div className="mb-2">
        <StressBars history={zone.history} scale={1.3} />
      </div>
      <div
        className="flex items-center gap-3 tabular-nums"
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 11,
          color: 'var(--ink-mid)',
        }}
      >
        <span>
          {zone.streak_days > 1 ? `Streak ${zone.streak_days}j` : 'Streak —'}
        </span>
        <span style={{ color: trend.color, fontSize: 14, fontWeight: 600 }}>{trend.glyph}</span>
      </div>
    </li>
  );
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

      {/* Desktop / tablet: editorial table */}
      <div className="stress-table-wrap">
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
                    <StatusPill status={z.current_status} />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Phone: card list */}
      <ul className="stress-card-list" style={{ margin: 0, padding: 0 }}>
        {ordered.map((z) => (
          <StressCard key={z.location_name} zone={z} />
        ))}
      </ul>

      <style>{`
        .stress-card-list { display: none; }
        @media (max-width: 767px) {
          .stress-table-wrap { display: none; }
          .stress-card-list { display: block; }
        }
      `}</style>
    </div>
  );
}
