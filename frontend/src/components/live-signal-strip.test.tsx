import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '../test/test-utils';
import { ENT } from '@/entitlements';

const held = new Set<string>();
vi.mock('@/contexts/EntitlementsContext', () => ({
  useEntitlements: () => ({
    has: (k: string) => held.has(k),
    hasAny: (ks: string[]) => ks.some((k) => held.has(k)),
    enforced: true,
  }),
}));

vi.mock('@/hooks/useDashboardDate', () => ({
  useDashboardDate: () => ({ currentDate: '2026-07-31' }),
}));

// Records the `enabled` flag each gated query was called with — the cells being
// absent from the DOM is only half the requirement; the request must not fire
// either, or an unentitled viewer generates a 403 per page load.
const enabledFor: Record<string, boolean | undefined> = {};
vi.mock('@/hooks/useDashboard', () => ({
  usePositionStatus: () => ({
    data: { position: 'OPEN', ytd_performance: 12.4, date: '2026-07-31' },
  }),
  useChartData: () => ({
    data: { data: [{ date: '2026-07-31', close: 4210, volume: 3625, open_interest: 36333 }] },
  }),
  useIndicatorsGrid: (_d?: string, enabled = true) => {
    enabledFor.indicators = enabled;
    return { data: enabled ? { indicators: { rsi: { value: 58.2 } } } : undefined };
  },
  useMacroPanel: (_d?: string, enabled = true) => {
    enabledFor.macro = enabled;
    return { data: enabled ? { fx_dxy_proxy: 1.084 } : undefined };
  },
  usePositioning: (_d?: string, enabled = true) => {
    enabledFor.positioning = enabled;
    return { data: enabled ? { stock_eu_tonnes: 141_200, cot_managed_money_net: 24_100 } : undefined };
  },
}));

const { default: LiveSignalStrip } = await import('./live-signal-strip');

beforeEach(() => {
  held.clear();
  for (const k of Object.keys(enabledFor)) delete enabledFor[k];
});

describe('LiveSignalStrip — per-cell entitlement filtering', () => {
  it('shows the full band for a tier holding technique, positioning and macro', () => {
    held.add(ENT.SECTION_MARKET);
    held.add(ENT.FEATURE_POSITIONING);
    held.add(ENT.FEATURE_MACRO_PANEL);
    render(<LiveSignalStrip />);

    expect(screen.getAllByText('RSI').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Stock EU').length).toBeGreaterThan(0);
    expect(screen.getAllByText('FX DXY').length).toBeGreaterThan(0);
  });

  it('reduces to signal, price, DoD, YTD and session for Coop Essentiel', () => {
    // The tier holds `chrome:ticker` but none of the rows the technical,
    // positioning and macro cells are sold under.
    render(<LiveSignalStrip />);

    for (const kept of ['Signal', 'ICE LDN', 'DoD', 'YTD', 'Session']) {
      expect(screen.getAllByText(kept).length).toBeGreaterThan(0);
    }
    for (const dropped of ['RSI', 'MACD', '%K', 'ATR', 'V/OI', 'Volume', 'OI']) {
      expect(screen.queryByText(dropped)).not.toBeInTheDocument();
    }
    for (const dropped of ['Stock EU', 'Stock US', 'COT MM EU', 'COT MM US', 'FX DXY']) {
      expect(screen.queryByText(dropped)).not.toBeInTheDocument();
    }
  });

  it('skips the gated queries entirely rather than letting them 403', () => {
    render(<LiveSignalStrip />);
    expect(enabledFor).toEqual({ indicators: false, macro: false, positioning: false });
  });

  it('closes the Export Essentiel leak: technique without positioning', () => {
    // Export Essentiel buys "Technique + FX" but not "Positionnement fonds &
    // fondamentaux" — it used to see stocks and COT in the band anyway.
    held.add(ENT.SECTION_MARKET);
    held.add(ENT.FEATURE_MACRO_PANEL);
    render(<LiveSignalStrip />);

    expect(screen.getAllByText('RSI').length).toBeGreaterThan(0);
    expect(screen.queryByText('Stock EU')).not.toBeInTheDocument();
    expect(screen.queryByText('COT MM EU')).not.toBeInTheDocument();
    expect(enabledFor.positioning).toBe(false);
  });
});
