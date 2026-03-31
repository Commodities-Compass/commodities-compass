import * as Sentry from '@sentry/react';
import { Card } from '@/components/ui/card';

function SectionFallback() {
  return (
    <Card className="flex items-center justify-center h-[200px]">
      <div className="text-center space-y-1">
        <p className="text-sm text-muted-foreground">This section could not be displayed</p>
        <p className="text-xs text-muted-foreground/60">Try refreshing the page</p>
      </div>
    </Card>
  );
}

export function DashboardErrorBoundary({ children }: { children: React.ReactNode }) {
  return (
    <Sentry.ErrorBoundary fallback={<SectionFallback />}>
      {children}
    </Sentry.ErrorBoundary>
  );
}
