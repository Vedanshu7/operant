"""
The capability artifact: the contract pinned to a graph version.

A capability no longer carries steps. It names a start and goal node in
the application graph, the typed IO, tenant bindings, policy scope, and
a compiled path cached for deterministic replay (re-planned only when
the graph changed or an edge is blocked). It pins the ``graph_version``
it compiled against, so capability + graph replay reproducibly. Stored
as ``artifacts/<id>.json``.

Import as:

import operant.domain.models.artifact as artifact
"""

from __future__ import annotations

from typing import Dict, Final, List, Literal, Optional

import pydantic

import operant.domain.models.graph as graph

SCHEMA_VERSION: Final = graph.SCHEMA_VERSION

DataClass = Literal["none", "pii", "financial", "credential"]


# #############################################################################
# ExtractSpec
# #############################################################################


class ExtractSpec(pydantic.BaseModel):
    """
    One output read from the screen at ``extract_at_node``.

    :ivar output: output name the value is stored under.
    :ivar pattern: regex over the digest text; group 1 (or the whole
        match) is the value.
    """

    output: str
    pattern: str


# #############################################################################
# IoField
# #############################################################################


class IoField(pydantic.BaseModel):
    """
    A declared capability input.

    :ivar type: value type.
    :ivar description: what the input is.
    :ivar required: whether a run must supply it.
    :ivar sensitive: whether the value is redacted from evidence.
    :ivar data_class: sensitivity class of the value.
    """

    type: Literal["string", "number", "boolean"] = "string"
    description: str
    required: bool = True
    sensitive: bool = False
    data_class: DataClass = "none"


# #############################################################################
# OutField
# #############################################################################


class OutField(pydantic.BaseModel):
    """
    A declared capability output.

    :ivar type: value type.
    :ivar description: what the output is.
    :ivar data_class: sensitivity class of the value.
    """

    type: Literal["string", "number", "boolean"] = "string"
    description: str
    data_class: DataClass = "none"


# #############################################################################
# TenantBinding
# #############################################################################


class TenantBinding(pydantic.BaseModel):
    """
    Where one tenant's instance of the application lives.

    :ivar base_url: root URL of the tenant's instance.
    :ivar entry_path: path appended to ``base_url`` on launch, e.g.
        ``/index.htm``.
    :ivar secret_refs: ref name -> env var name (never values).
    """

    base_url: str
    entry_path: str = ""
    secret_refs: Dict[str, str] = {}


# #############################################################################
# PolicyScope
# #############################################################################


class PolicyScope(pydantic.BaseModel):
    """
    What the capability needs the policy to allow.

    :ivar policy_id: policy document the capability runs under.
    :ivar required_action_kinds: action kinds the path performs.
    :ivar touches_mutating_edges: whether any edge on the path mutates.
    """

    policy_id: str
    required_action_kinds: List[str]
    touches_mutating_edges: bool


# #############################################################################
# Accessibility
# #############################################################################


class Accessibility(pydantic.BaseModel):
    """
    How much a capability's steps rely on the accessibility tree.

    A step located by a control's name or label survives restyling; one
    recorded as a screen position, or on a control with no name or
    label, breaks when the layout changes (ADR 8).

    :ivar steps: steps that act on a target (click, fill, select).
    :ivar coordinate_steps: of those, steps recorded as a screen point.
    :ivar unnamed_steps: of those, steps on a control with no name or
        label, located only by tree path or position.
    """

    steps: int = 0
    coordinate_steps: int = 0
    unnamed_steps: int = 0

    @property
    def score(self) -> Optional[float]:
        """
        Return the share of targeted steps located by name or label.
        """
        if not self.steps:
            return None
        weak = self.coordinate_steps + self.unnamed_steps
        return 1 - weak / self.steps


# #############################################################################
# Provenance
# #############################################################################


class Provenance(pydantic.BaseModel):
    """
    How the capability came to exist.

    :ivar discovery_run_id: run that discovered it.
    :ivar model: model that drove discovery.
    :ivar recorded_at: ISO timestamp of the recording.
    :ivar goal: natural-language goal given to discovery.
    """

    discovery_run_id: str
    model: str
    recorded_at: str
    goal: str


# #############################################################################
# Stability
# #############################################################################


class Stability(pydantic.BaseModel):
    """
    Replay track record over the most recent replays.

    :ivar runs: replays attempted.
    :ivar successes: replays that succeeded.
    :ivar last_run_at: ISO timestamp of the last replay.
    :ivar consecutive_failures: failed replays since the last success.
    """

    runs: int = 0
    successes: int = 0
    last_run_at: str = ""
    consecutive_failures: int = 0


# #############################################################################
# CapabilityArtifact
# #############################################################################


class CapabilityArtifact(pydantic.BaseModel):
    """
    A capability: a path query over the application graph.

    :ivar schema_version: on-disk schema version this document uses.
    :ivar id: capability id; also the file stem.
    :ivar name: display name.
    :ivar description: what the capability does.
    :ivar version: monotonic version of this artifact.
    :ivar status: ``draft`` until a human approves it; ``degraded``
        once an approved capability keeps failing, until re-approved.
    :ivar vendor_id: application graph the capability traverses.
    :ivar graph_version: graph version the path was compiled against.
    :ivar tenants: tenant bindings keyed by tenant name.
    :ivar default_tenant: tenant used when a run names none.
    :ivar inputs: declared inputs keyed by name.
    :ivar outputs: declared outputs keyed by name.
    :ivar start_node: start node id; ``*`` = start wherever we are.
    :ivar goal_node: goal node id.
    :ivar extract_at_node: where declared outputs are read (default:
        goal).
    :ivar extract: capability-scoped extraction, read at
        ``extract_at_node``. Lives on the capability, not on the
        shared graph edges, so different capabilities can read
        different things from the same screen.
    :ivar compiled_path: ordered edge ids; empty = plan at run time.
    :ivar policy_scope: what the policy must allow.
    :ivar provenance: how the capability was discovered.
    :ivar stability: replay track record, once any replay ran.
    :ivar accessibility: how much the steps rely on the accessibility tree.
    """

    schema_version: graph.ACCEPTED_SCHEMA_VERSIONS = SCHEMA_VERSION
    id: str
    name: str
    description: str
    version: int = 1
    status: Literal["draft", "approved", "degraded"] = "draft"
    vendor_id: str
    graph_version: int
    tenants: Dict[str, TenantBinding]
    default_tenant: str
    inputs: Dict[str, IoField] = {}
    outputs: Dict[str, OutField] = {}
    start_node: str
    goal_node: str
    extract_at_node: Optional[str] = None
    extract: List[ExtractSpec] = []
    compiled_path: List[str] = []
    policy_scope: PolicyScope
    provenance: Provenance
    accessibility: Optional[Accessibility] = None
    stability: Optional[Stability] = None
