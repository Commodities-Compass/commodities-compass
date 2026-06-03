import type { EnsembleDiagnosticsResponse } from '@/types/dashboard';

/**
 * Why-this-decision explanation, derived templated from the ensemble row.
 * Mirrors the new conviction breakdown order : Consensus → Confiance → Direction.
 *
 * Editorial rules (aligned with the brief redaction policy) :
 *   - never quote engine internals : no `net_score`, no `soft-gate`, no
 *     `wrapper`, no `orchestrateur`, no `running_acc_5d`. Those live in the
 *     audit DB, not in the user-facing summary.
 *   - never name the panel size explicitly ("14 specialists") — speak in
 *     terms of lectures engagées vs en retrait.
 *   - lead with consensus (how many lectures engaged), then confidence (the
 *     LLM rubric verdict + per-pillar rationale), then macro direction.
 *
 * Returns 2 short sentences. Caller (SignalHero) places them in the
 * "Pourquoi cette décision" sidebar.
 */
function decisionFR(d: 'OPEN' | 'HEDGE' | 'MONITOR'): string {
  if (d === 'OPEN') return 'acheteuse';
  if (d === 'HEDGE') return 'défensive';
  return 'attentiste';
}

function consensusLabel(n: number): string {
  if (n >= 10) return 'large consensus';
  if (n >= 7) return 'consensus solide';
  if (n >= 4) return 'consensus partiel';
  return 'consensus fragile';
}

function confidenceLabel(score: number): string {
  if (score >= 5) return 'très forte';
  if (score >= 4) return 'forte';
  if (score >= 3) return 'modérée';
  if (score >= 2) return 'mesurée';
  return 'faible';
}

function macroFR(direction: number | null | undefined): string | null {
  if (direction == null) return null;
  if (direction > 0) return 'porteur';
  if (direction < 0) return 'défavorable';
  return 'neutre';
}

export function buildEnsembleExplanation(
  diag: EnsembleDiagnosticsResponse,
): string[] {
  const sentences: string[] = [];
  const decision = decisionFR(diag.decision_wrapped);

  // S1 — Consensus + Confidence : lead with how many lectures engaged and
  // how strong the verdict is. No raw score, no panel size as a number
  // mentioned explicitly beyond "X engagées".
  const consensus = consensusLabel(diag.n_committed_specialists);
  const macro = macroFR(diag.macro_direction);
  const macroClause =
    macro != null
      ? macro === 'porteur'
        ? ' Contexte macro porteur.'
        : macro === 'défavorable'
          ? ' Contexte macro défavorable.'
          : ' Contexte macro neutre.'
      : '';

  if (diag.confidence != null) {
    const conf = confidenceLabel(diag.confidence);
    sentences.push(
      `${capitalize(consensus)} sur la position ${decision} — ${diag.n_committed_specialists} lectures engagées, confiance ${conf} (${diag.confidence}/5).${macroClause}`,
    );
  } else {
    sentences.push(
      `${capitalize(consensus)} sur la position ${decision} — ${diag.n_committed_specialists} lectures engagées.${macroClause}`,
    );
  }

  // S2 — Per-pillar rationale when available, else a generic convergence
  // statement. Never mentions wrapper / orchestrateur / detectors.
  const rationale = (diag.confidence_rationale ?? '').trim();
  if (rationale.length > 0) {
    sentences.push(rationale);
  } else {
    sentences.push(
      `Convergence des signaux techniques et fondamentaux sur la lecture du jour.`,
    );
  }

  return sentences;
}

function capitalize(s: string): string {
  if (!s) return s;
  return s.charAt(0).toUpperCase() + s.slice(1);
}
