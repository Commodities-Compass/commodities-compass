import { useQuery } from '@tanstack/react-query';
import { dashboardApi, PositionStatusResponse } from '@/api/dashboard';
import type {
  IndicatorsGridResponse,
  RecommendationsResponse,
  ChartDataResponse,
  NewsResponse,
  NewsSentimentResponse,
  WeatherResponse,
  AudioResponse,
  NonTradingDaysResponse,
  MacroPanelResponse,
  PositioningResponse,
  EnsembleDiagnosticsResponse,
} from '@/types/dashboard';
import axios from 'axios';
import { useLanguage } from '@/hooks/useLanguage';

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
  const { language } = useLanguage();
  return useQuery<RecommendationsResponse>({
    queryKey: ['recommendations', targetDate, language],
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
  const { language } = useLanguage();
  return useQuery<NewsResponse>({
    queryKey: ['news', targetDate, language],
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
  const { language } = useLanguage();
  return useQuery<WeatherResponse>({
    queryKey: ['weather', targetDate, language],
    queryFn: () => dashboardApi.getWeather(targetDate),
    ...DAILY_QUERY_OPTIONS,
  });
};

export const useAudio = (targetDate?: string) => {
  const { language } = useLanguage();
  return useQuery<AudioResponse>({
    // `language` in the key cache-busts on a switch; the actual edition is
    // carried to the backend by the Accept-Language header (client.ts), and the
    // returned stream URL embeds `?language=` so the <audio> element streams the
    // matching edition. The EN edition is ensemble-only and never serves FR.
    queryKey: ['audio', targetDate, language],
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

// Ensemble first ships on 2025-12-15 — earlier dates have no orchestrator row.
const ENSEMBLE_FIRST_DATE = '2025-12-15';

const isOnOrAfterEnsembleStart = (targetDate?: string): boolean => {
  if (!targetDate) return true; // latest data → assume potentially ensemble
  return targetDate >= ENSEMBLE_FIRST_DATE;
};

export const useMacroPanel = (targetDate?: string) => {
  return useQuery<MacroPanelResponse>({
    queryKey: ['macro-panel', targetDate],
    queryFn: () => dashboardApi.getMacroPanel(targetDate),
    ...DAILY_QUERY_OPTIONS,
  });
};

export const usePositioning = (targetDate?: string) => {
  return useQuery<PositioningResponse>({
    queryKey: ['positioning', targetDate],
    queryFn: () => dashboardApi.getPositioning(targetDate),
    ...DAILY_QUERY_OPTIONS,
  });
};

// Retries kill the ergonomics of the 404-on-legacy contract: a 404 is the
// signal to hide the section, not an error to surface or retry.
const shouldRetry404 = (failureCount: number, error: unknown): boolean => {
  if (axios.isAxiosError(error) && error.response?.status === 404) return false;
  return failureCount < 2;
};

export const useEnsembleDiagnostics = (targetDate?: string) => {
  const enabled = isOnOrAfterEnsembleStart(targetDate);
  return useQuery<EnsembleDiagnosticsResponse>({
    queryKey: ['ensemble-diagnostics', targetDate],
    queryFn: () => dashboardApi.getEnsembleDiagnostics(targetDate),
    enabled,
    retry: shouldRetry404,
    ...DAILY_QUERY_OPTIONS,
  });
};
