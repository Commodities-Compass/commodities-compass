from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.auth import get_current_user

router = APIRouter()


@router.get("/", deprecated=True)
async def get_commodities(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get list of all commodities"""
    # TODO: Implement database query
    return [
        {"id": 1, "symbol": "CC", "name": "Cocoa", "category": "Agricultural"},
        # Add more commodities as needed
    ]


@router.get("/{commodity_id}", deprecated=True)
async def get_commodity(
    commodity_id: int,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get specific commodity details"""
    # TODO: Implement database query
    return {
        "id": commodity_id,
        "symbol": "CC",
        "name": "Cocoa",
        "category": "Agricultural",
        "description": "West African cocoa futures",
    }
