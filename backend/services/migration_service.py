"""Alembic configuration and migration-state helpers."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy.engine import Connection

from database.connection import DATABASE_URL


BACKEND_DIR = Path(__file__).resolve().parents[1]


def alembic_config(
    database_url: str | None = None,
    version_table_schema: str | None = None,
) -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    config.set_main_option(
        "sqlalchemy.url",
        (database_url or DATABASE_URL).replace("%", "%%"),
    )
    if version_table_schema:
        config.set_main_option("version_table_schema", version_table_schema)
    return config


def upgrade_to_head(
    database_url: str | None = None,
    version_table_schema: str | None = None,
) -> None:
    command.upgrade(alembic_config(database_url, version_table_schema), "head")


def migration_state(
    connection: Connection,
    version_table_schema: str | None = None,
) -> tuple[str | None, str]:
    config = alembic_config(str(connection.engine.url), version_table_schema)
    current = MigrationContext.configure(
        connection,
        opts={"version_table_schema": version_table_schema},
    ).get_current_revision()
    head = ScriptDirectory.from_config(config).get_current_head()
    if head is None:
        raise RuntimeError("Alembic migration history has no head revision")
    return current, head
