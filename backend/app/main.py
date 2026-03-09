from contextlib import asynccontextmanager
from datetime import datetime, timezone
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.openapi.utils import get_openapi
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
import logging
import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration

from app.core.config import settings
from app.core.database import AsyncSessionLocal, engine, sync_engine, get_db
from app.core.sentry import init_sentry
from app.api.api_v1.api import api_router

# Initialize Sentry before FastAPI instantiation
init_sentry("fastapi", [FastApiIntegration(), SqlalchemyIntegration()])

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Verify DB on startup, dispose engines on shutdown."""
    async with AsyncSessionLocal() as session:
        await session.execute(text("SELECT 1"))
    logger.info("Database connection verified")
    yield
    await engine.dispose()
    sync_engine.dispose()
    logger.info("Database connections disposed")


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    lifespan=lifespan,
)

# Set all CORS enabled origins
origins = settings.BACKEND_CORS_ORIGINS

logger.info("CORS origins configured: %s", origins)

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log incoming requests with sensitive data stripped."""
    logger.info("%s %s", request.method, request.url.path)
    response = await call_next(request)
    logger.info("%s %s -> %d", request.method, request.url.path, response.status_code)
    return response


@app.get("/")
async def root():
    return {
        "message": f"Welcome to {settings.APP_NAME} API",
        "version": settings.APP_VERSION,
        "docs": f"{settings.API_V1_STR}/docs",
    }


@app.get("/health")
async def health_check(db: AsyncSession = Depends(get_db)):
    await db.execute(text("SELECT 1"))
    return {"status": "healthy", "timestamp": datetime.now(timezone.utc)}


# Include API router
app.include_router(api_router, prefix=settings.API_V1_STR)


# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    if isinstance(exc, (HTTPException, StarletteHTTPException)):
        raise exc

    sentry_sdk.capture_exception(exc)
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


def main():
    """Entry point for poetry run dev"""
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )


def custom_openapi():
    """Custom OpenAPI schema with Auth0 OAuth2 configuration."""
    if app.openapi_schema:
        return app.openapi_schema

    openapi_schema = get_openapi(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description="Business Intelligence application for commodities trading",
        routes=app.routes,
    )

    if "components" not in openapi_schema:
        openapi_schema["components"] = {}
    if "securitySchemes" not in openapi_schema["components"]:
        openapi_schema["components"]["securitySchemes"] = {}

    openapi_schema["components"]["securitySchemes"]["Auth0ImplicitBearer"] = {
        "type": "oauth2",
        "flows": {
            "implicit": {
                "authorizationUrl": f"https://{settings.AUTH0_DOMAIN}/authorize"
                f"?audience={settings.AUTH0_API_AUDIENCE}",
                "scopes": {
                    "openid": "OpenID Connect Features",
                    "profile": "Read user profile information",
                    "email": "Read user email address",
                },
            }
        },
    }

    # Apply security to all operations
    if "security" not in openapi_schema:
        openapi_schema["security"] = []
    openapi_schema["security"].append({"Auth0ImplicitBearer": []})

    app.openapi_schema = openapi_schema
    return app.openapi_schema


# Override the default OpenAPI schema
app.openapi = custom_openapi


if __name__ == "__main__":
    main()
