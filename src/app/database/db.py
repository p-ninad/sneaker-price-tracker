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
_ENGINE_URL: str | None = None
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
    global _ENGINE, _ENGINE_URL, _SESSION_FACTORY
    current_database_url = config.settings.database_url
    if _ENGINE is not None and _ENGINE_URL == current_database_url:
        return _ENGINE

    if _ENGINE is not None:
        _ENGINE.dispose()
        _ENGINE = None
        _SESSION_FACTORY = None

    backend = _database_backend()
    if backend == "sqlite":
        _ENGINE = create_engine(
            current_database_url,
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
            current_database_url,
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=True,
            echo=False,
        )
    else:
        _ENGINE = create_engine(
            current_database_url,
            pool_pre_ping=True,
            echo=False,
        )

    _ENGINE_URL = current_database_url
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
    """Initialize or verify the configured database.

    SQLite remains create-on-demand for local development and tests. PostgreSQL
    schema changes are owned by Alembic migrations, so startup only verifies
    that the external database is reachable.
    """
    engine = get_engine()
    backend = _database_backend()
    if _is_postgres_backend(backend):
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        logger.info(
            "Postgres connection verified; schema is managed by migrations",
            database_url=config.settings.database_url,
        )
        return

    _run_schema_operation(engine, lambda bind: Base.metadata.create_all(bind=bind))
    logger.info("Database schema initialized", database_url=config.settings.database_url)


def reset_db() -> None:
    """Drop and recreate the database schema for a fresh application launch."""
    engine = get_engine()
    backend = _database_backend()
    if _is_postgres_backend(backend):
        raise RuntimeError(
            "reset_db() is disabled for PostgreSQL. "
            "This deployment uses a persistent external database; use migrations "
            "or drop/recreate the database manually if you really intend data loss."
        )

    def reset_schema(bind: Engine | Connection) -> None:
        Base.metadata.drop_all(bind=bind)
        Base.metadata.create_all(bind=bind)

    _run_schema_operation(engine, reset_schema)
    logger.info("Database schema reset", database_url=config.settings.database_url)


def get_session() -> Session:
    """Get a new database session."""
    global _SESSION_FACTORY
    engine = get_engine()
    if _SESSION_FACTORY is None:
        _SESSION_FACTORY = sessionmaker(bind=engine, expire_on_commit=False)
    return _SESSION_FACTORY()


def close_session(session: Session) -> None:
    """Close a database session."""
    if session:
        session.close()
