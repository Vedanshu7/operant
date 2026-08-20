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

    :ivar output: Output name the value is stored under.
    :ivar pattern: Regex over the digest text; group 1 (or the whole
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

    :ivar type: Value type.
    :ivar description: What the input is.
    :ivar required: Whether a run must supply it.
    :ivar sensitive: Whether the value is redacted from evidence.
    :ivar data_class: Sensitivity class of the value.
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

    :ivar type: Value type.
    :ivar description: What the output is.
    :ivar data_class: Sensitivity class of the value.
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

    :ivar base_url: Root URL of the tenant's instance.
    :ivar entry_path: Path appended to ``base_url`` on launch, e.g.
        ``/index.htm``.
    :ivar secret_refs: Ref name -> env var name (never values).
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

    :ivar policy_id: Policy document the capability runs under.
    :ivar required_action_kinds: Action kinds the path performs.
    :ivar touches_mutating_edges: Whether any edge on the path mutates.
    """

    policy_id: str
    required_action_kinds: List[str]
    touches_mutating_edges: bool


# #############################################################################
# Provenance
# #############################################################################


class Provenance(pydantic.BaseModel):
    """
    How the capability came to exist.

    :ivar discovery_run_id: Run that discovered it.
    :ivar model: Model that drove discovery.
    :ivar recorded_at: ISO timestamp of the recording.
    :ivar goal: Natural-language goal given to discovery.
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
    Replay track record.

    :ivar runs: Replays attempted.
    :ivar successes: Replays that succeeded.
    :ivar last_run_at: ISO timestamp of the last replay.
    """

    runs: int = 0
    successes: int = 0
    last_run_at: str = ""


# #############################################################################
# CapabilityArtifact
# #############################################################################


class CapabilityArtifact(pydantic.BaseModel):
    """A capability: a path query over the application graph.

    :ivar schema_version: On-disk schema version this document uses.
    :ivar id: Capability id; also the file stem.
    :ivar name: Display name.
    :ivar description: What the capability does.
    :ivar version: Monotonic version of this artifact.
    :ivar status: ``draft`` until a human approves it.
    :ivar vendor_id: Application graph the capability traverses.
    :ivar graph_version: Graph version the path was compiled against.
    :ivar tenants: Tenant bindings keyed by tenant name.
    :ivar default_tenant: Tenant used when a run names none.
    :ivar inputs: Declared inputs keyed by name.
    :ivar outputs: Declared outputs keyed by name.
    :ivar start_node: Start node id; ``*`` = start wherever we are.
    :ivar goal_node: Goal node id.
    :ivar extract_at_node: Where declared outputs are read (default:
        goal).
    :ivar extract: Capability-scoped extraction, read at
        ``extract_at_node``. Lives on the capability, not on the
        shared graph edges, so different capabilities can read
        different things from the same screen.
    :ivar compiled_path: Ordered edge ids; empty = plan at run time.
    :ivar policy_scope: What the policy must allow.
    :ivar provenance: How the capability was discovered.
    :ivar stability: Replay track record, once any replay ran.
    """

    schema_version: graph.ACCEPTED_SCHEMA_VERSIONS = SCHEMA_VERSION
    id: str
    name: str
    description: str
    version: int = 1
    status: Literal["draft", "approved"] = "draft"
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
    stability: Optional[Stability] = None
