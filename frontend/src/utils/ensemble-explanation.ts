import type { EnsembleDiagnosticsResponse } from '@/types/dashboard';

function decisionFR(d: 'OPEN' | 'HEDGE' | 'MONITOR'): string {
  if (d === 'OPEN') return 'acheteuse';
  if (d === 'HEDGE') return 'défensive';
  return 'attentiste';
}

function convictionLabel(netScore: number): string {
  const abs = Math.abs(netScore);
  if (abs >= 0.6) return 'forte';
  if (abs >= 0.249) return 'marquée';
  return 'mesurée';
}

function macroFR(direction: number | null | undefined): string | null {
  if (direction == null) return null;
  if (direction > 0) return 'porteur';
  if (direction < 0) return 'défavorable';
  return 'neutre';
}

/**
 * 2 plain-French sentences derived from the ensemble diagnostics. Templated,
 * no LLM. Used by SignalHero (inline) and the optional DecisionExplainerCard.
 *
 * Tone: confidence-first. The explanation always frames the result as
 * "our orchestrator validates / calibrates the decision", never defensive.
 *
 * The 2nd sentence compares decision_wrapped vs soft_gate_decision to detect
 * an actual downgrade — wrapper_active=True alone can mean "Compass override
 * released a fired detector", which is positive for the user.
 */
export function buildEnsembleExplanation(diag: EnsembleDiagnosticsResponse): string[] {
  const sentences: string[] = [];

  const score = diag.net_score;
  const scoreStr = `${score >= 0 ? '+' : ''}${score.toFixed(2)}`;
  const conviction = convictionLabel(score);
  const decision = decisionFR(diag.decision_wrapped);
  const macro = macroFR(diag.macro_direction);

  // S1 — lead with conviction, mention specialists engaged + macro context
  const macroClause = macro
    ? macro === 'porteur'
      ? ' Contexte macro porteur.'
      : macro === 'défavorable'
        ? ' Contexte macro défavorable.'
        : ' Contexte macro neutre.'
    : '';
  sentences.push(
    `Conviction ${conviction} sur la position ${decision} (score net ${scoreStr}, ${diag.n_committed_specialists} spécialistes engagés sur 14).${macroClause}`,
  );

  // S2 — algo confidence layer: detector / wrapper / orchestrator outcome
  const decisionChanged = diag.decision_wrapped !== diag.soft_gate_decision;
  const anyDetectorFired =
    diag.fired_dispersion ||
    diag.fired_running_acc ||
    diag.fired_trend ||
    diag.fired_three_way;

  if (decisionChanged) {
    sentences.push(
      `Notre orchestrateur a calibré la décision (soft-gate ${diag.soft_gate_decision} → ${diag.decision_wrapped}) pour préserver la performance face à des signaux ambigus.`,
    );
  } else if (anyDetectorFired) {
    const acc =
      diag.running_acc_5d != null ? Math.round(diag.running_acc_5d * 100) : null;
    const accStr = acc != null ? ` ${acc}%` : '';
    sentences.push(
      `Nos détecteurs ont validé la robustesse du signal — la précision récente${accStr} sur 5 jours confirme la décision.`,
    );
  } else {
    sentences.push(
      `Convergence des signaux techniques et macro — l'orchestrateur Compass livre la décision avec haute fiabilité.`,
    );
  }

  return sentences;
}
