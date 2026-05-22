"""Main application entry point."""

import asyncio
import signal
import sys
from app.config import settings
from app.utils.logger import setup_logging, get_logger
from app.database.db import init_db
from app.collectors.base import CollectorRegistry
from app.collectors.myntra import MyntraCollector
from app.scheduler.jobs import ScanScheduler

logger = None


def initialize_app():
    """Initialize application components."""
    global logger

    # Setup logging
    setup_logging()
    logger = get_logger(__name__)

    logger.info(
        "Initializing Price Tracker",
        env=settings.env,
        log_level=settings.log_level,
    )

    # Initialize database
    init_db()
    logger.info("Database initialized")

    # Initialize collectors
    collector_registry = CollectorRegistry()
    collector_registry.register(MyntraCollector())
    logger.info(f"Registered {len(collector_registry.collectors)} collectors")

    # Initialize scheduler
    scheduler = ScanScheduler(collector_registry)

    return collector_registry, scheduler


def main():
    """Main application entry point."""
    global logger

    try:
        logger.info("=" * 60)
        logger.info("Price Tracker Starting")
        logger.info("=" * 60)

        collector_registry, scheduler = initialize_app()

        # Start scheduler
        scheduler.start()

        # Setup signal handlers for graceful shutdown
        def signal_handler(sig, frame):
            logger.info("Received shutdown signal")
            scheduler.stop()
            sys.exit(0)

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        logger.info("Application running. Press Ctrl+C to exit.")

        # Keep application running
        while True:
            asyncio.sleep(1)

    except Exception as e:
        logger.error("Fatal error during startup", error=str(e))
        sys.exit(1)


if __name__ == "__main__":
    main()
