"""Owned-schema migration API, deliberately absent from application Alembic.

Requires an already approved, connected, isolated schema with a pre-provisioned
canary_ownership marker. This module never opens a DB or loads an environment.
Real PostgreSQL execution is HOLD until explicit target approval and integration.
"""
import re
from sqlalchemy import select, text, func
from database import canary_schema as s
from services.canary_contracts import CanaryError


def _guard(connection, approval):
    if connection.dialect.name!='postgresql' or approval.environment!='disposable_test':
        raise CanaryError('POSTGRES_DISPOSABLE_APPROVAL_REQUIRED')
    namespace=connection.execute(text('SELECT current_schema()')).scalar_one()
    if not re.fullmatch(r'canary_stagea_[0-9a-f]{32}',namespace or ''):
        raise CanaryError('CANARY_NAMESPACE_REFUSED')
    marker=connection.execute(select(s.marker).where(s.marker.c.database_identity==approval.database_identity)).mappings().one_or_none()
    if not marker or marker['marker']!=approval.ownership_marker or marker['environment']!=approval.environment:
        raise CanaryError('CANARY_OWNERSHIP_REFUSED')
    return namespace


def upgrade(connection,approval):
    _guard(connection,approval)
    # Fail on pre-existing run tables: no implicit repair of an unknown schema.
    count=connection.execute(text("SELECT count(*) FROM pg_catalog.pg_tables WHERE schemaname=current_schema() AND tablename='canary_runs'")).scalar_one()
    if count:
        raise CanaryError('SCHEMA_ALREADY_INITIALIZED')
    s.metadata.create_all(connection)
    for statement in s.postgres_seal_guards():
        connection.execute(text(statement))


def downgrade(connection,approval):
    _guard(connection,approval)
    # Never use schema CASCADE or delete a source snapshot as run cleanup.
    if connection.execute(select(func.count()).select_from(s.runs)).scalar_one():
        raise CanaryError('RUNS_MUST_BE_EXPLICITLY_CLEANED_FIRST')
    # Retain owned source history and marker. Only remove empty run-owned tables.
    for table in reversed(s.metadata.sorted_tables):
        if table in s.RUN_TABLES:
            table.drop(connection,checkfirst=False)
    connection.execute(text('DROP FUNCTION canary_payload_guard()'))
    connection.execute(text('DROP TRIGGER canary_source_epoch_guard ON canary_source_lifecycle'))
    connection.execute(text('DROP FUNCTION canary_source_epoch_guard()'))
