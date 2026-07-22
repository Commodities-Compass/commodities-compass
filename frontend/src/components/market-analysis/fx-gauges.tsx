import { useTranslation } from 'react-i18next';
import GaugeIndicator from '@/components/gauge-indicator';
import { Eyebrow } from '@/components/editorial';
import GroupHeader from './group-header';
import type { MacroPanelResponse } from '@/types/dashboard';
import { MACRO_RANGES, gridStyle5 } from './helpers';

interface FxGaugesProps {
  macro?: MacroPanelResponse;
}

/**
 * Daily FX gauges — DXY proxy, GBPUSD, and the FCFA (XOF/GBP) conversion.
 * ENSO/Niño (monthly, non-daily) live in the Reference strata, not here.
 */
export default function FxGauges({ macro }: FxGaugesProps) {
  const { t } = useTranslation();
  return (
    <div style={{ marginBottom: 28 }}>
      <GroupHeader name={t('market.grp_fx')} cadence={t('market.cad_daily')} />
      <div className="gauges-row" style={gridStyle5}>
        <GaugeIndicator
          value={macro?.fx_dxy_proxy ?? MACRO_RANGES.FX_DXY.min}
          min={MACRO_RANGES.FX_DXY.min}
          max={MACRO_RANGES.FX_DXY.max}
          label="FX DXY"
          ranges={MACRO_RANGES.FX_DXY.ranges}
        />
        <GaugeIndicator
          value={macro?.fx_gbpusd ?? MACRO_RANGES.FX_GBPUSD.min}
          min={MACRO_RANGES.FX_GBPUSD.min}
          max={MACRO_RANGES.FX_GBPUSD.max}
          label="GBPUSD"
          ranges={MACRO_RANGES.FX_GBPUSD.ranges}
        />
        <GaugeIndicator
          value={macro?.fx_xofgbp ?? MACRO_RANGES.FX_XOFGBP.min}
          min={MACRO_RANGES.FX_XOFGBP.min}
          max={MACRO_RANGES.FX_XOFGBP.max}
          label="XOF/GBP"
          ranges={MACRO_RANGES.FX_XOFGBP.ranges}
        />
      </div>
      {macro?.fx_xofgbp != null && (
        <div style={{ marginTop: 8 }}>
          <Eyebrow tone="subtle" size={9}>
            {t('market.xofgbp_peg')}
          </Eyebrow>
        </div>
      )}
    </div>
  );
}
