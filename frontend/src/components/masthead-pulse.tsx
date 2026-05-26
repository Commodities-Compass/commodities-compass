import { useMemo } from 'react';
import { usePositionStatus, useChartData } from '@/hooks/useDashboard';
import { useDashboardDate } from '@/hooks/useDashboardDate';
import { Eyebrow, DotSeparator } from '@/components/editorial';

function fmtPct(n: number | null | undefined): string {
  if (n == null) return '—';
  return `${n >= 0 ? '+' : ''}${n.toFixed(2)}%`;
}

function formatShortDate(iso?: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso.slice(0, 10) + 'T00:00:00');
  if (Number.isNaN(d.getTime())) return iso;
  const months = ['jan', 'fév', 'mar', 'avr', 'mai', 'juin', 'juil', 'aoû', 'sep', 'oct', 'nov', 'déc'];
  return `${d.getDate()} ${months[d.getMonth()]}`;
}

interface SessionDelta {
  date: string;
  pct: number;
}

/**
 * Scans the chart series for the single largest day-over-day positive
 * close-to-close return, filtered to the current calendar year. Magazine
 * "fact" — "the best session of the year so far".
 */
function pickBestSession(
  data: { date: string; close?: number | null }[] | undefined,
  currentYear: number,
): SessionDelta | null {
  if (!data || data.length < 2) return null;
  const sorted = data
    .filter((p) => p.close != null)
    .slice()
    .sort((a, b) => a.date.localeCompare(b.date));
  let best: SessionDelta | null = null;
  for (let i = 1; i < sorted.length; i++) {
    const prev = sorted[i - 1];
    const curr = sorted[i];
    if (curr.close == null || prev.close == null || prev.close === 0) continue;
    const year = Number(curr.date.slice(0, 4));
    if (year !== currentYear) continue;
    const pct = ((curr.close - prev.close) / prev.close) * 100;
    if (pct > 0 && (best == null || pct > best.pct)) {
      best = { date: curr.date, pct };
    }
  }
  return best;
}

/* ============================================================================
 * <MastheadPulse /> — editorial "by the numbers" line under the deck.
 *
 * Single line: YTD anchor · Best session of the year · Sessions count.
 * No sparkline, no KPI duplication with the breakdown / score card.
 * ========================================================================= */
export default function MastheadPulse() {
  const { currentDate } = useDashboardDate();
  const { data: pos } = usePositionStatus(currentDate);
  // 365 days = covers full YTD even at end of year. React Query dedupes
  // with the price chart hook in the hero.
  const { data: chart } = useChartData(365, currentDate);

  const currentYear = useMemo(() => {
    if (currentDate) return Number(currentDate.slice(0, 4));
    return new Date().getFullYear();
  }, [currentDate]);

  const chartData = chart?.data;
  const best = useMemo(
    () => pickBestSession(chartData, currentYear),
    [chartData, currentYear],
  );

  if (!pos) return null;

  const ytd = pos.ytd_performance;
  const ytdColor =
    ytd != null && ytd >= 0
      ? 'var(--color-signal-open)'
      : 'var(--color-signal-hedge)';

  return (
    <div
      className="masthead-pulse"
      style={{
        display: 'flex',
        alignItems: 'baseline',
        justifyContent: 'center',
        flexWrap: 'wrap',
        rowGap: 6,
        columnGap: 20,
        padding: '12px 0 6px',
      }}
    >
      {/* YTD anchor */}
      <span style={{ display: 'inline-flex', alignItems: 'baseline', gap: 10 }}>
        <Eyebrow tone="muted" size={10} tracking="0.22em">
          YTD
        </Eyebrow>
        <span
          className="tabular-nums"
          style={{
            fontFamily: 'var(--font-display)',
            fontWeight: 700,
            fontSize: 'clamp(22px, 2.4vw, 30px)',
            lineHeight: 1,
            color: ytdColor,
          }}
        >
          {fmtPct(ytd)}
        </span>
      </span>

      <DotSeparator />

      {/* Best session of the year */}
      <span
        style={{ display: 'inline-flex', alignItems: 'baseline', gap: 10 }}
      >
        <Eyebrow tone="muted" size={10} tracking="0.22em">
          Meilleure session
        </Eyebrow>
        <span
          className="tabular-nums"
          style={{
            fontFamily: 'var(--font-display)',
            fontWeight: 600,
            fontSize: 18,
            lineHeight: 1,
            color: 'var(--color-signal-open)',
          }}
        >
          {best ? fmtPct(best.pct) : '—'}
        </span>
        {best && (
          <span
            style={{
              fontFamily: 'var(--font-display)',
              fontStyle: 'italic',
              fontSize: 14,
              color: 'var(--ink-mid)',
            }}
          >
            {formatShortDate(best.date)}
          </span>
        )}
      </span>

    </div>
  );
}
