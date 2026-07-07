"""Add manual discovery scans and product ignores.

Revision ID: 0005_manual_discovery_and_ignores
Revises: 0004_rollback_telegram_link_tokens_and_reset_wishlist
Create Date: 2026-06-26 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0005_manual_discovery_and_ignores"
down_revision = "0004_rollback_telegram_link_tokens_and_reset_wishlist"
branch_labels = None
depends_on = None


def _has_table(bind, table_name: str) -> bool:
    return sa.inspect(bind).has_table(table_name)


def upgrade() -> None:
    """Create manual discovery scan/result and ignore-list tables."""
    bind = op.get_bind()

    if not _has_table(bind, "product_ignores"):
        op.create_table(
            "product_ignores",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("platform_id", sa.Integer(), sa.ForeignKey("platforms.id"), nullable=False),
            sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id"), nullable=True),
            sa.Column("platform_product_id", sa.String(length=100), nullable=False),
            sa.Column("product_url", sa.String(length=500), nullable=False),
            sa.Column("reason", sa.Text(), nullable=True),
            sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
            sa.UniqueConstraint(
                "platform_id",
                "platform_product_id",
                name="uq_product_ignore_platform_product",
            ),
        )
        op.create_index("ix_product_ignores_platform_id", "product_ignores", ["platform_id"])
        op.create_index("ix_product_ignores_product_id", "product_ignores", ["product_id"])
        op.create_index("ix_product_ignores_created_by_user_id", "product_ignores", ["created_by_user_id"])
        op.create_index("ix_product_ignores_is_active", "product_ignores", ["is_active"])
        op.create_index("idx_product_ignore_active", "product_ignores", ["platform_id", "is_active"])

    if not _has_table(bind, "manual_discovery_scans"):
        op.create_table(
            "manual_discovery_scans",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("platform", sa.String(length=50), nullable=False),
            sa.Column("brand_filters", sa.Text(), nullable=False),
            sa.Column("size_filters", sa.Text(), nullable=False),
            sa.Column("status", sa.String(length=50), nullable=False),
            sa.Column("products_found", sa.Integer(), nullable=True),
            sa.Column("products_matched", sa.Integer(), nullable=True),
            sa.Column("errors", sa.Text(), nullable=True),
            sa.Column("started_at", sa.DateTime(), server_default=sa.func.now()),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_manual_discovery_scans_user_id", "manual_discovery_scans", ["user_id"])
        op.create_index("ix_manual_discovery_scans_platform", "manual_discovery_scans", ["platform"])
        op.create_index("ix_manual_discovery_scans_status", "manual_discovery_scans", ["status"])
        op.create_index("ix_manual_discovery_scans_started_at", "manual_discovery_scans", ["started_at"])
        op.create_index("idx_manual_scan_user_started", "manual_discovery_scans", ["user_id", "started_at"])
        op.create_index("idx_manual_scan_status", "manual_discovery_scans", ["status"])

    if not _has_table(bind, "manual_discovery_results"):
        op.create_table(
            "manual_discovery_results",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("scan_id", sa.Integer(), sa.ForeignKey("manual_discovery_scans.id"), nullable=False),
            sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id"), nullable=False),
            sa.Column("matched_brand", sa.String(length=120), nullable=False),
            sa.Column("matched_sizes", sa.Text(), nullable=True),
            sa.Column("current_price", sa.Float(), nullable=True),
            sa.Column("discount_percentage", sa.Float(), nullable=True),
            sa.Column("is_tracked", sa.Boolean(), nullable=True),
            sa.Column("is_ignored", sa.Boolean(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
            sa.UniqueConstraint("scan_id", "product_id", name="uq_manual_scan_product"),
        )
        op.create_index("ix_manual_discovery_results_scan_id", "manual_discovery_results", ["scan_id"])
        op.create_index("ix_manual_discovery_results_product_id", "manual_discovery_results", ["product_id"])
        op.create_index("ix_manual_discovery_results_is_tracked", "manual_discovery_results", ["is_tracked"])
        op.create_index("ix_manual_discovery_results_is_ignored", "manual_discovery_results", ["is_ignored"])
        op.create_index("ix_manual_discovery_results_created_at", "manual_discovery_results", ["created_at"])
        op.create_index(
            "idx_manual_result_scan_visible",
            "manual_discovery_results",
            ["scan_id", "is_ignored", "created_at"],
        )


def downgrade() -> None:
    """Drop manual discovery scan/result and ignore-list tables."""
    bind = op.get_bind()
    if _has_table(bind, "manual_discovery_results"):
        op.drop_table("manual_discovery_results")
    if _has_table(bind, "manual_discovery_scans"):
        op.drop_table("manual_discovery_scans")
    if _has_table(bind, "product_ignores"):
        op.drop_table("product_ignores")

