"""Scheduler integration with tracking service and telegram notifier."""

import asyncio
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.config import settings
from app.database.db import get_session
from app.database.repository import PlatformRepository
from app.collectors.registry import CollectorRegistry
from app.services.tracking import TrackingService
from app.notifier.telegram import NotificationService
from app.utils.logger import get_logger

logger = get_logger(__name__)


class IntegratedScheduler:
    """Scheduler that coordinates collectors, tracking, and notifications."""

    def __init__(self):
        """Initialize the integrated scheduler."""
        self.scheduler = BackgroundScheduler()
        self.tracking_service = TrackingService()
        self.notification_service = NotificationService()
        self.collector_registry = CollectorRegistry()

    def start(self):
        """Start the scheduler with all jobs."""
        if not settings.enable_scheduler:
            logger.warning("scheduler_disabled")
            return

        # Register catalog scan (discovers new products)
        self.scheduler.add_job(
            self._scan_catalog,
            trigger=IntervalTrigger(hours=settings.catalog_scan_interval_hours),
            id="catalog_scan",
            name="Catalog Scan",
            replace_existing=True,
        )

        # Register watchlist scan (checks tracked products)
        self.scheduler.add_job(
            self._scan_watchlist,
            trigger=IntervalTrigger(hours=settings.watchlist_scan_interval_hours),
            id="watchlist_scan",
            name="Watchlist Scan",
            replace_existing=True,
        )

        # Register notification processor
        self.scheduler.add_job(
            self._process_notifications,
            trigger=IntervalTrigger(minutes=5),  # Check every 5 minutes
            id="notification_processor",
            name="Notification Processor",
            replace_existing=True,
        )

        self.scheduler.start()
        logger.info("scheduler_started")

    def stop(self):
        """Stop the scheduler."""
        if self.scheduler.running:
            self.scheduler.shutdown()
            logger.info("scheduler_stopped")

    def _scan_catalog(self):
        """Scan catalog for new products."""
        try:
            session = get_session()
            logger.info("catalog_scan_started")

            for platform_name in settings.enabled_platforms_list:
                try:
                    platform = PlatformRepository.get_by_name(session, platform_name)
                    if not platform or not platform.is_active:
                        continue

                    collector = self.collector_registry.get(platform_name)
                    if not collector:
                        logger.warning(
                            "collector_not_found",
                            platform=platform_name,
                        )
                        continue

                    # Run collector (would use asyncio in real implementation)
                    # response = await collector.discover_products(query="Nike", limit=50)

                    logger.debug(
                        "catalog_scan_platform_complete",
                        platform=platform_name,
                    )

                except Exception as e:
                    logger.error(
                        "catalog_scan_platform_failed",
                        platform=platform_name,
                        error=str(e),
                    )

            logger.info("catalog_scan_completed")

        except Exception as e:
            logger.error("catalog_scan_error", error=str(e))
        finally:
            session.close()

    def _scan_watchlist(self):
        """Scan watchlist products for changes."""
        try:
            session = get_session()
            logger.info("watchlist_scan_started")

            # Get products from watchlist
            # products = WatchlistRepository.get_all(session)

            # For each product:
            #   - Fetch current details from collector
            #   - Analyze changes using TrackingService
            #   - Create alerts if needed

            logger.info("watchlist_scan_completed")

        except Exception as e:
            logger.error("watchlist_scan_error", error=str(e))
        finally:
            session.close()

    def _process_notifications(self):
        """Process unnotified alerts and send them."""
        try:
            session = get_session()

            # Run notification processing
            result = asyncio.run(
                self.notification_service.process_unnotified_alerts(session)
            )

            logger.info(
                "notifications_processed",
                sent=result.get("sent_count", 0),
                failed=result.get("failed_count", 0),
            )

        except Exception as e:
            logger.error("notification_processing_error", error=str(e))
        finally:
            session.close()


# Example: Complete flow from discovery to notification
def example_complete_flow():
    """Example of complete flow: discover → track → notify."""

    from app.collectors.base import ProductData
    from app.database.repository import (
        ProductRepository,
        PlatformRepository,
        AlertRepository,
    )

    session = get_session()

    try:
        # 1. DISCOVER: Collector finds a product
        print("\n=== 1. DISCOVERY ===")
        platform = PlatformRepository.get_by_name(session, "myntra")
        if not platform:
            platform = PlatformRepository.create(
                session,
                name="myntra",
                display_name="Myntra",
                base_url="https://myntra.com",
            )
        print(f"✓ Platform: {platform.display_name}")

        product_data = ProductData(
            platform_product_id="98765",
            product_url="https://myntra.com/shoes/98765",
            title="Adidas Ultraboost 22 Men Running",
            brand="Adidas",
            model_name="Ultraboost 22",
            listed_price=12000.0,
            discounted_price=9999.0,
            currency="INR",
            discount_percentage=16.7,
            in_stock=True,
            sizes_available='["6", "7", "8", "9", "10", "11"]',
            image_url="https://example.com/adidas.jpg",
            sku="ADIDAS-UB22",
        )
        print(f"✓ Product discovered: {product_data.brand} {product_data.model_name}")

        # 2. STORE: Save product to database
        print("\n=== 2. STORAGE ===")
        product = ProductRepository.create_or_update(
            session,
            platform_id=platform.id,
            product_url=product_data.product_url,
            platform_product_id=product_data.platform_product_id,
            brand=product_data.brand,
            model_name=product_data.model_name,
            title=product_data.title,
            listed_price=product_data.listed_price,
            discounted_price=product_data.discounted_price,
            in_stock=product_data.in_stock,
            sizes_available=product_data.sizes_available,
            image_url=product_data.image_url,
            sku=product_data.sku,
        )
        print(f"✓ Product stored: ID {product.id}")

        # 3. ANALYZE: Check for changes
        print("\n=== 3. CHANGE ANALYSIS ===")
        tracking_service = TrackingService()

        analysis = tracking_service.analyze_product_update(
            session,
            product=product,
            new_listed_price=product_data.listed_price,
            new_discounted_price=product_data.discounted_price,
            new_discount_percentage=product_data.discount_percentage,
            new_in_stock=product_data.in_stock,
            new_sizes_available=product_data.sizes_available,
        )
        print(f"✓ Changes detected: {[c.value for c in analysis.change_types]}")

        # 4. ALERT: Create alerts if needed
        print("\n=== 4. ALERT GENERATION ===")
        if analysis.has_changes():
            alerts = tracking_service.create_alerts_from_analysis(session, analysis)
            print(f"✓ Alerts created: {len(alerts)}")
            for alert in alerts:
                print(f"  - {alert.alert_type}: {alert.message[:50]}...")
        else:
            print("✓ No significant changes, no alerts created")

        # 5. RECORD: Save historical data
        print("\n=== 5. HISTORICAL TRACKING ===")
        tracking_service.record_price_snapshot(
            session,
            product,
            listed_price=product_data.listed_price,
            discounted_price=product_data.discounted_price,
            discount_percentage=product_data.discount_percentage,
        )
        tracking_service.record_stock_snapshot(
            session,
            product,
            in_stock=product_data.in_stock,
            sizes_available=product_data.sizes_available,
        )
        print("✓ Price and stock snapshots recorded")

        # 6. NOTIFY: Prepare notifications
        print("\n=== 6. NOTIFICATION PREPARATION ===")
        unnotified = AlertRepository.get_unnotified(session, limit=5)
        print(f"✓ Unnotified alerts ready: {len(unnotified)}")

        # 7. TELEGRAM: Would send via TelegramNotifier
        print("\n=== 7. TELEGRAM NOTIFICATION ===")
        if unnotified:
            from app.notifier.telegram import TelegramNotifier

            try:
                notifier = TelegramNotifier()
                print("✓ TelegramNotifier initialized")
                print(f"  - Would send {len(unnotified)} alerts to Telegram")
                print("  - Note: Actual sending requires TELEGRAM_BOT_TOKEN in .env")
            except ValueError as e:
                print(f"⚠ TelegramNotifier: {e}")
        else:
            print("  - No alerts to send")

        print("\n✅ Complete flow example finished!")

    finally:
        session.close()


if __name__ == "__main__":
    example_complete_flow()
