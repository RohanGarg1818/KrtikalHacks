"""The seller's own ShelfSense Store: per-product price and stock set by hand.

Revision ID: 0004_store_listings
Revises: 0003_alert_controls
Create Date: 2026-10-25
"""

import sqlalchemy as sa

from alembic import op

revision = "0004_store_listings"
down_revision = "0003_alert_controls"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "store_listings",
        sa.Column(
            "product_id",
            sa.String(length=36),
            sa.ForeignKey("products.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("mrp", sa.Float(), nullable=True),
        sa.Column("stock", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("eta_minutes", sa.Integer(), nullable=False, server_default="15"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("store_listings")
