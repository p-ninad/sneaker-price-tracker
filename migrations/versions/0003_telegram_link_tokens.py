"""Add Telegram link token fields to users.

Revision ID: 0003_telegram_link_tokens
Revises: 0002_wishlist_entry_user_id
Create Date: 2026-06-03 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0003_telegram_link_tokens"
down_revision = "0002_wishlist_entry_user_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add Telegram linking columns to the users table."""
    op.add_column("users", sa.Column("telegram_link_token_hash", sa.String(length=64), nullable=True))
    op.add_column(
        "users",
        sa.Column("telegram_link_token_expires_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "idx_user_telegram_link_token",
        "users",
        ["telegram_link_token_hash", "telegram_link_token_expires_at"],
        unique=False,
    )


def downgrade() -> None:
    """Remove Telegram linking columns from the users table."""
    op.drop_index("idx_user_telegram_link_token", table_name="users")
    op.drop_column("users", "telegram_link_token_expires_at")
    op.drop_column("users", "telegram_link_token_hash")
