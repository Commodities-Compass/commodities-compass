import { cn } from '@/utils';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { useIsTouch } from '@/hooks/useIsTouch';
import type { IndicatorRange } from '@/types/dashboard';

interface IndicatorMeta {
  fullName: string;
  description: string;
  zones: { RED: string; ORANGE: string; GREEN: string };
}

const INDICATOR_META: Record<string, IndicatorMeta> = {
  MACROECO: {
    fullName: 'Macro-Économique',
    description: "Score macro issu de l'analyse LLM (météo, fondamentaux, contexte global)",
    zones: { RED: 'Contexte défavorable', ORANGE: 'Contexte neutre', GREEN: 'Contexte porteur' },
  },
  RSI: {
    fullName: 'Relative Strength Index',
    description: 'Vitesse et amplitude des mouvements de prix sur 14 jours',
    zones: { RED: 'Survendu — pression vendeuse', ORANGE: 'Zone neutre', GREEN: 'Momentum haussier' },
  },
  MACD: {
    fullName: 'MACD',
    description: 'Changements de tendance via croisement de moyennes mobiles',
    zones: { RED: 'Signal baissier', ORANGE: 'Pas de signal clair', GREEN: 'Signal haussier' },
  },
  '%K': {
    fullName: 'Stochastique %K',
    description: 'Cours de clôture vs fourchette haute-basse',
    zones: { RED: 'Survendu (<20%)', ORANGE: 'Zone neutre', GREEN: 'Momentum fort (>80%)' },
  },
  ATR: {
    fullName: 'Average True Range',
    description: 'Volatilité moyenne du marché (Wilder, 14j)',
    zones: { RED: 'Volatilité faible', ORANGE: 'Volatilité normale', GREEN: 'Volatilité élevée' },
  },
  'VOL/OI': {
    fullName: 'Volume / Open Interest',
    description: 'Ratio volume de trading / positions ouvertes',
    zones: { RED: 'Activité faible', ORANGE: 'Activité normale', GREEN: 'Conviction forte' },
  },
  // Macro & FX
  'FX DXY': {
    fullName: 'Dollar Index proxy',
    description: 'Force du dollar (1 / EURUSD). Un USD fort pèse sur les commodités cotées en USD.',
    zones: {
      RED: 'USD fort — pression baissière',
      ORANGE: 'USD neutre',
      GREEN: 'USD faible — soutien commodités',
    },
  },
  GBPUSD: {
    fullName: 'Livre / Dollar',
    description: 'Devise de cotation du cocoa Londres. Une livre forte renchérit le contrat en USD.',
    zones: {
      RED: 'GBP faible — discount London',
      ORANGE: 'Zone neutre',
      GREEN: 'GBP forte — premium London',
    },
  },
  'ENSO ONI': {
    fullName: 'Oceanic Niño Index',
    description: 'Anomalie de température de surface Pacifique équatorial (moyenne 3 mois).',
    zones: {
      RED: 'La Niña — risque sec Afrique',
      ORANGE: 'Phase ENSO neutre',
      GREEN: 'El Niño — humidité Afrique',
    },
  },
  'NIÑO 3.4': {
    fullName: 'Anomalie Niño 3.4',
    description: 'Anomalie SST zone Niño 3.4 — signal climatique mensuel, lag 14 jours.',
    zones: {
      RED: 'Refroidissement (La Niña)',
      ORANGE: 'Anomalie neutre',
      GREEN: 'Réchauffement (El Niño)',
    },
  },
  // Positioning & Supply
  'COT MM NET EU': {
    fullName: 'Managed Money — net (ICE Europe)',
    description:
      'Position nette des Managed Money sur le contrat cacao ICE Europe (London #7), publiée hebdomadairement (long − short).',
    zones: {
      RED: 'Net short — sentiment baissier',
      ORANGE: 'Net léger — pas de conviction',
      GREEN: 'Net long — sentiment haussier',
    },
  },
  'COT MM NET US': {
    fullName: 'Managed Money — net (CFTC US)',
    description:
      'Position nette des Managed Money sur le contrat cacao NY (CFTC Disaggregated Cocoa, ICE US Futures), publiée hebdomadairement (long − short).',
    zones: {
      RED: 'Net short — sentiment baissier',
      ORANGE: 'Net léger — pas de conviction',
      GREEN: 'Net long — sentiment haussier',
    },
  },
  'STOCK EU': {
    fullName: 'Stocks certifiés ICE Europe',
    description: 'Stocks de fèves certifiés en entrepôts ICE Europe (sacs 60 kg). Stocks élevés = pression baissière.',
    zones: {
      RED: 'Stocks élevés — pression vendeuse',
      ORANGE: 'Stocks moyens',
      GREEN: 'Stocks bas — tension offre',
    },
  },
  'STOCK US': {
    fullName: 'Stocks certifiés ICE US',
    description: 'Stocks de fèves certifiés en entrepôts ICE US (tonnes). Stocks élevés = pression baissière.',
    zones: {
      RED: 'Stocks élevés — pression vendeuse',
      ORANGE: 'Stocks moyens',
      GREEN: 'Stocks bas — tension offre',
    },
  },
  PRODUCTION: {
    fullName: 'Sentiment Production',
    description: 'Ton de la presse sur la production cacao',
    zones: { RED: "Récit baissier — tensions sur l'offre", ORANGE: 'Ton neutre', GREEN: 'Récit haussier' },
  },
  CHOCOLAT: {
    fullName: 'Sentiment Chocolat',
    description: 'Ton de la presse sur la demande chocolat',
    zones: { RED: 'Demande en repli', ORANGE: 'Demande stable', GREEN: 'Demande soutenue' },
  },
  'TRANSF.': {
    fullName: 'Sentiment Transformation',
    description: 'Ton de la presse sur la transformation',
    zones: { RED: 'Activité en baisse', ORANGE: 'Activité stable', GREEN: 'Activité en hausse' },
  },
  'ÉCONOMIE': {
    fullName: 'Sentiment Économie',
    description: 'Ton de la presse macro-économique',
    zones: { RED: 'Contexte défavorable', ORANGE: 'Contexte neutre', GREEN: 'Contexte porteur' },
  },
};

interface RulerGaugeProps {
  /** Numeric value to plot. Pass `null` to render a "no data" gauge (no marker, "—" label). */
  value: number | null;
  min: number;
  max: number;
  label: string;
  ranges?: IndicatorRange[];
  className?: string;
  /** Optional formatter for the value label. Defaults to `v.toFixed(2)`. */
  formatValue?: (v: number) => string;
  /**
   * When `true`, swap the bottom zone labels from `HEDGE | MONITOR | OPEN`
   * to `OPEN | MONITOR | HEDGE`. Use for inverse-relation indicators where
   * LOW values are bullish (= OPEN signal) and HIGH values are bearish
   * (= HEDGE signal) — typically certified-stock gauges, since the
   * value→position mapping puts low values on the left where OPEN now sits.
   */
  inverted?: boolean;
}

function zoneOf(value: number, ranges?: IndicatorRange[]): 'RED' | 'ORANGE' | 'GREEN' {
  if (ranges && ranges.length > 0) {
    for (const r of ranges) {
      const lo = Math.min(r.range_low, r.range_high);
      const hi = Math.max(r.range_low, r.range_high);
      if (value >= lo && value <= hi) return r.area;
    }
  }
  return 'ORANGE';
}

/**
 * Compute the two inner tick positions (in %) that split the [min, max] line
 * into the 3 zones HEDGE / MONITOR / OPEN. Sorts the ranges by midpoint and
 * uses each range's upper bound as the boundary.
 */
function zoneBounds(ranges: IndicatorRange[] | undefined, min: number, max: number): [number, number] {
  const span = max - min || 1;
  if (!ranges || ranges.length < 2) return [33.33, 66.66];
  const sorted = [...ranges].sort(
    (a, b) =>
      (a.range_low + a.range_high) / 2 - (b.range_low + b.range_high) / 2,
  );
  const upper = (r: IndicatorRange) => Math.max(r.range_low, r.range_high);
  const b1 = Math.max(0, Math.min(100, ((upper(sorted[0]) - min) / span) * 100));
  const second = sorted.length >= 3 ? sorted[1] : sorted[0];
  const b2 = Math.max(0, Math.min(100, ((upper(second) - min) / span) * 100));
  return [b1, b2];
}

const SIGNAL_HEX = {
  RED: '#EF4444',
  ORANGE: '#F59E0B',
  GREEN: '#10B981',
} as const;

export default function GaugeIndicator({
  value,
  min,
  max,
  label,
  ranges,
  className,
  formatValue,
  inverted = false,
}: RulerGaugeProps) {
  const span = max - min || 1;
  const hasValue = value != null && Number.isFinite(value);
  const pct = hasValue
    ? Math.max(0, Math.min(100, ((value! - min) / span) * 100))
    : 0;
  const zone = hasValue ? zoneOf(value!, ranges) : 'ORANGE';
  const [t1, t2] = zoneBounds(ranges, min, max);
  const meta = INDICATOR_META[label];
  const isTouch = useIsTouch();

  const gauge = (
    <div className={cn('flex flex-col items-stretch select-none', className)} style={{ width: '100%' }}>
      {/* Indicator label */}
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

      {/* Ruler */}
      <div
        style={{
          position: 'relative',
          paddingTop: 28,
          paddingBottom: 4,
        }}
      >
        {/* Value label (top) — centered when no data, else above the marker */}
        <span
          className="tabular-nums"
          style={{
            position: 'absolute',
            top: 0,
            left: hasValue ? `${pct}%` : '50%',
            transform: 'translateX(-50%)',
            fontFamily: 'var(--font-mono)',
            fontSize: 12,
            fontWeight: 700,
            color: hasValue ? 'var(--ink)' : 'var(--ink-light)',
            whiteSpace: 'nowrap',
          }}
        >
          {hasValue
            ? (formatValue ? formatValue(value!) : value!.toFixed(2))
            : '—'}
        </span>

        {/* Triangle marker — suppressed when no data so we never imply a position */}
        {hasValue && (
          <span
            style={{
              position: 'absolute',
              top: 16,
              left: `${pct}%`,
              transform: 'translateX(-50%)',
              fontSize: 10,
              lineHeight: 1,
              color: SIGNAL_HEX[zone],
            }}
          >
            {'▼'}
          </span>
        )}

        {/* Ruler line */}
        <div
          style={{
            position: 'relative',
            width: '100%',
            height: 1,
            background: 'var(--ink)',
          }}
        >
          {/* Ticks */}
          <span style={tickStyle(0, true)} />
          <span style={tickStyle(t1, false)} />
          <span style={tickStyle(t2, false)} />
          <span style={tickStyle(100, true)} />
        </div>
      </div>

      {/* Zone labels — order depends on `inverted` (inverse-relation gauges
          like stocks put OPEN on the LEFT because their value→position
          mapping makes low values land near the GREEN/leftmost zone). */}
      <div
        className="flex justify-between"
        style={{ marginTop: 6 }}
      >
        <span style={zoneLabelStyle}>{inverted ? 'Open' : 'Hedge'}</span>
        <span style={{ ...zoneLabelStyle, textAlign: 'center' }}>Monitor</span>
        <span style={zoneLabelStyle}>{inverted ? 'Hedge' : 'Open'}</span>
      </div>
    </div>
  );

  if (!meta || isTouch) return gauge;

  return (
    <TooltipProvider delayDuration={200}>
      <Tooltip>
        <TooltipTrigger asChild>{gauge}</TooltipTrigger>
        <TooltipContent
          side="top"
          sideOffset={10}
          className="max-w-70 p-0 border-0 rounded-none shadow-[0_8px_20px_rgba(0,0,0,0.25)] data-[state=open]:zoom-in-100 data-[state=closed]:zoom-out-100"
          style={{
            background: 'var(--ink)',
            color: 'var(--paper)',
            borderRadius: 0,
            borderLeft: `2px solid ${SIGNAL_HEX[zone]}`,
          }}
        >
          <div style={{ padding: '12px 14px 12px 12px' }}>
            <div
              className="uppercase"
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 10,
                fontWeight: 600,
                letterSpacing: '0.22em',
                color: 'var(--paper)',
                marginBottom: 8,
              }}
            >
              {meta.fullName}
            </div>
            <div
              style={{
                fontFamily: 'var(--font-sans)',
                fontSize: 12,
                lineHeight: 1.55,
                color: '#CFCFCF',
                marginBottom: 10,
              }}
            >
              {meta.description}
            </div>
            <div
              aria-hidden
              style={{
                height: 1,
                borderTop: '1px dotted rgba(255,255,255,0.18)',
                marginBottom: 10,
              }}
            />
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span
                style={{
                  width: 6,
                  height: 6,
                  borderRadius: '50%',
                  background: SIGNAL_HEX[zone],
                  flexShrink: 0,
                }}
              />
              <span
                className="uppercase"
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: 10,
                  fontWeight: 600,
                  letterSpacing: '0.18em',
                  color: 'var(--paper)',
                }}
              >
                {meta.zones[zone]}
              </span>
            </div>
          </div>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

const zoneLabelStyle: React.CSSProperties = {
  fontFamily: 'var(--font-sans)',
  fontSize: 8,
  fontWeight: 600,
  textTransform: 'uppercase',
  letterSpacing: '0.12em',
  color: 'var(--ink-light)',
};

function tickStyle(leftPct: number, isEnd: boolean): React.CSSProperties {
  return {
    position: 'absolute',
    left: `${leftPct}%`,
    top: isEnd ? -2.5 : -4,
    width: 1,
    height: isEnd ? 6 : 9,
    background: 'var(--ink-dark)',
    transform: leftPct === 100 ? 'translateX(-100%)' : leftPct === 0 ? 'none' : 'translateX(-50%)',
  };
}
