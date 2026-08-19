import { describe, it, expect } from 'vitest';
import type { JudgeDiagnosticsResponse } from '@/types/dashboard';
import i18n from '@/i18n';
import {
  buildJudgeExplanation,
  regimeLabel,
  stanceLabel,
} from './judge-explanation';

// Driven with a French-bound t so the assertions check catalog-sourced output
// rather than the key names.
const t = i18n.getFixedT('fr');
const tEn = i18n.getFixedT('en');
const build = (d: JudgeDiagnosticsResponse) => buildJudgeExplanation(d, t);

// Deliberately partial: each test overrides what it reads. Widening through
// `unknown` states this is a fixture, not a claim that the shape is complete.
function makeDiag(
  overrides: Partial<JudgeDiagnosticsResponse>,
): JudgeDiagnosticsResponse {
  const base = {
    date: '2026-08-17',
    algorithm_version: 'regime',
    regime: 'bull',
    specialist: 'spec_bull',
    prob_up: 0.61,
    base_decision: 'OPEN',
    judge_direction: 'UP',
    judge_stance: 'CONFIRM',
    judge_confidence: 4,
    is_anomaly: false,
    changed: false,
    final_decision: 'OPEN',
    drift_summary: null,
    key_risk: null,
    disconfirming_case: null,
    evidence: [],
    weather_delta: null,
    n_days_window: 5,
    confidence: 4,
    confidence_rationale: 'Météo porteuse, grindings en retrait.',
    running_acc_5d: 0.6,
  } as unknown as JudgeDiagnosticsResponse;
  return { ...base, ...overrides };
}

describe('buildJudgeExplanation', () => {
  it('produces 2 non-empty sentences', () => {
    const r = build(makeDiag({}));
    expect(r).toHaveLength(2);
    expect(r[0]).toBeTruthy();
    expect(r[1]).toBeTruthy();
  });

  it('leads with the detected regime, in business language', () => {
    const r = build(makeDiag({ regime: 'bull' }));
    expect(r[0]).toMatch(/Haussier/i);
    // Never the engine tag.
    expect(r[0]).not.toMatch(/\bbull\b/);
  });

  it('uses the OPEN/HEDGE/MONITOR FR labels of the FINAL decision', () => {
    // The overlay can move the call — the sentence must describe what is
    // served, not the technical call it started from.
    expect(
      build(makeDiag({ base_decision: 'HEDGE', final_decision: 'MONITOR' }))[0],
    ).toMatch(/attentiste/);
    expect(build(makeDiag({ final_decision: 'OPEN' }))[0]).toMatch(/acheteuse/);
    expect(build(makeDiag({ final_decision: 'HEDGE' }))[0]).toMatch(/défensive/);
  });

  it('mentions the published confidence when available', () => {
    const r = build(makeDiag({ confidence: 4 }));
    expect(r[0]).toContain('4/5');
    expect(r[0].toLowerCase()).toContain('confiance');
  });

  it('omits the confidence clause when the brief has not run', () => {
    const r = build(makeDiag({ confidence: null }));
    expect(r[0]).not.toContain('/5');
  });

  it('reports the macro stance when the overlay spoke', () => {
    expect(build(makeDiag({ judge_stance: 'CONFIRM' }))[0]).toMatch(/confirme/i);
    expect(build(makeDiag({ judge_stance: 'CONTRADICT' }))[0]).toMatch(
      /oppose/i,
    );
    expect(build(makeDiag({ judge_stance: 'NEUTRAL' }))[0]).toMatch(/neutre/i);
  });

  it('says the position moved when the overlay revised it', () => {
    const r = build(makeDiag({ judge_stance: 'CONTRADICT', changed: true }));
    expect(r[0]).toMatch(/évoluer/i);
  });

  it('says NOTHING about the macro read when the overlay did not run', () => {
    // Fabricating "the macro read stays neutral" for a session where the LLM
    // leg never ran is the invented-history failure the pipeline refuses.
    const r = build(makeDiag({ judge_stance: null, changed: null }));
    expect(r[0]).not.toMatch(/macro/i);
  });

  it('carries the key risk as sentence 2, not the confidence rationale', () => {
    // The Conviction tile already shows `confidence_rationale` as the caption of
    // the CONFIANCE score, two columns to the left. Repeating it here put the
    // same words twice on one screen — which reads as a bug, not as emphasis.
    const rationale = 'Technique alignée, macro sans opposition.';
    const risk = "Un retour des arrivages ivoiriens invaliderait la lecture.";
    const r = build(makeDiag({ confidence_rationale: rationale, key_risk: risk }));
    expect(r[1]).toBe(risk);
    expect(r[1]).not.toBe(rationale);
  });

  it('falls back to a generic sentence 2 when the judge flagged no risk', () => {
    const r = build(makeDiag({ key_risk: null }));
    expect(r[1]).toBeTruthy();
    expect(r[1]).toMatch(/align/i);
  });

  it('never quotes the machinery, and never the fuse trace', () => {
    const r = build(
      makeDiag({
        judge_stance: 'CONTRADICT',
        changed: true,
        confidence_rationale: 'Macro contre, technique pour.',
      }),
    );
    const joined = r.join(' ').toLowerCase();
    for (const tok of [
      'router',
      'routeur',
      'specialist',
      'spécialiste',
      'prob_up',
      'fuse',
      'abstain',
      'shadow',
      'layer',
      'overlay',
    ]) {
      expect(joined).not.toContain(tok);
    }
  });
});

describe('regimeLabel', () => {
  it('maps every engine tag to a business label in both editions', () => {
    for (const tag of [
      'bull',
      'bear',
      'transition',
      'highvol',
      'oversold',
      'overbought',
    ]) {
      expect(regimeLabel(t, tag)).not.toBe(tag);
      expect(regimeLabel(tEn, tag)).not.toBe(tag);
      // A missing catalog entry surfaces as the raw key — catch that here
      // rather than on a client's screen.
      expect(regimeLabel(t, tag)).not.toContain('signal.regime');
      expect(regimeLabel(tEn, tag)).not.toContain('signal.regime');
    }
  });

  it('shows an unknown tag de-underscored rather than blank', () => {
    // A silent blank would read as "no regime detected" — a different claim.
    expect(regimeLabel(t, 'some_new_regime')).toBe('some new regime');
  });
});

describe('stanceLabel', () => {
  it('flags a revised position ahead of the raw stance', () => {
    const revised = stanceLabel(t, 'CONTRADICT', true);
    const contradicted = stanceLabel(t, 'CONTRADICT', false);
    expect(revised.label).not.toBe(contradicted.label);
  });

  it('renders an absent overlay as its own state, not as neutral', () => {
    const absent = stanceLabel(t, null, null);
    const neutral = stanceLabel(t, 'NEUTRAL', false);
    expect(absent.label).not.toBe(neutral.label);
  });

  it('colours confirm green and contradict red', () => {
    expect(stanceLabel(t, 'CONFIRM', false).color).toContain('signal-open');
    expect(stanceLabel(t, 'CONTRADICT', false).color).toContain('signal-hedge');
  });
});
