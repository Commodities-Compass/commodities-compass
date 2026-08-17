/**
 * Entitlement key constants — mirror of backend app/core/entitlements.py.
 * Keep in sync with the backend catalogue. Opaque strings; the frontend only
 * checks membership (see useEntitlements).
 */
export const ENT = {
  SECTION_SIGNAL: 'read:section:signal',
  SECTION_PODCAST: 'read:section:podcast',
  SECTION_MARKET: 'read:section:market',
  SECTION_CHART: 'read:section:chart',
  SECTION_NEWS: 'read:section:news',
  SECTION_WEATHER: 'read:section:weather',
  SECTION_WEATHER_SUMMARY: 'read:section:weather:summary',
  CHROME_TICKER: 'read:chrome:ticker',
  FEATURE_ENSEMBLE_DIAGNOSTICS: 'read:feature:ensemble_diagnostics',
  FEATURE_SPECIALIST_VOTES: 'read:feature:specialist_votes',
  FEATURE_MACRO_PANEL: 'read:feature:macro_panel',
  FEATURE_POSITIONING: 'read:feature:positioning',
  FEATURE_FARMGATE: 'read:feature:farmgate',

  // --- WatchAI (matrix block 2) — origin physical flows --------------------
  // The reduced variant of the campaign row. Coop Essentiel holds only this one
  // and never WATCHAI_CAMPAIGN, so the campaign gate is an anyOf over the pair.
  WATCHAI_CAMPAIGN: 'read:watchai:campaign_monthly',
  WATCHAI_CAMPAIGN_PUSH: 'read:watchai:campaign_monthly:push',
  WATCHAI_MARKET_VIEWS: 'read:watchai:market_views',
  WATCHAI_DESTINATIONS: 'read:watchai:destinations',
  WATCHAI_BENCHMARK: 'read:watchai:benchmark',
  WATCHAI_NOMINATIVE: 'read:watchai:nominative',
} as const;
