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

export type AlgorithmName = 'ensemble_v1_softgate_wrapper' | 'legacy' | string;

export interface PositionStatusResponse {
  date: string;
  position: 'OPEN' | 'HEDGE' | 'MONITOR';
  ytd_performance: number;
  source_algorithm?: AlgorithmName | null;
}

export interface IndicatorsGridResponse {
  date: string;
  indicators: {
    [key: string]: CommodityIndicator;
  };
  source_algorithm?: AlgorithmName | null;
  /** Front-month contract for this date (e.g. "CAU26"). Display-only provenance. */
  contract_code?: string | null;
}

export interface RecommendationsResponse {
  date: string;
  recommendations: string[];
  raw_score: string | null;
  source_algorithm?: AlgorithmName | null;
}

export interface ChartDataPoint {
  date: string;
  close?: number | null;
  volume?: number | null;
  open_interest?: number | null;
  rsi_14d?: number | null;
  macd?: number | null;
  stock_eu?: number | null;
  com_net_eu?: number | null;
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

export interface ThemeSentiment {
  theme: string;
  score: number | null;
  confidence: number | null;
  rationale: string | null;
  zscore_delta: number | null;
  has_signal: boolean;
}

export interface NewsSentimentResponse {
  date: string;
  themes: ThemeSentiment[];
  accumulation: number | null;
}

export interface SeasonStatus {
  season_name: string;
  label: string;
  months_covered: string;
  score: number | null;
  status: 'completed' | 'in_progress' | 'upcoming';
}

export interface LocationDiagnostic {
  location_name: string;
  country: 'CIV' | 'GHA';
  score: number | null;
  status: 'normal' | 'degraded' | 'stress';
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
  country: 'CIV' | 'GHA';
  current_status: 'normal' | 'degraded' | 'stress';
  streak_days: number;
  trend: 'stable' | 'improving' | 'worsening';
  history: ('normal' | 'degraded' | 'stress')[];
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

// ---------------------------------------------------------------------------
// Section VI — Macro & Positioning
// ---------------------------------------------------------------------------

export interface MacroPanelResponse {
  date: string;
  fx_dxy_proxy: number | null;
  fx_gbpusd: number | null;
  fx_eurusd: number | null;
  fx_gbpeur: number | null;
  fx_xofgbp: number | null;
  enso_oni_month: number | null;
  enso_nino34_anomaly: number | null;
  enso_reference_date: string | null;
  macro_direction: number | null;
  macro_surprise: number | null;
  macro_half_life_days: number | null;
  source_algorithm?: AlgorithmName | null;
}

export interface FarmgatePriceEntry {
  region: string;
  campaign_type: 'principale' | 'intermediaire';
  season_label: string;
  price_native: number;
  currency: string;
  unit: string;
  source: string;
  source_url: string | null;
  effective_date: string;
  announced_date: string | null;
}

export interface FarmgateRegionPrices {
  principale: FarmgatePriceEntry | null;
  intermediaire: FarmgatePriceEntry | null;
}

export interface FarmgatePriceResponse {
  date: string;
  civ: FarmgateRegionPrices;
  ghana: FarmgateRegionPrices;
}

export interface PositioningResponse {
  date: string;
  // ICE EU COT
  cot_managed_money_net: number | null;
  cot_managed_money_long: number | null;
  cot_managed_money_short: number | null;
  cot_producer_merchant_net: number | null;
  cot_open_interest: number | null;
  cot_report_date: string | null;
  cot_release_date: string | null;
  // CFTC US COT (added 2026-05-27 — parity with EU)
  cot_us_managed_money_net: number | null;
  cot_us_managed_money_long: number | null;
  cot_us_managed_money_short: number | null;
  cot_us_producer_merchant_net: number | null;
  cot_us_open_interest: number | null;
  cot_us_report_date: string | null;
  cot_us_release_date: string | null;
  // Stocks (canonical tonnes for both regions + EU native audit)
  stock_eu_tonnes: number | null;
  stock_eu_native_value: number | null;
  stock_eu_native_unit: string | null;
  stock_eu_report_date: string | null;
  stock_us_tonnes: number | null;
  stock_us_report_date: string | null;
  stock_eu_us_ratio: number | null;
}

// ---------------------------------------------------------------------------
// Ensemble diagnostics — consumed by SignalHero (Conviction Breakdown).
// ---------------------------------------------------------------------------

export interface EnsembleDiagnosticsResponse {
  date: string;
  algorithm_version: string;
  soft_gate_decision: 'OPEN' | 'HEDGE' | 'MONITOR';
  net_score: number;
  weights_sum: number;
  n_committed_specialists: number;
  decision_wrapped: 'OPEN' | 'HEDGE' | 'MONITOR';
  wrapper_active: boolean;
  fired_running_acc: boolean;
  fired_trend: boolean;
  fired_dispersion: boolean;
  fired_three_way: boolean;
  /** LLM confidence (1-5), derived from the brief's rubric. */
  confidence: number | null;
  /** Short rationale listing pillars SOUTIEN / NEUTRE / NUANCE. */
  confidence_rationale: string | null;
  running_acc_5d: number | null;
  realized_return_5d: number | null;
  winter_vote_signed: number | null;
  spring_vote_signed: number | null;
  macro_direction: number | null;
  macro_surprise: number | null;
  macro_half_life_days: number | null;
  anomaly_score_z: number | null;
  prior_open: number | null;
  prior_hedge: number | null;
  prior_monitor: number | null;
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
