export interface IndicatorRange {
  range_low: number;
  range_high: number;
  area: 'RED' | 'ORANGE' | 'GREEN';
}

export interface CommodityIndicator {
  value: number;
  min: number;
  max: number;
  label: string;
  ranges?: IndicatorRange[];
}

export interface PositionStatusResponse {
  date: string;
  position: 'OPEN' | 'HEDGE' | 'MONITOR';
  ytd_performance: number;
}

export interface IndicatorsGridResponse {
  date: string;
  indicators: {
    [key: string]: CommodityIndicator;
  };
}

export interface RecommendationsResponse {
  date: string;
  recommendations: string[];
  raw_score: string | null;
}

export interface ChartDataPoint {
  date: string;
  close?: number | null;
  volume?: number | null;
  open_interest?: number | null;
  rsi_14d?: number | null;
  macd?: number | null;
  stock_us?: number | null;
  com_net_us?: number | null;
}

export interface ChartDataResponse {
  data: ChartDataPoint[];
}

export interface NewsResponse {
  date: string;
  title: string;
  content: string;
  keywords: string | null;
  author: string | null;
  source_count: number | null;
  total_sources: number | null;
}

export interface SeasonStatus {
  season_name: string;
  label: string;
  months_covered: string;
  score: number | null;
  status: "completed" | "in_progress" | "upcoming";
}

export interface LocationDiagnostic {
  location_name: string;
  country: "CIV" | "GHA";
  score: number | null;
  status: "normal" | "degraded" | "stress";
  harmattan_days?: number | null;
}

export interface HarmattanStatus {
  days: number;
  threshold: number;
  risk: boolean;
  in_season: boolean;
}

export interface LocationStressHistory {
  location_name: string;
  country: "CIV" | "GHA";
  current_status: "normal" | "degraded" | "stress";
  streak_days: number;
  trend: "stable" | "improving" | "worsening";
  history: ("normal" | "degraded" | "stress")[];
}

export interface WeatherResponse {
  date: string;
  description: string;
  impact: string;
  campaign?: string;
  campaign_health?: number | null;
  seasons?: SeasonStatus[];
  diagnostics?: LocationDiagnostic[];
  daily_diagnostics?: LocationDiagnostic[];
  stress_history?: LocationStressHistory[];
  impact_score?: number | null;
  harmattan?: HarmattanStatus | null;
}

export interface AudioResponse {
  url: string;
  title: string;
  date: string;
  filename: string;
}

export interface NonTradingDaysResponse {
  dates: string[];
  latest_trading_day: string | null;
}