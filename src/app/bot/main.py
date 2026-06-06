"""Telegram bot runtime entrypoint."""

from __future__ import annotations

import signal
import sys

import app.config as config
from app.database.db import init_db
from app.utils.logger import get_logger, setup_logging

logger = None


def initialize_bot():
    """Initialize the Telegram bot runtime."""
    global logger

    logger = get_logger(__name__)
    init_db()

    if not config.settings.telegram_bot_token:
        raise ValueError("TELEGRAM_BOT_TOKEN is required to run the Telegram bot")

    from app.bot.telegram import create_application

    application = create_application(config.settings.telegram_bot_token)
    return application


def main() -> None:
    """Run the Telegram bot with polling."""
    global logger

    try:
        setup_logging()
        if logger is None:
            logger = get_logger(__name__)
    except Exception:
        print("Failed to initialize logging", file=sys.stderr)

    try:
        application = initialize_bot()

        logger.info("=" * 60)
        logger.info("Price Tracker Telegram Bot Starting")
        logger.info("=" * 60)

        def signal_handler(sig, frame):
            logger.info("Received shutdown signal", signal=sig)
            raise SystemExit(0)

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        application.run_polling(
            allowed_updates=None,
            close_loop=False,
        )
    except Exception as exc:
        logger.error("Fatal error during bot startup", error=str(exc))
        sys.exit(1)


if __name__ == "__main__":
    main()
