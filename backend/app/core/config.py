# pyright: reportAssignmentType=false, reportAttributeAccessIssue=false
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict
from decouple import config
import json


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        case_sensitive=True,
        env_file=".env",
        extra="ignore",
        # All values are read via python-decouple (class-level defaults).
        # Disable pydantic-settings env parsing to prevent JSON decode errors
        # on non-JSON env vars like BACKEND_CORS_ORIGINS and AUTH0_ALGORITHMS.
        env_parse_none_str=None,
    )

    # Application
    APP_NAME: str = config("APP_NAME", default="Commodities Compass", cast=str)
    APP_VERSION: str = config("APP_VERSION", default="1.0.0", cast=str)
    API_V1_STR: str = config("API_V1_STR", default="/v1", cast=str)
    DEBUG: bool = config("DEBUG", default=False, cast=bool)
    BACKEND_PORT: int = config("BACKEND_PORT", default=8000, cast=int)

    # Auth0 (defaults allow standalone cron services that don't need auth)
    AUTH0_DOMAIN: str = config("AUTH0_DOMAIN", default="", cast=str)
    AUTH0_CLIENT_ID: str = config("AUTH0_CLIENT_ID", default="", cast=str)
    AUTH0_API_AUDIENCE: str = config("AUTH0_API_AUDIENCE", default="", cast=str)
    AUTH0_ALGORITHMS: str = config("AUTH0_ALGORITHMS", default="RS256", cast=str)
    AUTH0_ISSUER: str = config("AUTH0_ISSUER", default="", cast=str)

    # CORS
    BACKEND_CORS_ORIGINS: str = config(
        "BACKEND_CORS_ORIGINS",
        default="http://localhost:5173,http://localhost:3000",
        cast=str,
    )

    # Database
    DATABASE_URL: str = config("DATABASE_URL", default="", cast=str)
    DATABASE_SYNC_URL: str = config("DATABASE_SYNC_URL", cast=str)

    # Redis
    REDIS_URL: str = config("REDIS_URL", default="redis://localhost:6379/0", cast=str)

    # Google Drive (audio streaming + compass brief upload)
    GOOGLE_DRIVE_CREDENTIALS_JSON: str = config(
        "GOOGLE_DRIVE_CREDENTIALS_JSON", default="", cast=str
    )
    GOOGLE_DRIVE_AUDIO_FOLDER_ID: str = config(
        "GOOGLE_DRIVE_AUDIO_FOLDER_ID", default="", cast=str
    )

    # External APIs
    WEATHER_API_KEY: str = config("WEATHER_API_KEY", default="", cast=str)
    NEWS_API_KEY: str = config("NEWS_API_KEY", default="", cast=str)

    # AWS Configuration
    AWS_ACCESS_KEY_ID: str = config("AWS_ACCESS_KEY_ID", default="", cast=str)
    AWS_SECRET_ACCESS_KEY: str = config("AWS_SECRET_ACCESS_KEY", default="", cast=str)
    AWS_REGION: str = config("AWS_REGION", default="us-east-1", cast=str)
    S3_BUCKET_NAME: str = config("S3_BUCKET_NAME", default="", cast=str)

    @property
    def auth0_algorithms_list(self) -> List[str]:
        return [a.strip() for a in self.AUTH0_ALGORITHMS.split(",")]

    @property
    def cors_origins(self) -> List[str]:
        raw = self.BACKEND_CORS_ORIGINS
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return [o.strip() for o in raw.split(",") if o.strip()]


settings = Settings()
