import { Card } from '@/components/ui/card';
import { cn } from '@/utils';
import { Loader2 } from 'lucide-react';
import { usePositionStatus } from '@/hooks/useDashboard';

interface SignalHeroProps {
  targetDate?: string;
  className?: string;
}

const SIGNAL_CONFIG = {
  HEDGE: {
    ring: 'ring-red-500/30 dark:ring-red-400/20',
    dot: 'bg-red-500',
    text: 'text-red-600 dark:text-red-400',
    badge: 'bg-red-500/8 dark:bg-red-400/10',
  },
  MONITOR: {
    ring: 'ring-amber-500/30 dark:ring-amber-400/20',
    dot: 'bg-amber-500',
    text: 'text-amber-600 dark:text-amber-400',
    badge: 'bg-amber-500/8 dark:bg-amber-400/10',
  },
  OPEN: {
    ring: 'ring-emerald-500/30 dark:ring-emerald-400/20',
    dot: 'bg-emerald-500',
    text: 'text-emerald-600 dark:text-emerald-400',
    badge: 'bg-emerald-500/8 dark:bg-emerald-400/10',
  },
} as const;

const DEFAULT_CONFIG = {
  ring: 'ring-muted-foreground/20',
  dot: 'bg-muted-foreground',
  text: 'text-muted-foreground',
  badge: 'bg-muted',
};

export default function SignalHero({ targetDate, className }: SignalHeroProps) {
  const { data, isLoading, error } = usePositionStatus(targetDate);

  if (isLoading) {
    return (
      <Card className={cn('flex items-center justify-center h-full min-h-[200px]', className)}>
        <div className="flex items-center gap-2 text-muted-foreground">
          <Loader2 className="h-5 w-5 animate-spin" />
          <span className="text-sm">Chargement...</span>
        </div>
      </Card>
    );
  }

  if (error || !data) {
    return (
      <Card className={cn('flex items-center justify-center h-full min-h-[200px]', className)}>
        <div className="text-center space-y-1">
          <p className="text-sm text-muted-foreground">
            Aucune donnée de position pour cette date
          </p>
          <p className="text-xs text-muted-foreground/60">
            L'analyse quotidienne n'a peut-être pas encore été exécutée
          </p>
        </div>
      </Card>
    );
  }

  const { position, ytd_performance } = data;
  const config = SIGNAL_CONFIG[position] ?? DEFAULT_CONFIG;

  return (
    <Card
      className={cn(
        'flex flex-col h-full min-h-[200px] overflow-hidden transition-all duration-500',
        className,
      )}
    >
      <div className="flex flex-col h-full px-6 py-5">
        <span className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
          Position du Jour
        </span>

        <div className="flex-1 flex items-center justify-center">
          <div
            className={cn(
              'flex items-center gap-3 px-6 py-3 rounded-full ring-2 transition-all duration-500',
              config.ring,
              config.badge,
            )}
          >
            <div className={cn('h-2.5 w-2.5 rounded-full', config.dot)} />
            <span className={cn('text-2xl font-semibold tracking-wide', config.text)}>
              {position}
            </span>
          </div>
        </div>

        <div className="flex items-end justify-between pt-2 border-t border-border/50">
          <span className="text-xs text-muted-foreground">Performance YTD</span>
          <span className="text-xl font-semibold tabular-nums text-foreground">
            {ytd_performance != null ? `${ytd_performance.toFixed(2)}%` : '—'}
          </span>
        </div>
      </div>
    </Card>
  );
}
