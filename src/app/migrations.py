"""Command-line helpers for Alembic migrations."""

from __future__ import annotations

import argparse

from app.database.db import run_migrations
from app.utils.logger import setup_logging


def main(argv: list[str] | None = None) -> None:
    """Run database migration commands."""
    parser = argparse.ArgumentParser(description="Database migration helper")
    parser.add_argument(
        "command",
        nargs="?",
        default="upgrade",
        choices=["upgrade"],
        help="Migration command to run",
    )
    parser.add_argument(
        "target",
        nargs="?",
        default="head",
        help="Alembic target revision",
    )
    args = parser.parse_args(argv)

    setup_logging()

    if args.command == "upgrade" and args.target == "head":
        run_migrations()
        return

    raise ValueError(f"Unsupported migration command: {args.command} {args.target}")


if __name__ == "__main__":
    main()
