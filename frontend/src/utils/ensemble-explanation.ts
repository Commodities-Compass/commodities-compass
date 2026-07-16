import type { TFunction } from 'i18next';

import type { EnsembleDiagnosticsResponse } from '@/types/dashboard';

/**
 * Why-this-decision explanation, derived templated from the ensemble row.
 * Mirrors the conviction breakdown order: Consensus → Confidence → Direction.
 *
 * Editorial rules (aligned with the brief redaction policy):
 *   - never quote engine internals: no `net_score`, no `soft-gate`, no
 *     `wrapper`, no `orchestrateur`, no `running_acc_5d`. Those live in the
 *     audit DB, not in the user-facing summary.
 *   - never name the panel size explicitly ("14 specialists") — speak in
 *     terms of engaged vs sidelined readings.
 *
 * i18n: pure util (no React context), so the caller (SignalHero) threads its
 * `t` in. Every label + sentence template lives under the `signal.*` catalog.
 * Returns 2 short sentences for the "why this decision" sidebar.
 */
function decisionKey(d: 'OPEN' | 'HEDGE' | 'MONITOR'): string {
  if (d === 'OPEN') return 'open';
  if (d === 'HEDGE') return 'hedge';
  return 'monitor';
}

function consensusKey(n: number): string {
  if (n >= 10) return 'large';
  if (n >= 7) return 'solid';
  if (n >= 4) return 'partial';
  return 'weak';
}

function confidenceKey(score: number): string {
  if (score >= 5) return 'very_high';
  if (score >= 4) return 'high';
  if (score >= 3) return 'moderate';
  if (score >= 2) return 'measured';
  return 'low';
}

function macroKey(direction: number | null | undefined): string | null {
  if (direction == null) return null;
  if (direction > 0) return 'positive';
  if (direction < 0) return 'negative';
  return 'neutral';
}

export function buildEnsembleExplanation(
  diag: EnsembleDiagnosticsResponse,
  t: TFunction,
): string[] {
  const sentences: string[] = [];
  const decision = t(`signal.decision.${decisionKey(diag.decision_wrapped)}`);
  const consensus = capitalize(
    t(`signal.consensus.${consensusKey(diag.n_committed_specialists)}`),
  );
  const mk = macroKey(diag.macro_direction);
  const macroClause = mk ? ` ${t(`signal.ensemble_macro_${mk}`)}` : '';

  if (diag.confidence != null) {
    sentences.push(
      t('signal.explanation.with_confidence', {
        consensus,
        decision,
        n: diag.n_committed_specialists,
        confidence: t(`signal.confidence.${confidenceKey(diag.confidence)}`),
        score: diag.confidence,
        macroClause,
      }),
    );
  } else {
    sentences.push(
      t('signal.explanation.without_confidence', {
        consensus,
        decision,
        n: diag.n_committed_specialists,
        macroClause,
      }),
    );
  }

  const rationale = (diag.confidence_rationale ?? '').trim();
  sentences.push(
    rationale.length > 0 ? rationale : t('signal.convergence_fallback'),
  );

  return sentences;
}

function capitalize(s: string): string {
  if (!s) return s;
  return s.charAt(0).toUpperCase() + s.slice(1);
}
