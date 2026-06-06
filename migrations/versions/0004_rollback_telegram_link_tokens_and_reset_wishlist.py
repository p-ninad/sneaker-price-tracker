"""Remove Telegram link tokens and reset legacy wishlist entries.

Revision ID: 0004_rollback_telegram_link_tokens_and_reset_wishlist
Revises: 0003_telegram_link_tokens
Create Date: 2026-06-03 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0004_rollback_telegram_link_tokens_and_reset_wishlist"
down_revision = "0003_telegram_link_tokens"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Rollback Telegram link token fields and clear existing wishlist entries."""
    op.execute(sa.text("DELETE FROM wishlist_entries"))
    op.drop_index("idx_user_telegram_link_token", table_name="users")
    op.drop_column("users", "telegram_link_token_expires_at")
    op.drop_column("users", "telegram_link_token_hash")
    with op.batch_alter_table("wishlist_entries") as batch_op:
        batch_op.alter_column(
            "user_id",
            existing_type=sa.Integer(),
            nullable=False,
        )


def downgrade() -> None:
    """Recreate the Telegram link token columns."""
    with op.batch_alter_table("wishlist_entries") as batch_op:
        batch_op.alter_column(
            "user_id",
            existing_type=sa.Integer(),
            nullable=True,
        )
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
