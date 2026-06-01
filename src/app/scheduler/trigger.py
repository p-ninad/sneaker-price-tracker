"""Manual scan trigger for operational debugging."""

import asyncio

from app.collectors.base import CollectorRegistry
from app.collectors.myntra import MyntraCollector
from app.database.db import init_db
from app.scheduler.jobs import ScanScheduler
from app.utils.logger import get_logger, setup_logging


logger = get_logger(__name__)


def _build_scheduler() -> ScanScheduler:
    """Create scheduler with default collector registry."""
    registry = CollectorRegistry()
    registry.register(MyntraCollector())
    return ScanScheduler(registry)


def main() -> None:
    """Run a one-off watchlist scan and dispatch pending alerts."""
    setup_logging()
    logger.info("Starting manual watchlist scan trigger")
    init_db()

    scheduler = _build_scheduler()
    asyncio.run(scheduler._async_watchlist_scan())

    logger.info("Manual watchlist scan trigger completed")


if __name__ == "__main__":
    main()
