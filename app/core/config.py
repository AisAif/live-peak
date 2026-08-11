import os
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """App settings loaded from environment variables or .env file."""

    PROJECT_NAME: str = "YouTube Live Highlight & Peak Analyzer"
    DEBUG: bool = True
    LOG_LEVEL: str = "INFO"

    # Dashboard Authentication Credentials
    DASHBOARD_USERNAME: str = "admin"
    DASHBOARD_PASSWORD: str = "admin123"

    # Database Configuration (Default SQLite Local Async)
    DATABASE_URL: str = "sqlite+aiosqlite:///./live_peak.db"

    # Analytics Parameters
    Z_SCORE_THRESHOLD: float = 2.5
    WINDOW_DURATION_SECONDS: int = 10  # Aggregation window interval
    SLIDING_WINDOW_SIZE: int = 30  # Baseline window count (30 * 10s = 300s / 5 mins)

    # Peak Merging & Time Padding Parameters
    PEAK_MERGE_GAP_SECONDS: int = 30  # Merge peaks if distance <= 30 seconds
    PEAK_PADDING_BEFORE_SECONDS: int = 15  # Pre-peak video clip offset
    PEAK_PADDING_AFTER_SECONDS: int = 15  # Post-peak video clip offset

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


settings = Settings()
