'use client';

import DateSelector from '@/components/date-selector';
import IndicatorsGrid from '@/components/indicators-grid';
import NewsCard from '@/components/news-card';
import PositionStatus from '@/components/position-status';
import PriceChart from '@/components/price-chart';
import RecommendationsList from '@/components/recommendations-list';
import WeatherUpdateCard from '@/components/weather-update-card';
import { METRIC_OPTIONS } from '@/data/commodities-data';
import { useState } from 'react';

// Convert date to ISO format (YYYY-MM-DD) preserving local timezone
const dateToISOString = (date: Date): string => {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
};

// Convert date string to ISO format for API
const convertToISODate = (dateStr: string, dayOffset: number = 0): string | undefined => {
  try {
    const date = new Date(dateStr);
    if (dayOffset !== 0) {
      date.setDate(date.getDate() + dayOffset);
    }
    return dateToISOString(date);
  } catch {
    return undefined;
  }
};

// Get yesterday's date in ISO format
const getYesterdayDate = (dateStr: string): string | undefined => {
  return convertToISODate(dateStr, -1);
};

export default function DashboardPage() {
  const today = new Date().toLocaleDateString('en-US', {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
  });
  const [currentDate, setCurrentDate] = useState(today);
  const [selectedMetric, setSelectedMetric] = useState('close');

  // Find the selected metric configuration
  const metricConfig =
    METRIC_OPTIONS.find((option) => option.value === selectedMetric) ||
    METRIC_OPTIONS[0];

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

      <PositionStatus 
        targetDate={getYesterdayDate(currentDate)} 
        audioDate={getYesterdayDate(currentDate)}
      />

      <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
        <div className="lg:col-span-2">
          <IndicatorsGrid targetDate={getYesterdayDate(currentDate)} />
        </div>
        <div className="lg:col-span-3">
          <RecommendationsList targetDate={getYesterdayDate(currentDate)} />
        </div>
      </div>

      <div>
        <PriceChart
          title={`${metricConfig.label} Trend`}
          selectedMetric={selectedMetric}
          onMetricChange={setSelectedMetric}
        />
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <NewsCard targetDate={getYesterdayDate(currentDate)} />

        <WeatherUpdateCard targetDate={getYesterdayDate(currentDate)} />
      </div>
    </div>
  );
}
