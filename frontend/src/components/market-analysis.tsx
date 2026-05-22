import GaugeIndicator from '@/components/gauge-indicator';
import EditorialTabs from '@/components/editorial-tabs';
import SectionHeader from '@/components/section-header';
import { Eyebrow, DataValue } from '@/components/editorial';
import { Loader2 } from 'lucide-react';
import {
  useIndicatorsGrid,
  useRecommendations,
  usePositionStatus,
  useMacroPanel,
  usePositioning,
} from '@/hooks/useDashboard';
import { parseConclusion, formatRecoText } from '@/utils/recommendation-parser';
import type { IndicatorRange } from '@/types/dashboard';

interface MarketAnalysisProps {
  targetDate?: string;
  className?: string;
}

const INDICATOR_KEYS = ['macd', 'volOi', 'rsi', 'percentK', 'atr'] as const;

// Editorial ranges for the macro + positioning gauges. Editorial defaults
// (not from pl_test_range which only covers the 5 technical indicators).
const MACRO_RANGES: Record<string, { min: number; max: number; ranges: IndicatorRange[] }> = {
  FX_DXY: {
    min: 0.85,
    max: 1.1,
    ranges: [
      { range_low: 0.98, range_high: 1.1, area: 'RED' },
      { range_low: 0.92, range_high: 0.98, area: 'ORANGE' },
      { range_low: 0.85, range_high: 0.92, area: 'GREEN' },
    ],
  },
  FX_GBPUSD: {
    min: 1.1,
    max: 1.45,
    ranges: [
      { range_low: 1.1, range_high: 1.22, area: 'RED' },
      { range_low: 1.22, range_high: 1.32, area: 'ORANGE' },
      { range_low: 1.32, range_high: 1.45, area: 'GREEN' },
    ],
  },
  ENSO_ONI: {
    min: -2,
    max: 2,
    ranges: [
      { range_low: -2, range_high: -0.5, area: 'RED' },
      { range_low: -0.5, range_high: 0.5, area: 'ORANGE' },
      { range_low: 0.5, range_high: 2, area: 'GREEN' },
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
  COT_MM: {
    min: -40000,
    max: 60000,
    ranges: [
      { range_low: -40000, range_high: 0, area: 'RED' },
      { range_low: 0, range_high: 20000, area: 'ORANGE' },
      { range_low: 20000, range_high: 60000, area: 'GREEN' },
    ],
  },
  STOCK_EU: {
    min: 500_000,
    max: 8_000_000,
    ranges: [
      { range_low: 5_000_000, range_high: 8_000_000, area: 'RED' },
      { range_low: 2_000_000, range_high: 5_000_000, area: 'ORANGE' },
      { range_low: 500_000, range_high: 2_000_000, area: 'GREEN' },
    ],
  },
};

function fmtCompactInt(v?: number | null): string {
  if (v == null || !Number.isFinite(v)) return '—';
  const abs = Math.abs(v);
  if (abs >= 1_000_000) return `${(v / 1_000_000).toFixed(2)}M`;
  if (abs >= 1_000) return `${(v / 1_000).toFixed(1)}k`;
  return v.toFixed(0);
}

function fmtNum(v?: number | null, digits = 2): string {
  if (v == null || !Number.isFinite(v)) return '—';
  return v.toFixed(digits);
}

function fmtDate(iso?: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso + 'T00:00:00');
  if (Number.isNaN(d.getTime())) return iso;
  const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  return `${d.getDate()} ${months[d.getMonth()]} ${d.getFullYear()}`;
}

function EditorialParagraph({ children, dropcap = false }: { children: React.ReactNode; dropcap?: boolean }) {
  return (
    <p
      style={{
        fontFamily: 'var(--font-editorial)',
        fontSize: 15,
        lineHeight: 1.75,
        color: 'var(--ink-dark)',
        textAlign: 'justify',
        marginBottom: 14,
        hyphens: 'auto',
        WebkitHyphens: 'auto',
      }}
      className={dropcap ? 'has-dropcap' : undefined}
    >
      {children}
    </p>
  );
}

function ParagraphsList({ items }: { items: string[] }) {
  if (items.length === 0) {
    return (
      <p style={{ color: 'var(--ink-light)', fontStyle: 'italic', fontSize: 14 }}>
        Aucune information pour cette section.
      </p>
    );
  }
  return (
    <div>
      {items.map((p, i) => (
        <EditorialParagraph key={i} dropcap={i === 0}>
          {formatRecoText(p)}
        </EditorialParagraph>
      ))}
      <style>{`
        .has-dropcap::first-letter {
          font-family: var(--font-display);
          font-size: 56px;
          font-weight: 700;
          float: left;
          line-height: 0.85;
          padding-right: 8px;
          padding-top: 4px;
          color: var(--ink);
        }
      `}</style>
    </div>
  );
}

function Watchlist({ items }: { items: string[] }) {
  if (items.length === 0) return null;
  return (
    <aside
      style={{
        padding: '18px 18px 16px',
        background: 'var(--paper-off)',
        borderLeft: '2px solid var(--ink)',
      }}
    >
      <div
        className="uppercase"
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 10,
          fontWeight: 600,
          letterSpacing: '0.22em',
          color: 'var(--ink-mid)',
          marginBottom: 12,
          paddingBottom: 8,
          borderBottom: '1px dotted var(--rule)',
        }}
      >
        À surveiller
      </div>
      <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
        {items.map((item, i) => (
          <li
            key={i}
            style={{
              fontFamily: 'var(--font-sans)',
              fontSize: 13,
              lineHeight: 1.55,
              color: 'var(--ink-dark)',
              marginBottom: 10,
              paddingLeft: 16,
              position: 'relative',
            }}
          >
            <span
              aria-hidden
              style={{
                position: 'absolute',
                left: 0,
                top: 9,
                width: 8,
                height: 1,
                background: 'var(--ink-mid)',
              }}
            />
            {formatRecoText(item)}
          </li>
        ))}
      </ul>
    </aside>
  );
}

const rowLabel: React.CSSProperties = {
  fontFamily: 'var(--font-mono)',
  fontSize: 10,
  textTransform: 'uppercase',
  letterSpacing: '0.12em',
  color: 'var(--ink-mid)',
};

export default function MarketAnalysis({ targetDate, className }: MarketAnalysisProps) {
  const { data: gridData, isLoading: gridLoading } = useIndicatorsGrid(targetDate);
  const { data: recoData, isLoading: recoLoading } = useRecommendations(targetDate);
  const { data: posData } = usePositionStatus(targetDate);
  const { data: macro } = useMacroPanel(targetDate);
  const { data: positioning } = usePositioning(targetDate);

  // Disclaimer when the day's decision is ensemble but the LLM narrative was
  // generated by the legacy daily-analysis job (which still writes conclusions).
  // Removed once Phase 8 ships ensemble-aligned narratives.
  const decisionAlgo = posData?.source_algorithm;
  const narrativeAlgo = recoData?.source_algorithm;
  const showNarrativeMismatch =
    decisionAlgo === 'ensemble_v1_softgate_wrapper' &&
    narrativeAlgo &&
    narrativeAlgo !== 'ensemble_v1_softgate_wrapper';

  const isLoading = gridLoading || recoLoading;
  const indicators = gridData?.indicators;
  const recommendations = recoData?.recommendations;
  const parsed = recommendations ? parseConclusion(recommendations) : { analysis: [], watchlist: [] };

  // Split analysis into 3 buckets — same distribution as before
  const split3 = (arr: string[]): [string[], string[], string[]] => {
    if (arr.length === 0) return [[], [], []];
    const per = Math.ceil(arr.length / 3);
    return [arr.slice(0, per), arr.slice(per, per * 2), arr.slice(per * 2)];
  };
  const [bucketReco, bucketSupply, bucketTechnical] = split3(parsed.analysis);

  const tabs = [
    { id: 'reco', label: 'Recommandation', badge: bucketReco.length > 0 ? String(bucketReco.length) : undefined },
    { id: 'supply', label: 'Supply & Momentum', badge: bucketSupply.length > 0 ? String(bucketSupply.length) : undefined },
    { id: 'technical', label: 'Technical Outlook', badge: bucketTechnical.length > 0 ? String(bucketTechnical.length) : undefined },
  ];

  return (
    <div className={className}>
      <section style={{ padding: '32px 0 24px' }}>
        <SectionHeader numeral="II" title="Market Analysis" />

        {/* Sub-block 1 — Compass Gauges (techniques) */}
        <div style={{ marginBottom: 28 }}>
          <Eyebrow as="div" tone="muted" size={10} style={{ marginBottom: 14, letterSpacing: '0.22em' }}>
            Compass Gauges · Techniques
          </Eyebrow>
          {indicators ? (
            <div
              className="gauges-row"
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(5, minmax(0, 1fr))',
                gap: 24,
                alignItems: 'start',
              }}
            >
              {INDICATOR_KEYS.map((key) =>
                indicators[key] ? (
                  <GaugeIndicator
                    key={key}
                    value={indicators[key].value}
                    min={indicators[key].min}
                    max={indicators[key].max}
                    label={indicators[key].label}
                    ranges={indicators[key].ranges}
                  />
                ) : null,
              )}
            </div>
          ) : (
            <p style={{ color: 'var(--ink-light)', fontSize: 14, textAlign: 'center' }}>
              Aucun indicateur disponible.
            </p>
          )}
        </div>

        {/* Sub-block 2 — Macro & FX */}
        <div style={{ marginBottom: 28 }}>
          <Eyebrow as="div" tone="muted" size={10} style={{ marginBottom: 14, letterSpacing: '0.22em' }}>
            Macro & FX
          </Eyebrow>
          <div
            className="macro-row"
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(4, minmax(0, 1fr))',
              gap: 24,
              alignItems: 'start',
            }}
          >
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
          {macro?.enso_reference_date && (
            <div style={{ marginTop: 8 }}>
              <Eyebrow tone="subtle" size={9}>
                ENSO reference {fmtDate(macro.enso_reference_date)} · 14-day lag policy
              </Eyebrow>
            </div>
          )}
        </div>

        {/* Sub-block 3 — Positioning & Supply */}
        <div style={{ marginBottom: 28 }}>
          <Eyebrow as="div" tone="muted" size={10} style={{ marginBottom: 14, letterSpacing: '0.22em' }}>
            Positioning & Supply
          </Eyebrow>
          <div
            className="positioning-row"
            style={{
              display: 'grid',
              gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1fr) minmax(0, 1.4fr)',
              gap: 24,
              alignItems: 'start',
            }}
          >
            <GaugeIndicator
              value={positioning?.cot_managed_money_net ?? 0}
              min={MACRO_RANGES.COT_MM.min}
              max={MACRO_RANGES.COT_MM.max}
              label="COT MM NET"
              ranges={MACRO_RANGES.COT_MM.ranges}
            />
            <GaugeIndicator
              value={positioning?.stock_eu_bags60kg ?? MACRO_RANGES.STOCK_EU.min}
              min={MACRO_RANGES.STOCK_EU.min}
              max={MACRO_RANGES.STOCK_EU.max}
              label="STOCK EU"
              ranges={MACRO_RANGES.STOCK_EU.ranges}
            />
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
                <DataValue>{fmtCompactInt(positioning?.stock_us)}</DataValue>

                <span style={rowLabel}>Stock EU (60kg bags)</span>
                <DataValue>{fmtCompactInt(positioning?.stock_eu_bags60kg)}</DataValue>

                <span style={rowLabel}>Ratio EU/US (tonnes)</span>
                <DataValue>{fmtNum(positioning?.stock_eu_us_ratio, 2)}</DataValue>

                <span style={rowLabel}>COT MM long</span>
                <DataValue>{fmtCompactInt(positioning?.cot_managed_money_long)}</DataValue>

                <span style={rowLabel}>COT MM short</span>
                <DataValue>{fmtCompactInt(positioning?.cot_managed_money_short)}</DataValue>

                <span style={rowLabel}>COT Prod/Merch net</span>
                <DataValue>{fmtCompactInt(positioning?.cot_producer_merchant_net)}</DataValue>
              </div>
              {(positioning?.cot_release_date || positioning?.cot_report_date) && (
                <div style={{ marginTop: 12, paddingTop: 10, borderTop: '1px solid var(--rule)' }}>
                  <Eyebrow tone="subtle" size={9}>
                    COT release {fmtDate(positioning?.cot_release_date)} · report {fmtDate(positioning?.cot_report_date)}
                  </Eyebrow>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Dotted separator between gauges and editorial body */}
        <div
          aria-hidden
          style={{
            height: 1,
            borderTop: '1px dotted var(--rule)',
            marginBottom: 28,
          }}
        />

        {/* Sub-block 4 — Editorial analysis (tabs + sidebar) */}
        {isLoading ? (
          <div className="flex items-center justify-center py-16" style={{ color: 'var(--ink-light)' }}>
            <Loader2 className="h-5 w-5 animate-spin mr-2" />
            <span className="text-sm">Chargement de l'analyse...</span>
          </div>
        ) : (
          <div
            className="market-grid"
            style={{
              display: 'grid',
              gridTemplateColumns: 'minmax(0, 2fr) minmax(0, 1fr)',
              gap: 40,
            }}
          >
            <div>
              {showNarrativeMismatch && (
                <div style={{ marginBottom: 12 }}>
                  <Eyebrow
                    as="div"
                    tone="muted"
                    size={9}
                    style={{
                      padding: '6px 10px',
                      borderLeft: '2px solid var(--color-signal-monitor)',
                      background: 'rgba(245, 158, 11, 0.05)',
                    }}
                  >
                    Décision algo ensemble · Narrative legacy
                  </Eyebrow>
                </div>
              )}
              <EditorialTabs
                tabs={tabs}
                panels={{
                  reco: <ParagraphsList items={bucketReco} />,
                  supply: <ParagraphsList items={bucketSupply} />,
                  technical: <ParagraphsList items={bucketTechnical} />,
                }}
              />
            </div>
            <Watchlist items={parsed.watchlist} />
          </div>
        )}
      </section>

      <style>{`
        @media (max-width: 1023px) {
          .market-grid { grid-template-columns: 1fr !important; }
        }
        @media (max-width: 767px) {
          .gauges-row { grid-template-columns: repeat(3, minmax(0, 1fr)) !important; }
          .macro-row { grid-template-columns: repeat(2, minmax(0, 1fr)) !important; }
          .positioning-row { grid-template-columns: 1fr !important; }
        }
        @media (max-width: 479px) {
          .gauges-row { grid-template-columns: repeat(2, minmax(0, 1fr)) !important; gap: 16px !important; }
        }
      `}</style>
    </div>
  );
}
