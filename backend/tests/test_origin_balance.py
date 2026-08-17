"""Material balance — pure arithmetic, no database.

Ports the invariants of `api/tests/test_bilan_matiere.py` (watch-ai
`refonte-da-v2` @ `11336ef`) as assertions in our own suite, per
port-inventory §1: *take these as tests, not as prose*.

The centrepiece is `test_v1_double_count_is_not_reproduced`: it reconstructs the
exact v1 formula on the same numbers and shows it produces the 124 % outflow rate
and negative balance that were shipped for months, while ours does not.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.services.origin_balance import (
    PERIMETER_ALL,
    PERIMETER_GEPEX,
    RENDEMENT_BROYAGE,
    BalanceInvariantError,
    MonthlyOriginSeries,
    SeasonBalance,
    assert_balance_invariants,
    balance_window,
    compute_ratios,
    compute_season_balance,
    confront_statser,
    cumulative_balance,
    derive_grinding,
    monthly_balance,
    ytd_block,
)


def _month(
    period: date,
    purchases: float = 1_000.0,
    beans: float = 600.0,
    transformed: float = 160.0,
    declared: float | None = None,
) -> MonthlyOriginSeries:
    """A coherent month by default: 1 000 t bought, 600 t of beans out, 160 t of
    product out (= 200 t of bean input), leaving a 200 t balance."""
    return MonthlyOriginSeries(
        period=period,
        purchases_t=purchases,
        exports_beans_t=beans,
        exports_transformed_t=transformed,
        grinding_declared_t=declared,
    )


_SEASON = "2025-2026"
# Season order is Oct→Sep, never calendar order.
_OCT, _NOV, _DEC, _JAN = (
    date(2025, 10, 1),
    date(2025, 11, 1),
    date(2025, 12, 1),
    date(2026, 1, 1),
)


# ---------------------------------------------------------------------------
# the pinned constant
# ---------------------------------------------------------------------------
def test_rendement_broyage_is_pinned() -> None:
    """Integration doc risk #1: the one constant whose silent upstream drift
    would restate every published balance."""
    assert RENDEMENT_BROYAGE == 0.80


def test_derived_grinding_is_larger_than_the_product_weight() -> None:
    """§4.1 — recovering bean input from product weight means dividing by the
    yield, so the result exceeds the input. Reads as a bug; is the point."""
    assert derive_grinding(160.0) == pytest.approx(200.0)
    assert derive_grinding(160.0) > 160.0


# ---------------------------------------------------------------------------
# the v1 bug
# ---------------------------------------------------------------------------
def test_v1_double_count_is_not_reproduced() -> None:
    """The regression this module exists for.

    v1: ``(exports_ALL_products + grinding_declared) / achats``. Transformed
    exports are the *output* of that grinding, so the beans were counted twice.
    On these numbers it yields 124 % and a negative balance — the exact symptoms
    reported on 2026-07-17.
    """
    series = _month(
        _OCT, purchases=1_000.0, beans=600.0, transformed=160.0, declared=480.0
    )

    v1_outflow_pct = (
        (series.exports_total_t + (series.grinding_declared_t or 0))
        / series.purchases_t
        * 100
    )
    v1_balance = (
        series.purchases_t - series.exports_total_t - (series.grinding_declared_t or 0)
    )
    assert v1_outflow_pct > 100.0  # 124 %
    assert v1_balance < 0

    ours = compute_season_balance(_SEASON, [series])
    assert ours.ratios.outflow_rate_pct == pytest.approx(80.0)
    assert ours.balance_t == pytest.approx(200.0)
    assert_balance_invariants(ours)


def test_declared_grinding_never_enters_the_balance() -> None:
    """STATSER is not an input (§4.2/§5). Changing the declaration must not move
    the balance by a single tonne."""
    without = compute_season_balance(_SEASON, [_month(_OCT, declared=None)])
    with_huge = compute_season_balance(_SEASON, [_month(_OCT, declared=999_999.0)])

    assert without.balance_t == pytest.approx(with_huge.balance_t)
    assert without.ratios.outflow_rate_pct == pytest.approx(
        with_huge.ratios.outflow_rate_pct
    )


# ---------------------------------------------------------------------------
# monthly balance
# ---------------------------------------------------------------------------
def test_monthly_balance_is_bean_equivalent_arithmetic() -> None:
    row = monthly_balance(_month(_OCT))

    assert row.grinding_derived_t == pytest.approx(200.0)
    assert row.balance_t == pytest.approx(1_000.0 - 600.0 - 200.0)


def test_a_single_month_may_legitimately_go_negative() -> None:
    """Off-season shipments draw on stock bought earlier. It is the *season*
    balance that cannot go negative, not each month."""
    row = monthly_balance(_month(_JAN, purchases=10.0, beans=600.0, transformed=0.0))

    assert row.balance_t < 0
    assert row.signal == "sortie_stock"


def test_positive_month_signals_stock_entry() -> None:
    assert monthly_balance(_month(_OCT)).signal == "entree_stock"


# ---------------------------------------------------------------------------
# ratios (§4.3)
# ---------------------------------------------------------------------------
def test_the_three_ratios() -> None:
    balance = compute_season_balance(_SEASON, [_month(_OCT)])

    assert balance.ratios.balance_pct == pytest.approx(20.0)
    assert balance.ratios.transformation_rate_pct == pytest.approx(20.0)
    assert balance.ratios.outflow_rate_pct == pytest.approx(80.0)


def test_ratios_are_undefined_not_zero_when_nothing_was_bought() -> None:
    """A ratio over an empty denominator is undefined. Returning 0 would publish
    "0 % transformation" for a month with no purchase data at all."""
    ratios = compute_ratios(
        purchases_t=0.0, exports_beans_t=0.0, grinding_derived_t=0.0, balance_t=0.0
    )

    assert ratios.balance_pct is None
    assert ratios.transformation_rate_pct is None
    assert ratios.outflow_rate_pct is None


def test_outflow_and_balance_are_complementary() -> None:
    """`taux_sortie + solde_pct == 100` by construction — a cheap algebraic check
    that the two are derived from the same decomposition."""
    balance = compute_season_balance(_SEASON, [_month(_OCT), _month(_NOV)])

    assert balance.ratios.outflow_rate_pct is not None
    assert balance.ratios.balance_pct is not None
    assert (
        balance.ratios.outflow_rate_pct + balance.ratios.balance_pct
        == pytest.approx(100.0)
    )


# ---------------------------------------------------------------------------
# invariants (§4.3)
# ---------------------------------------------------------------------------
def test_outflow_over_100_is_a_publishable_flag_not_only_an_error() -> None:
    """Empirical, on `11336ef`: season 2021-2022 lands at 108 % because the achats
    master covers fewer operators than customs exports (34 exporters shipping
    102 829 t never appear in it) and stock carries across seasons.

    So the serving layer must publish the season with a flag, not 500 on it. The
    raising checker stays for fixtures we control and for the double-count
    signature; this flag is what an endpoint reads.
    """
    over = compute_season_balance(
        _SEASON, [_month(_OCT, purchases=100.0, beans=600.0, transformed=0.0)]
    )

    assert over.outflow_exceeds_purchases is True
    assert over.stock_signal == "stock_n1_mobilise"


def test_coherent_season_is_not_flagged() -> None:
    assert (
        compute_season_balance(_SEASON, [_month(_OCT)]).outflow_exceeds_purchases
        is False
    )


def test_confrontation_requires_an_explicit_perimeter() -> None:
    """STATSER is GEPEX-only. Defaulting the perimeter would let a caller compare
    all-operator derived grinding against a GEPEX declaration and have the payload
    claim it was GEPEX — the ~3x bias of §4.5, silently."""
    with pytest.raises(TypeError):
        confront_statser([_month(_OCT, declared=180.0)])  # type: ignore[call-arg]


def test_transformation_rate_is_over_purchases_not_over_exports() -> None:
    """Two different figures share the name "taux de transformation". This one is
    grinding / achats (§4.3). The export-mix share is a different denominator, and
    on real data they read 20,4 % vs 19,9 % — close enough to be confused."""
    balance = compute_season_balance(_SEASON, [_month(_OCT)])

    over_purchases = balance.ratios.transformation_rate_pct
    over_exports = balance.exports_transformed_t / balance.exports_total_t * 100

    assert over_purchases == pytest.approx(20.0)
    assert over_exports == pytest.approx(160.0 / 760.0 * 100)
    assert over_purchases != pytest.approx(over_exports)


def test_invariants_pass_on_coherent_data() -> None:
    assert_balance_invariants(
        compute_season_balance(_SEASON, [_month(_OCT), _month(_NOV)])
    )


def test_outflow_above_100_raises() -> None:
    """The v1 symptom. Serving a 124 % outflow rate to a client is worse than
    serving an error."""
    broken = compute_season_balance(
        _SEASON, [_month(_OCT, purchases=100.0, beans=600.0, transformed=0.0)]
    )

    with pytest.raises(BalanceInvariantError, match="outside"):
        assert_balance_invariants(broken)


def test_the_two_invariants_of_section_4_3_are_algebraically_one() -> None:
    """business-rules §4.3 lists two invariants; for any positive purchase volume
    they are the same condition.

        solde < 0  <=>  B + G > P  <=>  (B + G) / P > 1  <=>  taux_sortie > 100 %

    Worth stating explicitly so nobody later "fixes" one of them in isolation and
    believes two independent guards are still standing. What follows shows the
    residual case the balance check alone covers.
    """
    broken = compute_season_balance(
        _SEASON, [_month(_OCT, purchases=100.0, beans=90.0, transformed=80.0)]
    )

    assert broken.balance_t < 0
    assert broken.ratios.outflow_rate_pct is not None
    assert broken.ratios.outflow_rate_pct > 100.0
    # The outflow branch fires first, which is why the message names the ratio.
    with pytest.raises(BalanceInvariantError, match="outside"):
        assert_balance_invariants(broken)


def test_balance_check_covers_the_case_the_ratio_check_cannot() -> None:
    """A zero denominator makes every ratio ``None``, so the outflow guard goes
    silent — the balance guard is what still catches a negative there.

    Unreachable through ``compute_season_balance`` (its window excludes months
    without purchases, so season purchases are either positive or the whole thing
    is zero), which is exactly why it is tested against a directly constructed
    value: a future service that assembles ``SeasonBalance`` itself must still hit
    the guard.
    """
    broken = SeasonBalance(
        season=_SEASON,
        months=(_OCT,),
        purchases_t=0.0,
        exports_beans_t=90.0,
        exports_transformed_t=0.0,
        grinding_derived_t=0.0,
        balance_t=-90.0,
        ratios=compute_ratios(0.0, 90.0, 0.0, -90.0),
        monthly=(),
    )

    assert broken.ratios.outflow_rate_pct is None  # the ratio guard is blind here
    with pytest.raises(BalanceInvariantError, match="negative"):
        assert_balance_invariants(broken)


def test_invariant_message_points_at_the_bean_equivalent_conversion() -> None:
    """The error must tell the next person where to look, not just that something
    is wrong — the fix is always the same: convert transformed exports back to
    bean equivalent before they enter the balance."""
    broken = SeasonBalance(
        season=_SEASON,
        months=(_OCT,),
        purchases_t=0.0,
        exports_beans_t=90.0,
        exports_transformed_t=0.0,
        grinding_derived_t=0.0,
        balance_t=-90.0,
        ratios=compute_ratios(0.0, 90.0, 0.0, -90.0),
        monthly=(),
    )

    with pytest.raises(BalanceInvariantError, match="bean equivalent"):
        assert_balance_invariants(broken)


# ---------------------------------------------------------------------------
# window (§4.2)
# ---------------------------------------------------------------------------
def test_window_is_purchases_intersect_exports_not_three_sources() -> None:
    """Grinding is derived, so STATSER's lag must not truncate the balance. A
    month with no declaration still counts."""
    series = [_month(_OCT, declared=480.0), _month(_NOV, declared=None)]

    assert balance_window(series) == (_OCT, _NOV)


def test_one_sided_months_are_excluded() -> None:
    """A month with purchases but no exports would look like a huge surplus that
    is really just missing data."""
    series = [
        _month(_OCT),
        _month(_NOV, beans=0.0, transformed=0.0),  # no exports
        _month(_DEC, purchases=0.0),  # no purchases
    ]

    assert balance_window(series) == (_OCT,)


def test_excluded_months_do_not_contribute_to_the_totals() -> None:
    balance = compute_season_balance(
        _SEASON,
        [_month(_OCT), _month(_NOV, purchases=50_000.0, beans=0.0, transformed=0.0)],
    )

    assert balance.months == (_OCT,)
    assert balance.purchases_t == pytest.approx(1_000.0)


# ---------------------------------------------------------------------------
# season aggregation + cumulative
# ---------------------------------------------------------------------------
def test_season_totals_and_window_bounds() -> None:
    balance = compute_season_balance(
        _SEASON, [_month(_NOV), _month(_OCT), _month(_DEC)]
    )

    assert balance.months == (_OCT, _NOV, _DEC)
    assert balance.window_from == _OCT
    assert balance.window_to == _DEC
    assert balance.purchases_t == pytest.approx(3_000.0)
    assert balance.balance_t == pytest.approx(600.0)
    assert balance.perimeter == PERIMETER_ALL


def test_monthly_rows_come_back_in_season_order() -> None:
    """Season order (Oct→Sep) is never calendar order, and the cumulative depends
    on it."""
    balance = compute_season_balance(_SEASON, [_month(_JAN), _month(_OCT)])

    assert [row.period for row in balance.monthly] == [_OCT, _JAN]


def test_cumulative_balance_is_a_running_total() -> None:
    balance = compute_season_balance(
        _SEASON, [_month(_OCT), _month(_NOV), _month(_DEC)]
    )

    assert cumulative_balance(balance.monthly) == pytest.approx((200.0, 400.0, 600.0))


def test_season_stock_signal() -> None:
    assert (
        compute_season_balance(_SEASON, [_month(_OCT)]).stock_signal
        == "stock_constitue"
    )


def test_empty_series_yields_an_empty_window_not_a_crash() -> None:
    balance = compute_season_balance(_SEASON, [])

    assert balance.months == ()
    assert balance.window_from is None
    assert balance.ratios.outflow_rate_pct is None
    assert_balance_invariants(balance)


# ---------------------------------------------------------------------------
# display mode independence (§4.4)
# ---------------------------------------------------------------------------
def test_both_export_figures_are_carried_for_the_display_toggle() -> None:
    """The brut/fèves toggle changes which export figure is *shown*, never the
    balance. Here it cannot: no function takes a mode, so mode-independence is
    structural rather than policed by an assertion."""
    balance = compute_season_balance(_SEASON, [_month(_OCT)])

    assert balance.exports_beans_t == pytest.approx(600.0)
    assert balance.exports_total_t == pytest.approx(760.0)
    assert balance.monthly[0].exports_beans_t == pytest.approx(600.0)
    assert balance.monthly[0].exports_total_t == pytest.approx(760.0)


# ---------------------------------------------------------------------------
# STATSER confrontation (§5)
# ---------------------------------------------------------------------------
def test_confrontation_compares_derived_against_declared() -> None:
    result = confront_statser([_month(_OCT, declared=180.0)], perimeter=PERIMETER_GEPEX)

    assert result is not None
    assert result.derived_t == pytest.approx(200.0)
    assert result.declared_t == pytest.approx(180.0)
    assert result.gap_t == pytest.approx(20.0)
    assert result.gap_pct == pytest.approx(20.0 / 180.0 * 100)
    assert result.perimeter == PERIMETER_GEPEX


def test_confrontation_uses_only_months_with_all_three_sources() -> None:
    """Its own window, unlike the balance — the three-source intersection is the
    only window where the comparison means anything."""
    result = confront_statser(
        [_month(_OCT, declared=180.0), _month(_NOV, declared=None)],
        perimeter=PERIMETER_GEPEX,
    )

    assert result is not None
    assert result.months == (_OCT,)
    assert result.window_from == _OCT and result.window_to == _OCT


def test_confrontation_is_none_when_statser_has_published_nothing() -> None:
    """Inventing a zero would publish a fake 100 % gap."""
    assert (
        confront_statser([_month(_OCT, declared=None)], perimeter=PERIMETER_GEPEX)
        is None
    )


def test_confrontation_gap_pct_is_undefined_when_nothing_was_declared() -> None:
    result = confront_statser([_month(_OCT, declared=0.0)], perimeter=PERIMETER_GEPEX)

    assert result is not None
    assert result.gap_pct is None


def test_confrontation_carries_a_narrower_window_than_the_balance() -> None:
    """The payload will hold both, so each block must state its own window — a
    client comparing across them would otherwise read a fake collapse (§6)."""
    series = [_month(_OCT, declared=180.0), _month(_NOV), _month(_DEC)]

    balance = compute_season_balance(_SEASON, series)
    confrontation = confront_statser(series, perimeter=PERIMETER_GEPEX)

    assert confrontation is not None
    assert len(confrontation.months) < len(balance.months)


# ---------------------------------------------------------------------------
# per-source YTD (§6)
# ---------------------------------------------------------------------------
def test_ytd_compares_the_same_campaign_months_a_year_earlier() -> None:
    current = {_OCT: 100.0, _NOV: 200.0}
    previous = {
        date(2024, 10, 1): 80.0,
        date(2024, 11, 1): 120.0,
        date(2025, 1, 1): 999.0,
    }

    block = ytd_block("exports", _SEASON, current, previous)

    assert block.current_t == pytest.approx(300.0)
    # 999 is excluded: January is not in this source's window this season.
    assert block.previous_t == pytest.approx(200.0)
    assert block.delta_pct == pytest.approx(50.0)
    assert block.previous_season == "2024-2025"


def test_ytd_never_compares_against_a_window_the_source_does_not_cover() -> None:
    """The rule §6 states outright. A source with 2 months published is compared
    against exactly those 2 months last season, not a full one."""
    block = ytd_block(
        "purchases",
        _SEASON,
        {_OCT: 100.0, _NOV: 100.0},
        {
            date(y, m, 1): 50.0
            for y, m in [(2024, 10), (2024, 11), (2024, 12), (2025, 1)]
        },
    )

    assert block.month_count == 2
    assert block.previous_t == pytest.approx(100.0)


def test_ytd_window_bounds_are_exposed_for_the_ui() -> None:
    block = ytd_block("exports", _SEASON, {_OCT: 1.0, _DEC: 1.0}, {})

    assert block.window_from == _OCT
    assert block.window_to == _DEC
    assert block.month_count == 2


def test_ytd_delta_is_undefined_against_a_zero_baseline() -> None:
    """Not +inf, not 0 — a growth rate off a zero base has no meaning."""
    block = ytd_block("grinding", _SEASON, {_OCT: 100.0}, {})

    assert block.previous_t == pytest.approx(0.0)
    assert block.delta_pct is None


def test_ytd_ignores_months_with_no_volume() -> None:
    block = ytd_block("exports", _SEASON, {_OCT: 100.0, _NOV: 0.0}, {})

    assert block.months == (_OCT,)
