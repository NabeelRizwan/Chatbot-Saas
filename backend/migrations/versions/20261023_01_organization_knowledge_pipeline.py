"""Pin existing organisations to OG; default new organisations to RAG2 Improved.

Revision ID: 20261023_01
Revises: 20261012_01
"""
from alembic import op
import sqlalchemy as sa

revision = "20261023_01"
down_revision = "20261012_01"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("organizations")}
    # The baseline migration creates current metadata on a fresh installation.
    # Only pre-existing tables need the conservative OG backfill.
    if "knowledge_pipeline" not in columns:
        op.add_column("organizations", sa.Column("knowledge_pipeline", sa.String(32),
                      nullable=False, server_default="og"))
    if "knowledge_pipeline_revision" not in columns:
        op.add_column("organizations", sa.Column("knowledge_pipeline_revision", sa.Integer(),
                      nullable=False, server_default="1"))
    constraints = {item["name"] for item in sa.inspect(op.get_bind()).get_check_constraints("organizations")}
    with op.batch_alter_table("organizations") as batch:
        batch.alter_column("knowledge_pipeline", existing_type=sa.String(32), nullable=False,
                           server_default="rag2_improved")
        if "ck_org_knowledge_pipeline" not in constraints:
            batch.create_check_constraint("ck_org_knowledge_pipeline", "knowledge_pipeline IN ('og', 'rag2_improved')")
        if "ck_org_knowledge_pipeline_revision" not in constraints:
            batch.create_check_constraint("ck_org_knowledge_pipeline_revision", "knowledge_pipeline_revision >= 1")


def downgrade():
    with op.batch_alter_table("organizations") as batch:
        batch.drop_constraint("ck_org_knowledge_pipeline_revision", type_="check")
        batch.drop_constraint("ck_org_knowledge_pipeline", type_="check")
        batch.drop_column("knowledge_pipeline_revision")
        batch.drop_column("knowledge_pipeline")
