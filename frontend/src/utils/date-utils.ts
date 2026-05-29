/**
 * Returns the ISO date that is `n` *trading* days after `iso`.
 * Skips weekends AND any ISO date present in `nonTradingDays` (exchange
 * holidays fetched from /v1/dashboard/non-trading-days). This is the exact
 * counterpart of the backend J+horizon evaluation — the user can verify
 * the target close on the price chart for the displayed date.
 */
export function addTradingDays(
  iso: string | null | undefined,
  n: number,
  nonTradingDays: Set<string>,
): string | null {
  if (!iso) return null;
  const d = new Date(iso.slice(0, 10) + 'T00:00:00');
  if (Number.isNaN(d.getTime())) return null;
  let remaining = n;
  while (remaining > 0) {
    d.setDate(d.getDate() + 1);
    const dow = d.getDay();
    if (dow === 0 || dow === 6) continue;
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    const isoDay = `${y}-${m}-${day}`;
    if (nonTradingDays.has(isoDay)) continue;
    remaining -= 1;
  }
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}
