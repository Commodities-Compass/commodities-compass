import { useTranslation } from 'react-i18next';
import GaugeIndicator from '@/components/gauge-indicator';
import { Eyebrow, DataValue } from '@/components/editorial';
import GroupHeader from './group-header';
import type { PositioningResponse } from '@/types/dashboard';
import {
  MACRO_RANGES,
  gridStyle4,
  fmtCompactInt,
  fmtTonnes,
  fmtNum,
  fmtDate,
  inlineCell,
} from './helpers';

interface PositioningGaugesProps {
  positioning?: PositioningResponse;
}

export default function PositioningGauges({
  positioning,
}: PositioningGaugesProps) {
  const { t } = useTranslation();
  return (
    <div style={{ marginBottom: 28 }}>
      <GroupHeader
        name={t('market.grp_positioning')}
        cadence={t('market.cad_weekly')}
      />
      <div className="gauges-row" style={gridStyle4}>
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

      {/* Thin caption row — supplementary positioning context, no card */}
      <div
        className="positioning-caption"
        style={{
          marginTop: 18,
          display: 'flex',
          flexWrap: 'wrap',
          alignItems: 'baseline',
          columnGap: 24,
          rowGap: 8,
          borderTop: '1px dotted var(--rule)',
          paddingTop: 12,
        }}
      >
        <span style={inlineCell}>
          <Eyebrow tone="subtle" size={9}>
            COT MM EU long
          </Eyebrow>
          <DataValue size={11}>
            {fmtCompactInt(positioning?.cot_managed_money_long)}
          </DataValue>
        </span>
        <span style={inlineCell}>
          <Eyebrow tone="subtle" size={9}>
            COT MM EU short
          </Eyebrow>
          <DataValue size={11}>
            {fmtCompactInt(positioning?.cot_managed_money_short)}
          </DataValue>
        </span>
        <span style={inlineCell}>
          <Eyebrow tone="subtle" size={9}>
            COT MM US long
          </Eyebrow>
          <DataValue size={11}>
            {fmtCompactInt(positioning?.cot_us_managed_money_long)}
          </DataValue>
        </span>
        <span style={inlineCell}>
          <Eyebrow tone="subtle" size={9}>
            COT MM US short
          </Eyebrow>
          <DataValue size={11}>
            {fmtCompactInt(positioning?.cot_us_managed_money_short)}
          </DataValue>
        </span>
        <span style={inlineCell}>
          <Eyebrow tone="subtle" size={9}>
            COT P/M net EU
          </Eyebrow>
          <DataValue size={11}>
            {fmtCompactInt(positioning?.cot_producer_merchant_net)}
          </DataValue>
        </span>
        <span style={inlineCell}>
          <Eyebrow tone="subtle" size={9}>
            COT P/M net US
          </Eyebrow>
          <DataValue size={11}>
            {fmtCompactInt(positioning?.cot_us_producer_merchant_net)}
          </DataValue>
        </span>
        <span style={inlineCell}>
          <Eyebrow tone="subtle" size={9}>
            Ratio EU/US (tonnes)
          </Eyebrow>
          <DataValue size={11}>
            {fmtNum(positioning?.stock_eu_us_ratio, 2)}
          </DataValue>
        </span>
        {positioning?.stock_eu_report_date && (
          <span style={inlineCell}>
            <Eyebrow tone="subtle" size={9}>
              Stock EU release
            </Eyebrow>
            <DataValue size={11} color="var(--ink-mid)">
              {fmtDate(positioning.stock_eu_report_date)}
            </DataValue>
          </span>
        )}
        {positioning?.stock_us_report_date && (
          <span style={inlineCell}>
            <Eyebrow tone="subtle" size={9}>
              Stock US release
            </Eyebrow>
            <DataValue size={11} color="var(--ink-mid)">
              {fmtDate(positioning.stock_us_report_date)}
            </DataValue>
          </span>
        )}
        {positioning?.cot_release_date && (
          <span style={inlineCell}>
            <Eyebrow tone="subtle" size={9}>
              COT EU release
            </Eyebrow>
            <DataValue size={11} color="var(--ink-mid)">
              {fmtDate(positioning.cot_release_date)}
            </DataValue>
          </span>
        )}
        {positioning?.cot_us_release_date && (
          <span style={inlineCell}>
            <Eyebrow tone="subtle" size={9}>
              COT US release
            </Eyebrow>
            <DataValue size={11} color="var(--ink-mid)">
              {fmtDate(positioning.cot_us_release_date)}
            </DataValue>
          </span>
        )}
      </div>
    </div>
  );
}
