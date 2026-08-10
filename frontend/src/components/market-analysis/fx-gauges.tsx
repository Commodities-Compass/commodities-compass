import { useTranslation } from 'react-i18next';
import GaugeIndicator from '@/components/gauge-indicator';
import Socle from './socle';
import type { MacroPanelResponse } from '@/types/dashboard';
import { MACRO_RANGES, gridStyle } from './helpers';

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
    <div>
      <div className="gauges-row" style={gridStyle(3)}>
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
      {macro?.fx_xofgbp != null && <Socle>{t('market.xofgbp_peg')}</Socle>}
    </div>
  );
}
