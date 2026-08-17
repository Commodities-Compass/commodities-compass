import type {
  OriginBenchmarkResponse,
  OriginDestinationsResponse,
  OriginExportersResponse,
  MonthlyFlow,
  OriginCampaignResponse,
  OriginMarketViewsResponse,
  TransformationBlock,
} from '@/types/origin';

/**
 * Fixtures for Section VI, shaped after the real 2025-2026 payload.
 *
 * They deliberately carry the awkward cases rather than a clean season, because
 * those are the ones the components have to get right: STATSER trailing three
 * months behind (`grinding_declared_t: null` on the tail), per-source windows of
 * different lengths, and a negative monthly balance.
 */
export const monthly: MonthlyFlow[] = [
  {
    period: '2025-10-01',
    purchases_t: 210_450,
    exports_beans_t: 150_120,
    exports_transformed_t: 30_400,
    exports_total_t: 180_520,
    grinding_declared_t: 52_300,
    grinding_derived_t: 38_000,
    balance_t: 22_330,
  },
  {
    period: '2025-11-01',
    purchases_t: 198_000,
    exports_beans_t: 172_400,
    exports_transformed_t: 33_100,
    exports_total_t: 205_500,
    grinding_declared_t: 54_900,
    grinding_derived_t: 41_375,
    balance_t: -15_775,
  },
  {
    // STATSER has not published this month — the row must read as pending, not
    // as a month where nothing was ground.
    period: '2026-07-01',
    purchases_t: 96_200,
    exports_beans_t: 88_300,
    exports_transformed_t: 28_900,
    exports_total_t: 117_200,
    grinding_declared_t: null,
    grinding_derived_t: 36_125,
    balance_t: -28_225,
  },
];

export const campaign: OriginCampaignResponse = {
  data_as_of: '2026-07-31',
  season: '2025-2026',
  available_seasons: ['2025-2026', '2024-2025', '2021-2022'],
  perimeter: 'all_ci',
  monthly,
  ytd: [
    {
      source: 'exports',
      season: '2025-2026',
      previous_season: '2024-2025',
      window: { from: '2025-10-01', to: '2026-07-01', months: 10 },
      current_t: 1_710_347,
      previous_t: 1_428_071,
      delta_pct: 19.8,
    },
    {
      source: 'purchases',
      season: '2025-2026',
      previous_season: '2024-2025',
      window: { from: '2025-10-01', to: '2026-07-01', months: 10 },
      current_t: 2_087_867,
      previous_t: 1_622_077,
      delta_pct: 28.7,
    },
    {
      // Seven months against the others' ten — the case the window caption and
      // the help tooltip both exist for.
      source: 'grinding',
      season: '2025-2026',
      previous_season: '2024-2025',
      window: { from: '2025-10-01', to: '2026-04-01', months: 7 },
      current_t: 381_169,
      previous_t: 389_745,
      delta_pct: -2.2,
    },
  ],
  month: {
    period: '2026-07-01',
    exports_t: 117_200,
    purchases_t: 96_200,
    valcaf_fcfa: 412_000_000_000,
    duties_taxes_fcfa: 38_400_000_000,
  },
};

export const transformation: TransformationBlock = {
  perimeter: 'gepex',
  window: { from: '2025-10-01', to: '2026-04-01', months: 7 },
  purchases_t: 2_087_867,
  exports_beans_t: 1_425_900,
  exports_transformed_t: 227_373,
  exports_total_t: 1_653_273,
  grinding_derived_t: 284_216,
  balance_t: 377_751,
  balance_pct: 18.1,
  transformation_rate_pct: 13.6,
  outflow_rate_pct: 81.9,
  stock_signal: 'stock_constitue',
  outflow_exceeds_purchases: false,
  cumulative_balance_t: 377_751,
  monthly_cumulative_t: [22_330, 6_555, -21_670],
  statser_confrontation: {
    perimeter: 'gepex',
    window: { from: '2025-10-01', to: '2026-04-01', months: 7 },
    derived_t: 284_216,
    declared_t: 381_169,
    gap_t: -96_953,
    gap_pct: -30.3,
  },
};

export const marketViews: OriginMarketViewsResponse = {
  data_as_of: '2026-07-31',
  season: '2025-2026',
  available_seasons: ['2025-2026', '2024-2025', '2021-2022'],
  season_totals: [
    { season: '2025-2026', exports_t: 1_710_347, purchases_t: 2_087_867 },
    { season: '2024-2025', exports_t: 1_428_071, purchases_t: 1_622_077 },
    // Before the purchase master starts — nullable on purpose.
    { season: '2015-2016', exports_t: 1_390_400, purchases_t: null },
  ],
  monthly,
  product_mix: [
    { product_code: 'FEVES', is_bean_equivalent: true, export_tonnes: 1_290_400, share_pct: 75.4 },
    { product_code: 'HORS_GRADE', is_bean_equivalent: true, export_tonnes: 80_100, share_pct: 4.7 },
    { product_code: 'MASSE', is_bean_equivalent: false, export_tonnes: 180_891, share_pct: 10.6 },
    { product_code: 'BEURRE', is_bean_equivalent: false, export_tonnes: 89_300, share_pct: 5.2 },
    { product_code: 'TOURTEAU', is_bean_equivalent: false, export_tonnes: 48_200, share_pct: 2.8 },
    { product_code: 'POUDRE', is_bean_equivalent: false, export_tonnes: 21_456, share_pct: 1.3 },
  ],
  transformation,
};

const line = (
  label: string,
  tonnes: number,
  previous: number,
  share: number,
  delta: number | null
) => ({
  label,
  export_tonnes: tonnes,
  previous_tonnes: previous,
  delta_pct: delta,
  window: { from: '2025-10-01', to: '2026-07-01', months: 10 },
  share_pct: share,
});

export const destinations: OriginDestinationsResponse = {
  data_as_of: '2026-07-31',
  season: '2025-2026',
  available_seasons: ['2025-2026', '2024-2025', '2021-2022'],
  previous_season: '2024-2025',
  destinations: [
    line('PAYS-BAS', 409_405, 373_237, 23.9, 9.7),
    line('ETATS-UNIS', 239_705, 144_782, 14.0, 65.6),
    line('BELGIQUE', 203_972, 119_196, 11.9, 71.1),
    // A destination that stopped mid-season: its window is shorter, and its
    // delta is computed over the months it actually shipped.
    { ...line('MALAISIE', 145_449, 80_395, 8.5, 80.9), window: { from: '2025-10-01', to: '2026-03-01', months: 6 } },
    // Growth off a zero baseline is undefined, not infinite.
    line('COREE DU SUD', 4_200, 0, 0.2, null),
  ],
  ports: [
    line('ABIDJAN', 865_401, 763_733, 50.6, 13.3),
    line('SAN PEDRO', 844_946, 664_338, 49.4, 27.2),
  ],
  concentration: { top1_share_pct: 23.9, top3_share_pct: 49.9, count: 49 },
};

export const exporters: OriginExportersResponse = {
  data_as_of: '2026-07-31',
  season: '2025-2026',
  available_seasons: ['2025-2026', '2024-2025', '2021-2022'],
  previous_season: '2024-2025',
  growth_floor_tonnes: 250,
  exporters: [
    {
      exporter: 'CARGILL',
      is_gepex_member: true,
      exports_beans_t: 147_350,
      exports_transformed_t: 51_771,
      exports_total_t: 199_121,
      purchases_t: 277_565,
      grinding_derived_t: 64_714,
      balance_t: 65_456,
      transformation_share_pct: 26.0,
      previous_exports_t: 174_667,
      growth_pct: 14.0,
      outflow_exceeds_purchases: false,
    },
    {
      // The majority case on real data: 58 of 102 exporters ship more than the
      // purchase master records for them. A flag, never an error.
      exporter: 'CYRIAN',
      is_gepex_member: false,
      exports_beans_t: 90_833,
      exports_transformed_t: 0,
      exports_total_t: 90_833,
      purchases_t: 74_540,
      grinding_derived_t: 0,
      balance_t: -16_293,
      transformation_share_pct: 0,
      previous_exports_t: 49_635,
      growth_pct: 83.0,
      outflow_exceeds_purchases: true,
    },
    {
      // Below the 250 t floor last season — growth is suppressed, not computed.
      exporter: 'PETIT NEGOCE',
      is_gepex_member: false,
      exports_beans_t: 812,
      exports_transformed_t: 0,
      exports_total_t: 812,
      purchases_t: 900,
      grinding_derived_t: 0,
      balance_t: 88,
      transformation_share_pct: 0,
      previous_exports_t: 180,
      growth_pct: null,
      outflow_exceeds_purchases: false,
    },
  ],
  movers: {
    up: [
      { exporter: 'ETRAYAWIEN', growth_pct: 451.0, exports_total_t: 5_520, previous_exports_t: 1_001 },
    ],
    down: [
      { exporter: 'IVCAO', growth_pct: -92.0, exports_total_t: 1_251, previous_exports_t: 15_700 },
    ],
  },
};

export const benchmark: OriginBenchmarkResponse = {
  data_as_of: '2026-07-31',
  season: '2025-2026',
  available_seasons: ['2025-2026', '2024-2025', '2021-2022'],
  previous_season: '2024-2025',
  applicable: true,
  exporter: 'CARGILL',
  position: {
    exports_total_t: 199_121,
    market_total_t: 1_710_347,
    market_share_pct: 11.6,
    rank: 1,
    exporters_ranked: 102,
    own_destinations: [
      { label: 'PAYS-BAS', export_tonnes: 88_400, share_pct: 44.4 },
      { label: 'ETATS-UNIS', export_tonnes: 61_200, share_pct: 30.7 },
      { label: 'BELGIQUE', export_tonnes: 49_521, share_pct: 24.9 },
    ],
  },
};

/** An account with no exporter identity: `n/a`, never a zeroed book. */
export const benchmarkNotApplicable: OriginBenchmarkResponse = {
  ...benchmark,
  applicable: false,
  exporter: null,
  position: null,
};
