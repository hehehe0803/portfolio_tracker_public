"""
Configuration Management.

Uses Pydantic Settings to load configuration from environment variables
with automatic type validation and fallback defaults.
"""

import os
from functools import lru_cache
from pathlib import Path
from typing import List

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.
    
    All settings are case-insensitive and can be configured via:
    - Environment variables
    - .env file
    - Command line arguments (for testing)
    """
    
    _repo_root = Path(__file__).parents[2]
    _api_dir = Path(__file__).parents[1]

    model_config = SettingsConfigDict(
        env_file=(_repo_root / ".env", _api_dir / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )
    
    # Application settings
    VERSION: str = "0.1.0"
    ENVIRONMENT: str = "development"
    DEBUG: bool = False
    SECRET_KEY: str = "your-secret-key-change-in-production"
    STARTUP_DB_INIT_ENABLED: bool = True
    STARTUP_REPAIRS_ENABLED: bool = True
    API_SCHEDULER_ENABLED: bool = True
    
    # CORS settings
    CORS_ORIGINS: List[str] = Field(
        default=["http://localhost:3000", "http://localhost:3001", "http://localhost:8000", "http://100.108.242.71:3000"],
        description="List of allowed CORS origins",
    )
    # Extra CORS origins for tunnel access (e.g. ngrok/Cloudflare tunnel URL)
    EXTRA_CORS_ORIGINS: List[str] = Field(
        default=[],
        description="Additional CORS origins for tunnel/remote access",
    )
    
    # Database settings
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://localhost/portfolio_dev",
        description="PostgreSQL connection URL",
    )
    
    # Redis settings
    REDIS_URL: str = Field(
        default="redis://localhost:6379/0",
        description="Redis connection URL",
    )
    
    # Owned polling / scheduler settings
    OWNED_POLLING_ENABLED: bool = True
    OWNED_POLLING_CADENCE_SECONDS: int = Field(default=900, ge=60)
    OWNED_POLLING_STALE_AFTER_SECONDS: int = Field(default=1800, ge=60)
    OWNED_POLLING_LOCK_TTL_SECONDS: int = Field(default=840, ge=30)
    OWNED_POLLING_MAX_CATCH_UP_WINDOWS: int = Field(default=4, ge=1)
    BINANCE_AUTO_SYNC_ENABLED: bool = False
    BINANCE_AUTO_SYNC_CADENCE_SECONDS: int = Field(default=3600, ge=300)
    BINANCE_AUTO_SYNC_LOCK_TTL_SECONDS: int = Field(default=3300, ge=60)
    WATCHLIST_ALERTS_ENABLED: bool = False
    WATCHLIST_ALERTS_CADENCE_SECONDS: int = Field(default=3600, ge=300)

    # S3/MinIO settings
    S3_ENDPOINT: str = Field(
        default="http://localhost:9000",
        description="S3-compatible endpoint URL",
    )

    S3_ACCESS_KEY: str = Field(default="minioadmin")
    S3_SECRET_KEY: str = Field(default="minioadmin")
    S3_BUCKET: str = Field(default="portfolio-artifacts")
    
    # Binance API settings
    BINANCE_API_KEY: str = Field(default="")
    BINANCE_API_SECRET: str = Field(default="")
    INSTITUTION_CREDENTIALS_MASTER_KEY: str = Field(default="")

    # API telemetry + rate limiting
    TELEMETRY_MAX_EVENTS: int = Field(default=200, ge=10)
    RATE_LIMIT_AUTH_REQUESTS: int = Field(default=5, ge=1)
    RATE_LIMIT_AUTH_WINDOW_SECONDS: int = Field(default=60, ge=1)
    RATE_LIMIT_SENSITIVE_REQUESTS: int = Field(default=3, ge=1)
    RATE_LIMIT_SENSITIVE_WINDOW_SECONDS: int = Field(default=60, ge=1)
    RATE_LIMIT_TRUST_PROXY_HEADERS: bool = False
    
    # Telegram Bot settings
    TELEGRAM_BOT_TOKEN: str = Field(default="")
    TELEGRAM_CHAT_ID: str = Field(default="")
    
    # Logging level
    LOG_LEVEL: str = "INFO"
    
    @property
    def is_production(self) -> bool:
        """Check if running in production environment."""
        return self.ENVIRONMENT == "production"
    
    @property
    def is_debug(self) -> bool:
        """Check if debug mode is enabled."""
        return self.DEBUG or self.ENVIRONMENT == "development"


@lru_cache
def get_settings() -> Settings:
    """
    Get cached settings instance.
    
    Uses lru_cache to ensure only one settings instance exists
    throughout the application lifetime.
    
    Returns:
        Settings instance.
    """
    return Settings()


# Create global settings instance for direct imports
settings = get_settings()
