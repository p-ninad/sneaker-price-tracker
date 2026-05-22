"""Base collector abstract class and utilities."""

from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import asyncio
import random
from app.utils.logger import get_logger
from app.config import settings

logger = get_logger(__name__)


class SizeAvailability(Enum):
    """Size availability status."""
    IN_STOCK = "in_stock"
    OUT_OF_STOCK = "out_of_stock"
    LIMITED = "limited"


@dataclass
class ProductData:
    """Normalized product data returned by collectors."""

    platform_product_id: str  # Internal ID from platform
    product_url: str
    title: str
    brand: str
    model_name: str  # Normalized sneaker name

    listed_price: Optional[float] = None
    discounted_price: Optional[float] = None
    currency: str = "INR"
    discount_percentage: Optional[float] = None

    in_stock: bool = True
    sizes_available: Optional[List[str]] = None

    image_url: Optional[str] = None
    description: Optional[str] = None
    sku: Optional[str] = None

    scraped_at: datetime = None

    def __post_init__(self):
        if self.scraped_at is None:
            self.scraped_at = datetime.utcnow()


@dataclass
class CollectorResponse:
    """Response from collector operations."""

    success: bool
    products: List[ProductData] = None
    error_message: Optional[str] = None
    products_count: int = 0
    duration_seconds: float = 0

    def __post_init__(self):
        if self.products is None:
            self.products = []
        self.products_count = len(self.products)


class BaseCollector(ABC):
    """Abstract base class for all platform collectors."""

    def __init__(self, platform_name: str, base_url: str):
        """Initialize collector.

        Args:
            platform_name: Unique identifier (e.g., 'myntra', 'ajio')
            base_url: Platform base URL
        """
        self.platform_name = platform_name
        self.base_url = base_url
        self.logger = get_logger(f"collectors.{platform_name}")

    async def health_check(self) -> bool:
        """Check if platform is accessible.

        Returns:
            True if platform is reachable and responding.
        """
        try:
            # Default: try to access base URL
            import httpx
            async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
                response = await client.get(self.base_url, follow_redirects=True)
                return response.status_code == 200
        except Exception as e:
            self.logger.error("Health check failed", error=str(e), platform=self.platform_name)
            return False

    @abstractmethod
    async def discover_products(self, query: str = "sneaker", limit: int = 100) -> CollectorResponse:
        """Discover sneaker products from platform.

        Args:
            query: Search query (e.g., 'New Balance', 'Adidas')
            limit: Maximum products to return

        Returns:
            CollectorResponse with discovered products
        """
        pass

    @abstractmethod
    async def fetch_product_details(self, product_id: str) -> Optional[ProductData]:
        """Fetch detailed information for a specific product.

        Args:
            product_id: Platform-specific product ID

        Returns:
            ProductData or None if not found
        """
        pass

    @staticmethod
    async def random_delay(
        min_seconds: float = None,
        max_seconds: float = None,
    ) -> None:
        """Sleep for random duration to avoid bot detection.

        Args:
            min_seconds: Minimum delay (defaults to config)
            max_seconds: Maximum delay (defaults to config)
        """
        if min_seconds is None:
            min_seconds = settings.min_delay_between_requests_seconds
        if max_seconds is None:
            max_seconds = settings.max_delay_between_requests_seconds

        delay = random.uniform(min_seconds, max_seconds)
        await asyncio.sleep(delay)

    @staticmethod
    def get_browser_headers() -> Dict[str, str]:
        """Get realistic browser headers."""
        return {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9,hi;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        }

    def normalize_product_name(self, raw_title: str) -> tuple[str, str]:
        """Normalize product title to brand and model.

        This is a deterministic first attempt.
        AI-assisted fallback comes later.

        Args:
            raw_title: Raw product title from platform

        Returns:
            Tuple of (brand, model_name)
        """
        title_lower = raw_title.lower().strip()

        # Simple heuristic normalization
        # TODO: Build comprehensive mapping for Indian market
        brands = {
            "nike": ["nike", "nk"],
            "adidas": ["adidas", "adidas originals"],
            "new balance": ["new balance", "nb"],
            "puma": ["puma"],
            "reebok": ["reebok"],
            "saucony": ["saucony"],
            "hoka": ["hoka"],
            "asics": ["asics"],
            "salomon": ["salomon"],
            "converse": ["converse"],
            "jordan": ["jordan", "air jordan"],
        }

        detected_brand = "Unknown"
        for brand_key, aliases in brands.items():
            for alias in aliases:
                if alias in title_lower:
                    detected_brand = brand_key.title()
                    break

        # Remove brand and common words from title to get model
        model = raw_title
        for brand_key, aliases in brands.items():
            for alias in aliases:
                model = model.replace(alias, "").replace(alias.title(), "")

        # Clean up
        model = " ".join(model.split())[:100]  # Max 100 chars

        return detected_brand, model if model else raw_title[:100]

    async def validate_response(self, response: CollectorResponse) -> bool:
        """Validate collector response.

        Args:
            response: CollectorResponse to validate

        Returns:
            True if response is valid
        """
        if not response.success:
            return False

        if not response.products:
            self.logger.warning(f"No products found for {self.platform_name}")
            return True  # Still valid, just empty

        # Validate each product
        for product in response.products:
            if not product.platform_product_id or not product.product_url:
                self.logger.warning(
                    f"Invalid product data: {product}",
                    platform=self.platform_name,
                )
                return False

        return True


class CollectorRegistry:
    """Registry for managing collectors."""

    def __init__(self):
        self.collectors: Dict[str, BaseCollector] = {}

    def register(self, collector: BaseCollector) -> None:
        """Register a collector."""
        self.collectors[collector.platform_name] = collector

    def get(self, platform_name: str) -> Optional[BaseCollector]:
        """Get collector by platform name."""
        return self.collectors.get(platform_name.lower())

    def get_all(self) -> List[BaseCollector]:
        """Get all collectors."""
        return list(self.collectors.values())

    def get_enabled(self) -> List[BaseCollector]:
        """Get collectors for enabled platforms."""
        enabled_platforms = settings.enabled_platforms_list
        return [
            c for c in self.collectors.values()
            if c.platform_name in enabled_platforms
        ]
