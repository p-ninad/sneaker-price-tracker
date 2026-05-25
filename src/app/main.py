"""Main application entry point."""

import signal
import sys
import time
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

    # Ensure logging is available immediately so exception handling can log failures
    try:
        setup_logging()
        if logger is None:
            logger = get_logger(__name__)
    except Exception:
        # If logging setup itself fails, fallback to printing to stderr
        print("Failed to initialize logging", file=sys.stderr)

    try:
        # Initialize app (may reconfigure logging and set the module logger)
        collector_registry, scheduler = initialize_app()

        logger.info("=" * 60)
        logger.info("Price Tracker Starting")
        logger.info("=" * 60)

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
            time.sleep(1)

    except Exception as e:
        logger.error("Fatal error during startup", error=str(e))
        sys.exit(1)


if __name__ == "__main__":
    main()
