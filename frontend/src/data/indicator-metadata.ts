/**
 * Maps a gauge indicator code (as passed via GaugeIndicator's `label`) to its
 * i18n catalog prefix under `indicators.*`. The tooltip strings (name,
 * description, zone labels) live in the FR/EN catalogs and are resolved by the
 * consumer via t(`indicators.${prefix}_name` | `_desc` | `_zones_{red|orange|green}`).
 * US-2 i18n — replaces the former hardcoded French INDICATOR_META table.
 */
export const INDICATOR_META_KEY: Record<string, string> = {
  MACROECO: 'macroeco',
  RSI: 'rsi',
  MACD: 'macd',
  '%K': 'stochastic',
  ATR: 'atr',
  'VOL/OI': 'voloi',
  'FX DXY': 'fx_dxy',
  GBPUSD: 'gbpusd',
  'ENSO ONI': 'enso_oni',
  'NIÑO 3.4': 'nino34',
  'COT MM NET EU': 'cot_mm_net_eu',
  'COT MM NET US': 'cot_mm_net_us',
  'STOCK EU': 'stock_eu',
  'STOCK US': 'stock_us',
  PRODUCTION: 'production',
  CHOCOLAT: 'chocolate',
  'TRANSF.': 'transformation',
  ÉCONOMIE: 'economy',
};
