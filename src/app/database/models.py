"""SQLAlchemy ORM models for the price tracker."""

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


class User(Base):
    """Application user for admin access and Telegram identity linkage."""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String(80), nullable=False, unique=True, index=True)
    display_name = Column(String(120), nullable=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(20), nullable=False, default="user", index=True)

    telegram_user_id = Column(String(50), nullable=True, unique=True, index=True)
    telegram_chat_id = Column(String(50), nullable=True, unique=True, index=True)
    is_active = Column(Boolean, default=True, index=True)
    last_login_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    sessions = relationship(
        "AuthSession", back_populates="user", cascade="all, delete-orphan"
    )
    wishlist_entries = relationship(
        "WishlistEntry", back_populates="owner", cascade="all, delete-orphan"
    )
    brand_monitors = relationship(
        "BrandMonitor", back_populates="owner", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("idx_user_role_active", "role", "is_active"),
        Index("idx_user_telegram_identity", "telegram_user_id", "telegram_chat_id"),
    )


class AuthSession(Base):
    """Persisted login session for the web portal."""

    __tablename__ = "auth_sessions"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    session_token_hash = Column(String(64), nullable=False, unique=True, index=True)

    ip_address = Column(String(64), nullable=True)
    user_agent = Column(String(255), nullable=True)

    created_at = Column(DateTime, server_default=func.now())
    last_seen_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=False, index=True)
    revoked_at = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="sessions")

    __table_args__ = (
        Index("idx_auth_session_user_expires", "user_id", "expires_at"),
        Index("idx_auth_session_revoked", "revoked_at"),
    )


class AppSetting(Base):
    """Persisted application-level setting controlled from the admin console."""

    __tablename__ = "app_settings"

    id = Column(Integer, primary_key=True)
    key = Column(String(120), nullable=False, unique=True, index=True)
    value = Column(Text, nullable=False)

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


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
    manual_discovery_results = relationship(
        "ManualDiscoveryResult",
        back_populates="product",
        cascade="all, delete-orphan",
    )

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


class WishlistEntry(Base):
    """Wishlist entry created from a product URL and metadata."""

    __tablename__ = "wishlist_entries"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    source_url = Column(String(500), nullable=False, index=True)
    platform = Column(String(50), nullable=False, index=True)
    brand = Column(String(100), nullable=False, index=True)
    model_name = Column(String(200), nullable=False, index=True)
    normalized_name = Column(String(200), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    size_scope = Column(Text, nullable=False)
    platforms_to_track = Column(Text, nullable=False)
    notes = Column(Text, nullable=True)

    is_active = Column(Boolean, default=True, index=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    owner = relationship("User", back_populates="wishlist_entries")

    __table_args__ = (
        UniqueConstraint("user_id", "source_url", name="uq_wishlist_user_source_url"),
        Index("idx_wishlist_user_active", "user_id", "is_active"),
        Index("idx_wishlist_active_updated", "is_active", "updated_at"),
        Index("idx_wishlist_normalized_name", "normalized_name"),
    )


class ProductIgnore(Base):
    """Product excluded from future discovery scans."""

    __tablename__ = "product_ignores"

    id = Column(Integer, primary_key=True)
    platform_id = Column(Integer, ForeignKey("platforms.id"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=True, index=True)
    platform_product_id = Column(String(100), nullable=False)
    product_url = Column(String(500), nullable=False)
    reason = Column(Text, nullable=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    is_active = Column(Boolean, default=True, index=True)
    created_at = Column(DateTime, server_default=func.now())

    platform = relationship("Platform")
    product = relationship("Product")
    created_by = relationship("User")

    __table_args__ = (
        UniqueConstraint(
            "platform_id",
            "platform_product_id",
            name="uq_product_ignore_platform_product",
        ),
        Index("idx_product_ignore_active", "platform_id", "is_active"),
    )


class ManualDiscoveryScan(Base):
    """Admin-triggered filtered product discovery scan."""

    __tablename__ = "manual_discovery_scans"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    platform = Column(String(50), nullable=False, index=True)
    brand_filters = Column(Text, nullable=False)
    size_filters = Column(Text, nullable=False)
    status = Column(String(50), nullable=False, default="running", index=True)
    products_found = Column(Integer, default=0)
    products_matched = Column(Integer, default=0)
    errors = Column(Text, nullable=True)
    started_at = Column(DateTime, server_default=func.now(), index=True)
    completed_at = Column(DateTime, nullable=True)

    owner = relationship("User")
    results = relationship(
        "ManualDiscoveryResult",
        back_populates="scan",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("idx_manual_scan_user_started", "user_id", "started_at"),
        Index("idx_manual_scan_status", "status"),
    )


class ManualDiscoveryResult(Base):
    """One product matched by an admin-triggered discovery scan."""

    __tablename__ = "manual_discovery_results"

    id = Column(Integer, primary_key=True)
    scan_id = Column(Integer, ForeignKey("manual_discovery_scans.id"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)
    matched_brand = Column(String(120), nullable=False)
    matched_sizes = Column(Text, nullable=True)
    current_price = Column(Float, nullable=True)
    discount_percentage = Column(Float, nullable=True)
    is_tracked = Column(Boolean, default=False, index=True)
    is_ignored = Column(Boolean, default=False, index=True)
    created_at = Column(DateTime, server_default=func.now(), index=True)

    scan = relationship("ManualDiscoveryScan", back_populates="results")
    product = relationship("Product", back_populates="manual_discovery_results")

    __table_args__ = (
        UniqueConstraint("scan_id", "product_id", name="uq_manual_scan_product"),
        Index("idx_manual_result_scan_visible", "scan_id", "is_ignored", "created_at"),
    )


class BrandMonitor(Base):
    """User-defined discovery monitor for brand/platform launches."""

    __tablename__ = "brand_monitors"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    platform = Column(String(50), nullable=False, index=True)
    brand = Column(String(120), nullable=False, index=True)
    query_terms = Column(Text, nullable=True)
    size_scope = Column(Text, nullable=True)
    min_discount_percentage = Column(Float, nullable=True)
    max_price = Column(Float, nullable=True)
    require_in_stock = Column(Boolean, default=True, index=True)
    notes = Column(Text, nullable=True)

    last_scanned_at = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True, index=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    owner = relationship("User", back_populates="brand_monitors")
    scans = relationship(
        "BrandMonitorScan", back_populates="monitor", cascade="all, delete-orphan"
    )
    seen_products = relationship(
        "BrandMonitorSeenProduct",
        back_populates="monitor",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("idx_brand_monitor_user_active", "user_id", "is_active"),
        Index("idx_brand_monitor_platform_brand", "platform", "brand"),
    )


class BrandMonitorScan(Base):
    """A single scan run for a brand monitor."""

    __tablename__ = "brand_monitor_scans"

    id = Column(Integer, primary_key=True)
    monitor_id = Column(Integer, ForeignKey("brand_monitors.id"), nullable=False, index=True)
    scan_job_id = Column(Integer, ForeignKey("scan_jobs.id"), nullable=True, index=True)
    status = Column(String(50), nullable=False, default="running", index=True)
    query = Column(String(255), nullable=False)

    products_found = Column(Integer, default=0)
    products_matched = Column(Integer, default=0)
    new_products = Column(Integer, default=0)
    errors = Column(Text, nullable=True)

    started_at = Column(DateTime, server_default=func.now())
    completed_at = Column(DateTime, nullable=True)

    monitor = relationship("BrandMonitor", back_populates="scans")
    results = relationship(
        "BrandMonitorScanResult",
        back_populates="scan",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("idx_brand_monitor_scan_completed", "monitor_id", "completed_at"),
    )


class BrandMonitorSeenProduct(Base):
    """Ledger of products already seen by a brand monitor."""

    __tablename__ = "brand_monitor_seen_products"

    id = Column(Integer, primary_key=True)
    monitor_id = Column(Integer, ForeignKey("brand_monitors.id"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)
    first_scan_id = Column(Integer, ForeignKey("brand_monitor_scans.id"), nullable=True)
    last_scan_id = Column(Integer, ForeignKey("brand_monitor_scans.id"), nullable=True)
    first_seen_at = Column(DateTime, server_default=func.now())
    last_seen_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    monitor = relationship("BrandMonitor", back_populates="seen_products")
    product = relationship("Product")

    __table_args__ = (
        UniqueConstraint(
            "monitor_id",
            "product_id",
            name="uq_brand_monitor_seen_product",
        ),
        Index("idx_brand_monitor_seen_monitor_product", "monitor_id", "product_id"),
    )


class BrandMonitorScanResult(Base):
    """Product match captured during a brand monitor scan."""

    __tablename__ = "brand_monitor_scan_results"

    id = Column(Integer, primary_key=True)
    scan_id = Column(Integer, ForeignKey("brand_monitor_scans.id"), nullable=False, index=True)
    monitor_id = Column(Integer, ForeignKey("brand_monitors.id"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)
    is_new = Column(Boolean, default=False, index=True)
    matched_sizes = Column(Text, nullable=True)
    current_price = Column(Float, nullable=True)
    discount_percentage = Column(Float, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    scan = relationship("BrandMonitorScan", back_populates="results")
    monitor = relationship("BrandMonitor")
    product = relationship("Product")

    __table_args__ = (
        UniqueConstraint("scan_id", "product_id", name="uq_brand_monitor_scan_product"),
        Index("idx_brand_monitor_result_new", "monitor_id", "is_new"),
    )
