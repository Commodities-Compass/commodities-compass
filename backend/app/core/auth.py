from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
from jose.exceptions import JOSEError
import httpx
import sentry_sdk
from cachetools import TTLCache
from typing import Any

from app.core.config import settings

# JWKS cache with 6 hour TTL like in the working example
jwks_cache: TTLCache[str, Any] = TTLCache(maxsize=1, ttl=21600)


def get_jwks() -> dict[str, Any]:
    """Fetches and caches JWKS from Auth0."""
    try:
        if "jwks" in jwks_cache:
            return jwks_cache["jwks"]
    except KeyError:
        pass

    jwks_url = f"https://{settings.AUTH0_DOMAIN}/.well-known/jwks.json"
    try:
        response = httpx.get(jwks_url)
        response.raise_for_status()
        jwks_data = response.json()
        jwks_cache["jwks"] = jwks_data
        return jwks_data
    except httpx.RequestError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not fetch JWKS for token validation.",
        ) from e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error processing JWKS for token validation.",
        ) from e


async def validate_auth0_token(token: str) -> dict:
    """Validate Auth0 JWT token and return payload."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials or token expired",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if not isinstance(token, str) or not token.strip():
        raise credentials_exception

    try:
        jwks = get_jwks()
        unverified_header = jwt.get_unverified_header(token)

        rsa_key = {}
        for key in jwks["keys"]:
            if key["kid"] == unverified_header["kid"]:
                rsa_key = {
                    "kty": key["kty"],
                    "kid": key["kid"],
                    "use": key["use"],
                    "n": key["n"],
                    "e": key["e"],
                }
                break

        if not rsa_key:
            raise credentials_exception

        payload = jwt.decode(
            token,
            rsa_key,
            algorithms=["RS256"],
            audience=settings.AUTH0_API_AUDIENCE,
            issuer=f"https://{settings.AUTH0_DOMAIN}/",
        )

        return payload

    except JWTError as e:
        raise credentials_exception from e
    except JOSEError as e:
        raise credentials_exception from e
    except Exception as e:
        raise credentials_exception from e


# Use the same HTTPBearer scheme as the working example
oauth2_scheme = HTTPBearer(scheme_name="Auth0ImplicitBearer", auto_error=True)


async def get_current_user(
    token: HTTPAuthorizationCredentials = Depends(oauth2_scheme),
) -> dict:
    """Get current user from Auth0 token"""
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token format from Authorization header.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    actual_token_str = token.credentials
    if not actual_token_str:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token format from Authorization header.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = await validate_auth0_token(actual_token_str)

    # Extract user info from token
    user = {
        "sub": payload.get("sub"),  # Auth0 user ID
        "email": payload.get("email"),
        "name": payload.get("name"),
        "permissions": payload.get("permissions", []),
    }

    sentry_sdk.set_user({"id": user["sub"], "email": user["email"]})

    return user
