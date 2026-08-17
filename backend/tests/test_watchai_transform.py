"""Unit tests for the WatchAI transform — pure derivation, no database.

These cover the two failure classes the integration doc calls the highest- and
second-highest-probability visible defects: product taxonomy divergence (§2) and
unit mixing (§1). Both are silent in production, so they are tested here rather
than being left to the end-to-end reconciliation.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from scripts.watchai_sync import transform
from scripts.watchai_sync.acquire import _classify_working_tree
from scripts.watchai_sync.errors import (
    InvalidTonnageError,
    UnknownProductError,
    UnmappedEntityError,
)


# ---------------------------------------------------------------------------
# season (business-rules §3)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (date(2025, 10, 1), "2025-2026"),  # first day of a season
        (date(2025, 12, 31), "2025-2026"),
        (date(2026, 1, 1), "2025-2026"),  # calendar year rolls, season does not
        (date(2026, 9, 30), "2025-2026"),  # last day of a season
        (date(2026, 10, 1), "2026-2027"),  # boundary
    ],
)
def test_derive_season_boundaries(value: date, expected: str) -> None:
    assert transform.derive_season(value) == expected


def test_season_label_fits_the_column() -> None:
    """VARCHAR(9) — "2025-2026" is exactly 9 characters."""
    assert len(transform.derive_season(date(2026, 7, 1))) == 9


# ---------------------------------------------------------------------------
# product taxonomy (business-rules §2) — the highest-risk area
# ---------------------------------------------------------------------------
def test_produit_simple_wins_over_postar() -> None:
    """The POSTAR fallback fires only when PRODUIT SIMPLE is absent (§2.2).

    32 rows in the current extract carry POSTAR 1801 (fèves) with
    PRODUIT SIMPLE = HORS GRADE. The label must win, or those rows move bucket.
    """
    assert transform.resolve_product("HORS GRADE", "1801001100") == "HORS_GRADE"


@pytest.mark.parametrize("label", ["MASSE", "PATE", "LIQUEUR"])
def test_liqueur_and_pate_collapse_into_masse(label: str) -> None:
    """The §2.2 latent bug, defused at ingestion.

    In WatchAI a null PRODUIT SIMPLE with POSTAR 1803 becomes "LIQUEUR", which
    then matches neither FEVES_PRODUITS nor TRANSFO_PRODUITS and disappears from
    the transformation balance entirely. Collapsing to MASSE at ingestion means
    no query can reproduce that hole.
    """
    assert transform.resolve_product(label, "1803100000") == "MASSE"


def test_postar_fallback_when_produit_simple_missing() -> None:
    assert transform.resolve_product(None, "1804200000") == "BEURRE"
    assert transform.resolve_product("", "1806320000") == "CHOCOLAT"
    assert transform.resolve_product(float("nan"), "1803100000") == "MASSE"


@pytest.mark.parametrize(
    ("code", "prefix", "product"),
    [
        ("1804200000", "1804", "BEURRE"),  # bare digits — the current shape
        ("18-04.20", "1804", "BEURRE"),  # formatted: v1 sliced "18-0" and missed
        ("  1805  ", "1805", "POUDRE"),
        ("POSTAR1806", "1806", "CHOCOLAT"),
    ],
)
def test_postar_prefix_strips_non_digits_before_slicing(
    code: str, prefix: str, product: str
) -> None:
    """business-rules §2.1: v2 does regexp_replace('[^0-9]','') then substr(1,4);
    v1 sliced the raw string. Identical on current data — all 172 712 codes are
    10 bare digits — but a formatted value must resolve rather than fall through
    to the fail-loud path."""
    assert transform.postar_prefix(code) == prefix
    assert transform.resolve_product(None, code) == product


def test_unknown_postar_prefix_fails_loud() -> None:
    """WatchAI returns FEVES here. Beans are ~85% of volume, so that default is
    both invisible and material — we refuse instead."""
    with pytest.raises(UnknownProductError, match="9999"):
        transform.resolve_product(None, "9999000000")


def test_unknown_produit_simple_fails_loud() -> None:
    with pytest.raises(UnknownProductError, match="TOURTEAU"):
        transform.resolve_product("TOURTEAU", "1801001100")


def test_bean_equivalent_set_excludes_transformed_products() -> None:
    """§2 wins over the §9 golden line, which counts HORS GRADE as transformed."""
    from scripts.watchai_sync.config import BEAN_EQUIVALENT_CODES

    assert BEAN_EQUIVALENT_CODES == {"FEVES", "HORS_GRADE"}
    assert "MASSE" not in BEAN_EQUIVALENT_CODES


# ---------------------------------------------------------------------------
# name normalization
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  cargill  ", "CARGILL"),
        ("Barry\tCallebaut", "BARRY CALLEBAUT"),
        ("TAN  IVOIRE", "TAN IVOIRE"),
        (None, ""),
        (float("nan"), ""),
    ],
)
def test_normalize_name(raw: object, expected: str) -> None:
    assert transform.normalize_name(raw) == expected


# ---------------------------------------------------------------------------
# fixtures for frame-level transforms
# ---------------------------------------------------------------------------
def _declarations(**overrides) -> pd.DataFrame:
    base = {
        "DATE_SIMPLE": [pd.Timestamp("2026-03-15"), pd.Timestamp("2025-11-02")],
        "EXPORTATEUR_SIMPLE": ["CARGILL", "BARRY"],
        "DESTINATION_SIMPLE": ["PAYS-BAS", "BELGIQUE"],
        "PORT": ["ABIDJAN", "SAN PEDRO"],
        "POSTAR": ["1801001100", "1803100000"],
        "PRODUIT SIMPLE": ["FEVES", "MASSE"],
        "PDS_NET": [100_000, 50_000],
        "VALCAF": [200_000_000.0, None],
        "DROITS_TAXES": [20_000_000.0, None],
    }
    base.update(overrides)
    return pd.DataFrame(base)


def _purchases(**overrides) -> pd.DataFrame:
    base = {
        "EXPORTATEUR_SIMPLE": ["CARGILL", "BARRY"],
        "DATE": [pd.Timestamp("2026-03-01"), pd.Timestamp("2025-11-01")],
        "POIDS_NET_KG": [1_000_000.0, 2_000_000.0],
    }
    base.update(overrides)
    return pd.DataFrame(base)


def _grindings(**overrides) -> pd.DataFrame:
    base = {
        "DATE": [pd.Timestamp("2026-03-01"), pd.Timestamp("2026-02-01")],
        "TONS_BROYES": [55_000.0, 53_000.0],
    }
    base.update(overrides)
    return pd.DataFrame(base)


_MAPPINGS = {
    "exporter": frozenset({"CARGILL", "BARRY", "RETIRED CO"}),
    "destination": frozenset({"PAYS-BAS", "BELGIQUE"}),
}


def _transform(**kwargs) -> transform.TransformedBatch:
    return transform.transform(
        declarations=kwargs.get("declarations", _declarations()),
        purchases=kwargs.get("purchases", _purchases()),
        grindings=kwargs.get("grindings", _grindings()),
        mapping_names=kwargs.get("mapping_names", _MAPPINGS),
    )


# ---------------------------------------------------------------------------
# units (business-rules §1) — the second-highest-risk area
# ---------------------------------------------------------------------------
def test_declaration_weights_stay_in_kilograms() -> None:
    """The kg→tonne conversion belongs to the cube and happens exactly once."""
    batch = _transform()
    assert list(batch.declarations["net_weight_kg"]) == [100_000, 50_000]


def test_purchase_weights_stay_in_kilograms() -> None:
    batch = _transform()
    assert set(batch.purchases["net_weight_kg"]) == {1_000_000.0, 2_000_000.0}


def test_grindings_are_not_divided() -> None:
    """TONS_BROYES is the one weight column already in tonnes (webapp_tax.py:1919).

    Dividing it by 1000 would understate grinding by three orders of magnitude
    and silently wreck every transformation ratio built on it.
    """
    batch = _transform()
    assert sorted(batch.grindings["tons_ground"]) == [53_000.0, 55_000.0]


# ---------------------------------------------------------------------------
# grain — purchases collapse onto one row per natural key
# ---------------------------------------------------------------------------
def test_purchases_sum_exporter_aliases_sharing_a_month() -> None:
    """183 (exporter, month) keys in the real extract have 2-3 source rows because
    distinct raw customs names collapse onto one EXPORTATEUR_SIMPLE. Summing here
    is what lets the table carry a real UNIQUE constraint."""
    purchases = pd.DataFrame(
        {
            "EXPORTATEUR_SIMPLE": ["CARGILL", "CARGILL", "BARRY"],
            "DATE": [
                pd.Timestamp("2026-03-01"),
                pd.Timestamp("2026-03-01"),
                pd.Timestamp("2026-03-01"),
            ],
            "POIDS_NET_KG": [1_000.0, 2_500.0, 400.0],
        }
    )
    batch = _transform(purchases=purchases)

    assert len(batch.purchases) == 2
    cargill = batch.purchases[batch.purchases["exporter_name"] == "CARGILL"]
    assert cargill["net_weight_kg"].tolist() == [3_500.0]
    # And the natural key really is unique afterwards.
    assert not batch.purchases.duplicated(["period_date", "exporter_name"]).any()


def test_duplicate_grinding_month_fails_loud() -> None:
    """The grinding series feeds cumulative ratios; two rows for one month would
    double-count with no visible symptom."""
    grindings = _grindings(
        DATE=[pd.Timestamp("2026-03-01"), pd.Timestamp("2026-03-01")],
        TONS_BROYES=[55_000.0, 1.0],
    )
    with pytest.raises(InvalidTonnageError, match="duplicate month"):
        _transform(grindings=grindings)


# ---------------------------------------------------------------------------
# fail-loud guards
# ---------------------------------------------------------------------------
def test_negative_declaration_weight_fails_loud() -> None:
    with pytest.raises(InvalidTonnageError, match="PDS_NET"):
        _transform(declarations=_declarations(PDS_NET=[100_000, -5]))


def test_negative_grinding_fails_loud() -> None:
    with pytest.raises(InvalidTonnageError, match="TONS_BROYES"):
        _transform(grindings=_grindings(TONS_BROYES=[55_000.0, -1.0]))


def test_zero_weight_is_allowed_but_counted() -> None:
    """Two rows in the real extract have PDS_NET = 0. A zero is a degenerate
    declaration, not a broken one — it is reported, not fatal."""
    batch = _transform(declarations=_declarations(PDS_NET=[0, 50_000]))
    assert batch.quality_report["declarations_zero_weight"] == 1


def test_blank_exporter_fails_loud() -> None:
    """A blank name would collapse unrelated books into one entity."""
    with pytest.raises(UnmappedEntityError, match="EXPORTATEUR_SIMPLE"):
        _transform(declarations=_declarations(EXPORTATEUR_SIMPLE=["CARGILL", "   "]))


def test_blank_destination_is_tolerated_and_counted() -> None:
    """destination_entity_id is nullable — a missing destination loses detail but
    not tonnage, so it must not drop the row."""
    batch = _transform(declarations=_declarations(DESTINATION_SIMPLE=["PAYS-BAS", ""]))
    assert batch.quality_report["declarations_blank_destination"] == 1
    assert len(batch.declarations) == 2


# ---------------------------------------------------------------------------
# entities
# ---------------------------------------------------------------------------
def test_entities_are_the_union_of_data_and_mapping_file() -> None:
    """47 exporters and 8 destinations in the real extract are absent from
    Entity_Mappings.xlsx, and the file also holds names no longer in the data.
    Seeding from the union means neither side can fragment a client's flows."""
    declarations = _declarations(EXPORTATEUR_SIMPLE=["CARGILL", "NEWCO"])
    batch = _transform(declarations=declarations)

    exporters = {e.source_name for e in batch.entities if e.entity_type == "exporter"}
    assert "NEWCO" in exporters  # in the data, not in the mapping file
    assert "RETIRED CO" in exporters  # in the mapping file, not in the data


def test_names_absent_from_mappings_are_flagged_not_fatal() -> None:
    batch = _transform(
        declarations=_declarations(EXPORTATEUR_SIMPLE=["CARGILL", "NEWCO"])
    )

    newco = next(e for e in batch.entities if e.source_name == "NEWCO")
    assert newco.in_entity_mappings is False
    assert batch.quality_report["entities_absent_from_mappings"] == {
        "exporters": ["NEWCO"],
        "destinations": [],
    }


def test_purchase_only_exporters_are_created() -> None:
    """~20 cooperatives sell but never export, so the exporter universe is the
    union of both observation tables, not just the declarations."""
    purchases = _purchases(EXPORTATEUR_SIMPLE=["COOP ANONKLON", "BARRY"])
    batch = _transform(purchases=purchases)

    exporters = {e.source_name for e in batch.entities if e.entity_type == "exporter"}
    assert "COOP ANONKLON" in exporters


def test_gepex_membership_is_seeded_from_the_canonical_eleven() -> None:
    batch = _transform()
    by_name = {e.source_name: e for e in batch.entities if e.entity_type == "exporter"}

    assert by_name["CARGILL"].is_gepex_member is True
    assert by_name["BARRY"].is_gepex_member is True
    assert by_name["RETIRED CO"].is_gepex_member is False


def test_destinations_are_never_gepex_members() -> None:
    batch = _transform()
    destinations = [e for e in batch.entities if e.entity_type == "destination"]

    assert destinations
    assert all(e.is_gepex_member is False for e in destinations)


# ---------------------------------------------------------------------------
# batch metadata
# ---------------------------------------------------------------------------
def test_source_max_periods_are_reported_per_source() -> None:
    """Printed before writing (integration doc §4 step 1). The three sources stop
    at different months — on 11336ef: exports 2026-07, achats 2026-07, broyage
    2026-04 — so a single stamp would hide which one is lagging."""
    batch = _transform()

    assert batch.source_max_periods == {
        "declarations": date(2026, 3, 15),
        "purchases": date(2026, 3, 1),
        "grindings": date(2026, 3, 1),
    }


def test_data_as_of_is_the_newest_period_across_all_three_sources() -> None:
    """The three sources publish on different lags; the stamp is the max, so the
    UI never claims to be older than the freshest thing it holds."""
    batch = _transform()
    assert batch.data_as_of == date(2026, 3, 15)


def test_row_counts_reflect_post_transform_shape() -> None:
    """Purchases are counted after the alias collapse, so the count matches what
    actually lands in the table."""
    purchases = pd.DataFrame(
        {
            "EXPORTATEUR_SIMPLE": ["CARGILL", "CARGILL"],
            "DATE": [pd.Timestamp("2026-03-01"), pd.Timestamp("2026-03-01")],
            "POIDS_NET_KG": [1.0, 2.0],
        }
    )
    batch = _transform(purchases=purchases)
    assert batch.row_counts["purchases"] == 1


def test_missing_money_columns_are_counted() -> None:
    """131 296 of 170 453 real rows carry no VALCAF at all (every row before
    2024). That is a property of the source, so it is reported, never fatal."""
    batch = _transform()
    assert batch.quality_report["declarations_missing_valcaf"] == 1
    assert batch.quality_report["declarations_missing_duties"] == 1


def test_sentinel_valcaf_is_counted() -> None:
    """VALCAF = 1 FCFA against a six-figure tonnage is a sentinel, not a price;
    any CAF-per-tonne built on those rows is meaningless."""
    batch = _transform(declarations=_declarations(VALCAF=[1.0, 200_000_000.0]))
    assert batch.quality_report["declarations_sentinel_valcaf"] == 1


# ---------------------------------------------------------------------------
# dirty working tree classification (integration doc §4 step 1)
# ---------------------------------------------------------------------------
def test_modified_tracked_file_blocks_the_load() -> None:
    """A batch records a commit SHA; with local modifications that SHA is a lie."""
    blocking, untracked = _classify_working_tree(" M Webapp/webapp_tax.py\n")
    assert blocking and not untracked


def test_untracked_file_under_master_data_blocks_the_load() -> None:
    """It could shadow or accompany the very files we are about to read."""
    blocking, untracked = _classify_working_tree(
        "?? Master_Data/Db_Master_Tax_v2.parquet\n"
    )
    assert blocking and not untracked


def test_untracked_file_elsewhere_is_noted_not_blocking() -> None:
    """A stray .env.example cannot change what this job reads — the real
    checkout has exactly that today, and it must not block ingestion."""
    blocking, untracked = _classify_working_tree("?? .env.example\n")
    assert not blocking
    assert untracked == [".env.example"]


def test_renamed_file_is_classified_on_its_destination() -> None:
    blocking, _ = _classify_working_tree("R  old.py -> Master_Data/new.py\n")
    assert blocking and "Master_Data/new.py" in blocking[0]


def test_clean_tree_produces_nothing() -> None:
    assert _classify_working_tree("") == ([], [])
