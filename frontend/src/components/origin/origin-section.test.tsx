import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, within } from '../../test/test-utils';
import { ENT } from '@/entitlements';
import {
  benchmark,
  benchmarkNotApplicable,
  campaign,
  destinations,
  exporters,
  marketViews,
  transformation,
} from './fixtures';

const held = new Set<string>();
vi.mock('@/contexts/EntitlementsContext', () => ({
  useEntitlements: () => ({
    has: (k: string) => held.has(k),
    hasAny: (ks: string[]) => ks.some((k) => held.has(k)),
    enforced: true,
  }),
}));

const campaignQuery = { data: campaign, isLoading: false, error: null };
const marketQuery = { data: marketViews, isLoading: false, error: null };
const destinationsQuery = { data: destinations, isLoading: false, error: null };
const empty = { data: undefined, isLoading: false, error: null };
vi.mock('@/hooks/useOriginFlows', () => ({
  useOriginCampaign: () => campaignQuery,
  useOriginMarketViews: (_s?: string, enabled = true) => (enabled ? marketQuery : empty),
  useOriginDestinations: (_s?: string, enabled = true) =>
    enabled ? destinationsQuery : empty,
  useOriginExporters: (_s?: string, enabled = true) =>
    enabled ? { data: exporters, isLoading: false, error: null } : empty,
  useOriginBenchmark: (_s?: string, enabled = true) =>
    enabled ? { data: benchmark, isLoading: false, error: null } : empty,
}));

// Imported after the mocks so the component picks them up.
const { default: OriginFlowsCard } = await import('./OriginFlowsCard');
const { default: MarketViewsTab } = await import('./MarketViewsTab');
const { default: ProductMixBar } = await import('./ProductMixBar');
const { default: DestinationsTab } = await import('./DestinationsTab');
const { default: ExportersTab } = await import('./ExportersTab');
const { default: BenchmarkTab } = await import('./BenchmarkTab');

beforeEach(() => held.clear());

describe('Section VI — entitlement-driven composition', () => {
  it('shows both tabs when the tier holds campaign and market views (Coop Premium)', () => {
    held.add(ENT.WATCHAI_CAMPAIGN);
    held.add(ENT.WATCHAI_MARKET_VIEWS);
    render(<OriginFlowsCard />);

    expect(screen.getByRole('tab', { name: /campagne|campaign/i })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: /march|market/i })).toBeInTheDocument();
  });

  it('drops the market tab — and its request — for a tier without the key', () => {
    // Coop Essentiel: the reduced campaign key only. A lone tab would read as a
    // broken control, so the strip is hidden entirely rather than shown with one.
    held.add(ENT.WATCHAI_CAMPAIGN_REDUCED);
    render(<OriginFlowsCard />);

    expect(screen.queryByRole('tab')).not.toBeInTheDocument();
    expect(screen.queryByText(/confrontation statser/i)).not.toBeInTheDocument();
    // The campaign content is still there, just untabbed.
    expect(screen.getByText(/2 087 867|2,087,867/)).toBeInTheDocument();
  });

  it('renders nothing at all when the tier holds no WatchAI key', () => {
    const { container } = render(<OriginFlowsCard />);
    expect(container).toBeEmptyDOMElement();
  });

  it('season selector shows the current season and lists every available one', async () => {
    held.add(ENT.WATCHAI_CAMPAIGN);
    render(<OriginFlowsCard />);

    // Editorial dropdown, not a native <select>: the options exist only once the
    // panel is open, which is what keeps the list inside the brand's own styling.
    const trigger = screen.getByRole('button', { expanded: false });
    expect(trigger).toHaveTextContent('2025-2026');

    fireEvent.click(trigger);
    const options = await screen.findAllByRole('option');
    expect(options.map((o) => o.textContent)).toEqual(['2025-2026', '2024-2025', '2021-2022']);
    expect(options[0]).toHaveAttribute('aria-selected', 'true');
  });
});

describe('Market tab — the states that must not print zeros', () => {
  it('says the balance is unavailable rather than showing 0 for a pre-2020 season', () => {
    render(<MarketViewsTab data={{ ...marketViews, transformation: null }} />);
    expect(screen.getByText(/le bilan mati|balance starts/i)).toBeInTheDocument();
    // The mix survives — only the balance is missing.
    expect(screen.getByText(/FEVES/)).toBeInTheDocument();
    expect(screen.queryByText(/confrontation statser/i)).not.toBeInTheDocument();
  });

  it('raises the flag when apparent outflow exceeds purchases', () => {
    render(
      <MarketViewsTab
        data={{
          ...marketViews,
          transformation: { ...transformation, outflow_exceeds_purchases: true },
        }}
      />
    );
    // 2021-2022 is a real occurrence (108.1 %): a publishable state, not a 500.
    expect(screen.getByText(/sorties|outflow/i)).toBeInTheDocument();
  });
});

describe('Product mix bar', () => {
  it('gives every product a legend entry, so the bar is readable without hovering', () => {
    render(<ProductMixBar lines={marketViews.product_mix} />);
    for (const line of marketViews.product_mix) {
      expect(screen.getByText(new RegExp(line.product_code.replace('_', ' '), 'i'))).toBeVisible();
    }
  });

  it('reveals the tonnage of a segment on hover', () => {
    render(<ProductMixBar lines={marketViews.product_mix} />);
    expect(screen.queryByText(/180 891|180,891/)).not.toBeInTheDocument();

    fireEvent.mouseEnter(screen.getByText(/MASSE/i).closest('span[tabindex]')!);
    expect(screen.getByText(/180 891|180,891/)).toBeInTheDocument();
  });
});

describe('Destinations tab', () => {
  it('ranks outlets, prints the share and the equivalent-period change', () => {
    render(<DestinationsTab data={destinations} />);

    const rows = screen.getAllByRole('row');
    // header + 5 destinations + header + 2 ports
    expect(rows.length).toBeGreaterThanOrEqual(9);
    expect(screen.getByText('PAYS-BAS')).toBeVisible();
    expect(screen.getByText(/409 405|409,405/)).toBeVisible();
    expect(screen.getByText(/\+65,6 %|\+65\.6 %/)).toBeVisible();
  });

  it('shows an em dash rather than a percentage when the baseline is zero', () => {
    render(<DestinationsTab data={destinations} />);
    // COREE DU SUD shipped nothing last season — growth off zero is undefined.
    const row = screen.getByText('COREE DU SUD').closest('tr')!;
    expect(within(row).getByText('—')).toBeInTheDocument();
  });

  it('never names an exporter', () => {
    const { container } = render(<DestinationsTab data={destinations} />);
    expect(container.textContent).not.toMatch(/CARGILL|OLAM|BARRY/i);
  });

  it('is absent from Section VI for a tier without the destinations key', () => {
    held.add(ENT.WATCHAI_CAMPAIGN);
    held.add(ENT.WATCHAI_MARKET_VIEWS);
    render(<OriginFlowsCard />);
    expect(screen.queryByRole('tab', { name: /destination/i })).not.toBeInTheDocument();
  });

  it('appears as a third tab once the tier holds it', () => {
    held.add(ENT.WATCHAI_CAMPAIGN);
    held.add(ENT.WATCHAI_MARKET_VIEWS);
    held.add(ENT.WATCHAI_DESTINATIONS);
    render(<OriginFlowsCard />);
    expect(screen.getByRole('tab', { name: /destination/i })).toBeInTheDocument();
  });
});

describe('Exporters tab — the only view that names an operator', () => {
  it('renders the apparent balance as a flag, not an error, when it is negative', () => {
    render(<ExportersTab data={exporters} />);
    const row = screen.getByText('CYRIAN').closest('tr')!;
    // 58 of 102 real exporters are in this state — treating it as an anomaly
    // would flag more than half the market.
    expect(within(row).getByText(/16 293|16,293/)).toBeInTheDocument();
    expect(within(row).getByText(/−|-/)).toBeInTheDocument();
  });

  it('prints no growth percentage below the 250 t floor', () => {
    render(<ExportersTab data={exporters} />);
    const row = screen.getByText('PETIT NEGOCE').closest('tr')!;
    expect(within(row).getByText('—')).toBeInTheDocument();
    expect(screen.getByText(/250/)).toBeInTheDocument();
  });

  it('marks GEPEX members, since they are the ones who actually grind', () => {
    render(<ExportersTab data={exporters} />);
    const cargill = screen.getByText('CARGILL').closest('tr')!;
    const cyrian = screen.getByText('CYRIAN').closest('tr')!;
    expect(within(cargill).getByText('GEPEX')).toBeInTheDocument();
    expect(within(cyrian).queryByText('GEPEX')).not.toBeInTheDocument();
  });

  it('is absent for a tier holding destinations but not the nominative key', () => {
    held.add(ENT.WATCHAI_CAMPAIGN);
    held.add(ENT.WATCHAI_MARKET_VIEWS);
    held.add(ENT.WATCHAI_DESTINATIONS);
    render(<OriginFlowsCard />);
    expect(screen.queryByRole('tab', { name: /exportateur|exporter/i })).not.toBeInTheDocument();
  });

  it('appears as a fourth tab for Export Premium', () => {
    for (const k of [
      ENT.WATCHAI_CAMPAIGN,
      ENT.WATCHAI_MARKET_VIEWS,
      ENT.WATCHAI_DESTINATIONS,
      ENT.WATCHAI_NOMINATIVE,
    ]) held.add(k);
    render(<OriginFlowsCard />);
    expect(screen.getAllByRole('tab')).toHaveLength(4);
  });
});

describe('Benchmark tab', () => {
  it('states the rank with its denominator, not the rank alone', () => {
    render(<BenchmarkTab data={benchmark} />);
    // "1st of 102" is a different sentence from "1st of 3".
    expect(screen.getByText('1')).toBeVisible();
    expect(screen.getByText(/102/)).toBeVisible();
    expect(screen.getByText(/11,6 %|11\.6 %/)).toBeVisible();
  });

  it('explains "not applicable" instead of rendering a zeroed book', () => {
    render(<BenchmarkTab data={benchmarkNotApplicable} />);
    expect(screen.getByText(/sans objet|not applicable/i)).toBeVisible();
    // Zeroes would say "you shipped nothing", a different and false claim.
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
    expect(screen.queryByText('0')).not.toBeInTheDocument();
  });

  it('shows only the client’s own destinations', () => {
    render(<BenchmarkTab data={benchmark} />);
    expect(screen.getByText('PAYS-BAS')).toBeVisible();
    // No competitor is ever named on this tab.
    expect(screen.queryByText('OLAM')).not.toBeInTheDocument();
  });

  it('is absent for Export Essentiel and present for Export Premium', () => {
    held.add(ENT.WATCHAI_CAMPAIGN);
    held.add(ENT.WATCHAI_MARKET_VIEWS);
    held.add(ENT.WATCHAI_DESTINATIONS);
    const { unmount } = render(<OriginFlowsCard />);
    expect(screen.queryByRole('tab', { name: /position/i })).not.toBeInTheDocument();
    unmount();

    held.add(ENT.WATCHAI_BENCHMARK);
    held.add(ENT.WATCHAI_NOMINATIVE);
    render(<OriginFlowsCard />);
    expect(screen.getByRole('tab', { name: /position/i })).toBeInTheDocument();
    expect(screen.getAllByRole('tab')).toHaveLength(5);
  });
});
