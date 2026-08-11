import { useTranslation } from 'react-i18next';
import GaugeIndicator from '@/components/gauge-indicator';
import Socle, { type SocleEntry } from './socle';
import type { PositioningResponse } from '@/types/dashboard';
import {
  MACRO_RANGES,
  gridStyle,
  fmtCompactInt,
  fmtTonnes,
  fmtNum,
  fmtDate,
} from './helpers';

interface PositioningGaugesProps {
  positioning?: PositioningResponse;
}

export default function PositioningGauges({
  positioning,
}: PositioningGaugesProps) {
  const { t } = useTranslation();

  const entries: SocleEntry[] = [
    {
      label: 'COT MM EU long',
      value: fmtCompactInt(positioning?.cot_managed_money_long),
    },
    {
      label: 'COT MM EU short',
      value: fmtCompactInt(positioning?.cot_managed_money_short),
    },
    {
      label: 'COT MM US long',
      value: fmtCompactInt(positioning?.cot_us_managed_money_long),
    },
    {
      label: 'COT MM US short',
      value: fmtCompactInt(positioning?.cot_us_managed_money_short),
    },
    {
      label: 'COT P/M net EU',
      value: fmtCompactInt(positioning?.cot_producer_merchant_net),
    },
    {
      label: 'COT P/M net US',
      value: fmtCompactInt(positioning?.cot_us_producer_merchant_net),
    },
    {
      label: t('market.socle_ratio_eu_us'),
      value: fmtNum(positioning?.stock_eu_us_ratio, 2),
    },
  ];

  // Release dates are context, not readings — dimmed, and only when present.
  const releases: Array<[string, string | null | undefined]> = [
    ['Stock EU release', positioning?.stock_eu_report_date],
    ['Stock US release', positioning?.stock_us_report_date],
    ['COT EU release', positioning?.cot_release_date],
    ['COT US release', positioning?.cot_us_release_date],
  ];
  releases.forEach(([label, value]) => {
    if (value) entries.push({ label, value: fmtDate(value), muted: true });
  });

  return (
    <div>
      <div className="gauges-row" style={gridStyle(4)}>
        <GaugeIndicator
          value={positioning?.cot_managed_money_net ?? 0}
          min={MACRO_RANGES.COT_MM_EU.min}
          max={MACRO_RANGES.COT_MM_EU.max}
          label="COT MM NET EU"
          ranges={MACRO_RANGES.COT_MM_EU.ranges}
        />
        <GaugeIndicator
          value={positioning?.cot_us_managed_money_net ?? 0}
          min={MACRO_RANGES.COT_MM_US.min}
          max={MACRO_RANGES.COT_MM_US.max}
          label="COT MM NET US"
          ranges={MACRO_RANGES.COT_MM_US.ranges}
        />
        <GaugeIndicator
          value={positioning?.stock_eu_tonnes ?? null}
          min={MACRO_RANGES.STOCK_EU.min}
          max={MACRO_RANGES.STOCK_EU.max}
          label="STOCK EU"
          ranges={MACRO_RANGES.STOCK_EU.ranges}
          formatValue={fmtTonnes}
        />
        <GaugeIndicator
          value={positioning?.stock_us_tonnes ?? null}
          min={MACRO_RANGES.STOCK_US.min}
          max={MACRO_RANGES.STOCK_US.max}
          label="STOCK US"
          ranges={MACRO_RANGES.STOCK_US.ranges}
          formatValue={fmtTonnes}
        />
      </div>
      <Socle entries={entries} />
    </div>
  );
}
