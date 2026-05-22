"""SQLAlchemy ORM models for the price tracker."""

from datetime import datetime
from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    Boolean,
    DateTime,
    ForeignKey,
    Text,
    Index,
    UniqueConstraint,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

Base = declarative_base()


class Platform(Base):
    """Represents a scraping platform (Myntra, AJIO, etc.)."""

    __tablename__ = "platforms"

    id = Column(Integer, primary_key=True)
    name = Column(String(50), unique=True, nullable=False, index=True)
    display_name = Column(String(100), nullable=False)
    base_url = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True, index=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # Relationships
    products = relationship("Product", back_populates="platform")
    scan_jobs = relationship("ScanJob", back_populates="platform")

    __table_args__ = (Index("idx_platform_name_active", "name", "is_active"),)


class Product(Base):
    """Represents a sneaker product tracked across platforms."""

    __tablename__ = "products"

    id = Column(Integer, primary_key=True)
    platform_id = Column(Integer, ForeignKey("platforms.id"), nullable=False, index=True)
    product_url = Column(String(500), nullable=False, index=True)
    platform_product_id = Column(String(100), nullable=False)  # e.g., SKU or internal ID

    # Product identity
    brand = Column(String(100), nullable=False, index=True)
    model_name = Column(String(200), nullable=False, index=True)  # Normalized: "New Balance RC42"
    normalized_name = Column(String(200), nullable=True, index=True)  # Deduplication
    title = Column(String(255), nullable=False)  # Raw title from platform
    sku = Column(String(50), nullable=True, index=True)

    # Current commerce state
    listed_price = Column(Float, nullable=True)
    discounted_price = Column(Float, nullable=True)
    currency = Column(String(10), default="INR")
    discount_percentage = Column(Float, nullable=True)

    # Stock state
    in_stock = Column(Boolean, default=True)
    sizes_available = Column(Text, nullable=True)  # JSON: ["8", "8.5", "9"]

    # Metadata
    image_url = Column(String(500), nullable=True)
    description = Column(Text, nullable=True)

    # Tracking
    first_seen_at = Column(DateTime, server_default=func.now())
    last_seen_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    last_price_check_at = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True, index=True)

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # Relationships
    platform = relationship("Platform", back_populates="products")
    price_history = relationship("PriceSnapshot", back_populates="product", cascade="all, delete-orphan")
    stock_history = relationship("StockSnapshot", back_populates="product", cascade="all, delete-orphan")
    alerts = relationship("Alert", back_populates="product", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("platform_id", "platform_product_id", name="uq_platform_product"),
        Index("idx_product_active_updated", "is_active", "updated_at"),
        Index("idx_product_normalized_name", "normalized_name"),
        Index("idx_product_brand_model", "brand", "model_name"),
    )


class PriceSnapshot(Base):
    """Historical price data for a product."""

    __tablename__ = "price_history"

    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)

    listed_price = Column(Float, nullable=True)
    discounted_price = Column(Float, nullable=True)
    discount_percentage = Column(Float, nullable=True)
    currency = Column(String(10), default="INR")

    recorded_at = Column(DateTime, server_default=func.now(), index=True)

    # Relationships
    product = relationship("Product", back_populates="price_history")

    __table_args__ = (Index("idx_price_history_product_date", "product_id", "recorded_at"),)


class StockSnapshot(Base):
    """Historical stock availability data."""

    __tablename__ = "stock_history"

    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)

    in_stock = Column(Boolean, default=True)
    sizes_available = Column(Text, nullable=True)  # JSON
    recorded_at = Column(DateTime, server_default=func.now(), index=True)

    # Relationships
    product = relationship("Product", back_populates="stock_history")

    __table_args__ = (Index("idx_stock_history_product_date", "product_id", "recorded_at"),)


class Alert(Base):
    """User alerts for price drops, new items, restocks."""

    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)

    alert_type = Column(String(50), nullable=False, index=True)  # "price_drop", "new_product", "restock"
    message = Column(Text, nullable=False)
    triggered_at = Column(DateTime, server_default=func.now())
    notified_at = Column(DateTime, nullable=True)  # NULL = not yet sent

    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=func.now())

    # Relationships
    product = relationship("Product", back_populates="alerts")

    __table_args__ = (
        Index("idx_alert_product_type", "product_id", "alert_type"),
        Index("idx_alert_notified", "notified_at"),
    )


class ScanJob(Base):
    """Audit log for scan jobs."""

    __tablename__ = "scan_jobs"

    id = Column(Integer, primary_key=True)
    platform_id = Column(Integer, ForeignKey("platforms.id"), nullable=False, index=True)

    scan_type = Column(String(50), nullable=False)  # "catalog", "watchlist", "hot_items"
    status = Column(String(50), nullable=False, index=True)  # "running", "success", "failed"

    products_found = Column(Integer, default=0)
    products_updated = Column(Integer, default=0)
    errors = Column(Text, nullable=True)  # JSON: error details

    started_at = Column(DateTime, server_default=func.now())
    completed_at = Column(DateTime, nullable=True)

    # Relationships
    platform = relationship("Platform", back_populates="scan_jobs")

    __table_args__ = (
        Index("idx_scan_job_platform_status", "platform_id", "status"),
        Index("idx_scan_job_completed", "completed_at"),
    )


class Watchlist(Base):
    """User watchlist for specific products."""

    __tablename__ = "watchlist"

    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False, unique=True, index=True)

    price_alert_threshold = Column(Float, nullable=True)  # Alert if drops below this
    restock_alert = Column(Boolean, default=True)
    notes = Column(Text, nullable=True)

    added_at = Column(DateTime, server_default=func.now())
    removed_at = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True, index=True)

    __table_args__ = (Index("idx_watchlist_active", "is_active"),)
