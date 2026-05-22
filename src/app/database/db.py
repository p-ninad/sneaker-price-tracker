"""Database connection and session management."""

from sqlalchemy import create_engine, event, Engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool
from app.config import settings
from app.database.models import Base
from app.utils.logger import get_logger

logger = get_logger(__name__)


def get_engine() -> Engine:
    """Create database engine with SQLite optimizations."""

    # SQLite-specific configuration
    if settings.database_url.startswith("sqlite"):
        engine = create_engine(
            settings.database_url,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
            echo=False,
        )

        # Enable WAL mode for better concurrency
        @event.listens_for(Engine, "connect")
        def set_sqlite_pragma(dbapi_conn, connection_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA cache_size=-64000")
            cursor.close()
    else:
        # PostgreSQL or other databases
        engine = create_engine(
            settings.database_url,
            pool_pre_ping=True,
            echo=False,
        )

    return engine


def init_db() -> None:
    """Create all tables in the database."""
    engine = get_engine()
    Base.metadata.create_all(bind=engine)
    logger.info("Database initialized", database_url=settings.database_url)


def get_session() -> Session:
    """Get a new database session."""
    engine = get_engine()
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    return SessionLocal()


def close_session(session: Session) -> None:
    """Close a database session."""
    if session:
        session.close()
