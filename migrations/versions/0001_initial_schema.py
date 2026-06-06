"""Initial schema for Postgres and SQLite.

Revision ID: 0001_initial_schema
Revises: 
Create Date: 2026-06-02 00:00:00.000000
"""

from __future__ import annotations

from alembic import op

from app.database.models import Base

# revision identifiers, used by Alembic.
revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the current schema from metadata."""
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    """Drop the current schema."""
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
