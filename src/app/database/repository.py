"""Data access layer for database operations."""

from datetime import datetime, timedelta
from typing import List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import desc, and_, or_
from app.database.models import (
    AuthSession,
    Platform,
    Product,
    PriceSnapshot,
    StockSnapshot,
    Alert,
    ScanJob,
    User,
    Watchlist,
    WishlistEntry,
)
from app.utils.logger import get_logger
from app.auth.tokens import hash_token

logger = get_logger(__name__)


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
