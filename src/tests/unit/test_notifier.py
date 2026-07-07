"""Unit tests for Telegram notifier."""

import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from telegram.error import TelegramError

from app.notifier.telegram import TelegramNotifier, NotificationService
from app.database.models import Alert, Product, Platform


@pytest.fixture
def mock_platform():
    """Create a mock platform."""
    platform = MagicMock(spec=Platform)
    platform.id = 1
    platform.name = "myntra"
    platform.display_name = "Myntra"
    return platform


@pytest.fixture
def mock_product(mock_platform):
    """Create a mock product."""
    product = MagicMock(spec=Product)
    product.id = 1
    product.platform_id = 1
    product.platform = mock_platform
    product.brand = "Nike"
    product.model_name = "Air Jordan 1"
    product.title = "Nike Air Jordan 1 Retro High"
    product.product_url = "https://myntra.com/shoes/123"
    product.discounted_price = 8999.0
    product.listed_price = 12000.0
    product.discount_percentage = 25.0
    product.in_stock = True
    product.sizes_available = '["6", "7", "8", "9", "10"]'
    return product


@pytest.fixture
def mock_alert(mock_product):
    """Create a mock alert."""
    alert = MagicMock(spec=Alert)
    alert.id = 1
    alert.product_id = 1
    alert.product = mock_product
    alert.alert_type = "price_drop"
    alert.message = "Price dropped by ₹3,001 (25%)"
    alert.triggered_at = datetime.now()
    alert.notified_at = None
    return alert


class TestTelegramNotifier:
    """Test TelegramNotifier class."""

    def test_init_with_params(self):
        """Test initialization with provided parameters."""
        notifier = TelegramNotifier(
            bot_token="test_token_123",
            chat_id="test_chat_456"
        )
        assert notifier.bot_token == "test_token_123"
        assert notifier.chat_id == "test_chat_456"

    def test_init_missing_token_raises_error(self):
        """Test that missing bot token raises ValueError."""
        with patch("app.notifier.telegram.settings") as mock_settings:
            mock_settings.telegram_bot_token = None
            mock_settings.telegram_chat_id = "test_chat"
            
            with pytest.raises(ValueError) as exc_info:
                TelegramNotifier()
            
            assert "Telegram bot token" in str(exc_info.value)

    def test_init_missing_chat_id_raises_error(self):
        """Test that missing chat ID raises ValueError."""
        with patch("app.notifier.telegram.settings") as mock_settings:
            mock_settings.telegram_bot_token = "test_token"
            mock_settings.telegram_chat_id = None
            
            with pytest.raises(ValueError) as exc_info:
                TelegramNotifier()
            
            assert "chat ID" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_send_alert_success(self, mock_alert):
        """Test successful alert sending."""
        notifier = TelegramNotifier(
            bot_token="test_token",
            chat_id="test_chat"
        )
        
        # Mock the bot
        notifier.bot = AsyncMock()
        notifier.bot.send_message = AsyncMock()
        
        result = await notifier.send_alert(mock_alert)
        
        assert result is True
        notifier.bot.send_message.assert_called_once()
        call_args = notifier.bot.send_message.call_args
        assert call_args.kwargs["chat_id"] == "test_chat"
        assert "Nike" in call_args.kwargs["text"]
        assert "Air Jordan 1" in call_args.kwargs["text"]

    @pytest.mark.asyncio
    async def test_send_alert_telegram_error(self, mock_alert):
        """Test handling of Telegram error."""
        notifier = TelegramNotifier(
            bot_token="test_token",
            chat_id="test_chat"
        )
        
        notifier.bot = AsyncMock()
        notifier.bot.send_message = AsyncMock(
            side_effect=TelegramError("Network error")
        )
        
        result = await notifier.send_alert(mock_alert)
        
        assert result is False

    @pytest.mark.asyncio
    async def test_send_alert_generic_error(self, mock_alert):
        """Test handling of generic exception."""
        notifier = TelegramNotifier(
            bot_token="test_token",
            chat_id="test_chat"
        )
        
        notifier.bot = AsyncMock()
        notifier.bot.send_message = AsyncMock(
            side_effect=Exception("Unknown error")
        )
        
        result = await notifier.send_alert(mock_alert)
        
        assert result is False

    @pytest.mark.asyncio
    async def test_send_alerts_batch(self, mock_alert):
        """Test batch sending of alerts."""
        notifier = TelegramNotifier(
            bot_token="test_token",
            chat_id="test_chat"
        )
        
        notifier.bot = AsyncMock()
        notifier.bot.send_message = AsyncMock(return_value=True)
        
        alerts = [mock_alert, mock_alert, mock_alert]
        result = await notifier.send_alerts_batch(alerts)
        
        assert result["sent_count"] == 3
        assert result["failed_count"] == 0
        assert notifier.bot.send_message.call_count == 3

    @pytest.mark.asyncio
    async def test_send_alerts_batch_partial_failure(self, mock_alert):
        """Test batch sending with some failures."""
        notifier = TelegramNotifier(
            bot_token="test_token",
            chat_id="test_chat"
        )

        notifier.bot = AsyncMock()
        # Fail on second call
        notifier.bot.send_message = AsyncMock(
            side_effect=[True, TelegramError("Error"), True]
        )

        alerts = [mock_alert, mock_alert, mock_alert]
        result = await notifier.send_alerts_batch(alerts)

        assert result["sent_count"] == 2
        assert result["failed_count"] == 1

    @pytest.mark.asyncio
    async def test_send_scan_summary_success(self):
        """Test sending a scan summary message."""
        notifier = TelegramNotifier(
            bot_token="test_token",
            chat_id="test_chat"
        )

        notifier.bot = AsyncMock()
        notifier.bot.send_message = AsyncMock()

        result = await notifier.send_scan_summary(
            scan_type="watchlist",
            entries_scanned=3,
            products_updated=2,
            alerts_created=1,
            mismatches=["New Balance 574 mismatch"],
            errors=["AJIO fetch failed"],
        )

        assert result is True
        notifier.bot.send_message.assert_called_once()
        message = notifier.bot.send_message.call_args.kwargs["text"]
        assert "Watchlist scan summary" in message
        assert "Entries scanned: 3" in message
        assert "Products updated: 2" in message
        assert "Alerts created: 1" in message
        assert "New Balance 574 mismatch" in message
        assert "AJIO fetch failed" in message

    @pytest.mark.asyncio
    async def test_send_mismatch_alert_success(self):
        """Test sending a mismatch alert message."""
        notifier = TelegramNotifier(
            bot_token="test_token",
            chat_id="test_chat"
        )

        notifier.bot = AsyncMock()
        notifier.bot.send_message = AsyncMock()

        result = await notifier.send_mismatch_alert(
            source_url="https://www.myntra.com/123",
            title="New Balance 574",
            expected="new balance 574",
            actual="new balance 990",
        )

        assert result is True
        notifier.bot.send_message.assert_called_once()
        message = notifier.bot.send_message.call_args.kwargs["text"]
        assert "Mismatch Alert" in message
        assert "https://www.myntra.com/123" in message
        assert "New Balance 574" in message
        assert "new balance 990" in message

    @pytest.mark.asyncio
    async def test_send_brand_monitor_update_to_user_chat(self):
        """Test sending launch monitor updates to an explicit chat."""
        notifier = TelegramNotifier(
            bot_token="test_token",
            chat_id="default_chat",
        )

        notifier.bot = AsyncMock()
        notifier.bot.send_message = AsyncMock()

        result = await notifier.send_brand_monitor_update(
            chat_id="user_chat",
            monitor_title="Adidas Originals on myntra",
            platform="myntra",
            query="Adidas Originals sneakers",
            products_found=12,
            products_matched=2,
            new_products=[],
        )

        assert result is True
        notifier.bot.send_message.assert_called_once()
        call_args = notifier.bot.send_message.call_args
        assert call_args.kwargs["chat_id"] == "user_chat"
        assert "No new products found" in call_args.kwargs["text"]

    def test_format_alert_message_price_drop(self, mock_alert, mock_product):
        """Test message formatting for price drop alert."""
        mock_product.last_price_check_at = datetime.utcnow() - timedelta(minutes=15)
        previous_snapshot = MagicMock()
        previous_snapshot.recorded_at = datetime.utcnow() - timedelta(hours=2)
        previous_snapshot.discounted_price = 9200.0
        previous_snapshot.listed_price = 12000.0
        mock_product.price_history = [previous_snapshot]

        notifier = TelegramNotifier(
            bot_token="test_token",
            chat_id="test_chat"
        )
        
        message = notifier._format_alert_message(mock_alert, mock_product)
        
        assert "Nike Air Jordan 1" in message
        assert "Myntra" in message
        assert "price_drop" in message
        assert "₹8,999" in message
        assert "25%" in message
        assert "✅ In Stock" in message
        assert "https://myntra.com/shoes/123" in message
        assert "⌛ Last scanned:" in message
        assert "View on Myntra" in message

    def test_format_alert_message_with_previous_scan(self, mock_alert, mock_product):
        """Test message includes previous scanned price when available."""
        mock_product.last_price_check_at = datetime.utcnow() - timedelta(minutes=30)
        current_snapshot = MagicMock()
        current_snapshot.recorded_at = datetime.utcnow() - timedelta(minutes=30)
        current_snapshot.discounted_price = 8999.0
        current_snapshot.listed_price = 12000.0
        previous_snapshot = MagicMock()
        previous_snapshot.recorded_at = datetime.utcnow() - timedelta(hours=2)
        previous_snapshot.discounted_price = 9500.0
        previous_snapshot.listed_price = 12000.0
        mock_product.price_history = [current_snapshot, previous_snapshot]

        notifier = TelegramNotifier(
            bot_token="test_token",
            chat_id="test_chat"
        )

        message = notifier._format_alert_message(mock_alert, mock_product)

        assert "📉 Last scanned price:" in message
        assert "₹9,500" in message

    def test_format_alert_message_out_of_stock(self, mock_alert, mock_product):
        """Test message formatting for out of stock alert."""
        mock_product.in_stock = False
        mock_alert.alert_type = "out_of_stock"
        mock_alert.message = "This product is now out of stock"
        
        notifier = TelegramNotifier(
            bot_token="test_token",
            chat_id="test_chat"
        )
        
        message = notifier._format_alert_message(mock_alert, mock_product)
        
        assert "❌ Out of Stock" in message
        assert "out_of_stock" in message

    def test_format_alert_message_restock(self, mock_alert, mock_product):
        """Test message formatting for restock alert."""
        mock_product.in_stock = True
        mock_alert.alert_type = "back_in_stock"
        mock_alert.message = "Product is back in stock!"
        
        notifier = TelegramNotifier(
            bot_token="test_token",
            chat_id="test_chat"
        )
        
        message = notifier._format_alert_message(mock_alert, mock_product)
        
        assert "back_in_stock" in message
        assert "✅ In Stock" in message

    def test_format_alert_message_without_discount(self, mock_alert, mock_product):
        """Test message formatting when discount is None."""
        mock_product.discount_percentage = None
        
        notifier = TelegramNotifier(
            bot_token="test_token",
            chat_id="test_chat"
        )
        
        message = notifier._format_alert_message(mock_alert, mock_product)
        
        assert "Nike Air Jordan 1" in message
        assert "₹8,999" in message

    def test_send_alert_sync(self, mock_alert):
        """Test synchronous wrapper for send_alert."""
        notifier = TelegramNotifier(
            bot_token="test_token",
            chat_id="test_chat"
        )
        
        # Mock the async send_alert method
        notifier.send_alert = AsyncMock(return_value=True)
        
        result = notifier.send_alert_sync(mock_alert)
        
        assert result is True

    def test_send_alert_sync_failure(self, mock_alert):
        """Test synchronous wrapper when async send fails."""
        notifier = TelegramNotifier(
            bot_token="test_token",
            chat_id="test_chat"
        )
        
        notifier.send_alert = AsyncMock(return_value=False)
        
        result = notifier.send_alert_sync(mock_alert)
        
        assert result is False


class TestNotificationService:
    """Test NotificationService class."""

    def test_init_with_notifier(self):
        """Test initialization with provided notifier."""
        mock_notifier = MagicMock(spec=TelegramNotifier)
        service = NotificationService(
            telegram_notifier=mock_notifier,
            telegram_enabled_checker=lambda: True,
        )
        
        assert service.notifier == mock_notifier

    def test_init_creates_notifier(self):
        """Test that service creates notifier if not provided."""
        with patch("app.notifier.telegram.TelegramNotifier") as MockNotifier:
            mock_instance = MagicMock()
            MockNotifier.return_value = mock_instance
            
            service = NotificationService()
            
            assert service.notifier == mock_instance

    def test_init_when_notifier_init_fails(self):
        """Test graceful handling when notifier initialization fails."""
        with patch("app.notifier.telegram.TelegramNotifier") as MockNotifier:
            MockNotifier.side_effect = ValueError("Config missing")
            
            service = NotificationService()
            
            assert service.notifier is None

    @pytest.mark.asyncio
    async def test_process_unnotified_alerts(self, mock_alert):
        """Test processing unnotified alerts."""
        mock_notifier = AsyncMock(spec=TelegramNotifier)
        mock_notifier.send_alerts_batch = AsyncMock(
            return_value={"sent_count": 1, "failed_count": 0}
        )
        
        service = NotificationService(
            telegram_notifier=mock_notifier,
            telegram_enabled_checker=lambda: True,
        )
        
        # Mock the repository
        with patch("app.notifier.telegram.AlertRepository") as MockRepo:
            MockRepo.get_unnotified.return_value = [mock_alert]
            MockRepo.mark_notified = MagicMock()
            
            session = MagicMock()
            result = await service.process_unnotified_alerts(session, batch_size=10)
            
            assert result["sent_count"] == 1
            assert result["failed_count"] == 0
            MockRepo.get_unnotified.assert_called_once_with(session, limit=10)
            MockRepo.mark_notified.assert_called_once()

    @pytest.mark.asyncio
    async def test_process_unnotified_alerts_none(self):
        """Test processing when no alerts exist."""
        mock_notifier = AsyncMock(spec=TelegramNotifier)
        service = NotificationService(
            telegram_notifier=mock_notifier,
            telegram_enabled_checker=lambda: True,
        )
        
        with patch("app.notifier.telegram.AlertRepository") as MockRepo:
            MockRepo.get_unnotified.return_value = []
            
            session = MagicMock()
            result = await service.process_unnotified_alerts(session)
            
            assert result["sent_count"] == 0
            assert result["failed_count"] == 0

    @pytest.mark.asyncio
    async def test_process_unnotified_alerts_disabled(self):
        """Test processing when notifier is disabled."""
        with patch("app.notifier.telegram.TelegramNotifier") as MockNotifier:
            MockNotifier.side_effect = ValueError("Config missing")
            service = NotificationService(telegram_notifier=None)
            
            session = MagicMock()
            result = await service.process_unnotified_alerts(session)
            
            assert result["sent_count"] == 0
            assert result["failed_count"] == 0
            assert "reason" in result

    @pytest.mark.asyncio
    async def test_send_scan_summary_skips_when_connectivity_disabled(self):
        """Test Telegram sends are skipped when the admin switch is off."""
        mock_notifier = AsyncMock(spec=TelegramNotifier)
        service = NotificationService(
            telegram_notifier=mock_notifier,
            telegram_enabled_checker=lambda: False,
        )

        result = await service.send_scan_summary(
            scan_type="watchlist",
            entries_scanned=1,
            products_updated=1,
            alerts_created=0,
        )

        assert result is False
        mock_notifier.send_scan_summary.assert_not_called()

    @pytest.mark.asyncio
    async def test_process_unnotified_alerts_error(self):
        """Test error handling in process_unnotified_alerts."""
        mock_notifier = AsyncMock(spec=TelegramNotifier)
        service = NotificationService(
            telegram_notifier=mock_notifier,
            telegram_enabled_checker=lambda: True,
        )
        
        with patch("app.notifier.telegram.AlertRepository") as MockRepo:
            MockRepo.get_unnotified.side_effect = Exception("DB error")
            
            session = MagicMock()
            result = await service.process_unnotified_alerts(session)
            
            assert result["sent_count"] == 0
            assert result["failed_count"] == 0
            assert "error" in result

    @pytest.mark.asyncio
    async def test_process_unnotified_alerts_mark_notified_fails(self, mock_alert):
        """Test handling when marking alert as notified fails."""
        mock_notifier = AsyncMock(spec=TelegramNotifier)
        mock_notifier.send_alerts_batch = AsyncMock(
            return_value={"sent_count": 1, "failed_count": 0}
        )
        
        service = NotificationService(
            telegram_notifier=mock_notifier,
            telegram_enabled_checker=lambda: True,
        )
        
        with patch("app.notifier.telegram.AlertRepository") as MockRepo:
            MockRepo.get_unnotified.return_value = [mock_alert]
            MockRepo.mark_notified.side_effect = Exception("DB error")
            
            session = MagicMock()
            # Should not raise exception
            result = await service.process_unnotified_alerts(session)
            
            # Still returns success result from send_alerts_batch
            assert result["sent_count"] == 1
