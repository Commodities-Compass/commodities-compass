/**
 * Origin flow types — mirror of `backend/app/schemas/origin.py`.
 *
 * Two payloads, one per matrix block ② row sold to Coop Premium. Neither carries
 * an exporter, a destination or a port: those live behind `read:watchai:nominative`
 * and `read:watchai:destinations`, which the tiers reaching these endpoints do not
 * necessarily hold.
 *
 * Note what is nullable and why — the nulls are the interesting part of this API:
 * every one of them means "not measured" rather than "zero", and rendering them
 * as 0 would print a figure that was never observed.
 */

/** The period range a figure actually covers. */
export interface OriginWindow {
  /** `from` is a reserved word in the payload; the backend aliases it. */
  from: string | null;
  to: string | null;
  months: number;
}

export interface MonthlyFlow {
  period: string;
  purchases_t: number;
  exports_beans_t: number;
  exports_transformed_t: number;
  exports_total_t: number;
  /** NULL = STATSER has not published this month yet. It trails the other two
   *  sources by 2-3 months, so the most recent rows are legitimately empty. */
  grinding_declared_t: number | null;
  /** Transformed exports back to bean equivalent (÷ 0.80). NOT the declaration. */
  grinding_derived_t: number;
  /** achats − fèves − broyage déduit, served by the backend so the arithmetic has
   *  one implementation. May be negative for a single month. */
  balance_t: number;
}

export interface YtdComparison {
  source: 'exports' | 'purchases' | 'grinding';
  season: string;
  previous_season: string;
  /** Each source has its OWN window — grinding typically shows 7 months where
   *  exports show 10. Display it: a shared window would imply a collapse that is
   *  purely a publication lag. */
  window: OriginWindow;
  current_t: number;
  previous_t: number;
  /** NULL against a zero baseline — growth off zero is undefined, not infinite. */
  delta_pct: number | null;
}

export interface MonthSynthesis {
  period: string;
  exports_t: number;
  purchases_t: number;
  valcaf_fcfa: number;
  duties_taxes_fcfa: number;
}

export interface ProductMixLine {
  product_code: string;
  /** TRUE for FEVES and HORS_GRADE. Carried so a consumer can see which
   *  denominator a "transformation" figure used: the WatchAI report counts
   *  hors-grade as transformed (27,7 %), Compass counts it as a bean (19,9 %). */
  is_bean_equivalent: boolean;
  export_tonnes: number;
  share_pct: number | null;
}

export interface StatserConfrontation {
  /** Always `gepex` — STATSER only covers those 11 operators, so both sides of
   *  the comparison are computed on them. */
  perimeter: string;
  window: OriginWindow;
  derived_t: number;
  declared_t: number;
  /** derived − declared. Either sign is informative. */
  gap_t: number;
  gap_pct: number | null;
}

export interface TransformationBlock {
  perimeter: string;
  window: OriginWindow;
  purchases_t: number;
  exports_beans_t: number;
  exports_transformed_t: number;
  exports_total_t: number;
  /** Transformed exports converted back to bean equivalent (÷ 0.80). Larger than
   *  the product weight by construction — that is the point, not an error. */
  grinding_derived_t: number;
  balance_t: number;
  balance_pct: number | null;
  /** Derived grinding over PURCHASES. NOT the transformed share of the export
   *  mix — different denominator, ~0.5 pt apart on real data. */
  transformation_rate_pct: number | null;
  outflow_rate_pct: number | null;
  stock_signal: 'stock_constitue' | 'stock_n1_mobilise';
  /** More matter left than was bought. A publishable state, not an error: stock
   *  carries across seasons and the purchase master covers fewer operators than
   *  customs exports. This is why it is a solde *apparent*. */
  outflow_exceeds_purchases: boolean;
  cumulative_balance_t: number;
  monthly_cumulative_t: number[];
  statser_confrontation: StatserConfrontation | null;
}

export interface OriginCampaignResponse {
  data_as_of: string;
  season: string;
  available_seasons: string[];
  perimeter: string;
  monthly: MonthlyFlow[];
  ytd: YtdComparison[];
  month: MonthSynthesis | null;
}

export interface SeasonTotal {
  season: string;
  exports_t: number;
  /** NULL for seasons before the purchase master starts (2020-10). */
  purchases_t: number | null;
}

export interface OriginMarketViewsResponse {
  data_as_of: string;
  season: string;
  available_seasons: string[];
  season_totals: SeasonTotal[];
  monthly: MonthlyFlow[];
  product_mix: ProductMixLine[];
  /** NULL for seasons before the purchase master starts: there are exports and a
   *  product mix, but no balance to compute. Zeros would read as a measurement. */
  transformation: TransformationBlock | null;
}

/** One destination or one port. */
export interface BreakdownLine {
  label: string;
  export_tonnes: number;
  previous_tonnes: number;
  /** Against the SAME months a year earlier, never the previous season in full.
   *  NULL against a zero baseline — growth off zero is undefined. */
  delta_pct: number | null;
  /** Per line, not per view: a destination that stopped shipping in March is
   *  compared over the months it did ship, so two lines can cover different spans. */
  window: OriginWindow;
  share_pct: number | null;
}

export interface DestinationConcentration {
  top1_share_pct: number | null;
  top3_share_pct: number | null;
  count: number;
}

export interface OriginDestinationsResponse {
  data_as_of: string;
  season: string;
  available_seasons: string[];
  previous_season: string;
  destinations: BreakdownLine[];
  ports: BreakdownLine[];
  concentration: DestinationConcentration;
}

/** One named exporter — gated by `read:watchai:nominative`. */
export interface ExporterFlowLine {
  exporter: string;
  is_gepex_member: boolean;
  exports_beans_t: number;
  exports_transformed_t: number;
  exports_total_t: number;
  purchases_t: number;
  grinding_derived_t: number;
  balance_t: number;
  /** This exporter's OWN transformed share (§7). STATSER is a GEPEX aggregate
   *  and is never allocated across operators. */
  transformation_share_pct: number | null;
  previous_exports_t: number;
  /** NULL below the 250 t floor — growth off a tiny base is noise (§8). */
  growth_pct: number | null;
  outflow_exceeds_purchases: boolean;
}

export interface ExporterMover {
  exporter: string;
  growth_pct: number | null;
  exports_total_t: number;
  previous_exports_t: number;
}

export interface OriginExportersResponse {
  data_as_of: string;
  season: string;
  available_seasons: string[];
  previous_season: string;
  growth_floor_tonnes: number;
  exporters: ExporterFlowLine[];
  movers: { up: ExporterMover[]; down: ExporterMover[] };
}

export interface OwnDestinationLine {
  label: string;
  export_tonnes: number;
  share_pct: number | null;
}

export interface BenchmarkPosition {
  exports_total_t: number;
  market_total_t: number;
  market_share_pct: number | null;
  /** Over EVERY exporter, not a truncated top-N. */
  rank: number | null;
  exporters_ranked: number;
  own_destinations: OwnDestinationLine[];
}

export interface OriginBenchmarkResponse {
  data_as_of: string;
  season: string;
  available_seasons: string[];
  previous_season: string;
  /** FALSE is a first-class answer: no exporter identity. Not an empty book —
   *  that would read as "you shipped nothing", which is a different claim. */
  applicable: boolean;
  exporter: string | null;
  position: BenchmarkPosition | null;
}
