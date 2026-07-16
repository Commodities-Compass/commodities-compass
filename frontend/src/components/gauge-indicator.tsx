import { useTranslation } from 'react-i18next';
import { cn } from '@/utils';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { useIsTouch } from '@/hooks/useIsTouch';
import type { IndicatorRange } from '@/types/dashboard';
import { INDICATOR_META_KEY } from '@/data/indicator-metadata';


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
}

function zoneOf(value: number, ranges?: IndicatorRange[]): 'RED' | 'ORANGE' | 'GREEN' {
  if (ranges && ranges.length > 0) {
    for (const r of ranges) {
      const lo = Math.min(r.range_low, r.range_high);
      const hi = Math.max(r.range_low, r.range_high);
      if (value >= lo && value <= hi) return r.area;
    }
    // Value falls outside every calibrated range. The marker gets clamped to
    // the nearest ruler edge (pct 0 or 100), so the color must match that edge
    // zone — never the ORANGE default, which would render a green-side marker
    // (e.g. VOL/OI below its lowest bound) as MONITOR.
    const sorted = sortRangesByMidpoint(ranges);
    const lowest = sorted[0];
    const lowestLo = Math.min(lowest.range_low, lowest.range_high);
    return value < lowestLo ? lowest.area : sorted[sorted.length - 1].area;
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
  const sorted = sortRangesByMidpoint(ranges);
  const upper = (r: IndicatorRange) => Math.max(r.range_low, r.range_high);
  const b1 = Math.max(0, Math.min(100, ((upper(sorted[0]) - min) / span) * 100));
  const second = sorted.length >= 3 ? sorted[1] : sorted[0];
  const b2 = Math.max(0, Math.min(100, ((upper(second) - min) / span) * 100));
  return [b1, b2];
}

function sortRangesByMidpoint(ranges: IndicatorRange[]): IndicatorRange[] {
  return [...ranges].sort(
    (a, b) =>
      (a.range_low + a.range_high) / 2 - (b.range_low + b.range_high) / 2,
  );
}

const AREA_TO_LABEL: Record<IndicatorRange['area'], string> = {
  RED: 'Hedge',
  ORANGE: 'Monitor',
  GREEN: 'Open',
};

/**
 * Derive the left/right zone labels from the actual leftmost/rightmost ranges.
 * The middle is always `Monitor`. Falls back to the default `Hedge|Open`
 * orientation when ranges are missing or ambiguous.
 */
function zoneLabels(ranges: IndicatorRange[] | undefined): [string, string] {
  if (!ranges || ranges.length < 2) return ['Hedge', 'Open'];
  const sorted = sortRangesByMidpoint(ranges);
  const left = AREA_TO_LABEL[sorted[0].area] ?? 'Hedge';
  const right = AREA_TO_LABEL[sorted[sorted.length - 1].area] ?? 'Open';
  return [left, right];
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
}: RulerGaugeProps) {
  const span = max - min || 1;
  const hasValue = value != null && Number.isFinite(value);
  const pct = hasValue
    ? Math.max(0, Math.min(100, ((value! - min) / span) * 100))
    : 0;
  const zone = hasValue ? zoneOf(value!, ranges) : 'ORANGE';
  const [t1, t2] = zoneBounds(ranges, min, max);
  const [leftLabel, rightLabel] = zoneLabels(ranges);
  const { t } = useTranslation();
  const metaKey = INDICATOR_META_KEY[label];
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

      {/* Zone labels — derived from the leftmost/rightmost range areas so the
          label under the marker always matches its color (inverse-relation
          gauges like stocks naturally render `OPEN | MONITOR | HEDGE`). */}
      <div
        className="flex justify-between"
        style={{ marginTop: 6 }}
      >
        <span style={zoneLabelStyle}>{leftLabel}</span>
        <span style={{ ...zoneLabelStyle, textAlign: 'center' }}>Monitor</span>
        <span style={zoneLabelStyle}>{rightLabel}</span>
      </div>
    </div>
  );

  if (!metaKey || isTouch) return gauge;

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
              {t(`indicators.${metaKey}_name`)}
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
              {t(`indicators.${metaKey}_desc`)}
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
                {t(`indicators.${metaKey}_zones_${zone.toLowerCase()}`)}
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
