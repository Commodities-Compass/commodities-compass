import { Area, AreaChart, CartesianGrid, XAxis, YAxis, Tooltip as ReTooltip, ResponsiveContainer } from 'recharts';
import { Loader2, ChevronDown } from 'lucide-react';
import { useState, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover';
import { METRIC_OPTIONS } from '@/data/commodities-data';
import { useChartData } from '@/hooks/useDashboard';
import SectionHeader from '@/components/section-header';

const DAYS_OPTIONS = [30, 90, 180, 365] as const;

interface PillGroupProps {
  value: number;
  onChange: (v: number) => void;
}

function DaysPillGroup({ value, onChange }: PillGroupProps) {
  const { t } = useTranslation();
  return (
    <div
      role="radiogroup"
      aria-label={t('market.chart_period_aria')}
      style={{
        display: 'inline-flex',
        border: '1px solid var(--ink)',
      }}
    >
      {DAYS_OPTIONS.map((d, i) => {
        const isActive = d === value;
        return (
          <button
            key={d}
            type="button"
            role="radio"
            aria-checked={isActive}
            onClick={() => onChange(d)}
            className="chart-days-pill uppercase"
            data-active={isActive ? 'true' : 'false'}
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 10,
              fontWeight: 600,
              letterSpacing: '0.18em',
              padding: '10px 14px',
              minWidth: 44,
              background: isActive ? 'var(--ink)' : 'transparent',
              color: isActive ? 'var(--paper)' : 'var(--ink-mid)',
              border: 'none',
              borderLeft: i > 0 ? '1px solid var(--ink)' : 'none',
              cursor: 'pointer',
              transition: 'background 120ms, color 120ms',
            }}
          >
            {d === 365 ? '1Y' : `${d}J`}
          </button>
        );
      })}
    </div>
  );
}

interface MetricDropdownProps {
  value: string;
  onChange: (v: string) => void;
}

function MetricDropdown({ value, onChange }: MetricDropdownProps) {
  const [open, setOpen] = useState(false);
  const current = METRIC_OPTIONS.find((o) => o.value === value) ?? METRIC_OPTIONS[0];

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-haspopup="listbox"
          aria-expanded={open}
          className="chart-metric-trigger uppercase inline-flex items-center gap-2"
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 10,
            fontWeight: 600,
            letterSpacing: '0.2em',
            color: 'var(--ink)',
            background: 'transparent',
            border: 'none',
            borderBottom: '1px solid var(--ink)',
            padding: '10px 0',
            minHeight: 40,
            cursor: 'pointer',
            transition: 'color 120ms',
          }}
        >
          <span
            className="uppercase"
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 9,
              letterSpacing: '0.18em',
              color: 'var(--ink-light)',
              marginRight: 2,
            }}
          >
            Metric:
          </span>
          {current.label}
          <ChevronDown style={{ width: 11, height: 11, opacity: 0.65 }} />
        </button>
      </PopoverTrigger>
      <PopoverContent
        align="end"
        sideOffset={4}
        collisionPadding={16}
        // `w-auto` is load-bearing: the shadcn PopoverContent primitive hardcodes
        // `w-72` (288px), so the minWidth below cannot shrink it — a class sets
        // `width` outright. The longest label here is OPEN INTEREST at ~101px.
        className="p-0 w-auto"
        style={{
          background: 'var(--paper)',
          border: '1px solid var(--ink)',
          borderRadius: 0,
          boxShadow: 'none',
          minWidth: 180,
        }}
      >
        <ul role="listbox" style={{ listStyle: 'none', margin: 0, padding: 0 }}>
          {METRIC_OPTIONS.map((m) => {
            const isActive = m.value === value;
            return (
              <li key={m.value}>
                <button
                  type="button"
                  role="option"
                  aria-selected={isActive}
                  onClick={() => {
                    onChange(m.value);
                    setOpen(false);
                  }}
                  className="chart-metric-option uppercase w-full text-left"
                  data-active={isActive ? 'true' : 'false'}
                  style={{
                    fontFamily: 'var(--font-mono)',
                    fontSize: 10,
                    fontWeight: isActive ? 700 : 500,
                    letterSpacing: '0.18em',
                    color: isActive ? 'var(--ink)' : 'var(--ink-mid)',
                    background: isActive ? 'var(--paper-off)' : 'transparent',
                    border: 'none',
                    borderBottom: '1px dotted var(--rule)',
                    padding: '10px 14px',
                    cursor: 'pointer',
                    transition: 'background 120ms, color 120ms',
                  }}
                >
                  {m.label}
                </button>
              </li>
            );
          })}
        </ul>
      </PopoverContent>
    </Popover>
  );
}

interface PriceChartProps {
  title?: string;
  selectedMetric?: string;
  onMetricChange?: (metric: string) => void;
  targetDate?: string;
  className?: string;
}

function ChartTooltip({ active, payload }: { active?: boolean; payload?: Array<{ value: number; name: string; payload: { date: string } }> }) {
  if (!active || !payload || payload.length === 0) return null;
  const p = payload[0];
  return (
    <div
      style={{
        background: 'var(--paper)',
        border: '1px solid var(--ink)',
        padding: '8px 12px',
        fontFamily: 'var(--font-mono)',
        fontSize: 11,
      }}
    >
      <div style={{ color: 'var(--ink-mid)', marginBottom: 2 }}>{p.payload.date}</div>
      <div style={{ color: 'var(--ink)', fontWeight: 600 }}>
        {p.name}: {typeof p.value === 'number' ? p.value.toLocaleString() : '—'}
      </div>
    </div>
  );
}

export default function PriceChart({
  title = 'Price History & Signal Overlay',
  selectedMetric = 'close',
  onMetricChange,
  targetDate,
  className,
}: PriceChartProps) {
  const { t } = useTranslation();
  const [days, setDays] = useState(90);
  const { data: chartResponse, isLoading, error } = useChartData(days, targetDate);

  const metricConfig = useMemo(
    () => METRIC_OPTIONS.find((o) => o.value === selectedMetric) || METRIC_OPTIONS[0],
    [selectedMetric],
  );

  const visibleData = useMemo(() => chartResponse?.data ?? [], [chartResponse?.data]);

  const yAxisDomain = useMemo<[number | string, number | string]>(() => {
    const tight = ['close', 'stock_eu'];
    if (!tight.includes(selectedMetric) || visibleData.length === 0) return [0, 'auto'];
    const values = visibleData
      .map((d) => d[metricConfig.dataKey as keyof typeof d] as number)
      .filter((v) => v != null);
    if (values.length === 0) return [0, 'auto'];
    const min = Math.min(...values);
    const max = Math.max(...values);
    const pad = (max - min) * 0.1 || max * 0.01;
    return [Math.floor(min - pad), Math.ceil(max + pad)];
  }, [selectedMetric, visibleData, metricConfig.dataKey]);

  const formatDate = (s: string) => {
    const d = new Date(s);
    return d.toLocaleDateString('en-US', { month: 'short', day: '2-digit' });
  };

  const formatValue = (n: number) => {
    if (n >= 1000) return n.toLocaleString();
    return n.toString();
  };

  const latest = visibleData[visibleData.length - 1];

  return (
    <section className={className} style={{ padding: '24px 0' }}>
      <style>{`
        .chart-days-pill[data-active="false"]:hover { color: var(--ink) !important; }
        .chart-metric-trigger:hover { color: var(--ink-mid) !important; }
        .chart-metric-option:hover {
          background: var(--paper-off) !important;
          color: var(--ink) !important;
        }
      `}</style>
      <SectionHeader numeral="III" title={title} />

      {/* Toolbar */}
      <div className="flex flex-wrap items-center justify-between gap-3 mb-5">
        <div
          className="uppercase"
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 10,
            letterSpacing: '0.18em',
            color: 'var(--ink-mid)',
          }}
        >
          Fig. 1 — {metricConfig.label}
        </div>
        <div className="flex items-center gap-5 flex-wrap">
          <MetricDropdown
            value={selectedMetric}
            onChange={(v) => onMetricChange?.(v)}
          />
          <DaysPillGroup value={days} onChange={setDays} />
        </div>
      </div>

      {/* Chart */}
      <div
        style={{
          background: 'var(--paper-off)',
          padding: '24px 16px 12px',
          border: '1px solid var(--rule)',
        }}
      >
        {isLoading ? (
          <div className="flex items-center justify-center h-[360px]" style={{ color: 'var(--ink-light)' }}>
            <Loader2 className="h-5 w-5 animate-spin mr-2" />
            <span className="text-sm">{t('loading.price_chart')}</span>
          </div>
        ) : error || visibleData.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-[360px] gap-1" style={{ color: 'var(--ink-light)' }}>
            <p className="text-sm">{t('common.error_no_price_data')}</p>
            <p className="text-xs" style={{ color: 'var(--ink-light)' }}>
              {t('common.error_no_price_data_hint')}
            </p>
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={360}>
            <AreaChart data={visibleData} margin={{ top: 20, right: 28, left: 16, bottom: 8 }}>
              <defs>
                <linearGradient id="editorialFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#1A1A1A" stopOpacity={0.15} />
                  <stop offset="100%" stopColor="#1A1A1A" stopOpacity={0.02} />
                </linearGradient>
              </defs>
              <CartesianGrid stroke="#E5E5E5" strokeDasharray="0" vertical={false} />
              <XAxis
                dataKey="date"
                tickFormatter={formatDate}
                tickLine={false}
                axisLine={{ stroke: '#999' }}
                tick={{ fontSize: 10, fontFamily: 'IBM Plex Mono, monospace', fill: '#666' }}
                minTickGap={40}
              />
              <YAxis
                domain={yAxisDomain}
                tickLine={false}
                axisLine={false}
                tick={{ fontSize: 10, fontFamily: 'IBM Plex Mono, monospace', fill: '#666' }}
                tickFormatter={formatValue}
                width={50}
              />
              <ReTooltip content={<ChartTooltip />} cursor={{ stroke: '#999', strokeDasharray: '2 2' }} />
              <Area
                type="monotone"
                dataKey={metricConfig.dataKey}
                stroke="#1A1A1A"
                strokeWidth={1.8}
                fill="url(#editorialFill)"
                name={metricConfig.label}
                dot={false}
                activeDot={{ r: 4, fill: '#1A1A1A', stroke: '#FFF', strokeWidth: 2 }}
              />
            </AreaChart>
          </ResponsiveContainer>
        )}
      </div>

      {/* Editorial caption */}
      {latest && !isLoading && (
        <div
          className="mt-3"
          style={{
            fontFamily: 'var(--font-editorial)',
            fontStyle: 'italic',
            fontSize: 12,
            color: 'var(--ink-mid)',
            lineHeight: 1.5,
          }}
        >
          <span
            className="uppercase mr-2"
            style={{
              fontFamily: 'var(--font-mono)',
              fontStyle: 'normal',
              fontSize: 10,
              fontWeight: 600,
              letterSpacing: '0.18em',
              color: 'var(--ink)',
            }}
          >
            Fig. 1
          </span>
          ICE London cocoa — {metricConfig.label.toLowerCase()} over the past {days} sessions. Source: ICE Futures, Compass CC computations.
        </div>
      )}
    </section>
  );
}
