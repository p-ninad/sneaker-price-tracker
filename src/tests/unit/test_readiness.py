from __future__ import annotations

from types import SimpleNamespace


def _stub_check(name: str, ok: bool = True, message: str = "ok"):
    from app.readiness import ReadinessCheck

    return ReadinessCheck(name=name, ok=ok, message=message)


def test_dashboard_readiness_requires_bootstrap_or_admins(monkeypatch):
    import app.readiness as readiness

    monkeypatch.setattr(readiness, "_check_database", lambda: _stub_check("database"))
    monkeypatch.setattr(readiness, "get_session", lambda: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(readiness.UserRepository, "list_admins", lambda session: [])
    readiness.config.settings = SimpleNamespace(
        auth_bootstrap_token=None,
        telegram_bot_token=None,
        telegram_chat_id=None,
    )

    report = readiness.build_readiness_report("dashboard")

    assert not report.ok
    assert "AUTH_BOOTSTRAP_TOKEN" in report.render()


def test_dashboard_readiness_passes_with_admin_account(monkeypatch):
    import app.readiness as readiness

    monkeypatch.setattr(readiness, "_check_database", lambda: _stub_check("database"))
    monkeypatch.setattr(readiness, "get_session", lambda: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(readiness.UserRepository, "list_admins", lambda session: [object()])
    readiness.config.settings = SimpleNamespace(
        auth_bootstrap_token=None,
        telegram_bot_token=None,
        telegram_chat_id=None,
    )

    report = readiness.build_readiness_report("dashboard")

    assert report.ok
    assert "admin account(s) available" in report.render()


def test_main_and_bot_readiness_require_telegram_credentials(monkeypatch):
    import app.readiness as readiness

    monkeypatch.setattr(readiness, "_check_database", lambda: _stub_check("database"))
    monkeypatch.setattr(readiness, "get_session", lambda: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(readiness.UserRepository, "list_admins", lambda session: [object()])

    readiness.config.settings = SimpleNamespace(
        auth_bootstrap_token="token",
        telegram_bot_token=None,
        telegram_chat_id=None,
    )

    main_report = readiness.build_readiness_report("main")
    bot_report = readiness.build_readiness_report("telegram-bot")

    assert not main_report.ok
    assert "TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID" in main_report.render()
    assert not bot_report.ok
    assert "TELEGRAM_BOT_TOKEN is required" in bot_report.render()


def test_all_readiness_aggregates_checks(monkeypatch):
    import app.readiness as readiness

    monkeypatch.setattr(readiness, "_check_database", lambda: _stub_check("database"))
    monkeypatch.setattr(readiness, "get_session", lambda: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(readiness.UserRepository, "list_admins", lambda session: [object()])
    readiness.config.settings = SimpleNamespace(
        auth_bootstrap_token="token",
        telegram_bot_token="bot-token",
        telegram_chat_id="chat-id",
    )

    report = readiness.build_readiness_report("all")

    assert report.ok
    assert len(report.checks) == 4

