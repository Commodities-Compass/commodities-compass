import type { TFunction } from 'i18next';

export const STATUS_HEX: Record<string, string> = {
  normal: '#10B981',
  degraded: '#F59E0B',
  stress: '#EF4444',
};

export function statusLabel(status: string | undefined, t: TFunction): string {
  if (status === 'normal') return t('weather.status_normal');
  if (status === 'degraded') return t('weather.status_degraded');
  if (status === 'stress') return t('weather.status_stress');
  return '—';
}

export function healthColor(score: number | null | undefined): string {
  if (score == null) return 'var(--ink-light)';
  if (score >= 3.5) return 'var(--color-signal-open)';
  if (score >= 2.5) return 'var(--color-signal-monitor)';
  return 'var(--color-signal-hedge)';
}
