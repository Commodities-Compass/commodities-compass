import { cn } from "@/utils";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import type { IndicatorRange } from "@/types/dashboard";

// ---------------------------------------------------------------------------
// Indicator metadata — static, never changes, no need to store in DB
// ---------------------------------------------------------------------------

interface IndicatorMeta {
  fullName: string;
  description: string;
  zones: { RED: string; ORANGE: string; GREEN: string };
}

const INDICATOR_META: Record<string, IndicatorMeta> = {
  MACROECO: {
    fullName: "Macro-Économique",
    description:
      "Score macro issu de l'analyse LLM (météo, fondamentaux, contexte global)",
    zones: {
      RED: "Contexte défavorable",
      ORANGE: "Contexte neutre",
      GREEN: "Contexte porteur",
    },
  },
  RSI: {
    fullName: "Relative Strength Index",
    description:
      "Vitesse et amplitude des mouvements de prix sur 14 jours",
    zones: {
      RED: "Survendu — pression vendeuse",
      ORANGE: "Zone neutre",
      GREEN: "Momentum haussier",
    },
  },
  MACD: {
    fullName: "MACD",
    description:
      "Changements de tendance via croisement de moyennes mobiles",
    zones: {
      RED: "Signal baissier",
      ORANGE: "Pas de signal clair",
      GREEN: "Signal haussier",
    },
  },
  "%K": {
    fullName: "Stochastique %K",
    description:
      "Cours de clôture vs fourchette haute-basse",
    zones: {
      RED: "Survendu (<20%)",
      ORANGE: "Zone neutre",
      GREEN: "Momentum fort (>80%)",
    },
  },
  ATR: {
    fullName: "Average True Range",
    description: "Volatilité moyenne du marché (Wilder, 14j)",
    zones: {
      RED: "Volatilité faible",
      ORANGE: "Volatilité normale",
      GREEN: "Volatilité élevée",
    },
  },
  "VOL/OI": {
    fullName: "Volume / Open Interest",
    description: "Ratio volume de trading / positions ouvertes",
    zones: {
      RED: "Activité faible",
      ORANGE: "Activité normale",
      GREEN: "Conviction forte",
    },
  },
};

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface GaugeIndicatorProps {
  value: number;
  min: number;
  max: number;
  label: string;
  ranges?: IndicatorRange[];
  size?: "sm" | "md" | "lg";
  showValue?: boolean;
  showLabel?: boolean;
  className?: string;
}

export default function GaugeIndicator({
  value,
  min,
  max,
  label,
  ranges,
  size = "md",
  showValue = true,
  showLabel = true,
  className,
}: GaugeIndicatorProps) {
  const percentage = Math.max(
    0,
    Math.min(100, ((value - min) / (max - min)) * 100),
  );

  const meta = INDICATOR_META[label];
  const zone = getCurrentZone(value, percentage, ranges);
  const colorSections = generateColorSections(ranges, min, max);

  // SVG geometry
  const cx = 60;
  const cy = 55;
  const r = 46;

  const angle = Math.PI - (percentage / 100) * Math.PI;
  const mx = cx + r * Math.cos(angle);
  const my = cy - r * Math.abs(Math.sin(angle));

  const sizeClasses = {
    sm: "w-20 h-12",
    md: "w-28 h-18",
    lg: "w-36 h-22",
  };

  const gauge = (
    <div
      className={cn(
        "flex flex-col items-center rounded-md px-1 py-2 transition-colors duration-150",
        "hover:bg-muted/40 cursor-default",
        className,
      )}
    >
      <div className={cn("relative", sizeClasses[size])}>
        <svg
          className="w-full h-full"
          viewBox="0 0 120 68"
          xmlns="http://www.w3.org/2000/svg"
        >
          {/* Background arc */}
          <path
            d={`M${cx - r},${cy} A${r},${r} 0 0,1 ${cx + r},${cy}`}
            fill="none"
            stroke="currentColor"
            strokeWidth="4"
            strokeLinecap="round"
            className="text-muted/50"
          />

          {/* Colored zone arcs */}
          {colorSections.map((section, i) => (
            <path
              key={i}
              d={createArcPath(cx, cy, r, section.startAngle, section.endAngle)}
              fill="none"
              stroke="currentColor"
              strokeWidth="4"
              strokeLinecap="round"
              className={cn(section.color, "opacity-75")}
            />
          ))}

          {/* Needle */}
          <line
            x1={cx}
            y1={cy}
            x2={mx}
            y2={my}
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
            className="text-foreground/60"
          />
          <circle cx={cx} cy={cy} r="2" fill="currentColor" className="text-foreground/40" />

          {/* Marker dot */}
          <circle cx={mx} cy={my} r="3.5" fill="currentColor" className={zone.color} />
          <circle cx={mx} cy={my} r="1.8" fill="white" className="dark:fill-gray-900" />

          {/* Min / Max labels */}
          <text
            x={cx - r + 2}
            y={cy + 9}
            textAnchor="start"
            className="fill-muted-foreground"
            fontSize="9"
            fontFamily="system-ui"
          >
            {min.toFixed(1)}
          </text>
          <text
            x={cx + r - 2}
            y={cy + 9}
            textAnchor="end"
            className="fill-muted-foreground"
            fontSize="9"
            fontFamily="system-ui"
          >
            {max.toFixed(1)}
          </text>
        </svg>
      </div>

      {/* Value + label */}
      {(showValue || showLabel) && (
        <div className="flex flex-col items-center gap-0 -mt-0.5">
          {showValue && (
            <span
              className={cn(
                "text-sm font-bold tabular-nums leading-tight",
                zone.color,
              )}
            >
              {value != null ? value.toFixed(2) : "—"}
            </span>
          )}
          {showLabel && (
            <span className="text-[10px] font-medium text-muted-foreground tracking-wider uppercase">
              {label}
            </span>
          )}
        </div>
      )}
    </div>
  );

  if (!meta) return gauge;

  return (
    <TooltipProvider delayDuration={150}>
      <Tooltip>
        <TooltipTrigger asChild>{gauge}</TooltipTrigger>
        <TooltipContent side="top" className="max-w-[220px] px-3 py-2 space-y-1.5">
          <p className="text-xs font-semibold">{meta.fullName}</p>
          <p className="text-[11px] text-gray-400 leading-snug">
            {meta.description}
          </p>
          <div className="flex items-center gap-1.5 pt-0.5">
            <div className={cn("h-1.5 w-1.5 rounded-full", zoneDotColor(zone.area))} />
            <span className="text-[11px] font-medium">{meta.zones[zone.area]}</span>
          </div>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const ZONE_COLORS = {
  RED: "text-red-500",
  ORANGE: "text-amber-500",
  GREEN: "text-emerald-500",
} as const;

function zoneDotColor(area: "RED" | "ORANGE" | "GREEN"): string {
  if (area === "RED") return "bg-red-500";
  if (area === "ORANGE") return "bg-amber-500";
  return "bg-emerald-500";
}

function getCurrentZone(
  value: number,
  percentage: number,
  ranges: IndicatorRange[] | undefined,
): { area: "RED" | "ORANGE" | "GREEN"; color: string } {
  if (ranges && ranges.length > 0) {
    for (const range of ranges) {
      const lo = Math.min(range.range_low, range.range_high);
      const hi = Math.max(range.range_low, range.range_high);
      if (value >= lo && value <= hi) {
        return { area: range.area, color: ZONE_COLORS[range.area] };
      }
    }
  }
  if (percentage <= 33) return { area: "RED", color: ZONE_COLORS.RED };
  if (percentage <= 66) return { area: "ORANGE", color: ZONE_COLORS.ORANGE };
  return { area: "GREEN", color: ZONE_COLORS.GREEN };
}

function createArcPath(
  cx: number,
  cy: number,
  r: number,
  startAngle: number,
  endAngle: number,
): string {
  const sx = cx + r * Math.cos(startAngle);
  const sy = cy - r * Math.abs(Math.sin(startAngle));
  const ex = cx + r * Math.cos(endAngle);
  const ey = cy - r * Math.abs(Math.sin(endAngle));
  const largeArc = Math.abs(startAngle - endAngle) > Math.PI ? 1 : 0;
  return `M${sx},${sy} A${r},${r} 0 ${largeArc},1 ${ex},${ey}`;
}

function generateColorSections(
  ranges: IndicatorRange[] | undefined,
  min: number,
  max: number,
) {
  if (!ranges || ranges.length === 0) {
    return [
      { startAngle: Math.PI, endAngle: (Math.PI * 2) / 3, color: "text-red-500" },
      { startAngle: (Math.PI * 2) / 3, endAngle: Math.PI / 3, color: "text-amber-500" },
      { startAngle: Math.PI / 3, endAngle: 0, color: "text-emerald-500" },
    ];
  }

  const sorted = [...ranges].sort(
    (a, b) => (a.range_low + a.range_high) / 2 - (b.range_low + b.range_high) / 2,
  );

  return sorted.map((range) => {
    const lo = Math.min(range.range_low, range.range_high);
    const hi = Math.max(range.range_low, range.range_high);
    const startPct = Math.max(0, Math.min(100, ((lo - min) / (max - min)) * 100));
    const endPct = Math.max(0, Math.min(100, ((hi - min) / (max - min)) * 100));
    const startAngle = Math.PI - (startPct / 100) * Math.PI;
    const endAngle = Math.PI - (endPct / 100) * Math.PI;
    const color =
      range.area === "RED"
        ? "text-red-500"
        : range.area === "ORANGE"
          ? "text-amber-500"
          : "text-emerald-500";
    return { startAngle, endAngle, color };
  });
}
