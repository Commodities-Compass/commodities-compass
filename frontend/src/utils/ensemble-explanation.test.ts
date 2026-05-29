import { describe, it, expect } from 'vitest';
import type { EnsembleDiagnosticsResponse } from '@/types/dashboard';
import { buildEnsembleExplanation } from './ensemble-explanation';

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
    const result = buildEnsembleExplanation(
      makeDiag({ decision_wrapped: 'OPEN', net_score: 0.8 }),
    );
    expect(result).toHaveLength(2);
    expect(result[0]).toBeTruthy();
    expect(result[1]).toBeTruthy();
  });

  it("includes the formatted net score with sign in sentence 1", () => {
    const r = buildEnsembleExplanation(makeDiag({ net_score: 0.42 }));
    expect(r[0]).toContain('+0.42');
  });

  it('renders negative scores with explicit minus', () => {
    const r = buildEnsembleExplanation(
      makeDiag({ decision_wrapped: 'HEDGE', net_score: -0.72 }),
    );
    expect(r[0]).toContain('-0.72');
  });

  it("labels conviction as 'forte' at |score| >= 0.6", () => {
    const r = buildEnsembleExplanation(makeDiag({ net_score: 0.6 }));
    expect(r[0].toLowerCase()).toContain('forte');
  });

  it("labels conviction as 'marquée' at |score| in [0.249, 0.6)", () => {
    const r = buildEnsembleExplanation(makeDiag({ net_score: 0.3 }));
    expect(r[0].toLowerCase()).toContain('marquée');
  });

  it("labels conviction as 'mesurée' below 0.249", () => {
    const r = buildEnsembleExplanation(makeDiag({ net_score: 0.1 }));
    expect(r[0].toLowerCase()).toContain('mesurée');
  });

  it('uses the OPEN/HEDGE/MONITOR FR labels', () => {
    expect(
      buildEnsembleExplanation(makeDiag({ decision_wrapped: 'OPEN' }))[0],
    ).toMatch(/acheteuse/);
    expect(
      buildEnsembleExplanation(makeDiag({ decision_wrapped: 'HEDGE' }))[0],
    ).toMatch(/défensive/);
    expect(
      buildEnsembleExplanation(makeDiag({ decision_wrapped: 'MONITOR' }))[0],
    ).toMatch(/attentiste/);
  });

  it('mentions macro porteur when direction > 0', () => {
    const r = buildEnsembleExplanation(makeDiag({ macro_direction: 1 }));
    expect(r[0]).toContain('porteur');
  });

  it('mentions macro défavorable when direction < 0', () => {
    const r = buildEnsembleExplanation(makeDiag({ macro_direction: -1 }));
    expect(r[0]).toContain('défavorable');
  });

  it('omits macro mention when direction is null', () => {
    const r = buildEnsembleExplanation(makeDiag({ macro_direction: null }));
    expect(r[0]).not.toMatch(/porteur|défavorable|neutre/);
  });
});
