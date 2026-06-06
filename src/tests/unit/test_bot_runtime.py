from __future__ import annotations

import sys
import types

from app import config as app_config


def test_initialize_bot_builds_application(monkeypatch, tmp_path):
    monkeypatch.setenv("ENV", "development")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'bot.db'}")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "bot-token")
    monkeypatch.setenv("TELEGRAM_REQUIRE_CHAT_ID", "false")
    app_config.settings = app_config.Settings()

    from app.database import db as app_db

    app_db._ENGINE = None
    app_db._SESSION_FACTORY = None

    fake_application = object()
    create_calls: list[str] = []

    import app.bot.main as bot_main

    monkeypatch.setattr(
        bot_main,
        "logger",
        types.SimpleNamespace(info=lambda *args, **kwargs: None, error=lambda *args, **kwargs: None),
    )
    fake_telegram_module = types.ModuleType("app.bot.telegram")
    fake_telegram_module.create_application = (
        lambda token: create_calls.append(token) or fake_application
    )
    monkeypatch.setitem(sys.modules, "app.bot.telegram", fake_telegram_module)

    application = bot_main.initialize_bot()

    assert application is fake_application
    assert create_calls == ["bot-token"]


def test_main_starts_polling(monkeypatch):
    import app.bot.main as bot_main

    run_calls = []

    class FakeApplication:
        def run_polling(self, **kwargs):
            run_calls.append(kwargs)

    fake_logger = types.SimpleNamespace(info=lambda *args, **kwargs: None, error=lambda *args, **kwargs: None)

    monkeypatch.setattr(bot_main, "setup_logging", lambda: None)
    monkeypatch.setattr(bot_main, "get_logger", lambda name: fake_logger)
    monkeypatch.setattr(bot_main, "initialize_bot", lambda: FakeApplication())
    monkeypatch.setattr(bot_main.signal, "signal", lambda *args, **kwargs: None)

    bot_main.main()

    assert run_calls
    assert run_calls[0]["close_loop"] is False
