"""Active contract and algorithm version resolution.

Bridges commodity-centric legacy queries to contract-centric pl_* tables.
"""

import uuid
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.reference import RefContract
from app.models.pipeline import PlAlgorithmVersion

logger = logging.getLogger(__name__)


async def get_active_contract_id(db: AsyncSession) -> uuid.UUID:
    """Get the active contract ID from ref_contract."""
    query = select(RefContract.id).where(RefContract.is_active.is_(True)).limit(1)
    result = await db.execute(query)
    contract_id = result.scalar_one_or_none()
    if contract_id is None:
        raise ValueError("No active contract found in ref_contract")
    return contract_id


async def get_active_algorithm_version_id(db: AsyncSession) -> uuid.UUID:
    """Get the active algorithm version ID from pl_algorithm_version."""
    query = (
        select(PlAlgorithmVersion.id)
        .where(PlAlgorithmVersion.is_active.is_(True))
        .limit(1)
    )
    result = await db.execute(query)
    algo_id = result.scalar_one_or_none()
    if algo_id is None:
        raise ValueError("No active algorithm version found in pl_algorithm_version")
    return algo_id
