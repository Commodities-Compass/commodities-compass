import type { CSSProperties } from 'react';

/**
 * Shared vocabulary for Section VI, lifted from the shipped sections so origin
 * flows read as part of the same magazine rather than a bolted-on annex.
 *
 * Sources: `weather/StressHistoryBlock.tsx` (table, dotted rows, tinted pills,
 * trend glyphs) and `weather/CampaignBlock.tsx` (hero number, methodology grid).
 * Kept here rather than re-derived per component so a future change to the
 * editorial vocabulary lands in one place.
 */

/** Table column head: mono 9/600, wide tracking, ink-light, over a 2px ink rule. */
export function thStyle(align: 'left' | 'right' = 'right'): CSSProperties {
  return {
    fontFamily: 'var(--font-mono)',
    fontSize: 9,
    fontWeight: 600,
    letterSpacing: '0.2em',
    textTransform: 'uppercase',
    color: 'var(--ink-light)',
    padding: align === 'left' ? '0 12px 10px 0' : '0 0 10px 12px',
    textAlign: align,
  };
}

/** Numeric cell: mono tabular, 12px padding, ink-dark. */
export function tdStyle(muted = false): CSSProperties {
  return {
    padding: 12,
    textAlign: 'right',
    fontFamily: 'var(--font-mono)',
    fontSize: 13,
    fontVariantNumeric: 'tabular-nums',
    color: muted ? 'var(--ink-light)' : 'var(--ink-dark)',
  };
}

/** Row-label cell: Georgia editorial, the voice used for place names in weather. */
export function tdLabelStyle(muted = false): CSSProperties {
  return {
    padding: '12px 12px 12px 0',
    textAlign: 'left',
    fontFamily: 'var(--font-editorial)',
    fontSize: 14,
    fontWeight: 600,
    fontStyle: muted ? 'italic' : 'normal',
    color: muted ? 'var(--ink-light)' : 'var(--ink)',
  };
}

export type PillTone = 'open' | 'monitor' | 'hedge' | 'mute';

/** Tinted status pill — same construction as the weather StatusPill. */
export function pillStyle(tone: PillTone): CSSProperties {
  const tones: Record<PillTone, { color: string; bg: string }> = {
    open: { color: 'var(--color-signal-open)', bg: 'rgba(16,185,129,0.09)' },
    monitor: { color: 'var(--color-signal-monitor)', bg: 'rgba(245,158,11,0.10)' },
    hedge: { color: 'var(--color-signal-hedge)', bg: 'rgba(239,68,68,0.08)' },
    mute: { color: 'var(--ink-light)', bg: 'rgba(153,153,153,0.08)' },
  };
  return {
    display: 'inline-block',
    fontFamily: 'var(--font-mono)',
    fontSize: 9,
    fontWeight: 600,
    letterSpacing: '0.18em',
    textTransform: 'uppercase',
    padding: '3px 9px',
    ...tones[tone],
  };
}

/** Trend glyph + colour, matching the weather table's Tendance column. */
export function trendGlyph(deltaPct: number | null): { glyph: string; color: string } {
  if (deltaPct === null) return { glyph: '→', color: 'var(--ink-light)' };
  if (deltaPct > 0) return { glyph: '↗', color: 'var(--color-signal-open)' };
  if (deltaPct < 0) return { glyph: '↘', color: 'var(--color-signal-hedge)' };
  return { glyph: '→', color: 'var(--ink-light)' };
}

/** Locale for number and date formatting. The app stores the choice under
 *  `cc_language` (see api/client.ts) and there is an EN edition, so nothing here
 *  may hardcode `fr-FR`. */
export function numberLocale(language: string): string {
  return language === 'en' ? 'en-GB' : 'fr-FR';
}

/** Tonnes, no decimals. `null` renders as an em dash rather than 0 — every null in
 *  this API means "not measured". */
export function formatTonnes(
  value: number | null | undefined,
  locale = 'fr-FR'
): string {
  if (value == null) return '—';
  return Math.round(value).toLocaleString(locale);
}

/** Millions of FCFA. The raw column is in absolute FCFA. */
export function formatMillions(
  value: number | null | undefined,
  locale = 'fr-FR'
): string {
  if (value == null) return '—';
  return Math.round(value / 1_000_000).toLocaleString(locale);
}

export function formatPercent(
  value: number | null | undefined,
  locale = 'fr-FR',
  digits = 1
): string {
  if (value == null) return '—';
  const n = value.toFixed(digits);
  return `${locale.startsWith('fr') ? n.replace('.', ',') : n} %`;
}

export function formatSignedPercent(
  value: number | null | undefined,
  locale = 'fr-FR'
): string {
  if (value == null) return '—';
  const sign = value > 0 ? '+' : '';
  const n = value.toFixed(1);
  return `${sign}${locale.startsWith('fr') ? n.replace('.', ',') : n} %`;
}

/** `2026-07-01` → `juil. 26`, the compact form the table needs. */
export function formatMonthShort(iso: string, locale = 'fr-FR'): string {
  const d = new Date(`${iso.slice(0, 10)}T00:00:00`);
  const month = d.toLocaleDateString(locale, { month: 'short' });
  return `${month} ${String(d.getFullYear()).slice(2)}`;
}

/** `2026-07-01` → `juillet 2026`, for headings. */
export function formatMonthLong(iso: string, locale = 'fr-FR'): string {
  const d = new Date(`${iso.slice(0, 10)}T00:00:00`);
  return d.toLocaleDateString(locale, { month: 'long', year: 'numeric' });
}

/** Window parts for the `origin.window` template. The caption is load-bearing —
 *  the three sources stop at different months and the reader must see which — so
 *  the sentence lives in i18n and only its pieces are computed here. */
export function windowParts(
  from: string | null,
  to: string | null,
  months: number,
  locale = 'fr-FR'
): { months: number; from: string; to: string } | null {
  if (!from || !to) return null;
  return {
    months,
    from: formatMonthShort(from, locale),
    to: formatMonthShort(to, locale),
  };
}

/**
 * Greyscale shade for one product-mix segment.
 *
 * The brand is greyscale plus a three-colour signal palette, and the signal
 * colours mean OPEN/MONITOR/HEDGE everywhere else in the dashboard — spending
 * them on product families here would make the bar read as a verdict. So the
 * split stays tonal: beans occupy the dark half, transformed the light half,
 * and within each family the lightness is spread across the full sub-range so
 * neighbouring segments never land within a few percent of each other. The
 * ramp is computed from the family size rather than a fixed list, so a seventh
 * product does not silently collide with a sixth.
 */
export function mixShade(indexInFamily: number, familySize: number, isBean: boolean): string {
  const [lo, hi] = isBean ? [12, 46] : [58, 88];
  const l = familySize <= 1 ? lo : lo + ((hi - lo) * indexInFamily) / (familySize - 1);
  return `hsl(0 0% ${l.toFixed(1)}%)`;
}
