"""Frozen Phase 3 catalog schema shared by declarative registration/migration.

Future schema changes belong in a new migration, not edits to this definition.
No connection is opened and no customer rows are projected by importing it.
"""
from datetime import datetime
from sqlalchemy import (BigInteger, Column, DateTime, ForeignKeyConstraint, Index,
                        Integer, JSON, String, Table, Text, UniqueConstraint, event, text)

TABLE_NAMES = ("resource_catalog_state", "knowledge_resources",
               "knowledge_resource_terms", "knowledge_resource_documents")


def define_tables(metadata):
    def tenant():
        return [Column("organization_id", Integer, nullable=False), Column("bot_id", Integer, nullable=False)]
    def dates():
        return [Column("created_at", DateTime, default=datetime.utcnow, nullable=False),
                Column("updated_at", DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)]
    def bot_fk():
        return ForeignKeyConstraint(["bot_id", "organization_id"], ["bots.id", "bots.organization_id"], ondelete="CASCADE")
    def resource_fk():
        return ForeignKeyConstraint(["resource_id", "organization_id", "bot_id"],
                                    ["knowledge_resources.id", "knowledge_resources.organization_id", "knowledge_resources.bot_id"], ondelete="CASCADE")
    state = Table(TABLE_NAMES[0], metadata, *tenant(), Column("revision", BigInteger, nullable=False, server_default="0"),
                  Column("updated_at", DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
                  bot_fk())
    # Composite primary key is also the per-bot revision upsert key.
    from sqlalchemy import PrimaryKeyConstraint
    state.append_constraint(PrimaryKeyConstraint("organization_id", "bot_id"))
    resource = Table(TABLE_NAMES[1], metadata, Column("id", Integer, primary_key=True), *tenant(),
        Column("resource_type", String(80), nullable=False, default="document"),
        Column("canonical_name", Text, nullable=False), Column("normalized_canonical_name", Text, nullable=False),
        Column("title", Text), Column("summary", Text), Column("url", Text), Column("breadcrumb", JSON),
        Column("parent_resource_id", Integer), Column("source_key", String(240), nullable=False),
        Column("status", String(32), nullable=False, default="ready"), Column("version", Integer, nullable=False, default=1),
        Column("metadata_json", JSON, nullable=False, default=dict), *dates(), bot_fk(),
        UniqueConstraint("id", "organization_id", "bot_id", name="uq_resources_tenant_identity"),
        UniqueConstraint("organization_id", "bot_id", "source_key", name="uq_resources_source_key"),
        ForeignKeyConstraint(["parent_resource_id", "organization_id", "bot_id"],
                             ["knowledge_resources.id", "knowledge_resources.organization_id", "knowledge_resources.bot_id"]),
        Index("ix_resources_tenant_status", "organization_id", "bot_id", "status"))
    terms = Table(TABLE_NAMES[2], metadata, Column("id", Integer, primary_key=True), *tenant(),
        Column("resource_id", Integer, nullable=False), Column("term_text", Text, nullable=False),
        Column("normalized_term", Text, nullable=False), Column("term_kind", String(40), nullable=False),
        Column("term_source", String(40), nullable=False),
        Column("source_document_id", Integer), Column("source_version", Integer), Column("source_crawl_id", Integer),
        *dates(), resource_fk(),
        ForeignKeyConstraint(["source_document_id", "organization_id", "bot_id"],
                             ["documents.id", "documents.organization_id", "documents.bot_id"], ondelete="CASCADE"),
        Index("ix_resource_terms_exact_v1", "organization_id", "bot_id", "normalized_term"),
        Index("ix_resource_terms_resource_v1", "resource_id", "organization_id", "bot_id"))
    links = Table(TABLE_NAMES[3], metadata, *tenant(), Column("resource_id", Integer, primary_key=True),
        Column("document_id", Integer, primary_key=True), Column("relation_type", String(32), nullable=False, default="primary"),
        Column("document_version", Integer, nullable=False), Column("document_crawl_id", Integer),
        *dates(), resource_fk(),
        ForeignKeyConstraint(["document_id", "organization_id", "bot_id"],
                             ["documents.id", "documents.organization_id", "documents.bot_id"], ondelete="CASCADE"),
        Index("ix_resource_docs_anchor_v1", "organization_id", "bot_id", "document_id", "resource_id"))
    for table in (resource, terms, links):
        event.listen(table, "after_create", _sqlite_revision_triggers)
    return state, resource, terms, links


def _sqlite_revision_triggers(table, connection, **_):
    if connection.dialect.name != "sqlite":
        return
    # Table/trigger names are fixed application identifiers, never user input.
    for operation, refs in (("INSERT", ("NEW",)), ("DELETE", ("OLD",)), ("UPDATE", ("OLD", "NEW"))):
        statements = " ".join(
            "INSERT INTO resource_catalog_state (organization_id,bot_id,revision,updated_at) "
            f"SELECT {ref}.organization_id,{ref}.bot_id,1,CURRENT_TIMESTAMP FROM bots "
            f"WHERE id={ref}.bot_id AND organization_id={ref}.organization_id "
            "ON CONFLICT (organization_id,bot_id) DO UPDATE SET revision=revision+1,updated_at=CURRENT_TIMESTAMP;"
            for ref in refs)
        connection.exec_driver_sql(f"CREATE TRIGGER {table.name}_revision_{operation.lower()} AFTER {operation} ON {table.name} BEGIN {statements} END")


REVISION_FUNCTION_SQL = """
CREATE FUNCTION resource_catalog_revision_v1() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP <> 'INSERT' THEN
    INSERT INTO resource_catalog_state (organization_id,bot_id,revision,updated_at)
    SELECT OLD.organization_id,OLD.bot_id,1,CURRENT_TIMESTAMP FROM bots
    WHERE id=OLD.bot_id AND organization_id=OLD.organization_id
    ON CONFLICT (organization_id,bot_id) DO UPDATE
    SET revision=resource_catalog_state.revision+1,updated_at=CURRENT_TIMESTAMP;
  END IF;
  IF TG_OP <> 'DELETE' THEN
    INSERT INTO resource_catalog_state (organization_id,bot_id,revision,updated_at)
    SELECT NEW.organization_id,NEW.bot_id,1,CURRENT_TIMESTAMP FROM bots
    WHERE id=NEW.bot_id AND organization_id=NEW.organization_id
    ON CONFLICT (organization_id,bot_id) DO UPDATE
    SET revision=resource_catalog_state.revision+1,updated_at=CURRENT_TIMESTAMP;
  END IF;
  RETURN NULL;
END $$
"""


def install_postgres_indexes_and_triggers(connection):
    connection.exec_driver_sql("CREATE INDEX ix_resource_terms_fts_simple_v1 ON knowledge_resource_terms USING gin (to_tsvector('simple'::regconfig, normalized_term))")
    connection.exec_driver_sql("CREATE INDEX ix_resource_terms_trgm_v1 ON knowledge_resource_terms USING gin (normalized_term gin_trgm_ops)")
    # Pin identifier lookup to the schema that owns these tables. A caller's
    # search_path (or temp tables) must not redirect revision writes.
    schema = connection.execute(text("SELECT current_schema()")).scalar_one()
    quoted = connection.dialect.identifier_preparer.quote_identifier(schema)
    connection.exec_driver_sql(REVISION_FUNCTION_SQL.replace(
        "LANGUAGE plpgsql", f"LANGUAGE plpgsql SET search_path TO pg_catalog, {quoted}, pg_temp"))
    for name in TABLE_NAMES[1:]:
        connection.exec_driver_sql(f"CREATE TRIGGER {name}_revision AFTER INSERT OR UPDATE OR DELETE ON {name} FOR EACH ROW EXECUTE FUNCTION resource_catalog_revision_v1()")
