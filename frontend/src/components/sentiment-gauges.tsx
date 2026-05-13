import GaugeIndicator from '@/components/gauge-indicator';
import { Loader2 } from 'lucide-react';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { useNewsSentiment } from '@/hooks/useDashboard';
import type { IndicatorRange } from '@/types/dashboard';

interface SentimentGaugesProps {
  targetDate?: string;
}

const THEME_LABELS: Record<string, string> = {
  production: 'PRODUCTION',
  chocolat: 'CHOCOLAT',
  transformation: 'TRANSF.',
  economie: 'ÉCONOMIE',
};

const THEME_ORDER = ['production', 'chocolat', 'transformation', 'economie'];

const SENTIMENT_RANGES: IndicatorRange[] = [
  { range_low: -1.0, range_high: -0.3, area: 'RED' },
  { range_low: -0.3, range_high: 0.3, area: 'ORANGE' },
  { range_low: 0.3, range_high: 1.0, area: 'GREEN' },
];

// Confidence below this threshold means the LLM had no meaningful coverage
// for this theme today (or the backend soft-filled with a neutral row).
// Render a distinct "no coverage" placeholder instead of a misleading gauge.
const NO_COVERAGE_CONFIDENCE_THRESHOLD = 0.2;

function NoCoveragePlaceholder({ label }: { label: string }) {
  return (
    <TooltipProvider delayDuration={150}>
      <Tooltip>
        <TooltipTrigger asChild>
          <div
            className="flex flex-col items-stretch select-none"
            style={{ width: '100%', cursor: 'help' }}
          >
            <div
              className="uppercase text-center"
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 10,
                fontWeight: 600,
                letterSpacing: '0.18em',
                color: 'var(--ink-mid)',
                marginBottom: 18,
              }}
            >
              {label}
            </div>
            <div
              style={{
                position: 'relative',
                paddingTop: 28,
                paddingBottom: 4,
              }}
            >
              <span
                className="tabular-nums"
                style={{
                  position: 'absolute',
                  top: 0,
                  left: '50%',
                  transform: 'translateX(-50%)',
                  fontFamily: 'var(--font-mono)',
                  fontSize: 12,
                  fontWeight: 700,
                  color: 'var(--ink-light)',
                  whiteSpace: 'nowrap',
                }}
              >
                —
              </span>
              <div
                style={{
                  position: 'relative',
                  width: '100%',
                  height: 1,
                  borderTop: '1px dashed var(--ink-light)',
                }}
              />
            </div>
            <div
              className="text-center"
              style={{
                marginTop: 6,
                fontFamily: 'var(--font-sans)',
                fontSize: 8,
                fontWeight: 600,
                textTransform: 'uppercase',
                letterSpacing: '0.12em',
                color: 'var(--ink-light)',
              }}
            >
              Pas de couverture
            </div>
          </div>
        </TooltipTrigger>
        <TooltipContent side="top" className="max-w-60 px-3 py-2">
          <p className="text-[11px] leading-snug">
            Aucune couverture significative dans les sources du jour.
          </p>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

export default function SentimentGauges({ targetDate }: SentimentGaugesProps) {
  const { data, isLoading, isError } = useNewsSentiment(targetDate);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-4" style={{ color: 'var(--ink-light)' }}>
        <Loader2 className="h-4 w-4 animate-spin" />
      </div>
    );
  }

  if (isError || !data || data.themes.length === 0) return null;

  const themeMap = new Map(data.themes.map((t) => [t.theme, t]));

  return (
    <div
      className="sentiment-row"
      style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(4, minmax(0, 1fr))',
        gap: 24,
        alignItems: 'start',
      }}
    >
      {THEME_ORDER.map((theme) => {
        const t = themeMap.get(theme);
        const label = THEME_LABELS[theme];

        const isNoCoverage =
          !t ||
          t.score === null ||
          t.score === undefined ||
          (t.confidence !== null &&
            t.confidence !== undefined &&
            t.confidence < NO_COVERAGE_CONFIDENCE_THRESHOLD);

        if (isNoCoverage) {
          return <NoCoveragePlaceholder key={theme} label={label} />;
        }

        return (
          <GaugeIndicator
            key={theme}
            value={t!.score as number}
            min={-1}
            max={1}
            label={label}
            ranges={SENTIMENT_RANGES}
          />
        );
      })}
      <style>{`
        @media (max-width: 720px) {
          .sentiment-row { grid-template-columns: repeat(2, minmax(0, 1fr)) !important; }
        }
      `}</style>
    </div>
  );
}
