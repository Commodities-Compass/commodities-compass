import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import GaugeIndicator from "@/components/gauge-indicator";
import { Loader2 } from "lucide-react";
import { useIndicatorsGrid, useRecommendations } from "@/hooks/useDashboard";
import { cn } from "@/utils";
import type { ReactNode } from "react";

interface MarketAnalysisProps {
  targetDate?: string;
  className?: string;
}

// ---------------------------------------------------------------------------
// Indicator keys
// ---------------------------------------------------------------------------

const INDICATOR_KEYS = [
  "macroeco",
  "macd",
  "volOi",
  "rsi",
  "percentK",
  "atr",
] as const;

// ---------------------------------------------------------------------------
// Recommendation parser
// ---------------------------------------------------------------------------

interface ParsedRecommendations {
  analysis: string[];
  watchlist: string[];
}

function parseConclusion(items: string[]): ParsedRecommendations {
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
// Inline formatter
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

function formatRecoText(text: string): ReactNode[] {
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

// ---------------------------------------------------------------------------
// Direction icon
// ---------------------------------------------------------------------------

function getDirectionDot(text: string) {
  const lower = text.toLowerCase();
  if (
    /diminué|baissé|réduit|négatif|baissière|repli|chute|survendu/.test(lower)
  ) {
    return <span className="mt-1.5 shrink-0 h-2 w-2 rounded-full bg-amber-500" />;
  }
  if (
    /augmenté|haussière|hausse|positif|accroissement|intensification/.test(lower)
  ) {
    return <span className="mt-1.5 shrink-0 h-2 w-2 rounded-full bg-emerald-500" />;
  }
  return <span className="mt-1.5 shrink-0 h-2 w-2 rounded-full bg-muted-foreground/40" />;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function MarketAnalysis({
  targetDate,
  className,
}: MarketAnalysisProps) {
  const {
    data: gridData,
    isLoading: gridLoading,
    error: gridError,
  } = useIndicatorsGrid(targetDate);
  const {
    data: recoData,
    isLoading: recoLoading,
    error: recoError,
  } = useRecommendations(targetDate);

  const isLoading = gridLoading || recoLoading;

  if (isLoading) {
    return (
      <Card
        className={cn(
          "flex items-center justify-center h-[300px]",
          className,
        )}
      >
        <div className="flex items-center gap-2 text-muted-foreground">
          <Loader2 className="h-5 w-5 animate-spin" />
          <span className="text-sm">Chargement de l'analyse...</span>
        </div>
      </Card>
    );
  }

  const indicators = gridData?.indicators;
  const recommendations = recoData?.recommendations;
  const parsed = recommendations
    ? parseConclusion(recommendations)
    : { analysis: [], watchlist: [] };

  return (
    <Card className={cn("overflow-hidden", className)}>
      <CardHeader className="pb-3">
        <CardTitle className="text-lg font-semibold tracking-tight">
          Analyse du Jour
        </CardTitle>
      </CardHeader>

      <CardContent className="space-y-5">
        {/* Row 1: Gauges — single horizontal row */}
        {indicators && !gridError && (
          <div className="grid grid-cols-3 sm:grid-cols-6 gap-1 justify-items-center">
            {INDICATOR_KEYS.map(
              (key) =>
                indicators[key] && (
                  <GaugeIndicator
                    key={key}
                    value={indicators[key].value}
                    min={indicators[key].min}
                    max={indicators[key].max}
                    label={indicators[key].label}
                    ranges={indicators[key].ranges}
                    size="sm"
                  />
                ),
            )}
          </div>
        )}

        {/* Separator */}
        <div className="border-t border-border/50" />

        {/* Row 2: Analysis (left) + Watchlist (right) */}
        {!recoError &&
        (parsed.analysis.length > 0 || parsed.watchlist.length > 0) ? (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Analysis */}
            <div className="space-y-2">
              {parsed.analysis.length > 0 && (
                <ul className="space-y-2">
                  {parsed.analysis.map((item, i) => (
                    <li key={i} className="flex items-start gap-2">
                      {getDirectionDot(item)}
                      <span className="text-sm leading-relaxed text-foreground/85">
                        {formatRecoText(item)}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            {/* Watchlist */}
            {parsed.watchlist.length > 0 && (
              <div className="rounded-lg border border-border/60 bg-muted/30 px-4 py-3 space-y-2.5 h-fit">
                <h3 className="text-sm font-semibold tracking-tight">
                  À surveiller
                </h3>
                <ul className="space-y-2">
                  {parsed.watchlist.map((item, i) => (
                    <li
                      key={i}
                      className="flex items-start gap-2.5 text-sm leading-relaxed text-foreground/85"
                    >
                      <span className="text-muted-foreground mt-1 shrink-0">
                        •
                      </span>
                      {formatRecoText(item)}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        ) : (
          !recoError && (
            <p className="text-sm text-muted-foreground text-center py-4">
              Aucune recommandation disponible
            </p>
          )
        )}
      </CardContent>
    </Card>
  );
}
