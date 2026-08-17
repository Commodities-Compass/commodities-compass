import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, within } from '../../test/test-utils';
import { ENT } from '@/entitlements';
import { campaign, marketViews, transformation } from './fixtures';

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
vi.mock('@/hooks/useOriginFlows', () => ({
  useOriginCampaign: () => campaignQuery,
  useOriginMarketViews: (_s?: string, enabled = true) =>
    enabled ? marketQuery : { data: undefined, isLoading: false, error: null },
}));

// Imported after the mocks so the component picks them up.
const { default: OriginFlowsCard } = await import('./OriginFlowsCard');
const { default: MarketViewsTab } = await import('./MarketViewsTab');
const { default: ProductMixBar } = await import('./ProductMixBar');

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

  it('season selector is reachable and lists every available season', () => {
    held.add(ENT.WATCHAI_CAMPAIGN);
    render(<OriginFlowsCard />);
    const select = screen.getByRole('combobox');
    expect(within(select).getAllByRole('option')).toHaveLength(3);
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
