"""
Objects every CLI command needs, built once per invocation.

Import as:

import operant.cli.deps as cddeps
"""

from __future__ import annotations

import dataclasses
from typing import Optional, Tuple

import filelock

import operant.adapters.secrets.factory as factory
import operant.application.context as context
import operant.helpers.logging as logging
import operant.infra.db.engine as engine
import operant.infra.db.migrate as migrate
import operant.infra.repositories.artifacts as artifact
import operant.infra.repositories.graphs as rggraphs
import operant.infra.repositories.profiles as rpprofil
import operant.infra.repositories.runs as runs
import operant.infra.settings as issettin
import operant.ports.secrets as secrets

_LOG = logging.get_logger(__name__)


# #############################################################################
# CliDeps
# #############################################################################


@dataclasses.dataclass
class CliDeps:
    """
    Settings plus the repositories and stores commands share.

    :ivar settings: Loaded settings.
    :ivar graphs: Graph repository.
    :ivar artifacts: Artifact repository.
    :ivar profiles: Profile repository.
    :ivar secret_store: Configured secret store.
    """

    settings: issettin.OperantSettings
    graphs: rggraphs.FileGraphRepository
    artifacts: artifact.FileArtifactRepository
    profiles: rpprofil.FileProfileRepository
    secret_store: secrets.SecretStore
    _screen_lock: Optional[filelock.FileLock] = dataclasses.field(
        default=None, init=False, repr=False
    )

    @classmethod
    def build(cls, settings: issettin.OperantSettings) -> CliDeps:
        """
        Wire the dependencies from ``settings``.
        """
        paths = settings.paths
        deps = cls(
            settings=settings,
            graphs=rggraphs.FileGraphRepository(paths.graphs_dir),
            artifacts=artifact.FileArtifactRepository(paths.artifacts_dir),
            profiles=rpprofil.FileProfileRepository(
                paths.policies_dir, paths.discovery_base_profile
            ),
            secret_store=factory.secret_store(settings.secrets),
        )
        return deps

    def run_factory(self) -> context.RunContextFactory:
        """
        Build a run-context factory for this invocation.

        Takes the screen lock first, held until the command exits, so a
        CLI run never drives the screen while the server (or another CLI
        run) does.
        """
        if self._screen_lock is None:
            path = self.settings.paths.screen_lock
            path.parent.mkdir(parents=True, exist_ok=True)
            self._screen_lock = filelock.FileLock(str(path))
            try:
                self._screen_lock.acquire(timeout=0)
            except filelock.Timeout:
                # Another run holds the screen: say so, then wait for it.
                _LOG.warning("another run is driving the screen; waiting")
                self._screen_lock.acquire()
        run_context_factory = context.RunContextFactory(self.settings)
        return run_context_factory

    def open_runs(
        self,
    ) -> Tuple[engine.Database, runs.SqlRunRepository]:
        """
        Open the run database at HEAD, returning it and the repository.
        """
        database = engine.Database.open(self.settings.paths.db_path)
        migrate.upgrade(database)
        repository = runs.SqlRunRepository(database)
        return database, repository
