import type { TFunction } from 'i18next';

import type { JudgeDiagnosticsResponse } from '@/types/dashboard';

/**
 * Why-this-decision explanation for the regime+judge track.
 *
 * Successor of `buildEnsembleExplanation`, under the same editorial rules and a
 * different subject: the ensemble explained a panel converging on a verdict,
 * regime+judge explains a detected market regime and what the macro read did
 * with the technical call.
 *
 * Editorial rules (aligned with the brief redaction policy):
 *   - never name the machinery: no "router", no "specialist", no "prob_up", no
 *     "fuse". Those live in the audit DB, not in a sentence a client reads.
 *   - never surface `rationale` — it is not even in the API payload; the
 *     user-facing sentence is `confidence_rationale`, written natively per
 *     language by cc-regime-brief.
 *
 * i18n: pure util (no React context), so the caller threads its `t` in. Every
 * template lives under the `signal.*` catalog.
 * Returns 2 short sentences for the "why this decision" sidebar.
 */
function decisionKey(d: 'OPEN' | 'HEDGE' | 'MONITOR'): string {
  if (d === 'OPEN') return 'open';
  if (d === 'HEDGE') return 'hedge';
  return 'monitor';
}

function confidenceKey(score: number): string {
  if (score >= 5) return 'very_high';
  if (score >= 4) return 'high';
  if (score >= 3) return 'moderate';
  if (score >= 2) return 'measured';
  return 'low';
}

/**
 * Business label for an internal regime tag.
 *
 * The engine tags (bull, highvol…) are vocabulary, not language. Deliberately
 * shorter than the brief's phrasing ("tendance haussière établie"): this one
 * lands in a nowrap tile, the brief's is read aloud. Two registers, one source
 * of truth for the mapping in each medium.
 */
export function regimeLabel(t: TFunction, regime: string): string {
  const known = [
    'bull',
    'bear',
    'transition',
    'highvol',
    'oversold',
    'overbought',
  ];
  if (known.includes(regime)) return t(`signal.regime.${regime}`);
  // An unrecognised tag is shown de-underscored rather than hidden: a silent
  // blank would read as "no regime detected", which is a different claim.
  return regime.replace(/_/g, ' ');
}

/** How the macro overlay arbitrated, in business language. */
export function stanceLabel(
  t: TFunction,
  stance: JudgeDiagnosticsResponse['judge_stance'],
  changed: boolean | null,
): { label: string; color: string } {
  if (stance == null)
    return { label: t('signal.stance.absent'), color: 'var(--ink-light)' };
  if (changed) return { label: t('signal.stance.revised'), color: 'var(--color-signal-monitor)' };
  if (stance === 'CONFIRM')
    return { label: t('signal.stance.confirm'), color: 'var(--color-signal-open)' };
  if (stance === 'CONTRADICT')
    return { label: t('signal.stance.contradict'), color: 'var(--color-signal-hedge)' };
  return { label: t('signal.stance.neutral'), color: 'var(--ink-mid)' };
}

export function buildJudgeExplanation(
  diag: JudgeDiagnosticsResponse,
  t: TFunction,
): string[] {
  const sentences: string[] = [];
  const decision = t(`signal.decision.${decisionKey(diag.final_decision)}`);
  const regime = regimeLabel(t, diag.regime);

  // The overlay clause only appears when the overlay actually spoke. Printing
  // "the macro read confirms" for a session where the LLM leg never ran would
  // be the fabricated-history failure the pipeline exists to refuse.
  const overlayClause =
    diag.judge_stance == null
      ? ''
      : diag.changed
        ? ` ${t('signal.judge_overlay_revised')}`
        : ` ${t(`signal.judge_overlay_${diag.judge_stance.toLowerCase()}`)}`;

  if (diag.confidence != null) {
    sentences.push(
      t('signal.judge_explanation.with_confidence', {
        regime,
        decision,
        confidence: t(`signal.confidence.${confidenceKey(diag.confidence)}`),
        score: diag.confidence,
        overlayClause,
      }),
    );
  } else {
    sentences.push(
      t('signal.judge_explanation.without_confidence', {
        regime,
        decision,
        overlayClause,
      }),
    );
  }

  // The second sentence used to repeat `confidence_rationale` verbatim — which
  // the Conviction tile already shows as the caption of the CONFIANCE score, two
  // columns to the left. Same words twice on one screen reads as a bug, not as
  // emphasis. The panel now carries what the tile cannot: the risk the judge
  // itself flagged.
  const risk = (diag.key_risk ?? '').trim();
  sentences.push(risk.length > 0 ? risk : t('signal.judge_rationale_fallback'));

  return sentences;
}
