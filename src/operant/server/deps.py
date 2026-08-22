"""
Shared server state and the FastAPI dependencies that expose it.

``ServerState`` is built once in the app lifespan and stored on
``app.state``; route dependencies read it from the request. Keeping
every repository and the run manager here means routes never construct
their own database connections.

Import as:

import operant.server.deps as deps
"""

from __future__ import annotations

import dataclasses

import fastapi

import operant.infra.db.engine as engine
import operant.infra.repositories.artifacts as artifact
import operant.infra.repositories.graphs as rggraphs
import operant.infra.repositories.profiles as rpprofil
import operant.infra.repositories.runs as rrruns
import operant.infra.settings as issettin
import operant.ports.secrets as secrets
import operant.server.jobs.hub as jhhub
import operant.server.jobs.lease as jllease
import operant.server.jobs.manager as jmmanage

_STATE_ATTR = "operant_state"


# #############################################################################
# ServerState
# #############################################################################


@dataclasses.dataclass
class ServerState:
    """
    Everything the API routes share for the life of the process.

    :ivar settings: Loaded settings.
    :ivar database: Open run database at schema head.
    :ivar runs: Run, HITL, and stability repository.
    :ivar secret_refs: Secret-reference metadata repository.
    :ivar artifacts: Capability repository.
    :ivar graphs: Graph repository.
    :ivar profiles: Profile repository.
    :ivar secret_store: Configured secret store (presence checks only).
    :ivar manager: The run manager driving worker threads.
    :ivar hub: The event hub SSE subscribers read from.
    :ivar lease: The driver lease runs queue on.
    :ivar token: Bearer token required on every route.
    """

    settings: issettin.OperantSettings
    database: engine.Database
    runs: rrruns.SqlRunRepository
    secret_refs: rrruns.SqlSecretRefRepository
    artifacts: artifact.FileArtifactRepository
    graphs: rggraphs.FileGraphRepository
    profiles: rpprofil.FileProfileRepository
    secret_store: secrets.SecretStore
    manager: jmmanage.RunManager
    hub: jhhub.EventHub
    lease: jllease.DriverLease
    token: str


def install(app: fastapi.FastAPI, state: ServerState) -> None:
    """
    Store the shared state on the app for dependencies to read.
    """
    setattr(app.state, _STATE_ATTR, state)


def get_state(request: fastapi.Request) -> ServerState:
    """
    Return the shared server state for the current request.
    """
    state: ServerState = getattr(request.app.state, _STATE_ATTR)
    return state
