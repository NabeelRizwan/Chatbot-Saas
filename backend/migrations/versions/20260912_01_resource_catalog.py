"""Universal resource catalog; no projection/backfill or chunk changes.

pg_trgm is retained on downgrade because another application may use it.
Run only as the existing explicit release migration, never per replica.
"""
from alembic import op
from sqlalchemy import MetaData, Table, inspect
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
    # The initial revision creates current metadata on an empty database. These
    # constraints and catalog tables may therefore already exist on first boot.
    inspector = inspect(bind)
    for table, name, columns in (
        ("bots", "uq_bots_resource_tenant", ["id", "organization_id"]),
        ("documents", "uq_documents_resource_tenant", ["id", "organization_id", "bot_id"]),
    ):
        existing = next((item for item in inspector.get_unique_constraints(table) if item['name'] == name), None)
        if existing is None:
            op.create_unique_constraint(name, table, columns)
        elif existing['column_names'] != columns:
            raise RuntimeError("Resource tenant constraint has an incompatible definition")
    metadata = MetaData()
    Table("bots", metadata, autoload_with=bind)
    Table("documents", metadata, autoload_with=bind)
    for table in define_tables(metadata):
        if inspector.has_table(table.name):
            actual = {column['name']: column for column in inspector.get_columns(table.name)}
            if set(actual) != set(table.c.keys()) or any(
                actual[column.name]['nullable'] != column.nullable or
                actual[column.name]['type']._type_affinity != column.type._type_affinity
                for column in table.c
            ):
                raise RuntimeError("Existing resource catalog table is incompatible: " + table.name)
        else:
            table.create(bind)
    install_postgres_indexes_and_triggers(bind)


def downgrade():
    for table in reversed(TABLE_NAMES):
        op.drop_table(table)
    op.execute("DROP FUNCTION resource_catalog_revision_v1()")
    op.drop_constraint("uq_documents_resource_tenant", "documents", type_="unique")
    op.drop_constraint("uq_bots_resource_tenant", "bots", type_="unique")
