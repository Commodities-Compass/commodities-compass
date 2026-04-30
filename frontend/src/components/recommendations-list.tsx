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
import { parseConclusion, formatRecoText } from "@/utils/recommendation-parser";

interface RecommendationsListProps {
  targetDate?: string;
  className?: string;
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
