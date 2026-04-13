/**
 * Inline formatter — regex-based styling for French financial / commodity text.
 * Shared by NewsCard and WeatherUpdateCard.
 */

import type { ReactNode } from "react";
import { cn } from "@/utils";

interface FormatRule {
  pattern: RegExp;
  render: (match: string) => ReactNode;
}

const FORMAT_RULES: FormatRule[] = [
  // Percentages — signed: +2,30%, -0,06%, (-0,30%) or unsigned: 27.7%, (13.2%)
  {
    pattern: /\(?\s?[+-]?\s?\d[\d\s]*[.,]?\d*\s?%\s?\)?/g,
    render: (m) => {
      const isNeg = m.includes("-");
      return (
        <span
          className={cn(
            "font-semibold tabular-nums",
            isNeg && "text-amber-500/80 dark:text-amber-400/70",
          )}
        >
          {m}
        </span>
      );
    },
  },
  // Prices with units: 2 358 GBP/t, 10 $, 3 160 $/t
  {
    pattern: /\d[\d\s]*(?:[.,]\d+)?\s?(?:GBP|USD|\$|€|£)(?:\/t(?:onne)?)?/g,
    render: (m) => <span className="font-semibold tabular-nums">{m}</span>,
  },
  // Standalone numbers with thousands separator or decimals (period or comma)
  // followed by a unit-like word. Captures leading negative sign for weather data.
  {
    pattern:
      /-?\d[\d\s]*(?:[.,]\d+)?\s?(?:contrats?|tonnes?|pts?|points?|mm|jours?|bags?|lots?|kPa|°C|m³\/m³|kt|Mt|heures?)/gi,
    render: (m) => <span className="font-semibold tabular-nums">{m}</span>,
  },
  // Contract codes: CAK26, CCK26, CAN26, etc.
  {
    pattern: /\b(?:CA|CC)[HKNUZ]\d{2}\b/g,
    render: (m) => (
      <span className="font-mono font-semibold text-primary/90">{m}</span>
    ),
  },
  // Market venues / institutions
  {
    pattern: /\b(?:ICE|CFTC|CRA|ICCO|NYSE|CME)\b/g,
    render: (m) => <span className="font-semibold">{m}</span>,
  },
  // Directional signals (bearish + bullish) — bold only, no color
  {
    pattern:
      /\b(?:en repli|baissière?s?|recul|chute|pression vendeuse|liquidation|décote|vulnérable|en hausse|haussière?s?|rebond|reprise|soutien|support)\b/gi,
    render: (m) => <span className="font-semibold">{m}</span>,
  },
  // Temporal markers: À court terme, À moyen terme
  {
    pattern: /[ÀA]\s(?:court|moyen|long)\s+terme/gi,
    render: (m) => <span className="font-semibold italic">{m}</span>,
  },
  // Weather-specific: location names in Côte d'Ivoire and Ghana
  {
    pattern:
      /\b(?:Daloa|San-Pédro|Soubré|Kumasi|Takoradi|Goaso|Abidjan|Accra)\b/g,
    render: (m) => <span className="font-semibold">{m}</span>,
  },
  // Weather-specific: agronomic keywords
  {
    pattern:
      /\b(?:stress hydrique|seuil|déficit hydrique|pluviométrie|évapotranspiration|ETO|VPD|harmattan|humidité du sol|saison des pluies|sécheresse)\b/gi,
    render: (m) => <span className="font-semibold">{m}</span>,
  },
];

/**
 * Apply formatting rules to a plain-text string.
 * Rules are matched left-to-right, first-match-wins (no overlaps).
 */
export function formatFinancialText(text: string): ReactNode[] {
  const allMatches: {
    start: number;
    end: number;
    match: string;
    rule: FormatRule;
  }[] = [];

  for (const rule of FORMAT_RULES) {
    rule.pattern.lastIndex = 0;
    let m: RegExpExecArray | null;
    while ((m = rule.pattern.exec(text)) !== null) {
      allMatches.push({
        start: m.index,
        end: m.index + m[0].length,
        match: m[0],
        rule,
      });
    }
  }

  allMatches.sort(
    (a, b) => a.start - b.start || b.match.length - a.match.length,
  );

  const filtered: typeof allMatches = [];
  let lastEnd = 0;
  for (const m of allMatches) {
    if (m.start >= lastEnd) {
      filtered.push(m);
      lastEnd = m.end;
    }
  }

  const nodes: ReactNode[] = [];
  let cursor = 0;

  for (let i = 0; i < filtered.length; i++) {
    const { start, end, match, rule } = filtered[i];
    if (start > cursor) {
      nodes.push(text.slice(cursor, start));
    }
    nodes.push(<span key={`fmt-${i}`}>{rule.render(match)}</span>);
    cursor = end;
  }

  if (cursor < text.length) {
    nodes.push(text.slice(cursor));
  }

  return nodes;
}
