import { Loader2 } from 'lucide-react';
import { usePositionStatus, useRecommendations, useEnsembleDiagnostics } from '@/hooks/useDashboard';
import Eyebrow from '@/components/editorial/Eyebrow';
import { buildEnsembleExplanation } from '@/utils/ensemble-explanation';
import type { EnsembleDiagnosticsResponse } from '@/types/dashboard';

function algoBadgeLabel(name?: string | null): string | null {
  if (!name) return null;
  if (name === 'ensemble_v1_softgate_wrapper') return 'Powered by Ensemble v1';
  if (name === 'legacy') return 'Powered by Legacy v1.0.1';
  return `Powered by ${name}`;
}

function horizonShortLabel(name?: string | null): string {
  if (name === 'ensemble_v1_softgate_wrapper') return '~4 J';
  return 'J+1';
}

function convictionWord(netScore: number): string {
  const abs = Math.abs(netScore);
  if (abs >= 0.6) return 'Forte';
  if (abs >= 0.249) return 'Marquée';
  return 'Mesurée';
}

function macroWord(direction: number | null | undefined): {
  label: string;
  arrow: string;
  color: string;
} {
  if (direction == null)
    return { label: 'Indéfini', arrow: '·', color: 'var(--ink-light)' };
  if (direction > 0)
    return { label: 'Porteur', arrow: '↑', color: 'var(--color-signal-open)' };
  if (direction < 0)
    return {
      label: 'Défavorable',
      arrow: '↓',
      color: 'var(--color-signal-hedge)',
    };
  return { label: 'Neutre', arrow: '→', color: 'var(--ink-mid)' };
}

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

/* ===================================================================
 * Conviction breakdown — left "by the numbers" magazine sidebar.
 * 4 KPI tiles in a 4-col grid separated by 1px vertical hairlines.
 * Sharp corners, no card borders, no shadows. Magazine codes.
 * =================================================================== */
function ConvictionBreakdown({
  diag,
  signalColor,
}: {
  diag: EnsembleDiagnosticsResponse;
  signalColor: string;
}) {
  const macro = macroWord(diag.macro_direction);
  const accPct =
    diag.running_acc_5d != null ? Math.round(diag.running_acc_5d * 100) : null;
  const scoreStr = `${diag.net_score >= 0 ? '+' : ''}${diag.net_score.toFixed(2)}`;

  const tiles = [
    {
      eyebrow: 'Conviction',
      big: convictionWord(diag.net_score),
      italic: true,
      color: signalColor,
      caption: `${scoreStr} score net`,
    },
    {
      eyebrow: 'Consensus',
      big: `${diag.n_committed_specialists} / 14`,
      italic: false,
      color: 'var(--ink)',
      caption: 'spécialistes engagés',
    },
    {
      eyebrow: 'Macro',
      big: macro.label,
      italic: true,
      color: macro.color,
      caption: `${macro.arrow} direction`,
    },
    {
      eyebrow: 'Précision 5j',
      big: accPct != null ? `${accPct}%` : '—',
      italic: false,
      color:
        accPct != null && accPct >= 60 ? 'var(--color-signal-open)' : 'var(--ink)',
      caption: 'running accuracy',
    },
  ];

  return (
    <div style={{ marginTop: 28, marginBottom: 16 }}>
      <Eyebrow
        as="div"
        tone="muted"
        size={9}
        tracking="0.24em"
        style={{ marginBottom: 12 }}
      >
        Conviction breakdown
      </Eyebrow>

      <div
        className="conviction-grid"
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(4, minmax(0, 1fr))',
          borderTop: '1px solid var(--ink)',
          borderBottom: '1px solid var(--rule)',
        }}
      >
        {tiles.map((tile, i) => (
          <div
            key={tile.eyebrow}
            style={{
              padding: '14px 16px 12px',
              borderLeft: i === 0 ? 'none' : '1px solid var(--rule)',
            }}
          >
            <Eyebrow as="div" tone="subtle" size={9} tracking="0.2em">
              {tile.eyebrow}
            </Eyebrow>
            <div
              style={{
                fontFamily: 'var(--font-display)',
                fontStyle: tile.italic ? 'italic' : 'normal',
                fontWeight: 700,
                fontSize: 'clamp(20px, 2.4vw, 28px)',
                lineHeight: 1.1,
                color: tile.color,
                marginTop: 6,
              }}
            >
              {tile.big}
            </div>
            <div
              className="uppercase"
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 9,
                letterSpacing: '0.15em',
                color: 'var(--ink-light)',
                marginTop: 4,
              }}
            >
              {tile.caption}
            </div>
          </div>
        ))}
      </div>

      <style>{`
        @media (max-width: 767px) {
          .conviction-grid {
            grid-template-columns: repeat(2, minmax(0, 1fr)) !important;
          }
          .conviction-grid > div:nth-child(2) {
            border-left: 1px solid var(--rule) !important;
          }
          .conviction-grid > div:nth-child(3) {
            border-left: none !important;
            border-top: 1px solid var(--rule);
          }
          .conviction-grid > div:nth-child(4) {
            border-top: 1px solid var(--rule);
          }
        }
      `}</style>
    </div>
  );
}

/* ===================================================================
 * Score panel Horizon — the only KPI kept inside the score card.
 *
 * Net score / Consensus / Précision 5j are surfaced in the left-side
 * Conviction Breakdown — duplicating them in the score panel was repetitive.
 * The Horizon stays here because it qualifies the OPEN/HEDGE/MONITOR call
 * directly ("acheteuse pour combien de temps ?"). Styled as a single
 * highlighted block — Playfair italic, prominent.
 * =================================================================== */
function ScorePanelHorizon({
  sourceAlgorithm,
  signalColor,
}: {
  sourceAlgorithm: string | null | undefined;
  signalColor: string;
}) {
  const horizon = horizonShortLabel(sourceAlgorithm);
  const subtitle =
    sourceAlgorithm === 'ensemble_v1_softgate_wrapper'
      ? '4 jours boursiers'
      : 'Session suivante · J+1';

  return (
    <div
      style={{
        marginTop: 16,
        paddingTop: 16,
        paddingBottom: 16,
        borderTop: '1px solid var(--ink)',
        borderBottom: '1px solid var(--rule)',
        textAlign: 'center',
      }}
    >
      <Eyebrow as="div" tone="muted" size={10} tracking="0.22em">
        Horizon de projection
      </Eyebrow>
      <div
        className="tabular-nums"
        style={{
          fontFamily: 'var(--font-display)',
          fontWeight: 700,
          fontSize: 'clamp(28px, 3.6vw, 38px)',
          lineHeight: 1,
          color: signalColor,
          margin: '8px 0 4px',
          whiteSpace: 'nowrap',
        }}
      >
        {horizon}
      </div>
      <div
        style={{
          fontFamily: 'var(--font-display)',
          fontStyle: 'italic',
          fontSize: 13,
          color: 'var(--ink-mid)',
        }}
      >
        {subtitle}
      </div>
    </div>
  );
}

export default function SignalHero({ targetDate, className }: SignalHeroProps) {
  const { data: pos, isLoading: posLoading, error: posErr } = usePositionStatus(targetDate);
  const { data: recs, isLoading: recsLoading } = useRecommendations(targetDate);
  const { data: diag } = useEnsembleDiagnostics(targetDate);
  const ensembleAligned =
    pos?.source_algorithm === 'ensemble_v1_softgate_wrapper' && Boolean(diag);
  const explanationSentences =
    ensembleAligned && diag ? buildEnsembleExplanation(diag) : null;

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
        {/* ============================= LEFT ============================= */}
        <div>
          {algoBadgeLabel(pos.source_algorithm) && (
            <Eyebrow
              as="div"
              size={9}
              tone="subtle"
              tracking="0.22em"
              style={{ marginBottom: 6 }}
            >
              {algoBadgeLabel(pos.source_algorithm)}
            </Eyebrow>
          )}
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

          {/* Conviction breakdown — only on ensemble dates */}
          {ensembleAligned && diag && (
            <ConvictionBreakdown diag={diag} signalColor={meta.color} />
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

        {/* ============================= RIGHT ============================= */}
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
                marginBottom: 4,
              }}
            >
              {meta.kicker}
            </div>

            {ensembleAligned && diag ? (
              <>
                <ScorePanelHorizon
                  sourceAlgorithm={pos.source_algorithm}
                  signalColor={meta.color}
                />

                {explanationSentences && (
                  <div style={{ marginTop: 14 }}>
                    <Eyebrow
                      as="div"
                      tone="muted"
                      size={9}
                      tracking="0.18em"
                      style={{ marginBottom: 8, textAlign: 'center' }}
                    >
                      Pourquoi cette décision
                    </Eyebrow>
                    {explanationSentences.map((s, i) => (
                      <p
                        key={i}
                        style={{
                          fontFamily: 'var(--font-editorial)',
                          fontStyle: 'italic',
                          fontSize: 12,
                          lineHeight: 1.55,
                          color: 'var(--ink-dark)',
                          margin: i === 0 ? '0 0 6px' : '0',
                          textAlign: 'left',
                        }}
                      >
                        {s}
                      </p>
                    ))}
                  </div>
                )}
              </>
            ) : (
              // Legacy / no diagnostics — minimal fallback (horizon line)
              <div
                style={{
                  marginTop: 12,
                  paddingTop: 12,
                  borderTop: '1px dotted var(--rule)',
                  textAlign: 'center',
                }}
              >
                <Eyebrow as="div" tone="muted" size={9} tracking="0.22em">
                  Horizon de projection
                </Eyebrow>
                <div
                  style={{
                    fontFamily: 'var(--font-display)',
                    fontStyle: 'italic',
                    fontSize: 13,
                    color: 'var(--ink-dark)',
                    marginTop: 4,
                  }}
                >
                  {pos.source_algorithm === 'ensemble_v1_softgate_wrapper'
                    ? '~4 jours boursiers'
                    : 'Session suivante · J+1'}
                </div>
              </div>
            )}
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
