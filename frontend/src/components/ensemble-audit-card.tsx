import axios from 'axios';
import { Loader2 } from 'lucide-react';
import SectionHeader from '@/components/section-header';
import GaugeIndicator from '@/components/gauge-indicator';
import { Eyebrow, DataValue } from '@/components/editorial';
import { useEnsembleDiagnostics, useSpecialistVotes } from '@/hooks/useDashboard';
import type {
  EnsembleDiagnosticsResponse,
  SpecialistVote,
  SpecialistVotesResponse,
} from '@/types/dashboard';

interface EnsembleAuditCardProps {
  /** Resolved by parent dashboard — when this isn't 'ensemble_v1_softgate_wrapper' the card stays hidden. */
  sourceAlgorithm?: string | null;
  targetDate?: string;
  className?: string;
}

const SIGNAL_HEX: Record<'OPEN' | 'HEDGE' | 'MONITOR', string> = {
  OPEN: 'var(--color-signal-open)',
  HEDGE: 'var(--color-signal-hedge)',
  MONITOR: 'var(--color-signal-monitor)',
};

// Soft-gate commit threshold per R&D config (kept here for the visual gauge zone hints).
const COMMIT_THRESHOLD = 0.249;
// Running-accuracy gate threshold (Compass override config-as-data).
const RUNNING_ACC_THRESHOLD = 0.5931;

function formatNumber(v?: number | null, digits = 3): string {
  if (v == null || !Number.isFinite(v)) return '—';
  return v.toFixed(digits);
}

function formatSigned(v?: number | null): string {
  if (v == null) return '—';
  return v >= 0 ? `+${v}` : `${v}`;
}

function StatusPill({
  label,
  active,
  inactive = false,
}: {
  label: string;
  active: boolean;
  inactive?: boolean;
}) {
  const bg = inactive ? 'transparent' : active ? 'var(--ink)' : 'transparent';
  const fg = inactive ? 'var(--ink-light)' : active ? 'var(--paper)' : 'var(--ink-mid)';
  const border = inactive ? '1px dashed var(--rule)' : '1px solid var(--ink)';
  return (
    <span
      className="uppercase"
      style={{
        display: 'inline-block',
        padding: '2px 8px',
        fontFamily: 'var(--font-mono)',
        fontSize: 9,
        fontWeight: 600,
        letterSpacing: '0.18em',
        background: bg,
        color: fg,
        border,
      }}
    >
      {label}
    </span>
  );
}

function DecisionBadge({ pred }: { pred: 'OPEN' | 'HEDGE' | 'MONITOR' }) {
  const hex = SIGNAL_HEX[pred];
  return (
    <span
      className="uppercase"
      style={{
        display: 'inline-block',
        padding: '2px 8px',
        fontFamily: 'var(--font-mono)',
        fontSize: 10,
        fontWeight: 700,
        letterSpacing: '0.18em',
        color: pred === 'MONITOR' ? 'var(--ink)' : 'var(--paper)',
        background: hex,
      }}
    >
      {pred}
    </span>
  );
}

function ClusterColumn({
  title,
  votes,
  signed,
  highlight,
}: {
  title: string;
  votes: SpecialistVote[];
  signed: number | null;
  highlight: boolean;
}) {
  return (
    <div
      style={{
        border: '1px solid var(--rule)',
        padding: 16,
        background: highlight ? 'rgba(245, 158, 11, 0.04)' : 'var(--paper-off)',
        borderLeft: highlight ? '2px solid var(--color-signal-monitor)' : '1px solid var(--rule)',
      }}
    >
      <div className="flex items-baseline justify-between" style={{ marginBottom: 10 }}>
        <Eyebrow tone="primary" size={10}>
          {title}
        </Eyebrow>
        <span
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 11,
            fontWeight: 700,
            color: 'var(--ink)',
          }}
        >
          signed {formatSigned(signed)}
        </span>
      </div>
      <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
        {votes.length === 0 && (
          <li style={{ fontSize: 11, color: 'var(--ink-light)', fontStyle: 'italic' }}>
            Aucun spécialiste assigné à ce cluster.
          </li>
        )}
        {votes.map((v) => (
          <li
            key={v.specialist_name}
            className="flex items-center justify-between"
            style={{
              padding: '6px 0',
              borderTop: '1px dotted var(--rule)',
            }}
          >
            <span
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 11,
                color: 'var(--ink-dark)',
              }}
            >
              {v.specialist_name}
              <span style={{ color: 'var(--ink-light)', marginLeft: 6 }}>
                · {v.window_months}m
              </span>
            </span>
            <DecisionBadge pred={v.pred} />
          </li>
        ))}
      </ul>
    </div>
  );
}

function DetectorCard({
  title,
  active,
  fired,
  inactive,
  value,
  threshold,
  note,
  released,
}: {
  title: string;
  active: boolean;
  fired: boolean;
  inactive?: boolean;
  value?: string;
  threshold?: string;
  note?: string;
  released?: boolean;
}) {
  const status = inactive
    ? 'INACTIVE V1.0.0'
    : released
      ? 'FIRED · RELEASED'
      : fired
        ? 'FIRED'
        : 'PASS';
  return (
    <div
      style={{
        border: '1px solid var(--ink)',
        padding: 14,
        opacity: inactive ? 0.55 : 1,
        background: 'var(--paper)',
      }}
    >
      <div className="flex items-baseline justify-between" style={{ marginBottom: 8 }}>
        <Eyebrow tone="primary" size={10}>
          {title}
        </Eyebrow>
        <StatusPill label={status} active={active} inactive={inactive} />
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr auto', gap: 6, fontSize: 11 }}>
        {value && (
          <>
            <span style={rowLabel}>Value</span>
            <DataValue>{value}</DataValue>
          </>
        )}
        {threshold && (
          <>
            <span style={rowLabel}>Threshold</span>
            <DataValue color="var(--ink-mid)">{threshold}</DataValue>
          </>
        )}
      </div>
      {note && (
        <p
          style={{
            marginTop: 10,
            fontFamily: 'var(--font-editorial)',
            fontSize: 12,
            color: 'var(--ink-mid)',
            lineHeight: 1.5,
          }}
        >
          {note}
        </p>
      )}
    </div>
  );
}

function PriorsBar({ open, hedge, monitor }: { open?: number | null; hedge?: number | null; monitor?: number | null }) {
  const o = Math.max(0, Math.min(1, open ?? 0));
  const h = Math.max(0, Math.min(1, hedge ?? 0));
  const m = Math.max(0, Math.min(1, monitor ?? 0));
  const total = o + h + m || 1;
  const oPct = (o / total) * 100;
  const hPct = (h / total) * 100;
  const mPct = (m / total) * 100;
  return (
    <div>
      <div style={{ display: 'flex', height: 8, border: '1px solid var(--ink)' }}>
        <div style={{ width: `${oPct}%`, background: SIGNAL_HEX.OPEN }} />
        <div style={{ width: `${mPct}%`, background: SIGNAL_HEX.MONITOR }} />
        <div style={{ width: `${hPct}%`, background: SIGNAL_HEX.HEDGE }} />
      </div>
      <div className="flex justify-between" style={{ marginTop: 4 }}>
        <span style={priorLabel}>OPEN {formatNumber(open, 2)}</span>
        <span style={priorLabel}>MON {formatNumber(monitor, 2)}</span>
        <span style={priorLabel}>HEDGE {formatNumber(hedge, 2)}</span>
      </div>
    </div>
  );
}

function renderDiagnostics(diag: EnsembleDiagnosticsResponse, votes?: SpecialistVotesResponse) {
  const winterVotes = (votes?.votes ?? []).filter((v) => v.cluster === 'winter');
  const springVotes = (votes?.votes ?? []).filter((v) => v.cluster === 'spring');
  const dispReleased = diag.fired_dispersion && !diag.wrapper_active;

  return (
    <>
      {/* Sub-block 1 — Soft-gate signal */}
      <div style={{ marginBottom: 32 }}>
        <Eyebrow as="div" tone="primary" size={11} style={{ marginBottom: 12 }}>
          Soft-gate signal
        </Eyebrow>
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'minmax(0, 1.4fr) minmax(0, 1fr)',
            gap: 24,
            alignItems: 'start',
          }}
          className="audit-grid"
        >
          <GaugeIndicator
            value={diag.net_score}
            min={-1}
            max={1}
            label="NET SCORE"
            ranges={[
              { range_low: -1, range_high: -COMMIT_THRESHOLD, area: 'RED' },
              { range_low: -COMMIT_THRESHOLD, range_high: COMMIT_THRESHOLD, area: 'ORANGE' },
              { range_low: COMMIT_THRESHOLD, range_high: 1, area: 'GREEN' },
            ]}
          />
          <div
            style={{
              border: '1px solid var(--ink)',
              padding: '14px 16px',
              display: 'grid',
              gridTemplateColumns: '1fr auto',
              rowGap: 10,
              columnGap: 12,
              fontSize: 11,
            }}
          >
            <span style={rowLabel}>Soft-gate</span>
            <DecisionBadge pred={diag.soft_gate_decision} />
            <span style={rowLabel}>Wrapped</span>
            <DecisionBadge pred={diag.decision_wrapped} />
            <span style={rowLabel}>Wrapper</span>
            <StatusPill label={diag.wrapper_active ? 'ACTIVE' : 'NEUTRAL'} active={diag.wrapper_active} />
            <span style={rowLabel}>Committed</span>
            <DataValue>{diag.n_committed_specialists}/14</DataValue>
            <span style={rowLabel}>Weights Σ</span>
            <DataValue>{formatNumber(diag.weights_sum, 3)}</DataValue>
            <span style={rowLabel}>Realized 5d</span>
            <DataValue>{formatNumber(diag.realized_return_5d, 4)}</DataValue>
          </div>
        </div>
      </div>

      {/* Sub-block 2 — Specialist votes (cluster columns) */}
      <div style={{ marginBottom: 32 }}>
        <Eyebrow as="div" tone="primary" size={11} style={{ marginBottom: 12 }}>
          Specialist votes · cluster decomposition
        </Eyebrow>
        {votes ? (
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: '1fr 1fr',
              gap: 16,
            }}
            className="cluster-grid"
          >
            <ClusterColumn
              title="Winter cluster"
              votes={winterVotes}
              signed={votes.winter_signed}
              highlight={dispReleased}
            />
            <ClusterColumn
              title="Spring cluster"
              votes={springVotes}
              signed={votes.spring_signed}
              highlight={dispReleased}
            />
          </div>
        ) : (
          <p style={{ fontSize: 11, color: 'var(--ink-light)', fontStyle: 'italic' }}>
            Votes des spécialistes indisponibles pour cette date.
          </p>
        )}
      </div>

      {/* Sub-block 3 — Detector firings */}
      <div style={{ marginBottom: 32 }}>
        <Eyebrow as="div" tone="primary" size={11} style={{ marginBottom: 12 }}>
          Detectors · wrapper override audit
        </Eyebrow>
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(2, minmax(0, 1fr))',
            gap: 16,
          }}
          className="detector-grid"
        >
          <DetectorCard
            title="Running accuracy gate"
            active={diag.fired_running_acc}
            fired={diag.fired_running_acc}
            value={formatNumber(diag.running_acc_5d, 3)}
            threshold={`≥ ${RUNNING_ACC_THRESHOLD}`}
            note={
              diag.fired_running_acc
                ? 'Accuracy ≥ threshold — wrapper unlocks dispersion release.'
                : 'Accuracy below threshold — dispersion veto stands when fired.'
            }
          />
          <DetectorCard
            title="Cluster dispersion"
            active={diag.fired_dispersion}
            fired={diag.fired_dispersion}
            released={dispReleased}
            value={
              diag.winter_vote_signed != null && diag.spring_vote_signed != null
                ? `W ${formatSigned(diag.winter_vote_signed)} · S ${formatSigned(diag.spring_vote_signed)}`
                : undefined
            }
            note={
              dispReleased
                ? 'Dispersion fired but Compass override released to soft-gate decision.'
                : diag.fired_dispersion
                  ? 'Dispersion vetoes the commit — wrapper degrades to MONITOR.'
                  : 'Winter / Spring aligned — no dispersion penalty.'
            }
          />
          <DetectorCard
            title="Trend conflict"
            active={false}
            fired={diag.fired_trend}
            inactive
            note="Inactive in v1.0.0 — reserved for v1.1.0 trend overlay."
          />
          <DetectorCard
            title="Three-way disagreement"
            active={false}
            fired={diag.fired_three_way}
            inactive
            note="Inactive in v1.0.0 — reserved for v1.1.0 three-cluster topology."
          />
        </div>
      </div>

      {/* Sub-block 4 — Macro & context */}
      <div>
        <Eyebrow as="div" tone="primary" size={11} style={{ marginBottom: 12 }}>
          Macro & context · priors
        </Eyebrow>
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
            gap: 16,
          }}
        >
          <div style={contextCard}>
            <Eyebrow tone="muted" size={9}>
              Macro direction
            </Eyebrow>
            <div
              style={{
                fontFamily: 'var(--font-display)',
                fontWeight: 700,
                fontSize: 28,
                color:
                  diag.macro_direction == null
                    ? 'var(--ink-light)'
                    : diag.macro_direction > 0
                      ? SIGNAL_HEX.OPEN
                      : diag.macro_direction < 0
                        ? SIGNAL_HEX.HEDGE
                        : 'var(--ink)',
                marginTop: 6,
              }}
            >
              {diag.macro_direction == null
                ? '—'
                : diag.macro_direction > 0
                  ? 'BULL'
                  : diag.macro_direction < 0
                    ? 'BEAR'
                    : 'NEUTRAL'}
            </div>
            <div style={{ marginTop: 4 }}>
              <Eyebrow tone="subtle" size={9}>
                surprise {formatNumber(diag.macro_surprise, 3)} · half-life{' '}
                {diag.macro_half_life_days ?? '—'}d
              </Eyebrow>
            </div>
          </div>

          <div style={contextCard}>
            <Eyebrow tone="muted" size={9}>
              Anomaly score z
            </Eyebrow>
            <div
              style={{
                fontFamily: 'var(--font-display)',
                fontWeight: 700,
                fontSize: 28,
                color:
                  diag.anomaly_score_z != null && Math.abs(diag.anomaly_score_z) > 2
                    ? SIGNAL_HEX.MONITOR
                    : 'var(--ink)',
                marginTop: 6,
              }}
            >
              {formatNumber(diag.anomaly_score_z, 2)}
            </div>
            <div style={{ marginTop: 4 }}>
              <Eyebrow tone="subtle" size={9}>
                Long-run regime anomaly
              </Eyebrow>
            </div>
          </div>

          <div style={contextCard}>
            <Eyebrow tone="muted" size={9} style={{ marginBottom: 8 }}>
              Priors triplet
            </Eyebrow>
            <PriorsBar open={diag.prior_open} hedge={diag.prior_hedge} monitor={diag.prior_monitor} />
          </div>
        </div>
      </div>

      <style>{`
        @media (max-width: 767px) {
          .audit-grid, .cluster-grid, .detector-grid {
            grid-template-columns: 1fr !important;
          }
        }
      `}</style>
    </>
  );
}

export default function EnsembleAuditCard({
  sourceAlgorithm,
  targetDate,
  className,
}: EnsembleAuditCardProps) {
  // Section is conditional on the date producing an ensemble decision.
  const isEnsembleDate = sourceAlgorithm === 'ensemble_v1_softgate_wrapper';
  const diagQ = useEnsembleDiagnostics(isEnsembleDate ? targetDate : undefined);
  const votesQ = useSpecialistVotes(isEnsembleDate ? targetDate : undefined);

  if (!isEnsembleDate) return null;

  const is404 = (q: typeof diagQ) =>
    q.isError && axios.isAxiosError(q.error) && q.error.response?.status === 404;

  if (is404(diagQ)) return null;

  return (
    <section className={className} style={{ padding: '32px 0' }}>
      <SectionHeader numeral="VII" title="Ensemble Decision Audit" />

      {diagQ.isLoading ? (
        <div className="flex items-center justify-center min-h-[200px]" style={{ color: 'var(--ink-light)' }}>
          <Loader2 className="h-5 w-5 animate-spin mr-2" />
          <span className="text-sm">Chargement de l'audit ensemble...</span>
        </div>
      ) : diagQ.data ? (
        renderDiagnostics(diagQ.data, votesQ.data)
      ) : (
        <p style={{ fontSize: 13, color: 'var(--ink-light)' }}>
          Aucune ligne d'audit ensemble pour cette date.
        </p>
      )}
    </section>
  );
}

const rowLabel: React.CSSProperties = {
  fontFamily: 'var(--font-mono)',
  fontSize: 10,
  textTransform: 'uppercase',
  letterSpacing: '0.12em',
  color: 'var(--ink-mid)',
};

const priorLabel: React.CSSProperties = {
  fontFamily: 'var(--font-mono)',
  fontSize: 9,
  textTransform: 'uppercase',
  letterSpacing: '0.12em',
  color: 'var(--ink-mid)',
};

const contextCard: React.CSSProperties = {
  border: '1px solid var(--rule)',
  padding: 14,
  background: 'var(--paper-off)',
};
