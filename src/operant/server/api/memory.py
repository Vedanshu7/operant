"""
Agent-memory route: what earlier runs taught the agents, read-only.

Import as:

import operant.server.api.memory as srmemory
"""

from __future__ import annotations

from typing import Annotated, Any, Optional

import fastapi

import operant.application.gateway.learner as gllearne
import operant.application.memory as apmemory
import operant.application.remediation as remem
import operant.infra.repositories.learned_tools as learned_
import operant.infra.repositories.memory as rmmemory
import operant.infra.repositories.remediations as rgremed
import operant.server.deps as deps

router = fastapi.APIRouter(tags=["memory"])

State = Annotated[deps.ServerState, fastapi.Depends(deps.get_state)]


@router.get("/memory")
def get_memory(state: State, app: Optional[str] = None) -> Any:
    """
    Return plans, lessons, learned tools, and remedies, optionally for one app.
    """
    paths = state.settings.paths
    view = apmemory.summary(
        apmemory.AgentMemory(rmmemory.SqlMemoryStore(state.database)),
        learned=gllearne.ToolLearner(
            learned_.LearnedToolsStore(paths.learned_tools)
        ).entries(),
        remedies=remem.RemediationMemory(
            rgremed.RemediationsStore(paths.remediations)
        ).entries(),
        app=app,
    )
    return view
