import json
from unittest.mock import AsyncMock

from app import config as app_config
from app.collectors.base import CollectorRegistry, ProductData
from app.database.repository import (
    AlertRepository,
    PlatformRepository,
    PriceSnapshotRepository,
    ProductRepository,
    StockSnapshotRepository,
)
from app.scheduler.jobs import ScanScheduler
from app.services.wishlist import WishlistService


class FakeCollector:
    def __init__(self, platform_name: str, product_data: ProductData):
        self.platform_name = platform_name
        self.base_url = "https://example.com"
        self._product_data = product_data

    async def fetch_product_details(self, product_id: str):
        return self._product_data


class TestWatchlistScan:
    async def _run_scan(self, test_session, collector):
        scheduler = ScanScheduler(CollectorRegistry())
        scheduler.registry.register(collector)
        await scheduler._async_watchlist_scan()

    def test_watchlist_scan_records_snapshots_and_alerts(self, test_session, test_db_url):
        app_config.settings.database_url = test_db_url

        platform = PlatformRepository.create(
            test_session,
            name="myntra",
            display_name="Myntra",
            base_url="https://www.myntra.com",
        )

        existing = ProductRepository.create_or_update(
            test_session,
            platform_id=platform.id,
            product_url="https://www.myntra.com/p/old",
            platform_product_id="old-1",
            brand="Nike",
            model_name="Air Max 90",
            title="Nike Air Max 90",
            listed_price=10000.0,
            discounted_price=8000.0,
            in_stock=True,
            sizes_available='["11"]',
        )

        WishlistService.add_from_url(
            test_session,
            url="https://www.myntra.com/p/old",
            brand="Nike",
            model_name="Air Max 90",
            title="Nike Air Max 90",
            platforms_to_track=["myntra"],
            size_scope=["11", "11.5", "12", "12.5"],
        )

        collector = FakeCollector(
            "myntra",
            ProductData(
                platform_product_id="old-1",
                product_url="https://www.myntra.com/p/old",
                title="Nike Air Max 90",
                brand="Nike",
                model_name="Air Max 90",
                listed_price=10000.0,
                discounted_price=7000.0,
                currency="INR",
                discount_percentage=30.0,
                in_stock=True,
                sizes_available=["11", "12"],
                image_url="https://example.com/airmax.jpg",
                description="Updated product",
                sku="old-1",
            ),
        )

        scheduler = ScanScheduler(CollectorRegistry())
        scheduler.registry.register(collector)
        scheduler.notification_service.send_scan_summary = AsyncMock(return_value=True)
        scheduler.notification_service.process_unnotified_alerts = AsyncMock(
            return_value={"sent_count": 0, "failed_count": 0}
        )

        import asyncio

        asyncio.run(scheduler._async_watchlist_scan())

        updated = ProductRepository.get_active_by_platform(test_session, platform.id)
        assert len(updated) == 1
        assert updated[0].discounted_price == 7000.0

        alerts = AlertRepository.get_unnotified(test_session)
        assert len(alerts) == 1
        assert alerts[0].alert_type == "price_drop"

        price_snapshots = PriceSnapshotRepository.get_last_n(test_session, existing.id, n=1)
        stock_snapshots = StockSnapshotRepository.get_last_n(test_session, existing.id, n=1)
        assert len(price_snapshots) == 1
        assert len(stock_snapshots) == 1

        assert json.loads(stock_snapshots[0].sizes_available) == ["11", "12"]

    def test_watchlist_scan_dispatches_unnotified_alerts(self, test_session, test_db_url):
        app_config.settings.database_url = test_db_url

        platform = PlatformRepository.create(
            test_session,
            name="myntra",
            display_name="Myntra",
            base_url="https://www.myntra.com",
        )

        ProductRepository.create_or_update(
            test_session,
            platform_id=platform.id,
            product_url="https://www.myntra.com/p/dispatch",
            platform_product_id="dispatch-1",
            brand="Nike",
            model_name="Air Max 90",
            title="Nike Air Max 90",
            listed_price=10000.0,
            discounted_price=8000.0,
            in_stock=True,
            sizes_available='["11"]',
        )

        WishlistService.add_from_url(
            test_session,
            url="https://www.myntra.com/p/dispatch",
            brand="Nike",
            model_name="Air Max 90",
            title="Nike Air Max 90",
            platforms_to_track=["myntra"],
            size_scope=["11", "11.5", "12", "12.5"],
        )

        collector = FakeCollector(
            "myntra",
            ProductData(
                platform_product_id="dispatch-1",
                product_url="https://www.myntra.com/p/dispatch",
                title="Nike Air Max 90",
                brand="Nike",
                model_name="Air Max 90",
                listed_price=10000.0,
                discounted_price=7000.0,
                currency="INR",
                discount_percentage=30.0,
                in_stock=True,
                sizes_available=["11", "12"],
            ),
        )

        scheduler = ScanScheduler(CollectorRegistry())
        scheduler.registry.register(collector)
        scheduler.notification_service.send_scan_summary = AsyncMock(return_value=True)
        scheduler.notification_service.process_unnotified_alerts = AsyncMock(
            return_value={"sent_count": 1, "failed_count": 0}
        )

        import asyncio

        asyncio.run(scheduler._async_watchlist_scan())

        scheduler.notification_service.process_unnotified_alerts.assert_awaited_once()

    def test_watchlist_scan_skips_products_outside_size_scope(self, test_session, test_db_url):
        app_config.settings.database_url = test_db_url

        platform = PlatformRepository.create(
            test_session,
            name="myntra",
            display_name="Myntra",
            base_url="https://www.myntra.com",
        )

        ProductRepository.create_or_update(
            test_session,
            platform_id=platform.id,
            product_url="https://www.myntra.com/p/size-check",
            platform_product_id="size-check",
            brand="Nike",
            model_name="Air Max 90",
            title="Nike Air Max 90",
            listed_price=10000.0,
            discounted_price=8000.0,
            in_stock=True,
            sizes_available='["11"]',
        )

        WishlistService.add_from_url(
            test_session,
            url="https://www.myntra.com/p/size-check",
            brand="Nike",
            model_name="Air Max 90",
            title="Nike Air Max 90",
            platforms_to_track=["myntra"],
            size_scope=["12.5"],
        )

        collector = FakeCollector(
            "myntra",
            ProductData(
                platform_product_id="size-check",
                product_url="https://www.myntra.com/p/size-check",
                title="Nike Air Max 90",
                brand="Nike",
                model_name="Air Max 90",
                listed_price=10000.0,
                discounted_price=7000.0,
                currency="INR",
                discount_percentage=30.0,
                in_stock=True,
                sizes_available=["11"],
            ),
        )

        scheduler = ScanScheduler(CollectorRegistry())
        scheduler.registry.register(collector)

        import asyncio

        asyncio.run(scheduler._async_watchlist_scan())

        product = ProductRepository.get_active_by_platform(test_session, platform.id)[0]
        price_snapshots = PriceSnapshotRepository.get_last_n(test_session, product.id, n=1)
        assert len(price_snapshots) == 0
