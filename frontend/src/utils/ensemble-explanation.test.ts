import { describe, it, expect } from 'vitest';
import type { EnsembleDiagnosticsResponse } from '@/types/dashboard';
import i18n from '@/i18n';
import { buildEnsembleExplanation } from './ensemble-explanation';

// The util now renders through i18next; drive it with a French-bound t so these
// assertions keep checking the (catalog-sourced) French output.
const t = i18n.getFixedT('fr');
const build = (d: EnsembleDiagnosticsResponse) => buildEnsembleExplanation(d, t);

// Minimal diagnostics scaffold — every test overrides the fields it cares
// about. Using Partial avoids hard-coding fields we don't read.
function makeDiag(
  overrides: Partial<EnsembleDiagnosticsResponse>,
): EnsembleDiagnosticsResponse {
  const base: EnsembleDiagnosticsResponse = {
    date: '2026-05-29',
    decision_wrapped: 'OPEN',
    soft_gate_decision: 'OPEN',
    net_score: 0.5,
    n_committed_specialists: 10,
    wrapper_active: false,
    confidence: 4,
    confidence_rationale: 'Tech + macro alignés, stocks neutres, climat NUANCE.',
    macro_direction: 0,
    macro_surprise: null,
    macro_half_life_days: null,
    running_acc_5d: null,
    source_algorithm: 'ensemble_v1_softgate_wrapper',
  } as EnsembleDiagnosticsResponse;
  return { ...base, ...overrides };
}

describe('buildEnsembleExplanation', () => {
  it('produces 2 non-empty sentences for a clean OPEN signal', () => {
    const result = build(
      makeDiag({ decision_wrapped: 'OPEN', n_committed_specialists: 9 }),
    );
    expect(result).toHaveLength(2);
    expect(result[0]).toBeTruthy();
    expect(result[1]).toBeTruthy();
  });

  it('leads sentence 1 with the consensus framing (no raw net_score)', () => {
    const r = build(makeDiag({ n_committed_specialists: 12 }));
    expect(r[0]).toMatch(/consensus/i);
    expect(r[0]).toMatch(/12 lectures engagées/);
    expect(r[0]).not.toMatch(/score net/);
    expect(r[0]).not.toMatch(/net_score/);
  });

  it('mentions the LLM confidence score when available', () => {
    const r = build(makeDiag({ confidence: 4 }));
    expect(r[0]).toContain('4/5');
    expect(r[0].toLowerCase()).toContain('confiance');
  });

  it("uses 'large consensus' label at n_committed >= 10", () => {
    const r = build(makeDiag({ n_committed_specialists: 12 }));
    expect(r[0].toLowerCase()).toContain('large consensus');
  });

  it("uses 'consensus solide' at 7 <= n_committed < 10", () => {
    const r = build(makeDiag({ n_committed_specialists: 8 }));
    expect(r[0].toLowerCase()).toContain('consensus solide');
  });

  it("uses 'consensus fragile' at n_committed < 4", () => {
    const r = build(makeDiag({ n_committed_specialists: 3 }));
    expect(r[0].toLowerCase()).toContain('consensus fragile');
  });

  it('uses the OPEN/HEDGE/MONITOR FR labels', () => {
    expect(build(makeDiag({ decision_wrapped: 'OPEN' }))[0]).toMatch(/acheteuse/);
    expect(build(makeDiag({ decision_wrapped: 'HEDGE' }))[0]).toMatch(/défensive/);
    expect(build(makeDiag({ decision_wrapped: 'MONITOR' }))[0]).toMatch(/attentiste/);
  });

  it('mentions macro porteur when direction > 0', () => {
    const r = build(makeDiag({ macro_direction: 1 }));
    expect(r[0]).toContain('porteur');
  });

  it('mentions macro défavorable when direction < 0', () => {
    const r = build(makeDiag({ macro_direction: -1 }));
    expect(r[0]).toContain('défavorable');
  });

  it('omits macro mention when direction is null', () => {
    const r = build(makeDiag({ macro_direction: null }));
    expect(r[0]).not.toMatch(/porteur|défavorable|neutre/);
  });

  it('returns the rationale verbatim as sentence 2 when present', () => {
    const rationale = 'Macro soutient, technique mixte, sentiment NUANCE.';
    const r = build(makeDiag({ confidence_rationale: rationale }));
    expect(r[1]).toBe(rationale);
  });

  it('falls back to a generic sentence 2 when rationale is empty', () => {
    const r = build(makeDiag({ confidence_rationale: null }));
    expect(r[1]).toMatch(/[Cc]onvergence/);
  });

  it('never quotes engine internals (no soft-gate, wrapper, orchestrateur, net_score)', () => {
    const r = build(
      makeDiag({
        decision_wrapped: 'HEDGE',
        soft_gate_decision: 'OPEN',
        wrapper_active: true,
        confidence_rationale: 'Tech baissier, macro défavorable.',
      }),
    );
    const joined = r.join(' ').toLowerCase();
    for (const tok of [
      'soft-gate',
      'wrapper',
      'orchestrateur',
      'net_score',
      'net score',
      'détecteur',
      'cluster winter',
      'cluster spring',
    ]) {
      expect(joined).not.toContain(tok);
    }
  });
});
