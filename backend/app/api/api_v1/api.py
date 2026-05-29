from fastapi import APIRouter

from app.api.api_v1.endpoints import audio, auth, dashboard

api_router = APIRouter()

api_router.include_router(auth.router, prefix="/auth", tags=["authentication"])
api_router.include_router(dashboard.router, prefix="/dashboard", tags=["dashboard"])
api_router.include_router(audio.router, prefix="/audio", tags=["audio"])
