import type {
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
