"""Tests for per-client entitlement enforcement.

Unit: tier template expansion + key validity (pure).
Integration: the serving-layer gate — default-deny for an unseeded login
(MANDATORY), 403 when un-entitled, pass-through when entitled, dark-mode
no-op when the flag is off, and the per-series export filter.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator, Callable
from datetime import date, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import entitlements as ent
from app.core import tenancy
from app.core.auth import get_current_user
from app.core.config import settings
from app.main import app
from app.models.tenant import TenantAccount, TenantEntitlement, TenantUser

V1 = settings.API_V1_STR
WEATHER = f"{V1}/dashboard/weather"
EXPORT = f"{V1}/data/export"
ME = f"{V1}/auth/me"


# --------------------------------------------------------------------------- #
# Unit — pure vocabulary / tier expansion
# --------------------------------------------------------------------------- #
@pytest.mark.unit
def test_tier_catalogue_matches_matrix() -> None:
    assert len(ent.VALID_TIERS) == 7
    # Every tier grants only valid keys.
    for tier in ent.VALID_TIERS:
        assert ent.expand_tier(tier) <= ent.ALL_ENTITLEMENT_KEYS
    coop_ess = ent.expand_tier(ent.COOP_ESSENTIEL)
    export_ess = ent.expand_tier(ent.EXPORT_ESSENTIEL)
    export_prem = ent.expand_tier(ent.EXPORT_PREMIUM)
    signal_plus = ent.expand_tier(ent.SIGNAL_PLUS)
    # Reduced weather variant on the essentiel tiers, full on premium.
    assert ent.SECTION_WEATHER_SUMMARY in coop_ess and ent.SECTION_WEATHER not in coop_ess
    assert ent.SECTION_WEATHER_SUMMARY in export_ess
    assert ent.SECTION_WEATHER in export_prem and ent.SECTION_WEATHER_SUMMARY not in export_prem
    # Export Essentiel is lean: no positioning / press / history.
    assert ent.FEATURE_POSITIONING not in export_ess
    assert ent.SECTION_NEWS not in export_ess
    assert ent.SECTION_CHART not in export_ess
    assert {ent.FEATURE_POSITIONING, ent.SECTION_NEWS, ent.SECTION_CHART} <= export_prem
    # Podcast is "option" on Signal+ (not in the default template).
    assert ent.SECTION_PODCAST not in signal_plus


@pytest.mark.unit
def test_seat_caps_match_matrix() -> None:
    assert ent.max_seats_for(ent.COOP_ESSENTIEL) == 0  # push-only
    assert ent.max_seats_for(ent.COOP_PREMIUM) == 2
    assert ent.max_seats_for(ent.EXPORT_PREMIUM) == 3
    assert ent.max_seats_for(ent.EXPORT_PRO) == 4


@pytest.mark.unit
def test_internal_tier_is_full_catalogue() -> None:
    assert ent.expand_tier(ent.INTERNAL) == ent.ALL_ENTITLEMENT_KEYS
    assert ent.max_seats_for(ent.INTERNAL) >= 999
    assert ent.INTERNAL in ent.PROVISIONABLE_TIERS
    assert ent.INTERNAL not in ent.VALID_TIERS  # not a commercial/sellable tier


@pytest.mark.unit
def test_expand_unknown_tier_raises() -> None:
    with pytest.raises(ValueError):
        ent.expand_tier("platinum")


@pytest.mark.unit
def test_key_validity() -> None:
    assert ent.is_valid_key(ent.SECTION_WEATHER)
    assert ent.is_valid_key(ent.export_key("ohlcv"))
    assert not ent.is_valid_key("read:section:does_not_exist")


# --------------------------------------------------------------------------- #
# Fixtures — cache isolation + auth override
# --------------------------------------------------------------------------- #
@pytest.fixture(autouse=True)
def _clear_principal_cache() -> None:
    """The principal cache is module-level; clear it so subs don't leak between tests."""
    if tenancy._principal_cache is not None:
        tenancy._principal_cache.clear()
    yield
    if tenancy._principal_cache is not None:
        tenancy._principal_cache.clear()


@pytest.fixture
def auth_as() -> AsyncGenerator[Callable[[str], None], None]:
    """Return a setter that overrides get_current_user with a given Auth0 sub."""

    def _set(sub: str) -> None:
        app.dependency_overrides[get_current_user] = lambda: {
            "sub": sub,
            "email": "t@example.com",
            "name": "T",
            "permissions": [],
        }

    yield _set
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture
def enforced(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ENTITLEMENTS_ENFORCED", True)


async def _seed_tenant(
    db: AsyncSession, sub: str, keys: set[str], *, tier: str = "export_premium"
) -> uuid.UUID:
    account = TenantAccount(code=f"acct-{uuid.uuid4().hex[:8]}", name="T", tier=tier)
    db.add(account)
    await db.flush()
    db.add(TenantUser(account_id=account.id, auth0_sub=sub))
    for key in keys:
        db.add(
            TenantEntitlement(
                account_id=account.id,
                entitlement_key=key,
                effective_from=date.today(),
                active=True,
            )
        )
    await db.flush()
    return account.id


# --------------------------------------------------------------------------- #
# Integration — the gate
# --------------------------------------------------------------------------- #
@pytest.mark.integration
@pytest.mark.asyncio
async def test_no_tenant_row_is_denied_when_enforced(
    client: AsyncClient, auth_as, enforced
) -> None:
    """MANDATORY: an authenticated login with no tenant seat gets 403 (default-deny)."""
    auth_as("auth0|stranger")
    r = await client.get(WEATHER, params={})
    assert r.status_code == 403


@pytest.mark.integration
@pytest.mark.asyncio
async def test_unentitled_section_is_denied(
    client: AsyncClient, db_session: AsyncSession, auth_as, enforced
) -> None:
    sub = "auth0|signal-only"
    await _seed_tenant(db_session, sub, {ent.SECTION_SIGNAL})
    auth_as(sub)
    r = await client.get(WEATHER)
    assert r.status_code == 403


@pytest.mark.integration
@pytest.mark.asyncio
async def test_entitled_section_passes_the_gate(
    client: AsyncClient, db_session: AsyncSession, auth_as, enforced
) -> None:
    sub = "auth0|has-weather"
    await _seed_tenant(db_session, sub, {ent.SECTION_WEATHER})
    auth_as(sub)
    r = await client.get(WEATHER)
    # The gate passed; downstream may 200 or fail on absent market data, but NEVER 403.
    assert r.status_code != 403


@pytest.mark.integration
@pytest.mark.asyncio
async def test_dark_mode_lets_everyone_through(
    client: AsyncClient, auth_as
) -> None:
    """Flag OFF (default): no tenant row, still not 403 — preserves single-shared-view."""
    assert settings.ENTITLEMENTS_ENFORCED is False
    auth_as("auth0|nobody")
    r = await client.get(WEATHER)
    assert r.status_code != 403


@pytest.mark.integration
@pytest.mark.asyncio
async def test_auth_me_surfaces_entitlements(
    client: AsyncClient, db_session: AsyncSession, auth_as
) -> None:
    sub = "auth0|me"
    await _seed_tenant(db_session, sub, {ent.SECTION_SIGNAL, ent.SECTION_CHART}, tier="coop_premium")
    auth_as(sub)
    r = await client.get(ME)
    assert r.status_code == 200
    body = r.json()
    assert body["tier"] == "coop_premium"
    assert set(body["entitlements"]) == {ent.SECTION_SIGNAL, ent.SECTION_CHART}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_export_series_filter(
    client: AsyncClient, db_session: AsyncSession, auth_as, enforced
) -> None:
    # Grant only the 'weather' series (a plain table — no chained view needed).
    sub = "auth0|weather-export-only"
    await _seed_tenant(db_session, sub, {ent.export_key("weather")})
    auth_as(sub)
    params = {"from": "2026-01-01", "to": "2026-02-01"}
    denied = await client.get(EXPORT, params={**params, "series": "fx"})
    assert denied.status_code == 403
    allowed = await client.get(EXPORT, params={**params, "series": "weather"})
    assert allowed.status_code == 200


@pytest.mark.integration
@pytest.mark.asyncio
async def test_revoke_tombstone_hides_key_from_current_view(
    client: AsyncClient, db_session: AsyncSession, auth_as, enforced
) -> None:
    """A later active=false row wins in the current view → the key is gone → 403."""
    sub = "auth0|revoked"
    account = TenantAccount(code=f"acct-{uuid.uuid4().hex[:8]}", name="T", tier="export_premium")
    db_session.add(account)
    await db_session.flush()
    db_session.add(TenantUser(account_id=account.id, auth0_sub=sub))
    # Grant yesterday, revoke today → DISTINCT ON (…, effective_from DESC) picks the revoke.
    db_session.add(
        TenantEntitlement(
            account_id=account.id,
            entitlement_key=ent.SECTION_WEATHER,
            effective_from=date.today() - timedelta(days=1),
            active=True,
        )
    )
    db_session.add(
        TenantEntitlement(
            account_id=account.id,
            entitlement_key=ent.SECTION_WEATHER,
            effective_from=date.today(),
            active=False,
        )
    )
    await db_session.flush()
    auth_as(sub)
    r = await client.get(WEATHER)
    assert r.status_code == 403


@pytest.mark.integration
@pytest.mark.asyncio
async def test_internal_account_sees_everything_without_key_rows(
    client: AsyncClient, db_session: AsyncSession, auth_as, enforced
) -> None:
    """An internal account with ZERO explicit entitlement rows still passes gates
    (read-time short-circuit → full catalogue, incl. future keys)."""
    sub = "auth0|staff"
    await _seed_tenant(db_session, sub, set(), tier=ent.INTERNAL)  # no keys granted
    auth_as(sub)
    r = await client.get(WEATHER)
    assert r.status_code != 403
    me = await client.get(ME)
    assert set(me.json()["entitlements"]) == ent.ALL_ENTITLEMENT_KEYS
