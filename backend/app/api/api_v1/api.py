from fastapi import APIRouter

from app.api.api_v1.endpoints import audio, auth, billing, dashboard, data, origin

api_router = APIRouter()

api_router.include_router(auth.router, prefix="/auth", tags=["authentication"])
api_router.include_router(dashboard.router, prefix="/dashboard", tags=["dashboard"])
api_router.include_router(audio.router, prefix="/audio", tags=["audio"])
api_router.include_router(data.router, prefix="/data", tags=["data"])
# Origin physical flows (matrix block 2). Under /dashboard because it is a
# dashboard section (VI), gated per row by read:watchai:* keys.
api_router.include_router(origin.router, prefix="/dashboard/origin", tags=["origin"])
# Billing. No prefix: the module owns two unrelated paths — /webhooks/stripe
# (unauthenticated, signature-gated) and /billing/portal-session (authenticated,
# deliberately NOT entitlement-gated so an unpaid client can still fix its card).
api_router.include_router(billing.router, tags=["billing"])
