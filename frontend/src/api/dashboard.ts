import { apiClient } from './client';
import type { PositionStatusResponse, IndicatorsGridResponse, RecommendationsResponse, ChartDataResponse, NewsResponse, NewsSentimentResponse, WeatherResponse, AudioResponse, NonTradingDaysResponse } from '@/types/dashboard';

export type { PositionStatusResponse };

export const dashboardApi = {
  getPositionStatus: async (targetDate?: string): Promise<PositionStatusResponse> => {
    const params = targetDate ? { target_date: targetDate } : {};
    const response = await apiClient.get<PositionStatusResponse>('/dashboard/position-status', { params });
    return response.data;
  },

  getIndicatorsGrid: async (targetDate?: string): Promise<IndicatorsGridResponse> => {
    const params = targetDate ? { target_date: targetDate } : {};
    const response = await apiClient.get<IndicatorsGridResponse>('/dashboard/indicators-grid', { params });
    return response.data;
  },

  getRecommendations: async (targetDate?: string): Promise<RecommendationsResponse> => {
    const params = targetDate ? { target_date: targetDate } : {};
    const response = await apiClient.get<RecommendationsResponse>('/dashboard/recommendations', { params });
    return response.data;
  },

  getChartData: async (days: number = 30, targetDate?: string): Promise<ChartDataResponse> => {
    const params: Record<string, string | number> = { days };
    if (targetDate) params.target_date = targetDate;
    const response = await apiClient.get<ChartDataResponse>('/dashboard/chart-data', { params });
    return response.data;
  },

  getNews: async (targetDate?: string): Promise<NewsResponse> => {
    const params = targetDate ? { target_date: targetDate } : {};
    const response = await apiClient.get<NewsResponse>('/dashboard/news', { params });
    return response.data;
  },

  getNewsSentiment: async (targetDate?: string): Promise<NewsSentimentResponse> => {
    const params = targetDate ? { target_date: targetDate } : {};
    const response = await apiClient.get<NewsSentimentResponse>('/dashboard/news/sentiment', { params });
    return response.data;
  },

  getWeather: async (targetDate?: string): Promise<WeatherResponse> => {
    const params = targetDate ? { target_date: targetDate } : {};
    const response = await apiClient.get<WeatherResponse>('/dashboard/weather', { params });
    return response.data;
  },

  getAudio: async (targetDate?: string): Promise<AudioResponse> => {
    const params = targetDate ? { target_date: targetDate } : {};
    const response = await apiClient.get<AudioResponse>('/dashboard/audio', { params });
    return response.data;
  },

  getNonTradingDays: async (year: number, month?: number): Promise<NonTradingDaysResponse> => {
    const params: Record<string, number> = { year };
    if (month !== undefined) params.month = month;
    const response = await apiClient.get<NonTradingDaysResponse>('/dashboard/non-trading-days', { params });
    return response.data;
  },
};