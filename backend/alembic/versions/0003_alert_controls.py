"""Alert-noise controls: severity, per-product mute, per-user alert level.

Adds ``alerts.severity`` (urgent/important/info, used to decide instant vs
digest vs inbox-only delivery), ``products.alert_muted_until`` (the "Mute 24h"
button) and ``user_settings.alert_level`` (Calm/Balanced/Everything). All
columns have defaults so existing rows keep working unchanged.

Revision ID: 0003_alert_controls
Revises: 0002_price_thresholds
Create Date: 2026-10-24
"""

import sqlalchemy as sa

from alembic import op

revision = "0003_alert_controls"
down_revision = "0002_price_thresholds"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("alerts") as batch:
        batch.add_column(
            sa.Column(
                "severity",
                sa.String(length=16),
                nullable=False,
                server_default="important",
            )
        )
    with op.batch_alter_table("products") as batch:
        batch.add_column(
            sa.Column("alert_muted_until", sa.DateTime(timezone=True), nullable=True)
        )
    with op.batch_alter_table("user_settings") as batch:
        batch.add_column(
            sa.Column(
                "alert_level",
                sa.String(length=16),
                nullable=False,
                server_default="balanced",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("user_settings") as batch:
        batch.drop_column("alert_level")
    with op.batch_alter_table("products") as batch:
        batch.drop_column("alert_muted_until")
    with op.batch_alter_table("alerts") as batch:
        batch.drop_column("severity")
