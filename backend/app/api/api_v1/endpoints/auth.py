from fastapi import APIRouter, Depends

from app.core.auth import get_current_user
from app.schemas.auth import TokenVerifyResponse, UserResponse

router = APIRouter()


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: dict = Depends(get_current_user)) -> UserResponse:
    """Get current user information from Auth0 token."""
    return UserResponse(**current_user)


@router.get("/verify", response_model=TokenVerifyResponse)
async def verify_token(
    current_user: dict = Depends(get_current_user),
) -> TokenVerifyResponse:
    """Verify if token is valid."""
    return TokenVerifyResponse(valid=True, user_id=current_user.get("sub"))
