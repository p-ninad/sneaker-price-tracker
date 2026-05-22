"""Configuration management for the price tracker."""

from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Optional
from pathlib import Path
import os


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # === Core ===
    env: str = Field(default="development", alias="ENV")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    
    # Database - use absolute path to data directory
    _data_dir = Path(__file__).parent.parent.parent / "data"
    _data_dir.mkdir(exist_ok=True)
    
    database_url: str = Field(
        default=f"sqlite:///{_data_dir / 'price_tracker.db'}", alias="DATABASE_URL"
    )

    # === OpenAI ===
    openai_api_key: Optional[str] = Field(default=None, alias="OPENAI_API_KEY")
    openai_model_main: str = Field(default="gpt-4o-mini", alias="OPENAI_MODEL_MAIN")
    openai_model_cheap: str = Field(default="gpt-4o-mini", alias="OPENAI_MODEL_CHEAP")

    # === Telegram ===
    telegram_bot_token: Optional[str] = Field(
        default=None, alias="TELEGRAM_BOT_TOKEN"
    )
    telegram_chat_id: Optional[str] = Field(default=None, alias="TELEGRAM_CHAT_ID")

    # === Scraping ===
    playwright_headless: bool = Field(default=True, alias="PLAYWRIGHT_HEADLESS")
    browser_timeout_ms: int = Field(default=30000, alias="BROWSER_TIMEOUT_MS")
    request_timeout_seconds: int = Field(default=15, alias="REQUEST_TIMEOUT_SECONDS")

    # === Rate Limiting ===
    min_delay_between_requests_seconds: float = Field(
        default=3, alias="MIN_DELAY_BETWEEN_REQUESTS_SECONDS"
    )
    max_delay_between_requests_seconds: float = Field(
        default=10, alias="MAX_DELAY_BETWEEN_REQUESTS_SECONDS"
    )
    retry_max_attempts: int = Field(default=3, alias="RETRY_MAX_ATTEMPTS")
    retry_backoff_factor: float = Field(default=2, alias="RETRY_BACKOFF_FACTOR")

    # === Scheduler ===
    enable_scheduler: bool = Field(default=True, alias="ENABLE_SCHEDULER")
    catalog_scan_interval_hours: int = Field(
        default=6, alias="CATALOG_SCAN_INTERVAL_HOURS"
    )
    watchlist_scan_interval_hours: int = Field(
        default=1, alias="WATCHLIST_SCAN_INTERVAL_HOURS"
    )
    hot_items_scan_interval_minutes: int = Field(
        default=15, alias="HOT_ITEMS_SCAN_INTERVAL_MINUTES"
    )

    # === Platforms ===
    enabled_platforms: str = Field(
        default="myntra,ajio,vegnonveg,superkicks", alias="ENABLED_PLATFORMS"
    )

    # === Notifications ===
    price_drop_threshold_percent: float = Field(
        default=10, alias="PRICE_DROP_THRESHOLD_PERCENT"
    )
    new_product_notification_enabled: bool = Field(
        default=True, alias="NEW_PRODUCT_NOTIFICATION_ENABLED"
    )
    restock_notification_enabled: bool = Field(
        default=True, alias="RESTOCK_NOTIFICATION_ENABLED"
    )

    class Config:
        env_file = ".env"
        case_sensitive = False

    @property
    def enabled_platforms_list(self) -> list[str]:
        """Return list of enabled platforms."""
        return [p.strip() for p in self.enabled_platforms.split(",")]

    @property
    def is_production(self) -> bool:
        """Check if running in production."""
        return self.env.lower() == "production"


# Global settings instance
settings = Settings()
