"""Entitlement vocabulary + tier templates (config-as-code).

The finite, opaque catalogue of per-client entitlement keys and the named tier
bundles that expand into per-key grants at provisioning time.

Tiers mirror the commercial "Matrice de versioning par blocs" (Compass CC block,
July 2026): 7 packages across two orientations — COOP (physical-sale decision)
and EXPORT (forward-hedge decision) — plus a bespoke Origin Desk. WatchAI and
Formation are separate products, NOT modeled here.

Design (see docs/architecture/entitlement-and-tenancy-for-USERS.md):
- Keys are hierarchical ``read:<domain>:<name>`` strings, opaque to the runtime.
- Some features have a REDUCED variant (a sub-key): weather full vs weekly
  ``:summary``, hedge full vs ``:initiation``. A tier grants exactly one variant.
- The STORED source of truth is per-key rows in ``tenant_entitlement`` (DB);
  tiers are only a provisioning shortcut (``expand_tier``).
- ``TIER_MAX_SEATS`` carries the contracted dashboard-seat count per tier.
- This module is PURE (no DB/I-O) so it imports everywhere and unit-tests cheaply.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Mapping

# --- Sections (dashboard blocks) ---------------------------------------------
SECTION_SIGNAL = "read:section:signal"
SECTION_PODCAST = "read:section:podcast"
SECTION_MARKET = "read:section:market"  # technique gauges (MACD/RSI/ATR/%K)
SECTION_CHART = "read:section:chart"  # historique + supports/résistances
SECTION_NEWS = "read:section:news"  # press review + impact
SECTION_WEATHER = "read:section:weather"  # full weather intelligence
SECTION_WEATHER_SUMMARY = "read:section:weather:summary"  # "résumé hebdo" variant

# --- Chrome (the live band lives in the layout, not the page) ----------------
CHROME_TICKER = "read:chrome:ticker"

# --- Features (ensemble / premium panels) ------------------------------------
FEATURE_ENSEMBLE_DIAGNOSTICS = "read:feature:ensemble_diagnostics"
FEATURE_SPECIALIST_VOTES = "read:feature:specialist_votes"  # consensus X/14
FEATURE_MACRO_PANEL = "read:feature:macro_panel"  # FX/DXY + ENSO
FEATURE_POSITIONING = "read:feature:positioning"  # COT + stocks + grindings
FEATURE_FARMGATE = "read:feature:farmgate"  # prix garantis CIV/Ghana

# --- Decisions (product features; not all have a built endpoint yet) ---------
# Catalogue keys that reflect the commercial offer; the gate attaches when the
# feature ships. Present now so provisioning/CLI accept them.
DECISION_PHYSICAL_SALE = "read:decision:physical_sale"  # calc "vendre ou stocker"
DECISION_HEDGE = "read:decision:hedge"  # couverture forward (full)
DECISION_HEDGE_INITIATION = "read:decision:hedge:initiation"  # reduced intro

# --- Export series (mirror EXPORT_SERIES keys in export_service.py) -----------
# Not part of the packaged Compass CC matrix (that's the separate Enterprise API
# co-construct); kept in the catalogue because the endpoint exists and is gated.
_EXPORT_SERIES = ("ohlcv", "indicators", "fx", "cot_eu", "cot_us", "stocks", "weather")


def export_key(series: str) -> str:
    """Return the entitlement key gating a given export series."""
    return f"read:export:{series}"


EXPORT_KEYS: frozenset[str] = frozenset(export_key(s) for s in _EXPORT_SERIES)

# --- WatchAI (matrix block (2)) — origin physical flows ----------------------
# Côte d'Ivoire customs exports, exporter purchases, GEPEX grindings. Data landed
# by `poetry run watchai-sync`; served from `pl_origin_flow_monthly`.
WATCHAI_CAMPAIGN = "read:watchai:campaign_monthly"
# Reduced variant. NOTE the name is provisional: the "push" channel it was named
# for is no longer the plan — Coop Essentiel gets a reduced dashboard plus a
# button generating a WatchAI PDF. Rename to `:pdf` when that ships; keeping the
# spec'd name until then avoids churning grants for a design still open.
WATCHAI_CAMPAIGN_PUSH = "read:watchai:campaign_monthly:push"
WATCHAI_MARKET_VIEWS = "read:watchai:market_views"
WATCHAI_DESTINATIONS = "read:watchai:destinations"
WATCHAI_BENCHMARK = "read:watchai:benchmark"
# Per-exporter flows and the solde apparent. Gates anything that names an
# operator — including growth top-3 lists, which is why the campaign row carries
# none.
WATCHAI_NOMINATIVE = "read:watchai:nominative"

WATCHAI_KEYS: frozenset[str] = frozenset(
    {
        WATCHAI_CAMPAIGN,
        WATCHAI_CAMPAIGN_PUSH,
        WATCHAI_MARKET_VIEWS,
        WATCHAI_DESTINATIONS,
        WATCHAI_BENCHMARK,
        WATCHAI_NOMINATIVE,
    }
)

SECTION_KEYS: frozenset[str] = frozenset(
    {
        SECTION_SIGNAL,
        SECTION_PODCAST,
        SECTION_MARKET,
        SECTION_CHART,
        SECTION_NEWS,
        SECTION_WEATHER,
        SECTION_WEATHER_SUMMARY,
    }
)

CHROME_KEYS: frozenset[str] = frozenset({CHROME_TICKER})

FEATURE_KEYS: frozenset[str] = frozenset(
    {
        FEATURE_ENSEMBLE_DIAGNOSTICS,
        FEATURE_SPECIALIST_VOTES,
        FEATURE_MACRO_PANEL,
        FEATURE_POSITIONING,
        FEATURE_FARMGATE,
    }
)

DECISION_KEYS: frozenset[str] = frozenset(
    {DECISION_PHYSICAL_SALE, DECISION_HEDGE, DECISION_HEDGE_INITIATION}
)

# The complete, valid key catalogue. A key outside this set is a bug (typo in a
# grant, a stale gate) — the CLI and gates validate against it, fail-loud.
ALL_ENTITLEMENT_KEYS: frozenset[str] = (
    SECTION_KEYS
    | CHROME_KEYS
    | FEATURE_KEYS
    | DECISION_KEYS
    | EXPORT_KEYS
    | WATCHAI_KEYS
)

# Reduced-variant pairs (full → reduced). A tier holds at most one of each pair;
# endpoints that serve both accept either (any-of gate), and the frontend renders
# the reduced UI when only the reduced key is present.
VARIANT_PAIRS: Mapping[str, str] = MappingProxyType(
    {
        SECTION_WEATHER: SECTION_WEATHER_SUMMARY,
        DECISION_HEDGE: DECISION_HEDGE_INITIATION,
        WATCHAI_CAMPAIGN: WATCHAI_CAMPAIGN_PUSH,
    }
)


# --- Tier templates (Compass CC matrix, July 2026) ---------------------------
COOP_ESSENTIEL = "coop_essentiel"
COOP_PREMIUM = "coop_premium"
EXPORT_ESSENTIEL = "export_essentiel"
EXPORT_PREMIUM = "export_premium"
EXPORT_PRO = "export_pro"
SIGNAL_PLUS = "signal_plus"
ORIGIN_DESK = "origin_desk"

# Convenience bundles matching multi-key matrix rows.
_CONVICTION = frozenset({FEATURE_SPECIALIST_VOTES, FEATURE_ENSEMBLE_DIAGNOSTICS})
_TECHNIQUE_FX = frozenset({SECTION_MARKET, FEATURE_MACRO_PANEL})

# Coop Essentiel — "push only" (0 dashboard seats). Entitlements exist so push
# content can be generated from the same check; no login / no ticker.
_COOP_ESSENTIEL_KEYS: frozenset[str] = frozenset(
    {
        DECISION_PHYSICAL_SALE,
        DECISION_HEDGE_INITIATION,
        SECTION_SIGNAL,
        SECTION_PODCAST,
        FEATURE_FARMGATE,
        SECTION_WEATHER_SUMMARY,
    }
)

# Coop Premium — full dashboard.
_COOP_PREMIUM_KEYS: frozenset[str] = (
    frozenset(
        {
            DECISION_PHYSICAL_SALE,
            DECISION_HEDGE,
            SECTION_SIGNAL,
            SECTION_PODCAST,
            FEATURE_FARMGATE,
            SECTION_WEATHER,
            FEATURE_POSITIONING,
            SECTION_NEWS,
            SECTION_CHART,
            CHROME_TICKER,
        }
    )
    | _CONVICTION
    | _TECHNIQUE_FX
)

# Export Essentiel — lean: no positioning / press / history; weather summary.
_EXPORT_ESSENTIEL_KEYS: frozenset[str] = (
    frozenset(
        {
            DECISION_PHYSICAL_SALE,
            DECISION_HEDGE,
            SECTION_SIGNAL,
            SECTION_PODCAST,
            FEATURE_FARMGATE,
            SECTION_WEATHER_SUMMARY,
            CHROME_TICKER,
        }
    )
    | _CONVICTION
    | _TECHNIQUE_FX
)

# Export Premium — full dashboard (3 seats).
_EXPORT_PREMIUM_KEYS: frozenset[str] = _COOP_PREMIUM_KEYS

# Export Pro — same Compass CC surface as Premium, and the same block (2) surface
# too (both hold all five WatchAI rows). They differ on Formation and seats only.
_EXPORT_PRO_KEYS: frozenset[str] = _EXPORT_PREMIUM_KEYS

# Signal+ / Origin Desk — full dashboard, podcast is "option" (à la carte → not
# in the default template; grant separately).
_SIGNAL_PLUS_KEYS: frozenset[str] = _EXPORT_PREMIUM_KEYS - {SECTION_PODCAST}
_ORIGIN_DESK_KEYS: frozenset[str] = _EXPORT_PREMIUM_KEYS - {SECTION_PODCAST}

# --- WatchAI bundles per tier (matrix block (2)) -----------------------------
# Kept separate from the Compass CC bundles above and unioned in TIER_TEMPLATES,
# because the two blocks do NOT move together: `_EXPORT_PREMIUM_KEYS` aliases
# `_COOP_PREMIUM_KEYS` on block (1), but on block (2) Export Premium adds
# destinations + benchmark + nominative that Coop Premium does not buy. Composing
# per block is what keeps that alias honest instead of silently wrong.
_WATCHAI_COOP_ESSENTIEL: frozenset[str] = frozenset({WATCHAI_CAMPAIGN_PUSH})
_WATCHAI_COOP_PREMIUM: frozenset[str] = frozenset(
    {WATCHAI_CAMPAIGN, WATCHAI_MARKET_VIEWS}
)
_WATCHAI_EXPORT_ESSENTIEL: frozenset[str] = frozenset(
    {WATCHAI_CAMPAIGN_PUSH, WATCHAI_MARKET_VIEWS, WATCHAI_DESTINATIONS}
)
# "100 % débloqué dès Export Premium" — all five matrix rows.
_WATCHAI_EXPORT_PREMIUM: frozenset[str] = frozenset(
    {
        WATCHAI_CAMPAIGN,
        WATCHAI_MARKET_VIEWS,
        WATCHAI_DESTINATIONS,
        WATCHAI_BENCHMARK,
        WATCHAI_NOMINATIVE,
    }
)
# Signal+ / Origin Desk have no exporter identity, so benchmark is `n/a` in the
# matrix — meaningless rather than unsold. The endpoint returns "not applicable",
# never 403; the key is simply absent.
_WATCHAI_SIGNAL_PLUS: frozenset[str] = _WATCHAI_EXPORT_PREMIUM - {WATCHAI_BENCHMARK}
# Origin Desk: nominative is `s/ CdC` (à la carte) → not in the default template.
_WATCHAI_ORIGIN_DESK: frozenset[str] = _WATCHAI_SIGNAL_PLUS - {WATCHAI_NOMINATIVE}

TIER_TEMPLATES: Mapping[str, frozenset[str]] = MappingProxyType(
    {
        COOP_ESSENTIEL: _COOP_ESSENTIEL_KEYS | _WATCHAI_COOP_ESSENTIEL,
        COOP_PREMIUM: _COOP_PREMIUM_KEYS | _WATCHAI_COOP_PREMIUM,
        EXPORT_ESSENTIEL: _EXPORT_ESSENTIEL_KEYS | _WATCHAI_EXPORT_ESSENTIEL,
        EXPORT_PREMIUM: _EXPORT_PREMIUM_KEYS | _WATCHAI_EXPORT_PREMIUM,
        EXPORT_PRO: _EXPORT_PRO_KEYS | _WATCHAI_EXPORT_PREMIUM,
        SIGNAL_PLUS: _SIGNAL_PLUS_KEYS | _WATCHAI_SIGNAL_PLUS,
        ORIGIN_DESK: _ORIGIN_DESK_KEYS | _WATCHAI_ORIGIN_DESK,
    }
)

# Contracted dashboard seats per tier (matrix "Accès dashboard" row). Coop
# Essentiel = 1 (minimal dashboard: guaranteed-price reference only). Stored on
# the account; NOT hard-enforced (link-seat warns past the cap — see docs
# decision "Store max_seats, don't hard-enforce").
TIER_MAX_SEATS: Mapping[str, int] = MappingProxyType(
    {
        COOP_ESSENTIEL: 1,
        COOP_PREMIUM: 2,
        EXPORT_ESSENTIEL: 2,
        EXPORT_PREMIUM: 3,
        EXPORT_PRO: 4,
        SIGNAL_PLUS: 4,
        ORIGIN_DESK: 4,
    }
)

VALID_TIERS: frozenset[str] = frozenset(TIER_TEMPLATES.keys())

# --- Internal / full-access marker -------------------------------------------
# NOT a commercial tier. It resolves to the COMPLETE catalogue at READ-TIME
# (see app/core/tenancy.py::resolve_principal), so a full-access account always
# sees every feature — including keys added AFTER it was provisioned, with no
# re-backfill. Used to grandfather the existing user base into "the whole app"
# before enforcement is flipped on (rollout §10), and for staff.
INTERNAL = "internal"
INTERNAL_MAX_SEATS = 9999  # effectively unlimited seats for staff/full accounts

# Tiers the provisioning CLI accepts (the 7 commercial ones + internal).
PROVISIONABLE_TIERS: frozenset[str] = VALID_TIERS | {INTERNAL}


def expand_tier(tier: str) -> frozenset[str]:
    """Return the set of entitlement keys granted by a tier (fail-loud).

    ``internal`` expands to the full catalogue (materialised for consistency;
    the runtime also short-circuits it — see resolve_principal).
    """
    if tier == INTERNAL:
        return ALL_ENTITLEMENT_KEYS
    try:
        return TIER_TEMPLATES[tier]
    except KeyError as exc:
        raise ValueError(
            f"Unknown tier {tier!r}. Valid tiers: {sorted(PROVISIONABLE_TIERS)}"
        ) from exc


def max_seats_for(tier: str) -> int:
    """Return the contracted dashboard-seat cap for a tier (fail-loud)."""
    if tier == INTERNAL:
        return INTERNAL_MAX_SEATS
    try:
        return TIER_MAX_SEATS[tier]
    except KeyError as exc:
        raise ValueError(
            f"Unknown tier {tier!r}. Valid tiers: {sorted(PROVISIONABLE_TIERS)}"
        ) from exc


def is_valid_key(key: str) -> bool:
    """Return True iff ``key`` is a known entitlement key."""
    return key in ALL_ENTITLEMENT_KEYS
