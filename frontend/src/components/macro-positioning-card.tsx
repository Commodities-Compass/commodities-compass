import { Loader2 } from 'lucide-react';
import SectionHeader from '@/components/section-header';
import GaugeIndicator from '@/components/gauge-indicator';
import { Eyebrow, DataValue } from '@/components/editorial';
import { useMacroPanel, usePositioning } from '@/hooks/useDashboard';
import type { IndicatorRange } from '@/types/dashboard';

interface MacroPositioningCardProps {
  targetDate?: string;
  className?: string;
}

/**
 * Section VI — MACRO & POSITIONING
 * Sub-block 1: 4 macro ruler gauges (FX DXY proxy, FX GBPUSD, ENSO ONI, Niño 3.4)
 * Sub-block 2: 2 positioning gauges (COT MM net, Stock EU) + compact stock table
 *
 * Ranges are editorial defaults chosen for cocoa price discovery — they don't
 * come from pl_test_range (which only covers the legacy 6 technical indicators).
 */

// Editorial ranges, ordered HEDGE → MONITOR → OPEN
const RANGES: Record<string, { min: number; max: number; ranges: IndicatorRange[] }> = {
  // USD strength proxy — strong USD bearish for cocoa (priced in USD)
  FX_DXY: {
    min: 0.85,
    max: 1.1,
    ranges: [
      { range_low: 0.98, range_high: 1.1, area: 'RED' }, // HEDGE
      { range_low: 0.92, range_high: 0.98, area: 'ORANGE' },
      { range_low: 0.85, range_high: 0.92, area: 'GREEN' }, // OPEN
    ],
  },
  // GBPUSD — strong GBP bullish for London cocoa #7
  FX_GBPUSD: {
    min: 1.1,
    max: 1.45,
    ranges: [
      { range_low: 1.1, range_high: 1.22, area: 'RED' },
      { range_low: 1.22, range_high: 1.32, area: 'ORANGE' },
      { range_low: 1.32, range_high: 1.45, area: 'GREEN' },
    ],
  },
  // ENSO ONI — El Niño (positive) bullish (West Africa drought)
  ENSO_ONI: {
    min: -2,
    max: 2,
    ranges: [
      { range_low: -2, range_high: -0.5, area: 'RED' }, // La Niña → wet → bearish
      { range_low: -0.5, range_high: 0.5, area: 'ORANGE' },
      { range_low: 0.5, range_high: 2, area: 'GREEN' }, // El Niño → dry → bullish
    ],
  },
  ENSO_NINO34: {
    min: -3,
    max: 3,
    ranges: [
      { range_low: -3, range_high: -0.5, area: 'RED' },
      { range_low: -0.5, range_high: 0.5, area: 'ORANGE' },
      { range_low: 0.5, range_high: 3, area: 'GREEN' },
    ],
  },
  // COT EU Managed Money net (cocoa London #7, contracts)
  COT_MM: {
    min: -40000,
    max: 60000,
    ranges: [
      { range_low: -40000, range_high: 0, area: 'RED' }, // specs short
      { range_low: 0, range_high: 20000, area: 'ORANGE' },
      { range_low: 20000, range_high: 60000, area: 'GREEN' }, // specs heavily long
    ],
  },
  // Stock EU certified (60kg bags) — high stocks bearish
  STOCK_EU: {
    min: 500_000,
    max: 8_000_000,
    ranges: [
      { range_low: 5_000_000, range_high: 8_000_000, area: 'RED' }, // abundant supply
      { range_low: 2_000_000, range_high: 5_000_000, area: 'ORANGE' },
      { range_low: 500_000, range_high: 2_000_000, area: 'GREEN' }, // tight
    ],
  },
};

function formatCompactInt(v?: number | null): string {
  if (v == null || !Number.isFinite(v)) return '—';
  const abs = Math.abs(v);
  if (abs >= 1_000_000) return `${(v / 1_000_000).toFixed(2)}M`;
  if (abs >= 1_000) return `${(v / 1_000).toFixed(1)}k`;
  return v.toFixed(0);
}

function formatNumber(v?: number | null, digits = 3): string {
  if (v == null || !Number.isFinite(v)) return '—';
  return v.toFixed(digits);
}

function formatDate(iso?: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso + 'T00:00:00');
  if (Number.isNaN(d.getTime())) return iso;
  const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  return `${d.getDate()} ${months[d.getMonth()]} ${d.getFullYear()}`;
}

export default function MacroPositioningCard({ targetDate, className }: MacroPositioningCardProps) {
  const macroQ = useMacroPanel(targetDate);
  const posQ = usePositioning(targetDate);

  if (macroQ.isLoading || posQ.isLoading) {
    return (
      <section className={className} style={{ padding: '32px 0' }}>
        <SectionHeader numeral="VI" title="Macro & Positioning" />
        <div className="flex items-center justify-center min-h-[200px]" style={{ color: 'var(--ink-light)' }}>
          <Loader2 className="h-5 w-5 animate-spin mr-2" />
          <span className="text-sm">Chargement des indicateurs macro & positionnement...</span>
        </div>
      </section>
    );
  }

  const macro = macroQ.data;
  const pos = posQ.data;

  return (
    <section className={className} style={{ padding: '32px 0' }}>
      <SectionHeader numeral="VI" title="Macro & Positioning" />

      {/* Sub-block 1 — Compass Macro */}
      <div style={{ marginBottom: 36 }}>
        <Eyebrow as="div" tone="primary" size={11} style={{ marginBottom: 14 }}>
          Compass Macro · FX & Climat
        </Eyebrow>

        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
            gap: 24,
            alignItems: 'start',
          }}
        >
          <GaugeIndicator
            value={macro?.fx_dxy_proxy ?? RANGES.FX_DXY.min}
            min={RANGES.FX_DXY.min}
            max={RANGES.FX_DXY.max}
            label="FX DXY"
            ranges={RANGES.FX_DXY.ranges}
          />
          <GaugeIndicator
            value={macro?.fx_gbpusd ?? RANGES.FX_GBPUSD.min}
            min={RANGES.FX_GBPUSD.min}
            max={RANGES.FX_GBPUSD.max}
            label="GBPUSD"
            ranges={RANGES.FX_GBPUSD.ranges}
          />
          <GaugeIndicator
            value={macro?.enso_oni_month ?? 0}
            min={RANGES.ENSO_ONI.min}
            max={RANGES.ENSO_ONI.max}
            label="ENSO ONI"
            ranges={RANGES.ENSO_ONI.ranges}
          />
          <GaugeIndicator
            value={macro?.enso_nino34_anomaly ?? 0}
            min={RANGES.ENSO_NINO34.min}
            max={RANGES.ENSO_NINO34.max}
            label="NIÑO 3.4"
            ranges={RANGES.ENSO_NINO34.ranges}
          />
        </div>

        {macro?.enso_reference_date && (
          <div style={{ marginTop: 12 }}>
            <Eyebrow tone="subtle" size={9}>
              ENSO reference {formatDate(macro.enso_reference_date)} · 14-day lag policy
            </Eyebrow>
          </div>
        )}
      </div>

      {/* Sub-block 2 — Positioning & Supply */}
      <div>
        <Eyebrow as="div" tone="primary" size={11} style={{ marginBottom: 14 }}>
          Positioning & Supply · COT & Stocks
        </Eyebrow>

        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1fr) minmax(0, 1.4fr)',
            gap: 24,
            alignItems: 'start',
          }}
          className="positioning-grid"
        >
          <GaugeIndicator
            value={pos?.cot_managed_money_net ?? 0}
            min={RANGES.COT_MM.min}
            max={RANGES.COT_MM.max}
            label="COT MM NET"
            ranges={RANGES.COT_MM.ranges}
          />
          <GaugeIndicator
            value={pos?.stock_eu_bags60kg ?? RANGES.STOCK_EU.min}
            min={RANGES.STOCK_EU.min}
            max={RANGES.STOCK_EU.max}
            label="STOCK EU"
            ranges={RANGES.STOCK_EU.ranges}
          />

          {/* Compact stock table */}
          <div
            style={{
              border: '1px solid var(--rule)',
              padding: '14px 16px',
            }}
          >
            <Eyebrow as="div" tone="muted" size={9} style={{ marginBottom: 10 }}>
              Stocks & flux
            </Eyebrow>
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: '1fr auto',
                gap: '8px 12px',
                rowGap: 8,
                fontSize: 11,
              }}
            >
              <span style={rowLabel}>Stock US (tonnes)</span>
              <DataValue>{formatCompactInt(pos?.stock_us)}</DataValue>

              <span style={rowLabel}>Stock EU (60kg bags)</span>
              <DataValue>{formatCompactInt(pos?.stock_eu_bags60kg)}</DataValue>

              <span style={rowLabel}>Ratio EU/US (tonnes)</span>
              <DataValue>{formatNumber(pos?.stock_eu_us_ratio, 2)}</DataValue>

              <span style={rowLabel}>COT MM long</span>
              <DataValue>{formatCompactInt(pos?.cot_managed_money_long)}</DataValue>

              <span style={rowLabel}>COT MM short</span>
              <DataValue>{formatCompactInt(pos?.cot_managed_money_short)}</DataValue>

              <span style={rowLabel}>COT Prod/Merch net</span>
              <DataValue>{formatCompactInt(pos?.cot_producer_merchant_net)}</DataValue>
            </div>

            {(pos?.cot_release_date || pos?.cot_report_date) && (
              <div style={{ marginTop: 12, paddingTop: 10, borderTop: '1px solid var(--rule)' }}>
                <Eyebrow tone="subtle" size={9}>
                  COT release {formatDate(pos?.cot_release_date)} · report {formatDate(pos?.cot_report_date)}
                </Eyebrow>
              </div>
            )}
          </div>
        </div>
      </div>

      <style>{`
        @media (max-width: 767px) {
          .positioning-grid {
            grid-template-columns: 1fr !important;
          }
        }
      `}</style>
    </section>
  );
}

const rowLabel: React.CSSProperties = {
  fontFamily: 'var(--font-mono)',
  fontSize: 10,
  textTransform: 'uppercase',
  letterSpacing: '0.12em',
  color: 'var(--ink-mid)',
};
