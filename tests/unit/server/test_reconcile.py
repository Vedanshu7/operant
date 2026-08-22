"""
Runs orphaned by a restart are settled, and can still be cancelled.
"""

from __future__ import annotations

import asyncio
import pathlib
from typing import Tuple

import operant.adapters.secrets.factory as sffactor
import operant.domain.models.runs as mrruns
import operant.infra.db.engine as dbeng
import operant.infra.db.migrate as dbmig
import operant.infra.repositories.artifacts as raartifa
import operant.infra.repositories.graphs as rggraphs
import operant.infra.repositories.profiles as rpprofil
import operant.infra.repositories.runs as rrruns
import operant.server.jobs.hub as jhhub
import operant.server.jobs.lease as jhlease
import operant.server.jobs.manager as jmmanage
import tests.support.server as server
import tests.support.settings as tssettin


def _manager(
    tmp_path: pathlib.Path,
) -> Tuple[jmmanage.RunManager, rrruns.SqlRunRepository]:
    settings = tssettin.test_settings(tmp_path)
    server.seed(settings)
    database = dbeng.Database.open(settings.paths.db_path)
    dbmig.upgrade(database)
    runs = rrruns.SqlRunRepository(database)
    manager = jmmanage.RunManager(
        settings=settings,
        factory=server.ScriptedFactory(settings),
        artifacts=raartifa.FileArtifactRepository(settings.paths.artifacts_dir),
        graphs=rggraphs.FileGraphRepository(settings.paths.graphs_dir),
        profiles=rpprofil.FileProfileRepository(
            settings.paths.policies_dir, settings.paths.discovery_base_profile
        ),
        secret_store=sffactor.secret_store(settings.secrets),
        runs=runs,
        hub=jhhub.EventHub(asyncio.new_event_loop()),
        lease=jhlease.DriverLease(),
    )
    return manager, runs


def _orphan(runs: rrruns.SqlRunRepository, run_id: str, status: str) -> None:
    runs.create(
        mrruns.RunRecord(
            id=run_id, kind="replay", status="queued", vendor_id="app"
        )
    )
    runs.update_status(run_id, status)


def test_reconcile_fails_interrupted_runs(tmp_path: pathlib.Path) -> None:
    manager, runs = _manager(tmp_path)
    _orphan(runs, "r-live", "waiting_intervention")
    _orphan(runs, "r-done", "succeeded")
    settled = manager.reconcile_interrupted()
    assert settled == 1
    assert runs.get("r-live").status == "failed"
    assert runs.get("r-done").status == "succeeded"


def test_cancel_settles_an_orphan(tmp_path: pathlib.Path) -> None:
    manager, runs = _manager(tmp_path)
    _orphan(runs, "r-zombie", "waiting_intervention")
    manager.cancel("r-zombie")
    assert runs.get("r-zombie").status == "cancelled"
