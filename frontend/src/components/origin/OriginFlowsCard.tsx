import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Loader2 } from 'lucide-react';
import SectionHeader from '@/components/section-header';
import EditorialTabs, { type EditorialTab } from '@/components/editorial-tabs';
import { Eyebrow } from '@/components/editorial';
import { ENT } from '@/entitlements';
import { useEntitlements } from '@/contexts/EntitlementsContext';
import {
  useOriginCampaign,
  useOriginDestinations,
  useOriginBenchmark,
  useOriginExporters,
  useOriginMarketViews,
} from '@/hooks/useOriginFlows';
import CampaignTab from './CampaignTab';
import DestinationsTab from './DestinationsTab';
import BenchmarkTab from './BenchmarkTab';
import ExportersTab from './ExportersTab';
import MarketViewsTab from './MarketViewsTab';
import OriginPeriodSelector from './OriginPeriodSelector';

/**
 * Section VI — physical market. Matrix block ②, Côte d'Ivoire physical flows.
 *
 * One tab per entitlement key held, and the tab strip is hidden when only one
 * survives: Coop Essentiel holds `campaign_monthly:reduced` and nothing else, so
 * showing a lone tab would read as a broken control rather than a deliberate
 * single view.
 *
 * The season selector is local to this section and is **not** wired to
 * `DashboardDateContext` — origin data is monthly, the rest of the dashboard is
 * daily, and mixing the two grains is the collision the timeseries-uniqueness
 * rule exists to prevent.
 */
export default function OriginFlowsCard({ className }: { className?: string }) {
  const { t } = useTranslation();
  const { has, hasAny } = useEntitlements();
  const canSeeMarketViews = has(ENT.WATCHAI_MARKET_VIEWS);
  const canSeeDestinations = has(ENT.WATCHAI_DESTINATIONS);
  const canSeeExporters = has(ENT.WATCHAI_NOMINATIVE);
  const canSeeBenchmark = has(ENT.WATCHAI_BENCHMARK);
  const canSeeCampaign = hasAny([ENT.WATCHAI_CAMPAIGN, ENT.WATCHAI_CAMPAIGN_REDUCED]);

  const [season, setSeason] = useState<string | undefined>(undefined);

  const campaign = useOriginCampaign(season);
  const marketViews = useOriginMarketViews(season, canSeeMarketViews);
  const destinations = useOriginDestinations(season, canSeeDestinations);
  const exporters = useOriginExporters(season, canSeeExporters);
  const benchmark = useOriginBenchmark(season, canSeeBenchmark);

  // Either payload can drive the selector — both carry the season list and the
  // stamp. Prefer whichever has landed.
  const meta = campaign.data ?? marketViews.data ?? destinations.data ?? exporters.data ?? benchmark.data;
  const isLoading =
    campaign.isLoading ||
    (canSeeMarketViews && marketViews.isLoading) ||
    (canSeeDestinations && destinations.isLoading) ||
    (canSeeExporters && exporters.isLoading) ||
    (canSeeBenchmark && benchmark.isLoading);
  const failed = (!campaign.data && campaign.error) || (canSeeMarketViews && !marketViews.data && marketViews.error);

  if (isLoading) {
    return (
      <section className={className} style={{ padding: '24px 0' }}>
        <SectionHeader numeral="VI" title={t('origin.section_title')} />
        <div
          className="flex items-center justify-center py-12"
          style={{ color: 'var(--ink-light)' }}
        >
          <Loader2 className="h-5 w-5 animate-spin mr-2" />
          <span className="text-sm">{t('origin.loading')}</span>
        </div>
      </section>
    );
  }

  if (failed || !meta) {
    // 503 until the manual ingestion has run — an operational state, so say so
    // plainly instead of implying the data is empty.
    return (
      <section className={className} style={{ padding: '24px 0' }}>
        <SectionHeader numeral="VI" title={t('origin.section_title')} />
        <Eyebrow tone="subtle" size={10} tracking="0.14em">
          {t('origin.unavailable')}
        </Eyebrow>
      </section>
    );
  }

  const tabs: EditorialTab[] = [];
  const panels: Record<string, React.ReactNode> = {};
  if (canSeeCampaign && campaign.data) {
    tabs.push({ id: 'campaign', label: t('origin.tab_campaign') });
    panels.campaign = <CampaignTab data={campaign.data} />;
  }
  if (canSeeMarketViews && marketViews.data) {
    tabs.push({ id: 'market', label: t('origin.tab_market') });
    panels.market = <MarketViewsTab data={marketViews.data} />;
  }
  if (canSeeDestinations && destinations.data) {
    tabs.push({ id: 'destinations', label: t('origin.tab_destinations') });
    panels.destinations = <DestinationsTab data={destinations.data} />;
  }
  // Benchmark before the nominative list: a client asks "where am I" before
  // "who else is there", and the matrix sells them at the same tier anyway.
  if (canSeeBenchmark && benchmark.data) {
    tabs.push({ id: 'benchmark', label: t('origin.tab_benchmark') });
    panels.benchmark = <BenchmarkTab data={benchmark.data} />;
  }
  if (canSeeExporters && exporters.data) {
    tabs.push({ id: 'exporters', label: t('origin.tab_exporters') });
    panels.exporters = <ExportersTab data={exporters.data} />;
  }

  if (tabs.length === 0) return null;

  return (
    <section className={className} style={{ padding: '24px 0' }}>
      {/* The season lives in the header rather than above the tabs: it scopes the
          whole section, tabs only switch the view of it. Putting it in the rule
          also stops it reading as a third tab. */}
      <SectionHeader
        numeral="VI"
        title={t('origin.section_title')}
        aside={
          <OriginPeriodSelector
            seasons={meta.available_seasons}
            value={season ?? meta.season}
            onChange={setSeason}
            dataAsOf={meta.data_as_of}
          />
        }
      />

      {tabs.length === 1 ? (
        panels[tabs[0].id]
      ) : (
        <EditorialTabs tabs={tabs} panels={panels} defaultActiveId="campaign" />
      )}
    </section>
  );
}
