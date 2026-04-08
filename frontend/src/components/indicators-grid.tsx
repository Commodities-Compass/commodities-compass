import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import GaugeIndicator from "@/components/gauge-indicator";
import { ActivityIcon, Loader2 } from "lucide-react";
import { useIndicatorsGrid } from "@/hooks/useDashboard";
import { cn } from "@/utils";

interface IndicatorsGridProps {
  targetDate?: string;
  className?: string;
}

const INDICATOR_KEYS = [
  "macroeco",
  "macd",
  "volOi",
  "rsi",
  "percentK",
  "atr",
] as const;

export default function IndicatorsGrid({
  targetDate,
  className,
}: IndicatorsGridProps) {
  const { data, isLoading, error } = useIndicatorsGrid(targetDate);

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
          <span className="text-sm">Chargement des indicateurs...</span>
        </div>
      </Card>
    );
  }

  if (error || !data?.indicators) {
    return (
      <Card
        className={cn(
          "flex items-center justify-center h-[400px]",
          className,
        )}
      >
        <div className="text-center space-y-1">
          <p className="text-sm text-muted-foreground">
            Aucune donnée d'indicateur pour cette date
          </p>
          <p className="text-xs text-muted-foreground/60">
            Les indicateurs sont calculés après la clôture du marché
          </p>
        </div>
      </Card>
    );
  }

  const { indicators } = data;

  return (
    <Card className={className}>
      <CardHeader className="pb-2">
        <CardTitle className="text-lg font-medium flex items-center gap-2">
          <ActivityIcon className="h-5 w-5 text-primary" />
          Indicateurs de Marché
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-3 gap-x-2 gap-y-4 justify-items-center">
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
                  size="md"
                />
              ),
          )}
        </div>
      </CardContent>
    </Card>
  );
}
