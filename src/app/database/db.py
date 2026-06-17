"""Database connection, migration, and session management."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.engine import Connection
from sqlalchemy.engine.url import make_url
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.config as config
from app.database.models import Base
from app.utils.logger import get_logger

logger = get_logger(__name__)
_ENGINE: Engine | None = None
_SESSION_FACTORY: sessionmaker | None = None
_ALEMBIC_CONFIG_PATH = Path(__file__).resolve().parents[3] / "alembic.ini"
_POSTGRES_SCHEMA_LOCK_KEY = 814_228_917


def _database_backend() -> str:
    """Return the configured database backend name."""
    return make_url(config.settings.database_url).drivername.split("+", 1)[0]


def _is_postgres_backend(backend: str) -> bool:
    """Return whether the configured backend is PostgreSQL-compatible."""
    return backend in {"postgresql", "postgres"}


def get_engine() -> Engine:
    """Create the SQLAlchemy engine with backend-specific tuning."""
    global _ENGINE
    if _ENGINE is not None:
        return _ENGINE

    backend = _database_backend()
    if backend == "sqlite":
        _ENGINE = create_engine(
            config.settings.database_url,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
            pool_pre_ping=True,
            echo=False,
        )

        # Enable WAL mode for better concurrency
        @event.listens_for(_ENGINE, "connect")
        def set_sqlite_pragma(dbapi_conn, connection_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA cache_size=-64000")
            cursor.close()
    elif _is_postgres_backend(backend):
        _ENGINE = create_engine(
            config.settings.database_url,
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=True,
            echo=False,
        )
    else:
        _ENGINE = create_engine(
            config.settings.database_url,
            pool_pre_ping=True,
            echo=False,
        )

    return _ENGINE


def _run_schema_operation(
    engine: Engine,
    operation: Callable[[Engine | Connection], None],
) -> None:
    """Run schema DDL with a Postgres advisory lock when needed."""
    backend = _database_backend()
    if _is_postgres_backend(backend):
        with engine.begin() as connection:
            connection.execute(
                text("SELECT pg_advisory_xact_lock(:lock_key)"),
                {"lock_key": _POSTGRES_SCHEMA_LOCK_KEY},
            )
            operation(connection)
        return

    operation(engine)


def run_migrations() -> None:
    """Apply database migrations for non-SQLite backends."""
    try:
        from alembic import command
        from alembic.config import Config
    except Exception as exc:  # pragma: no cover - dependency issue
        raise RuntimeError(
            "Database migrations require Alembic. Install project dependencies first."
        ) from exc

    alembic_config = Config(str(_ALEMBIC_CONFIG_PATH))
    alembic_config.set_main_option("sqlalchemy.url", config.settings.database_url)
    command.upgrade(alembic_config, "head")
    logger.info("Database migrations applied", database_url=config.settings.database_url)


def init_db() -> None:
    """Initialize the database schema for the configured backend."""
    engine = get_engine()
    _run_schema_operation(engine, lambda bind: Base.metadata.create_all(bind=bind))
    logger.info("Database schema initialized", database_url=config.settings.database_url)


def reset_db() -> None:
    """Drop and recreate the database schema for a fresh application launch."""
    engine = get_engine()

    def reset_schema(bind: Engine | Connection) -> None:
        Base.metadata.drop_all(bind=bind)
        Base.metadata.create_all(bind=bind)

    _run_schema_operation(engine, reset_schema)
    logger.info("Database schema reset", database_url=config.settings.database_url)


def get_session() -> Session:
    """Get a new database session."""
    global _SESSION_FACTORY
    if _SESSION_FACTORY is None:
        _SESSION_FACTORY = sessionmaker(bind=get_engine(), expire_on_commit=False)
    return _SESSION_FACTORY()


def close_session(session: Session) -> None:
    """Close a database session."""
    if session:
        session.close()
