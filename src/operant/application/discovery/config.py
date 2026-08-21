"""
The discovery run's typed contract: config, result, and failure.

Import as:

import operant.application.discovery.config as config
"""

from __future__ import annotations

import dataclasses
from typing import Dict, List, Optional

import operant.application.recorder.recording as recdng
import operant.domain.approval as approval
import operant.domain.models.graph as dmgraph
import operant.domain.profile as dmprofil
import operant.ports.hitl as hitl

# #############################################################################
# DiscoveryConfig
# #############################################################################


@dataclasses.dataclass
class DiscoveryConfig:
    """
    Everything one discovery run needs.

    :ivar goal: The natural-language goal.
    :ivar capability_id: Id the resulting capability is saved under.
    :ivar capability_name: Human-readable capability name.
    :ivar inputs: Optional pre-seeded task inputs; the agent declares
        the rest itself.
    :ivar profile: The app profile, or the discovery base in bootstrap
        mode.
    :ivar tenant: Tenant binding to run against.
    :ivar bootstrap:``True`` when no vendor is pre-seeded - the model
        decides the entry and the vendor is derived from it.
    :ivar max_turns: Turn budget before the run fails.
    :ivar screenshots: Whether to send screenshots to the model.
    :ivar clarifier: Answers the agent's clarifying question; ``None``
        means no channel (the agent resolves values itself or gives up).
    :ivar approver: Answers approval requests; ``None`` routes to the
        operator console via the broker.
    :ivar known_graph: The app's current graph, when one exists, so the
        agent can be told which mapped state the live screen matches and
        skip steps already recorded (empty for a first/bootstrap run).
    """

    goal: str
    capability_id: str
    capability_name: str
    inputs: Dict[str, str]
    profile: dmprofil.AppProfile
    tenant: str
    bootstrap: bool = False
    max_turns: int = 40
    screenshots: bool = True
    clarifier: Optional[hitl.Clarifier] = None
    approver: Optional[hitl.Approver] = None
    credential_requester: Optional[hitl.CredentialRequester] = None
    known_graph: Optional[dmgraph.AppGraph] = None


# #############################################################################
# DiscoveryResult
# #############################################################################


@dataclasses.dataclass
class DiscoveryResult:
    """
    A successful discovery run.

    :ivar recording: What was recorded; the caller commits it.
    :ivar profile: The effective profile - derived in bootstrap mode,
        widened by grants in profile mode. Persisting it is what makes
        the recording replayable.
    :ivar grants: Scope grants a human made during the run.
    """

    recording: recdng.Recording
    profile: dmprofil.AppProfile
    grants: List[approval.ScopeGrant] = dataclasses.field(default_factory=list)


# #############################################################################
# DiscoveryFailure
# #############################################################################


@dataclasses.dataclass(frozen=True)
class DiscoveryFailure:
    """
    A discovery run that did not produce a recording.

    :ivar reason: Human-readable explanation.
    :ivar failure_class: Machine-readable class of the failure.
    """

    reason: str
    failure_class: str = "discovery_failed"
