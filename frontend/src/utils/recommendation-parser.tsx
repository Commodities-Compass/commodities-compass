import type { ReactNode } from "react";

// ---------------------------------------------------------------------------
// Parser — split conclusion into analysis + watchlist
// ---------------------------------------------------------------------------

export interface ParsedRecommendations {
  analysis: string[];
  watchlist: string[];
}

export function parseConclusion(items: string[]): ParsedRecommendations {
  const result: ParsedRecommendations = { analysis: [], watchlist: [] };
  let inWatchlist = false;

  for (const item of items) {
    const trimmed = item.trim();
    if (!trimmed) continue;

    if (/a surveiller/i.test(trimmed)) {
      inWatchlist = true;
      continue;
    }

    const cleaned = trimmed.replace(/^>\s*/, "");
    if (!cleaned) continue;

    if (inWatchlist) {
      result.watchlist.push(cleaned);
    } else {
      result.analysis.push(cleaned);
    }
  }

  return result;
}

// ---------------------------------------------------------------------------
// Inline formatter — highlight indicator names and numbers
// ---------------------------------------------------------------------------

interface FormatRule {
  pattern: RegExp;
  render: (match: string) => ReactNode;
}

const FORMAT_RULES: FormatRule[] = [
  {
    pattern:
      /\b(?:CLOSE|VOLUME|OPEN INTEREST|RSI|MACD|ATR|STOCK (?:EU|US)|COM NET|BOLLINGER (?:SUP|INF)|SUPPORT|RESISTANCE|VOL\/OI)\b/g,
    render: (m) => <span className="font-semibold">{m}</span>,
  },
  {
    pattern: /(?<![a-zA-Z])-?\d[\d\s]*(?:\.\d+)?%?(?![a-zA-Z])/g,
    render: (m) => <span className="font-semibold tabular-nums">{m}</span>,
  },
];

export function formatRecoText(text: string): ReactNode[] {
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
    if (start > cursor) nodes.push(text.slice(cursor, start));
    nodes.push(<span key={`r-${i}`}>{rule.render(match)}</span>);
    cursor = end;
  }
  if (cursor < text.length) nodes.push(text.slice(cursor));
  return nodes;
}
