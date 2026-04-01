import { apiClient } from './client';
import type { PositionStatusResponse, IndicatorsGridResponse, RecommendationsResponse, ChartDataResponse, NewsResponse, WeatherResponse, AudioResponse } from '@/types/dashboard';

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

  getChartData: async (days: number = 30): Promise<ChartDataResponse> => {
    const response = await apiClient.get<ChartDataResponse>('/dashboard/chart-data', { params: { days } });
    return response.data;
  },

  getNews: async (targetDate?: string): Promise<NewsResponse> => {
    const params = targetDate ? { target_date: targetDate } : {};
    const response = await apiClient.get<NewsResponse>('/dashboard/news', { params });
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
};