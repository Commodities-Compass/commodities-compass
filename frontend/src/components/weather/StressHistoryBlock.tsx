import type { CSSProperties } from 'react';
import { useTranslation } from 'react-i18next';
import type { TFunction } from 'i18next';
import type { LocationStressHistory } from '@/types/dashboard';
import { Eyebrow } from '@/components/editorial';
import { STATUS_HEX, statusLabel } from './shared';

function trendArrow(trend: LocationStressHistory['trend']): { glyph: string; color: string } {
  if (trend === 'improving') return { glyph: '↗', color: 'var(--color-signal-open)' };
  if (trend === 'worsening') return { glyph: '↘', color: 'var(--color-signal-hedge)' };
  return { glyph: '→', color: 'var(--ink-light)' };
}

function countryLabel(country: LocationStressHistory['country'], t: TFunction): string {
  return country === 'CIV' ? t('weather.country_civ') : t('weather.country_ghana');
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

function StressCard({
  zone,
  harmattanDays,
  t,
}: {
  zone: LocationStressHistory;
  harmattanDays?: number | null;
  t: TFunction;
}) {
  const isStress = zone.current_status === 'stress';
  const trend = trendArrow(zone.trend);
  const harmattan = formatHarmattan(harmattanDays);
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
            {countryLabel(zone.country, t)}
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
          {zone.streak_days > 1
            ? t('weather.streak_days', { days: zone.streak_days })
            : t('weather.streak_none')}
        </span>
        <span style={{ color: trend.color, fontSize: 14, fontWeight: 600 }}>{trend.glyph}</span>
        <span style={{ color: harmattan.color }}>
          {t('weather.harmattan_label', { value: harmattan.label })}
        </span>
      </div>
    </li>
  );
}

interface StressHistoryBlockProps {
  history: LocationStressHistory[];
  harmattanByLocation?: Record<string, number | null | undefined>;
}

function formatHarmattan(days: number | null | undefined): {
  label: string;
  color: string;
} {
  if (days == null) return { label: '—', color: 'var(--ink-light)' };
  if (days === 0) return { label: '0j', color: 'var(--ink-light)' };
  return { label: `${days}j`, color: 'var(--ink-dark)' };
}

export default function StressHistoryBlock({
  history,
  harmattanByLocation = {},
}: StressHistoryBlockProps) {
  const { t } = useTranslation();
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
          {t('weather.stress_title')}
        </Eyebrow>
        <Eyebrow tone="subtle" size={9} tracking="0.18em">
          {t('weather.recent_evolution')}
        </Eyebrow>
      </div>

      {/* Desktop / tablet: editorial table */}
      <div className="stress-table-wrap">
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ borderBottom: '2px solid var(--ink)' }}>
              <th style={thStyle('left')}>{t('weather.col_origin')}</th>
              <th style={thStyle('left')}>{t('weather.col_country')}</th>
              <th style={thStyle('left')}>{t('weather.col_trend_7d')}</th>
              <th style={thStyle('left')}>{t('weather.col_streak')}</th>
              <th style={thStyle('left')}>{t('weather.col_trend')}</th>
              <th style={thStyle('left')}>{t('weather.col_harmattan')}</th>
              <th style={thStyle('right')}>{t('weather.col_status')}</th>
            </tr>
          </thead>
          <tbody>
            {ordered.map((z) => {
              const isStress = z.current_status === 'stress';
              const trend = trendArrow(z.trend);
              const harmattan = formatHarmattan(harmattanByLocation[z.location_name]);
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
                    {countryLabel(z.country, t)}
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
                  <td
                    className="tabular-nums"
                    style={{
                      padding: '12px',
                      fontFamily: 'var(--font-mono)',
                      fontSize: 12,
                      color: harmattan.color,
                    }}
                  >
                    {harmattan.label}
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
          <StressCard
            key={z.location_name}
            zone={z}
            harmattanDays={harmattanByLocation[z.location_name]}
            t={t}
          />
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
