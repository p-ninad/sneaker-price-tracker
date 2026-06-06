"""Tracking service for detecting product changes and generating alerts."""

from datetime import datetime, timedelta
from typing import List, Optional, Tuple, Dict, Any
from dataclasses import dataclass
from enum import Enum
from sqlalchemy.orm import Session
from app.utils.logger import get_logger
from app.database.models import Product, PriceSnapshot, StockSnapshot, Alert
from app.database.repository import (
    PriceSnapshotRepository,
    StockSnapshotRepository,
    AlertRepository,
    ProductRepository,
    WatchlistRepository,
)
from app.config import settings

logger = get_logger(__name__)


class ChangeType(Enum):
    """Types of product changes."""
    PRICE_DROP = "price_drop"
    PRICE_INCREASE = "price_increase"
    OUT_OF_STOCK = "out_of_stock"
    BACK_IN_STOCK = "back_in_stock"
    NEW_PRODUCT = "new_product"
    PRODUCT_REMOVED = "product_removed"
    DISCOUNT_CHANGED = "discount_changed"
    SIZE_AVAILABILITY_CHANGED = "size_availability_changed"


@dataclass
class PriceChange:
    """Represents a price change."""
    old_price: float
    new_price: float
    change_amount: float
    change_percentage: float
    
    def is_drop(self) -> bool:
        """Check if this is a price drop."""
        return self.change_amount < 0
    
    def is_significant(self, threshold_percent: float = None) -> bool:
        """Check if change exceeds threshold."""
        if threshold_percent is None:
            threshold_percent = settings.price_drop_threshold_percent
        return abs(self.change_percentage) >= threshold_percent


@dataclass
class DiscountChange:
    """Represents a discount change."""
    old_discount: Optional[float]
    new_discount: Optional[float]
    discount_difference: float


@dataclass
class StockChange:
    """Represents stock availability change."""
    old_in_stock: bool
    new_in_stock: bool
    changed: bool
    
    def became_available(self) -> bool:
        """Check if product became available."""
        return not self.old_in_stock and self.new_in_stock
    
    def became_unavailable(self) -> bool:
        """Check if product became unavailable."""
        return self.old_in_stock and not self.new_in_stock


@dataclass
class ProductChangeAnalysis:
    """Complete analysis of product changes."""
    product: Product
    change_types: List[ChangeType]
    price_change: Optional[PriceChange] = None
    discount_change: Optional[DiscountChange] = None
    stock_change: Optional[StockChange] = None
    size_changes: Optional[Dict[str, Any]] = None
    
    def has_changes(self) -> bool:
        """Check if any changes were detected."""
        return len(self.change_types) > 0
    
    def should_notify(self) -> bool:
        """Check if changes warrant notification."""
        # Notify for significant price drops
        if ChangeType.PRICE_DROP in self.change_types:
            if self.price_change and self.price_change.is_significant():
                return True
        
        # Notify for stock changes
        if ChangeType.BACK_IN_STOCK in self.change_types:
            return settings.restock_notification_enabled
        
        # Notify for new products
        if ChangeType.NEW_PRODUCT in self.change_types:
            return settings.new_product_notification_enabled
        
        return False


class TrackingService:
    """Service for tracking product changes and generating alerts."""
    
    def __init__(self):
        """Initialize tracking service."""
        self.logger = get_logger("services.tracking")
    
    def analyze_product_update(
        self,
        session: Session,
        product: Product,
        new_listed_price: Optional[float],
        new_discounted_price: Optional[float],
        new_discount_percentage: Optional[float],
        new_in_stock: bool,
        new_sizes_available: Optional[str],
    ) -> ProductChangeAnalysis:
        """Analyze changes for a product update.
        
        Args:
            session: Database session
            product: Product to analyze
            new_listed_price: New listed price
            new_discounted_price: New discounted price
            new_discount_percentage: New discount percentage
            new_in_stock: New stock status
            new_sizes_available: New sizes available (JSON string)
        
        Returns:
            ProductChangeAnalysis with detected changes
        """
        
        changes: List[ChangeType] = []
        
        # Detect price changes
        price_change = None
        if product.discounted_price is not None and new_discounted_price is not None:
            price_change = self._analyze_price_change(
                product.discounted_price,
                new_discounted_price,
            )
            if price_change:
                if price_change.is_drop():
                    changes.append(ChangeType.PRICE_DROP)
                else:
                    changes.append(ChangeType.PRICE_INCREASE)
        
        # Detect discount changes
        discount_change = None
        if product.discount_percentage is not None or new_discount_percentage is not None:
            discount_change = self._analyze_discount_change(
                product.discount_percentage,
                new_discount_percentage,
            )
            if discount_change and discount_change.discount_difference != 0:
                changes.append(ChangeType.DISCOUNT_CHANGED)
        
        # Detect stock changes
        stock_change = self._analyze_stock_change(product.in_stock, new_in_stock)
        if stock_change.changed:
            if stock_change.became_available():
                changes.append(ChangeType.BACK_IN_STOCK)
            elif stock_change.became_unavailable():
                changes.append(ChangeType.OUT_OF_STOCK)
        
        # Detect size availability changes
        size_changes = self._analyze_size_changes(
            product.sizes_available,
            new_sizes_available,
        )
        if size_changes:
            changes.append(ChangeType.SIZE_AVAILABILITY_CHANGED)
        
        analysis = ProductChangeAnalysis(
            product=product,
            change_types=changes,
            price_change=price_change,
            discount_change=discount_change,
            stock_change=stock_change,
            size_changes=size_changes,
        )
        
        return analysis
    
    def create_alerts_from_analysis(
        self,
        session: Session,
        analysis: ProductChangeAnalysis,
    ) -> List[Alert]:
        """Create alerts based on change analysis.
        
        Args:
            session: Database session
            analysis: ProductChangeAnalysis
        
        Returns:
            List of created alerts
        """
        
        alerts: List[Alert] = []
        
        watchlist_rule = WatchlistRepository.get_by_product_id(session, analysis.product.id)

        for change_type in analysis.change_types:
            alert = None
            
            if change_type == ChangeType.PRICE_DROP and analysis.price_change:
                threshold_price = (
                    watchlist_rule.price_alert_threshold
                    if watchlist_rule and watchlist_rule.price_alert_threshold is not None
                    else None
                )
                price_matches_threshold = (
                    threshold_price is not None
                    and analysis.price_change.new_price <= threshold_price
                )
                if price_matches_threshold or analysis.price_change.is_significant():
                    threshold_note = (
                        f"\nThreshold: ₹{threshold_price:.0f}"
                        if threshold_price is not None
                        else ""
                    )
                    message = (
                        f"Price dropped on {analysis.product.brand} {analysis.product.model_name}\n"
                        f"₹{analysis.price_change.old_price:.0f} → ₹{analysis.price_change.new_price:.0f}\n"
                        f"Discount: {analysis.price_change.change_percentage:.1f}%"
                        f"{threshold_note}"
                    )
                    alert = AlertRepository.create(
                        session,
                        product_id=analysis.product.id,
                        alert_type="price_drop",
                        message=message,
                    )
            
            elif change_type == ChangeType.BACK_IN_STOCK:
                restock_enabled = settings.restock_notification_enabled
                if watchlist_rule is not None:
                    restock_enabled = watchlist_rule.restock_alert

                if restock_enabled:
                    message = (
                        f"{analysis.product.brand} {analysis.product.model_name} is back in stock!"
                    )
                    alert = AlertRepository.create(
                        session,
                        product_id=analysis.product.id,
                        alert_type="restock",
                        message=message,
                    )
            
            elif change_type == ChangeType.OUT_OF_STOCK:
                message = (
                    f"{analysis.product.brand} {analysis.product.model_name} is now out of stock"
                )
                alert = AlertRepository.create(
                    session,
                    product_id=analysis.product.id,
                    alert_type="out_of_stock",
                    message=message,
                )
            
            elif change_type == ChangeType.NEW_PRODUCT:
                if settings.new_product_notification_enabled:
                    message = (
                        f"New product discovered: {analysis.product.brand} {analysis.product.model_name}\n"
                        f"Price: ₹{analysis.product.discounted_price or analysis.product.listed_price:.0f}"
                    )
                    alert = AlertRepository.create(
                        session,
                        product_id=analysis.product.id,
                        alert_type="new_product",
                        message=message,
                    )
            
            if alert:
                alerts.append(alert)
                self.logger.info(
                    "Alert created",
                    alert_type=change_type.value,
                    product_id=analysis.product.id,
                )
        
        return alerts
    
    def detect_new_products(
        self,
        session: Session,
        platform_id: int,
        discovered_product_ids: List[str],
    ) -> List[Product]:
        """Detect newly discovered products.
        
        Args:
            session: Database session
            platform_id: Platform ID
            discovered_product_ids: List of product IDs from latest scan
        
        Returns:
            List of newly discovered products
        """
        
        # Get existing products
        existing = session.query(Product).filter(
            Product.platform_id == platform_id,
            Product.is_active == True,
        ).all()
        existing_ids = {p.platform_product_id for p in existing}
        
        # Find new IDs
        new_ids = set(discovered_product_ids) - existing_ids
        
        # Note: New products are created by ProductRepository.create_or_update
        # This method is for detecting and alerting
        return []
    
    def detect_removed_products(
        self,
        session: Session,
        platform_id: int,
        discovered_product_ids: List[str],
        days_missing: int = 7,
    ) -> List[Product]:
        """Detect products that have been removed/delisted.
        
        Args:
            session: Database session
            platform_id: Platform ID
            discovered_product_ids: Current discovered product IDs
            days_missing: Days before marking as removed
        
        Returns:
            List of removed products
        """
        
        # Get products not seen in recent scans
        cutoff = datetime.utcnow() - timedelta(days=days_missing)
        removed = session.query(Product).filter(
            Product.platform_id == platform_id,
            Product.is_active == True,
            Product.last_seen_at < cutoff,
            ~Product.platform_product_id.in_(discovered_product_ids),
        ).all()
        
        # Mark as inactive
        for product in removed:
            product.is_active = False
            alert = AlertRepository.create(
                session,
                product_id=product.id,
                alert_type="product_removed",
                message=f"{product.brand} {product.model_name} is no longer available",
            )
            self.logger.info(
                "Product removed",
                product_id=product.id,
                platform_id=platform_id,
            )
        
        session.commit()
        return removed
    
    def record_price_snapshot(
        self,
        session: Session,
        product: Product,
        listed_price: Optional[float],
        discounted_price: Optional[float],
        discount_percentage: Optional[float],
    ) -> PriceSnapshot:
        """Record a price snapshot for trend analysis.
        
        Args:
            session: Database session
            product: Product
            listed_price: Listed price
            discounted_price: Discounted price
            discount_percentage: Discount percentage
        
        Returns:
            Created PriceSnapshot
        """
        
        return PriceSnapshotRepository.create(
            session,
            product_id=product.id,
            listed_price=listed_price,
            discounted_price=discounted_price,
            discount_percentage=discount_percentage,
        )
    
    def record_stock_snapshot(
        self,
        session: Session,
        product: Product,
        in_stock: bool,
        sizes_available: Optional[str],
    ) -> StockSnapshot:
        """Record a stock snapshot for trend analysis.
        
        Args:
            session: Database session
            product: Product
            in_stock: Stock status
            sizes_available: Available sizes (JSON)
        
        Returns:
            Created StockSnapshot
        """
        
        snapshot = StockSnapshot(
            product_id=product.id,
            in_stock=in_stock,
            sizes_available=sizes_available,
        )
        session.add(snapshot)
        session.commit()
        return snapshot
    
    def get_price_trend(
        self,
        session: Session,
        product_id: int,
        days: int = 30,
    ) -> Optional[Dict[str, Any]]:
        """Get price trend for a product.
        
        Args:
            session: Database session
            product_id: Product ID
            days: Number of days to look back
        
        Returns:
            Trend data or None
        """
        
        cutoff = datetime.utcnow() - timedelta(days=days)
        snapshots = session.query(PriceSnapshot).filter(
            PriceSnapshot.product_id == product_id,
            PriceSnapshot.recorded_at >= cutoff,
        ).order_by(PriceSnapshot.recorded_at).all()
        
        if len(snapshots) < 2:
            return None
        
        prices = [s.discounted_price or s.listed_price for s in snapshots]
        return {
            "snapshots": len(snapshots),
            "min_price": min(prices),
            "max_price": max(prices),
            "current_price": prices[-1],
            "price_change": prices[-1] - prices[0],
            "price_change_percent": ((prices[-1] - prices[0]) / prices[0] * 100) if prices[0] else 0,
        }
    
    # === Private Helper Methods ===
    
    @staticmethod
    def _analyze_price_change(
        old_price: float,
        new_price: float,
    ) -> Optional[PriceChange]:
        """Analyze price change between two prices."""
        
        if old_price is None or new_price is None:
            return None
        
        if old_price == new_price:
            return None
        
        change_amount = new_price - old_price
        change_percentage = (change_amount / old_price * 100) if old_price != 0 else 0
        
        return PriceChange(
            old_price=old_price,
            new_price=new_price,
            change_amount=change_amount,
            change_percentage=change_percentage,
        )
    
    @staticmethod
    def _analyze_discount_change(
        old_discount: Optional[float],
        new_discount: Optional[float],
    ) -> Optional[DiscountChange]:
        """Analyze discount change."""
        
        old = old_discount or 0
        new = new_discount or 0
        
        if old == new:
            return None
        
        return DiscountChange(
            old_discount=old_discount,
            new_discount=new_discount,
            discount_difference=new - old,
        )
    
    @staticmethod
    def _analyze_stock_change(
        old_in_stock: bool,
        new_in_stock: bool,
    ) -> StockChange:
        """Analyze stock availability change."""
        
        return StockChange(
            old_in_stock=old_in_stock,
            new_in_stock=new_in_stock,
            changed=(old_in_stock != new_in_stock),
        )
    
    @staticmethod
    def _analyze_size_changes(
        old_sizes: Optional[str],
        new_sizes: Optional[str],
    ) -> Optional[Dict[str, Any]]:
        """Analyze size availability changes."""
        
        # Parse JSON or comma-separated sizes
        try:
            import json
            old = set(json.loads(old_sizes)) if old_sizes else set()
            new = set(json.loads(new_sizes)) if new_sizes else set()
        except:
            old = set(old_sizes.split(",")) if old_sizes else set()
            new = set(new_sizes.split(",")) if new_sizes else set()
        
        if old == new:
            return None
        
        return {
            "added": list(new - old),
            "removed": list(old - new),
            "old_count": len(old),
            "new_count": len(new),
        }
