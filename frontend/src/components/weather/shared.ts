export const STATUS_HEX: Record<string, string> = {
  normal: '#10B981',
  degraded: '#F59E0B',
  stress: '#EF4444',
};

export function statusLabel(status?: string): string {
  if (status === 'normal') return 'Normal';
  if (status === 'degraded') return 'Dégradé';
  if (status === 'stress') return 'Stress';
  return '—';
}

export function healthColor(score: number | null | undefined): string {
  if (score == null) return 'var(--ink-light)';
  if (score >= 3.5) return 'var(--color-signal-open)';
  if (score >= 2.5) return 'var(--color-signal-monitor)';
  return 'var(--color-signal-hedge)';
}
