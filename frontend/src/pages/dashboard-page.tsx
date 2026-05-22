import { useState } from 'react';
import MarketAnalysis from '@/components/market-analysis';
import NewsCard from '@/components/news-card';
import SignalHero from '@/components/signal-hero';
import PodcastPlayer from '@/components/podcast-player';
import PriceChart from '@/components/price-chart';
import WeatherUpdateCard from '@/components/weather-update-card';
import DecisionExplainerCard from '@/components/decision-explainer-card';
import { DashboardErrorBoundary } from '@/components/DashboardErrorBoundary';
import { useDashboardDate } from '@/hooks/useDashboardDate';
import { usePositionStatus } from '@/hooks/useDashboard';

export default function DashboardPage() {
  const { currentDate } = useDashboardDate();
  const [selectedMetric, setSelectedMetric] = useState('close');
  // Drives the conditional Section VII (ensemble audit). usePositionStatus is
  // already fetched by SignalHero — React Query dedupes, so this is free.
  const { data: positionStatus } = usePositionStatus(currentDate);

  return (
    <div>
      <DashboardErrorBoundary>
        <SignalHero targetDate={currentDate} />
      </DashboardErrorBoundary>

      <DashboardErrorBoundary>
        <PodcastPlayer audioDate={currentDate} />
      </DashboardErrorBoundary>

      <DashboardErrorBoundary>
        <MarketAnalysis targetDate={currentDate} />
      </DashboardErrorBoundary>

      <DashboardErrorBoundary>
        <PriceChart
          title="Price History & Signal Overlay"
          selectedMetric={selectedMetric}
          onMetricChange={setSelectedMetric}
          targetDate={currentDate}
        />
      </DashboardErrorBoundary>

      <DashboardErrorBoundary>
        <NewsCard targetDate={currentDate} />
      </DashboardErrorBoundary>

      <DashboardErrorBoundary>
        <WeatherUpdateCard targetDate={currentDate} />
      </DashboardErrorBoundary>

      <DashboardErrorBoundary>
        <DecisionExplainerCard
          targetDate={currentDate}
          sourceAlgorithm={positionStatus?.source_algorithm}
        />
      </DashboardErrorBoundary>
    </div>
  );
}
