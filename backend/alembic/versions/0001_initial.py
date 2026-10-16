"""initial ShelfSense schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-10-16
"""

from alembic import op

from app.models import Base

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # SQLAlchemy generic types keep this first migration portable across SQLite and Postgres.
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())

