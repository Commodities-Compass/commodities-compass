import GaugeIndicator from "@/components/gauge-indicator";
import { Loader2 } from "lucide-react";
import { useNewsSentiment } from "@/hooks/useDashboard";
import type { IndicatorRange } from "@/types/dashboard";

interface SentimentGaugesProps {
  targetDate?: string;
}

const THEME_LABELS: Record<string, string> = {
  production: "PRODUCTION",
  chocolat: "CHOCOLAT",
  transformation: "TRANSF.",
  economie: "ÉCONOMIE",
};

const THEME_ORDER = ["production", "chocolat", "transformation", "economie"];

const SENTIMENT_RANGES: IndicatorRange[] = [
  { range_low: -1.0, range_high: -0.3, area: "RED" },
  { range_low: -0.3, range_high: 0.3, area: "ORANGE" },
  { range_low: 0.3, range_high: 1.0, area: "GREEN" },
];

export default function SentimentGauges({ targetDate }: SentimentGaugesProps) {
  const { data, isLoading, isError } = useNewsSentiment(targetDate);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-4">
        <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (isError || !data || data.themes.length === 0) {
    return null;
  }

  const themeMap = new Map(data.themes.map((t) => [t.theme, t]));

  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-1 justify-items-center">
      {THEME_ORDER.map((theme) => {
        const t = themeMap.get(theme);
        const label = THEME_LABELS[theme];

        if (!t || t.score === null) {
          return (
            <div key={theme} className="flex flex-col items-center opacity-40">
              <GaugeIndicator
                value={0}
                min={-1}
                max={1}
                label={label}
                ranges={SENTIMENT_RANGES}
                size="sm"
              />
            </div>
          );
        }

        return (
          <GaugeIndicator
            key={theme}
            value={t.score}
            min={-1}
            max={1}
            label={label}
            ranges={SENTIMENT_RANGES}
            size="sm"
          />
        );
      })}
    </div>
  );
}
