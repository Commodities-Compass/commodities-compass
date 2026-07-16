import GaugeIndicator from '@/components/gauge-indicator';
import { Loader2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { useNewsSentiment } from '@/hooks/useDashboard';
import { useIsTouch } from '@/hooks/useIsTouch';
import type { IndicatorRange } from '@/types/dashboard';

interface SentimentGaugesProps {
  targetDate?: string;
}

const THEME_LABEL_KEYS: Record<string, string> = {
  production: 'theme.production',
  chocolat: 'theme.chocolat',
  transformation: 'theme.transformation',
  economie: 'theme.economy',
};

// Language-independent keys into INDICATOR_META_KEY for the tooltip lookup. The
// display `label` is localized (t()), so it can't double as the metadata key —
// in EN it would be "CHOCOLATE"/"GRINDINGS"/"ECONOMY", none of which exist in
// INDICATOR_META_KEY, silently suppressing the tooltip. These stable codes do.
const THEME_METADATA_KEYS: Record<string, string> = {
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

// Note: the previous behavior hid the gauge when confidence < 0.2 (treating
// the backend soft-fill as "no coverage"). Product decision 2026-05-28: always
// display the gauge so traders see a sentiment value every day, even when the
// LLM had thin source coverage. The placeholder below is kept only for the
// (now defensive) case where the score is truly null/undefined.

function NoCoveragePlaceholder({ label }: { label: string }) {
  const { t } = useTranslation();
  const isTouch = useIsTouch();
  const inner = (
    <div
      className="flex flex-col items-stretch select-none"
      style={{ width: '100%', cursor: isTouch ? 'default' : 'help' }}
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
              {t('common.no_coverage')}
            </div>
          </div>
  );

  if (isTouch) return inner;

  return (
    <TooltipProvider delayDuration={150}>
      <Tooltip>
        <TooltipTrigger asChild>{inner}</TooltipTrigger>
        <TooltipContent side="top" className="max-w-60 px-3 py-2">
          <p className="text-[11px] leading-snug">
            {t('common.no_coverage_tooltip')}
          </p>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

export default function SentimentGauges({ targetDate }: SentimentGaugesProps) {
  const { t } = useTranslation();
  const { data, isLoading, isError } = useNewsSentiment(targetDate);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-4" style={{ color: 'var(--ink-light)' }}>
        <Loader2 className="h-4 w-4 animate-spin" />
      </div>
    );
  }

  if (isError || !data || data.themes.length === 0) return null;

  const themeMap = new Map(data.themes.map((item) => [item.theme, item]));

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
        const themeData = themeMap.get(theme);
        const label = t(THEME_LABEL_KEYS[theme]);

        const hasNoScore =
          !themeData || themeData.score === null || themeData.score === undefined;

        if (hasNoScore) {
          return <NoCoveragePlaceholder key={theme} label={label} />;
        }

        return (
          <GaugeIndicator
            key={theme}
            value={themeData!.score as number}
            min={-1}
            max={1}
            label={label}
            metadataKey={THEME_METADATA_KEYS[theme]}
            ranges={SENTIMENT_RANGES}
          />
        );
      })}
      <style>{`
        @media (max-width: 767px) {
          .sentiment-row { grid-template-columns: repeat(2, minmax(0, 1fr)) !important; gap: 16px !important; }
        }
        @media (max-width: 399px) {
          .sentiment-row { grid-template-columns: 1fr !important; }
        }
      `}</style>
    </div>
  );
}
