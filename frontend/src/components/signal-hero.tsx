import { Loader2 } from 'lucide-react';
import { usePositionStatus, useRecommendations } from '@/hooks/useDashboard';

interface SignalHeroProps {
  targetDate?: string;
  className?: string;
}

const SIGNAL_META = {
  OPEN: {
    color: 'var(--color-signal-open)',
    headline: 'Bullish Continuation',
    kicker: 'Buy Signal Active',
    panelTint: 'rgba(16, 185, 129, 0.04)',
  },
  MONITOR: {
    color: 'var(--color-signal-monitor)',
    headline: 'Watch & Wait',
    kicker: 'Neutral Bias',
    panelTint: 'rgba(245, 158, 11, 0.04)',
  },
  HEDGE: {
    color: 'var(--color-signal-hedge)',
    headline: 'Bearish Pressure',
    kicker: 'Protect Positions',
    panelTint: 'rgba(239, 68, 68, 0.04)',
  },
} as const;

function formatSessionDate(iso?: string | null): string {
  if (!iso) return '';
  const date = iso.slice(0, 10);
  const d = new Date(date + 'T00:00:00');
  if (Number.isNaN(d.getTime())) return '';
  const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  return `${d.getDate()} ${months[d.getMonth()]} ${d.getFullYear()}`;
}

function weekOfYear(iso?: string | null): number | null {
  if (!iso) return null;
  const d = new Date(iso.slice(0, 10) + 'T00:00:00');
  if (Number.isNaN(d.getTime())) return null;
  const start = new Date(d.getFullYear(), 0, 1);
  const week = Math.ceil(((d.getTime() - start.getTime()) / 86400000 + start.getDay() + 1) / 7);
  return Number.isFinite(week) ? week : null;
}

function yearOf(iso?: string | null): number | null {
  if (!iso) return null;
  const d = new Date(iso.slice(0, 10) + 'T00:00:00');
  if (Number.isNaN(d.getTime())) return null;
  const y = d.getFullYear();
  return Number.isFinite(y) ? y : null;
}

export default function SignalHero({ targetDate, className }: SignalHeroProps) {
  const { data: pos, isLoading: posLoading, error: posErr } = usePositionStatus(targetDate);
  const { data: recs, isLoading: recsLoading } = useRecommendations(targetDate);

  if (posLoading || recsLoading) {
    return (
      <section className={className} style={{ padding: '48px 0' }}>
        <div className="flex items-center justify-center min-h-[280px]" style={{ color: 'var(--ink-light)' }}>
          <Loader2 className="h-5 w-5 animate-spin mr-2" />
          <span className="text-sm">Chargement de l'analyse...</span>
        </div>
      </section>
    );
  }

  if (posErr || !pos) {
    return (
      <section className={className} style={{ padding: '48px 0' }}>
        <p className="text-center text-sm" style={{ color: 'var(--ink-mid)' }}>
          Aucune donnée de position pour cette date — l'analyse quotidienne n'a peut-être pas encore été exécutée.
        </p>
      </section>
    );
  }

  const meta = SIGNAL_META[pos.position];
  const sessionDate = pos.date ?? targetDate ?? null;
  const week = weekOfYear(sessionDate);
  const ytd = pos.ytd_performance;

  const deck = (recs?.recommendations ?? [])
    .slice(0, 2)
    .filter(Boolean)
    .join(' ');

  return (
    <section
      className={className}
      style={{
        display: 'grid',
        gridTemplateColumns: 'minmax(0, 1fr)',
        gap: 40,
        padding: '48px 0 40px',
        borderBottom: '2px solid var(--ink)',
      }}
    >
      <div
        className="hero-grid"
        style={{
          display: 'grid',
          gridTemplateColumns: 'minmax(0, 1fr) 320px',
          gap: 40,
        }}
      >
        <div>
          <div
            className="uppercase mb-3"
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 11,
              fontWeight: 600,
              letterSpacing: '0.2em',
              color: 'var(--ink-mid)',
            }}
          >
            {[
              'Lead Analysis',
              week != null ? `Week ${week}` : null,
              yearOf(sessionDate) != null ? `${yearOf(sessionDate)}` : null,
            ]
              .filter(Boolean)
              .join(' · ')}
          </div>

          <h2
            style={{
              fontFamily: 'var(--font-display)',
              fontWeight: 700,
              fontSize: 'clamp(36px, 5.2vw, 56px)',
              lineHeight: 1.08,
              letterSpacing: '-0.01em',
              color: 'var(--ink)',
              marginBottom: 20,
            }}
          >
            Signal {pos.position} — Cocoa {meta.headline}
            <span
              className="inline-block align-middle ml-2 px-3 py-0.5 rounded-sm uppercase"
              style={{
                background: meta.color,
                color: pos.position === 'MONITOR' ? 'var(--ink)' : 'var(--paper)',
                fontFamily: 'var(--font-mono)',
                fontSize: 16,
                fontWeight: 600,
                letterSpacing: '0.15em',
              }}
            >
              {pos.position}
            </span>
          </h2>

          {deck && (
            <p
              style={{
                fontFamily: 'var(--font-editorial)',
                fontSize: 18,
                lineHeight: 1.55,
                color: 'var(--ink-dark)',
                marginBottom: 16,
              }}
            >
              {deck}
            </p>
          )}

          <p
            className="uppercase"
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 11,
              letterSpacing: '0.15em',
              color: 'var(--ink-light)',
            }}
          >
            Compass Intelligence Desk · {formatSessionDate(sessionDate)}
          </p>
        </div>

        <aside
          className="hero-score-panel"
          style={{
            border: '1px solid var(--ink)',
            padding: '24px 20px 20px',
            background: meta.panelTint,
            borderTop: `3px solid ${meta.color}`,
            display: 'flex',
            flexDirection: 'column',
            justifyContent: 'space-between',
          }}
        >
          <div>
            <div
              className="uppercase text-center"
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 10,
                letterSpacing: '0.2em',
                color: 'var(--ink-mid)',
                marginBottom: 4,
              }}
            >
              Compass Signal
            </div>
            <div
              className="text-center"
              style={{
                fontFamily: 'var(--font-display)',
                fontWeight: 700,
                fontSize:
                  pos.position === 'MONITOR'
                    ? 'clamp(32px, 7vw, 44px)'
                    : pos.position === 'HEDGE'
                      ? 'clamp(40px, 8vw, 56px)'
                      : 'clamp(44px, 9vw, 60px)',
                lineHeight: 1,
                color: meta.color,
                margin: '8px 0 4px',
                wordBreak: 'keep-all',
                overflow: 'hidden',
                whiteSpace: 'nowrap',
              }}
            >
              {pos.position}
            </div>
            <div
              className="text-center uppercase"
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 10,
                letterSpacing: '0.18em',
                color: 'var(--ink-mid)',
                marginBottom: 16,
              }}
            >
              {meta.kicker}
            </div>
          </div>

          <div
            className="border-t pt-3"
            style={{ borderColor: 'var(--rule)' }}
          >
            <div className="flex justify-between items-baseline">
              <span
                className="uppercase"
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: 10,
                  letterSpacing: '0.15em',
                  color: 'var(--ink-mid)',
                }}
              >
                Performance YTD
              </span>
              <span
                className="tabular-nums"
                style={{
                  fontFamily: 'var(--font-display)',
                  fontWeight: 700,
                  fontSize: 24,
                  color: ytd != null && ytd >= 0 ? 'var(--color-signal-open)' : 'var(--color-signal-hedge)',
                }}
              >
                {ytd != null ? `${ytd >= 0 ? '+' : ''}${ytd.toFixed(2)}%` : '—'}
              </span>
            </div>
          </div>
        </aside>
      </div>

      <style>{`
        @media (max-width: 767px) {
          .hero-grid {
            grid-template-columns: 1fr !important;
          }
          .hero-score-panel {
            width: 100% !important;
          }
        }
      `}</style>
    </section>
  );
}
