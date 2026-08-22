"""
Alembic environment: runs migrations against the configured SQLite URL.
"""

from __future__ import annotations

import logging.config

import alembic.context as context
import sqlalchemy

import operant.infra.db.models as models

config = context.config
if config.config_file_name is not None:
    logging.config.fileConfig(config.config_file_name)

target_metadata = models.Base.metadata


def run_migrations_offline() -> None:
    """
    Emit SQL without a live connection.
    """
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """
    Apply migrations over a real connection.
    """
    connectable = context.config.attributes.get("connection")
    if connectable is None:
        # No connection injected: build a throwaway engine and connect.
        engine = sqlalchemy.engine_from_config(
            config.get_section(config.config_ini_section, {}),
            prefix="sqlalchemy.",
            poolclass=sqlalchemy.pool.NullPool,
        )
        with engine.connect() as connection:
            _run(connection)
    else:
        # A connection was injected (e.g. by tests): use it directly.
        _run(connectable)


def _run(connection: sqlalchemy.Connection) -> None:
    """
    Configure the context and run migrations over ``connection``.
    """
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
