import GaugeIndicator from '@/components/gauge-indicator';
import { Eyebrow } from '@/components/editorial';
import type { MacroPanelResponse } from '@/types/dashboard';
import { MACRO_RANGES, gridStyle5, fmtDate } from './helpers';

interface MacroGaugesProps {
  macro?: MacroPanelResponse;
}

export default function MacroGauges({ macro }: MacroGaugesProps) {
  return (
    <div style={{ marginBottom: 28 }}>
      <Eyebrow
        as="div"
        tone="muted"
        size={10}
        style={{ marginBottom: 14, letterSpacing: '0.22em' }}
      >
        Macro & FX
      </Eyebrow>
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
        <GaugeIndicator
          value={macro?.enso_oni_month ?? 0}
          min={MACRO_RANGES.ENSO_ONI.min}
          max={MACRO_RANGES.ENSO_ONI.max}
          label="ENSO ONI"
          ranges={MACRO_RANGES.ENSO_ONI.ranges}
        />
        <GaugeIndicator
          value={macro?.enso_nino34_anomaly ?? 0}
          min={MACRO_RANGES.ENSO_NINO34.min}
          max={MACRO_RANGES.ENSO_NINO34.max}
          label="NIÑO 3.4"
          ranges={MACRO_RANGES.ENSO_NINO34.ranges}
        />
      </div>
      {macro?.fx_xofgbp != null && (
        <div style={{ marginTop: 8 }}>
          <Eyebrow tone="subtle" size={9}>
            XOF/GBP via fixed EUR peg (1 EUR = 655.957 XOF) · floats on GBP/EUR
            only
          </Eyebrow>
        </div>
      )}
      {macro?.enso_reference_date && (
        <div style={{ marginTop: 8 }}>
          <Eyebrow tone="subtle" size={9}>
            ENSO reference {fmtDate(macro.enso_reference_date)} · 14-day lag
            policy
          </Eyebrow>
        </div>
      )}
    </div>
  );
}
