"""Constants ported from WatchAI — the semantics that must not drift.

Everything here is a literal transcription of business-rules.md. Where WatchAI
carries an ambiguity, the resolution is recorded in a comment next to the value
rather than in a commit message, because the next person to read this file is
the one who has to reproduce a number in front of a client.
"""

from __future__ import annotations

from typing import Final

# --- Spec provenance --------------------------------------------------------
# The WatchAI state these rules were read from and reconciled against. Recorded
# for the reader, NOT enforced at runtime: batch identity is the sha256 of the
# source files (decision #5), and a new month legitimately moves any commit.
#
# `refonte-da-v2` is an active branch and the spec is pinned to a SHA on purpose:
# WatchAI was rebuilt as FastAPI + DuckDB + Next.js, and `main` is frozen at
# 2026-06-05 (May data). If RENDEMENT_BROYAGE or the product CASE below changed
# upstream without us noticing, every balance we publish would be restated —
# that is the top risk on this integration. Re-sync deliberately, re-run the
# reconciliation, then bump this string.
SPEC_SOURCE_BRANCH: Final[str] = "refonte-da-v2"
SPEC_SOURCE_COMMIT: Final[str] = "11336ef5038ffa839143e205c252ebdceb1d4bd9"
SPEC_VERIFIED_ON: Final[str] = "2026-08-17"

# Content identity of the exact dataset the golden fixtures were verified against
# — `SourceProvenance.combined_hash` over the four files at that commit. The
# reconciliation gate uses this to tell "our transform is wrong" apart from
# "you pointed me at a different dataset": on `main` (frozen at May data) the
# 2024-2025 product mix legitimately differs by 2 t, which is a restatement, not
# a bug. Bump it together with the three strings above, never on its own.
SPEC_SOURCE_FILE_SET_SHA256: Final[str] = (
    "c42b44e9052b0eab3804eafca0d22e5b273c4b4445310a5cf5df2a3b0f8e849c"
)

# --- Units (business-rules §1) ----------------------------------------------
# The single source of the kg→tonne conversion. Applied exactly once, at cube
# compute. PDS_NET and POIDS_NET_KG are kg; TONS_BROYES is ALREADY tonnes and
# must never be divided (the trap flagged at webapp_tax.py:1919).
KG_PER_TONNE: Final[int] = 1000

# The material balance (business-rules §4) is NOT computed here — it belongs to
# the serving layer, and its one constant lives with it in
# `app/services/origin_balance.py::RENDEMENT_BROYAGE`. Ingestion stores tonnages;
# it does not interpret them.

# --- Season (business-rules §3) ---------------------------------------------
# Cocoa season runs October → September. season(d) = "Y-Y+1" if month >= 10.
SEASON_START_MONTH: Final[int] = 10
SEASON_LABEL_LENGTH: Final[int] = 9  # "2025-2026"

# --- Product taxonomy (business-rules §2) -----------------------------------
# ONE canonical set, resolved at ingestion and stored on the row, so no query
# ever has to pick between WatchAI's three parallel taxonomies.
#
# MASSE absorbs LIQUEUR and PATE here, at ingestion. That collapse is what
# defuses the §2.2 latent bug: in WatchAI a null PRODUIT SIMPLE with POSTAR 1803
# becomes "LIQUEUR", which then matches neither FEVES_PRODUITS nor
# TRANSFO_PRODUITS and silently vanishes from the transformation balance.
PRODUCT_SIMPLE_MAP: Final[dict[str, str]] = {
    "FEVES": "FEVES",
    "FEVE": "FEVES",
    "CACAO EN GRAIN": "FEVES",
    "HORS GRADE": "HORS_GRADE",
    "HORS-GRADE": "HORS_GRADE",
    "MASSE": "MASSE",
    "PATE": "MASSE",
    "LIQUEUR": "MASSE",
    "BEURRE": "BEURRE",
    "POUDRE": "POUDRE",
    "CHOCOLAT": "CHOCOLAT",
    "COQUES": "COQUES",
}

# Fallback on the first 4 chars of the POSTAR customs code, used ONLY when
# PRODUIT SIMPLE is absent. WatchAI's version ends in `else: return 'FEVES'`;
# ours has no else — an unknown prefix raises (errors.UnknownProductError).
#
# 1803 maps to MASSE, not to WatchAI's "LIQUEUR", per the collapse above.
POSTAR_PREFIX_MAP: Final[dict[str, str]] = {
    "1801": "FEVES",
    "1802": "COQUES",
    "1803": "MASSE",
    "1804": "BEURRE",
    "1805": "POUDRE",
    "1806": "CHOCOLAT",
}
POSTAR_PREFIX_LENGTH: Final[int] = 4

# Bean-equivalent set (business-rules §2). Mirrored as a GENERATED column on
# pl_origin_flow_monthly so the solde formulas key on the database's own flag
# rather than re-listing products.
#
# NOTE — this contradicts the §9 golden line "TOTAL TRANSFORMÉ 473 907 (27,7 %)",
# which is 340 068 t of MASSE+BEURRE+POUDRE+CHOCOLAT *plus* 133 840 t of
# HORS GRADE, i.e. the published report treats "transformé" as everything that
# is not FEVES. §2 wins by decision: hors-grade beans are beans. The divergence
# is asserted explicitly in the reconciliation report instead of being buried.
BEAN_EQUIVALENT_CODES: Final[frozenset[str]] = frozenset({"FEVES", "HORS_GRADE"})

# --- GEPEX membership (business-rules §9) -----------------------------------
# 11 canonical names, hardcoded at auth_config.py:25 in WatchAI. Seeded onto
# ref_origin_entity.is_gepex_member so it becomes editable without a deploy
# (North Star: config as data). This tuple is the seed, not the runtime source
# of truth — after the first load, the column is authoritative.
GEPEX_MEMBER_SEED: Final[frozenset[str]] = frozenset(
    {
        "ATLANTIC",
        "BARRY",
        "CARGILL",
        "CCB",
        "CEMOI",
        "ECOM",
        "GCB",
        "ICP",
        "NESTLE",
        "OLAM",
        "SUCDEN",
    }
)

# --- Source layout ----------------------------------------------------------
MASTER_DATA_DIR: Final[str] = "Master_Data"
DECLARATIONS_FILE: Final[str] = "Db_Master_Tax.parquet"
PURCHASES_FILE: Final[str] = "Db_Master_Achats.parquet"
GRINDINGS_FILE: Final[str] = "Db_Master_Broyage.parquet"
ENTITY_MAPPINGS_FILE: Final[str] = "Entity_Mappings.xlsx"

# Hashed on every run — together these four hashes ARE the batch identity
# (decision #5), which is why the list is explicit rather than a glob: a new file
# appearing in Master_Data/ must not silently change what a batch means.
REQUIRED_SOURCE_FILES: Final[tuple[str, ...]] = (
    DECLARATIONS_FILE,
    PURCHASES_FILE,
    GRINDINGS_FILE,
    ENTITY_MAPPINGS_FILE,
)

# Only the two sheets whose dimensions we actually ingest. Destinataires and
# Declarant map columns dropped by the reduced projection (decision #7), so
# reading them would import 54k rows we can never use.
ENTITY_MAPPING_SHEETS: Final[dict[str, str]] = {
    "exporter": "Exportateurs",
    "destination": "Destinations",
}
ENTITY_MAPPING_SIMPLE_COLUMN: Final[dict[str, str]] = {
    "exporter": "EXPORTATEUR_SIMPLE",
    "destination": "DESTINATION_SIMPLE",
}

# --- Required source columns (fail loud on drift) ---------------------------
DECLARATION_COLUMNS: Final[tuple[str, ...]] = (
    "DATE_SIMPLE",
    "EXPORTATEUR_SIMPLE",
    "DESTINATION_SIMPLE",
    "PDS_NET",
    "VALCAF",
    "DROITS_TAXES",
    "POSTAR",
    "PRODUIT SIMPLE",
    "PORT",
)
PURCHASE_COLUMNS: Final[tuple[str, ...]] = (
    "EXPORTATEUR_SIMPLE",
    "DATE",
    "POIDS_NET_KG",
)
GRINDING_COLUMNS: Final[tuple[str, ...]] = ("DATE", "TONS_BROYES")

# --- Batch retention --------------------------------------------------------
# Keep the previous batch so the next run has something to diff against
# (integration doc §4 step 5). Two is the minimum that makes restatement
# detection possible; more is just disk.
DEFAULT_KEEP_BATCHES: Final[int] = 2

# A new batch may legitimately shrink (upstream restates history), but not by
# much — the masters are rebuilt from scratch each month, so a truncated source
# file is a real failure mode that would otherwise look like a restatement.
ROW_COUNT_REGRESSION_TOLERANCE: Final[float] = 0.02  # 2%

# A month is reported as restated when its total moves by more than this.
# Pure float-noise moves are not news; a real correction upstream is.
RESTATEMENT_TOLERANCE_TONNES: Final[float] = 0.5

# --- Local default target ---------------------------------------------------
# scripts/db.py deliberately has no fallback URL so a scraper can never write
# locally by accident. This job is the mirror case — local by default, and prod
# reachable only through an explicit `--target prod` plus a tunnel URL from the
# environment — so a local default is the safe choice.
LOCAL_DATABASE_URL: Final[str] = (
    "postgresql://postgres:password@localhost:5433/commodities_compass"
)
