import axios from 'axios';
import { Loader2 } from 'lucide-react';
import { useState } from 'react';
import SectionHeader from '@/components/section-header';
import { Eyebrow, DataValue } from '@/components/editorial';
import { useEnsembleDiagnostics, useSpecialistVotes } from '@/hooks/useDashboard';
import type {
  EnsembleDiagnosticsResponse,
  SpecialistVotesResponse,
} from '@/types/dashboard';

interface DecisionExplainerCardProps {
  /** Resolved by parent dashboard — when this isn't 'ensemble_v1_softgate_wrapper' the card stays hidden. */
  sourceAlgorithm?: string | null;
  targetDate?: string;
  className?: string;
}

/**
 * Section VII — POURQUOI CETTE DÉCISION
 *
 * Replaces the previous full audit panel. Shows a plain-French explanation of
 * the ensemble decision + 3 wow-effect metric tiles. The underlying technical
 * diagnostics (cluster votes, detector firings, priors) remain accessible via
 * a collapsed "Diagnostic technique" disclosure for power users.
 *
 * Hides automatically on legacy dates or when /ensemble-diagnostics 404s.
 */
const SIGNAL_HEX = {
  OPEN: 'var(--color-signal-open)',
  HEDGE: 'var(--color-signal-hedge)',
  MONITOR: 'var(--color-signal-monitor)',
} as const;

function decisionFR(d: 'OPEN' | 'HEDGE' | 'MONITOR'): string {
  if (d === 'OPEN') return 'acheteuse';
  if (d === 'HEDGE') return 'défensive';
  return 'attentiste';
}

function macroFR(direction: number | null | undefined): string | null {
  if (direction == null) return null;
  if (direction > 0) return 'porteur (signal macro haussier)';
  if (direction < 0) return 'défavorable (signal macro baissier)';
  return 'neutre';
}

function convictionLabel(netScore: number): string {
  const abs = Math.abs(netScore);
  if (abs >= 0.6) return 'forte';
  if (abs >= 0.249) return 'modérée';
  return 'faible';
}

/**
 * Build 2-4 plain-French sentences from the diagnostics — templated, no LLM.
 * Replaced by a real ensemble-aligned narrative in Phase 8 (cc-daily-analysis
 * refactor).
 */
function buildExplanation(diag: EnsembleDiagnosticsResponse): string[] {
  const sentences: string[] = [];

  // Sentence 1 — consensus + conviction
  const decision = diag.decision_wrapped;
  const conviction = convictionLabel(diag.net_score);
  const scoreStr = `${diag.net_score >= 0 ? '+' : ''}${diag.net_score.toFixed(2)}`;
  sentences.push(
    `${diag.n_committed_specialists} spécialistes sur 14 confirment la position ${decisionFR(decision)}, avec une conviction ${conviction} (score ${scoreStr}).`,
  );

  // Sentence 2 — macro context (skip if null)
  const macroLabel = macroFR(diag.macro_direction);
  if (macroLabel) {
    sentences.push(`Le contexte macro reste ${macroLabel}.`);
  }

  // Sentence 3 — anomaly check
  if (diag.anomaly_score_z != null && Math.abs(diag.anomaly_score_z) > 2) {
    sentences.push(
      `Le marché évolue en régime atypique (anomalie z=${diag.anomaly_score_z.toFixed(2)}) — la décision intègre cette singularité.`,
    );
  }

  // Sentence 4 — safety net status
  if (diag.fired_dispersion && !diag.wrapper_active) {
    const acc = diag.running_acc_5d ? Math.round(diag.running_acc_5d * 100) : null;
    const accStr = acc != null ? ` (${acc}% sur 5 jours)` : '';
    sentences.push(
      `Une divergence entre régimes a été détectée, mais la précision récente du modèle${accStr} a permis de relâcher le filet de sécurité.`,
    );
  } else if (diag.wrapper_active) {
    sentences.push(
      `Le filet de sécurité s'est activé : la décision a été rétrogradée par prudence face à des signaux conflictuels.`,
    );
  } else {
    sentences.push(
      `Aucun signal d'alerte n'a été déclenché — la décision est livrée telle quelle par l'orchestrateur.`,
    );
  }

  return sentences;
}

function MetricTile({
  value,
  label,
  color,
  highlight,
}: {
  value: string;
  label: string;
  color?: string;
  highlight?: boolean;
}) {
  return (
    <div
      style={{
        padding: '18px 16px 14px',
        border: '1px solid var(--ink)',
        background: highlight ? 'rgba(16, 185, 129, 0.03)' : 'var(--paper)',
        textAlign: 'center',
      }}
    >
      <div
        className="tabular-nums"
        style={{
          fontFamily: 'var(--font-display)',
          fontWeight: 700,
          fontSize: 'clamp(28px, 4vw, 40px)',
          lineHeight: 1,
          color: color ?? 'var(--ink)',
          marginBottom: 8,
        }}
      >
        {value}
      </div>
      <Eyebrow as="div" tone="muted" size={10}>
        {label}
      </Eyebrow>
    </div>
  );
}

function TechnicalDisclosure({
  diag,
  votes,
}: {
  diag: EnsembleDiagnosticsResponse;
  votes?: SpecialistVotesResponse;
}) {
  const [open, setOpen] = useState(false);
  const dispReleased = diag.fired_dispersion && !diag.wrapper_active;

  return (
    <div style={{ marginTop: 24 }}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="uppercase"
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 10,
          fontWeight: 600,
          letterSpacing: '0.18em',
          color: 'var(--ink-mid)',
          background: 'transparent',
          border: 0,
          padding: 0,
          cursor: 'pointer',
          borderBottom: '1px solid var(--rule)',
          paddingBottom: 2,
        }}
        aria-expanded={open}
      >
        {open ? '— Masquer' : '+ Diagnostic technique'}
      </button>

      {open && (
        <div
          style={{
            marginTop: 16,
            padding: 16,
            background: 'var(--paper-off)',
            border: '1px solid var(--rule)',
            display: 'grid',
            gridTemplateColumns: '1fr 1fr',
            gap: '8px 24px',
            fontSize: 11,
          }}
          className="audit-disclosure-grid"
        >
          <span style={rowLabel}>Soft-gate</span>
          <DataValue>{diag.soft_gate_decision}</DataValue>

          <span style={rowLabel}>Décision finale (wrapped)</span>
          <DataValue color={SIGNAL_HEX[diag.decision_wrapped]}>{diag.decision_wrapped}</DataValue>

          <span style={rowLabel}>Wrapper actif</span>
          <DataValue>{diag.wrapper_active ? 'oui' : 'non'}</DataValue>

          <span style={rowLabel}>Détecteur running accuracy</span>
          <DataValue>{diag.fired_running_acc ? 'fired' : 'pass'}</DataValue>

          <span style={rowLabel}>Détecteur dispersion</span>
          <DataValue>
            {dispReleased ? 'fired · released' : diag.fired_dispersion ? 'fired' : 'pass'}
          </DataValue>

          <span style={rowLabel}>Votes Winter (signed)</span>
          <DataValue>
            {votes?.winter_signed != null
              ? votes.winter_signed >= 0
                ? `+${votes.winter_signed}`
                : `${votes.winter_signed}`
              : '—'}
          </DataValue>

          <span style={rowLabel}>Votes Spring (signed)</span>
          <DataValue>
            {votes?.spring_signed != null
              ? votes.spring_signed >= 0
                ? `+${votes.spring_signed}`
                : `${votes.spring_signed}`
              : '—'}
          </DataValue>

          <span style={rowLabel}>Macro direction</span>
          <DataValue>
            {diag.macro_direction == null
              ? '—'
              : diag.macro_direction > 0
                ? 'bullish'
                : diag.macro_direction < 0
                  ? 'bearish'
                  : 'neutral'}
          </DataValue>

          <span style={rowLabel}>Anomaly score z</span>
          <DataValue>
            {diag.anomaly_score_z != null ? diag.anomaly_score_z.toFixed(2) : '—'}
          </DataValue>

          <span style={rowLabel}>Realized 5d</span>
          <DataValue>
            {diag.realized_return_5d != null ? diag.realized_return_5d.toFixed(4) : '—'}
          </DataValue>
        </div>
      )}

      <style>{`
        @media (max-width: 639px) {
          .audit-disclosure-grid { grid-template-columns: 1fr !important; }
        }
      `}</style>
    </div>
  );
}

export default function DecisionExplainerCard({
  sourceAlgorithm,
  targetDate,
  className,
}: DecisionExplainerCardProps) {
  const isEnsembleDate = sourceAlgorithm === 'ensemble_v1_softgate_wrapper';
  const diagQ = useEnsembleDiagnostics(isEnsembleDate ? targetDate : undefined);
  const votesQ = useSpecialistVotes(isEnsembleDate ? targetDate : undefined);

  if (!isEnsembleDate) return null;

  const is404 = axios.isAxiosError(diagQ.error) && diagQ.error.response?.status === 404;
  if (is404) return null;

  return (
    <section className={className} style={{ padding: '32px 0' }}>
      <SectionHeader numeral="VII" title="Pourquoi cette décision" />

      {diagQ.isLoading ? (
        <div className="flex items-center justify-center min-h-[160px]" style={{ color: 'var(--ink-light)' }}>
          <Loader2 className="h-5 w-5 animate-spin mr-2" />
          <span className="text-sm">Chargement de l'analyse de décision…</span>
        </div>
      ) : diagQ.data ? (
        <DecisionExplanationBody diag={diagQ.data} votes={votesQ.data} />
      ) : (
        <p style={{ fontSize: 13, color: 'var(--ink-light)' }}>
          Aucune analyse de décision disponible pour cette date.
        </p>
      )}
    </section>
  );
}

function DecisionExplanationBody({
  diag,
  votes,
}: {
  diag: EnsembleDiagnosticsResponse;
  votes?: SpecialistVotesResponse;
}) {
  const sentences = buildExplanation(diag);
  const accPct =
    diag.running_acc_5d != null ? `${Math.round(diag.running_acc_5d * 100)}%` : '—';
  const scoreStr =
    diag.net_score >= 0 ? `+${diag.net_score.toFixed(2)}` : diag.net_score.toFixed(2);
  const wrapperReleased = diag.fired_dispersion && !diag.wrapper_active;

  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: 'minmax(0, 1.4fr) minmax(0, 1fr)',
        gap: 40,
        alignItems: 'start',
      }}
      className="explainer-grid"
    >
      {/* Left — editorial prose */}
      <div>
        <Eyebrow as="div" tone="muted" size={10} style={{ marginBottom: 14, letterSpacing: '0.22em' }}>
          Analyse Compass · {diag.algorithm_version.split('_')[0].toUpperCase()}
        </Eyebrow>

        {sentences.map((s, i) => (
          <p
            key={i}
            style={{
              fontFamily: 'var(--font-editorial)',
              fontSize: 16,
              lineHeight: 1.7,
              color: 'var(--ink-dark)',
              marginBottom: 14,
              textAlign: 'justify',
            }}
          >
            {s}
          </p>
        ))}

        <TechnicalDisclosure diag={diag} votes={votes} />
      </div>

      {/* Right — 3 wow-effect metric tiles */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: '1fr',
          gap: 12,
        }}
      >
        <MetricTile
          value={`${diag.n_committed_specialists}/14`}
          label="Consensus spécialistes"
          highlight={diag.n_committed_specialists >= 10}
        />
        <MetricTile
          value={scoreStr}
          label="Conviction (score)"
          color={
            diag.net_score >= 0.249
              ? SIGNAL_HEX.OPEN
              : diag.net_score <= -0.249
                ? SIGNAL_HEX.HEDGE
                : SIGNAL_HEX.MONITOR
          }
        />
        <MetricTile
          value={accPct}
          label="Précision récente (5j)"
          color={
            diag.running_acc_5d != null && diag.running_acc_5d >= 0.6
              ? SIGNAL_HEX.OPEN
              : 'var(--ink)'
          }
        />
        {wrapperReleased && (
          <div
            style={{
              padding: '10px 12px',
              border: '1px dashed var(--color-signal-monitor)',
              background: 'rgba(245, 158, 11, 0.05)',
            }}
          >
            <Eyebrow tone="muted" size={9}>
              Décision validée malgré une divergence détectée
            </Eyebrow>
          </div>
        )}
      </div>

      <style>{`
        @media (max-width: 767px) {
          .explainer-grid { grid-template-columns: 1fr !important; gap: 24px !important; }
        }
      `}</style>
    </div>
  );
}

const rowLabel: React.CSSProperties = {
  fontFamily: 'var(--font-mono)',
  fontSize: 10,
  textTransform: 'uppercase',
  letterSpacing: '0.12em',
  color: 'var(--ink-mid)',
};
