from fastapi import APIRouter, Depends

from app.core.auth import get_current_user
from app.core.config import settings
from app.core.tenancy import TenantPrincipal, get_current_principal
from app.schemas.auth import TokenVerifyResponse, UserResponse

router = APIRouter()


@router.get("/me", response_model=UserResponse)
async def get_me(
    current_user: dict = Depends(get_current_user),
    principal: TenantPrincipal = Depends(get_current_principal),
) -> UserResponse:
    """Get current user information + resolved entitlement context.

    The `entitlements` list is what the frontend uses to gate sections; the
    backend 403 is the real boundary (this is only for UI show/hide).
    """
    return UserResponse(
        **current_user,
        tier=principal.tier,
        account_code=principal.account_code,
        entitlements=sorted(principal.entitlements),
        enforced=settings.ENTITLEMENTS_ENFORCED,
        billing_status=principal.billing_status,
    )


@router.get("/verify", response_model=TokenVerifyResponse)
async def verify_token(
    current_user: dict = Depends(get_current_user),
) -> TokenVerifyResponse:
    """Verify if token is valid."""
    return TokenVerifyResponse(valid=True, user_id=current_user.get("sub"))
