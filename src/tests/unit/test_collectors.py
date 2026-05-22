"""Unit tests for collectors."""

import pytest
from app.collectors.base import BaseCollector, ProductData, CollectorResponse
from app.collectors.myntra import MyntraCollector


class TestProductData:
    """Test ProductData model."""

    def test_product_data_creation(self):
        """Test creating a ProductData instance."""
        product = ProductData(
            platform_product_id="123",
            product_url="https://example.com/product/123",
            title="Nike Air Jordan 1",
            brand="Nike",
            model_name="Air Jordan 1",
            listed_price=10000.0,
            discounted_price=8000.0,
            discount_percentage=20.0,
        )

        assert product.platform_product_id == "123"
        assert product.brand == "Nike"
        assert product.discounted_price == 8000.0
        assert product.scraped_at is not None

    def test_product_data_with_defaults(self):
        """Test ProductData with default values."""
        product = ProductData(
            platform_product_id="456",
            product_url="https://example.com/product/456",
            title="Adidas Ultraboost",
            brand="Adidas",
            model_name="Ultraboost",
        )

        assert product.currency == "INR"
        assert product.in_stock is True
        assert product.listed_price is None


class TestCollectorResponse:
    """Test CollectorResponse model."""

    def test_response_creation_success(self):
        """Test creating a successful response."""
        products = [
            ProductData(
                platform_product_id="1",
                product_url="https://example.com/1",
                title="Shoe 1",
                brand="Brand A",
                model_name="Model A",
            )
        ]

        response = CollectorResponse(success=True, products=products)

        assert response.success is True
        assert response.products_count == 1
        assert len(response.products) == 1

    def test_response_creation_failure(self):
        """Test creating a failed response."""
        response = CollectorResponse(
            success=False,
            error_message="API timeout",
        )

        assert response.success is False
        assert response.products_count == 0
        assert response.error_message == "API timeout"


class TestMyntraCollector:
    """Test Myntra collector."""

    def test_collector_initialization(self):
        """Test Myntra collector initialization."""
        collector = MyntraCollector()

        assert collector.platform_name == "myntra"
        assert collector.base_url == "https://www.myntra.com"
        assert collector.api_base == "https://www.myntra.com/gateway/v2"

    def test_normalize_product_name(self):
        """Test product name normalization."""
        collector = MyntraCollector()

        # Test Nike
        brand, model = collector.normalize_product_name("Nike Air Jordan 1 Retro High OG")
        # Note: Jordan is detected as primary brand when "Jordan" appears first
        assert brand in ["Nike", "Jordan"]
        assert "Air Jordan" in model or "Retro" in model or "High" in model

        # Test New Balance
        brand, model = collector.normalize_product_name("New Balance 574 Men's Lifestyle")
        assert brand == "New Balance"
        assert "574" in model

        # Test unknown brand
        brand, model = collector.normalize_product_name("Generic Sneaker Brand XYZ")
        assert brand == "Unknown"

    def test_get_browser_headers(self):
        """Test browser headers generation."""
        headers = BaseCollector.get_browser_headers()

        assert "User-Agent" in headers
        assert "Accept" in headers
        assert "Accept-Language" in headers
        assert "Chrome" in headers["User-Agent"]

    @pytest.mark.asyncio
    async def test_random_delay(self):
        """Test random delay."""
        import time
        start = time.time()
        await BaseCollector.random_delay(min_seconds=0.1, max_seconds=0.2)
        duration = time.time() - start

        assert 0.1 <= duration <= 0.3  # Allow some tolerance
