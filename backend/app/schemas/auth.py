"""Auth API response schemas."""

from pydantic import BaseModel, Field


class UserResponse(BaseModel):
    """Response schema for /auth/me."""

    sub: str | None = Field(None, description="Auth0 user ID")
    email: str | None = Field(None, description="User email")
    name: str | None = Field(None, description="User display name")
    permissions: list[str] = Field(default_factory=list, description="User permissions")


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
