from __future__ import annotations

import sys
import types
import asyncio

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


def test_main_runs_supervisor(monkeypatch):
    import app.bot.main as bot_main

    run_calls = []

    fake_logger = types.SimpleNamespace(info=lambda *args, **kwargs: None, error=lambda *args, **kwargs: None)

    async def fake_supervisor(**kwargs):
        run_calls.append(kwargs)

    monkeypatch.setattr(bot_main, "setup_logging", lambda: None)
    monkeypatch.setattr(bot_main, "get_logger", lambda name: fake_logger)
    monkeypatch.setattr(bot_main, "run_bot_supervisor", fake_supervisor)
    monkeypatch.setattr(bot_main.signal, "signal", lambda *args, **kwargs: None)

    bot_main.main()

    assert run_calls


def test_supervisor_idles_when_telegram_connectivity_disabled(monkeypatch):
    import app.bot.main as bot_main

    fake_logger = types.SimpleNamespace(
        info=lambda *args, **kwargs: None,
        warning=lambda *args, **kwargs: None,
        error=lambda *args, **kwargs: None,
    )

    monkeypatch.setattr(bot_main, "logger", fake_logger)
    monkeypatch.setattr(bot_main, "init_db", lambda: None)
    monkeypatch.setattr(bot_main, "telegram_connectivity_enabled", lambda: False)
    monkeypatch.setattr(
        bot_main,
        "initialize_bot",
        lambda: (_ for _ in ()).throw(AssertionError("bot should not start")),
    )

    asyncio.run(bot_main.run_bot_supervisor(poll_seconds=0, max_cycles=1))


def test_supervisor_starts_and_stops_when_enabled(monkeypatch):
    import app.bot.main as bot_main

    calls = []

    class FakeUpdater:
        running = False

        async def start_polling(self, **kwargs):
            calls.append(("start_polling", kwargs))
            self.running = True

        async def stop(self):
            calls.append(("stop_polling", None))
            self.running = False

    class FakeApplication:
        def __init__(self):
            self.updater = FakeUpdater()
            self.running = False

        async def initialize(self):
            calls.append(("initialize", None))

        async def post_init(self, application):
            calls.append(("post_init", application is self))

        async def start(self):
            calls.append(("start", None))
            self.running = True

        async def stop(self):
            calls.append(("stop", None))
            self.running = False

        async def shutdown(self):
            calls.append(("shutdown", None))

    fake_logger = types.SimpleNamespace(
        info=lambda *args, **kwargs: None,
        warning=lambda *args, **kwargs: None,
        error=lambda *args, **kwargs: None,
    )

    monkeypatch.setattr(bot_main, "logger", fake_logger)
    monkeypatch.setattr(bot_main, "init_db", lambda: None)
    monkeypatch.setattr(bot_main, "telegram_connectivity_enabled", lambda: True)
    monkeypatch.setattr(bot_main, "initialize_bot", lambda: FakeApplication())

    asyncio.run(bot_main.run_bot_supervisor(poll_seconds=0, max_cycles=1))

    call_names = [name for name, _payload in calls]
    assert call_names == [
        "initialize",
        "post_init",
        "start",
        "start_polling",
        "stop_polling",
        "stop",
        "shutdown",
    ]
