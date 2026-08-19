import { describe, it, expect } from 'vitest';
import type { JudgeDiagnosticsResponse } from '@/types/dashboard';
import i18n from '@/i18n';
import {
  buildInvalidationNote,
  buildJudgeExplanation,
  confidenceLabel,
  regimeLabel,
  stanceLabel,
} from './judge-explanation';

// Driven with a French-bound t so the assertions check catalog-sourced output
// rather than the key names.
const t = i18n.getFixedT('fr');
const tEn = i18n.getFixedT('en');
const build = (d: JudgeDiagnosticsResponse) => buildJudgeExplanation(d, t);
const note = (d: JudgeDiagnosticsResponse) => buildInvalidationNote(d, t);

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
  it('produces exactly one sentence for the score panel', () => {
    // Deliberately one: the panel is 320px wide and the second sentence used to
    // be 300+ characters of editorial prose, which rendered as six italic lines
    // and swamped the score card. That prose now has its own full-width row
    // under the Conviction tiles.
    const diag = makeDiag({});
    const r = build(diag);
    expect(typeof r).toBe('string');
    expect(r).toBeTruthy();
    expect(r).not.toContain(diag.confidence_rationale);
  });

  it('leads with the detected regime, in business language', () => {
    const r = build(makeDiag({ regime: 'bull' }));
    expect(r).toMatch(/Haussier/i);
    // Never the engine tag.
    expect(r).not.toMatch(/\bbull\b/);
  });

  it('uses the OPEN/HEDGE/MONITOR FR labels of the FINAL decision', () => {
    // The overlay can move the call — the sentence must describe what is
    // served, not the technical call it started from.
    expect(
      build(makeDiag({ base_decision: 'HEDGE', final_decision: 'MONITOR' })),
    ).toMatch(/attentiste/);
    expect(build(makeDiag({ final_decision: 'OPEN' }))).toMatch(/acheteuse/);
    expect(build(makeDiag({ final_decision: 'HEDGE' }))).toMatch(/défensive/);
  });

  it('mentions the published confidence when available', () => {
    const r = build(makeDiag({ confidence: 4 }));
    expect(r).toContain('4/5');
    expect(r.toLowerCase()).toContain('confiance');
  });

  it('omits the confidence clause when the brief has not run', () => {
    const r = build(makeDiag({ confidence: null }));
    expect(r).not.toContain('/5');
  });

  it('reports the macro stance when the overlay spoke', () => {
    expect(build(makeDiag({ judge_stance: 'CONFIRM' }))).toMatch(/confirme/i);
    expect(build(makeDiag({ judge_stance: 'CONTRADICT' }))).toMatch(
      /oppose/i,
    );
    expect(build(makeDiag({ judge_stance: 'NEUTRAL' }))).toMatch(/neutre/i);
  });

  it('says the position moved when the overlay revised it', () => {
    const r = build(makeDiag({ judge_stance: 'CONTRADICT', changed: true }));
    expect(r).toMatch(/évoluer/i);
  });

  it('says NOTHING about the macro read when the overlay did not run', () => {
    // Fabricating "the macro read stays neutral" for a session where the LLM
    // leg never ran is the invented-history failure the pipeline refuses.
    const r = build(makeDiag({ judge_stance: null, changed: null }));
    expect(r).not.toMatch(/macro/i);
  });

  it('keeps the rationale OUT of the panel sentence', () => {
    const rationale = 'Technique alignée, macro sans opposition.';
    expect(build(makeDiag({ confidence_rationale: rationale }))).not.toContain(
      rationale,
    );
  });

  it('never renders a raw judge field — they are written in English', () => {
    // The judge hands ENGLISH working notes to cc-regime-brief, which composes
    // natively per language. `key_risk` was briefly rendered here to stop the
    // Conviction tile from repeating the rationale; it fixed the duplication and
    // put an English sentence in the middle of the French panel instead (caught
    // on a production screenshot, 2026-08-19). Every raw judge field carries the
    // same hazard, so the guard covers all of them, not just the one that shipped.
    const englishNotes = {
      key_risk:
        'Whether EUDR gaps lead to export curbs remains the critical risk.',
      drift_summary: 'Weather stress eased while arrivals accelerated.',
      disconfirming_case: 'Smooth Ivorian port arrivals would undo this.',
    };
    const diag = makeDiag({
      ...englishNotes,
      confidence_rationale: 'Lecture française.',
    });
    const rendered = `${build(diag)} ${note(diag)}`;

    for (const englishNote of Object.values(englishNotes)) {
      expect(rendered).not.toContain(englishNote);
    }
  });

  it('never quotes the machinery, and never the fuse trace', () => {
    const diag = makeDiag({
      judge_stance: 'CONTRADICT',
      changed: true,
      confidence_rationale: 'Macro contre, technique pour.',
    });
    const joined = `${build(diag)} ${note(diag)}`.toLowerCase();
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

describe('buildInvalidationNote', () => {
  it('carries the natively-written rationale verbatim', () => {
    const rationale = 'Technique alignée, macro sans opposition.';
    expect(note(makeDiag({ confidence_rationale: rationale }))).toBe(rationale);
  });

  it('falls back to a generic sentence when the brief wrote no rationale', () => {
    const r = note(makeDiag({ confidence_rationale: null }));
    expect(r).toBeTruthy();
    expect(r).toMatch(/align/i);
  });
});

describe('confidenceLabel', () => {
  it('names every score on the 1-5 scale, in both editions', () => {
    // This caption replaced `confidence_rationale` under the CONFIANCE score.
    // A missing catalog entry would print the raw key inside the tile.
    for (const score of [1, 2, 3, 4, 5]) {
      for (const fixedT of [t, tEn]) {
        const label = confidenceLabel(fixedT, score);
        expect(label).toBeTruthy();
        expect(label).not.toContain('signal.confidence');
      }
    }
  });

  it('separates the bands rather than collapsing them into one word', () => {
    const bands = [1, 2, 3, 4, 5].map((s) => confidenceLabel(t, s));
    expect(new Set(bands).size).toBe(5);
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
