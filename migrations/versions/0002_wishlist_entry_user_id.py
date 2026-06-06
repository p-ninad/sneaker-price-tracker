"""Add user scoping to wishlist entries.

Revision ID: 0002_wishlist_entry_user_id
Revises: 0001_initial_schema
Create Date: 2026-06-03 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0002_wishlist_entry_user_id"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add the user_id column and supporting index to wishlist entries."""
    bind = op.get_bind()
    dialect_name = bind.dialect.name

    op.add_column("wishlist_entries", sa.Column("user_id", sa.Integer(), nullable=True))

    if dialect_name == "postgresql":
        op.create_foreign_key(
            "fk_wishlist_entries_user_id_users",
            "wishlist_entries",
            "users",
            ["user_id"],
            ["id"],
        )

    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS idx_wishlist_user_active "
            "ON wishlist_entries (user_id, is_active)"
        )
    )


def downgrade() -> None:
    """Remove the user_id column from wishlist entries."""
    bind = op.get_bind()
    dialect_name = bind.dialect.name

    if dialect_name == "postgresql":
        op.drop_constraint(
            "fk_wishlist_entries_user_id_users",
            "wishlist_entries",
            type_="foreignkey",
        )

    op.drop_index("idx_wishlist_user_active", table_name="wishlist_entries")
    op.drop_column("wishlist_entries", "user_id")
