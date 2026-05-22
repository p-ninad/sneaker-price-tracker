"""Pytest configuration and fixtures."""

import pytest
import os
from pathlib import Path
from app.config import settings
from app.database.db import init_db, get_session
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


@pytest.fixture(scope="session")
def test_db_url():
    """Create test database URL."""
    test_db = Path("./data/test_price_tracker.db")
    return f"sqlite:///{test_db}"


@pytest.fixture(scope="function")
def test_session(test_db_url):
    """Create test database session."""
    # Create test engine
    engine = create_engine(test_db_url, connect_args={"check_same_thread": False})

    # Create all tables
    from app.database.models import Base
    Base.metadata.create_all(bind=engine)

    # Create session
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()

    yield session

    session.close()

    # Cleanup
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def mock_settings(monkeypatch):
    """Mock settings for testing."""
    monkeypatch.setenv("ENV", "test")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("ENABLE_SCHEDULER", "false")
    from app import config
    config.settings = config.Settings()
    return config.settings
