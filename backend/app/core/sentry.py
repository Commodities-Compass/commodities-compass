"""Shared Sentry initialization for all backend services."""

import os
import sys

import sentry_sdk


def init_sentry(
    service: str,
    integrations: list | None = None,
) -> None:
    """Initialize Sentry SDK with service-specific tagging.

    Must be called before any @monitor-decorated function is invoked.
    No-ops gracefully when:
    - pytest is loaded in the current process (prevents local test runs
      from leaking events into the production Sentry project when
      SENTRY_DSN happens to be exported in the shell). Detected via
      sys.modules rather than PYTEST_CURRENT_TEST because the latter is
      only set during test execution, not during module import where most
      init_sentry() calls happen. pytest is a dev-only dependency and is
      absent from the production Docker image, so this check is safe.
    - SENTRY_DSN is absent (local dev without Sentry).
    """
    if "pytest" in sys.modules:
        return
    dsn = os.getenv("SENTRY_DSN")
    if not dsn:
        return

    sentry_sdk.init(
        dsn=dsn,
        environment=os.getenv("ENVIRONMENT", "production"),
        traces_sample_rate=0.2,
        sample_rate=1.0,
        send_default_pii=False,
        integrations=integrations or [],
        release=os.getenv("GIT_COMMIT_SHA") or os.getenv("GITHUB_SHA"),
    )
    sentry_sdk.set_tag("service", service)
