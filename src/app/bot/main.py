"""Telegram bot runtime entrypoint."""

from __future__ import annotations

import asyncio
import signal
import sys

import app.config as config
from app.database.db import get_session, init_db
from app.database.repository import AppSettingRepository
from app.utils.logger import get_logger, setup_logging

logger = None
DEFAULT_CONNECTIVITY_POLL_SECONDS = 10


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


def telegram_connectivity_enabled() -> bool:
    """Return whether the bot is allowed to communicate with Telegram."""
    session = get_session()
    try:
        return AppSettingRepository.telegram_connectivity_enabled(session)
    except Exception as exc:
        logger.warning(
            "telegram_connectivity_check_failed",
            error=str(exc),
        )
        return config.settings.telegram_connectivity_enabled
    finally:
        session.close()


async def _maybe_call_post_init(application) -> None:
    """Run python-telegram-bot post_init when manually managing lifecycle."""
    post_init = getattr(application, "post_init", None)
    if post_init is not None:
        await post_init(application)


async def start_polling_application(application) -> None:
    """Start a python-telegram-bot application without blocking forever."""
    await application.initialize()
    await _maybe_call_post_init(application)
    await application.start()
    updater = getattr(application, "updater", None)
    if updater is not None:
        await updater.start_polling(allowed_updates=None)


async def stop_polling_application(application) -> None:
    """Stop a manually managed python-telegram-bot application."""
    updater = getattr(application, "updater", None)
    if updater is not None and getattr(updater, "running", False):
        await updater.stop()

    if getattr(application, "running", False):
        await application.stop()

    await application.shutdown()


async def _wait_or_stop(stop_event: asyncio.Event, seconds: float) -> None:
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=seconds)
    except asyncio.TimeoutError:
        return


async def run_bot_supervisor(
    *,
    poll_seconds: float = DEFAULT_CONNECTIVITY_POLL_SECONDS,
    stop_event: asyncio.Event | None = None,
    max_cycles: int | None = None,
) -> None:
    """Start or stop Telegram polling according to the admin connectivity switch."""
    init_db()
    event = stop_event or asyncio.Event()
    application = None
    cycles = 0

    while not event.is_set():
        cycles += 1
        enabled = telegram_connectivity_enabled()

        if enabled and application is None:
            try:
                application = initialize_bot()
                await start_polling_application(application)
                logger.info("telegram_polling_started")
            except Exception as exc:
                logger.error("telegram_polling_start_failed", error=str(exc))
                if application is not None:
                    try:
                        await stop_polling_application(application)
                    except Exception as stop_exc:
                        logger.warning(
                            "telegram_polling_cleanup_failed",
                            error=str(stop_exc),
                        )
                application = None
        elif not enabled and application is not None:
            logger.info("telegram_connectivity_disabled_stopping_polling")
            await stop_polling_application(application)
            application = None
        elif not enabled:
            logger.info("telegram_connectivity_disabled_idle")

        if max_cycles is not None and cycles >= max_cycles:
            break

        await _wait_or_stop(event, poll_seconds)

    if application is not None:
        await stop_polling_application(application)
        logger.info("telegram_polling_stopped")


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
        logger.info("=" * 60)
        logger.info("Price Tracker Telegram Bot Supervisor Starting")
        logger.info("=" * 60)

        stop_event = asyncio.Event()

        def signal_handler(sig, frame):
            logger.info("Received shutdown signal", signal=sig)
            stop_event.set()

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        asyncio.run(run_bot_supervisor(stop_event=stop_event))
    except Exception as exc:
        logger.error("Fatal error during bot startup", error=str(exc))
        sys.exit(1)


if __name__ == "__main__":
    main()
