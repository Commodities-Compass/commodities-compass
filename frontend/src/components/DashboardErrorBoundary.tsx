import * as Sentry from '@sentry/react';
import { Card } from '@/components/ui/card';

function SectionFallback() {
  return (
    <Card className="flex items-center justify-center h-[200px]">
      <p className="text-sm text-muted-foreground">Unable to load this section</p>
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
