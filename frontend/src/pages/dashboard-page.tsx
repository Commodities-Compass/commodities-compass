import DateSelector from '@/components/date-selector';
import IndicatorsGrid from '@/components/indicators-grid';
import NewsCard from '@/components/news-card';
import PositionStatus from '@/components/position-status';
import PriceChart from '@/components/price-chart';
import RecommendationsList from '@/components/recommendations-list';
import WeatherUpdateCard from '@/components/weather-update-card';
import { DashboardErrorBoundary } from '@/components/DashboardErrorBoundary';
import { METRIC_OPTIONS } from '@/data/commodities-data';
import { useState } from 'react';
import { format, subDays } from 'date-fns';

const getYesterdayISO = (isoDate: string): string => {
  const date = new Date(isoDate + 'T12:00:00');
  return format(subDays(date, 1), 'yyyy-MM-dd');
};

export default function DashboardPage() {
  const today = format(new Date(), 'yyyy-MM-dd');
  const [currentDate, setCurrentDate] = useState(today);
  const [selectedMetric, setSelectedMetric] = useState('close');

  const metricConfig =
    METRIC_OPTIONS.find((option) => option.value === selectedMetric) ||
    METRIC_OPTIONS[0];

  const yesterdayDate = getYesterdayISO(currentDate);

  return (
    <div className="space-y-6">
      <div className="flex flex-col md:flex-row gap-4 items-start md:items-center justify-between">
        <h1 className="text-2xl font-bold">Commodities Dashboard</h1>
        <DateSelector
          currentDate={currentDate}
          onDateChange={setCurrentDate}
          className="w-full md:w-auto"
        />
      </div>

      <DashboardErrorBoundary>
        <PositionStatus
          targetDate={yesterdayDate}
          audioDate={yesterdayDate}
        />
      </DashboardErrorBoundary>

      <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
        <div className="lg:col-span-2">
          <DashboardErrorBoundary>
            <IndicatorsGrid targetDate={yesterdayDate} />
          </DashboardErrorBoundary>
        </div>
        <div className="lg:col-span-3">
          <DashboardErrorBoundary>
            <RecommendationsList targetDate={yesterdayDate} />
          </DashboardErrorBoundary>
        </div>
      </div>

      <div>
        <DashboardErrorBoundary>
          <PriceChart
            title={`${metricConfig.label} Trend`}
            selectedMetric={selectedMetric}
            onMetricChange={setSelectedMetric}
          />
        </DashboardErrorBoundary>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <DashboardErrorBoundary>
          <NewsCard targetDate={yesterdayDate} />
        </DashboardErrorBoundary>

        <DashboardErrorBoundary>
          <WeatherUpdateCard targetDate={yesterdayDate} />
        </DashboardErrorBoundary>
      </div>
    </div>
  );
}
