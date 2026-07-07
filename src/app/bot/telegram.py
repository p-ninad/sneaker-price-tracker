"""Telegram bot command and conversation handling."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal
from urllib.parse import urlparse

from app.database.db import get_session
from app.database.repository import BrandMonitorRepository, UserRepository
from app.services.brand_monitor import BrandMonitorService
from app.services.wishlist import WishlistService
from app.utils.logger import get_logger

logger = get_logger(__name__)

ALLOWED_COMMANDS = {
    "/start",
    "/help",
    "/status",
    "/add",
    "/list",
    "/monitor",
    "/monitors",
    "/edit",
    "/delete",
    "/pause",
    "/resume",
    "/cancel",
}

DEFAULT_ALERT_LIMIT = 5
DEFAULT_MONITOR_LIMIT = 5

ConversationStep = Literal[
    "idle",
    "add_url",
    "add_brand",
    "add_model_name",
    "add_title",
    "add_platforms",
    "add_sizes",
    "add_notes",
    "add_confirm",
    "monitor_platform",
    "monitor_brand",
    "monitor_terms",
    "monitor_sizes",
    "monitor_min_discount",
    "monitor_max_price",
    "monitor_notes",
    "monitor_confirm",
]


@dataclass
class TelegramAlertDraft:
    """In-progress alert creation data."""

    url: str | None = None
    brand: str | None = None
    model_name: str | None = None
    title: str | None = None
    platforms_to_track: list[str] = field(default_factory=list)
    size_scope: list[str] = field(default_factory=list)
    notes: str | None = None

    def is_complete(self) -> bool:
        return bool(self.url and self.brand and self.model_name and self.title)


@dataclass
class TelegramBrandMonitorDraft:
    """In-progress launch monitor creation data."""

    platform: str | None = None
    brand: str | None = None
    query_terms: list[str] = field(default_factory=list)
    size_scope: list[str] = field(default_factory=list)
    min_discount_percentage: float | None = None
    max_price: float | None = None
    notes: str | None = None

    def is_complete(self) -> bool:
        return bool(self.platform and self.brand)


@dataclass
class TelegramCommand:
    """Parsed Telegram command plus remainder text."""

    name: str
    arguments: str = ""

    @property
    def normalized_name(self) -> str:
        return self.name.lower()


def parse_command_text(text: str | None) -> TelegramCommand | None:
    """Parse a Telegram slash command from incoming text."""
    if not text:
        return None

    stripped = text.strip()
    if not stripped.startswith("/"):
        return None

    command, _, arguments = stripped.partition(" ")
    command = command.split("@", 1)[0]
    if command.lower() not in ALLOWED_COMMANDS:
        return None

    return TelegramCommand(name=command.lower(), arguments=arguments.strip())


def parse_url(value: str | None) -> str | None:
    """Validate and normalize a product URL."""
    if value is None:
        return None

    candidate = value.strip()
    if not candidate:
        return None

    parsed = urlparse(candidate)
    if parsed.scheme not in {"http", "https"}:
        return None
    if not parsed.netloc:
        return None

    return candidate


def _split_list_value(value: str | None) -> list[str]:
    if value is None:
        return []

    normalized = value.replace(";", ",").replace("\n", ",")
    parts = [item.strip() for item in normalized.split(",")]
    return [item for item in parts if item]


def parse_platform_list(value: str | None) -> list[str]:
    """Parse a comma-separated platform list."""
    platforms = []
    for platform in _split_list_value(value):
        cleaned = platform.lower()
        if cleaned not in platforms:
            platforms.append(cleaned)
    return platforms


def parse_size_list(value: str | None) -> list[str]:
    """Parse a comma-separated size list and reject arbitrary text."""
    parsed_sizes: list[str] = []
    for size in _split_list_value(value):
        cleaned = size.replace(" ", "")
        if not cleaned:
            continue
        if not cleaned.replace(".", "", 1).isdigit():
            raise ValueError(f"Invalid size value: {size}")
        if cleaned not in parsed_sizes:
            parsed_sizes.append(cleaned)
    return parsed_sizes


def parse_optional_number(value: str | None, field_name: str) -> float | None:
    """Parse an optional positive number from a structured Telegram prompt."""
    if value is None:
        return None

    cleaned = (
        value.strip()
        .replace("Rs", "")
        .replace("INR", "")
        .replace("%", "")
        .replace(",", "")
        .strip()
    )
    if not cleaned or cleaned == "-":
        return None

    try:
        parsed = float(cleaned)
    except ValueError as exc:
        raise ValueError(f"Invalid {field_name}: {value}") from exc

    if parsed < 0:
        raise ValueError(f"{field_name} must be zero or greater")
    return parsed


def build_monitor_draft_preview(draft: TelegramBrandMonitorDraft) -> str:
    """Return a concise confirmation preview for a launch monitor draft."""
    parts = [f"{draft.brand} on {draft.platform}"]
    if draft.query_terms:
        parts.append(f"terms: {', '.join(draft.query_terms)}")
    if draft.size_scope:
        parts.append(f"sizes: {', '.join(draft.size_scope)}")
    if draft.min_discount_percentage is not None:
        parts.append(f"min discount: {draft.min_discount_percentage:g}%")
    if draft.max_price is not None:
        parts.append(f"max price: Rs {draft.max_price:g}")
    return " | ".join(parts)


def build_help_text() -> str:
    """Describe the supported Telegram inputs."""
    return (
        "Telegram commands:\n"
        "/start - register or refresh your Telegram profile\n"
        "/help - show this help\n"
        "/status - show bot uptime and your active alert count\n"
        "/add - create a new alert in a guided flow\n"
        "/list - list your alerts\n"
        "/monitor - create a launch monitor in a guided flow\n"
        "/monitors - list your launch monitors\n"
        "/edit <id> - update alert fields like note, sizes or platforms\n"
        "/pause <id> - disable an alert\n"
        "/resume <id> - re-enable an alert\n"
        "/delete <id> - remove an alert\n"
        "/cancel - abort the current flow\n\n"
        "For /add, we accept one value per prompt:\n"
        "- URL: full http(s) product URL\n"
        "- Brand, model, title: plain text\n"
        "- Platforms: comma-separated slugs like myntra, ajio\n"
        "- Sizes: comma-separated numeric sizes like 8, 8.5, 9\n"
        "- Notes: optional free text\n\n"
        "For /monitor, we accept one value per prompt:\n"
        "- Platform: one slug like myntra\n"
        "- Brand: plain text like Adidas Originals\n"
        "- Terms: comma-separated filter terms like sneakers, samba\n"
        "- Sizes: comma-separated numeric sizes like 10, 11\n"
        "- Min discount and max price: numbers, or - to skip"
    )


def build_start_text(
    alert_count: int,
    limit: int = DEFAULT_ALERT_LIMIT,
    monitor_count: int = 0,
    monitor_limit: int = DEFAULT_MONITOR_LIMIT,
) -> str:
    """Build a welcome message for a Telegram user."""
    return (
        "Welcome to Price Tracker.\n"
        f"You currently have {alert_count}/{limit} active alerts.\n"
        f"You also have {monitor_count}/{monitor_limit} active launch monitors.\n"
        "Use /add for product alerts, /monitor for launch discovery, "
        "or /help for the command guide."
    )


def build_status_text(
    *,
    uptime_seconds: int,
    active_alerts: int,
    active_monitors: int = 0,
    limit: int = DEFAULT_ALERT_LIMIT,
    monitor_limit: int = DEFAULT_MONITOR_LIMIT,
) -> str:
    """Build a lightweight operational status message."""
    minutes, seconds = divmod(max(uptime_seconds, 0), 60)
    hours, minutes = divmod(minutes, 60)
    uptime_parts = []
    if hours:
        uptime_parts.append(f"{hours}h")
    if minutes or hours:
        uptime_parts.append(f"{minutes}m")
    uptime_parts.append(f"{seconds}s")

    return (
        "Bot status: online\n"
        f"Uptime: {' '.join(uptime_parts)}\n"
        f"Active alerts: {active_alerts}/{limit}\n"
        f"Active launch monitors: {active_monitors}/{monitor_limit}\n"
        "Polling mode: enabled"
    )


def parse_key_value_fields(text: str | None) -> dict[str, str]:
    """Parse simple key:value lines used for edit operations."""
    result: dict[str, str] = {}
    if not text:
        return result

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        cleaned_key = key.strip().lower().replace(" ", "_")
        cleaned_value = value.strip()
        if cleaned_key and cleaned_value:
            result[cleaned_key] = cleaned_value
    return result


class TelegramBotService:
    """Business logic for the Telegram bot."""

    def __init__(
        self,
        alert_limit: int = DEFAULT_ALERT_LIMIT,
        monitor_limit: int = DEFAULT_MONITOR_LIMIT,
    ):
        self.alert_limit = alert_limit
        self.monitor_limit = monitor_limit

    def register_user(
        self,
        telegram_user_id: str,
        telegram_chat_id: str,
        display_name: str | None = None,
    ):
        """Create or refresh a Telegram-registered regular user."""
        session = get_session()
        try:
            user = UserRepository.get_or_create_telegram_user(
                session,
                telegram_user_id=telegram_user_id,
                telegram_chat_id=telegram_chat_id,
                display_name=display_name,
            )
            UserRepository.record_login(session, user)
            return user
        finally:
            session.close()

    def get_active_alert_count(self, session, user_id: int) -> int:
        """Return the number of active alerts for a user."""
        return WishlistService.count_active_for_user(session, user_id)

    def get_active_monitor_count(self, session, user_id: int) -> int:
        """Return the number of active launch monitors for a user."""
        return BrandMonitorRepository.count_active_for_user(session, user_id)

    def can_create_more_alerts(self, session, user_id: int) -> bool:
        """Return whether the user can create another active alert."""
        return self.get_active_alert_count(session, user_id) < self.alert_limit

    def can_create_more_monitors(self, session, user_id: int) -> bool:
        """Return whether the user can create another active monitor."""
        return self.get_active_monitor_count(session, user_id) < self.monitor_limit

    def build_registration_summary(self, session, user_id: int) -> str:
        """Summarize the current alert count for the user."""
        active_count = self.get_active_alert_count(session, user_id)
        monitor_count = self.get_active_monitor_count(session, user_id)
        return build_start_text(
            active_count,
            self.alert_limit,
            monitor_count,
            self.monitor_limit,
        )

    def build_status_report(self, session, user_id: int, started_at: datetime) -> str:
        """Summarize bot uptime and the user's alert usage."""
        active_count = self.get_active_alert_count(session, user_id)
        monitor_count = self.get_active_monitor_count(session, user_id)
        uptime_seconds = int((datetime.utcnow() - started_at).total_seconds())
        return build_status_text(
            uptime_seconds=uptime_seconds,
            active_alerts=active_count,
            active_monitors=monitor_count,
            limit=self.alert_limit,
            monitor_limit=self.monitor_limit,
        )

    def start_add_flow(self) -> tuple[ConversationStep, str]:
        """Begin the guided add flow."""
        return "add_url", "Send the product URL for the new alert."

    def validate_add_draft(self, draft: TelegramAlertDraft) -> str | None:
        """Validate an in-progress add flow."""
        if not parse_url(draft.url):
            return "Please send a valid http(s) product URL."
        if not draft.brand:
            return "Please send the brand name."
        if not draft.model_name:
            return "Please send the model name."
        if not draft.title:
            return "Please send the alert title."
        return None

    def finalize_add_draft(self, session, user_id: int, draft: TelegramAlertDraft):
        """Persist a validated add draft."""
        if not self.can_create_more_alerts(session, user_id):
            raise ValueError(
                f"You already have {self.alert_limit} active alerts. "
                "Please disable or delete one before adding another."
            )

        url = parse_url(draft.url)
        if url is None:
            raise ValueError("Invalid product URL")
        if not draft.brand or not draft.model_name or not draft.title:
            raise ValueError("brand, model_name and title are required")

        return WishlistService.add_from_url(
            session,
            url=url,
            brand=draft.brand,
            model_name=draft.model_name,
            title=draft.title,
            platforms_to_track=draft.platforms_to_track or None,
            size_scope=draft.size_scope or None,
            notes=draft.notes,
            user_id=user_id,
        )

    def list_alerts(self, session, user_id: int) -> list:
        """Return the user's alerts."""
        return WishlistService.get_all_for_user(session, user_id)

    def validate_monitor_draft(self, draft: TelegramBrandMonitorDraft) -> str | None:
        """Validate an in-progress launch monitor flow."""
        if not draft.platform:
            return "Please send one platform slug, such as myntra."
        if not draft.brand:
            return "Please send the brand name."
        return None

    def finalize_monitor_draft(
        self,
        session,
        user_id: int,
        draft: TelegramBrandMonitorDraft,
    ):
        """Persist a validated launch monitor draft."""
        if not self.can_create_more_monitors(session, user_id):
            raise ValueError(
                f"You already have {self.monitor_limit} active launch monitors. "
                "Please pause or delete one before adding another."
            )

        validation_error = self.validate_monitor_draft(draft)
        if validation_error:
            raise ValueError(validation_error)

        return BrandMonitorService.add_monitor(
            session,
            user_id=user_id,
            platform=draft.platform or BrandMonitorService.DEFAULT_PLATFORM,
            brand=draft.brand or "",
            query_terms=draft.query_terms or None,
            size_scope=draft.size_scope or None,
            min_discount_percentage=draft.min_discount_percentage,
            max_price=draft.max_price,
            notes=draft.notes,
        )

    def list_monitors(self, session, user_id: int) -> list:
        """Return the user's launch monitors."""
        return BrandMonitorRepository.list_for_user(session, user_id)

    def _find_user_monitor(self, session, user_id: int, identifier: str):
        """Find one monitor for a user by numeric ID."""
        if not identifier.strip().isdigit():
            return None
        return BrandMonitorRepository.get_for_user(session, user_id, int(identifier.strip()))

    def set_monitor_state(self, session, user_id: int, identifier: str, is_active: bool):
        """Enable or disable a launch monitor."""
        target = self._find_user_monitor(session, user_id, identifier)
        if target is None:
            return None
        return BrandMonitorRepository.set_active(session, target, is_active)

    def delete_monitor(self, session, user_id: int, identifier: str) -> bool:
        """Delete a launch monitor owned by a user."""
        target = self._find_user_monitor(session, user_id, identifier)
        if target is None:
            return False
        session.delete(target)
        session.commit()
        return True

    def _find_user_alert(self, session, user_id: int, identifier: str):
        """Find one alert for a user by numeric ID or URL."""
        alerts = WishlistService.get_all_for_user(session, user_id)
        if identifier.isdigit():
            alert_id = int(identifier)
            for alert in alerts:
                if alert.id == alert_id:
                    return alert
        else:
            for alert in alerts:
                if alert.source_url == identifier:
                    return alert
        return None

    def set_alert_state(self, session, user_id: int, identifier: str, is_active: bool):
        """Enable or disable an alert by numeric ID or URL."""
        identifier = identifier.strip()
        if not identifier:
            raise ValueError("Alert ID or URL is required")
        return self._set_alert_state_impl(session, user_id, identifier, is_active)

    def _set_alert_state_impl(self, session, user_id: int, identifier: str, is_active: bool):
        target = self._find_user_alert(session, user_id, identifier)

        if target is None:
            return None

        target.is_active = is_active
        session.commit()
        return target

    def edit_alert(
        self,
        session,
        user_id: int,
        identifier: str,
        *,
        title: str | None = None,
        brand: str | None = None,
        model_name: str | None = None,
        notes: str | None = None,
        platforms_to_track: list[str] | None = None,
        size_scope: list[str] | None = None,
    ):
        """Edit a user's alert with validated fields."""
        target = self._find_user_alert(session, user_id, identifier)
        if target is None:
            return None

        if title is not None:
            target.title = title
        if brand is not None:
            target.brand = brand
        if model_name is not None:
            target.model_name = model_name
        if notes is not None:
            target.notes = notes
        if platforms_to_track is not None:
            import json

            target.platforms_to_track = json.dumps(platforms_to_track)
        if size_scope is not None:
            import json

            target.size_scope = json.dumps(size_scope)

        session.commit()
        return target

    def delete_alert(self, session, user_id: int, identifier: str) -> bool:
        """Delete an alert by ID or URL if it belongs to the user."""
        alerts = WishlistService.get_all_for_user(session, user_id)
        target = None
        if identifier.isdigit():
            alert_id = int(identifier)
            for alert in alerts:
                if alert.id == alert_id:
                    target = alert
                    break
        else:
            for alert in alerts:
                if alert.source_url == identifier:
                    target = alert
                    break

        if target is None:
            return False

        session.delete(target)
        session.commit()
        return True


def create_application(bot_token: str, service: TelegramBotService | None = None):
    """Build a python-telegram-bot application if the dependency is available."""
    from telegram import BotCommand, ReplyKeyboardRemove, Update
    from telegram.ext import (
        ApplicationBuilder,
        CommandHandler,
        ContextTypes,
        MessageHandler,
        filters,
    )

    bot_service = service or TelegramBotService()
    started_at = datetime.utcnow()

    async def post_init(application):
        """Register the command menu shown by Telegram clients."""
        await application.bot.set_my_commands(
            [
                BotCommand("start", "Register or refresh your Telegram profile"),
                BotCommand("status", "Show bot uptime and alert usage"),
                BotCommand("add", "Create a new alert"),
                BotCommand("list", "List your alerts"),
                BotCommand("monitor", "Create or manage launch monitors"),
                BotCommand("monitors", "List your launch monitors"),
                BotCommand("edit", "Edit an alert"),
                BotCommand("pause", "Pause an alert"),
                BotCommand("resume", "Resume an alert"),
                BotCommand("delete", "Delete an alert"),
                BotCommand("cancel", "Cancel the current flow"),
                BotCommand("help", "Show help"),
            ]
        )

    async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
        telegram_user = update.effective_user
        telegram_chat = update.effective_chat
        if telegram_user is None or telegram_chat is None:
            return

        user = bot_service.register_user(
            telegram_user_id=str(telegram_user.id),
            telegram_chat_id=str(telegram_chat.id),
            display_name=telegram_user.full_name,
        )
        session = get_session()
        try:
            message = bot_service.build_registration_summary(session, user.id)
        finally:
            session.close()

        await update.message.reply_text(message, reply_markup=ReplyKeyboardRemove())

    async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(build_help_text())

    async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        telegram_user = update.effective_user
        telegram_chat = update.effective_chat
        if telegram_user is None or telegram_chat is None:
            return

        user = bot_service.register_user(
            telegram_user_id=str(telegram_user.id),
            telegram_chat_id=str(telegram_chat.id),
            display_name=telegram_user.full_name,
        )
        session = get_session()
        try:
            message = bot_service.build_status_report(session, user.id, started_at)
        finally:
            session.close()

        await update.message.reply_text(message)

    async def add_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        telegram_user = update.effective_user
        telegram_chat = update.effective_chat
        if telegram_user is None or telegram_chat is None:
            return

        user = bot_service.register_user(
            telegram_user_id=str(telegram_user.id),
            telegram_chat_id=str(telegram_chat.id),
            display_name=telegram_user.full_name,
        )
        session = get_session()
        try:
            if not bot_service.can_create_more_alerts(session, user.id):
                await update.message.reply_text(
                    f"You already have {bot_service.alert_limit} active alerts."
                )
                return
        finally:
            session.close()

        context.user_data["alert_draft"] = TelegramAlertDraft()
        context.user_data["alert_step"] = "add_url"
        await update.message.reply_text("Send the product URL for the new alert.")

    async def list_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        telegram_user = update.effective_user
        if telegram_user is None:
            return

        session = get_session()
        try:
            user = UserRepository.get_by_telegram_user_id(session, str(telegram_user.id))
            if user is None:
                await update.message.reply_text("Please send /start first so I can register you.")
                return

            alerts = bot_service.list_alerts(session, user.id)
        finally:
            session.close()

        if not alerts:
            await update.message.reply_text("You do not have any alerts yet. Use /add to create one.")
            return

        lines = ["Your alerts:"]
        for alert in alerts:
            status = "active" if alert.is_active else "paused"
            lines.append(f"{alert.id}. {alert.title} [{status}]")
        await update.message.reply_text("\n".join(lines))

    async def monitor_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        telegram_user = update.effective_user
        telegram_chat = update.effective_chat
        if telegram_user is None or telegram_chat is None or update.message is None:
            return

        command = parse_command_text(update.message.text)
        arguments = command.arguments if command is not None else ""
        if arguments:
            parts = arguments.split()
            action = parts[0].lower()
            if action == "list":
                await monitors_command(update, context)
                return
            if action in {"pause", "resume", "delete"}:
                await _mutate_monitor_state(update, context, action=action)
                return
            await update.message.reply_text(
                "Use /monitor to create one, /monitors to list them, "
                "or /monitor pause|resume|delete <id>."
            )
            return

        user = bot_service.register_user(
            telegram_user_id=str(telegram_user.id),
            telegram_chat_id=str(telegram_chat.id),
            display_name=telegram_user.full_name,
        )
        session = get_session()
        try:
            if not bot_service.can_create_more_monitors(session, user.id):
                await update.message.reply_text(
                    f"You already have {bot_service.monitor_limit} active launch monitors."
                )
                return
        finally:
            session.close()

        context.user_data["monitor_draft"] = TelegramBrandMonitorDraft(
            platform=BrandMonitorService.DEFAULT_PLATFORM,
        )
        context.user_data["monitor_step"] = "monitor_platform"
        await update.message.reply_text(
            "Send one platform slug for this launch monitor, such as myntra. "
            "Reply with - to use myntra."
        )

    async def monitors_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        telegram_user = update.effective_user
        if telegram_user is None:
            return

        session = get_session()
        try:
            user = UserRepository.get_by_telegram_user_id(session, str(telegram_user.id))
            if user is None:
                await update.message.reply_text("Please send /start first so I can register you.")
                return

            monitors = bot_service.list_monitors(session, user.id)
        finally:
            session.close()

        if not monitors:
            await update.message.reply_text(
                "You do not have any launch monitors yet. Use /monitor to create one."
            )
            return

        lines = ["Your launch monitors:"]
        for monitor in monitors:
            status = "active" if monitor.is_active else "paused"
            lines.append(
                f"{monitor.id}. {BrandMonitorService.describe_monitor(monitor)} [{status}]"
            )
        await update.message.reply_text("\n".join(lines))

    async def edit_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        command = parse_command_text(update.message.text)
        if command is None or not command.arguments:
            await update.message.reply_text(
                "Use /edit <id> followed by fields on new lines, such as:\n"
                "/edit 12 notes: Needs colorway update\n"
                "sizes: 8, 8.5, 9\n"
                "platforms: myntra, ajio"
            )
            return

        target, _, remainder = command.arguments.partition(" ")
        fields = parse_key_value_fields(remainder)
        if not fields:
            await update.message.reply_text(
                "No editable fields were found. Include notes, sizes or platforms."
            )
            return

        telegram_user = update.effective_user
        telegram_chat = update.effective_chat
        if telegram_user is None or telegram_chat is None:
            return

        try:
            parsed_platforms = (
                parse_platform_list(fields["platforms"])
                if "platforms" in fields
                else None
            )
            parsed_sizes = parse_size_list(fields["sizes"]) if "sizes" in fields else None
        except ValueError as exc:
            await update.message.reply_text(str(exc))
            return

        session = get_session()
        try:
            user = UserRepository.get_by_telegram_user_id(session, str(telegram_user.id))
            if user is None:
                await update.message.reply_text("Please send /start first so I can register you.")
                return

            edited = bot_service.edit_alert(
                session,
                user.id,
                target,
                title=fields.get("title"),
                brand=fields.get("brand"),
                model_name=fields.get("model_name"),
                notes=fields.get("notes"),
                platforms_to_track=parsed_platforms,
                size_scope=parsed_sizes,
            )
        finally:
            session.close()

        if edited is None:
            await update.message.reply_text("I could not find that alert.")
            return

        await update.message.reply_text(f"Updated alert #{edited.id}.")

    async def delete_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await _mutate_alert_state(update, context, is_active=None, delete=True)

    async def pause_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await _mutate_alert_state(update, context, is_active=False, delete=False)

    async def resume_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await _mutate_alert_state(update, context, is_active=True, delete=False)

    async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        context.user_data.pop("alert_draft", None)
        context.user_data.pop("alert_step", None)
        context.user_data.pop("monitor_draft", None)
        context.user_data.pop("monitor_step", None)
        context.user_data.pop("edit_target", None)
        context.user_data.pop("edit_fields", None)
        await update.message.reply_text("Cancelled.", reply_markup=ReplyKeyboardRemove())

    async def message_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
        telegram_user = update.effective_user
        telegram_chat = update.effective_chat
        message = update.message.text if update.message else None
        if telegram_user is None or telegram_chat is None or not message:
            return

        command = parse_command_text(message)
        if command is not None:
            return

        session = get_session()
        try:
            user = UserRepository.get_or_create_telegram_user(
                session,
                telegram_user_id=str(telegram_user.id),
                telegram_chat_id=str(telegram_chat.id),
                display_name=telegram_user.full_name,
            )

            monitor_step = context.user_data.get("monitor_step")
            monitor_draft = context.user_data.get("monitor_draft")
            if isinstance(monitor_draft, TelegramBrandMonitorDraft):
                if monitor_step == "monitor_platform":
                    if message.strip() != "-":
                        platforms = parse_platform_list(message)
                        if len(platforms) != 1:
                            await update.message.reply_text(
                                "Please send exactly one platform slug, such as myntra."
                            )
                            return
                        monitor_draft.platform = platforms[0]
                    context.user_data["monitor_step"] = "monitor_brand"
                    await update.message.reply_text(
                        "Send the brand to monitor, such as Adidas Originals."
                    )
                    return

                if monitor_step == "monitor_brand":
                    monitor_draft.brand = message.strip()
                    context.user_data["monitor_step"] = "monitor_terms"
                    await update.message.reply_text(
                        "Send filter terms as comma-separated text, such as sneakers, samba. "
                        "Reply with - to skip."
                    )
                    return

                if monitor_step == "monitor_terms":
                    if message.strip() != "-":
                        monitor_draft.query_terms = _split_list_value(message)
                    context.user_data["monitor_step"] = "monitor_sizes"
                    await update.message.reply_text(
                        "Send sizes as comma-separated values like 10, 11. "
                        "Reply with - to skip size filtering."
                    )
                    return

                if monitor_step == "monitor_sizes":
                    if message.strip() != "-":
                        try:
                            monitor_draft.size_scope = parse_size_list(message)
                        except ValueError as exc:
                            await update.message.reply_text(str(exc))
                            return
                    context.user_data["monitor_step"] = "monitor_min_discount"
                    await update.message.reply_text(
                        "Send minimum discount percentage, such as 20. "
                        "Reply with - to include all discounts."
                    )
                    return

                if monitor_step == "monitor_min_discount":
                    try:
                        monitor_draft.min_discount_percentage = parse_optional_number(
                            message,
                            "minimum discount",
                        )
                    except ValueError as exc:
                        await update.message.reply_text(str(exc))
                        return
                    context.user_data["monitor_step"] = "monitor_max_price"
                    await update.message.reply_text(
                        "Send maximum price, such as 8000. Reply with - to skip."
                    )
                    return

                if monitor_step == "monitor_max_price":
                    try:
                        monitor_draft.max_price = parse_optional_number(
                            message,
                            "maximum price",
                        )
                    except ValueError as exc:
                        await update.message.reply_text(str(exc))
                        return
                    context.user_data["monitor_step"] = "monitor_notes"
                    await update.message.reply_text(
                        "Send optional notes, or reply with - to skip."
                    )
                    return

                if monitor_step == "monitor_notes":
                    if message.strip() != "-":
                        monitor_draft.notes = message.strip()
                    validation_error = bot_service.validate_monitor_draft(monitor_draft)
                    if validation_error:
                        await update.message.reply_text(validation_error)
                        return
                    context.user_data["monitor_step"] = "monitor_confirm"
                    preview = build_monitor_draft_preview(monitor_draft)
                    await update.message.reply_text(
                        f"{preview}\nReply YES to create the launch monitor or NO to cancel."
                    )
                    return

                if monitor_step == "monitor_confirm":
                    normalized = message.strip().lower()
                    if normalized in {"yes", "y"}:
                        created = bot_service.finalize_monitor_draft(
                            session,
                            user.id,
                            monitor_draft,
                        )
                        context.user_data.pop("monitor_draft", None)
                        context.user_data.pop("monitor_step", None)
                        await update.message.reply_text(
                            f"Created launch monitor #{created.id}."
                        )
                        return
                    if normalized in {"no", "n"}:
                        context.user_data.pop("monitor_draft", None)
                        context.user_data.pop("monitor_step", None)
                        await update.message.reply_text("Cancelled.")
                        return
                    await update.message.reply_text("Please reply YES or NO.")
                    return

            step = context.user_data.get("alert_step")
            draft = context.user_data.get("alert_draft")
            if not isinstance(draft, TelegramAlertDraft):
                return

            if step == "add_url":
                url = parse_url(message)
                if url is None:
                    await update.message.reply_text("Please send a valid http(s) product URL.")
                    return
                draft.url = url
                context.user_data["alert_step"] = "add_brand"
                await update.message.reply_text("Send the brand name.")
                return

            if step == "add_brand":
                draft.brand = message.strip()
                context.user_data["alert_step"] = "add_model_name"
                await update.message.reply_text("Send the model name.")
                return

            if step == "add_model_name":
                draft.model_name = message.strip()
                context.user_data["alert_step"] = "add_title"
                await update.message.reply_text("Send the alert title.")
                return

            if step == "add_title":
                draft.title = message.strip()
                context.user_data["alert_step"] = "add_platforms"
                await update.message.reply_text(
                    "Send platforms as comma-separated slugs like myntra, ajio. "
                    "Reply with - to keep the default platform."
                )
                return

            if step == "add_platforms":
                if message.strip() != "-":
                    draft.platforms_to_track = parse_platform_list(message)
                context.user_data["alert_step"] = "add_sizes"
                await update.message.reply_text(
                    "Send sizes as comma-separated values like 8, 8.5, 9. "
                    "Reply with - to keep the default size scope."
                )
                return

            if step == "add_sizes":
                if message.strip() != "-":
                    try:
                        draft.size_scope = parse_size_list(message)
                    except ValueError as exc:
                        await update.message.reply_text(str(exc))
                        return
                context.user_data["alert_step"] = "add_notes"
                await update.message.reply_text(
                    "Send optional notes, or reply with - to skip."
                )
                return

            if step == "add_notes":
                if message.strip() != "-":
                    draft.notes = message.strip()
                validation_error = bot_service.validate_add_draft(draft)
                if validation_error:
                    await update.message.reply_text(validation_error)
                    return
                context.user_data["alert_step"] = "add_confirm"
                await update.message.reply_text(
                    "Reply YES to create the alert or NO to cancel."
                )
                return

            if step == "add_confirm":
                normalized = message.strip().lower()
                if normalized in {"yes", "y"}:
                    created = bot_service.finalize_add_draft(session, user.id, draft)
                    context.user_data.pop("alert_draft", None)
                    context.user_data.pop("alert_step", None)
                    await update.message.reply_text(
                        f"Created alert #{created.id} for {created.title}."
                    )
                    return
                if normalized in {"no", "n"}:
                    context.user_data.pop("alert_draft", None)
                    context.user_data.pop("alert_step", None)
                    await update.message.reply_text("Cancelled.")
                    return
                await update.message.reply_text("Please reply YES or NO.")
                return

            if context.user_data.get("edit_target"):
                await update.message.reply_text(
                    "I have your edit details. Use /edit <id> with key:value lines for notes, sizes or platforms."
                )
                return

        finally:
            session.close()

    async def _mutate_alert_state(update: Update, context: ContextTypes.DEFAULT_TYPE, *, is_active: bool | None, delete: bool):
        telegram_user = update.effective_user
        if telegram_user is None or update.message is None:
            return

        command = parse_command_text(update.message.text)
        if command is None or not command.arguments:
            action = "delete" if delete else "pause" if is_active is False else "resume"
            await update.message.reply_text(f"Use /{action} <id or url>.")
            return

        session = get_session()
        try:
            user = UserRepository.get_by_telegram_user_id(session, str(telegram_user.id))
            if user is None:
                await update.message.reply_text("Please send /start first so I can register you.")
                return

            identifier = command.arguments.split()[0]
            if delete:
                deleted = bot_service.delete_alert(session, user.id, identifier)
                await update.message.reply_text(
                    "Deleted." if deleted else "I could not find that alert."
                )
                return

            updated = bot_service._set_alert_state_impl(session, user.id, identifier, bool(is_active))
            if updated is None:
                await update.message.reply_text("I could not find that alert.")
                return

            await update.message.reply_text(
                "Alert resumed." if is_active else "Alert paused."
            )
        finally:
            session.close()

    async def _mutate_monitor_state(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        *,
        action: str,
    ):
        telegram_user = update.effective_user
        if telegram_user is None or update.message is None:
            return

        command = parse_command_text(update.message.text)
        parts = command.arguments.split() if command is not None else []
        if len(parts) < 2:
            await update.message.reply_text(f"Use /monitor {action} <id>.")
            return

        identifier = parts[1]
        session = get_session()
        try:
            user = UserRepository.get_by_telegram_user_id(session, str(telegram_user.id))
            if user is None:
                await update.message.reply_text("Please send /start first so I can register you.")
                return

            if action == "delete":
                deleted = bot_service.delete_monitor(session, user.id, identifier)
                await update.message.reply_text(
                    "Launch monitor deleted."
                    if deleted
                    else "I could not find that launch monitor."
                )
                return

            updated = bot_service.set_monitor_state(
                session,
                user.id,
                identifier,
                is_active=(action == "resume"),
            )
            if updated is None:
                await update.message.reply_text("I could not find that launch monitor.")
                return

            await update.message.reply_text(
                "Launch monitor resumed." if action == "resume" else "Launch monitor paused."
            )
        finally:
            session.close()

    application = (
        ApplicationBuilder()
        .token(bot_token)
        .post_init(post_init)
        .build()
    )
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("add", add_command))
    application.add_handler(CommandHandler("list", list_command))
    application.add_handler(CommandHandler("monitor", monitor_command))
    application.add_handler(CommandHandler("monitors", monitors_command))
    application.add_handler(CommandHandler("edit", edit_command))
    application.add_handler(CommandHandler("delete", delete_command))
    application.add_handler(CommandHandler("pause", pause_command))
    application.add_handler(CommandHandler("resume", resume_command))
    application.add_handler(CommandHandler("cancel", cancel_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_router))
    return application
