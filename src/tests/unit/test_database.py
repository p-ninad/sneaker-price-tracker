"""Unit tests for database operations."""

import pytest
from datetime import datetime
from app.database.repository import (
    PlatformRepository,
    ProductRepository,
    PriceSnapshotRepository,
    AlertRepository,
)


class TestPlatformRepository:
    """Test Platform repository operations."""

    def test_create_platform(self, test_session):
        """Test creating a platform."""
        platform = PlatformRepository.create(
            test_session,
            name="myntra",
            display_name="Myntra",
            base_url="https://www.myntra.com",
        )

        assert platform.name == "myntra"
        assert platform.display_name == "Myntra"
        assert platform.is_active is True

    def test_get_platform_by_name(self, test_session):
        """Test getting platform by name."""
        # Create platform
        PlatformRepository.create(
            test_session,
            name="ajio",
            display_name="AJIO",
            base_url="https://www.ajio.com",
        )

        # Retrieve
        platform = PlatformRepository.get_by_name(test_session, "ajio")
        assert platform is not None
        assert platform.name == "ajio"

    def test_get_nonexistent_platform(self, test_session):
        """Test getting nonexistent platform."""
        platform = PlatformRepository.get_by_name(test_session, "nonexistent")
        assert platform is None

    def test_get_all_active_platforms(self, test_session):
        """Test getting all active platforms."""
        # Create multiple platforms
        PlatformRepository.create(test_session, "myntra", "Myntra", "https://myntra.com")
        PlatformRepository.create(test_session, "ajio", "AJIO", "https://ajio.com")

        # Retrieve all
        platforms = PlatformRepository.get_all_active(test_session)
        assert len(platforms) == 2


class TestProductRepository:
    """Test Product repository operations."""

    @pytest.fixture
    def platform(self, test_session):
        """Create a platform for testing."""
        return PlatformRepository.create(
            test_session,
            name="myntra",
            display_name="Myntra",
            base_url="https://www.myntra.com",
        )

    def test_create_product(self, test_session, platform):
        """Test creating a product."""
        product = ProductRepository.create_or_update(
            test_session,
            platform_id=platform.id,
            product_url="https://myntra.com/shoes/123",
            platform_product_id="123",
            brand="Nike",
            model_name="Air Jordan 1",
            title="Nike Air Jordan 1 Retro",
            listed_price=10000.0,
            discounted_price=8000.0,
        )

        assert product.brand == "Nike"
        assert product.model_name == "Air Jordan 1"
        assert product.discounted_price == 8000.0
        assert product.is_active is True

    def test_update_existing_product(self, test_session, platform):
        """Test updating an existing product."""
        # Create initial product
        product = ProductRepository.create_or_update(
            test_session,
            platform_id=platform.id,
            product_url="https://myntra.com/shoes/456",
            platform_product_id="456",
            brand="Adidas",
            model_name="Ultraboost",
            title="Adidas Ultraboost",
            listed_price=12000.0,
            discounted_price=10000.0,
        )

        product_id = product.id

        # Update
        updated_product = ProductRepository.create_or_update(
            test_session,
            platform_id=platform.id,
            product_url="https://myntra.com/shoes/456",
            platform_product_id="456",
            brand="Adidas",
            model_name="Ultraboost",
            title="Adidas Ultraboost",
            listed_price=12000.0,
            discounted_price=9000.0,  # Price changed
        )

        # Verify ID is same
        assert updated_product.id == product_id
        # Verify price was updated
        assert updated_product.discounted_price == 9000.0


class TestPriceSnapshotRepository:
    """Test PriceSnapshot repository operations."""

    @pytest.fixture
    def product_with_platform(self, test_session):
        """Create a product for testing."""
        platform = PlatformRepository.create(
            test_session,
            name="test_platform",
            display_name="Test",
            base_url="https://test.com",
        )

        product = ProductRepository.create_or_update(
            test_session,
            platform_id=platform.id,
            product_url="https://test.com/1",
            platform_product_id="1",
            brand="Test Brand",
            model_name="Test Model",
            title="Test Product",
            listed_price=1000.0,
            discounted_price=800.0,
        )

        return product

    def test_create_price_snapshot(self, test_session, product_with_platform):
        """Test creating a price snapshot."""
        snapshot = PriceSnapshotRepository.create(
            test_session,
            product_id=product_with_platform.id,
            listed_price=1000.0,
            discounted_price=800.0,
            discount_percentage=20.0,
        )

        assert snapshot.product_id == product_with_platform.id
        assert snapshot.discounted_price == 800.0

    def test_get_last_n_snapshots(self, test_session, product_with_platform):
        """Test retrieving last N snapshots."""
        # Create multiple snapshots
        for i in range(5):
            PriceSnapshotRepository.create(
                test_session,
                product_id=product_with_platform.id,
                listed_price=1000.0 + i * 100,
                discounted_price=800.0 + i * 100,
                discount_percentage=20.0,
            )

        # Get last 3
        snapshots = PriceSnapshotRepository.get_last_n(
            test_session,
            product_with_platform.id,
            n=3,
        )

        assert len(snapshots) == 3


class TestAlertRepository:
    """Test Alert repository operations."""

    @pytest.fixture
    def product_with_platform(self, test_session):
        """Create a product for testing."""
        platform = PlatformRepository.create(
            test_session,
            name="alert_test_platform",
            display_name="Alert Test",
            base_url="https://test.com",
        )

        product = ProductRepository.create_or_update(
            test_session,
            platform_id=platform.id,
            product_url="https://test.com/alert_test",
            platform_product_id="alert_test",
            brand="Alert Brand",
            model_name="Alert Model",
            title="Alert Test Product",
        )

        return product

    def test_create_alert(self, test_session, product_with_platform):
        """Test creating an alert."""
        alert = AlertRepository.create(
            test_session,
            product_id=product_with_platform.id,
            alert_type="price_drop",
            message="Price dropped!",
        )

        assert alert.product_id == product_with_platform.id
        assert alert.alert_type == "price_drop"
        assert alert.notified_at is None

    def test_get_unnotified_alerts(self, test_session, product_with_platform):
        """Test retrieving unnotified alerts."""
        # Create multiple alerts
        AlertRepository.create(
            test_session,
            product_id=product_with_platform.id,
            alert_type="price_drop",
            message="Alert 1",
        )
        AlertRepository.create(
            test_session,
            product_id=product_with_platform.id,
            alert_type="new_product",
            message="Alert 2",
        )

        # Get unnotified
        alerts = AlertRepository.get_unnotified(test_session)
        assert len(alerts) == 2

    def test_mark_alert_notified(self, test_session, product_with_platform):
        """Test marking alert as notified."""
        alert = AlertRepository.create(
            test_session,
            product_id=product_with_platform.id,
            alert_type="price_drop",
            message="Test alert",
        )

        assert alert.notified_at is None

        AlertRepository.mark_notified(test_session, alert)

        assert alert.notified_at is not None
