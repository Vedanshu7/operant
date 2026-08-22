"""
Programmatic Alembic entry points used by ``operant migrate`` and tests.

Import as:

import operant.infra.db.migrate as migrate
"""

from __future__ import annotations

import pathlib
from typing import Optional

import alembic.command as command
import alembic.config

import operant.infra.db.engine as engine

_MIGRATIONS = pathlib.Path(__file__).parent / "migrations"


def alembic_config(database: engine.Database) -> alembic.config.Config:
    """
    Build an Alembic config bound to an open database.
    """
    config = alembic.config.Config()
    config.set_main_option("script_location", str(_MIGRATIONS))
    config.set_main_option("sqlalchemy.url", database.url)
    return config


def upgrade(database: engine.Database, revision: str = "head") -> None:
    """
    Apply migrations up to ``revision`` on ``database``.
    """
    config = alembic_config(database)
    with database.engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, revision)


def current_revision(database: engine.Database) -> Optional[str]:
    """
    Return the revision the database is at, or ``None`` if unversioned.
    """
    import alembic.runtime.migration as migratio

    # Ask the migration context what revision the schema is stamped at.
    with database.engine.connect() as connection:
        context = migratio.MigrationContext.configure(connection)
        revision = context.get_current_revision()
    return revision
