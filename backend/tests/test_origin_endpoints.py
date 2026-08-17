"""Origin flow endpoints + service — matrix block ② rows sold to Coop Premium.

Three things under test, in descending order of what would hurt if wrong:

1. **No nominative leak.** `campaign` is held by all seven tiers and
   `market-views` by six; neither may expose an exporter, a destination or a port,
   because those are separate keys. A leak here sells `nominative` for free.
2. **Two keys, two gates.** The tier → 200/403 matrix for both routes.
3. The arithmetic reaches the payload intact — windows, perimeters, flags.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import entitlements as ent
from app.core.config import settings
from app.core.database import get_db
from app.core.tenancy import TenantPrincipal, get_current_principal
from app.main import app
from app.services.origin_flow_service import (
    OriginDataUnavailableError,
    get_campaign,
    get_market_views,
)

SEASON = "2025-2026"
PREV_SEASON = "2024-2025"

# Derived from settings, never hardcoded: the mounted prefix is /api/v1 while the
# load balancer exposes /v1, and a literal would pass locally and 404 in CI.
CAMPAIGN_URL = f"{settings.API_V1_STR}/dashboard/origin/campaign"
MARKET_VIEWS_URL = f"{settings.API_V1_STR}/dashboard/origin/market-views"


# ---------------------------------------------------------------------------
# fixtures — a two-season batch with one GEPEX and one non-GEPEX exporter
# ---------------------------------------------------------------------------
async def _seed(db: AsyncSession) -> uuid.UUID:
    """Minimal but complete: both seasons, both perimeters, STATSER lagging.

    Numbers are chosen so every derived figure is checkable by hand:
    per month CARGILL (GEPEX) ships 600 t beans + 160 t transformed and buys
    1 000 t; OTHERCO (non-GEPEX) ships 100 t beans and buys 200 t.
    """
    await db.execute(text("DELETE FROM pl_origin_ingest_batch"))
    await db.execute(text("DELETE FROM ref_origin_entity"))

    batch_id = (
        await db.execute(
            text(
                """
                INSERT INTO pl_origin_ingest_batch
                    (source, source_hashes, ingested_by, row_counts, data_as_of,
                     is_current)
                VALUES ('files', '{}'::jsonb, 'pytest', '{}'::jsonb,
                        '2026-07-31', true)
                RETURNING id
                """
            )
        )
    ).scalar_one()

    exporters = {}
    for name, gepex in (("CARGILL", True), ("OTHERCO", False)):
        exporters[name] = (
            await db.execute(
                text(
                    """
                    INSERT INTO ref_origin_entity
                        (entity_type, source_name, canonical_name, is_gepex_member)
                    VALUES ('exporter', :n, :n, :g) RETURNING id
                    """
                ),
                {"n": name, "g": gepex},
            )
        ).scalar_one()
    destination = (
        await db.execute(
            text(
                """
                INSERT INTO ref_origin_entity
                    (entity_type, source_name, canonical_name)
                VALUES ('destination', 'PAYS-BAS', 'PAYS-BAS') RETURNING id
                """
            )
        )
    ).scalar_one()

    months = {
        SEASON: [date(2025, 10, 1), date(2025, 11, 1), date(2025, 12, 1)],
        PREV_SEASON: [date(2024, 10, 1), date(2024, 11, 1)],
    }
    for season, periods in months.items():
        for period in periods:
            for name, beans, transformed, purchases in (
                ("CARGILL", 600.0, 160.0, 1_000.0),
                ("OTHERCO", 100.0, 0.0, 200.0),
            ):
                for product, tonnes in (("FEVES", beans), ("MASSE", transformed)):
                    if tonnes <= 0:
                        continue
                    await db.execute(
                        text(
                            """
                            INSERT INTO pl_origin_flow_monthly
                                (ingest_batch_id, period_date, season,
                                 exporter_entity_id, product_code,
                                 destination_entity_id, port, export_tonnes,
                                 valcaf, duties_taxes)
                            VALUES (:b, :p, :s, :e, :prod, :d, 'ABIDJAN', :t,
                                    :v, :x)
                            """
                        ),
                        {
                            "b": batch_id,
                            "p": period,
                            "s": season,
                            "e": exporters[name],
                            "prod": product,
                            "d": destination,
                            "t": tonnes,
                            "v": tonnes * 1_000_000,
                            "x": tonnes * 100_000,
                        },
                    )
                await db.execute(
                    text(
                        """
                        INSERT INTO pl_origin_purchase_monthly
                            (ingest_batch_id, period_date, season,
                             exporter_entity_id, net_weight_kg)
                        VALUES (:b, :p, :s, :e, :kg)
                        """
                    ),
                    {
                        "b": batch_id,
                        "p": period,
                        "s": season,
                        "e": exporters[name],
                        "kg": purchases * 1000,
                    },
                )
            # STATSER lags: only the first month of each season is declared.
            if period == periods[0]:
                await db.execute(
                    text(
                        """
                        INSERT INTO pl_origin_grinding_monthly
                            (ingest_batch_id, period_date, season, tons_ground)
                        VALUES (:b, :p, :s, 180.0)
                        """
                    ),
                    {"b": batch_id, "p": period, "s": season},
                )
    return batch_id


@pytest.fixture
async def seeded(db_session: AsyncSession) -> AsyncSession:
    await _seed(db_session)
    return db_session


# ---------------------------------------------------------------------------
# 1. no nominative leak — the thing that would cost money
# ---------------------------------------------------------------------------
_FORBIDDEN_SUBSTRINGS = ("CARGILL", "OTHERCO", "PAYS-BAS", "ABIDJAN")


def _flatten(payload: object) -> list[str]:
    """Every scalar in the payload, as strings — so a leak cannot hide in a nested
    block a targeted assertion would miss."""
    if isinstance(payload, dict):
        return [s for value in payload.values() for s in _flatten(value)]
    if isinstance(payload, (list, tuple)):
        return [s for item in payload for s in _flatten(item)]
    return [str(payload)]


@pytest.mark.parametrize("view", ["campaign", "market_views"])
async def test_no_exporter_destination_or_port_ever_appears(
    seeded: AsyncSession, view: str
) -> None:
    """`campaign` is sold to all 7 tiers and `market-views` to 6. Naming an
    operator in either would hand `read:watchai:nominative` away for free, and a
    destination would hand away `read:watchai:destinations`."""
    payload = (
        await get_campaign(seeded)
        if view == "campaign"
        else await get_market_views(seeded)
    )

    haystack = " ".join(_flatten(payload)).upper()
    for forbidden in _FORBIDDEN_SUBSTRINGS:
        assert forbidden not in haystack, f"{view} leaked {forbidden}"


async def test_campaign_carries_no_growth_ranking(seeded: AsyncSession) -> None:
    """`calc_growth`'s top-3 hausses/baisses names exporters, so it belongs to
    /exporters behind `nominative` — not to the row every tier holds."""
    payload = await get_campaign(seeded)

    assert "top_growth" not in payload
    assert "growth" not in payload


# ---------------------------------------------------------------------------
# 2. the gates
# ---------------------------------------------------------------------------
_TIER_EXPECTATIONS = [
    (ent.COOP_ESSENTIEL, 200, 403),
    (ent.COOP_PREMIUM, 200, 200),
    (ent.EXPORT_ESSENTIEL, 200, 200),
    (ent.EXPORT_PREMIUM, 200, 200),
    (ent.EXPORT_PRO, 200, 200),
    (ent.SIGNAL_PLUS, 200, 200),
    (ent.ORIGIN_DESK, 200, 200),
]


@pytest.fixture
async def client_for(seeded: AsyncSession):
    """Build a client whose principal holds exactly one tier's template."""

    def _make(tier: str) -> AsyncClient:
        async def override_db():
            yield seeded

        def override_principal() -> TenantPrincipal:
            return TenantPrincipal(
                sub=f"auth0|{tier}",
                account_id=uuid.uuid4(),
                tier=tier,
                entitlements=frozenset(ent.TIER_TEMPLATES[tier]),
            )

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[get_current_principal] = override_principal
        return AsyncClient(
            transport=ASGITransport(app=app),  # type: ignore[arg-type]
            base_url="http://test",
        )

    yield _make
    app.dependency_overrides.clear()


@pytest.fixture
def enforced(monkeypatch: pytest.MonkeyPatch) -> None:
    """Turn enforcement on for the gate tests only.

    The catalogue ships dark (`ENTITLEMENTS_ENFORCED=False`), so gates are a
    no-op passthrough in the default configuration — which is exactly why the
    403 side of the matrix has to be tested under an explicit flip. Without this
    fixture the assertions would pass vacuously the day enforcement is enabled
    and a key is wrong.
    """
    monkeypatch.setattr(settings, "ENTITLEMENTS_ENFORCED", True)


async def test_gates_are_a_passthrough_while_the_catalogue_ships_dark(
    client_for,
) -> None:
    """Documents the current deployment posture: a tier without `market_views`
    still gets 200 because enforcement is off. Flipping the flag is what makes the
    matrix bite — and the test below proves it does."""
    assert settings.ENTITLEMENTS_ENFORCED is False
    async with client_for(ent.COOP_ESSENTIEL) as client:
        assert (await client.get(MARKET_VIEWS_URL)).status_code == 200


@pytest.mark.parametrize(("tier", "campaign", "market_views"), _TIER_EXPECTATIONS)
async def test_tier_gate_matrix(
    client_for, enforced, tier: str, campaign: int, market_views: int
) -> None:
    """The matrix, under enforcement. Coop Essentiel is the only tier without
    `market_views`, and it still reaches `campaign` through the reduced variant."""
    async with client_for(tier) as client:
        assert (await client.get(CAMPAIGN_URL)).status_code == campaign
        assert (await client.get(MARKET_VIEWS_URL)).status_code == market_views


async def test_coop_essentiel_reaches_campaign_through_the_reduced_variant(
    client_for, enforced
) -> None:
    """It holds `campaign_monthly:reduced`, never `campaign_monthly` — the any-of gate
    is what makes the reduced grant a grant rather than a denial."""
    template = ent.TIER_TEMPLATES[ent.COOP_ESSENTIEL]

    assert ent.WATCHAI_CAMPAIGN_REDUCED in template
    assert ent.WATCHAI_CAMPAIGN not in template
    async with client_for(ent.COOP_ESSENTIEL) as client:
        assert (await client.get(CAMPAIGN_URL)).status_code == 200


# ---------------------------------------------------------------------------
# 3. the arithmetic reaches the payload intact
# ---------------------------------------------------------------------------
async def test_campaign_monthly_series_and_synthesis(seeded: AsyncSession) -> None:
    payload = await get_campaign(seeded)

    assert payload["season"] == SEASON
    assert payload["data_as_of"] == date(2026, 7, 31)
    assert len(payload["monthly"]) == 3
    october = payload["monthly"][0]
    assert october["purchases_t"] == pytest.approx(1_200.0)
    assert october["exports_beans_t"] == pytest.approx(700.0)
    assert october["exports_transformed_t"] == pytest.approx(160.0)
    # STATSER declared only October.
    assert october["grinding_declared_t"] == pytest.approx(180.0)
    assert payload["monthly"][1]["grinding_declared_t"] is None

    assert payload["month"]["period"] == date(2025, 12, 1)
    assert payload["month"]["exports_t"] == pytest.approx(860.0)


async def test_monthly_balance_is_served_not_left_to_the_client(
    seeded: AsyncSession,
) -> None:
    """The same arithmetic must have one implementation. A client re-deriving
    `achats − fèves − transformé/0.80` would be free to drift from the season
    balance computed here (.claude/rules/pipeline-continuity.md)."""
    october = (await get_campaign(seeded))["monthly"][0]

    # 1 200 t bought, 700 t of beans out, 160 t of product out (= 200 t of beans).
    assert october["grinding_derived_t"] == pytest.approx(200.0)
    assert october["balance_t"] == pytest.approx(1_200.0 - 700.0 - 200.0)


async def test_monthly_balance_may_be_negative(seeded: AsyncSession) -> None:
    """A single month can legitimately go negative — that is not an error state,
    so the field is a plain float rather than something clamped at zero."""
    batch = (
        await seeded.execute(
            text("SELECT id FROM pl_origin_ingest_batch WHERE is_current")
        )
    ).scalar_one()
    await seeded.execute(
        text(
            "DELETE FROM pl_origin_purchase_monthly "
            "WHERE ingest_batch_id = :b AND period_date = '2025-10-01'"
        ),
        {"b": batch},
    )

    october = (await get_campaign(seeded))["monthly"][0]
    assert october["balance_t"] < 0


async def test_ytd_windows_differ_per_source(seeded: AsyncSession) -> None:
    """The §6 rule, visible in the payload: exports and purchases have 3 months,
    grinding 1. A shared window would invent a collapse."""
    blocks = {b["source"]: b for b in (await get_campaign(seeded))["ytd"]}

    assert blocks["exports"]["window"]["months"] == 3
    assert blocks["purchases"]["window"]["months"] == 3
    assert blocks["grinding"]["window"]["months"] == 1
    assert blocks["exports"]["previous_season"] == PREV_SEASON
    # 3 months this season vs the 2 published last season at the same months.
    assert blocks["exports"]["current_t"] == pytest.approx(2_580.0)
    assert blocks["exports"]["previous_t"] == pytest.approx(1_720.0)


async def test_transformation_is_bean_equivalent_and_excludes_statser(
    seeded: AsyncSession,
) -> None:
    block = (await get_market_views(seeded))["transformation"]

    # 3 months x 160 t transformed / 0.80
    assert block["grinding_derived_t"] == pytest.approx(600.0)
    assert block["purchases_t"] == pytest.approx(3_600.0)
    assert block["exports_beans_t"] == pytest.approx(2_100.0)
    assert block["balance_t"] == pytest.approx(3_600.0 - 2_100.0 - 600.0)
    assert block["outflow_exceeds_purchases"] is False
    assert block["stock_signal"] == "stock_constitue"
    assert block["perimeter"] == "all_operators"


async def test_confrontation_is_gepex_on_both_sides(seeded: AsyncSession) -> None:
    """The fix that matters: the derived side is filtered to GEPEX exporters, so
    the gap is not a population mismatch. CARGILL alone ships 160 t transformed in
    the declared month → 200 t derived vs 180 t declared."""
    confrontation = (await get_market_views(seeded))["transformation"][
        "statser_confrontation"
    ]

    assert confrontation is not None
    assert confrontation["perimeter"] == "gepex"
    assert confrontation["derived_t"] == pytest.approx(200.0)
    assert confrontation["declared_t"] == pytest.approx(180.0)
    assert confrontation["gap_t"] == pytest.approx(20.0)
    # Its window is narrower than the balance's — STATSER lags.
    assert confrontation["window"]["months"] == 1


async def test_confrontation_excludes_non_gepex_transformed_exports(
    seeded: AsyncSession,
) -> None:
    """Guard against regressing to all-operator derived grinding: adding a large
    non-GEPEX transformed export must not move the confrontation at all."""
    before = (await get_market_views(seeded))["transformation"]["statser_confrontation"]
    other = (
        await seeded.execute(
            text("SELECT id FROM ref_origin_entity WHERE source_name = 'OTHERCO'")
        )
    ).scalar_one()
    batch = (
        await seeded.execute(
            text("SELECT id FROM pl_origin_ingest_batch WHERE is_current")
        )
    ).scalar_one()
    await seeded.execute(
        text(
            """
            INSERT INTO pl_origin_flow_monthly
                (ingest_batch_id, period_date, season, exporter_entity_id,
                 product_code, port, export_tonnes)
            VALUES (:b, '2025-10-01', :s, :e, 'BEURRE', 'ABIDJAN', 5000.0)
            """
        ),
        {"b": batch, "s": SEASON, "e": other},
    )

    after = (await get_market_views(seeded))["transformation"]["statser_confrontation"]
    assert before is not None and after is not None
    assert after["derived_t"] == pytest.approx(before["derived_t"])


async def test_transformation_is_absent_when_no_purchases_exist(
    seeded: AsyncSession,
) -> None:
    """The purchase master starts 2020-10, so older seasons have exports and a mix
    but no balance. Zeros would print "solde 0 t, stock constitué" as if measured."""
    await seeded.execute(
        text("DELETE FROM pl_origin_purchase_monthly WHERE season = :s"),
        {"s": SEASON},
    )

    views = await get_market_views(seeded, season=SEASON)

    assert views["transformation"] is None
    # The rest of the view still works — that is the point of degrading here.
    assert views["product_mix"]
    assert views["monthly"]


async def test_product_mix_carries_the_bean_flag(seeded: AsyncSession) -> None:
    """So a consumer can see which denominator any "transformation" figure used —
    the published report counts HORS GRADE as transformed, we do not."""
    views = await get_market_views(seeded)
    mix = {line["product_code"]: line for line in views["product_mix"]}

    assert mix["FEVES"]["is_bean_equivalent"] is True
    assert mix["MASSE"]["is_bean_equivalent"] is False
    assert sum(line["share_pct"] for line in mix.values()) == pytest.approx(100.0)


async def test_season_totals_cover_every_season(seeded: AsyncSession) -> None:
    views = await get_market_views(seeded)
    totals = {row["season"]: row for row in views["season_totals"]}

    assert set(totals) == {SEASON, PREV_SEASON}
    assert totals[SEASON]["exports_t"] == pytest.approx(2_580.0)


# ---------------------------------------------------------------------------
# parameter resolution + unavailable
# ---------------------------------------------------------------------------
async def test_unknown_season_falls_back_to_newest(seeded: AsyncSession) -> None:
    """A stale bookmark should show data, not a 404."""
    assert (await get_campaign(seeded, season="1999-2000"))["season"] == SEASON


async def test_explicit_season_is_honoured(seeded: AsyncSession) -> None:
    payload = await get_campaign(seeded, season=PREV_SEASON)

    assert payload["season"] == PREV_SEASON
    assert len(payload["monthly"]) == 2


async def test_explicit_month_is_honoured(seeded: AsyncSession) -> None:
    payload = await get_campaign(seeded, month="2025-10")

    assert payload["month"]["period"] == date(2025, 10, 1)


async def test_unparseable_month_falls_back(seeded: AsyncSession) -> None:
    payload = await get_campaign(seeded, month="not-a-month")

    assert payload["month"]["period"] == date(2025, 12, 1)


async def test_no_current_batch_raises(db_session: AsyncSession) -> None:
    await db_session.execute(text("DELETE FROM pl_origin_ingest_batch"))

    with pytest.raises(OriginDataUnavailableError, match="watchai-sync"):
        await get_campaign(db_session)


async def test_missing_data_surfaces_as_503_not_404(client_for, seeded) -> None:  # noqa: F811
    """The subsystem having no data is operational, not a bad request."""
    await seeded.execute(text("DELETE FROM pl_origin_ingest_batch"))

    async with client_for(ent.COOP_PREMIUM) as client:
        assert (await client.get(CAMPAIGN_URL)).status_code == 503
