"""Data access layer for database operations."""

from datetime import datetime, timedelta
from typing import List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import desc, and_, or_
from app.database.models import (
    AppSetting,
    AuthSession,
    BrandMonitor,
    BrandMonitorScan,
    BrandMonitorScanResult,
    BrandMonitorSeenProduct,
    ManualDiscoveryResult,
    ManualDiscoveryScan,
    Platform,
    Product,
    ProductIgnore,
    PriceSnapshot,
    StockSnapshot,
    Alert,
    ScanJob,
    User,
    Watchlist,
    WishlistEntry,
)
import app.config as config
from app.utils.logger import get_logger
from app.auth.tokens import hash_token

logger = get_logger(__name__)

TELEGRAM_CONNECTIVITY_SETTING_KEY = "telegram_connectivity_enabled"


class UserRepository:
    """Repository for User operations."""

    @staticmethod
    def create(
        session: Session,
        username: str,
        password_hash: str,
        role: str = "user",
        display_name: str | None = None,
        telegram_user_id: str | None = None,
        telegram_chat_id: str | None = None,
        is_active: bool = True,
    ) -> User:
        """Create a new user record."""
        cleaned_username = username.strip().lower()
        cleaned_role = role.strip().lower()
        if not cleaned_username:
            raise ValueError("username is required")
        if not password_hash:
            raise ValueError("password_hash is required")
        if not cleaned_role:
            raise ValueError("role is required")

        user = User(
            username=cleaned_username,
            display_name=display_name,
            password_hash=password_hash,
            role=cleaned_role,
            telegram_user_id=(
                str(telegram_user_id).strip() if telegram_user_id is not None else None
            )
            or None,
            telegram_chat_id=(
                str(telegram_chat_id).strip() if telegram_chat_id is not None else None
            )
            or None,
            is_active=is_active,
        )
        session.add(user)
        session.commit()
        return user

    @staticmethod
    def get_by_username(session: Session, username: str) -> User | None:
        """Return an active user by username."""
        return (
            session.query(User)
            .filter(User.username == username.strip().lower(), User.is_active == True)
            .first()
        )

    @staticmethod
    def get_by_telegram_user_id(session: Session, telegram_user_id: str) -> User | None:
        """Return a user linked to a Telegram user ID."""
        return session.query(User).filter(
            User.telegram_user_id == str(telegram_user_id),
            User.is_active == True,
        ).first()

    @staticmethod
    def get_by_telegram_chat_id(session: Session, telegram_chat_id: str) -> User | None:
        """Return a user linked to a Telegram chat ID."""
        return session.query(User).filter(
            User.telegram_chat_id == str(telegram_chat_id),
            User.is_active == True,
        ).first()

    @staticmethod
    def list_admins(session: Session) -> list[User]:
        """Return all active admin users."""
        return (
            session.query(User)
            .filter(User.role == "admin", User.is_active == True)
            .order_by(User.username.asc())
            .all()
        )

    @staticmethod
    def search_telegram_users(session: Session, query: str | None = None, limit: int = 20) -> list[User]:
        """Return registered Telegram users matching a search string."""
        base_query = (
            session.query(User)
            .filter(
                User.telegram_user_id.isnot(None),
                User.role == "user",
                User.is_active == True,
            )
            )

        cleaned_query = (query or "").strip()
        if cleaned_query:
            like_query = f"%{cleaned_query.lower()}%"
            base_query = base_query.filter(
                or_(
                    and_(User.display_name.isnot(None), User.display_name.ilike(like_query)),
                    User.username.ilike(like_query),
                    User.telegram_user_id.ilike(like_query),
                )
            )

        return (
            base_query.order_by(User.display_name.asc().nullslast(), User.username.asc())
            .limit(limit)
            .all()
        )

    @staticmethod
    def get_by_id(session: Session, user_id: int) -> User | None:
        """Return an active user by numeric ID."""
        return session.query(User).filter(User.id == user_id, User.is_active == True).first()

    @staticmethod
    def set_telegram_identity(
        session: Session,
        user: User,
        telegram_user_id: str | None = None,
        telegram_chat_id: str | None = None,
    ) -> User:
        """Attach Telegram identity to an existing user."""
        if telegram_user_id is not None:
            cleaned_telegram_user_id = str(telegram_user_id).strip()
            user.telegram_user_id = cleaned_telegram_user_id or None
        if telegram_chat_id is not None:
            cleaned_telegram_chat_id = str(telegram_chat_id).strip()
            user.telegram_chat_id = cleaned_telegram_chat_id or None

        session.commit()
        return user

    @staticmethod
    def attach_telegram_identity(
        session: Session,
        user: User,
        telegram_user_id: str,
        telegram_chat_id: str,
        display_name: str | None = None,
    ) -> User:
        """Bind a Telegram identity to an existing user."""
        cleaned_telegram_user_id = str(telegram_user_id).strip()
        cleaned_telegram_chat_id = str(telegram_chat_id).strip()
        if not cleaned_telegram_user_id:
            raise ValueError("telegram_user_id is required")
        if not cleaned_telegram_chat_id:
            raise ValueError("telegram_chat_id is required")

        conflict = (
            session.query(User)
            .filter(
                User.telegram_user_id == cleaned_telegram_user_id,
                User.id != user.id,
                User.is_active == True,
            )
            .first()
        )
        if conflict is not None:
            raise ValueError("That Telegram account is already linked to another user.")

        user.telegram_user_id = cleaned_telegram_user_id
        user.telegram_chat_id = cleaned_telegram_chat_id
        if display_name:
            user.display_name = display_name
        session.commit()
        return user

    @staticmethod
    def record_login(session: Session, user: User) -> User:
        """Update the user's last login timestamp."""
        from datetime import datetime

        user.last_login_at = datetime.utcnow()
        session.commit()
        return user

    @staticmethod
    def set_active(session: Session, user: User, is_active: bool) -> User:
        """Enable or disable a user."""
        user.is_active = is_active
        session.commit()
        return user

    @staticmethod
    def get_or_create_telegram_user(
        session: Session,
        telegram_user_id: str,
        telegram_chat_id: str,
        display_name: str | None = None,
        username_prefix: str = "tg",
    ) -> User:
        """Get or create a Telegram-linked regular user."""
        cleaned_telegram_user_id = str(telegram_user_id).strip()
        cleaned_telegram_chat_id = str(telegram_chat_id).strip()
        if not cleaned_telegram_user_id:
            raise ValueError("telegram_user_id is required")
        if not cleaned_telegram_chat_id:
            raise ValueError("telegram_chat_id is required")

        existing = session.query(User).filter(
            User.telegram_user_id == cleaned_telegram_user_id
        ).first()
        if existing is not None:
            if existing.telegram_chat_id != cleaned_telegram_chat_id:
                existing.telegram_chat_id = cleaned_telegram_chat_id
                session.commit()
            return existing

        username = f"{username_prefix}_{cleaned_telegram_user_id}"
        from app.auth.passwords import hash_password

        user = User(
            username=username,
            display_name=display_name,
            password_hash=hash_password(cleaned_telegram_user_id + cleaned_telegram_chat_id),
            role="user",
            telegram_user_id=cleaned_telegram_user_id,
            telegram_chat_id=cleaned_telegram_chat_id,
            is_active=True,
        )
        session.add(user)
        session.commit()
        return user


class AuthSessionRepository:
    """Repository for persisted web sessions."""

    @staticmethod
    def create(
        session: Session,
        user_id: int,
        session_token: str,
        expires_at: datetime,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> AuthSession:
        """Create a new session row for a hashed session token."""
        if not session_token:
            raise ValueError("session_token is required")
        if expires_at is None:
            raise ValueError("expires_at is required")

        auth_session = AuthSession(
            user_id=user_id,
            session_token_hash=hash_token(session_token),
            expires_at=expires_at,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        session.add(auth_session)
        session.commit()
        return auth_session

    @staticmethod
    def get_by_token(session: Session, session_token: str) -> AuthSession | None:
        """Return an unrevoked session by raw token."""
        return (
            session.query(AuthSession)
            .filter(
                AuthSession.session_token_hash == hash_token(session_token),
                AuthSession.revoked_at == None,
                AuthSession.expires_at > datetime.utcnow(),
            )
            .first()
        )

    @staticmethod
    def revoke(session: Session, auth_session: AuthSession) -> AuthSession:
        """Revoke a persisted session."""
        from datetime import datetime

        auth_session.revoked_at = datetime.utcnow()
        session.commit()
        return auth_session

    @staticmethod
    def revoke_for_user(session: Session, user_id: int) -> int:
        """Revoke all active sessions for a user."""
        from datetime import datetime

        sessions = (
            session.query(AuthSession)
            .filter(AuthSession.user_id == user_id, AuthSession.revoked_at == None)
            .all()
        )

        now = datetime.utcnow()
        for auth_session in sessions:
            auth_session.revoked_at = now

        session.commit()
        return len(sessions)

    @staticmethod
    def touch(session: Session, auth_session: AuthSession) -> AuthSession:
        """Update the last-seen timestamp for a session."""
        auth_session.last_seen_at = datetime.utcnow()
        session.commit()
        return auth_session


class AppSettingRepository:
    """Repository for admin-controlled application settings."""

    @staticmethod
    def get(session: Session, key: str) -> AppSetting | None:
        """Return a setting row by key."""
        return session.query(AppSetting).filter(AppSetting.key == key).first()

    @staticmethod
    def set_value(session: Session, key: str, value: str) -> AppSetting:
        """Create or update a setting value."""
        cleaned_key = key.strip()
        if not cleaned_key:
            raise ValueError("setting key is required")

        setting = AppSettingRepository.get(session, cleaned_key)
        if setting is None:
            setting = AppSetting(key=cleaned_key, value=value)
            session.add(setting)
        else:
            setting.value = value

        session.commit()
        return setting

    @staticmethod
    def get_bool(session: Session, key: str, default: bool = False) -> bool:
        """Return a boolean setting value."""
        setting = AppSettingRepository.get(session, key)
        if setting is None:
            return default

        normalized = str(setting.value).strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
        return default

    @staticmethod
    def set_bool(session: Session, key: str, value: bool) -> AppSetting:
        """Persist a boolean setting value."""
        return AppSettingRepository.set_value(session, key, "true" if value else "false")

    @staticmethod
    def telegram_connectivity_enabled(session: Session) -> bool:
        """Return whether runtime Telegram communication is enabled."""
        return AppSettingRepository.get_bool(
            session,
            TELEGRAM_CONNECTIVITY_SETTING_KEY,
            default=config.settings.telegram_connectivity_enabled,
        )

    @staticmethod
    def set_telegram_connectivity_enabled(
        session: Session,
        enabled: bool,
    ) -> AppSetting:
        """Persist the Telegram connectivity switch."""
        return AppSettingRepository.set_bool(
            session,
            TELEGRAM_CONNECTIVITY_SETTING_KEY,
            enabled,
        )


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
        discount_percentage: Optional[float] = None,
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
            existing.discount_percentage = discount_percentage
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
                discount_percentage=discount_percentage,
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
    def get_by_id(session: Session, product_id: int) -> Product | None:
        """Get a product by its primary key."""
        return session.query(Product).filter(Product.id == product_id).first()

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


class BrandMonitorRepository:
    """Repository for user-defined launch/brand monitors."""

    @staticmethod
    def create(
        session: Session,
        user_id: int,
        platform: str,
        brand: str,
        query_terms: str | None = None,
        size_scope: str | None = None,
        min_discount_percentage: float | None = None,
        max_price: float | None = None,
        require_in_stock: bool = True,
        notes: str | None = None,
    ) -> BrandMonitor:
        """Create a brand monitor."""
        cleaned_platform = platform.strip().lower()
        cleaned_brand = brand.strip()
        if not cleaned_platform:
            raise ValueError("platform is required")
        if not cleaned_brand:
            raise ValueError("brand is required")

        monitor = BrandMonitor(
            user_id=user_id,
            platform=cleaned_platform,
            brand=cleaned_brand,
            query_terms=query_terms,
            size_scope=size_scope,
            min_discount_percentage=min_discount_percentage,
            max_price=max_price,
            require_in_stock=require_in_stock,
            notes=notes,
            is_active=True,
        )
        session.add(monitor)
        session.commit()
        return monitor

    @staticmethod
    def get_by_id(session: Session, monitor_id: int) -> BrandMonitor | None:
        """Return a monitor by ID."""
        return session.query(BrandMonitor).filter(BrandMonitor.id == monitor_id).first()

    @staticmethod
    def get_for_user(session: Session, user_id: int, monitor_id: int) -> BrandMonitor | None:
        """Return one monitor owned by a user."""
        return (
            session.query(BrandMonitor)
            .filter(BrandMonitor.id == monitor_id, BrandMonitor.user_id == user_id)
            .first()
        )

    @staticmethod
    def list_active(session: Session) -> list[BrandMonitor]:
        """Return all active monitors."""
        return (
            session.query(BrandMonitor)
            .filter(BrandMonitor.is_active == True)
            .order_by(BrandMonitor.created_at.desc())
            .all()
        )

    @staticmethod
    def list_for_user(session: Session, user_id: int) -> list[BrandMonitor]:
        """Return monitors for a user."""
        return (
            session.query(BrandMonitor)
            .filter(BrandMonitor.user_id == user_id)
            .order_by(BrandMonitor.created_at.desc())
            .all()
        )

    @staticmethod
    def count_active_for_user(session: Session, user_id: int) -> int:
        """Return active monitor count for a user."""
        return (
            session.query(BrandMonitor)
            .filter(BrandMonitor.user_id == user_id, BrandMonitor.is_active == True)
            .count()
        )

    @staticmethod
    def count_active(session: Session) -> int:
        """Return all active monitor count."""
        return session.query(BrandMonitor).filter(BrandMonitor.is_active == True).count()

    @staticmethod
    def set_active(
        session: Session,
        monitor: BrandMonitor,
        is_active: bool,
    ) -> BrandMonitor:
        """Enable or disable a monitor."""
        monitor.is_active = is_active
        session.commit()
        return monitor

    @staticmethod
    def mark_scanned(session: Session, monitor: BrandMonitor) -> BrandMonitor:
        """Record that a monitor has completed a scan."""
        monitor.last_scanned_at = datetime.utcnow()
        session.commit()
        return monitor


class ProductIgnoreRepository:
    """Repository for products excluded from discovery scans."""

    @staticmethod
    def is_ignored(
        session: Session,
        platform_id: int,
        platform_product_id: str,
    ) -> bool:
        """Return whether a platform product is actively ignored."""
        cleaned_product_id = str(platform_product_id or "").strip()
        if not cleaned_product_id:
            return False

        return (
            session.query(ProductIgnore)
            .filter(
                ProductIgnore.platform_id == platform_id,
                ProductIgnore.platform_product_id == cleaned_product_id,
                ProductIgnore.is_active == True,
            )
            .first()
            is not None
        )

    @staticmethod
    def ignore_product(
        session: Session,
        product: Product,
        created_by_user_id: int | None = None,
        reason: str | None = None,
    ) -> ProductIgnore:
        """Create or reactivate an ignore-list entry for a product."""
        existing = (
            session.query(ProductIgnore)
            .filter(
                ProductIgnore.platform_id == product.platform_id,
                ProductIgnore.platform_product_id == product.platform_product_id,
            )
            .first()
        )
        if existing is not None:
            existing.product_id = product.id
            existing.product_url = product.product_url
            existing.reason = reason
            existing.created_by_user_id = created_by_user_id
            existing.is_active = True
            session.commit()
            return existing

        ignored = ProductIgnore(
            platform_id=product.platform_id,
            product_id=product.id,
            platform_product_id=product.platform_product_id,
            product_url=product.product_url,
            reason=reason,
            created_by_user_id=created_by_user_id,
            is_active=True,
        )
        session.add(ignored)
        session.commit()
        return ignored


class ManualDiscoveryScanRepository:
    """Repository for admin-triggered discovery scans."""

    @staticmethod
    def create(
        session: Session,
        *,
        user_id: int,
        platform: str,
        brand_filters: str,
        size_filters: str,
    ) -> ManualDiscoveryScan:
        """Create a running manual discovery scan."""
        scan = ManualDiscoveryScan(
            user_id=user_id,
            platform=platform.strip().lower(),
            brand_filters=brand_filters,
            size_filters=size_filters,
            status="running",
        )
        session.add(scan)
        session.commit()
        return scan

    @staticmethod
    def get(session: Session, scan_id: int) -> ManualDiscoveryScan | None:
        """Return a manual discovery scan."""
        return (
            session.query(ManualDiscoveryScan)
            .filter(ManualDiscoveryScan.id == scan_id)
            .first()
        )

    @staticmethod
    def mark_complete(
        session: Session,
        scan: ManualDiscoveryScan,
        *,
        status: str,
        products_found: int = 0,
        products_matched: int = 0,
        errors: str | None = None,
    ) -> ManualDiscoveryScan:
        """Mark a manual discovery scan complete."""
        scan.status = status
        scan.products_found = products_found
        scan.products_matched = products_matched
        scan.errors = errors
        scan.completed_at = datetime.utcnow()
        session.commit()
        return scan

    @staticmethod
    def list_recent_for_user(
        session: Session,
        user_id: int,
        limit: int = 5,
    ) -> list[ManualDiscoveryScan]:
        """Return recent manual scans for a user."""
        return (
            session.query(ManualDiscoveryScan)
            .filter(ManualDiscoveryScan.user_id == user_id)
            .order_by(ManualDiscoveryScan.started_at.desc())
            .limit(limit)
            .all()
        )


class ManualDiscoveryResultRepository:
    """Repository for products matched during manual discovery scans."""

    @staticmethod
    def create(
        session: Session,
        *,
        scan_id: int,
        product_id: int,
        matched_brand: str,
        matched_sizes: str | None = None,
        current_price: float | None = None,
        discount_percentage: float | None = None,
    ) -> ManualDiscoveryResult:
        """Create or refresh one manual discovery result."""
        existing = (
            session.query(ManualDiscoveryResult)
            .filter(
                ManualDiscoveryResult.scan_id == scan_id,
                ManualDiscoveryResult.product_id == product_id,
            )
            .first()
        )
        if existing is not None:
            existing.matched_brand = matched_brand
            existing.matched_sizes = matched_sizes
            existing.current_price = current_price
            existing.discount_percentage = discount_percentage
            session.commit()
            return existing

        result = ManualDiscoveryResult(
            scan_id=scan_id,
            product_id=product_id,
            matched_brand=matched_brand,
            matched_sizes=matched_sizes,
            current_price=current_price,
            discount_percentage=discount_percentage,
        )
        session.add(result)
        session.commit()
        return result

    @staticmethod
    def get(session: Session, result_id: int) -> ManualDiscoveryResult | None:
        """Return a manual discovery result."""
        return (
            session.query(ManualDiscoveryResult)
            .filter(ManualDiscoveryResult.id == result_id)
            .first()
        )

    @staticmethod
    def list_for_scan(
        session: Session,
        scan_id: int,
        *,
        page: int = 1,
        page_size: int = 12,
        include_ignored: bool = False,
    ) -> tuple[list[ManualDiscoveryResult], int]:
        """Return one page of manual discovery results and the total count."""
        query = session.query(ManualDiscoveryResult).filter(
            ManualDiscoveryResult.scan_id == scan_id
        )
        if not include_ignored:
            query = query.filter(ManualDiscoveryResult.is_ignored == False)

        total = query.count()
        safe_page = max(page, 1)
        safe_page_size = max(min(page_size, 100), 1)
        results = (
            query.order_by(ManualDiscoveryResult.created_at.desc(), ManualDiscoveryResult.id.desc())
            .offset((safe_page - 1) * safe_page_size)
            .limit(safe_page_size)
            .all()
        )
        return results, total

    @staticmethod
    def set_tracked(
        session: Session,
        result: ManualDiscoveryResult,
        tracked: bool = True,
    ) -> ManualDiscoveryResult:
        """Mark a manual discovery result as tracked."""
        result.is_tracked = tracked
        session.commit()
        return result

    @staticmethod
    def set_ignored(
        session: Session,
        result: ManualDiscoveryResult,
        ignored: bool = True,
    ) -> ManualDiscoveryResult:
        """Mark a manual discovery result as ignored in its scan."""
        result.is_ignored = ignored
        session.commit()
        return result


class BrandMonitorScanRepository:
    """Repository for brand monitor scan runs."""

    @staticmethod
    def create(
        session: Session,
        monitor_id: int,
        query: str,
        scan_job_id: int | None = None,
    ) -> BrandMonitorScan:
        """Create a running monitor scan."""
        scan = BrandMonitorScan(
            monitor_id=monitor_id,
            scan_job_id=scan_job_id,
            query=query,
            status="running",
        )
        session.add(scan)
        session.commit()
        return scan

    @staticmethod
    def mark_complete(
        session: Session,
        scan: BrandMonitorScan,
        status: str,
        products_found: int = 0,
        products_matched: int = 0,
        new_products: int = 0,
        errors: str | None = None,
    ) -> BrandMonitorScan:
        """Mark a monitor scan complete."""
        scan.status = status
        scan.products_found = products_found
        scan.products_matched = products_matched
        scan.new_products = new_products
        scan.errors = errors
        scan.completed_at = datetime.utcnow()
        session.commit()
        return scan

    @staticmethod
    def list_recent(session: Session, limit: int = 10) -> list[BrandMonitorScan]:
        """Return recent monitor scans."""
        return (
            session.query(BrandMonitorScan)
            .order_by(BrandMonitorScan.started_at.desc())
            .limit(limit)
            .all()
        )


class BrandMonitorSeenProductRepository:
    """Repository for monitor seen-product ledger rows."""

    @staticmethod
    def get(
        session: Session,
        monitor_id: int,
        product_id: int,
    ) -> BrandMonitorSeenProduct | None:
        """Return a seen-product row if present."""
        return (
            session.query(BrandMonitorSeenProduct)
            .filter(
                BrandMonitorSeenProduct.monitor_id == monitor_id,
                BrandMonitorSeenProduct.product_id == product_id,
            )
            .first()
        )

    @staticmethod
    def upsert(
        session: Session,
        monitor_id: int,
        product_id: int,
        scan_id: int,
    ) -> tuple[BrandMonitorSeenProduct, bool]:
        """Create or refresh a seen-product row.

        Returns the row and whether it was newly created.
        """
        seen = BrandMonitorSeenProductRepository.get(session, monitor_id, product_id)
        if seen is not None:
            seen.last_scan_id = scan_id
            seen.last_seen_at = datetime.utcnow()
            session.commit()
            return seen, False

        seen = BrandMonitorSeenProduct(
            monitor_id=monitor_id,
            product_id=product_id,
            first_scan_id=scan_id,
            last_scan_id=scan_id,
        )
        session.add(seen)
        session.commit()
        return seen, True


class BrandMonitorScanResultRepository:
    """Repository for per-scan monitor product matches."""

    @staticmethod
    def create(
        session: Session,
        scan_id: int,
        monitor_id: int,
        product_id: int,
        is_new: bool,
        matched_sizes: str | None = None,
        current_price: float | None = None,
        discount_percentage: float | None = None,
    ) -> BrandMonitorScanResult:
        """Record one matched product for a monitor scan."""
        result = BrandMonitorScanResult(
            scan_id=scan_id,
            monitor_id=monitor_id,
            product_id=product_id,
            is_new=is_new,
            matched_sizes=matched_sizes,
            current_price=current_price,
            discount_percentage=discount_percentage,
        )
        session.add(result)
        session.commit()
        return result

    @staticmethod
    def list_recent(
        session: Session,
        limit: int = 20,
        user_id: int | None = None,
        new_only: bool = False,
    ) -> list[BrandMonitorScanResult]:
        """Return recent monitor scan result rows."""
        query = session.query(BrandMonitorScanResult).join(
            BrandMonitor,
            BrandMonitorScanResult.monitor_id == BrandMonitor.id,
        )
        if user_id is not None:
            query = query.filter(BrandMonitor.user_id == user_id)
        if new_only:
            query = query.filter(BrandMonitorScanResult.is_new == True)

        return (
            query.order_by(BrandMonitorScanResult.created_at.desc())
            .limit(limit)
            .all()
        )


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


class WatchlistRepository:
    """Repository for Watchlist rule operations."""

    @staticmethod
    def get_by_product_id(session: Session, product_id: int) -> Watchlist | None:
        """Return the watchlist rule for a product if it exists."""
        return session.query(Watchlist).filter(Watchlist.product_id == product_id).first()

    @staticmethod
    def list_active(session: Session) -> List[Watchlist]:
        """Return all active watchlist rules."""
        return session.query(Watchlist).filter(Watchlist.is_active == True).all()

    @staticmethod
    def upsert(
        session: Session,
        product_id: int,
        price_alert_threshold: Optional[float] = None,
        restock_alert: bool = True,
        notes: Optional[str] = None,
        is_active: bool = True,
    ) -> Watchlist:
        """Create or update a watchlist rule for a product."""
        watchlist = WatchlistRepository.get_by_product_id(session, product_id)
        if watchlist is None:
            watchlist = Watchlist(product_id=product_id)
            session.add(watchlist)

        watchlist.price_alert_threshold = price_alert_threshold
        watchlist.restock_alert = restock_alert
        watchlist.notes = notes
        watchlist.is_active = is_active
        session.commit()
        return watchlist

    @staticmethod
    def deactivate(session: Session, product_id: int) -> Watchlist | None:
        """Disable a watchlist rule without deleting it."""
        watchlist = WatchlistRepository.get_by_product_id(session, product_id)
        if watchlist is None:
            return None

        watchlist.is_active = False
        session.commit()
        return watchlist


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
