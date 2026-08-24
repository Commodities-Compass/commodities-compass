"""Auth API response schemas."""

from pydantic import BaseModel, Field


class UserResponse(BaseModel):
    """Response schema for /auth/me."""

    sub: str | None = Field(None, description="Auth0 user ID")
    email: str | None = Field(None, description="User email")
    name: str | None = Field(None, description="User display name")
    permissions: list[str] = Field(default_factory=list, description="User permissions")
    # Per-client entitlement context (resolved from the tenant tables). The
    # frontend consumes `entitlements` to gate sections/features. Empty for a
    # user with no tenant seat (default-deny under enforcement).
    tier: str | None = Field(None, description="Tenant tier")
    account_code: str | None = Field(None, description="Tenant account code")
    entitlements: list[str] = Field(
        default_factory=list, description="Granted entitlement keys"
    )
    # Mirrors the backend flag so the frontend gates ONLY when enforcement is on.
    # When false (dark mode), the UI shows everything regardless of entitlements —
    # matching the backend, which serves everything. Prevents a blank dashboard
    # for legacy/un-seeded users before the flag is flipped.
    enforced: bool = Field(
        False, description="Whether entitlement enforcement is active server-side"
    )
    # Payment state, so the frontend can show the "update your card" banner.
    # Note this is orthogonal to `entitlements`: an account in `past_due` still
    # holds its full key set (the Stripe retry window keeps access), so the
    # banner is the ONLY signal the client gets before the retries are exhausted.
    billing_status: str | None = Field(
        None, description="trialing|active|past_due|unpaid|canceled|manual"
    )


class TokenVerifyResponse(BaseModel):
    """Response schema for /auth/verify."""

    valid: bool
    user_id: str | None = None


class NonTradingDaysResponse(BaseModel):
    """Response schema for /dashboard/non-trading-days."""

    dates: list[str] = Field(
        default_factory=list, description="Non-trading weekday dates (ISO format)"
    )
    latest_trading_day: str | None = Field(
        None, description="Most recent display_date with data"
    )
