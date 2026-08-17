import { useState } from 'react';
import MarketAnalysis from '@/components/market-analysis';
import NewsCard from '@/components/news-card';
import SignalHero from '@/components/signal-hero';
import PodcastPlayer from '@/components/podcast-player';
import PriceChart from '@/components/price-chart';
import WeatherUpdateCard from '@/components/weather-update-card';
import OriginFlowsCard from '@/components/origin/OriginFlowsCard';
import { DashboardErrorBoundary } from '@/components/DashboardErrorBoundary';
import { useDashboardDate } from '@/hooks/useDashboardDate';
import { Entitled, useEntitlements } from '@/contexts/EntitlementsContext';
import { ENT } from '@/entitlements';

export default function DashboardPage() {
  const { currentDate } = useDashboardDate();
  const [selectedMetric, setSelectedMetric] = useState('close');
  const { has } = useEntitlements();

  // Reduced "résumé hebdo" weather when the client holds only the summary key.
  const weatherSummary =
    has(ENT.SECTION_WEATHER_SUMMARY) && !has(ENT.SECTION_WEATHER);

  return (
    <div>
      <Entitled anyOf={[ENT.SECTION_SIGNAL]}>
        <DashboardErrorBoundary>
          <SignalHero targetDate={currentDate} />
        </DashboardErrorBoundary>
      </Entitled>

      <Entitled anyOf={[ENT.SECTION_PODCAST]}>
        <DashboardErrorBoundary>
          <PodcastPlayer audioDate={currentDate} />
        </DashboardErrorBoundary>
      </Entitled>

      <Entitled
        anyOf={[
          ENT.SECTION_MARKET,
          ENT.FEATURE_MACRO_PANEL,
          ENT.FEATURE_POSITIONING,
          ENT.FEATURE_FARMGATE,
        ]}
      >
        <DashboardErrorBoundary>
          <MarketAnalysis targetDate={currentDate} />
        </DashboardErrorBoundary>
      </Entitled>

      <Entitled anyOf={[ENT.SECTION_CHART]}>
        <DashboardErrorBoundary>
          <PriceChart
            title="Price History & Signal Overlay"
            selectedMetric={selectedMetric}
            onMetricChange={setSelectedMetric}
            targetDate={currentDate}
          />
        </DashboardErrorBoundary>
      </Entitled>

      <Entitled anyOf={[ENT.SECTION_NEWS]}>
        <DashboardErrorBoundary>
          <NewsCard targetDate={currentDate} />
        </DashboardErrorBoundary>
      </Entitled>

      <Entitled anyOf={[ENT.SECTION_WEATHER, ENT.SECTION_WEATHER_SUMMARY]}>
        <DashboardErrorBoundary>
          <WeatherUpdateCard targetDate={currentDate} summary={weatherSummary} />
        </DashboardErrorBoundary>
      </Entitled>

      {/* VI — origin physical flows (matrix block 2). No targetDate: this section
          is monthly and carries its own season selector, deliberately outside
          DashboardDateContext. */}
      <Entitled
        anyOf={[
          ENT.WATCHAI_CAMPAIGN,
          ENT.WATCHAI_CAMPAIGN_PUSH,
          ENT.WATCHAI_MARKET_VIEWS,
        ]}
      >
        <DashboardErrorBoundary>
          <OriginFlowsCard />
        </DashboardErrorBoundary>
      </Entitled>
    </div>
  );
}
