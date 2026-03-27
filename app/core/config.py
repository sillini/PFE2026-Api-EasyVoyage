"""
Application configuration — loaded from environment variables / .env file.
All settings are validated at startup via Pydantic.
"""
from functools import lru_cache
from typing import List

from pydantic import AnyHttpUrl, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # ── Application ──────────────────────────────────────────
    APP_NAME: str = "Voyage Hotel API"
    APP_ENV: str = "development"
    DEBUG: bool = True

    # ── Database ─────────────────────────────────────────────
    DB_HOST: str = "localhost"
    DB_PORT: int = 5432
    DB_NAME: str = "voyage_hotel"
    DB_USER: str = "postgres"
    DB_PASSWORD: str = "postgres"
    DB_SCHEMA: str = "voyage_hotel"   # PostgreSQL search_path

    @property
    def DATABASE_URL(self) -> str:
        """Async SQLAlchemy connection string for asyncpg."""
        return (
            f"postgresql+asyncpg://{self.DB_USER}:{self.DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
        )

    # ── JWT ───────────────────────────────────────────────────
    SECRET_KEY: str = "change-me-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # ── CORS ──────────────────────────────────────────────────
    ALLOWED_ORIGINS: List[str] = ["http://localhost:3000", "http://localhost:5173"]

    @field_validator("ALLOWED_ORIGINS", mode="before")
    @classmethod
    def parse_origins(cls, v):
        if isinstance(v, str):
            import json
            return json.loads(v)
        return v

    # ── Email / SMTP ───────────────────────────────────────────
    SMTP_HOST:          str = "smtp-relay.brevo.com"
    SMTP_PORT:          int = 587
    SMTP_USER:          str = "a54180001@smtp-brevo.com"
    SMTP_PASSWORD:      str = ""
    SMTP_FROM:          str = "EasyVoyage <malekghamgui270@gmail.com>"
    OTP_EXPIRE_MINUTES: int = 15


@lru_cache
def get_settings() -> Settings:
    """Return a cached singleton of Settings."""
    s = Settings()
    print(f"\n[CONFIG] SMTP_FROM = {s.SMTP_FROM}")
    print(f"[CONFIG] SMTP_USER = {s.SMTP_USER}\n")
    return s


settings = get_settings()