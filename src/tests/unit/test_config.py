from pathlib import Path

import pytest

from app.config import load_settings


def test_load_settings_uses_explicit_env_file(tmp_path: Path, monkeypatch):
    for key in ("ENV", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "PLAYWRIGHT_HEADLESS"):
        monkeypatch.delenv(key, raising=False)

    env_file = tmp_path / ".env.test"
    env_file.write_text(
        "ENV=production\n"
        "TELEGRAM_BOT_TOKEN=test-token\n"
        "TELEGRAM_CHAT_ID=123456\n"
        "PLAYWRIGHT_HEADLESS=false\n"
    )

    settings = load_settings(env_file=env_file)

    assert settings.env == "production"
    assert settings.telegram_bot_token == "test-token"
    assert settings.telegram_chat_id == "123456"
    assert settings.playwright_headless is False


def test_load_settings_rejects_partial_telegram_credentials(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)

    env_file = tmp_path / ".env.test"
    env_file.write_text("ENV=production\nTELEGRAM_BOT_TOKEN=test-token\n")

    with pytest.raises(ValueError, match="TELEGRAM_CHAT_ID"):
        load_settings(env_file=env_file)
