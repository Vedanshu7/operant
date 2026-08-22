"""Engine and session factory for the SQLite database.

Typical usage example:

  database = Database.open(settings.paths.db_path)
  database.migrate()
  with database.session() as session:
      ...

Import as:

import operant.infra.db.engine as engine
"""

from __future__ import annotations

import collections.abc
import contextlib
import dataclasses
import pathlib
from typing import Optional

import sqlalchemy
import sqlalchemy.orm as orm

import operant.infra.db.models as models


def sqlite_url(path: Optional[pathlib.Path]) -> str:
    """
    Build a SQLAlchemy URL; ``None`` selects an in-memory database.
    """
    if path is None:
        url = "sqlite+pysqlite:///:memory:"
    else:
        url = f"sqlite+pysqlite:///{path}"
    return url


# #############################################################################
# Database
# #############################################################################


@dataclasses.dataclass
class Database:
    """
    An open database with a session factory.

    :ivar engine: The SQLAlchemy engine.
    :ivar url: The URL the engine was created from.
    """

    engine: sqlalchemy.Engine
    url: str

    @classmethod
    def open(cls, path: Optional[pathlib.Path]) -> Database:
        """
        Open (creating directories for) the database at ``path``.

        In-memory databases use a static pool so every session sees the
        same connection, which is what tests need.
        """
        url = sqlite_url(path)
        if path is None:
            # In-memory: share one connection across sessions via a
            # static pool.
            engine = sqlalchemy.create_engine(
                url,
                connect_args={"check_same_thread": False},
                poolclass=sqlalchemy.pool.StaticPool,
            )
        else:
            # File-backed: create the parent directory and open the file.
            path.parent.mkdir(parents=True, exist_ok=True)
            engine = sqlalchemy.create_engine(
                url, connect_args={"check_same_thread": False}
            )
        _enable_foreign_keys(engine)
        database = cls(engine=engine, url=url)
        return database

    def create_all(self) -> None:
        """
        Create every table directly (tests and first-run bootstrap).
        """
        models.Base.metadata.create_all(self.engine)

    @contextlib.contextmanager
    def session(self) -> collections.abc.Iterator[orm.Session]:
        """
        Yield a session that commits on success and rolls back on error.
        """
        session = orm.Session(self.engine, expire_on_commit=False)
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def close(self) -> None:
        """
        Dispose the engine's connections.
        """
        self.engine.dispose()


def _enable_foreign_keys(engine: sqlalchemy.Engine) -> None:
    """
    Enable foreign-key and WAL pragmas on every new connection.
    """

    @sqlalchemy.event.listens_for(engine, "connect")
    def _on_connect(connection: object, _record: object) -> None:
        cursor = connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()
