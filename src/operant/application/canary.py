"""
Choosing canary replays: approved, read-only capabilities replayed on a
schedule with inputs they ran with before.

A capability breaks when its application's UI changes, usually long
before anyone next needs it. A canary replay finds that early, and each
failure counts toward degrading the capability (see
``operant.application.stability``).

Import as:

import operant.application.canary as apcanary
"""

from __future__ import annotations

import dataclasses
from typing import Dict, List, Optional

import operant.domain.errors as errors
import operant.domain.models.artifact as artifact
import operant.domain.models.runs as runs
import operant.ports.repositories as repos

# #############################################################################
# Canary
# #############################################################################


@dataclasses.dataclass(frozen=True)
class Canary:
    """
    One capability to replay, or why it is skipped.

    :ivar capability_id: The capability.
    :ivar inputs: Inputs to replay it with; ``None`` when skipped.
    :ivar skipped: Why it is not replayed, when skipped.
    """

    capability_id: str
    inputs: Optional[Dict[str, str]] = None
    skipped: str = ""


def plan_canaries(
    artifact_repo: repos.ArtifactRepository,
    run_repo: repos.RunRepository,
) -> List[Canary]:
    """
    Pick every approved capability a canary may replay unattended.

    Only read-only capabilities qualify: a canary must never move money
    or change data. Inputs come from the last successful replay, else
    from the discovery run; a capability with sensitive inputs is
    skipped because stored runs hold those values redacted.

    :param artifact_repo: Where capabilities live.
    :param run_repo: Where earlier runs and their inputs live.
    :return: One entry per approved capability, replayable or skipped.
    """
    canaries: List[Canary] = []
    for capability in artifact_repo.list():
        if capability.status != "approved":
            continue
        canaries.append(_plan(capability, run_repo))
    return canaries


def _plan(
    capability: artifact.CapabilityArtifact, run_repo: repos.RunRepository
) -> Canary:
    """
    Plan one approved capability's canary.
    """
    inputs = _known_inputs(capability, run_repo)
    if capability.policy_scope.touches_mutating_edges:
        # A canary never runs a step that changes data.
        canary = Canary(capability.id, skipped="it changes data")
    elif any(spec.sensitive for spec in capability.inputs.values()):
        # Stored runs hold sensitive inputs redacted.
        canary = Canary(capability.id, skipped="it takes sensitive inputs")
    elif inputs is None:
        # No earlier run to borrow inputs from.
        canary = Canary(capability.id, skipped="no earlier run's inputs")
    else:
        canary = Canary(capability.id, inputs=inputs)
    return canary


def _known_inputs(
    capability: artifact.CapabilityArtifact, run_repo: repos.RunRepository
) -> Optional[Dict[str, str]]:
    """
    Return inputs an earlier run used, covering every required input.
    """
    candidates = [
        run.inputs
        for run in run_repo.list(
            runs.RunFilter(
                kind="replay",
                status="succeeded",
                capability_id=capability.id,
                limit=1,
            )
        )
    ]
    try:
        candidates.append(
            run_repo.get(capability.provenance.discovery_run_id).inputs
        )
    except errors.NotFoundError:
        # The discovery ran elsewhere (another machine, an older database).
        pass
    required = {name for name, spec in capability.inputs.items() if spec.required}
    known = next(
        (dict(inputs) for inputs in candidates if required <= set(inputs)),
        None,
    )
    return known
