from __future__ import annotations

from app.auth.passwords import hash_password
from app.bot.telegram import (
    DEFAULT_ALERT_LIMIT,
    TelegramAlertDraft,
    TelegramBotService,
    build_help_text,
    build_status_text,
    build_start_text,
    parse_command_text,
    parse_platform_list,
    parse_size_list,
    parse_url,
)
from app.database.repository import UserRepository
from app.services.wishlist import WishlistService


def test_command_parser_recognizes_supported_commands():
    command = parse_command_text("/add https://example.com/item")
    assert command is not None
    assert command.normalized_name == "/add"
    assert command.arguments == "https://example.com/item"

    assert parse_command_text("/unknown") is None
    assert parse_command_text("hello there") is None
    assert parse_command_text("/status") is not None


def test_url_platform_and_size_parsers_enforce_structure():
    assert parse_url("https://www.myntra.com/p/123") == "https://www.myntra.com/p/123"
    assert parse_url("ftp://example.com") is None
    assert parse_platform_list("myntra, AJIO, myntra") == ["myntra", "ajio"]
    assert parse_size_list("8, 8.5, 9") == ["8", "8.5", "9"]

    try:
        parse_size_list("large")
    except ValueError as exc:
        assert "Invalid size value" in str(exc)
    else:
        raise AssertionError("Expected invalid size to raise")


def test_help_and_start_copy_are_telegram_friendly():
    help_text = build_help_text()
    assert "/add" in help_text
    assert "comma-separated" in help_text

    start_text = build_start_text(2, limit=DEFAULT_ALERT_LIMIT)
    assert "2/5 active alerts" in start_text
    assert "Use /add" in start_text

    status_text = build_status_text(uptime_seconds=3661, active_alerts=3, limit=DEFAULT_ALERT_LIMIT)
    assert "1h 1m 1s" in status_text
    assert "3/5" in status_text


def test_telegram_bot_enforces_limit_and_persists_alerts(test_session):
    user = UserRepository.create(
        test_session,
        username="tg_user",
        password_hash=hash_password("secret", iterations=1000),
        role="user",
        telegram_user_id="111",
        telegram_chat_id="222",
    )

    service = TelegramBotService(alert_limit=5)
    draft_template = TelegramAlertDraft(
        url="https://www.myntra.com/p/1",
        brand="Nike",
        model_name="Air Max",
        title="Nike Air Max",
        platforms_to_track=["myntra"],
        size_scope=["8", "8.5"],
        notes="Spring drop",
    )

    for index in range(5):
        draft = TelegramAlertDraft(
            url=f"https://www.myntra.com/p/{index}",
            brand=draft_template.brand,
            model_name=draft_template.model_name,
            title=f"{draft_template.title} {index}",
            platforms_to_track=draft_template.platforms_to_track,
            size_scope=draft_template.size_scope,
            notes=draft_template.notes,
        )
        created = service.finalize_add_draft(test_session, user.id, draft)
        assert created.user_id == user.id

    assert service.can_create_more_alerts(test_session, user.id) is False

    over_limit_draft = TelegramAlertDraft(
        url="https://www.myntra.com/p/999",
        brand="Nike",
        model_name="Air Max",
        title="Nike Air Max 999",
    )

    try:
        service.finalize_add_draft(test_session, user.id, over_limit_draft)
    except ValueError as exc:
        assert "5 active alerts" in str(exc)
    else:
        raise AssertionError("Expected alert limit to be enforced")

    alerts = WishlistService.get_all_for_user(test_session, user.id)
    assert len(alerts) == 5

    edited = service.edit_alert(
        test_session,
        user.id,
        "1",
        notes="Updated notes",
        platforms_to_track=["myntra", "ajio"],
        size_scope=["8", "8.5"],
    )
    assert edited is not None
    assert edited.notes == "Updated notes"
    assert WishlistService.get_platforms_to_track(edited) == ["myntra", "ajio"]
    assert WishlistService.get_size_scope(edited) == ["8", "8.5"]


def test_get_or_create_telegram_user_registers_identity(test_session):
    user = UserRepository.get_or_create_telegram_user(
        test_session,
        telegram_user_id="333",
        telegram_chat_id="444",
        display_name="Telegram User",
    )

    same_user = UserRepository.get_or_create_telegram_user(
        test_session,
        telegram_user_id="333",
        telegram_chat_id="555",
        display_name="Telegram User",
    )

    assert user.id == same_user.id
    assert same_user.telegram_chat_id == "555"
