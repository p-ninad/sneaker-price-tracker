"""Database connection and session management."""

from sqlalchemy import create_engine, event, Engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool
from app.config import settings
from app.database.models import Base
from app.utils.logger import get_logger

logger = get_logger(__name__)
_ENGINE: Engine | None = None
_SESSION_FACTORY: sessionmaker | None = None


def get_engine() -> Engine:
    """Create database engine with SQLite optimizations."""
    global _ENGINE
    if _ENGINE is not None:
        return _ENGINE

    # SQLite-specific configuration
    if settings.database_url.startswith("sqlite"):
        _ENGINE = create_engine(
            settings.database_url,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
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
    else:
        # PostgreSQL or other databases
        _ENGINE = create_engine(
            settings.database_url,
            pool_pre_ping=True,
            echo=False,
        )

    return _ENGINE


def init_db() -> None:
    """Create all tables in the database."""
    engine = get_engine()
    Base.metadata.create_all(bind=engine)
    logger.info("Database initialized", database_url=settings.database_url)


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
