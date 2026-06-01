"""Telegram notifier for sending price alerts to users."""

import asyncio
import html
from datetime import datetime
from typing import Optional
from telegram import Bot
from telegram.error import TelegramError

from app.config import settings
from app.database.models import Alert, Product
from app.database.repository import AlertRepository
from app.utils.logger import get_logger

logger = get_logger(__name__)


class TelegramNotifier:
    """Sends price alerts via Telegram Bot API."""

    def __init__(
        self,
        bot_token: Optional[str] = None,
        chat_id: Optional[str] = None,
    ):
        """Initialize Telegram notifier.

        Args:
            bot_token: Telegram bot token. Defaults to settings.telegram_bot_token
            chat_id: Telegram chat ID. Defaults to settings.telegram_chat_id

        Raises:
            ValueError: If bot_token or chat_id are not provided and not in settings
        """
        self.bot_token = bot_token or settings.telegram_bot_token
        self.chat_id = chat_id or settings.telegram_chat_id

        if not self.bot_token or not self.chat_id:
            raise ValueError(
                "Telegram bot token and chat ID are required. "
                "Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env"
            )

        self.bot = Bot(token=self.bot_token)

    async def send_message(self, text: str, context: dict | None = None) -> bool:
        """Send a raw Telegram message."""
        try:
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=text,
                parse_mode="HTML",
            )

            logger.info(
                "telegram_message_sent",
                chat_id=self.chat_id,
                context=context,
            )
            return True

        except TelegramError as e:
            logger.error(
                "telegram_send_failed",
                chat_id=self.chat_id,
                error=str(e),
                error_type=type(e).__name__,
                context=context,
            )
            return False
        except Exception as e:
            logger.error(
                "telegram_unexpected_error",
                chat_id=self.chat_id,
                error=str(e),
                error_type=type(e).__name__,
                context=context,
            )
            return False

    async def send_alert(self, alert: Alert) -> bool:
        """Send alert via Telegram.

        Args:
            alert: Alert object with product and message

        Returns:
            True if sent successfully, False otherwise
        """
        product = alert.product
        message = self._format_alert_message(alert, product)
        sent = await self.send_message(
            message,
            context={
                "kind": "alert",
                "alert_id": alert.id,
                "alert_type": alert.alert_type,
                "product_id": product.id,
            },
        )

        if sent:
            logger.info(
                "telegram_alert_sent",
                alert_id=alert.id,
                product_id=product.id,
                alert_type=alert.alert_type,
                chat_id=self.chat_id,
            )

        return bool(sent)

    async def send_alerts_batch(self, alerts: list[Alert]) -> dict:
        """Send multiple alerts.

        Args:
            alerts: List of alerts to send

        Returns:
            Dictionary with sent_count and failed_count
        """
        results = await asyncio.gather(
            *[self.send_alert(alert) for alert in alerts],
            return_exceptions=True,
        )

        sent_alert_ids = []
        failed_alert_ids = []
        for alert, result in zip(alerts, results):
            if result is True:
                sent_alert_ids.append(alert.id)
            else:
                failed_alert_ids.append(alert.id)

        sent = len(sent_alert_ids)
        failed = len(failed_alert_ids)

        logger.info(
            "telegram_batch_send_complete",
            total=len(alerts),
            sent=sent,
            failed=failed,
        )

        return {
            "sent_count": sent,
            "failed_count": failed,
            "sent_alert_ids": sent_alert_ids,
            "failed_alert_ids": failed_alert_ids,
        }

    async def send_scan_summary(
        self,
        scan_type: str,
        entries_scanned: int,
        products_updated: int,
        alerts_created: int,
        mismatches: list[str] | None = None,
        errors: list[str] | None = None,
    ) -> bool:
        """Send a summary message for a scheduled scan run."""
        message = self._format_scan_summary_message(
            scan_type,
            entries_scanned,
            products_updated,
            alerts_created,
            mismatches or [],
            errors or [],
        )

        return await self.send_message(
            message,
            context={
                "kind": "scan_summary",
                "scan_type": scan_type,
                "entries_scanned": entries_scanned,
                "products_updated": products_updated,
                "alerts_created": alerts_created,
            },
        )

    async def send_mismatch_alert(
        self,
        source_url: str,
        title: str,
        expected: str,
        actual: str,
    ) -> bool:
        """Send an operational notification when a fetched product mismatches the wishlist expectation."""
        message = self._format_mismatch_alert_message(source_url, title, expected, actual)

        return await self.send_message(
            message,
            context={
                "kind": "mismatch_alert",
                "source_url": source_url,
                "title": title,
            },
        )

    def _format_alert_message(self, alert: Alert, product: Product) -> str:
        """Format alert message with product details.

        Args:
            alert: Alert object
            product: Product object

        Returns:
            Formatted HTML message for Telegram
        """
        brand = html.escape(product.brand or "")
        model_name = html.escape(product.model_name or "")
        platform_name = html.escape(product.platform.display_name if product.platform else "")
        alert_type = html.escape(alert.alert_type or "")
        message_body = html.escape(alert.message or "").replace("\n", "\n")

        base_message = f"""<b>{brand} {model_name}</b>
Platform: <i>{platform_name}</i>
Type: <code>{alert_type}</code>

{message_body}"""

        # Add price info if available
        if product.discounted_price or product.listed_price:
            current_price = product.discounted_price or product.listed_price
            price_line = f"\n💰 Current Price: <b>₹{current_price:,.0f}</b>"
            if product.discount_percentage:
                price_line += f" ({product.discount_percentage:.0f}% off)"
            base_message += price_line

            previous_price_line = self._format_previous_price_line(product)
            if previous_price_line:
                base_message += f"\n{previous_price_line}"

        # Add scan timestamp and age
        scan_age_line = self._format_last_scanned_ago(product.last_price_check_at)
        if scan_age_line:
            base_message += f"\n⌛ Last scanned: <b>{scan_age_line}</b>"

        # Add stock info
        if product.in_stock:
            base_message += "\n✅ In Stock"
        else:
            base_message += "\n❌ Out of Stock"

        # Add link to product
        product_url = html.escape(product.product_url or "")
        platform_name = html.escape(product.platform.display_name if product.platform else "")
        base_message += f"\n🔎 Source URL: <code>{product_url}</code>"
        base_message += f"\n\n🔗 <a href=\"{product_url}\">View on {platform_name}</a>"

        return base_message

    def _format_previous_price_line(self, product: Product) -> str | None:
        """Format previous scanned price line for a product."""
        price_history = getattr(product, "price_history", None)
        if not isinstance(price_history, list):
            return None

        snapshots = [
            snapshot
            for snapshot in price_history
            if getattr(snapshot, "recorded_at", None) is not None
        ]
        if len(snapshots) < 2:
            return None

        snapshots.sort(key=lambda snapshot: snapshot.recorded_at, reverse=True)
        previous = snapshots[1]
        previous_price = previous.discounted_price or previous.listed_price
        if previous_price is None:
            return None

        return f"📉 Last scanned price: <b>₹{previous_price:,.0f}</b>"

    @staticmethod
    def _format_last_scanned_ago(last_scanned_at: datetime | None) -> str | None:
        """Return a human-readable relative duration since the last scan."""
        if not last_scanned_at or not isinstance(last_scanned_at, datetime):
            return None

        now = datetime.utcnow()
        delta = now - last_scanned_at
        if delta.total_seconds() < 0:
            return "just now"

        minutes = int(delta.total_seconds() / 60)
        if minutes < 1:
            return "just now"
        if minutes < 60:
            return f"{minutes}m ago"

        hours = int(minutes / 60)
        if hours < 24:
            return f"{hours}h ago"

        days = int(hours / 24)
        return f"{days}d ago"

    @staticmethod
    def _format_scan_summary_message(
        scan_type: str,
        entries_scanned: int,
        products_updated: int,
        alerts_created: int,
        mismatches: list[str],
        errors: list[str],
    ) -> str:
        """Format a Telegram summary for scheduled scans."""
        lines = [
            f"<b>{scan_type.title()} scan summary</b>",
            f"Entries scanned: {entries_scanned}",
            f"Products updated: {products_updated}",
            f"Alerts created: {alerts_created}",
        ]

        if mismatches:
            lines.append("\n⚠️ Mismatches:")
            lines.extend(f"• {message}" for message in mismatches)

        if errors:
            lines.append("\n❗ Errors:")
            lines.extend(f"• {message}" for message in errors)

        return "\n".join(lines)

    @staticmethod
    def _format_mismatch_alert_message(
        source_url: str,
        title: str,
        expected: str,
        actual: str,
    ) -> str:
        """Format a mismatch alert for the Telegram channel."""
        return (
            "<b>Mismatch Alert</b>\n"
            f"Source: <code>{html.escape(source_url)}</code>\n"
            f"Wishlist title: {html.escape(title)}\n"
            f"Expected: {html.escape(expected)}\n"
            f"Actual: {html.escape(actual)}"
        )

    def send_alert_sync(self, alert: Alert) -> bool:
        """Synchronous wrapper for sending alert.

        Args:
            alert: Alert object

        Returns:
            True if sent successfully, False otherwise
        """
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        return loop.run_until_complete(self.send_alert(alert))


class NotificationService:
    """Service to manage notifications: get unnotified alerts and send them."""

    def __init__(self, telegram_notifier: Optional[TelegramNotifier] = None):
        """Initialize notification service.

        Args:
            telegram_notifier: TelegramNotifier instance. Creates one if not provided.

        Raises:
            ValueError: If Telegram config is missing and notifier not provided
        """
        self.notifier = telegram_notifier
        if not self.notifier:
            try:
                self.notifier = TelegramNotifier()
            except ValueError as e:
                logger.warning("telegram_notifier_disabled", reason=str(e))
                self.notifier = None

    async def process_unnotified_alerts(
        self, session, batch_size: int = 10
    ) -> dict:
        """Get unnotified alerts and send them.

        Args:
            session: SQLAlchemy session
            batch_size: Number of alerts to process at once

        Returns:
            Dictionary with sent_count and failed_count
        """
        if not self.notifier:
            logger.warning("notification_service_disabled")
            return {"sent_count": 0, "failed_count": 0, "reason": "notifier_disabled"}

        try:
            # Get unnotified alerts
            unnotified = AlertRepository.get_unnotified(session, limit=batch_size)

            if not unnotified:
                logger.debug("no_unnotified_alerts")
                return {"sent_count": 0, "failed_count": 0}

            logger.info(
                "processing_unnotified_alerts",
                count=len(unnotified),
            )

            # Send batch
            result = await self.notifier.send_alerts_batch(unnotified)

            sent_ids = set(result.get("sent_alert_ids", []))
            if not sent_ids and result.get("failed_count", 0) == 0:
                sent_ids = {alert.id for alert in unnotified}

            # Mark only successfully sent alerts as notified
            for alert in unnotified:
                if alert.id not in sent_ids:
                    continue
                try:
                    AlertRepository.mark_notified(session, alert)
                except Exception as e:
                    logger.error(
                        "mark_notified_failed",
                        alert_id=alert.id,
                        error=str(e),
                    )

            return result

        except Exception as e:
            logger.error(
                "process_unnotified_alerts_failed",
                error=str(e),
                error_type=type(e).__name__,
            )
            return {"sent_count": 0, "failed_count": 0, "error": str(e)}

    async def send_scan_summary(
        self,
        scan_type: str,
        entries_scanned: int,
        products_updated: int,
        alerts_created: int,
        mismatches: list[str] | None = None,
        errors: list[str] | None = None,
    ) -> bool:
        """Send a scan summary message via Telegram when available."""
        if not self.notifier:
            logger.warning("notification_service_disabled")
            return False

        return await self.notifier.send_scan_summary(
            scan_type=scan_type,
            entries_scanned=entries_scanned,
            products_updated=products_updated,
            alerts_created=alerts_created,
            mismatches=mismatches,
            errors=errors,
        )

    async def send_mismatch_alert(
        self,
        source_url: str,
        title: str,
        expected: str,
        actual: str,
    ) -> bool:
        """Send a mismatch alert via Telegram when available."""
        if not self.notifier:
            logger.warning("notification_service_disabled")
            return False

        return await self.notifier.send_mismatch_alert(
            source_url=source_url,
            title=title,
            expected=expected,
            actual=actual,
        )
