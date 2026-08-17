"""Typed failures for ``watchai-sync``.

Every one of these aborts the run with a non-zero exit and no partial write
(.claude/rules/pipeline-error-handling.md). There is deliberately no retry, no
provider fallback and no "skip the bad rows and carry on" path: this job loads
figures a client will read as fact, so a source that changed shape must stop the
pipeline and be looked at, not be silently absorbed.

The distinction that matters here is **fatal vs reported**. Anything that would
make the loaded numbers wrong is fatal and lives in this module. Anything that
merely describes the source's own imperfections (names missing from
Entity_Mappings, sentinel ``VALCAF`` values, precomputed columns that disagree
with a recompute) is counted into the batch's ``quality_report`` instead — those
conditions are permanently true of the upstream extract, so raising on them
would mean the job never runs at all.
"""

from __future__ import annotations


class WatchAiSyncError(Exception):
    """Base for every fatal condition in the sync job."""


class SourceNotFoundError(WatchAiSyncError):
    """``--source`` is not a directory, not a git checkout, or is missing a master file."""


class DirtyWorkingTreeError(WatchAiSyncError):
    """The watch-ai checkout has uncommitted changes that could affect the data.

    A batch records a commit SHA as its provenance. If the working tree differs
    from that commit, the SHA is a lie: re-running it later would not reproduce
    the same numbers, and ``pl_origin_ingest_batch`` is the only audit record
    this manual operation leaves behind.
    """


class SourceSchemaError(WatchAiSyncError):
    """A master file is missing a required column, or a column changed type.

    Fail loud rather than reindex around it — a shape change upstream means the
    extract itself changed and the transform's assumptions need re-checking.
    """


class UnknownProductError(WatchAiSyncError):
    """A product could not be resolved to the canonical taxonomy.

    WatchAI silently defaults both its ``categorize_product`` and its
    ``normalize_produit`` to ``FEVES`` (business-rules §2, two separate ``else``
    branches). Beans are ~85% of volume, so a wrong default is both invisible
    and material. We refuse instead.
    """


class UnmappedEntityError(WatchAiSyncError):
    """An exporter or destination row carries no usable ``*_SIMPLE`` name.

    Note this is *not* raised for names absent from ``Entity_Mappings.xlsx`` —
    47 exporters and 8 destinations in the current extract are in that state, so
    the mapping file is not a complete universe and cannot act as a gate. Those
    are reported on the batch instead. This error is for a genuinely empty name,
    which would silently merge unrelated flows into one blank entity.
    """


class InvalidTonnageError(WatchAiSyncError):
    """A negative weight or ground tonnage reached the transform."""


class RowCountRegressionError(WatchAiSyncError):
    """The new batch has materially fewer rows than the current one.

    The masters are rebuilt from scratch upstream (business-rules §12), so a
    truncated or half-written source file is a real failure mode and would
    otherwise land as a legitimate-looking "everything shrank" restatement.
    """


class CubeUniquenessError(WatchAiSyncError):
    """The cube has more than one row for a natural key, or lost/gained mass.

    The cube backs cross-series ratios (solde, taux de transformation); a
    fan-out there corrupts them with no visible symptom. See
    .claude/rules/timeseries-uniqueness.md.
    """


class ReconciliationError(WatchAiSyncError):
    """A computed total diverges from a published golden value.

    Per the integration doc §9: a divergence is a taxonomy (§2) or unit (§1)
    bug. It is never a reason to adjust the expected value.
    """


class ProdTargetRefusedError(WatchAiSyncError):
    """``--target prod`` was requested. Phase 1 is local-only by scope."""
