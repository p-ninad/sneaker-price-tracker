"""Unit tests for tracking service."""

import pytest
from datetime import datetime
from app.services.tracking import (
    TrackingService,
    ChangeType,
    PriceChange,
    DiscountChange,
    StockChange,
    ProductChangeAnalysis,
)
from app.database.repository import (
    PlatformRepository,
    ProductRepository,
    AlertRepository,
)


class TestPriceChange:
    """Test PriceChange model."""
    
    def test_price_drop(self):
        """Test detecting price drop."""
        change = PriceChange(
            old_price=10000.0,
            new_price=8000.0,
            change_amount=-2000.0,
            change_percentage=-20.0,
        )
        
        assert change.is_drop() is True
        assert change.is_significant() is True  # Default threshold is 10%
    
    def test_price_increase(self):
        """Test detecting price increase."""
        change = PriceChange(
            old_price=8000.0,
            new_price=9000.0,
            change_amount=1000.0,
            change_percentage=12.5,
        )
        
        assert change.is_drop() is False
        assert change.is_significant() is True
    
    def test_insignificant_change(self):
        """Test insignificant price change."""
        change = PriceChange(
            old_price=10000.0,
            new_price=9800.0,
            change_amount=-200.0,
            change_percentage=-2.0,
        )
        
        assert change.is_drop() is True
        assert change.is_significant() is False  # Below 10% threshold
        assert change.is_significant(threshold_percent=5.0) is False
        assert change.is_significant(threshold_percent=1.0) is True


class TestStockChange:
    """Test StockChange model."""
    
    def test_became_available(self):
        """Test product becoming available."""
        change = StockChange(
            old_in_stock=False,
            new_in_stock=True,
            changed=True,
        )
        
        assert change.became_available() is True
        assert change.became_unavailable() is False
    
    def test_became_unavailable(self):
        """Test product becoming unavailable."""
        change = StockChange(
            old_in_stock=True,
            new_in_stock=False,
            changed=True,
        )
        
        assert change.became_available() is False
        assert change.became_unavailable() is True
    
    def test_no_change(self):
        """Test no stock change."""
        change = StockChange(
            old_in_stock=True,
            new_in_stock=True,
            changed=False,
        )
        
        assert change.became_available() is False
        assert change.became_unavailable() is False


class TestProductChangeAnalysis:
    """Test ProductChangeAnalysis model."""
    
    def test_has_changes(self, test_session):
        """Test detecting changes."""
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
        
        analysis = ProductChangeAnalysis(
            product=product,
            change_types=[ChangeType.PRICE_DROP],
            price_change=PriceChange(1000, 800, -200, -20),
        )
        
        assert analysis.has_changes() is True
        assert ChangeType.PRICE_DROP in analysis.change_types
    
    def test_should_notify_price_drop(self, test_session):
        """Test notification for significant price drop."""
        platform = PlatformRepository.create(
            test_session,
            name="notify_test",
            display_name="Notify Test",
            base_url="https://test.com",
        )
        
        product = ProductRepository.create_or_update(
            test_session,
            platform_id=platform.id,
            product_url="https://test.com/notify",
            platform_product_id="notify",
            brand="Nike",
            model_name="Test",
            title="Test",
            discounted_price=5000.0,
        )
        
        analysis = ProductChangeAnalysis(
            product=product,
            change_types=[ChangeType.PRICE_DROP],
            price_change=PriceChange(
                old_price=10000.0,
                new_price=8000.0,
                change_amount=-2000.0,
                change_percentage=-20.0,
            ),
        )
        
        assert analysis.should_notify() is True


class TestTrackingService:
    """Test TrackingService."""
    
    @pytest.fixture
    def service(self):
        """Create tracking service instance."""
        return TrackingService()
    
    @pytest.fixture
    def product_with_platform(self, test_session):
        """Create product for testing."""
        platform = PlatformRepository.create(
            test_session,
            name="tracking_test",
            display_name="Tracking Test",
            base_url="https://test.com",
        )
        
        product = ProductRepository.create_or_update(
            test_session,
            platform_id=platform.id,
            product_url="https://test.com/tracking",
            platform_product_id="tracking",
            brand="Adidas",
            model_name="Ultraboost",
            title="Adidas Ultraboost",
            listed_price=12000.0,
            discounted_price=10000.0,
            in_stock=True,
            sizes_available='["6", "7", "8", "9"]',
        )
        
        return product
    
    def test_analyze_price_drop(self, service, test_session, product_with_platform):
        """Test analyzing price drop."""
        analysis = service.analyze_product_update(
            test_session,
            product_with_platform,
            new_listed_price=12000.0,
            new_discounted_price=8000.0,
            new_discount_percentage=33.33,
            new_in_stock=True,
            new_sizes_available='["6", "7", "8", "9"]',
        )
        
        assert analysis.has_changes() is True
        assert ChangeType.PRICE_DROP in analysis.change_types
        assert analysis.price_change is not None
        assert analysis.price_change.old_price == 10000.0
        assert analysis.price_change.new_price == 8000.0
        assert analysis.price_change.change_percentage == -20.0
    
    def test_analyze_stock_change_to_unavailable(
        self, service, test_session, product_with_platform
    ):
        """Test detecting stock change to unavailable."""
        analysis = service.analyze_product_update(
            test_session,
            product_with_platform,
            new_listed_price=12000.0,
            new_discounted_price=10000.0,
            new_discount_percentage=16.67,
            new_in_stock=False,
            new_sizes_available=None,
        )
        
        assert ChangeType.OUT_OF_STOCK in analysis.change_types
        assert analysis.stock_change is not None
        assert analysis.stock_change.became_unavailable() is True
    
    def test_analyze_stock_change_to_available(
        self, service, test_session, product_with_platform
    ):
        """Test detecting stock change to available."""
        # First make it unavailable
        product_with_platform.in_stock = False
        test_session.commit()
        
        # Now check becoming available
        analysis = service.analyze_product_update(
            test_session,
            product_with_platform,
            new_listed_price=12000.0,
            new_discounted_price=10000.0,
            new_discount_percentage=16.67,
            new_in_stock=True,
            new_sizes_available='["6", "7", "8"]',
        )
        
        assert ChangeType.BACK_IN_STOCK in analysis.change_types
        assert analysis.stock_change is not None
        assert analysis.stock_change.became_available() is True
    
    def test_analyze_size_changes(self, service, test_session, product_with_platform):
        """Test detecting size availability changes."""
        analysis = service.analyze_product_update(
            test_session,
            product_with_platform,
            new_listed_price=12000.0,
            new_discounted_price=10000.0,
            new_discount_percentage=16.67,
            new_in_stock=True,
            new_sizes_available='["7", "8", "9", "10"]',
        )
        
        assert ChangeType.SIZE_AVAILABILITY_CHANGED in analysis.change_types
        assert analysis.size_changes is not None
        assert "6" in analysis.size_changes["removed"]
        assert "10" in analysis.size_changes["added"]
    
    def test_create_alerts_for_price_drop(self, service, test_session, product_with_platform):
        """Test creating alerts for price drop."""
        analysis = service.analyze_product_update(
            test_session,
            product_with_platform,
            new_listed_price=12000.0,
            new_discounted_price=8000.0,
            new_discount_percentage=33.33,
            new_in_stock=True,
            new_sizes_available='["6", "7", "8", "9"]',
        )
        
        alerts = service.create_alerts_from_analysis(test_session, analysis)
        
        # Should have price drop alert
        price_drop_alerts = [a for a in alerts if a.alert_type == "price_drop"]
        assert len(price_drop_alerts) > 0
        assert "₹" in price_drop_alerts[0].message
    
    def test_create_alerts_for_restock(self, service, test_session, product_with_platform):
        """Test creating alerts for restock."""
        product_with_platform.in_stock = False
        test_session.commit()
        
        analysis = service.analyze_product_update(
            test_session,
            product_with_platform,
            new_listed_price=12000.0,
            new_discounted_price=10000.0,
            new_discount_percentage=16.67,
            new_in_stock=True,
            new_sizes_available='["6", "7", "8"]',
        )
        
        alerts = service.create_alerts_from_analysis(test_session, analysis)
        
        # Should have restock alert
        restock_alerts = [a for a in alerts if a.alert_type == "restock"]
        assert len(restock_alerts) > 0
    
    def test_record_price_snapshot(self, service, test_session, product_with_platform):
        """Test recording price snapshot."""
        snapshot = service.record_price_snapshot(
            test_session,
            product_with_platform,
            listed_price=12000.0,
            discounted_price=9500.0,
            discount_percentage=20.83,
        )
        
        assert snapshot.product_id == product_with_platform.id
        assert snapshot.discounted_price == 9500.0
        assert snapshot.recorded_at is not None
    
    def test_record_stock_snapshot(self, service, test_session, product_with_platform):
        """Test recording stock snapshot."""
        snapshot = service.record_stock_snapshot(
            test_session,
            product_with_platform,
            in_stock=True,
            sizes_available='["6", "7"]',
        )
        
        assert snapshot.product_id == product_with_platform.id
        assert snapshot.in_stock is True
    
    def test_get_price_trend(self, service, test_session, product_with_platform):
        """Test getting price trend."""
        # Record multiple snapshots
        service.record_price_snapshot(
            test_session, product_with_platform, 12000.0, 10000.0, 16.67
        )
        service.record_price_snapshot(
            test_session, product_with_platform, 12000.0, 9500.0, 20.83
        )
        service.record_price_snapshot(
            test_session, product_with_platform, 12000.0, 9000.0, 25.0
        )
        
        trend = service.get_price_trend(test_session, product_with_platform.id)
        
        assert trend is not None
        assert trend["snapshots"] == 3
        assert trend["min_price"] == 9000.0
        assert trend["max_price"] == 10000.0
        assert trend["current_price"] == 9000.0
        assert trend["price_change"] == -1000.0
