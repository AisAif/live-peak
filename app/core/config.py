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

    # Peak Notification Webhook (Discord / Telegram / generic HTTP)
    WEBHOOK_URL: str = ""

    # Analytics Parameters
    Z_SCORE_THRESHOLD: float = 2.5
    Z_SCORE_METHOD: str = "mad"  # "mad" (robust median/MAD) or "std" (mean/std)
    WINDOW_DURATION_SECONDS: int = 10  # Aggregation window interval
    SLIDING_WINDOW_SIZE: int = 30  # Baseline window count (30 * 10s = 300s / 5 mins)

    # EWMA Detection (detects sustained shifts in chat velocity)
    ENABLE_EWMA_DETECTION: bool = True
    EWMA_ALPHA: float = 0.2  # Smoothing factor in (0, 1]; lower = slower adaptation
    EWMA_Z_THRESHOLD: float = 3.0

    # CUSUM Detection (detects small but persistent increases)
    ENABLE_CUSUM_DETECTION: bool = True
    CUSUM_DRIFT_SIGMA: float = 0.5  # Allowance before accumulating
    CUSUM_THRESHOLD_SIGMA: float = 5.0  # Alarm threshold

    # Raw Chat Storage (opt-in; can grow quickly)
    ENABLE_RAW_CHAT_STORAGE: bool = False
    CHAT_MESSAGE_RETENTION_DAYS: int = 7
    CHAT_FLUSH_BATCH_SIZE: int = 500

    # Data Retention & Hourly Rollup (0 days = keep forever)
    ENABLE_DATA_RETENTION: bool = True
    WINDOW_STATS_RETENTION_DAYS: int = 30
    PEAK_EVENTS_RETENTION_DAYS: int = 365
    RETENTION_CHECK_INTERVAL_HOURS: float = 6.0

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
