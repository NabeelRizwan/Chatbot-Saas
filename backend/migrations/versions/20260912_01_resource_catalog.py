"""Universal resource catalog; no projection/backfill or chunk changes.

pg_trgm is retained on downgrade because another application may use it.
Run only as the existing explicit release migration, never per replica.
"""
from alembic import op
from sqlalchemy import MetaData, Table
from database.resource_schema_v1 import TABLE_NAMES, define_tables, install_postgres_indexes_and_triggers

revision = "20260912_01"
down_revision = "20260910_01"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        raise RuntimeError("Resource catalog release migration requires PostgreSQL")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.create_unique_constraint("uq_bots_resource_tenant", "bots", ["id", "organization_id"])
    op.create_unique_constraint("uq_documents_resource_tenant", "documents", ["id", "organization_id", "bot_id"])
    metadata = MetaData()
    Table("bots", metadata, autoload_with=bind)
    Table("documents", metadata, autoload_with=bind)
    for table in define_tables(metadata):
        table.create(bind)
    install_postgres_indexes_and_triggers(bind)


def downgrade():
    for table in reversed(TABLE_NAMES):
        op.drop_table(table)
    op.execute("DROP FUNCTION resource_catalog_revision_v1()")
    op.drop_constraint("uq_documents_resource_tenant", "documents", type_="unique")
    op.drop_constraint("uq_bots_resource_tenant", "bots", type_="unique")
