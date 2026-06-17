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

_WISHLIST_TABLE = "wishlist_entries"
_USER_FK_NAME = "fk_wishlist_entries_user_id_users"
_USER_INDEX_NAME = "idx_wishlist_user_active"


def _wishlist_entries_schema(bind) -> tuple[set[str], list[dict[str, object]], set[str]]:
    """Return the current wishlist_entries columns, foreign keys, and indexes."""
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns(_WISHLIST_TABLE)}
    foreign_keys = inspector.get_foreign_keys(_WISHLIST_TABLE)
    indexes = {index["name"] for index in inspector.get_indexes(_WISHLIST_TABLE)}
    return columns, foreign_keys, indexes


def upgrade() -> None:
    """Add the user_id column and supporting index to wishlist entries."""
    bind = op.get_bind()
    dialect_name = bind.dialect.name
    columns, foreign_keys, indexes = _wishlist_entries_schema(bind)

    if "user_id" not in columns:
        op.add_column(_WISHLIST_TABLE, sa.Column("user_id", sa.Integer(), nullable=True))

    if dialect_name == "postgresql":
        matching_foreign_keys = [
            foreign_key
            for foreign_key in foreign_keys
            if foreign_key.get("constrained_columns") == ["user_id"]
            and foreign_key.get("referred_table") == "users"
            and foreign_key.get("referred_columns") == ["id"]
        ]

        if matching_foreign_keys:
            existing_foreign_key_name = matching_foreign_keys[0].get("name")
            if existing_foreign_key_name and existing_foreign_key_name != _USER_FK_NAME:
                op.drop_constraint(
                    existing_foreign_key_name,
                    _WISHLIST_TABLE,
                    type_="foreignkey",
                )
                op.create_foreign_key(
                    _USER_FK_NAME,
                    _WISHLIST_TABLE,
                    "users",
                    ["user_id"],
                    ["id"],
                )
            elif existing_foreign_key_name is None:
                op.create_foreign_key(
                    _USER_FK_NAME,
                    _WISHLIST_TABLE,
                    "users",
                    ["user_id"],
                    ["id"],
                )
        else:
            op.create_foreign_key(
                _USER_FK_NAME,
                _WISHLIST_TABLE,
                "users",
                ["user_id"],
                ["id"],
            )

    if _USER_INDEX_NAME not in indexes:
        op.create_index(
            _USER_INDEX_NAME,
            _WISHLIST_TABLE,
            ["user_id", "is_active"],
            unique=False,
        )


def downgrade() -> None:
    """Remove the user_id column from wishlist entries."""
    bind = op.get_bind()
    dialect_name = bind.dialect.name

    if dialect_name == "postgresql":
        op.drop_constraint(
            _USER_FK_NAME,
            _WISHLIST_TABLE,
            type_="foreignkey",
        )

    op.drop_index(_USER_INDEX_NAME, table_name=_WISHLIST_TABLE)
    op.drop_column(_WISHLIST_TABLE, "user_id")
