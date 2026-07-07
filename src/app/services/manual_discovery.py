"""Manual dashboard-triggered discovery scans."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Iterable

from app.collectors.myntra import MyntraCollector
from app.database.db import get_session
from app.database.models import Product
from app.database.repository import (
    ManualDiscoveryResultRepository,
    ManualDiscoveryScanRepository,
    PlatformRepository,
    ProductIgnoreRepository,
)
from app.notifier.telegram import NotificationService
from app.services.brand_monitor import BrandMonitorService
from app.utils.logger import get_logger
from app.utils.url_parser import extract_product_id_from_url

logger = get_logger(__name__)


class ManualDiscoveryService:
    """Run filtered product discovery from dashboard input."""

    DEFAULT_PLATFORM = "myntra"

    @staticmethod
    def normalize_values(values: Iterable[str] | None) -> list[str]:
        """Return de-duplicated non-empty values."""
        normalized: list[str] = []
        for value in values or []:
            cleaned = str(value).strip()
            if cleaned and cleaned not in normalized:
                normalized.append(cleaned)
        return normalized

    @staticmethod
    def serialize_values(values: Iterable[str]) -> str:
        """Serialize filter values for database storage."""
        return json.dumps(ManualDiscoveryService.normalize_values(values))

    @staticmethod
    def read_values(value: str | None) -> list[str]:
        """Deserialize a stored filter list."""
        if not value:
            return []
        try:
            parsed = json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return []
        if not isinstance(parsed, list):
            return []
        return ManualDiscoveryService.normalize_values(str(item) for item in parsed)

    @staticmethod
    def _collector_for_platform(platform: str):
        cleaned_platform = str(platform or "").strip().lower()
        if cleaned_platform == "myntra":
            return MyntraCollector()
        raise ValueError(f"No collector registered for {cleaned_platform or 'unknown platform'}")

    @staticmethod
    def _match_product(product_data, brands: list[str], sizes: list[str]) -> tuple[str | None, list[str]]:
        for brand in brands:
            monitor = SimpleNamespace(
                brand=brand,
                query_terms=None,
                size_scope=json.dumps(sizes),
                min_discount_percentage=None,
                max_price=None,
                require_in_stock=True,
            )
            matches, matched_sizes = BrandMonitorService.product_matches_monitor(
                monitor,
                product_data,
            )
            if matches:
                return brand, matched_sizes
        return None, []

    @staticmethod
    async def run_scan(scan_id: int) -> None:
        """Run one persisted manual discovery scan and append results as they match."""
        session = get_session()
        products_found = 0
        products_matched = 0
        errors: list[str] = []
        new_product_messages: list[dict[str, object]] = []

        try:
            scan = ManualDiscoveryScanRepository.get(session, scan_id)
            if scan is None:
                logger.error("manual_discovery_scan_missing", scan_id=scan_id)
                return

            brands = ManualDiscoveryService.read_values(scan.brand_filters)
            sizes = ManualDiscoveryService.read_values(scan.size_filters)
            collector = ManualDiscoveryService._collector_for_platform(scan.platform)
            platform = PlatformRepository.get_by_name(session, collector.platform_name)

            seen_keys: set[str] = set()
            for brand in brands:
                query = f"{brand} sneakers"
                response = await collector.discover_products(query=query, limit=50)
                products_found += response.products_count
                if not response.success:
                    errors.append(response.error_message or f"{brand}: discovery failed")
                    continue

                for product_data in response.products:
                    platform_product_id = (
                        product_data.platform_product_id
                        or extract_product_id_from_url(product_data.product_url)
                        or product_data.product_url
                    )
                    if not platform_product_id or platform_product_id in seen_keys:
                        continue
                    seen_keys.add(platform_product_id)

                    if platform is not None and ProductIgnoreRepository.is_ignored(
                        session,
                        platform.id,
                        platform_product_id,
                    ):
                        continue

                    matched_brand, matched_sizes = ManualDiscoveryService._match_product(
                        product_data,
                        brands,
                        sizes,
                    )
                    if not matched_brand:
                        continue

                    product = BrandMonitorService.upsert_scanned_product(
                        session,
                        platform_name=collector.platform_name,
                        platform_base_url=collector.base_url,
                        product_data=product_data,
                    )
                    if ProductIgnoreRepository.is_ignored(
                        session,
                        product.platform_id,
                        product.platform_product_id,
                    ):
                        continue

                    ManualDiscoveryResultRepository.create(
                        session,
                        scan_id=scan.id,
                        product_id=product.id,
                        matched_brand=matched_brand,
                        matched_sizes=json.dumps(matched_sizes) if matched_sizes else None,
                        current_price=BrandMonitorService.current_price(product),
                        discount_percentage=product.discount_percentage,
                    )
                    products_matched += 1
                    new_product_messages.append(
                        ManualDiscoveryService.product_message(product, matched_sizes)
                    )

            ManualDiscoveryScanRepository.mark_complete(
                session,
                scan,
                status="success" if not errors else "partial",
                products_found=products_found,
                products_matched=products_matched,
                errors=json.dumps(errors) if errors else None,
            )

            chat_id = scan.owner.telegram_chat_id if scan.owner else None
            if chat_id:
                await NotificationService().send_brand_monitor_update(
                    chat_id=chat_id,
                    monitor_title=f"Manual scan: {', '.join(brands)}",
                    platform=scan.platform,
                    query=", ".join(brands),
                    products_found=products_found,
                    products_matched=products_matched,
                    new_products=new_product_messages,
                    errors=errors,
                    session=session,
                )
        except Exception as exc:
            logger.exception("manual_discovery_scan_failed", scan_id=scan_id, error=str(exc))
            scan = ManualDiscoveryScanRepository.get(session, scan_id)
            if scan is not None:
                ManualDiscoveryScanRepository.mark_complete(
                    session,
                    scan,
                    status="failed",
                    products_found=products_found,
                    products_matched=products_matched,
                    errors=json.dumps(errors + [str(exc)]),
                )
        finally:
            session.close()

    @staticmethod
    def run_scan_sync(scan_id: int) -> None:
        """Synchronous wrapper used by dashboard background threads."""
        asyncio.run(ManualDiscoveryService.run_scan(scan_id))

    @staticmethod
    def product_message(product: Product, matched_sizes: list[str]) -> dict[str, object]:
        """Return a Telegram-friendly product summary."""
        return {
            "title": product.title,
            "brand": product.brand,
            "model_name": product.model_name,
            "url": product.product_url,
            "current_price": BrandMonitorService.current_price(product),
            "discount_percentage": product.discount_percentage,
            "matched_sizes": matched_sizes,
        }

