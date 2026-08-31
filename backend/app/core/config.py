# pyright: reportAssignmentType=false, reportAttributeAccessIssue=false
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict
from decouple import config
import json


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        case_sensitive=True,
        env_file=".env",
        extra="ignore",
        # All values are read via python-decouple (class-level defaults).
        # Disable pydantic-settings env parsing to prevent JSON decode errors
        # on non-JSON env vars like BACKEND_CORS_ORIGINS and AUTH0_ALGORITHMS.
        env_parse_none_str=None,
    )

    # Application
    APP_NAME: str = config("APP_NAME", default="Commodities Compass", cast=str)
    APP_VERSION: str = config("APP_VERSION", default="1.0.0", cast=str)
    API_V1_STR: str = config("API_V1_STR", default="/v1", cast=str)
    DEBUG: bool = config("DEBUG", default=False, cast=bool)
    BACKEND_PORT: int = config("BACKEND_PORT", default=8000, cast=int)

    # Auth0 (defaults allow standalone cron services that don't need auth)
    AUTH0_DOMAIN: str = config("AUTH0_DOMAIN", default="", cast=str)
    AUTH0_CLIENT_ID: str = config("AUTH0_CLIENT_ID", default="", cast=str)
    AUTH0_API_AUDIENCE: str = config("AUTH0_API_AUDIENCE", default="", cast=str)
    AUTH0_ALGORITHMS: str = config("AUTH0_ALGORITHMS", default="RS256", cast=str)
    AUTH0_ISSUER: str = config("AUTH0_ISSUER", default="", cast=str)

    # CORS
    BACKEND_CORS_ORIGINS: str = config(
        "BACKEND_CORS_ORIGINS",
        default="http://localhost:5173,http://localhost:3000",
        cast=str,
    )

    # Database
    DATABASE_URL: str = config("DATABASE_URL", default="", cast=str)
    DATABASE_SYNC_URL: str = config("DATABASE_SYNC_URL", cast=str)

    # Google Drive (audio streaming + compass brief upload)
    GOOGLE_DRIVE_CREDENTIALS_JSON: str = config(
        "GOOGLE_DRIVE_CREDENTIALS_JSON", default="", cast=str
    )
    GOOGLE_DRIVE_AUDIO_FOLDER_ID: str = config(
        "GOOGLE_DRIVE_AUDIO_FOLDER_ID", default="", cast=str
    )

    # Brief version behind the audio filename suffix, for /v1/dashboard/audio,
    # /v1/audio/info AND the cc-publish-session release gate.
    # Allowed: "regime" (-Regime) | "ensemble" (-Ensemble) | "legacy" (no suffix).
    # The frontend can override per-request via the `?version=` query param.
    #
    # The default is "regime" — the served track since 2026-08-19 — and that is
    # load-bearing, not cosmetic. It used to be "legacy", which was correct while
    # legacy ran and became a landmine the day it was deleted: any consumer that
    # does not set the env var looks for `YYYYMMDD-CompassAudio.*`, a file nobody
    # writes any more, and concludes the audio is missing.
    #
    # That is exactly what happened to `cc-publish-session` on its first live
    # night (2026-08-19): the backend *service* carried the env var, the *job* did
    # not, so the gate held the session back reporting `audio=False` while
    # `-Regime.m4a` sat in Drive. A dead default must never be the fallback.
    BRIEF_DEFAULT_VERSION: str = config(
        "BRIEF_DEFAULT_VERSION", default="regime", cast=str
    )

    # Per-client entitlement enforcement. Default OFF → dark deploy: principals
    # are resolved but no 403 is raised (every authenticated user sees everything,
    # preserving today's single-shared-view behavior). Flip ON only AFTER every
    # existing login is seeded with a tenant_account + grants (rollout §10),
    # otherwise default-deny locks everyone out.
    ENTITLEMENTS_ENFORCED: bool = config(
        "ENTITLEMENTS_ENFORCED", default=False, cast=bool
    )

    # --- Billing (Stripe) ---------------------------------------------------
    # Recurring EUR card-on-file billing. Design: docs/architecture/billing-and-collection.md
    #
    # Deliberately a SEPARATE flag from ENTITLEMENTS_ENFORCED: billing must be
    # able to ship dark, flip, and roll back on its own schedule. Default OFF →
    # `_billing_blocks()` returns False unconditionally, so no account can lose
    # access because of a payment state. Flip only once real subscriptions exist
    # and `paid_through` is set on the manual/wire accounts.
    BILLING_ENFORCED: bool = config("BILLING_ENFORCED", default=False, cast=bool)

    # Stripe API credentials. Empty in dev/CI — the tests never hit the network,
    # and BillingService fails loud rather than silently no-op'ing if a caller
    # tries to reach Stripe without them.
    STRIPE_SECRET_KEY: str = config("STRIPE_SECRET_KEY", default="", cast=str)
    # Signing secret for POST /v1/webhooks/stripe. Required whenever the webhook
    # is reachable: an unverified payload must never be trusted to change access.
    STRIPE_WEBHOOK_SECRET: str = config("STRIPE_WEBHOOK_SECRET", default="", cast=str)

    # HMAC secret for signing the unauthenticated /audio/stream capability token.
    # Required only when ENTITLEMENTS_ENFORCED is on (dark mode keeps the stream
    # open). Store in GCP Secret Manager in prod.
    AUDIO_URL_SECRET: str = config("AUDIO_URL_SECRET", default="", cast=str)

    # TTL (seconds) for the resolved-principal in-memory cache. Prod default 600
    # (10 min). Set to 0 locally to disable caching so entitlement/tier changes
    # are reflected on the very next request (useful for demos).
    PRINCIPAL_CACHE_TTL: int = config("PRINCIPAL_CACHE_TTL", default=600, cast=int)

    # External APIs
    WEATHER_API_KEY: str = config("WEATHER_API_KEY", default="", cast=str)
    NEWS_API_KEY: str = config("NEWS_API_KEY", default="", cast=str)

    # AWS Configuration
    AWS_ACCESS_KEY_ID: str = config("AWS_ACCESS_KEY_ID", default="", cast=str)
    AWS_SECRET_ACCESS_KEY: str = config("AWS_SECRET_ACCESS_KEY", default="", cast=str)
    AWS_REGION: str = config("AWS_REGION", default="us-east-1", cast=str)
    S3_BUCKET_NAME: str = config("S3_BUCKET_NAME", default="", cast=str)

    @property
    def auth0_algorithms_list(self) -> List[str]:
        return [a.strip() for a in self.AUTH0_ALGORITHMS.split(",")]

    @property
    def cors_origins(self) -> List[str]:
        raw = self.BACKEND_CORS_ORIGINS
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return [o.strip() for o in raw.split(",") if o.strip()]

    @property
    def frontend_url(self) -> str:
        """Where Stripe sends the client back after Checkout / the Portal.

        Derived from the first CORS origin rather than a dedicated env var, so
        it is correct per environment by construction and cannot rot into a
        stale default pointing at a URL nobody serves (the failure mode that
        BRIEF_DEFAULT_VERSION documents above).
        """
        origins = self.cors_origins
        return origins[0] if origins else "http://localhost:5173"


settings = Settings()
