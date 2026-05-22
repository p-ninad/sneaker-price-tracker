"""APScheduler-based job scheduling for scans."""

import asyncio
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from datetime import datetime
from app.config import settings
from app.utils.logger import get_logger
from app.database.db import get_session
from app.database.repository import PlatformRepository, ScanJobRepository
from app.collectors.base import CollectorRegistry

logger = get_logger(__name__)


class ScanScheduler:
    """Manages background scan jobs using APScheduler."""

    def __init__(self, collector_registry: CollectorRegistry):
        """Initialize scheduler.

        Args:
            collector_registry: Registry of available collectors
        """
        self.registry = collector_registry
        self.scheduler = BackgroundScheduler()

    def start(self) -> None:
        """Start the scheduler."""
        if not settings.enable_scheduler:
            logger.info("Scheduler disabled via config")
            return

        logger.info("Starting scheduler")

        # Register jobs
        self._register_catalog_scan()
        self._register_watchlist_scan()
        self._register_hot_items_scan()

        # Start scheduler
        self.scheduler.start()
        logger.info("Scheduler started")

    def stop(self) -> None:
        """Stop the scheduler."""
        if self.scheduler.running:
            self.scheduler.shutdown()
            logger.info("Scheduler stopped")

    def _register_catalog_scan(self) -> None:
        """Register general catalog scan job."""
        self.scheduler.add_job(
            self._run_catalog_scan,
            trigger=IntervalTrigger(hours=settings.catalog_scan_interval_hours),
            id="catalog_scan",
            name="Catalog Scan",
            replace_existing=True,
            max_instances=1,
        )
        logger.info(
            f"Registered catalog scan (every {settings.catalog_scan_interval_hours}h)"
        )

    def _register_watchlist_scan(self) -> None:
        """Register watchlist scan job."""
        self.scheduler.add_job(
            self._run_watchlist_scan,
            trigger=IntervalTrigger(hours=settings.watchlist_scan_interval_hours),
            id="watchlist_scan",
            name="Watchlist Scan",
            replace_existing=True,
            max_instances=1,
        )
        logger.info(
            f"Registered watchlist scan (every {settings.watchlist_scan_interval_hours}h)"
        )

    def _register_hot_items_scan(self) -> None:
        """Register hot items scan job."""
        self.scheduler.add_job(
            self._run_hot_items_scan,
            trigger=IntervalTrigger(minutes=settings.hot_items_scan_interval_minutes),
            id="hot_items_scan",
            name="Hot Items Scan",
            replace_existing=True,
            max_instances=1,
        )
        logger.info(
            f"Registered hot items scan (every {settings.hot_items_scan_interval_minutes}m)"
        )

    def _run_catalog_scan(self) -> None:
        """Execute catalog scan for all platforms."""
        asyncio.run(self._async_catalog_scan())

    async def _async_catalog_scan(self) -> None:
        """Async catalog scan implementation."""
        logger.info("Starting catalog scan")
        session = get_session()

        try:
            for collector in self.registry.get_enabled():
                await self._scan_platform(
                    collector,
                    scan_type="catalog",
                    session=session,
                )
        finally:
            session.close()

    def _run_watchlist_scan(self) -> None:
        """Execute watchlist scan."""
        asyncio.run(self._async_watchlist_scan())

    async def _async_watchlist_scan(self) -> None:
        """Async watchlist scan implementation."""
        logger.info("Starting watchlist scan")
        session = get_session()

        try:
            # TODO: Implement watchlist-specific scan
            logger.info("Watchlist scan not yet implemented")
        finally:
            session.close()

    def _run_hot_items_scan(self) -> None:
        """Execute hot items scan."""
        asyncio.run(self._async_hot_items_scan())

    async def _async_hot_items_scan(self) -> None:
        """Async hot items scan implementation."""
        logger.info("Starting hot items scan")
        session = get_session()

        try:
            # TODO: Implement hot items-specific scan
            logger.info("Hot items scan not yet implemented")
        finally:
            session.close()

    async def _scan_platform(
        self,
        collector,
        scan_type: str = "catalog",
        session = None,
    ) -> None:
        """Scan a single platform.

        Args:
            collector: Collector instance
            scan_type: Type of scan (catalog, watchlist, hot_items)
            session: Database session
        """
        if session is None:
            session = get_session()

        logger.info(
            "Scanning platform",
            platform=collector.platform_name,
            scan_type=scan_type,
        )

        try:
            # Get or create platform record
            platform = PlatformRepository.get_by_name(session, collector.platform_name)
            if not platform:
                # Register platform if not exists
                # TODO: Get display_name from collector
                platform = PlatformRepository.create(
                    session,
                    name=collector.platform_name,
                    display_name=collector.platform_name.title(),
                    base_url=collector.base_url,
                )

            # Create scan job record
            job = ScanJobRepository.create(
                session,
                platform_id=platform.id,
                scan_type=scan_type,
            )

            # Run discovery
            response = await collector.discover_products()

            if response.success:
                logger.info(
                    "Platform scan completed",
                    platform=collector.platform_name,
                    products_found=response.products_count,
                    scan_type=scan_type,
                )
                ScanJobRepository.mark_complete(
                    session,
                    job,
                    status="success",
                    products_found=response.products_count,
                    products_updated=response.products_count,  # TODO: actual update count
                )
            else:
                logger.error(
                    "Platform scan failed",
                    platform=collector.platform_name,
                    error=response.error_message,
                    scan_type=scan_type,
                )
                ScanJobRepository.mark_complete(
                    session,
                    job,
                    status="failed",
                    errors=response.error_message,
                )

        except Exception as e:
            logger.error(
                "Unexpected error during platform scan",
                platform=collector.platform_name,
                error=str(e),
                scan_type=scan_type,
            )
