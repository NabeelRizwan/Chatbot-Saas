"""Add structural persistence only; no backfill, extraction or activation.

Downgrade refuses populated sidecar history. Production rollback uses inactive
code paths, not destruction of immutable source versions.
"""
from alembic import op
from database import structural_schema_v1

revision = "20260916_01"
down_revision = "20260912_01"
branch_labels = None
depends_on = None


def upgrade():
    structural_schema_v1.upgrade(op.get_bind())


def downgrade():
    structural_schema_v1.downgrade(op.get_bind())
