import { Loader2 } from 'lucide-react';
import { useWeather } from '@/hooks/useDashboard';
import type {
  LocationDiagnostic,
  LocationStressHistory,
  SeasonStatus,
} from '@/types/dashboard';
import SectionHeader from '@/components/section-header';

interface WeatherUpdateCardProps {
  targetDate?: string;
  className?: string;
}

function SubHeader({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="flex items-baseline justify-between mb-3">
      <h3
        className="uppercase"
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 11,
          fontWeight: 600,
          letterSpacing: '0.18em',
          color: 'var(--ink)',
        }}
      >
        {title}
      </h3>
      {hint && (
        <span
          className="uppercase"
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 9,
            letterSpacing: '0.15em',
            color: 'var(--ink-light)',
          }}
        >
          {hint}
        </span>
      )}
    </div>
  );
}

const STATUS_HEX: Record<string, string> = {
  normal: '#10B981',
  degraded: '#F59E0B',
  stress: '#EF4444',
};

function statusLabel(status?: string): string {
  if (status === 'normal') return 'Normal';
  if (status === 'degraded') return 'Dégradé';
  if (status === 'stress') return 'Stress';
  return '—';
}

function healthColor(score: number | null | undefined): string {
  if (score == null) return 'var(--ink-light)';
  if (score >= 3.5) return 'var(--color-signal-open)';
  if (score >= 2.5) return 'var(--color-signal-monitor)';
  return 'var(--color-signal-hedge)';
}

// ---------------------------------------------------------------------------
// Campaign health + seasons
// ---------------------------------------------------------------------------

function statusBadge(status: SeasonStatus['status']): { label: string; color: string } {
  if (status === 'completed') return { label: 'Clôturée', color: 'var(--ink-light)' };
  if (status === 'in_progress') return { label: 'En cours', color: 'var(--ink)' };
  return { label: 'À venir', color: 'var(--ink-light)' };
}

function CampaignBlock({
  campaign,
  campaignHealth,
  seasons,
}: {
  campaign: string;
  campaignHealth: number | null | undefined;
  seasons: SeasonStatus[];
}) {
  return (
    <div style={{ marginBottom: 40 }}>
      {/* Header: campaign title (left) + santé globale (right) */}
      <div
        className="flex items-end justify-between gap-6 mb-6 pb-3"
        style={{ borderBottom: '1px solid var(--ink)' }}
      >
        <div>
          <div
            className="uppercase"
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 10,
              fontWeight: 600,
              letterSpacing: '0.2em',
              color: 'var(--ink-mid)',
              marginBottom: 4,
            }}
          >
            Campagne {campaign}
          </div>
          <div
            style={{
              fontFamily: 'var(--font-display)',
              fontStyle: 'italic',
              fontWeight: 400,
              fontSize: 22,
              color: 'var(--ink)',
              lineHeight: 1.1,
            }}
          >
            Bilan saisonnier cumulé
          </div>
        </div>
        <div className="text-right">
          <div
            className="uppercase"
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 9,
              letterSpacing: '0.22em',
              color: 'var(--ink-light)',
              marginBottom: 2,
            }}
          >
            Santé globale
          </div>
          <div
            className="tabular-nums"
            style={{
              fontFamily: 'var(--font-display)',
              fontWeight: 700,
              fontSize: 44,
              lineHeight: 1,
              color: healthColor(campaignHealth),
            }}
          >
            {campaignHealth != null ? campaignHealth.toFixed(1) : '—'}
            <span
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 14,
                fontWeight: 500,
                color: 'var(--ink-light)',
                marginLeft: 4,
              }}
            >
              /5
            </span>
          </div>
        </div>
      </div>

      {/* Methodology-grid style: one column per saison */}
      {seasons.length > 0 && (
        <div
          className="campaign-grid"
          style={{
            display: 'grid',
            gridTemplateColumns: `repeat(${seasons.length}, minmax(0, 1fr))`,
            gap: 0,
          }}
        >
          {seasons.map((s, i) => {
            const badge = statusBadge(s.status);
            const isLast = i === seasons.length - 1;
            const isActive = s.status === 'in_progress';
            return (
              <div
                key={s.season_name}
                style={{
                  padding: '20px 18px',
                  borderRight: isLast ? 'none' : '1px solid var(--rule)',
                  borderTop: isActive ? `2px solid ${healthColor(s.score)}` : '2px solid transparent',
                  position: 'relative',
                  background: isActive ? 'var(--paper-off)' : 'transparent',
                }}
              >
                <div
                  style={{
                    fontFamily: 'var(--font-display)',
                    fontWeight: 300,
                    fontSize: 36,
                    color: 'var(--rule)',
                    lineHeight: 1,
                    marginBottom: 12,
                  }}
                >
                  {String(i + 1).padStart(2, '0')}
                </div>
                <div
                  className="uppercase"
                  style={{
                    fontFamily: 'var(--font-sans)',
                    fontSize: 10,
                    fontWeight: 700,
                    letterSpacing: '0.15em',
                    color: 'var(--ink)',
                    marginBottom: 4,
                    lineHeight: 1.3,
                  }}
                >
                  {s.label}
                </div>
                <div
                  className="uppercase"
                  style={{
                    fontFamily: 'var(--font-mono)',
                    fontSize: 9,
                    letterSpacing: '0.18em',
                    color: 'var(--ink-light)',
                    marginBottom: 12,
                  }}
                >
                  {s.months_covered}
                </div>
                <div
                  className="tabular-nums"
                  style={{
                    fontFamily: 'var(--font-display)',
                    fontWeight: 700,
                    fontSize: 28,
                    lineHeight: 1,
                    color: s.score != null ? healthColor(s.score) : 'var(--ink-light)',
                    marginBottom: 2,
                  }}
                >
                  {s.score != null ? s.score.toFixed(1) : '—'}
                </div>
                <div
                  style={{
                    fontFamily: 'var(--font-mono)',
                    fontSize: 10,
                    color: 'var(--ink-light)',
                    marginBottom: 10,
                  }}
                >
                  / 5
                </div>
                <div
                  className="uppercase"
                  style={{
                    fontFamily: 'var(--font-mono)',
                    fontSize: 9,
                    fontWeight: 600,
                    letterSpacing: '0.18em',
                    color: badge.color,
                  }}
                >
                  {badge.label}
                </div>
              </div>
            );
          })}
        </div>
      )}

      <style>{`
        @media (max-width: 900px) {
          .campaign-grid { grid-template-columns: repeat(2, minmax(0, 1fr)) !important; }
          .campaign-grid > div { border-right: none !important; border-bottom: 1px solid var(--rule); }
        }
      `}</style>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Stress history mini-timeline per zone (7 days)
// ---------------------------------------------------------------------------

function trendArrow(trend: LocationStressHistory['trend']): { glyph: string; color: string } {
  if (trend === 'improving') return { glyph: '↗', color: 'var(--color-signal-open)' };
  if (trend === 'worsening') return { glyph: '↘', color: 'var(--color-signal-hedge)' };
  return { glyph: '→', color: 'var(--ink-light)' };
}

function StressBars({ history }: { history: string[] }) {
  return (
    <span className="inline-flex items-end gap-[3px]">
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

function StressHistoryBlock({ history }: { history: LocationStressHistory[] }) {
  const ordered = [...history].sort((a, b) => {
    if (a.country !== b.country) return a.country.localeCompare(b.country);
    return a.location_name.localeCompare(b.location_name);
  });

  return (
    <div style={{ marginBottom: 40 }}>
      {/* Section header matches the editorial weather-table style */}
      <div
        className="flex items-baseline justify-between mb-4 pb-2.5"
        style={{ borderBottom: '1px solid var(--ink)' }}
      >
        <h3
          className="uppercase"
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 11,
            fontWeight: 700,
            letterSpacing: '0.22em',
            color: 'var(--ink)',
          }}
        >
          Stress hydrique — 7 jours
        </h3>
        <span
          className="uppercase"
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 9,
            letterSpacing: '0.18em',
            color: 'var(--ink-light)',
          }}
        >
          Évolution récente
        </span>
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
                  <td
                    style={{
                      padding: '12px 0 12px 12px',
                      textAlign: 'right',
                    }}
                  >
                    <span
                      className="inline-block uppercase"
                      style={{
                        fontFamily: 'var(--font-mono)',
                        fontSize: 9,
                        fontWeight: 600,
                        letterSpacing: '0.18em',
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
                    </span>
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

function thStyle(align: 'left' | 'right'): React.CSSProperties {
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

// ---------------------------------------------------------------------------
// Harmattan summary
// ---------------------------------------------------------------------------

function HarmattanBlock({
  harmattan,
  diagnostics,
}: {
  harmattan?: { days: number; threshold: number; risk: boolean; in_season: boolean } | null;
  diagnostics: LocationDiagnostic[];
}) {
  const affected = diagnostics.filter((d) => d.harmattan_days != null && d.harmattan_days > 0);
  if (!harmattan?.in_season && affected.length === 0) return null;

  const color = harmattan?.risk ? 'var(--color-signal-hedge)' : 'var(--ink)';

  return (
    <div style={{ marginBottom: 24 }}>
      <SubHeader title="Harmattan" hint={`Seuil critique ${harmattan?.threshold ?? 24}j`} />
      <div className="flex items-center gap-3 mb-2">
        <span
          className="uppercase"
          style={{
            padding: '4px 10px',
            border: `1px solid ${color}`,
            color,
            fontWeight: 600,
            fontFamily: 'var(--font-mono)',
            fontSize: 10,
            letterSpacing: '0.18em',
          }}
        >
          {harmattan?.risk ? '— Risk' : '— Active'}
        </span>
        {harmattan && (
          <span
            className="tabular-nums"
            style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--ink-mid)' }}
          >
            {harmattan.days} jours cumulés
          </span>
        )}
      </div>
      {affected.length > 0 && (
        <p
          style={{
            fontFamily: 'var(--font-editorial)',
            fontStyle: 'italic',
            fontSize: 13,
            color: 'var(--ink-dark)',
            lineHeight: 1.5,
          }}
        >
          Sites affectés :{' '}
          {affected
            .map((d) => `${d.location_name} (${d.harmattan_days}j)`)
            .join(' · ')}
        </p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function WeatherUpdateCard({ targetDate, className }: WeatherUpdateCardProps) {
  const { data, isLoading, error } = useWeather(targetDate);

  if (isLoading) {
    return (
      <section className={className} style={{ padding: '24px 0' }}>
        <SectionHeader numeral="V" title="Weather Intelligence" />
        <div className="flex items-center justify-center py-12" style={{ color: 'var(--ink-light)' }}>
          <Loader2 className="h-5 w-5 animate-spin mr-2" />
          <span className="text-sm">Chargement du rapport météo...</span>
        </div>
      </section>
    );
  }

  if (error || !data) {
    return (
      <section className={className} style={{ padding: '24px 0' }}>
        <SectionHeader numeral="V" title="Weather Intelligence" />
        <p style={{ color: 'var(--ink-light)', textAlign: 'center', fontSize: 14 }}>
          Aucun rapport météo pour cette date.
        </p>
      </section>
    );
  }

  const diagnostics: LocationDiagnostic[] =
    data.daily_diagnostics ?? data.diagnostics ?? [];

  return (
    <section className={className} style={{ padding: '24px 0' }}>
      <SectionHeader numeral="V" title="Weather Intelligence" />

      {/* Campaign health + seasons */}
      {data.campaign && data.seasons && data.seasons.length > 0 && (
        <CampaignBlock
          campaign={data.campaign}
          campaignHealth={data.campaign_health}
          seasons={data.seasons}
        />
      )}

      {/* Stress history per zone */}
      {data.stress_history && data.stress_history.length > 0 && (
        <StressHistoryBlock history={data.stress_history} />
      )}

      {/* Harmattan */}
      <HarmattanBlock harmattan={data.harmattan} diagnostics={diagnostics} />

      {/* Bulletin */}
      {data.description && (
        <div
          style={{
            padding: '16px 18px',
            background: 'var(--paper-off)',
            borderLeft: '3px solid var(--ink)',
          }}
        >
          <div
            className="uppercase mb-2"
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 10,
              fontWeight: 600,
              letterSpacing: '0.2em',
              color: 'var(--ink-mid)',
            }}
          >
            Bulletin du jour
          </div>
          {data.description
            .split(/\n{2,}/)
            .map((s) => s.trim())
            .filter(Boolean)
            .map((p, i) => (
              <p
                key={i}
                style={{
                  fontFamily: 'var(--font-editorial)',
                  fontSize: 14,
                  lineHeight: 1.65,
                  color: 'var(--ink-dark)',
                  marginBottom: 10,
                }}
              >
                {p}
              </p>
            ))}
        </div>
      )}

    </section>
  );
}
