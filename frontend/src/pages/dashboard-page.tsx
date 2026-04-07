import DateSelector from '@/components/date-selector';
import IndicatorsGrid from '@/components/indicators-grid';
import NewsCard from '@/components/news-card';
import PositionStatus from '@/components/position-status';
import PriceChart from '@/components/price-chart';
import RecommendationsList from '@/components/recommendations-list';
import WeatherUpdateCard from '@/components/weather-update-card';
import { DashboardErrorBoundary } from '@/components/DashboardErrorBoundary';
import { METRIC_OPTIONS } from '@/data/commodities-data';
import { usePositionStatus } from '@/hooks/useDashboard';
import { useState } from 'react';

const todayISO = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
};

export default function DashboardPage() {
  const [currentDate, setCurrentDate] = useState(todayISO());
  const [selectedMetric, setSelectedMetric] = useState('close');

  const { data: positionData } = usePositionStatus(currentDate);
  const sessionDate = positionData?.date ?? null;

  const metricConfig =
    METRIC_OPTIONS.find((option) => option.value === selectedMetric) ||
    METRIC_OPTIONS[0];

  return (
    <div className="space-y-6">
      <div className="flex flex-col md:flex-row gap-4 items-start md:items-center justify-between">
        <h1 className="text-2xl font-bold">Tableau de Bord</h1>
        <DateSelector
          currentDate={currentDate}
          onDateChange={setCurrentDate}
          sessionDate={sessionDate ?? undefined}
          className="w-full md:w-auto"
        />
      </div>

      <DashboardErrorBoundary>
        <PositionStatus
          targetDate={currentDate}
          audioDate={currentDate}
        />
      </DashboardErrorBoundary>

      <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
        <div className="lg:col-span-2">
          <DashboardErrorBoundary>
            <IndicatorsGrid targetDate={currentDate} />
          </DashboardErrorBoundary>
        </div>
        <div className="lg:col-span-3">
          <DashboardErrorBoundary>
            <RecommendationsList targetDate={currentDate} />
          </DashboardErrorBoundary>
        </div>
      </div>

      <div>
        <DashboardErrorBoundary>
          <PriceChart
            title={`Évolution ${metricConfig.label}`}
            selectedMetric={selectedMetric}
            onMetricChange={setSelectedMetric}
            targetDate={currentDate}
          />
        </DashboardErrorBoundary>
      </div>

      <DashboardErrorBoundary>
        <NewsCard targetDate={currentDate} />
      </DashboardErrorBoundary>

      <DashboardErrorBoundary>
        <WeatherUpdateCard targetDate={currentDate} />
      </DashboardErrorBoundary>
    </div>
  );
}
