import { describe, it, expect } from 'vitest';

import fr from './locales/fr.json';
import en from './locales/en.json';

/**
 * Catalog invariants.
 *
 * The two editions are a product promise, not a nice-to-have: a French client
 * reading an English sentence mid-page reads a bug. Two failure modes put one
 * there, and only the first is caught here:
 *
 *   1. a key added to one edition and forgotten in the other — i18next then
 *      falls back to the other language and the leak is silent;
 *   2. a string hardcoded in a component and never routed through a catalog at
 *      all — invisible to any test that only reads these files. That is how
 *      "Cocoa Bullish Continuation" led the French hero at 56px for months
 *      (fixed 2026-08-19, `signal.headline.*`).
 *
 * For (2) the rule is a review rule: user-facing prose goes in the catalog.
 * Brand vocabulary that is deliberately identical in both editions — OPEN /
 * MONITOR / HEDGE, "Compass Intelligence Desk", the masthead's signal legend —
 * is the documented exception.
 */
type Catalog = { [k: string]: string | Catalog };

function flatten(node: Catalog, prefix = ''): Set<string> {
  const keys = new Set<string>();
  for (const [k, v] of Object.entries(node)) {
    const path = prefix ? `${prefix}.${k}` : k;
    if (typeof v === 'string') keys.add(path);
    else for (const nested of flatten(v, path)) keys.add(nested);
  }
  return keys;
}

const frKeys = flatten(fr as Catalog);
const enKeys = flatten(en as Catalog);

/** Resolve a dotted path against a catalog. */
function read(catalog: unknown, path: string): unknown {
  return path
    .split('.')
    .reduce<unknown>((node, k) => (node as Record<string, unknown>)?.[k], catalog);
}

describe('i18n catalogs', () => {
  it('define exactly the same keys in both editions', () => {
    expect([...frKeys].filter((k) => !enKeys.has(k)).sort()).toEqual([]);
    expect([...enKeys].filter((k) => !frKeys.has(k)).sort()).toEqual([]);
  });

  it('leaves no empty string behind', () => {
    // An empty value renders as a blank where a sentence belongs — which reads
    // as missing data rather than as a missing translation.
    for (const [edition, catalog] of [
      ['fr', fr],
      ['en', en],
    ] as const) {
      const blanks = [...flatten(catalog as Catalog)].filter((path) => {
        const value = path
          .split('.')
          .reduce<unknown>(
            (node, k) => (node as Record<string, unknown>)?.[k],
            catalog,
          );
        return typeof value === 'string' && value.trim().length === 0;
      });
      expect(blanks, `${edition} has blank values`).toEqual([]);
    }
  });

  it('carries a headline for every position the hero can render', () => {
    // SignalHero indexes this by `pos.position.toLowerCase()`. A gap surfaces
    // as the raw key printed at 56px.
    for (const position of ['open', 'monitor', 'hedge']) {
      for (const [edition, keys] of [
        ['fr', frKeys],
        ['en', enKeys],
      ] as const) {
        expect(
          keys.has(`signal.headline.${position}`),
          `${edition} is missing signal.headline.${position}`,
        ).toBe(true);
      }
    }
  });

  /**
   * Keys whose value is deliberately identical in both editions.
   *
   * Three legitimate reasons, and no fourth:
   *   - brand vocabulary ("Compass Intelligence Desk", "Lead Analysis") —
   *     carried identically by both editions on purpose;
   *   - proper nouns and technical names (MACD, GEPEX, Ghana, Oceanic Niño Index);
   *   - cognates that are genuinely the same word (Destination, Total, Pause).
   *
   * Anything else identical is an untranslated string. That is how
   * `market.tab_supply` and `market.tab_technical` shipped as "Supply & Momentum"
   * and "Technical Outlook" on the French dashboard, and how the weather table
   * ran "Pays / Statut" next to "Origin / Trend" — half translated, which reads
   * worse than not translated at all.
   *
   * Adding a key here is a decision, not a formality: say which of the three
   * reasons applies.
   */
  const INTENTIONALLY_IDENTICAL = new Set([
    // brand
    'dashboard.algo_regime',
    'dashboard.desk_name',
    'dashboard.lead_analysis',
    // proper nouns / technical names
    'indicators.atr_name',
    'indicators.cot_mm_net_eu_name',
    'indicators.cot_mm_net_us_name',
    'indicators.enso_oni_name',
    'indicators.fx_dxy_name',
    'indicators.macd_name',
    'indicators.rsi_name',
    'indicators.voloi_name',
    'market.grp_fx',
    'origin.gepex_member',
    'theme.production',
    'weather.country_civ',
    'weather.country_ghana',
    // cognates — same word in both languages
    'common.session_prefix',
    'market.socle_session',
    'origin.caption_grinding',
    'origin.caption_tonnes',
    'origin.col_destination',
    'origin.col_port',
    'origin.col_tonnes',
    'origin.concentration_count',
    'origin.tab_destinations',
    'origin.total',
    'origin.vs',
    'podcast.pause',
    'weather.col_harmattan',
    'weather.harmattan_label',
    'weather.status_normal',
    'weather.status_stress',
  ]);

  it('has no untranslated string — identical values must be declared', () => {
    const identical = [...frKeys]
      .filter((k) => enKeys.has(k))
      .filter((k) => read(fr, k) === read(en, k))
      .filter((k) => !INTENTIONALLY_IDENTICAL.has(k))
      .sort();

    expect(
      identical,
      'these are identical in fr and en — translate them, or add them to ' +
        'INTENTIONALLY_IDENTICAL with the reason',
    ).toEqual([]);
  });

  it('keeps the two headline sets distinct — a copy-paste is not a translation', () => {
    for (const position of ['open', 'monitor', 'hedge'] as const) {
      const frText = (fr.signal.headline as Record<string, string>)[position];
      const enText = (en.signal.headline as Record<string, string>)[position];
      expect(frText).toBeTruthy();
      expect(frText).not.toBe(enText);
      // The signal token itself is brand vocabulary and stays untranslated.
      expect(frText).toContain(position.toUpperCase());
      expect(enText).toContain(position.toUpperCase());
    }
  });
});
