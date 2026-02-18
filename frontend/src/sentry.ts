import * as Sentry from "@sentry/react";

const dsn = import.meta.env.SENTRY_DSN;

if (dsn && import.meta.env.MODE === "production") {
  Sentry.init({
    dsn,
    environment: import.meta.env.MODE,
    integrations: [
      Sentry.browserTracingIntegration(),
      Sentry.replayIntegration({ maskAllText: false, blockAllMedia: false }),
    ],
    tracesSampleRate: 1.0,
    replaysSessionSampleRate: 0,
    replaysOnErrorSampleRate: 1.0,
  });

  Sentry.setTag("service", "frontend");
}
