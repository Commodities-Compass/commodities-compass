import type {
  FarmgatePriceResponse,
  IndicatorRange,
  MacroPanelResponse,
} from '@/types/dashboard';

/**
 * Whether the Reference stratum has anything to show.
 *
 * Lives here rather than next to the component so the rail can decide whether
 * to offer the page at all — the folio must never advertise an empty stratum.
 */
export function hasFarmgateData(farmgate?: FarmgatePriceResponse): boolean {
  if (!farmgate) return false;
  // A season with one origin still pending is data: the pending card is the
  // point, not a placeholder for missing data.
  return Boolean(farmgate.season);
}

export function hasReferenceData(
  farmgate?: FarmgatePriceResponse,
  macro?: MacroPanelResponse
): boolean {
  const hasEnso =
    macro?.enso_oni_month != null || macro?.enso_nino34_anomaly != null;
  return hasFarmgateData(farmgate) || hasEnso;
}

export const INDICATOR_KEYS = [
  'macd',
  'volOi',
  'rsi',
  'percentK',
  'atr',
] as const;

// Editorial ranges for the macro + positioning gauges. Editorial defaults
// (not from pl_test_range which only covers the 5 technical indicators).
export const MACRO_RANGES: Record<
  string,
  { min: number; max: number; ranges: IndicatorRange[] }
> = {
  FX_DXY: {
    min: 0.85,
    max: 1.1,
    ranges: [
      { range_low: 0.98, range_high: 1.1, area: 'RED' },
      { range_low: 0.92, range_high: 0.98, area: 'ORANGE' },
      { range_low: 0.85, range_high: 0.92, area: 'GREEN' },
    ],
  },
  FX_GBPUSD: {
    min: 1.1,
    max: 1.45,
    ranges: [
      { range_low: 1.1, range_high: 1.22, area: 'RED' },
      { range_low: 1.22, range_high: 1.32, area: 'ORANGE' },
      { range_low: 1.32, range_high: 1.45, area: 'GREEN' },
    ],
  },
  // XOF (FCFA) per 1 GBP — FCFA value of the London cocoa price. Derived from
  // the FIXED EUR/XOF peg (655.957) through the floating GBP/EUR leg, so it
  // only moves with GBP/EUR. Zones are INDICATIVE (producer-revenue lens: a
  // weaker XOF = more FCFA per GBP of crop = greener), not a trading signal —
  // same editorial-default convention as the other FX gauges above.
  FX_XOFGBP: {
    min: 700,
    max: 850,
    ranges: [
      { range_low: 700, range_high: 740, area: 'RED' },
      { range_low: 740, range_high: 800, area: 'ORANGE' },
      { range_low: 800, range_high: 850, area: 'GREEN' },
    ],
  },
  ENSO_ONI: {
    min: -2,
    max: 2,
    ranges: [
      { range_low: -2, range_high: -0.5, area: 'RED' },
      { range_low: -0.5, range_high: 0.5, area: 'ORANGE' },
      { range_low: 0.5, range_high: 2, area: 'GREEN' },
    ],
  },
  ENSO_NINO34: {
    min: -3,
    max: 3,
    ranges: [
      { range_low: -3, range_high: -0.5, area: 'RED' },
      { range_low: -0.5, range_high: 0.5, area: 'ORANGE' },
      { range_low: 0.5, range_high: 3, area: 'GREEN' },
    ],
  },
  // COT Managed Money Net — Net long position of speculative funds.
  // Same direction convention for both regions: net long = bullish for prices.
  // Ranges differ because CFTC US cocoa contracts trade larger notional
  // (NY cocoa) and historically swing wider than ICE Europe (London #7).
  COT_MM_EU: {
    min: -40000,
    max: 60000,
    ranges: [
      { range_low: -40000, range_high: 0, area: 'RED' },
      { range_low: 0, range_high: 20000, area: 'ORANGE' },
      { range_low: 20000, range_high: 60000, area: 'GREEN' },
    ],
  },
  // Calibrated 2026-05-28 from CFTC cocoa Managed Money historical envelope
  // (~−50k bottom of 2022 / ~+100k 2024 supply-crisis peak). Re-tune once
  // we accumulate enough scraped weeks to plot the post-refactor distribution.
  COT_MM_US: {
    min: -50000,
    max: 100000,
    ranges: [
      { range_low: -50000, range_high: 0, area: 'RED' },
      { range_low: 0, range_high: 30000, area: 'ORANGE' },
      { range_low: 30000, range_high: 100000, area: 'GREEN' },
    ],
  },
  // Stock EU certified (tonnes). Recalibrated 2026-05-27 for the post-crisis
  // West African supply regime (2k-37k since 2024 vs 150k-200k pre-crisis).
  // Low stocks = bullish for cocoa prices → GREEN on the low end.
  STOCK_EU: {
    min: 0,
    max: 200_000,
    ranges: [
      { range_low: 0, range_high: 20_000, area: 'GREEN' },
      { range_low: 20_000, range_high: 60_000, area: 'ORANGE' },
      { range_low: 60_000, range_high: 200_000, area: 'RED' },
    ],
  },
  // Stock US certified (tonnes) — same inverse direction as EU. Recalibrated
  // 2026-05-27 to current ICE US range (90k-190k since 2025).
  STOCK_US: {
    min: 0,
    max: 450_000,
    ranges: [
      { range_low: 0, range_high: 100_000, area: 'GREEN' },
      { range_low: 100_000, range_high: 250_000, area: 'ORANGE' },
      { range_low: 250_000, range_high: 450_000, area: 'RED' },
    ],
  },
};

export function fmtCompactInt(v?: number | null): string {
  if (v == null || !Number.isFinite(v)) return '—';
  const abs = Math.abs(v);
  if (abs >= 1_000_000) return `${(v / 1_000_000).toFixed(2)}M`;
  if (abs >= 1_000) return `${(v / 1_000).toFixed(1)}k`;
  return v.toFixed(0);
}

export function fmtTonnes(v: number): string {
  const abs = Math.abs(v);
  if (abs >= 1_000_000) return `${(v / 1_000_000).toFixed(2)}M t`;
  if (abs >= 1_000) return `${(v / 1_000).toFixed(0)}k t`;
  return `${v.toFixed(0)} t`;
}

export function fmtNum(v?: number | null, digits = 2): string {
  if (v == null || !Number.isFinite(v)) return '—';
  return v.toFixed(digits);
}

export function fmtDate(iso?: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso + 'T00:00:00');
  if (Number.isNaN(d.getTime())) return iso;
  const months = [
    'Jan',
    'Feb',
    'Mar',
    'Apr',
    'May',
    'Jun',
    'Jul',
    'Aug',
    'Sep',
    'Oct',
    'Nov',
    'Dec',
  ];
  return `${d.getDate()} ${months[d.getMonth()]} ${d.getFullYear()}`;
}

export const gridStyle = (cols: number): React.CSSProperties => ({
  display: 'grid',
  gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))`,
  // Token, not a literal: the rail compacts it on phones, and an inline
  // literal could only be overridden with !important.
  gap: 'var(--field-gap, 24px)',
  alignItems: 'start',
});

// No fixed 5-/4-column constants: since the rail shows one stratum at a time,
// each panel fits its own column count (`gridStyle(items.length)`). A stratum
// of 3 gauges gets 3 wide columns instead of 3 gauges stranded in a 5-column
// grid — and a wider ruler is a more readable ruler. Cross-stratum gauge widths
// are deliberately NOT held constant; the strata are never seen side by side.
