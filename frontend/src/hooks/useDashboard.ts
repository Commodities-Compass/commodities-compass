import { useQuery } from '@tanstack/react-query';
import { dashboardApi, PositionStatusResponse } from '@/api/dashboard';
import type { IndicatorsGridResponse, RecommendationsResponse, ChartDataResponse, NewsResponse, NewsSentimentResponse, WeatherResponse, AudioResponse, NonTradingDaysResponse } from '@/types/dashboard';

const DAILY_QUERY_OPTIONS = {
  staleTime: 24 * 60 * 60 * 1000,
  refetchInterval: false as const,
  refetchOnWindowFocus: false,
  refetchOnMount: false,
};

export const usePositionStatus = (targetDate?: string) => {
  return useQuery<PositionStatusResponse>({
    queryKey: ['position-status', targetDate],
    queryFn: () => dashboardApi.getPositionStatus(targetDate),
    ...DAILY_QUERY_OPTIONS,
  });
};

export const useIndicatorsGrid = (targetDate?: string) => {
  return useQuery<IndicatorsGridResponse>({
    queryKey: ['indicators-grid', targetDate],
    queryFn: () => dashboardApi.getIndicatorsGrid(targetDate),
    ...DAILY_QUERY_OPTIONS,
  });
};

export const useRecommendations = (targetDate?: string) => {
  return useQuery<RecommendationsResponse>({
    queryKey: ['recommendations', targetDate],
    queryFn: () => dashboardApi.getRecommendations(targetDate),
    ...DAILY_QUERY_OPTIONS,
  });
};

export const useChartData = (days: number = 30, targetDate?: string) => {
  return useQuery<ChartDataResponse>({
    queryKey: ['chart-data', days, targetDate],
    queryFn: () => dashboardApi.getChartData(days, targetDate),
    ...DAILY_QUERY_OPTIONS,
  });
};

export const useNews = (targetDate?: string) => {
  return useQuery<NewsResponse>({
    queryKey: ['news', targetDate],
    queryFn: () => dashboardApi.getNews(targetDate),
    ...DAILY_QUERY_OPTIONS,
  });
};

export const useNewsSentiment = (targetDate?: string) => {
  return useQuery<NewsSentimentResponse>({
    queryKey: ['news-sentiment', targetDate],
    queryFn: () => dashboardApi.getNewsSentiment(targetDate),
    ...DAILY_QUERY_OPTIONS,
  });
};

export const useWeather = (targetDate?: string) => {
  return useQuery<WeatherResponse>({
    queryKey: ['weather', targetDate],
    queryFn: () => dashboardApi.getWeather(targetDate),
    ...DAILY_QUERY_OPTIONS,
  });
};

export const useAudio = (targetDate?: string) => {
  return useQuery<AudioResponse>({
    queryKey: ['audio', targetDate],
    queryFn: () => dashboardApi.getAudio(targetDate),
    staleTime: 5 * 60 * 1000, // 5 min — audio availability can change (pipeline timing)
    refetchOnMount: true,
    refetchOnWindowFocus: false,
    retry: 2,
  });
};

export const useNonTradingDays = (year: number) => {
  return useQuery<NonTradingDaysResponse>({
    queryKey: ['non-trading-days', year],
    queryFn: () => dashboardApi.getNonTradingDays(year),
    ...DAILY_QUERY_OPTIONS,
  });
};
