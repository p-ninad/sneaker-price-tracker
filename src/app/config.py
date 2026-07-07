"""Configuration management for the price tracker."""

from pathlib import Path
import os
from typing import Optional

from dotenv import dotenv_values
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(case_sensitive=False, extra="ignore")

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
    telegram_require_chat_id: bool = Field(
        default=True, alias="TELEGRAM_REQUIRE_CHAT_ID"
    )
    telegram_connectivity_enabled: bool = Field(
        default=True, alias="TELEGRAM_CONNECTIVITY_ENABLED"
    )

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
    scan_on_startup: bool = Field(default=False, alias="SCAN_ON_STARTUP")
    enable_catalog_scan: bool = Field(default=False, alias="ENABLE_CATALOG_SCAN")
    catalog_scan_interval_hours: int = Field(
        default=6, alias="CATALOG_SCAN_INTERVAL_HOURS"
    )
    watchlist_scan_interval_hours: int = Field(
        default=1, alias="WATCHLIST_SCAN_INTERVAL_HOURS"
    )
    hot_items_scan_interval_minutes: int = Field(
        default=15, alias="HOT_ITEMS_SCAN_INTERVAL_MINUTES"
    )
    brand_monitor_scan_interval_minutes: int = Field(
        default=15, alias="BRAND_MONITOR_SCAN_INTERVAL_MINUTES"
    )
    brand_monitor_result_limit: int = Field(
        default=50, alias="BRAND_MONITOR_RESULT_LIMIT"
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

    # === Authentication ===
    auth_session_cookie_name: str = Field(
        default="price_tracker_session", alias="AUTH_SESSION_COOKIE_NAME"
    )
    auth_session_ttl_hours: int = Field(default=24 * 7, alias="AUTH_SESSION_TTL_HOURS")
    auth_password_iterations: int = Field(
        default=310_000, alias="AUTH_PASSWORD_ITERATIONS"
    )
    auth_bootstrap_token: Optional[str] = Field(
        default=None, alias="AUTH_BOOTSTRAP_TOKEN"
    )

    @model_validator(mode="after")
    def validate_secret_configuration(self):
        """Fail fast when the runtime configuration is internally inconsistent."""
        if not self.telegram_connectivity_enabled:
            return self

        if self.telegram_chat_id and not self.telegram_bot_token:
            raise ValueError("TELEGRAM_BOT_TOKEN must be set when TELEGRAM_CHAT_ID is set.")

        if self.telegram_bot_token and self.telegram_require_chat_id and not self.telegram_chat_id:
            raise ValueError(
                "TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must both be set together."
            )

        return self

    @property
    def enabled_platforms_list(self) -> list[str]:
        """Return list of enabled platforms."""
        return [p.strip() for p in self.enabled_platforms.split(",")]

    @property
    def is_production(self) -> bool:
        """Check if running in production."""
        return self.env.lower() == "production"


def load_settings(env_file: str | Path | None = None) -> Settings:
    """Load settings from the environment and an optional env file.

    Use APP_ENV_FILE to override the default .env path. If the file is missing,
    the application falls back to environment variables only.
    """
    env_file_path = (
        Path(env_file)
        if env_file is not None
        else Path(os.getenv("APP_ENV_FILE", ".env"))
    )

    if not env_file_path.exists():
        return Settings()

    env_values = dotenv_values(str(env_file_path))
    original_env = {key: os.environ.get(key) for key in env_values if key in os.environ}

    try:
        for key, value in env_values.items():
            if value is not None and key not in os.environ:
                os.environ[key] = value

        return Settings()
    finally:
        for key, original_value in original_env.items():
            if original_value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = original_value

        for key in env_values:
            if key not in original_env:
                os.environ.pop(key, None)


settings = load_settings()
