"""Data access layer for database operations."""

from typing import Optional, List
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import desc, and_, or_
from app.database.models import (
    Platform,
    Product,
    PriceSnapshot,
    StockSnapshot,
    Alert,
    ScanJob,
    Watchlist,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)


class PlatformRepository:
    """Repository for Platform operations."""

    @staticmethod
    def create(session: Session, name: str, display_name: str, base_url: str) -> Platform:
        """Create a new platform."""
        platform = Platform(
            name=name.lower(),
            display_name=display_name,
            base_url=base_url,
        )
        session.add(platform)
        session.commit()
        return platform

    @staticmethod
    def get_by_name(session: Session, name: str) -> Optional[Platform]:
        """Get platform by name."""
        return session.query(Platform).filter(
            Platform.name == name.lower(),
            Platform.is_active == True,
        ).first()

    @staticmethod
    def get_all_active(session: Session) -> List[Platform]:
        """Get all active platforms."""
        return session.query(Platform).filter(Platform.is_active == True).all()


class ProductRepository:
    """Repository for Product operations."""

    @staticmethod
    def create_or_update(
        session: Session,
        platform_id: int,
        product_url: str,
        platform_product_id: str,
        brand: str,
        model_name: str,
        title: str,
        listed_price: Optional[float] = None,
        discounted_price: Optional[float] = None,
        currency: str = "INR",
        in_stock: bool = True,
        sizes_available: Optional[str] = None,
        image_url: Optional[str] = None,
        sku: Optional[str] = None,
    ) -> Product:
        """Create or update a product."""

        # Try to find existing product
        existing = session.query(Product).filter(
            Product.platform_id == platform_id,
            Product.platform_product_id == platform_product_id,
        ).first()

        if existing:
            # Update existing
            existing.title = title
            existing.brand = brand
            existing.model_name = model_name
            existing.listed_price = listed_price
            existing.discounted_price = discounted_price
            existing.currency = currency
            existing.in_stock = in_stock
            existing.sizes_available = sizes_available
            existing.image_url = image_url or existing.image_url
            existing.sku = sku or existing.sku
            existing.last_seen_at = datetime.utcnow()
            existing.last_price_check_at = datetime.utcnow()
            product = existing
        else:
            # Create new
            product = Product(
                platform_id=platform_id,
                product_url=product_url,
                platform_product_id=platform_product_id,
                brand=brand,
                model_name=model_name,
                title=title,
                listed_price=listed_price,
                discounted_price=discounted_price,
                currency=currency,
                in_stock=in_stock,
                sizes_available=sizes_available,
                image_url=image_url,
                sku=sku,
            )
            session.add(product)

        session.commit()
        return product

    @staticmethod
    def get_by_url(session: Session, platform_id: int, product_url: str) -> Optional[Product]:
        """Get product by platform and URL."""
        return session.query(Product).filter(
            Product.platform_id == platform_id,
            Product.product_url == product_url,
        ).first()

    @staticmethod
    def get_active_by_platform(session: Session, platform_id: int) -> List[Product]:
        """Get all active products for a platform."""
        return session.query(Product).filter(
            Product.platform_id == platform_id,
            Product.is_active == True,
        ).all()

    @staticmethod
    def search_by_brand_model(
        session: Session, brand: str, model_name: str
    ) -> List[Product]:
        """Search for products by brand and model."""
        return session.query(Product).filter(
            Product.brand.ilike(f"%{brand}%"),
            Product.model_name.ilike(f"%{model_name}%"),
            Product.is_active == True,
        ).all()


class PriceSnapshotRepository:
    """Repository for PriceSnapshot operations."""

    @staticmethod
    def create(
        session: Session,
        product_id: int,
        listed_price: Optional[float],
        discounted_price: Optional[float],
        discount_percentage: Optional[float],
        currency: str = "INR",
    ) -> PriceSnapshot:
        """Record a price snapshot."""
        snapshot = PriceSnapshot(
            product_id=product_id,
            listed_price=listed_price,
            discounted_price=discounted_price,
            discount_percentage=discount_percentage,
            currency=currency,
        )
        session.add(snapshot)
        session.commit()
        return snapshot

    @staticmethod
    def get_last_n(session: Session, product_id: int, n: int = 10) -> List[PriceSnapshot]:
        """Get last N price snapshots for a product."""
        return session.query(PriceSnapshot).filter(
            PriceSnapshot.product_id == product_id
        ).order_by(desc(PriceSnapshot.recorded_at)).limit(n).all()

    @staticmethod
    def get_price_change(session: Session, product_id: int, hours: int = 24) -> Optional[tuple]:
        """Get price change in last N hours."""
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        snapshots = session.query(PriceSnapshot).filter(
            PriceSnapshot.product_id == product_id,
            PriceSnapshot.recorded_at >= cutoff,
        ).order_by(PriceSnapshot.recorded_at).all()

        if len(snapshots) < 2:
            return None

        first = snapshots[0]
        last = snapshots[-1]
        return (first, last)


class StockSnapshotRepository:
    """Repository for StockSnapshot operations."""

    @staticmethod
    def create(
        session: Session,
        product_id: int,
        in_stock: bool,
        sizes_available: Optional[str] = None,
    ) -> StockSnapshot:
        """Record a stock snapshot."""
        snapshot = StockSnapshot(
            product_id=product_id,
            in_stock=in_stock,
            sizes_available=sizes_available,
        )
        session.add(snapshot)
        session.commit()
        return snapshot

    @staticmethod
    def get_last_n(session: Session, product_id: int, n: int = 10) -> List[StockSnapshot]:
        """Get last N stock snapshots for a product."""
        return session.query(StockSnapshot).filter(
            StockSnapshot.product_id == product_id
        ).order_by(desc(StockSnapshot.recorded_at)).limit(n).all()

    @staticmethod
    def get_last(session: Session, product_id: int) -> Optional[StockSnapshot]:
        """Get the most recent stock snapshot."""
        return session.query(StockSnapshot).filter(
            StockSnapshot.product_id == product_id
        ).order_by(desc(StockSnapshot.recorded_at)).first()


class AlertRepository:
    """Repository for Alert operations."""

    @staticmethod
    def create(
        session: Session,
        product_id: int,
        alert_type: str,
        message: str,
    ) -> Alert:
        """Create a new alert."""
        alert = Alert(
            product_id=product_id,
            alert_type=alert_type,
            message=message,
        )
        session.add(alert)
        session.commit()
        return alert

    @staticmethod
    def get_unnotified(session: Session, limit: int = 100) -> List[Alert]:
        """Get alerts that haven't been notified yet."""
        return session.query(Alert).filter(
            Alert.notified_at == None
        ).order_by(Alert.triggered_at).limit(limit).all()

    @staticmethod
    def mark_notified(session: Session, alert: Alert) -> None:
        """Mark alert as notified."""
        alert.notified_at = datetime.utcnow()
        session.commit()


class ScanJobRepository:
    """Repository for ScanJob operations."""

    @staticmethod
    def create(session: Session, platform_id: int, scan_type: str) -> ScanJob:
        """Create a new scan job."""
        job = ScanJob(
            platform_id=platform_id,
            scan_type=scan_type,
            status="running",
        )
        session.add(job)
        session.commit()
        return job

    @staticmethod
    def mark_complete(
        session: Session,
        job: ScanJob,
        status: str = "success",
        products_found: int = 0,
        products_updated: int = 0,
        errors: Optional[str] = None,
    ) -> None:
        """Mark scan job as complete."""
        job.status = status
        job.products_found = products_found
        job.products_updated = products_updated
        job.errors = errors
        job.completed_at = datetime.utcnow()
        session.commit()

    @staticmethod
    def get_last_scan(session: Session, platform_id: int, scan_type: str) -> Optional[ScanJob]:
        """Get the last completed scan for a platform."""
        return session.query(ScanJob).filter(
            ScanJob.platform_id == platform_id,
            ScanJob.scan_type == scan_type,
            ScanJob.status == "success",
        ).order_by(desc(ScanJob.completed_at)).first()
