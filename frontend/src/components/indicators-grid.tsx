import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import GaugeIndicator from "@/components/gauge-indicator";
import { TrendingUpIcon, ActivityIcon, Loader2 } from "lucide-react";
import { useIndicatorsGrid } from "@/hooks/useDashboard";
import { cn } from "@/utils";

interface IndicatorsGridProps {
  targetDate?: string;
  className?: string;
}

export default function IndicatorsGrid({
  targetDate,
  className,
}: IndicatorsGridProps) {
  // Fetch indicators from API
  const { data, isLoading, error } = useIndicatorsGrid(targetDate);

  if (isLoading) {
    return (
      <Card className={cn("flex items-center justify-center h-[400px]", className)}>
        <div className="flex items-center gap-2 text-muted-foreground">
          <Loader2 className="h-5 w-5 animate-spin" />
          <span className="text-sm">Loading indicators...</span>
        </div>
      </Card>
    );
  }

  if (error || !data?.indicators) {
    return (
      <Card className={cn("flex items-center justify-center h-[400px]", className)}>
        <div className="text-center space-y-1">
          <p className="text-sm text-muted-foreground">No indicator data for this date</p>
          <p className="text-xs text-muted-foreground/60">
            Indicators are computed after market close
          </p>
        </div>
      </Card>
    );
  }

  const { indicators } = data;

  return (
    <Card className={className}>
      <CardHeader>
        <CardTitle className="text-lg font-medium">Market Indicators</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="space-y-6">
          {/* Tendances Category */}
          <div className="space-y-4">
            <div className="flex items-center gap-2 border-b pb-2">
              <TrendingUpIcon className="h-4 w-4 text-primary" />
              <h3 className="text-sm font-medium">Tendances</h3>
            </div>

            <div className="grid grid-cols-3 gap-4 justify-items-center">
              {indicators.macroeco && (
                <GaugeIndicator
                  value={indicators.macroeco.value}
                  min={indicators.macroeco.min}
                  max={indicators.macroeco.max}
                  label={indicators.macroeco.label}
                  ranges={indicators.macroeco.ranges}
                  size="sm"
                />
              )}

              {indicators.macd && (
                <GaugeIndicator
                  value={indicators.macd.value}
                  min={indicators.macd.min}
                  max={indicators.macd.max}
                  label={indicators.macd.label}
                  ranges={indicators.macd.ranges}
                  size="sm"
                />
              )}

              {indicators.volOi && (
                <GaugeIndicator
                  value={indicators.volOi.value}
                  min={indicators.volOi.min}
                  max={indicators.volOi.max}
                  label={indicators.volOi.label}
                  ranges={indicators.volOi.ranges}
                  size="sm"
                />
              )}
            </div>
          </div>

          {/* Volatilité Category */}
          <div className="space-y-4">
            <div className="flex items-center gap-2 border-b pb-2">
              <ActivityIcon className="h-4 w-4 text-primary" />
              <h3 className="text-sm font-medium">Volatilité</h3>
            </div>

            <div className="grid grid-cols-3 gap-4 justify-items-center">
              {indicators.rsi && (
                <GaugeIndicator
                  value={indicators.rsi.value}
                  min={indicators.rsi.min}
                  max={indicators.rsi.max}
                  label={indicators.rsi.label}
                  ranges={indicators.rsi.ranges}
                  size="sm"
                />
              )}

              {indicators.percentK && (
                <GaugeIndicator
                  value={indicators.percentK.value}
                  min={indicators.percentK.min}
                  max={indicators.percentK.max}
                  label={indicators.percentK.label}
                  ranges={indicators.percentK.ranges}
                  size="sm"
                />
              )}

              {indicators.atr && (
                <GaugeIndicator
                  value={indicators.atr.value}
                  min={indicators.atr.min}
                  max={indicators.atr.max}
                  label={indicators.atr.label}
                  ranges={indicators.atr.ranges}
                  size="sm"
                />
              )}
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}