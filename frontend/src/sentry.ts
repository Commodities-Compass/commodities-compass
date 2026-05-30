import * as Sentry from '@sentry/react';

export function initSentry(): void {
  const dsn = import.meta.env.SENTRY_DSN as string | undefined;
  if (!dsn) {
    return;
  }

  Sentry.init({
    dsn,
    environment: (import.meta.env.ENVIRONMENT as string | undefined) ?? 'production',
    release: import.meta.env.GIT_COMMIT_SHA as string | undefined,
    sendDefaultPii: false,
    tracesSampleRate: 0.1,
    integrations: [Sentry.browserTracingIntegration()],
  });

  Sentry.setTag('service', 'frontend');
}

export { Sentry };
