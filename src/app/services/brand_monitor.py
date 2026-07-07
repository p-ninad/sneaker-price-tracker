"""Services for brand/platform launch monitors."""

from __future__ import annotations

import json
import re
from typing import Iterable

from sqlalchemy.orm import Session

from app.collectors.base import ProductData
from app.database.models import BrandMonitor, Product
from app.database.repository import (
    BrandMonitorRepository,
    PlatformRepository,
    PriceSnapshotRepository,
    ProductRepository,
    StockSnapshotRepository,
)
from app.utils.url_parser import extract_product_id_from_url


class BrandMonitorService:
    """Manage user-defined product discovery monitors."""

    DEFAULT_PLATFORM = "myntra"

    @staticmethod
    def _normalize_json_list(values: Iterable[str] | None) -> str | None:
        if values is None:
            return None

        normalized: list[str] = []
        for value in values:
            cleaned = str(value).strip()
            if cleaned and cleaned not in normalized:
                normalized.append(cleaned)

        return json.dumps(normalized) if normalized else None

    @staticmethod
    def _read_json_list(value: str | None) -> list[str]:
        if not value:
            return []

        try:
            parsed = json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return []

        if not isinstance(parsed, list):
            return []

        return [str(item).strip() for item in parsed if str(item).strip()]

    @staticmethod
    def _normalize_text(value: str | None) -> str:
        return re.sub(r"\s+", " ", str(value or "").strip().lower())

    @staticmethod
    def _tokens(value: str | None) -> set[str]:
        return set(re.findall(r"[a-z0-9.]+", BrandMonitorService._normalize_text(value)))

    @staticmethod
    def _normalize_size_token(size_value: str) -> str:
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
    def _parse_sizes(sizes_available) -> list[str]:
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
    def _token_subset(expected: set[str], actual: set[str]) -> bool:
        for token in expected:
            variants = {token}
            if token.endswith("s") and len(token) > 3:
                variants.add(token[:-1])
            else:
                variants.add(f"{token}s")
            if not variants.intersection(actual):
                return False
        return True

    @staticmethod
    def get_query_terms(monitor: BrandMonitor) -> list[str]:
        """Return configured query/filter terms for a monitor."""
        return BrandMonitorService._read_json_list(monitor.query_terms)

    @staticmethod
    def get_size_scope(monitor: BrandMonitor) -> list[str]:
        """Return configured size scope for a monitor."""
        return BrandMonitorService._read_json_list(monitor.size_scope)

    @staticmethod
    def current_price(product_data: ProductData | Product) -> float | None:
        """Return the effective current price."""
        discounted_price = getattr(product_data, "discounted_price", None)
        listed_price = getattr(product_data, "listed_price", None)
        return discounted_price if discounted_price is not None else listed_price

    @staticmethod
    def build_discovery_query(monitor: BrandMonitor) -> str:
        """Build the platform search query for a monitor."""
        parts = [monitor.brand]
        parts.extend(BrandMonitorService.get_query_terms(monitor))
        return " ".join(part for part in parts if str(part).strip())

    @staticmethod
    def add_monitor(
        session: Session,
        *,
        user_id: int,
        platform: str,
        brand: str,
        query_terms: Iterable[str] | None = None,
        size_scope: Iterable[str] | None = None,
        min_discount_percentage: float | None = None,
        max_price: float | None = None,
        require_in_stock: bool = True,
        notes: str | None = None,
    ) -> BrandMonitor:
        """Create a launch monitor from structured user input."""
        return BrandMonitorRepository.create(
            session,
            user_id=user_id,
            platform=platform or BrandMonitorService.DEFAULT_PLATFORM,
            brand=brand,
            query_terms=BrandMonitorService._normalize_json_list(query_terms),
            size_scope=BrandMonitorService._normalize_json_list(size_scope),
            min_discount_percentage=min_discount_percentage,
            max_price=max_price,
            require_in_stock=require_in_stock,
            notes=notes,
        )

    @staticmethod
    def product_matches_monitor(
        monitor: BrandMonitor,
        product_data: ProductData,
    ) -> tuple[bool, list[str]]:
        """Return whether product data satisfies a monitor and which sizes matched."""
        haystack = " ".join(
            [
                product_data.brand or "",
                product_data.model_name or "",
                product_data.title or "",
                product_data.description or "",
            ]
        )
        actual_tokens = BrandMonitorService._tokens(haystack)

        brand_tokens = BrandMonitorService._tokens(monitor.brand)
        if brand_tokens and not BrandMonitorService._token_subset(brand_tokens, actual_tokens):
            return False, []

        query_terms = BrandMonitorService.get_query_terms(monitor)
        query_tokens = BrandMonitorService._tokens(" ".join(query_terms))
        if query_tokens and not BrandMonitorService._token_subset(query_tokens, actual_tokens):
            return False, []

        if monitor.require_in_stock and not product_data.in_stock:
            return False, []

        available_sizes = BrandMonitorService._parse_sizes(product_data.sizes_available)
        available_normalized = {
            BrandMonitorService._normalize_size_token(size): size
            for size in available_sizes
            if BrandMonitorService._normalize_size_token(size)
        }

        size_scope = BrandMonitorService.get_size_scope(monitor)
        if size_scope:
            matched_sizes = []
            for size in size_scope:
                normalized = BrandMonitorService._normalize_size_token(size)
                if normalized in available_normalized:
                    matched_sizes.append(available_normalized[normalized])

            if not matched_sizes:
                return False, []
        else:
            matched_sizes = available_sizes

        current_price = BrandMonitorService.current_price(product_data)
        if monitor.max_price is not None:
            if current_price is None or current_price > monitor.max_price:
                return False, []

        if monitor.min_discount_percentage is not None:
            discount = product_data.discount_percentage
            if discount is None or discount < monitor.min_discount_percentage:
                return False, []

        return True, matched_sizes

    @staticmethod
    def upsert_scanned_product(
        session: Session,
        *,
        platform_name: str,
        platform_base_url: str,
        product_data: ProductData,
    ) -> Product:
        """Persist a discovered product and record price/stock snapshots."""
        platform = PlatformRepository.get_by_name(session, platform_name)
        if platform is None:
            platform = PlatformRepository.create(
                session,
                name=platform_name,
                display_name=platform_name.title(),
                base_url=platform_base_url,
            )

        platform_product_id = (
            product_data.platform_product_id
            or extract_product_id_from_url(product_data.product_url)
            or product_data.product_url
        )
        if not platform_product_id:
            raise ValueError("product_data must include a product id or URL")

        sizes_available = (
            json.dumps(product_data.sizes_available)
            if product_data.sizes_available is not None
            else None
        )
        product = ProductRepository.create_or_update(
            session,
            platform_id=platform.id,
            product_url=product_data.product_url,
            platform_product_id=platform_product_id,
            brand=product_data.brand,
            model_name=product_data.model_name,
            title=product_data.title,
            listed_price=product_data.listed_price,
            discounted_price=product_data.discounted_price,
            discount_percentage=product_data.discount_percentage,
            currency=product_data.currency,
            in_stock=product_data.in_stock,
            sizes_available=sizes_available,
            image_url=product_data.image_url,
            sku=product_data.sku,
        )

        PriceSnapshotRepository.create(
            session,
            product.id,
            product.listed_price,
            product.discounted_price,
            product.discount_percentage,
            product.currency,
        )
        StockSnapshotRepository.create(
            session,
            product.id,
            product.in_stock,
            product.sizes_available,
        )
        return product

    @staticmethod
    def describe_monitor(monitor: BrandMonitor) -> str:
        """Return a concise human-readable monitor description."""
        parts = [f"{monitor.brand} on {monitor.platform}"]
        query_terms = BrandMonitorService.get_query_terms(monitor)
        if query_terms:
            parts.append(f"terms: {', '.join(query_terms)}")
        size_scope = BrandMonitorService.get_size_scope(monitor)
        if size_scope:
            parts.append(f"sizes: {', '.join(size_scope)}")
        if monitor.min_discount_percentage is not None:
            parts.append(f"min discount: {monitor.min_discount_percentage:g}%")
        if monitor.max_price is not None:
            parts.append(f"max price: Rs {monitor.max_price:g}")
        return " | ".join(parts)
