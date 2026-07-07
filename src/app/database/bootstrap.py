"""Database bootstrap commands for local development and maintenance."""

from __future__ import annotations

import argparse

from app.database.db import init_db, reset_db
from app.utils.logger import setup_logging


def main(argv: list[str] | None = None) -> None:
    """Initialize or reset the database schema.

    PostgreSQL deployments should use `python -m app.migrations upgrade head`.
    The reset path intentionally refuses to drop persistent PostgreSQL data.
    """
    parser = argparse.ArgumentParser(description="Bootstrap the application database")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Drop and recreate the local SQLite schema",
    )
    args = parser.parse_args(argv)

    setup_logging()
    if args.reset:
        reset_db()
        return

    init_db()


if __name__ == "__main__":
    main()
