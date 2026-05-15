import { cn } from '@/utils';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';
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
  value: number;
  min: number;
  max: number;
  label: string;
  ranges?: IndicatorRange[];
  className?: string;
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
}: RulerGaugeProps) {
  const span = max - min || 1;
  const pct = Math.max(0, Math.min(100, ((value - min) / span) * 100));
  const zone = zoneOf(value, ranges);
  const [t1, t2] = zoneBounds(ranges, min, max);
  const meta = INDICATOR_META[label];

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
        {/* Value label (top) */}
        <span
          className="tabular-nums"
          style={{
            position: 'absolute',
            top: 0,
            left: `${pct}%`,
            transform: 'translateX(-50%)',
            fontFamily: 'var(--font-mono)',
            fontSize: 12,
            fontWeight: 700,
            color: 'var(--ink)',
            whiteSpace: 'nowrap',
          }}
        >
          {value != null ? value.toFixed(2) : '—'}
        </span>

        {/* Triangle marker */}
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

      {/* Zone labels */}
      <div
        className="flex justify-between"
        style={{ marginTop: 6 }}
      >
        <span style={zoneLabelStyle}>Hedge</span>
        <span style={{ ...zoneLabelStyle, textAlign: 'center' }}>Monitor</span>
        <span style={zoneLabelStyle}>Open</span>
      </div>
    </div>
  );

  if (!meta) return gauge;

  return (
    <TooltipProvider delayDuration={150}>
      <Tooltip>
        <TooltipTrigger asChild>{gauge}</TooltipTrigger>
        <TooltipContent side="top" className="max-w-60 px-3 py-2 space-y-1.5">
          <p className="text-xs font-semibold">{meta.fullName}</p>
          <p className="text-[11px] text-muted-foreground leading-snug">{meta.description}</p>
          <div className="flex items-center gap-1.5 pt-0.5">
            <span
              className="h-1.5 w-1.5 rounded-full"
              style={{ background: SIGNAL_HEX[zone] }}
            />
            <span className="text-[11px] font-medium">{meta.zones[zone]}</span>
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
