import { Component } from 'react';
import type { ErrorInfo, ReactNode } from 'react';
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

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
}

class DashboardErrorBoundaryClass extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(): State {
    return { hasError: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('[DashboardErrorBoundary]', error, info.componentStack);
  }

  render() {
    if (this.state.hasError) {
      return <SectionFallback />;
    }
    return this.props.children;
  }
}

export function DashboardErrorBoundary({ children }: Props) {
  return <DashboardErrorBoundaryClass>{children}</DashboardErrorBoundaryClass>;
}
