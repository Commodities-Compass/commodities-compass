import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  TrendingUpIcon,
  TrendingDownIcon,
  MinusIcon,
  EyeIcon,
  Loader2,
  ActivityIcon,
} from "lucide-react";
import { useRecommendations } from "@/hooks/useDashboard";
import { cn } from "@/utils";
import type { ReactNode } from "react";

interface RecommendationsListProps {
  targetDate?: string;
  className?: string;
}

// ---------------------------------------------------------------------------
// Parser — split conclusion into analysis + watchlist
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

    // Detect watchlist header
    if (/a surveiller/i.test(trimmed)) {
      inWatchlist = true;
      continue;
    }

    // Clean leading "> " prefix
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
  // Indicator names: CLOSE, VOLUME, RSI, MACD, ATR, etc.
  {
    pattern:
      /\b(?:CLOSE|VOLUME|OPEN INTEREST|RSI|MACD|ATR|STOCK (?:EU|US)|COM NET|BOLLINGER (?:SUP|INF)|SUPPORT|RESISTANCE|VOL\/OI)\b/g,
    render: (m) => <span className="font-semibold">{m}</span>,
  },
  // Numbers with decimals or large values: 2470, 51.20, -24.27, 2494.67, 165605
  {
    pattern: /(?<![a-zA-Z])-?\d[\d\s]*(?:\.\d+)?%?(?![a-zA-Z])/g,
    render: (m) => (
      <span className="font-semibold tabular-nums">{m}</span>
    ),
  },
];

function formatRecoText(text: string): ReactNode[] {
  const allMatches: { start: number; end: number; match: string; rule: FormatRule }[] = [];

  for (const rule of FORMAT_RULES) {
    rule.pattern.lastIndex = 0;
    let m: RegExpExecArray | null;
    while ((m = rule.pattern.exec(text)) !== null) {
      allMatches.push({ start: m.index, end: m.index + m[0].length, match: m[0], rule });
    }
  }

  allMatches.sort((a, b) => a.start - b.start || b.match.length - a.match.length);

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
// Direction detection for analysis bullets
// ---------------------------------------------------------------------------

function getDirectionIcon(text: string) {
  const lower = text.toLowerCase();
  const bearish =
    /diminué|baissé|réduit|négatif|baissière|repli|chute|survendu/.test(lower);
  const bullish =
    /augmenté|haussière|hausse|positif|accroissement|intensification/.test(lower);

  if (bearish) {
    return (
      <TrendingDownIcon className="h-4 w-4 text-amber-500 mt-0.5 shrink-0" />
    );
  }
  if (bullish) {
    return (
      <TrendingUpIcon className="h-4 w-4 text-emerald-500 mt-0.5 shrink-0" />
    );
  }
  return <MinusIcon className="h-4 w-4 text-muted-foreground mt-0.5 shrink-0" />;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function RecommendationsList({
  targetDate,
  className,
}: RecommendationsListProps) {
  const { data, isLoading, error } = useRecommendations(targetDate);

  if (isLoading) {
    return (
      <Card
        className={cn(
          "flex items-center justify-center h-[400px]",
          className,
        )}
      >
        <div className="flex items-center gap-2 text-muted-foreground">
          <Loader2 className="h-5 w-5 animate-spin" />
          <span className="text-sm">Chargement des recommandations...</span>
        </div>
      </Card>
    );
  }

  if (error || !data) {
    return (
      <Card
        className={cn(
          "flex items-center justify-center h-[400px]",
          className,
        )}
      >
        <div className="text-center space-y-1">
          <p className="text-sm text-muted-foreground">
            Aucune recommandation pour cette date
          </p>
          <p className="text-xs text-muted-foreground/60">
            Les signaux de trading sont générés après l'analyse quotidienne
          </p>
        </div>
      </Card>
    );
  }

  const { recommendations } = data;
  const { analysis, watchlist } = parseConclusion(recommendations);

  return (
    <Card className={className}>
      <CardHeader className="pb-3">
        <CardTitle className="text-lg font-medium flex items-center gap-2">
          <ActivityIcon className="h-5 w-5 text-primary" />
          Analyse du Jour
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-5">
        {/* Analysis section */}
        {analysis.length > 0 && (
          <ul className="space-y-2.5">
            {analysis.map((item, i) => (
              <li key={i} className="flex items-start gap-2.5">
                {getDirectionIcon(item)}
                <span className="text-sm leading-relaxed text-foreground/85">
                  {formatRecoText(item)}
                </span>
              </li>
            ))}
          </ul>
        )}

        {/* Watchlist section */}
        {watchlist.length > 0 && (
          <div className="rounded-lg border border-border/60 bg-muted/30 px-4 py-3 space-y-2.5">
            <div className="flex items-center gap-2 text-sm font-semibold text-muted-foreground">
              <EyeIcon className="h-4 w-4" />
              À surveiller
            </div>
            <ul className="space-y-2">
              {watchlist.map((item, i) => (
                <li
                  key={i}
                  className="flex items-start gap-2.5 text-sm leading-relaxed text-foreground/85"
                >
                  <span className="text-muted-foreground mt-1.5 shrink-0">•</span>
                  {formatRecoText(item)}
                </li>
              ))}
            </ul>
          </div>
        )}

        {analysis.length === 0 && watchlist.length === 0 && (
          <p className="text-sm text-muted-foreground text-center py-4">
            Aucune recommandation disponible
          </p>
        )}
      </CardContent>
    </Card>
  );
}
