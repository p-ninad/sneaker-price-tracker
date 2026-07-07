import asyncio

from unittest.mock import AsyncMock

from app import config as app_config
from app.auth.passwords import hash_password
from app.collectors.base import CollectorRegistry, CollectorResponse, ProductData
from app.database.models import (
    BrandMonitorScan,
    BrandMonitorScanResult,
    BrandMonitorSeenProduct,
)
from app.database.repository import (
    BrandMonitorRepository,
    ProductRepository,
    UserRepository,
)
from app.scheduler.jobs import ScanScheduler
from app.services.brand_monitor import BrandMonitorService


class FakeDiscoveryCollector:
    def __init__(self, products: list[ProductData]):
        self.platform_name = "myntra"
        self.base_url = "https://www.myntra.com"
        self.products = products
        self.queries: list[tuple[str, int]] = []

    async def discover_products(self, query: str = "sneaker", limit: int = 100):
        self.queries.append((query, limit))
        return CollectorResponse(success=True, products=self.products[:limit])


def _product(product_id: str, title: str, sizes: list[str]) -> ProductData:
    return ProductData(
        platform_product_id=product_id,
        product_url=f"https://www.myntra.com/p/{product_id}",
        title=title,
        brand="Adidas",
        model_name=title,
        listed_price=10000.0,
        discounted_price=7000.0,
        discount_percentage=30.0,
        in_stock=True,
        sizes_available=sizes,
    )


def test_brand_monitor_matching_uses_brand_terms_sizes_and_discount(test_session):
    user = UserRepository.create(
        test_session,
        username="monitor_match_user",
        password_hash=hash_password("secret", iterations=1000),
        telegram_user_id="700",
        telegram_chat_id="701",
    )
    monitor = BrandMonitorService.add_monitor(
        test_session,
        user_id=user.id,
        platform="myntra",
        brand="Adidas Originals",
        query_terms=["sneakers"],
        size_scope=["11"],
        min_discount_percentage=20,
    )

    matches, matched_sizes = BrandMonitorService.product_matches_monitor(
        monitor,
        ProductData(
            platform_product_id="samba-1",
            product_url="https://www.myntra.com/p/samba-1",
            title="Adidas Originals Samba Sneaker",
            brand="Adidas",
            model_name="Originals Samba",
            listed_price=10000.0,
            discounted_price=7500.0,
            discount_percentage=25.0,
            sizes_available=["UK 11", "UK 12"],
        ),
    )

    assert matches is True
    assert matched_sizes == ["UK 11"]


def test_brand_monitor_scan_records_delta_between_runs(test_session, test_db_url):
    app_config.settings.database_url = test_db_url

    from app.database import db as app_db

    app_db._ENGINE = None
    app_db._SESSION_FACTORY = None

    user = UserRepository.create(
        test_session,
        username="monitor_scan_user",
        password_hash=hash_password("secret", iterations=1000),
        telegram_user_id="710",
        telegram_chat_id="711",
    )
    monitor = BrandMonitorService.add_monitor(
        test_session,
        user_id=user.id,
        platform="myntra",
        brand="Adidas Originals",
        query_terms=["sneakers"],
        size_scope=["10", "11"],
        min_discount_percentage=20,
    )

    first_product = _product("samba-1", "Adidas Originals Samba Sneakers", ["10"])
    collector = FakeDiscoveryCollector(
        [
            first_product,
            ProductData(
                platform_product_id="nike-1",
                product_url="https://www.myntra.com/p/nike-1",
                title="Nike Air Max Sneakers",
                brand="Nike",
                model_name="Air Max",
                listed_price=10000.0,
                discounted_price=7000.0,
                discount_percentage=30.0,
                in_stock=True,
                sizes_available=["10"],
            ),
        ]
    )
    registry = CollectorRegistry()
    registry.register(collector)
    scheduler = ScanScheduler(registry)
    scheduler.notification_service.send_brand_monitor_update = AsyncMock(return_value=True)

    asyncio.run(scheduler._async_hot_items_scan())

    scans = test_session.query(BrandMonitorScan).filter_by(monitor_id=monitor.id).all()
    results = test_session.query(BrandMonitorScanResult).filter_by(monitor_id=monitor.id).all()
    seen = test_session.query(BrandMonitorSeenProduct).filter_by(monitor_id=monitor.id).all()

    assert len(scans) == 1
    assert scans[0].products_found == 2
    assert scans[0].products_matched == 1
    assert scans[0].new_products == 1
    assert len(results) == 1
    assert results[0].is_new is True
    assert len(seen) == 1
    assert ProductRepository.get_by_id(test_session, results[0].product_id).discount_percentage == 30.0
    scheduler.notification_service.send_brand_monitor_update.assert_awaited_once()
    first_message = scheduler.notification_service.send_brand_monitor_update.await_args.kwargs
    assert first_message["chat_id"] == "711"
    assert len(first_message["new_products"]) == 1

    collector.products = [
        first_product,
        _product("gazelle-1", "Adidas Originals Gazelle Sneakers", ["11"]),
    ]
    asyncio.run(scheduler._async_hot_items_scan())

    all_scans = test_session.query(BrandMonitorScan).filter_by(monitor_id=monitor.id).all()
    latest_scan = sorted(all_scans, key=lambda scan: scan.id)[-1]
    latest_results = (
        test_session.query(BrandMonitorScanResult)
        .filter_by(monitor_id=monitor.id, scan_id=latest_scan.id)
        .all()
    )
    latest_new_results = [result for result in latest_results if result.is_new]

    assert latest_scan.products_found == 2
    assert latest_scan.products_matched == 2
    assert latest_scan.new_products == 1
    assert len(latest_results) == 2
    assert len(latest_new_results) == 1
    assert test_session.query(BrandMonitorSeenProduct).filter_by(monitor_id=monitor.id).count() == 2
    assert scheduler.notification_service.send_brand_monitor_update.await_count == 2
    second_message = scheduler.notification_service.send_brand_monitor_update.await_args.kwargs
    assert len(second_message["new_products"]) == 1
    assert second_message["new_products"][0]["title"] == "Adidas Originals Gazelle Sneakers"


def test_brand_monitor_state_helpers(test_session):
    user = UserRepository.create(
        test_session,
        username="monitor_state_user",
        password_hash=hash_password("secret", iterations=1000),
        telegram_user_id="720",
        telegram_chat_id="721",
    )
    monitor = BrandMonitorService.add_monitor(
        test_session,
        user_id=user.id,
        platform="myntra",
        brand="Adidas",
        query_terms=["sneakers"],
    )

    assert BrandMonitorRepository.count_active_for_user(test_session, user.id) == 1
    BrandMonitorRepository.set_active(test_session, monitor, False)
    assert BrandMonitorRepository.count_active_for_user(test_session, user.id) == 0
