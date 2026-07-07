"""APScheduler-based job scheduling for scans."""

import asyncio
import json
import re
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from datetime import datetime
from app.config import settings
from app.utils.logger import get_logger
from app.database.db import get_session
from app.database.models import Product
from app.database.repository import (
    BrandMonitorRepository,
    BrandMonitorScanRepository,
    BrandMonitorScanResultRepository,
    BrandMonitorSeenProductRepository,
    PlatformRepository,
    PriceSnapshotRepository,
    ProductRepository,
    ScanJobRepository,
    StockSnapshotRepository,
)
from app.collectors.base import CollectorRegistry
from app.notifier.telegram import NotificationService
from app.services.brand_monitor import BrandMonitorService
from app.services.tracking import TrackingService
from app.services.wishlist import WishlistService
from app.utils.url_parser import extract_product_id_from_url

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
        self.notification_service = NotificationService()

    def start(self) -> None:
        """Start the scheduler."""
        if not settings.enable_scheduler:
            logger.info("Scheduler disabled via config")
            return

        logger.info("Starting scheduler")

        # Register jobs
        if settings.enable_catalog_scan:
            self._register_catalog_scan()
        else:
            logger.info("Catalog scan disabled; use dashboard manual discovery scans")
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
            next_run_time=datetime.utcnow() if settings.scan_on_startup else None,
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
            next_run_time=datetime.utcnow() if settings.scan_on_startup else None,
        )
        logger.info(
            f"Registered watchlist scan (every {settings.watchlist_scan_interval_hours}h)"
        )

    def _register_hot_items_scan(self) -> None:
        """Register hot items scan job."""
        self.scheduler.add_job(
            self._run_hot_items_scan,
            trigger=IntervalTrigger(minutes=settings.brand_monitor_scan_interval_minutes),
            id="brand_monitor_scan",
            name="Brand Monitor Scan",
            replace_existing=True,
            max_instances=1,
            next_run_time=datetime.utcnow() if settings.scan_on_startup else None,
        )
        logger.info(
            "Registered brand monitor scan "
            f"(every {settings.brand_monitor_scan_interval_minutes}m)"
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

    @staticmethod
    def _parse_sizes(sizes_available) -> list[str]:
        """Normalize size values into a list of strings."""
        if sizes_available is None:
            return []

        if isinstance(sizes_available, list):
            return [str(size).strip() for size in sizes_available if str(size).strip()]

        if isinstance(sizes_available, str):
            try:
                parsed = json.loads(sizes_available)
            except (TypeError, json.JSONDecodeError):
                return []

            if isinstance(parsed, list):
                return [str(size).strip() for size in parsed if str(size).strip()]

        return []

    @staticmethod
    def _normalize_text(value) -> str:
        """Normalize free-text identifiers for comparison."""
        return re.sub(r"\s+", " ", str(value or "").strip().lower())

    @staticmethod
    def _normalize_size_token(size_value: str) -> str:
        """Normalize size text across variants like UK12, UK 12, and 12."""
        token = str(size_value or "").strip().upper()
        if not token:
            return ""
        token = token.replace("UK", "").strip()
        token = re.sub(r"[^0-9.]", "", token)
        if not token:
            return ""
        try:
            numeric = float(token)
            if numeric.is_integer():
                return str(int(numeric))
            return f"{numeric:.1f}".rstrip("0").rstrip(".")
        except ValueError:
            return token

    @staticmethod
    def _size_scope_matches(size_scope: list[str], sizes_available) -> bool:
        """Check whether any available size is inside the configured scope."""
        if not size_scope:
            return True

        available_sizes = {
            ScanScheduler._normalize_size_token(size)
            for size in ScanScheduler._parse_sizes(sizes_available)
            if ScanScheduler._normalize_size_token(size)
        }
        if not available_sizes:
            return False

        scope_sizes = {
            ScanScheduler._normalize_size_token(size)
            for size in size_scope
            if ScanScheduler._normalize_size_token(size)
        }
        return bool(available_sizes.intersection(scope_sizes))

    @staticmethod
    def _model_tokens(value: str) -> set[str]:
        """Extract meaningful comparison tokens from model/title text."""
        noise = {
            "buy", "unisex", "men", "mens", "women", "womens",
            "shoe", "shoes", "sneaker", "sneakers", "footwear",
            "for", "the", "and", "with", "textured", "everyday",
            "casual", "lifestyle",
        }
        tokens = re.findall(r"[a-z0-9.]+", ScanScheduler._normalize_text(value))
        return {token for token in tokens if token not in noise and len(token) > 1}

    @staticmethod
    def _product_matches_wishlist(entry, product_data) -> bool:
        """Check whether fetched product metadata matches the wishlist entry."""
        expected = WishlistService._normalize_name(f"{entry.brand} {entry.model_name}")
        actual = ScanScheduler._normalize_text(f"{product_data.brand} {product_data.model_name}")
        if expected == actual:
            return True

        expected_model_tokens = ScanScheduler._model_tokens(entry.model_name or "")
        actual_model_tokens = ScanScheduler._model_tokens(
            f"{product_data.model_name or ''} {product_data.title or ''}"
        )
        if not expected_model_tokens:
            return False

        # Treat this as a match when all meaningful wishlist tokens are present in fetched text.
        return expected_model_tokens.issubset(actual_model_tokens)

    def _ensure_platform(self, session, collector) -> Product:
        """Get or create platform record for a collector."""
        platform = PlatformRepository.get_by_name(session, collector.platform_name)
        if platform:
            return platform

        return PlatformRepository.create(
            session,
            name=collector.platform_name,
            display_name=collector.platform_name.title(),
            base_url=collector.base_url,
        )

    async def _process_wishlist_product(
        self,
        session,
        entry,
        collector,
        product_data,
    ) -> dict:
        """Fetch, update, snapshot, and alert on one wishlist product."""
        size_scope = WishlistService.get_size_scope(entry)
        if not self._size_scope_matches(size_scope, product_data.sizes_available):
            logger.info(
                "Wishlist product skipped due to size scope",
                platform=collector.platform_name,
                source_url=entry.source_url,
                size_scope=size_scope,
            )
            return {"success": False, "reason": "size_scope_mismatch", "alerts_created": 0}

        platform = self._ensure_platform(session, collector)
        source_product_id = product_data.platform_product_id or extract_product_id_from_url(
            product_data.product_url or entry.source_url
        )

        if not source_product_id:
            logger.warning(
                "Skipping wishlist product without platform product id",
                platform=collector.platform_name,
                source_url=entry.source_url,
            )
            return {"success": False, "reason": "missing_product_id", "alerts_created": 0}

        existing = session.query(Product).filter(
            Product.platform_id == platform.id,
            Product.platform_product_id == source_product_id,
        ).first()

        baseline = Product(
            id=existing.id if existing else 0,
            discounted_price=existing.discounted_price if existing else None,
            in_stock=existing.in_stock if existing else False,
            sizes_available=existing.sizes_available if existing else None,
        )

        updated_product = ProductRepository.create_or_update(
            session,
            platform_id=platform.id,
            product_url=product_data.product_url or entry.source_url,
            platform_product_id=source_product_id,
            brand=product_data.brand,
            model_name=product_data.model_name,
            title=product_data.title,
            listed_price=product_data.listed_price,
            discounted_price=product_data.discounted_price,
            discount_percentage=product_data.discount_percentage,
            currency=product_data.currency,
            in_stock=product_data.in_stock,
            sizes_available=(
                json.dumps(product_data.sizes_available)
                if product_data.sizes_available is not None
                else None
            ),
            image_url=product_data.image_url,
            sku=product_data.sku,
        )

        analysis = TrackingService().analyze_product_update(
            session,
            baseline,
            new_listed_price=product_data.listed_price,
            new_discounted_price=product_data.discounted_price,
            new_discount_percentage=product_data.discount_percentage,
            new_in_stock=product_data.in_stock,
            new_sizes_available=(
                json.dumps(product_data.sizes_available)
                if product_data.sizes_available is not None
                else None
            ),
        )

        PriceSnapshotRepository.create(
            session,
            updated_product.id,
            updated_product.listed_price,
            updated_product.discounted_price,
            updated_product.discount_percentage,
            updated_product.currency,
        )
        StockSnapshotRepository.create(
            session,
            updated_product.id,
            updated_product.in_stock,
            json.dumps(product_data.sizes_available)
            if product_data.sizes_available is not None
            else None,
        )

        alerts_created = 0
        if analysis.has_changes():
            alerts = TrackingService().create_alerts_from_analysis(session, analysis)
            alerts_created = len(alerts)
            logger.info(
                "Wishlist product analysis completed",
                source_url=entry.source_url,
                platform=collector.platform_name,
                alerts_created=alerts_created,
            )
        else:
            logger.info(
                "Wishlist product unchanged",
                source_url=entry.source_url,
                platform=collector.platform_name,
            )

        return {"success": True, "alerts_created": alerts_created}

    async def _async_watchlist_scan(self) -> None:
        """Async watchlist scan implementation."""
        logger.info("Starting watchlist scan")
        session = get_session()

        entries_scanned = 0
        products_updated = 0
        alerts_created = 0
        size_skipped = 0
        mismatches = []
        errors = []

        try:
            active_entries = WishlistService.get_active(session)
            if not active_entries:
                logger.info("No active wishlist entries found")
                await self.notification_service.send_scan_summary(
                    scan_type="watchlist",
                    entries_scanned=0,
                    products_updated=0,
                    alerts_created=0,
                    mismatches=[],
                    errors=["No active wishlist entries found"],
                    session=session,
                )
                return

            scanned_keys = set()

            for entry in active_entries:
                entries_scanned += 1
                try:
                    platforms_to_track = WishlistService.get_platforms_to_track(entry)
                    source_product_id = extract_product_id_from_url(entry.source_url)

                    logger.debug(
                        "Processing wishlist entry",
                        entry_id=entry.id,
                        title=entry.title,
                        platform=entry.platform,
                        source_url=entry.source_url,
                        extracted_product_id=source_product_id,
                        platforms_to_track=platforms_to_track,
                    )

                    if entry.platform in platforms_to_track and source_product_id:
                        collector = self.registry.get(entry.platform)
                        if collector is None:
                            errors.append(
                                f"{entry.title} on {entry.platform}: no collector registered"
                            )
                            logger.warning(
                                "No collector registered",
                                entry_title=entry.title,
                                platform=entry.platform,
                            )
                        else:
                            logger.debug(
                                "Fetching product details",
                                title=entry.title,
                                platform=entry.platform,
                                product_id=source_product_id,
                            )
                            product_data = await collector.fetch_product_details(entry.source_url)
                            if not product_data:
                                error_msg = (
                                    f"{entry.title} on {entry.platform} [{entry.source_url}]: "
                                    "source product not found"
                                )
                                errors.append(error_msg)
                                logger.warning(
                                    "Failed to fetch product",
                                    entry_title=entry.title,
                                    platform=entry.platform,
                                    product_id=source_product_id,
                                    source_url=entry.source_url,
                                )
                            else:
                                logger.debug(
                                    "Successfully fetched product",
                                    title=entry.title,
                                    product_id=source_product_id,
                                    brand=product_data.brand,
                                    model=product_data.model_name,
                                )
                                if not self._product_matches_wishlist(entry, product_data):
                                    mismatch_message = (
                                        f"{entry.title} [{entry.source_url}]: "
                                        f"expected {entry.brand} {entry.model_name}, "
                                        f"got {product_data.brand} {product_data.model_name}"
                                    )
                                    mismatches.append(mismatch_message)
                                    await self.notification_service.send_mismatch_alert(
                                        source_url=entry.source_url,
                                        title=entry.title,
                                        expected=ScanScheduler._normalize_text(
                                            f"{entry.brand} {entry.model_name}"
                                        ),
                                        actual=ScanScheduler._normalize_text(
                                            f"{product_data.brand} {product_data.model_name}"
                                        ),
                                        session=session,
                                    )

                                result = await self._process_wishlist_product(
                                    session,
                                    entry,
                                    collector,
                                    product_data,
                                )
                                if result["success"]:
                                    products_updated += 1
                                    alerts_created += result["alerts_created"]
                                elif result["reason"] == "size_scope_mismatch":
                                    size_skipped += 1
                                else:
                                    errors.append(
                                        f"{entry.title} on {entry.platform}: {result['reason']}"
                                    )
                                scanned_keys.add(
                                    (collector.platform_name, product_data.platform_product_id or source_product_id)
                                )

                    exact_matches = WishlistService.find_exact_matches(session, entry)
                    for product in exact_matches:
                        if product.platform.name not in platforms_to_track:
                            continue

                        key = (product.platform.name, product.platform_product_id)
                        if key in scanned_keys:
                            continue

                        collector = self.registry.get(product.platform.name)
                        if collector is None:
                            errors.append(
                                f"{entry.title} on {product.platform.name}: no collector registered"
                            )
                            continue

                        product_id = product.platform_product_id or extract_product_id_from_url(
                            product.product_url
                        )
                        if not product_id:
                            errors.append(
                                f"{entry.title} on {product.platform.name}: missing product id"
                            )
                            continue

                        product_data = await collector.fetch_product_details(
                            product.product_url or product_id
                        )
                        if not product_data:
                            errors.append(
                                f"{entry.title} on {product.platform.name}: exact match product not found"
                            )
                            continue

                        if not self._product_matches_wishlist(entry, product_data):
                            mismatch_message = (
                                f"{entry.title} [{product.product_url}]: "
                                f"expected {entry.brand} {entry.model_name}, "
                                f"got {product_data.brand} {product_data.model_name}"
                            )
                            mismatches.append(mismatch_message)
                            await self.notification_service.send_mismatch_alert(
                                source_url=product.product_url,
                                title=entry.title,
                                expected=ScanScheduler._normalize_text(
                                    f"{entry.brand} {entry.model_name}"
                                ),
                                actual=ScanScheduler._normalize_text(
                                    f"{product_data.brand} {product_data.model_name}"
                                ),
                                session=session,
                            )

                        result = await self._process_wishlist_product(
                            session,
                            entry,
                            collector,
                            product_data,
                        )
                        if result["success"]:
                            products_updated += 1
                            alerts_created += result["alerts_created"]
                        elif result["reason"] == "size_scope_mismatch":
                            size_skipped += 1
                        else:
                            errors.append(
                                f"{entry.title} on {product.platform.name}: {result['reason']}"
                            )
                        scanned_keys.add((collector.platform_name, product_data.platform_product_id or product_id))

                except Exception as exc:
                    logger.error(
                        "Wishlist scan entry failed",
                        source_url=entry.source_url,
                        error=str(exc),
                    )
                    errors.append(f"{entry.title}: {str(exc)}")

            logger.info(
                "Watchlist scan completed",
                entries=len(active_entries),
                products_updated=products_updated,
                alerts_created=alerts_created,
                size_skipped=size_skipped,
            )
            await self.notification_service.send_scan_summary(
                scan_type="watchlist",
                entries_scanned=entries_scanned,
                products_updated=products_updated,
                alerts_created=alerts_created,
                mismatches=list(dict.fromkeys(mismatches)),
                errors=list(dict.fromkeys(errors)),
                session=session,
            )

            try:
                dispatch_result = await self.notification_service.process_unnotified_alerts(
                    session,
                    batch_size=50,
                )
                logger.info(
                    "Processed unnotified alerts after watchlist scan",
                    sent_count=dispatch_result.get("sent_count", 0),
                    failed_count=dispatch_result.get("failed_count", 0),
                )
            except Exception as exc:
                logger.error(
                    "Failed to dispatch unnotified alerts after watchlist scan",
                    error=str(exc),
                )
        finally:
            session.close()

    def _run_hot_items_scan(self) -> None:
        """Execute hot items scan."""
        asyncio.run(self._async_hot_items_scan())

    async def _async_hot_items_scan(self) -> None:
        """Async launch/brand monitor scan implementation."""
        logger.info("Starting brand monitor scan")
        session = get_session()

        try:
            monitors = BrandMonitorRepository.list_active(session)
            if not monitors:
                logger.info("No active brand monitors found")
                return

            total_new_products = 0
            total_matched_products = 0
            total_errors: list[str] = []

            for monitor in monitors:
                collector = self.registry.get(monitor.platform)
                query = BrandMonitorService.build_discovery_query(monitor)
                scan = BrandMonitorScanRepository.create(
                    session,
                    monitor_id=monitor.id,
                    query=query,
                )

                errors: list[str] = []
                new_product_messages: list[dict[str, object]] = []
                products_found = 0
                products_matched = 0

                try:
                    if collector is None:
                        raise ValueError(f"No collector registered for {monitor.platform}")

                    response = await collector.discover_products(
                        query=query,
                        limit=settings.brand_monitor_result_limit,
                    )
                    products_found = response.products_count
                    if not response.success:
                        raise ValueError(response.error_message or "discovery failed")

                    seen_platform_ids: set[str] = set()
                    for product_data in response.products:
                        source_key = product_data.platform_product_id or product_data.product_url
                        if source_key in seen_platform_ids:
                            continue
                        seen_platform_ids.add(source_key)

                        matches, matched_sizes = BrandMonitorService.product_matches_monitor(
                            monitor,
                            product_data,
                        )
                        if not matches:
                            continue

                        product = BrandMonitorService.upsert_scanned_product(
                            session,
                            platform_name=collector.platform_name,
                            platform_base_url=collector.base_url,
                            product_data=product_data,
                        )
                        products_matched += 1

                        _seen, is_new = BrandMonitorSeenProductRepository.upsert(
                            session,
                            monitor_id=monitor.id,
                            product_id=product.id,
                            scan_id=scan.id,
                        )
                        BrandMonitorScanResultRepository.create(
                            session,
                            scan_id=scan.id,
                            monitor_id=monitor.id,
                            product_id=product.id,
                            is_new=is_new,
                            matched_sizes=json.dumps(matched_sizes) if matched_sizes else None,
                            current_price=BrandMonitorService.current_price(product),
                            discount_percentage=product.discount_percentage,
                        )

                        if is_new:
                            new_product_messages.append(
                                {
                                    "title": product.title,
                                    "brand": product.brand,
                                    "model_name": product.model_name,
                                    "url": product.product_url,
                                    "current_price": BrandMonitorService.current_price(product),
                                    "discount_percentage": product.discount_percentage,
                                    "matched_sizes": matched_sizes,
                                }
                            )

                    BrandMonitorRepository.mark_scanned(session, monitor)
                    BrandMonitorScanRepository.mark_complete(
                        session,
                        scan,
                        status="success",
                        products_found=products_found,
                        products_matched=products_matched,
                        new_products=len(new_product_messages),
                    )

                    total_new_products += len(new_product_messages)
                    total_matched_products += products_matched
                    chat_id = monitor.owner.telegram_chat_id if monitor.owner else None
                    if chat_id:
                        await self.notification_service.send_brand_monitor_update(
                            chat_id=chat_id,
                            monitor_title=BrandMonitorService.describe_monitor(monitor),
                            platform=monitor.platform,
                            query=query,
                            products_found=products_found,
                            products_matched=products_matched,
                            new_products=new_product_messages,
                            errors=[],
                            session=session,
                        )
                except Exception as exc:
                    error_message = str(exc)
                    errors.append(error_message)
                    total_errors.append(
                        f"Monitor #{monitor.id} {monitor.brand} on {monitor.platform}: "
                        f"{error_message}"
                    )
                    logger.error(
                        "Brand monitor scan failed",
                        monitor_id=monitor.id,
                        platform=monitor.platform,
                        brand=monitor.brand,
                        error=error_message,
                    )
                    BrandMonitorScanRepository.mark_complete(
                        session,
                        scan,
                        status="failed",
                        products_found=products_found,
                        products_matched=products_matched,
                        new_products=0,
                        errors=json.dumps(errors),
                    )
                    chat_id = monitor.owner.telegram_chat_id if monitor.owner else None
                    if chat_id:
                        await self.notification_service.send_brand_monitor_update(
                            chat_id=chat_id,
                            monitor_title=BrandMonitorService.describe_monitor(monitor),
                            platform=monitor.platform,
                            query=query,
                            products_found=products_found,
                            products_matched=products_matched,
                            new_products=[],
                            errors=errors,
                            session=session,
                        )

            logger.info(
                "Brand monitor scan completed",
                monitors=len(monitors),
                products_matched=total_matched_products,
                new_products=total_new_products,
                errors=len(total_errors),
            )
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
