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
