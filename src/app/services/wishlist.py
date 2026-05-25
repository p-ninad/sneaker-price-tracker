"""Wishlist services for ingesting user-selected products."""

import json
import re
from typing import Iterable, Optional

from sqlalchemy.orm import Session

from app.database.models import WishlistEntry
from app.database.repository import ProductRepository
from app.utils.logger import get_logger
from app.utils.url_parser import extract_platform_from_url

logger = get_logger(__name__)


class WishlistService:
    """Service for managing wishlist entries."""

    @staticmethod
    def _normalize_name(value: str) -> str:
        normalized = re.sub(r"\s+", " ", value.strip().lower())
        return normalized

    @staticmethod
    def _normalize_size_scope(size_scope: Optional[Iterable[str]]) -> list[str]:
        if size_scope is None:
            return ["11", "11.5", "12", "12.5"]

        normalized = []
        for size in size_scope:
            cleaned = str(size).strip()
            if cleaned:
                normalized.append(cleaned)

        if not normalized:
            return ["11", "11.5", "12", "12.5"]

        return normalized

    @staticmethod
    def _normalize_platforms(platforms_to_track: Optional[Iterable[str]], fallback: str) -> list[str]:
        if platforms_to_track is None:
            return [fallback]

        normalized = []
        for platform in platforms_to_track:
            cleaned = str(platform).strip().lower()
            if cleaned and cleaned not in normalized:
                normalized.append(cleaned)

        if not normalized:
            return [fallback]

        return normalized

    @staticmethod
    def add_from_url(
        session: Session,
        url: str,
        brand: str,
        model_name: str,
        title: str,
        platforms_to_track: Optional[Iterable[str]] = None,
        size_scope: Optional[Iterable[str]] = None,
        notes: Optional[str] = None,
    ) -> WishlistEntry:
        """Add a wishlist entry from a product URL and metadata."""
        platform = extract_platform_from_url(url)
        if not platform:
            raise ValueError("Unsupported product URL")

        if not brand or not model_name or not title:
            raise ValueError("brand, model_name, and title are required")

        normalized_name = WishlistService._normalize_name(f"{brand} {model_name}")
        size_scope_value = WishlistService._normalize_size_scope(size_scope)
        platforms_value = WishlistService._normalize_platforms(platforms_to_track, platform)

        existing = session.query(WishlistEntry).filter(WishlistEntry.source_url == url).first()
        if existing:
            existing.platform = platform
            existing.brand = brand
            existing.model_name = model_name
            existing.normalized_name = normalized_name
            existing.title = title
            existing.size_scope = json.dumps(size_scope_value)
            existing.platforms_to_track = json.dumps(platforms_value)
            existing.notes = notes
            existing.is_active = True
            session.commit()
            logger.info("wishlist_entry_updated", source_url=url, normalized_name=normalized_name)
            return existing

        wishlist_entry = WishlistEntry(
            source_url=url,
            platform=platform,
            brand=brand,
            model_name=model_name,
            normalized_name=normalized_name,
            title=title,
            size_scope=json.dumps(size_scope_value),
            platforms_to_track=json.dumps(platforms_value),
            notes=notes,
            is_active=True,
        )

        session.add(wishlist_entry)
        session.commit()
        logger.info("wishlist_entry_added", source_url=url, normalized_name=normalized_name)
        return wishlist_entry

    @staticmethod
    def get_active(session: Session) -> list[WishlistEntry]:
        return (
            session.query(WishlistEntry)
            .filter(WishlistEntry.is_active == True)
            .order_by(WishlistEntry.created_at.desc())
            .all()
        )

    @staticmethod
    def get_all(session: Session) -> list[WishlistEntry]:
        """Return all wishlist entries sorted by newest first."""
        return session.query(WishlistEntry).order_by(WishlistEntry.created_at.desc()).all()

    @staticmethod
    def get_by_url(session: Session, url: str) -> WishlistEntry | None:
        """Return a wishlist entry by source URL if it exists."""
        return session.query(WishlistEntry).filter(WishlistEntry.source_url == url).first()

    @staticmethod
    def set_active(session: Session, url: str, is_active: bool) -> WishlistEntry | None:
        """Enable or disable an existing wishlist entry."""
        wishlist_entry = WishlistService.get_by_url(session, url)
        if wishlist_entry is None:
            return None

        wishlist_entry.is_active = is_active
        session.commit()
        return wishlist_entry

    @staticmethod
    def delete(session: Session, url: str) -> bool:
        """Delete a wishlist entry by source URL."""
        wishlist_entry = WishlistService.get_by_url(session, url)
        if wishlist_entry is None:
            return False

        session.delete(wishlist_entry)
        session.commit()
        return True

    @staticmethod
    def get_size_scope(wishlist_entry: WishlistEntry) -> list[str]:
        """Return the configured size scope for a wishlist entry."""
        if not wishlist_entry.size_scope:
            return ["11", "11.5", "12", "12.5"]

        try:
            parsed = json.loads(wishlist_entry.size_scope)
        except (TypeError, json.JSONDecodeError):
            return ["11", "11.5", "12", "12.5"]

        return [str(size).strip() for size in parsed if str(size).strip()]

    @staticmethod
    def get_platforms_to_track(wishlist_entry: WishlistEntry) -> list[str]:
        """Return the configured platforms for a wishlist entry."""
        if not wishlist_entry.platforms_to_track:
            return [wishlist_entry.platform]

        try:
            parsed = json.loads(wishlist_entry.platforms_to_track)
        except (TypeError, json.JSONDecodeError):
            return [wishlist_entry.platform]

        normalized = [str(platform).strip().lower() for platform in parsed if str(platform).strip()]
        return normalized or [wishlist_entry.platform]

    @staticmethod
    def find_exact_matches(session: Session, wishlist_entry: WishlistEntry) -> list:
        """Return exact product matches for a wishlist entry."""
        return ProductRepository.search_by_brand_model(
            session,
            wishlist_entry.brand,
            wishlist_entry.model_name,
        )
