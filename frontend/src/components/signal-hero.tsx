import { Loader2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { usePositionStatus, useRecommendations, useEnsembleDiagnostics, useNonTradingDays } from '@/hooks/useDashboard';
import Eyebrow from '@/components/editorial/Eyebrow';
import { buildEnsembleExplanation } from '@/utils/ensemble-explanation';
import { addTradingDays } from '@/utils/date-utils';
import { formatDate } from '@/utils/format-locale';
import { useLanguage } from '@/hooks/useLanguage';
import type { Language } from '@/contexts/LanguageContext';
import type { TFunction } from 'i18next';
import type { EnsembleDiagnosticsResponse } from '@/types/dashboard';

function algoBadgeLabel(t: TFunction, name?: string | null): string | null {
  if (!name) return null;
  if (name === 'ensemble_v1_softgate_wrapper') return t('dashboard.algo_ensemble');
  if (name === 'legacy') return t('dashboard.algo_legacy');
  return `Powered by ${name}`;
}

function horizonShortLabel(t: TFunction, name?: string | null): string {
  if (name === 'ensemble_v1_softgate_wrapper') return t('dashboard.horizon_short_ensemble');
  return t('dashboard.horizon_short_legacy');
}

function formatLongDate(iso: string | null, language: Language): string {
  if (!iso) return '—';
  const d = new Date(iso + 'T00:00:00');
  if (Number.isNaN(d.getTime())) return iso;
  return formatDate(d, language, 'd MMMM yyyy');
}

function macroWord(
  t: TFunction,
  direction: number | null | undefined,
): {
  label: string;
  arrow: string;
  color: string;
} {
  if (direction == null)
    return { label: t('signal.macro.undefined'), arrow: '·', color: 'var(--ink-light)' };
  if (direction > 0)
    return { label: t('signal.macro.positive'), arrow: '↑', color: 'var(--color-signal-open)' };
  if (direction < 0)
    return {
      label: t('signal.macro.negative'),
      arrow: '↓',
      color: 'var(--color-signal-hedge)',
    };
  return { label: t('signal.macro.neutral'), arrow: '→', color: 'var(--ink-mid)' };
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

function formatSessionDate(iso: string | null | undefined, language: Language): string {
  if (!iso) return '';
  const date = iso.slice(0, 10);
  const d = new Date(date + 'T00:00:00');
  if (Number.isNaN(d.getTime())) return '';
  return formatDate(d, language, 'd MMM yyyy');
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
 *
 * Three KPI tiles, in this order:
 *   1. Consensus  — n_committed_specialists / 14
 *   2. Confiance  — LLM confidence 1-5 + rationale
 *   3. Contexte   — macro direction (porteur / défavorable / neutre)
 *
 * Engine internals (net_score, wrapper, soft-gate, detectors) intentionally
 * hidden — they're audit-only and live in the brief redaction.
 * =================================================================== */
function ConvictionBreakdown({
  diag,
  signalColor,
}: {
  diag: EnsembleDiagnosticsResponse;
  signalColor: string;
}) {
  const { t } = useTranslation();
  const macro = macroWord(t, diag.macro_direction);

  const tiles = [
    {
      key: 'consensus',
      eyebrow: t('dashboard.conviction_consensus_label'),
      big: `${diag.n_committed_specialists} / 14`,
      italic: false,
      color: 'var(--ink)',
      caption: t('dashboard.specialists_engaged'),
      wraps: false,
    },
    {
      key: 'confidence',
      eyebrow: t('dashboard.conviction_confidence_label'),
      big: diag.confidence != null ? `${diag.confidence} / 5` : '—',
      italic: false,
      color: signalColor,
      caption:
        diag.confidence_rationale && diag.confidence_rationale.trim().length > 0
          ? diag.confidence_rationale
          : t('dashboard.rationale_unavailable'),
      wraps: true,
    },
    {
      key: 'context',
      eyebrow: t('dashboard.conviction_context_label'),
      big: macro.label,
      italic: true,
      color: macro.color,
      caption: `${macro.arrow} ${t('dashboard.macro_suffix')}`,
      wraps: false,
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
        {t('dashboard.conviction_breakdown_title')}
      </Eyebrow>

      <div
        className="conviction-grid"
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(3, minmax(0, 1fr))',
          borderTop: '1px solid var(--ink)',
          borderBottom: '1px solid var(--rule)',
        }}
      >
        {tiles.map((tile, i) => {
          // Allow the confidence tile caption (rationale) to wrap onto 2 lines
          // — it's a sentence, not a kicker. Others stay single-line.
          const captionWraps = tile.wraps;
          return (
            <div
              key={tile.key}
              style={{
                padding: '14px 16px 12px',
                borderLeft: i === 0 ? 'none' : '1px solid var(--rule)',
                minWidth: 0,
                overflow: 'hidden',
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
                  fontSize: 'clamp(18px, 1.9vw, 24px)',
                  lineHeight: 1.1,
                  color: tile.color,
                  marginTop: 6,
                  whiteSpace: 'nowrap',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                }}
              >
                {tile.big}
              </div>
              <div
                className={captionWraps ? '' : 'uppercase'}
                style={{
                  fontFamily: captionWraps
                    ? 'var(--font-sans)'
                    : 'var(--font-mono)',
                  fontSize: captionWraps ? 11 : 9,
                  letterSpacing: captionWraps ? 'normal' : '0.15em',
                  color: 'var(--ink-mid)',
                  marginTop: 4,
                  whiteSpace: captionWraps ? 'normal' : 'nowrap',
                  overflow: 'hidden',
                  textOverflow: captionWraps ? 'clip' : 'ellipsis',
                  lineHeight: captionWraps ? 1.35 : 1.2,
                  display: captionWraps ? '-webkit-box' : 'block',
                  WebkitLineClamp: captionWraps ? 3 : undefined,
                  WebkitBoxOrient: captionWraps ? 'vertical' : undefined,
                }}
              >
                {tile.caption}
              </div>
            </div>
          );
        })}
      </div>

      <style>{`
        /* Stack to a single column under ~720px so the rationale stays
           readable on mobile. Above that, 3 columns is OK because the
           caption can wrap. */
        @media (max-width: 719px) {
          .conviction-grid {
            grid-template-columns: 1fr !important;
          }
          .conviction-grid > div {
            border-left: none !important;
          }
          .conviction-grid > div:not(:first-child) {
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
 * Conviction / Consensus / Macro / Wrapper are surfaced in the left-side
 * Conviction Breakdown — duplicating them in the score panel was repetitive.
 * The Horizon stays here because it qualifies the OPEN/HEDGE/MONITOR call
 * directly ("acheteuse pour combien de temps ?"). Styled as a single
 * highlighted block — Playfair italic, prominent.
 * =================================================================== */
function ScorePanelHorizon({
  sourceAlgorithm,
  signalColor,
  sessionDate,
  nonTradingDays,
}: {
  sourceAlgorithm: string | null | undefined;
  signalColor: string;
  sessionDate: string | null;
  nonTradingDays: Set<string>;
}) {
  const { t } = useTranslation();
  const { language } = useLanguage();
  const horizon = horizonShortLabel(t, sourceAlgorithm);
  const horizonDays =
    sourceAlgorithm === 'ensemble_v1_softgate_wrapper' ? 4 : 1;
  const targetDate = addTradingDays(sessionDate, horizonDays, nonTradingDays);
  const subtitle =
    targetDate != null
      ? t('signal.horizon_evaluated_at', { date: formatLongDate(targetDate, language) })
      : sourceAlgorithm === 'ensemble_v1_softgate_wrapper'
        ? t('signal.horizon_ensemble_label')
        : t('signal.horizon_legacy_label');

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
        {t('dashboard.horizon_label')}
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
  const { t } = useTranslation();
  const { language } = useLanguage();
  const { data: pos, isLoading: posLoading, error: posErr } = usePositionStatus(targetDate);
  const { data: recs, isLoading: recsLoading } = useRecommendations(targetDate);
  const { data: diag } = useEnsembleDiagnostics(targetDate);
  // Non-trading days for the current year — used to compute the exact close
  // date evaluated at T+horizon (skip weekends AND exchange holidays).
  const sessionYear = (() => {
    const iso = pos?.date ?? targetDate ?? null;
    if (!iso) return new Date().getFullYear();
    const y = Number(iso.slice(0, 4));
    return Number.isFinite(y) ? y : new Date().getFullYear();
  })();
  const { data: nonTradingDaysData } = useNonTradingDays(sessionYear);
  const nonTradingDays = new Set(nonTradingDaysData?.dates ?? []);
  const ensembleAligned =
    pos?.source_algorithm === 'ensemble_v1_softgate_wrapper' && Boolean(diag);
  const explanationSentences =
    ensembleAligned && diag ? buildEnsembleExplanation(diag, t) : null;

  if (posLoading || recsLoading) {
    return (
      <section className={className} style={{ padding: '48px 0' }}>
        <div className="flex items-center justify-center min-h-[280px]" style={{ color: 'var(--ink-light)' }}>
          <Loader2 className="h-5 w-5 animate-spin mr-2" />
          <span className="text-sm">{t('loading.signal_analysis')}</span>
        </div>
      </section>
    );
  }

  if (posErr || !pos) {
    return (
      <section className={className} style={{ padding: '48px 0' }}>
        <p className="text-center text-sm" style={{ color: 'var(--ink-mid)' }}>
          {t('common.error_no_data')}
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
          {algoBadgeLabel(t, pos.source_algorithm) && (
            <Eyebrow
              as="div"
              size={9}
              tone="subtle"
              tracking="0.22em"
              style={{ marginBottom: 6 }}
            >
              {algoBadgeLabel(t, pos.source_algorithm)}
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
              t('dashboard.lead_analysis'),
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
            {t('dashboard.desk_name')} · {formatSessionDate(sessionDate, language)}
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
                  sessionDate={sessionDate}
                  nonTradingDays={nonTradingDays}
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
                      {t('dashboard.why_this_decision')}
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
                  {t('dashboard.horizon_label')}
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
                    ? t('signal.horizon_ensemble_label_approx')
                    : t('signal.horizon_legacy_label')}
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
