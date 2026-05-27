import { useState } from 'react';
import { useDashboardDate } from '@/hooks/useDashboardDate';
import {
  usePositionStatus,
  useChartData,
  useIndicatorsGrid,
  useMacroPanel,
  usePositioning,
} from '@/hooks/useDashboard';
import { Eyebrow, DotSeparator, DataValue } from '@/components/editorial';

const SIGNAL_HEX = {
  OPEN: '#10B981',
  MONITOR: '#F59E0B',
  HEDGE: '#EF4444',
} as const;

function fmtPrice(n: number | null | undefined): string {
  if (n == null) return '—';
  return `£${n.toLocaleString('en-GB', { maximumFractionDigits: 0 })}`;
}

function fmtPct(n: number | null | undefined): string {
  if (n == null) return '—';
  const sign = n >= 0 ? '+' : '';
  return `${sign}${n.toFixed(2)}%`;
}

function fmtNum(n: number | null | undefined, digits = 2): string {
  if (n == null) return '—';
  return n.toFixed(digits);
}

function fmtInt(n: number | null | undefined): string {
  if (n == null) return '—';
  return Math.round(n).toLocaleString('en-GB');
}

function fmtCompact(n: number | null | undefined): string {
  if (n == null) return '—';
  const abs = Math.abs(n);
  const sign = n < 0 ? '-' : '';
  if (abs >= 1_000_000) return `${sign}${(abs / 1_000_000).toFixed(2)}M`;
  if (abs >= 1_000) return `${sign}${(abs / 1_000).toFixed(1)}k`;
  return n.toFixed(0);
}

function fmtSignedCompact(n: number | null | undefined): string {
  if (n == null) return '—';
  const formatted = fmtCompact(n);
  return n >= 0 ? `+${formatted}` : formatted;
}

interface TickerItem {
  key: string;
  label: string;
  value: string;
  valueColor?: string;
  dot?: string;
}

function TickerCell({ item }: { item: TickerItem }) {
  return (
    <span className="ticker-cell inline-flex items-center gap-1.5 whitespace-nowrap">
      {item.dot && (
        <span
          aria-hidden
          style={{
            display: 'inline-block',
            width: 7,
            height: 7,
            borderRadius: '50%',
            background: item.dot,
          }}
        />
      )}
      {item.label && (
        <Eyebrow tone="subtle" size={10}>
          {item.label}
        </Eyebrow>
      )}
      <DataValue color={item.valueColor}>{item.value}</DataValue>
    </span>
  );
}

export default function LiveSignalStrip() {
  const { currentDate } = useDashboardDate();
  const { data: pos } = usePositionStatus(currentDate);
  const { data: chart } = useChartData(5, currentDate);
  const { data: grid } = useIndicatorsGrid(currentDate);
  const { data: macro } = useMacroPanel(currentDate);
  const { data: positioning } = usePositioning(currentDate);

  const sortedPoints = (chart?.data ?? [])
    .filter((p) => p.close != null)
    .slice()
    .sort((a, b) => a.date.localeCompare(b.date));
  const latest = sortedPoints[sortedPoints.length - 1];
  const previous = sortedPoints[sortedPoints.length - 2];
  const dod =
    latest && previous && latest.close != null && previous.close != null && previous.close !== 0
      ? ((latest.close - previous.close) / previous.close) * 100
      : null;

  const indicators = grid?.indicators ?? {};
  const rsi = indicators.rsi?.value ?? null;
  const macd = indicators.macd?.value ?? null;
  const volOi = indicators.volOi?.value ?? null;
  const percentK = indicators.percentK?.value ?? null;
  const atr = indicators.atr?.value ?? null;

  const items: TickerItem[] = [
    {
      key: 'signal',
      label: 'Signal',
      value: pos?.position ?? '—',
      valueColor: pos ? SIGNAL_HEX[pos.position] : 'var(--ink-light)',
      dot: pos ? SIGNAL_HEX[pos.position] : undefined,
    },
    { key: 'price', label: 'ICE LDN', value: fmtPrice(latest?.close) },
    {
      key: 'dod',
      label: 'DoD',
      value: fmtPct(dod),
      valueColor:
        dod == null
          ? 'var(--ink-light)'
          : dod >= 0
            ? 'var(--color-signal-open)'
            : 'var(--color-signal-hedge)',
    },
    { key: 'vol', label: 'Volume', value: fmtInt(latest?.volume) },
    { key: 'oi', label: 'OI', value: fmtInt(latest?.open_interest) },
    { key: 'rsi', label: 'RSI', value: fmtNum(rsi) },
    { key: 'macd', label: 'MACD', value: fmtNum(macd) },
    { key: 'pk', label: '%K', value: fmtNum(percentK) },
    { key: 'atr', label: 'ATR', value: fmtNum(atr) },
    { key: 'voi', label: 'V/OI', value: fmtNum(volOi) },
    {
      key: 'stockEu',
      label: 'Stock EU',
      value:
        positioning?.stock_eu_tonnes != null
          ? `${fmtCompact(positioning.stock_eu_tonnes)} t`
          : '—',
    },
    {
      key: 'stockUs',
      label: 'Stock US',
      value:
        positioning?.stock_us_tonnes != null
          ? `${fmtCompact(positioning.stock_us_tonnes)} t`
          : '—',
    },
    {
      key: 'fxDxy',
      label: 'FX DXY',
      value: fmtNum(macro?.fx_dxy_proxy, 3),
    },
    {
      key: 'cotMm',
      label: 'COT MM',
      value: fmtSignedCompact(positioning?.cot_managed_money_net),
      valueColor:
        positioning?.cot_managed_money_net == null
          ? undefined
          : positioning.cot_managed_money_net >= 0
            ? 'var(--color-signal-open)'
            : 'var(--color-signal-hedge)',
    },
    {
      key: 'ytd',
      label: 'YTD',
      value: pos?.ytd_performance != null ? fmtPct(pos.ytd_performance) : '—',
      valueColor:
        pos?.ytd_performance == null
          ? 'var(--ink-light)'
          : pos.ytd_performance >= 0
            ? 'var(--color-signal-open)'
            : 'var(--color-signal-hedge)',
    },
    { key: 'session', label: 'Session', value: (pos?.date ?? currentDate).slice(0, 10) },
  ];

  const row = (keyPrefix: string) => (
    <div className="inline-flex items-center" aria-hidden={keyPrefix === 'b'}>
      {items.map((it, i) => (
        <span key={`${keyPrefix}-${it.key}`} className="inline-flex items-center">
          <TickerCell item={it} />
          {i < items.length - 1 && (
            <span className="ticker-sep">
              <DotSeparator />
            </span>
          )}
        </span>
      ))}
      <span className="ticker-sep">
        <DotSeparator />
      </span>
    </div>
  );

  const [paused, setPaused] = useState(false);

  return (
    <div
      className="overflow-hidden ticker-track"
      style={{ flex: 1, minWidth: 0, cursor: 'pointer' }}
      aria-label="Live market data ticker — tap to pause/resume"
      role="marquee"
      onClick={() => setPaused((p) => !p)}
    >
      <div
        className="ticker-scroll inline-flex items-center"
        style={paused ? { animationPlayState: 'paused' } : undefined}
      >
        {row('a')}
        {row('b')}
      </div>
      <style>{`
        .ticker-track {
          mask-image: linear-gradient(to right, transparent 0, #000 32px, #000 calc(100% - 32px), transparent 100%);
          -webkit-mask-image: linear-gradient(to right, transparent 0, #000 32px, #000 calc(100% - 32px), transparent 100%);
        }
        .ticker-cell { margin-right: 32px; }
        .ticker-sep { margin-right: 32px; }
        .ticker-scroll {
          animation: ticker-scroll 60s linear infinite;
          will-change: transform;
        }
        @media (hover: hover) {
          .ticker-track:hover .ticker-scroll {
            animation-play-state: paused;
          }
        }
        @keyframes ticker-scroll {
          from { transform: translateX(0); }
          to { transform: translateX(-50%); }
        }
        @media (prefers-reduced-motion: reduce) {
          .ticker-scroll {
            animation: none;
          }
        }
        @media (max-width: 639px) {
          .ticker-track {
            mask-image: linear-gradient(to right, transparent 0, #000 12px, #000 calc(100% - 12px), transparent 100%);
            -webkit-mask-image: linear-gradient(to right, transparent 0, #000 12px, #000 calc(100% - 12px), transparent 100%);
          }
          .ticker-cell { margin-right: 14px; }
          .ticker-sep { margin-right: 14px; }
          .ticker-scroll {
            animation-duration: 45s;
          }
        }
      `}</style>
    </div>
  );
}
