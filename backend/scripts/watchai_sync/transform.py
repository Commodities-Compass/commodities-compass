"""Pure derivation: season, product taxonomy, entity resolution, units.

This is the port of the derivation block inside WatchAI's ``load_data_raw``
(webapp_tax.py:1729-1802) minus its I/O and its ``st.cache_data`` wrapper — the
densest concentration of portable logic in that 6 610-line file.

No database, no filesystem, no network. Everything here is a function of the
DataFrames handed in, which is what makes the reconciliation test meaningful.

Two behavioural departures from the original, both deliberate:

* **No silent defaults.** WatchAI's product resolution ends in ``else: FEVES``
  in two separate places. Beans are ~85% of volume, so a wrong default is
  invisible and material. Here an unresolvable product raises.
* **Current mappings applied over all history.** WatchAI applies the mapping in
  force at integration time and never revisits it, so a 2023 row keeps its 2023
  spelling forever. We re-canonicalize the whole history on every load, which is
  a quality gain and also a reason our older-season nominative totals may
  legitimately differ from a WatchAI screen (business-rules §12.3).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date

import pandas as pd
from typing import cast

from scripts.watchai_sync import config
from scripts.watchai_sync.errors import (
    InvalidTonnageError,
    UnknownProductError,
    UnmappedEntityError,
)

logger = logging.getLogger(__name__)

EXPORTER = "exporter"
DESTINATION = "destination"


def _column(frame: pd.DataFrame, name: str) -> pd.Series:
    """Fetch a column as a Series.

    ``frame[name]`` is typed as ``Series | DataFrame`` by the pandas stubs, which
    makes every downstream call ambiguous. One narrowing point beats a cast at
    each use site.
    """
    return pd.Series(frame[name])


@dataclass(frozen=True)
class EntityRecord:
    """One canonical exporter or destination, ready for ``ref_origin_entity``."""

    entity_type: str
    source_name: str
    canonical_name: str
    is_gepex_member: bool
    in_entity_mappings: bool
    country_code: str | None = None

    @property
    def key(self) -> tuple[str, str]:
        return (self.entity_type, self.source_name)


@dataclass(frozen=True)
class TransformedBatch:
    """Everything the writer needs, already derived and validated."""

    entities: tuple[EntityRecord, ...]
    declarations: pd.DataFrame
    purchases: pd.DataFrame
    grindings: pd.DataFrame
    data_as_of: date
    row_counts: dict[str, int]
    # Newest period *per source*. The three publications stop at different
    # months and the CLI prints this before writing (integration doc §4 step 1):
    # a stale checkout is the normal case, not the exception, so freshness must
    # be visible at load time rather than discovered on the dashboard.
    source_max_periods: dict[str, date] = field(default_factory=dict)
    quality_report: dict[str, object] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# scalar derivations
# ---------------------------------------------------------------------------
def derive_season(value: date) -> str:
    """Cocoa season label for a date — October → September (business-rules §3)."""
    if value.month >= config.SEASON_START_MONTH:
        return f"{value.year}-{value.year + 1}"
    return f"{value.year - 1}-{value.year}"


def normalize_name(raw: object) -> str:
    """Our normalization layer on top of WatchAI's ``*_SIMPLE``.

    Trim, collapse internal whitespace, uppercase. Deliberately conservative:
    anything cleverer (fuzzy matching, punctuation stripping) risks merging two
    genuinely different exporters, which on the Benchmark row means showing a
    client a competitor's book.
    """
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return ""
    return " ".join(str(raw).split()).upper()


def resolve_product(produit_simple: object, postar: object) -> str:
    """Resolve one row to the canonical taxonomy, or raise.

    ``PRODUIT SIMPLE`` wins when present; the POSTAR prefix is a fallback only
    (webapp_tax.py:1766-1772). In the current extract the fallback never fires —
    ``PRODUIT SIMPLE`` is populated on all 170 453 rows — but it is implemented
    because a future month may not be so tidy, and the failure mode it guards
    against is silent.
    """
    label = normalize_name(produit_simple)
    if label:
        resolved = config.PRODUCT_SIMPLE_MAP.get(label)
        if resolved is None:
            raise UnknownProductError(
                f"unmappable PRODUIT SIMPLE {label!r} (POSTAR {postar!r}). "
                "Add it to config.PRODUCT_SIMPLE_MAP after confirming which "
                "canonical product it is — do not let it default."
            )
        return resolved

    code = normalize_name(postar)
    prefix = postar_prefix(code)
    resolved = config.POSTAR_PREFIX_MAP.get(prefix)
    if resolved is None:
        raise UnknownProductError(
            f"PRODUIT SIMPLE is empty and POSTAR prefix {prefix!r} "
            f"(full code {code!r}) is unknown. WatchAI would silently call this "
            "FEVES; we refuse."
        )
    return resolved


def postar_prefix(code: str) -> str:
    """First 4 digits of a POSTAR customs code, non-digits stripped first.

    v2 does ``substr(regexp_replace(POSTAR, '[^0-9]', '', 'g'), 1, 4)``
    (business-rules §2.1); v1 sliced the raw string. Identical on current data —
    all 172 712 codes are 10 bare digits — but a formatted value like
    ``18-01.00`` would slice to ``18-0`` and land on the fail-loud path instead
    of resolving to FEVES.
    """
    digits = "".join(char for char in code if char.isdigit())
    return digits[: config.POSTAR_PREFIX_LENGTH]


# ---------------------------------------------------------------------------
# batch transform
# ---------------------------------------------------------------------------
def transform(
    declarations: pd.DataFrame,
    purchases: pd.DataFrame,
    grindings: pd.DataFrame,
    mapping_names: dict[str, frozenset[str]],
) -> TransformedBatch:
    """Derive a full batch from the three raw masters."""
    quality: dict[str, object] = {}

    declarations_out = _transform_declarations(declarations, quality)
    purchases_out = _transform_purchases(purchases)
    grindings_out = _transform_grindings(grindings)

    entities = _build_entities(declarations_out, purchases_out, mapping_names, quality)

    source_max_periods: dict[str, date] = {
        "declarations": _column(declarations_out, "declaration_date").max(),
        "purchases": _column(purchases_out, "period_date").max(),
        "grindings": _column(grindings_out, "period_date").max(),
    }
    # The newest period any source covers — what the UI stamps as
    # "Données au <mois>" (decision #15). Deliberately the max, not an
    # intersection: the three sources publish on different lags, and STATSER
    # grinding structurally trails the other two by 2-3 months.
    data_as_of: date = max(source_max_periods.values())

    row_counts = {
        "declarations": int(len(declarations_out)),
        "purchases": int(len(purchases_out)),
        "grindings": int(len(grindings_out)),
        "entities": len(entities),
    }
    logger.info(
        "transformed %s; data_as_of=%s; %d entities",
        row_counts,
        data_as_of.isoformat(),
        len(entities),
    )
    return TransformedBatch(
        entities=entities,
        declarations=declarations_out,
        purchases=purchases_out,
        grindings=grindings_out,
        data_as_of=data_as_of,
        row_counts=row_counts,
        source_max_periods=source_max_periods,
        quality_report=quality,
    )


def _transform_declarations(
    raw: pd.DataFrame, quality: dict[str, object]
) -> pd.DataFrame:
    """Line-level exports → the reduced 9-column projection.

    Weight stays in **kg** here. The kg→tonne conversion belongs to the cube and
    happens exactly once (business-rules §1: convert at the edge, never inside a
    formula).
    """
    frame = pd.DataFrame(
        {
            "declaration_date": pd.to_datetime(raw["DATE_SIMPLE"]).dt.date,
            "exporter_name": raw["EXPORTATEUR_SIMPLE"].map(normalize_name),
            "destination_name": raw["DESTINATION_SIMPLE"].map(normalize_name),
            "port": raw["PORT"].map(normalize_name),
            "postar": raw["POSTAR"].map(lambda v: str(v).strip()),
            "net_weight_kg": raw["PDS_NET"],
            "valcaf": raw["VALCAF"],
            "duties_taxes": raw["DROITS_TAXES"],
        }
    )
    frame["product_code"] = [
        resolve_product(produit, postar)
        for produit, postar in zip(raw["PRODUIT SIMPLE"], raw["POSTAR"], strict=True)
    ]
    frame["season"] = frame["declaration_date"].map(derive_season)

    _assert_non_negative(_column(frame, "net_weight_kg"), "PDS_NET", "declarations")
    _require_names(_column(frame, "exporter_name"), "EXPORTATEUR_SIMPLE")

    # A blank destination is tolerated (the column is nullable downstream) but a
    # blank exporter is not — it would merge unrelated books into one entity.
    blank_destinations = int((_column(frame, "destination_name") == "").sum())
    if blank_destinations:
        logger.warning("%d declaration(s) have no destination", blank_destinations)

    quality.update(_declaration_quality(raw, blank_destinations))
    return frame


def _declaration_quality(
    raw: pd.DataFrame, blank_destinations: int
) -> dict[str, object]:
    """Count the source's known imperfections. Reported, never fatal.

    None of these can be fixed here and all of them are permanently true of the
    upstream extract, so raising would mean the job never runs. Recording them on
    the batch means a number that looks odd later has a documented cause.
    """
    valcaf = _column(raw, "VALCAF")
    duties = _column(raw, "DROITS_TAXES")
    report: dict[str, object] = {
        # On `main` these were NULL on 131 296 of 170 453 rows. On `refonte-da-v2`
        # they are NULL on **zero** rows — the same absent values are now encoded
        # as 0. Sums are unaffected (0 adds nothing, NULL was skipped), which is
        # why the golden totals reproduce identically on both, but it moves the
        # signal: `sentinel` below is the load-bearing counter now, not `missing`.
        "declarations_missing_valcaf": int(valcaf.isna().sum()),
        "declarations_missing_duties": int(duties.isna().sum()),
        # No real money data: 0 (the ex-NULLs) or a literal 1 FCFA against a
        # six-figure tonnage. Any CAF-per-tonne built on these rows is
        # meaningless. 131 573 rows on `11336ef`, essentially everything before
        # 2024 — money data starts with the 2023-2024 season.
        "declarations_sentinel_valcaf": int((valcaf.notna() & (valcaf <= 1)).sum()),
        "declarations_zero_weight": int((_column(raw, "PDS_NET") == 0).sum()),
        "declarations_blank_destination": blank_destinations,
    }

    # business-rules §1 asks that the precomputed TAX % / CAF-per-kg columns be
    # checked against a recompute. They disagree structurally — on `11336ef`,
    # CAF/kg matches on 99,46 % of comparable rows and TAX % on only 70,03 %
    # (12 119 divergences) — so a hard assert would abort every run. Counters
    # instead. WatchAI ignores both columns and recomputes; so do we, and the
    # reduced projection does not ingest them at all.
    if "CAF/kg" in raw.columns:
        report["declarations_caf_per_kg_mismatch"] = _mismatch_count(
            _column(raw, "CAF/kg"),
            valcaf / _column(raw, "PDS_NET").where(_column(raw, "PDS_NET") > 0),
        )
    if "TAX %" in raw.columns:
        report["declarations_tax_ratio_mismatch"] = _mismatch_count(
            _column(raw, "TAX %"),
            duties / valcaf.where(valcaf > 0),
        )
    return report


def _mismatch_count(published: pd.Series, recomputed: pd.Series) -> int:
    """Rows where a precomputed source column disagrees with a recompute by >0.01%."""
    comparable = published.notna() & recomputed.notna() & (published != 0)
    if not comparable.any():
        return 0
    delta = pd.Series(recomputed[comparable]) - pd.Series(published[comparable])
    relative = delta.abs() / pd.Series(published[comparable]).abs()
    return int((relative > 1e-4).sum())


def _transform_purchases(raw: pd.DataFrame) -> pd.DataFrame:
    """Monthly purchases per exporter, summed onto one row per natural key.

    The source ships up to 3 rows for the same (exporter, month) because distinct
    raw customs names collapse onto one ``EXPORTATEUR_SIMPLE`` — 192 such keys on
    ``11336ef``. Summing here rather than at query time is what lets the table
    carry a real UNIQUE constraint instead of hoping consumers aggregate.

    ``SAISON`` is deliberately **not** read from the source. business-rules §3
    flags the asymmetry: the v2 `tax` view derives the season in SQL while
    `achats` takes the column verbatim from the workbook. Deriving both means a
    source-side labelling error cannot desynchronize the two series.
    """
    frame = pd.DataFrame(
        {
            "period_date": pd.to_datetime(raw["DATE"]).dt.date,
            "exporter_name": raw["EXPORTATEUR_SIMPLE"].map(normalize_name),
            "net_weight_kg": raw["POIDS_NET_KG"].astype(float),
        }
    )
    _assert_non_negative(_column(frame, "net_weight_kg"), "POIDS_NET_KG", "purchases")
    _require_names(_column(frame, "exporter_name"), "EXPORTATEUR_SIMPLE (achats)")

    # Cast the aggregation before sorting: with as_index=False the runtime value
    # is a DataFrame, but the stub types the single-column selection as a Series
    # and then refuses sort_values(by=[...]).
    grouped = cast(
        pd.DataFrame,
        frame.groupby(["period_date", "exporter_name"], as_index=False)[
            "net_weight_kg"
        ].sum(),
    )
    collapsed = grouped.sort_values(["period_date", "exporter_name"]).reset_index(
        drop=True
    )
    if len(collapsed) < len(frame):
        logger.info(
            "purchases: %d source rows collapsed to %d (exporter aliases sharing a month)",
            len(frame),
            len(collapsed),
        )
    collapsed["season"] = collapsed["period_date"].map(derive_season)
    return collapsed


def _transform_grindings(raw: pd.DataFrame) -> pd.DataFrame:
    """GEPEX-aggregate grindings. Already in tonnes — no division.

    ``TONS_BROYES`` is the one weight column in the whole source that is not in
    kg (business-rules §1, webapp_tax.py:1919). Dividing it by 1000 here would
    understate grinding by three orders of magnitude and quietly wreck every
    transformation ratio.
    """
    frame = pd.DataFrame(
        {
            "period_date": pd.to_datetime(raw["DATE"]).dt.date,
            "tons_ground": raw["TONS_BROYES"].astype(float),
        }
    )
    _assert_non_negative(_column(frame, "tons_ground"), "TONS_BROYES", "grindings")
    frame["season"] = frame["period_date"].map(derive_season)

    duplicates = int(_column(frame, "period_date").duplicated().sum())
    if duplicates:
        raise InvalidTonnageError(
            f"grindings has {duplicates} duplicate month(s); this series must be "
            "one row per month or every cumulative ratio built on it is wrong"
        )
    return frame.sort_values("period_date").reset_index(drop=True)


# ---------------------------------------------------------------------------
# entities
# ---------------------------------------------------------------------------
def _build_entities(
    declarations: pd.DataFrame,
    purchases: pd.DataFrame,
    mapping_names: dict[str, frozenset[str]],
    quality: dict[str, object],
) -> tuple[EntityRecord, ...]:
    """Union of every name seen in the data and in the mapping sheets.

    Both directions matter. The data contains names the mapping file has never
    heard of (47 exporters, 8 destinations), and the mapping file contains names
    that no longer appear in the data. Seeding from the union means a client's
    flows are never fragmented by a name we declined to create, and the
    ``in_entity_mappings`` flag records which side each name came from.

    Purchases contribute ~20 exporters that never export (cooperatives selling
    to exporters), so the exporter universe is genuinely the union of both
    observation tables.
    """
    exporter_names = set(_column(declarations, "exporter_name")) | set(
        _column(purchases, "exporter_name")
    )
    exporter_names.discard("")
    destination_names = set(_column(declarations, "destination_name"))
    destination_names.discard("")

    known_exporters = mapping_names.get(EXPORTER, frozenset())
    known_destinations = mapping_names.get(DESTINATION, frozenset())

    records: list[EntityRecord] = []
    for name in sorted(exporter_names | known_exporters):
        records.append(
            EntityRecord(
                entity_type=EXPORTER,
                source_name=name,
                canonical_name=name,
                is_gepex_member=name in config.GEPEX_MEMBER_SEED,
                in_entity_mappings=name in known_exporters,
            )
        )
    for name in sorted(destination_names | known_destinations):
        records.append(
            EntityRecord(
                entity_type=DESTINATION,
                source_name=name,
                canonical_name=name,
                is_gepex_member=False,
                in_entity_mappings=name in known_destinations,
            )
        )

    unmapped_exporters = sorted(exporter_names - known_exporters)
    unmapped_destinations = sorted(destination_names - known_destinations)
    if unmapped_exporters or unmapped_destinations:
        logger.warning(
            "%d exporter(s) and %d destination(s) present in the data are absent "
            "from Entity_Mappings.xlsx — created anyway, flagged on the batch",
            len(unmapped_exporters),
            len(unmapped_destinations),
        )
    quality["entities_absent_from_mappings"] = {
        "exporters": unmapped_exporters,
        "destinations": unmapped_destinations,
    }

    missing_gepex = sorted(config.GEPEX_MEMBER_SEED - exporter_names)
    if missing_gepex:
        # Not fatal, but worth knowing: a GEPEX member that stopped appearing
        # silently shrinks the perimeter every transformation ratio is built on.
        logger.warning("GEPEX seed name(s) not present in the data: %s", missing_gepex)
        quality["gepex_seed_names_absent"] = missing_gepex

    return tuple(records)


# ---------------------------------------------------------------------------
# guards
# ---------------------------------------------------------------------------
def _assert_non_negative(series: pd.Series, column: str, dataset: str) -> None:
    negative = cast(pd.Series, series[series < 0])
    if len(negative):
        raise InvalidTonnageError(
            f"{dataset}: {len(negative)} row(s) with negative {column} "
            f"(e.g. {negative.iloc[0]}). A negative weight is not a correction, "
            "it is a broken extract."
        )


def _require_names(series: pd.Series, column: str) -> None:
    blank = int((series == "").sum())
    if blank:
        raise UnmappedEntityError(
            f"{blank} row(s) have an empty {column}. These would collapse into a "
            "single blank entity and merge unrelated flows."
        )
