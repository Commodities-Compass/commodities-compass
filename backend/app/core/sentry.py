"""Shared Sentry initialization for all backend services."""

import os

import sentry_sdk


def init_sentry(
    service: str,
    integrations: list | None = None,
) -> None:
    """Initialize Sentry SDK with service-specific tagging.

    Must be called before any @monitor-decorated function is invoked.
    No-ops gracefully when SENTRY_DSN is absent (local dev without Sentry).
    """
    dsn = os.getenv("SENTRY_DSN")
    if not dsn:
        return

    sentry_sdk.init(
        dsn=dsn,
        environment=os.getenv("ENVIRONMENT", "production"),
        traces_sample_rate=1.0,
        sample_rate=1.0,
        integrations=integrations or [],
        release=os.getenv("RAILWAY_GIT_COMMIT_SHA"),
    )
    sentry_sdk.set_tag("service", service)
