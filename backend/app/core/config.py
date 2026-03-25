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
    AUTH0_ALGORITHMS: List[str] = config(
        "AUTH0_ALGORITHMS", default="RS256", cast=str
    ).split(",")
    AUTH0_ISSUER: str = config("AUTH0_ISSUER", default="", cast=str)

    # CORS
    BACKEND_CORS_ORIGINS: List[str] = []

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Handle CORS origins from environment
        cors_origins = config(
            "BACKEND_CORS_ORIGINS",
            default='["http://localhost:5173", "http://localhost:3000"]',
            cast=str,
        )
        if isinstance(cors_origins, str):
            try:
                # Try to parse as JSON array first
                self.BACKEND_CORS_ORIGINS = json.loads(cors_origins)
            except json.JSONDecodeError:
                # Fall back to comma-separated string
                self.BACKEND_CORS_ORIGINS = [
                    origin.strip() for origin in cors_origins.split(",")
                ]

    # Database
    DATABASE_URL: str = config("DATABASE_URL", default="", cast=str)
    DATABASE_SYNC_URL: str = config("DATABASE_SYNC_URL", cast=str)

    # Redis
    REDIS_URL: str = config("REDIS_URL", default="redis://localhost:6379/0", cast=str)

    # Google Sheets
    GOOGLE_SHEETS_CREDENTIALS_JSON: str = config(
        "GOOGLE_SHEETS_CREDENTIALS_JSON", default="", cast=str
    )
    SPREADSHEET_ID: str = config("SPREADSHEET_ID", default="", cast=str)

    # Google Drive
    GOOGLE_DRIVE_CREDENTIALS_JSON: str = config(
        "GOOGLE_DRIVE_CREDENTIALS_JSON",
        default=config("GOOGLE_SHEETS_CREDENTIALS_JSON", default="", cast=str),
        cast=str,
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


settings = Settings()
