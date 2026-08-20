"""
The versioned application graph: the substrate capabilities query.

One graph per application, versioned on disk as ``graphs/<vendor>/
v<N>.json``. Nodes are screen states with assertions, edges are actions
with ranked target-descriptor stacks, and outcome edges encode the error
taxonomy (business outcome / recover / escalate / fail / invoke). The
graph is the union of every recorded flow, deduped by node identity, so
shared subgraphs (login, navigation) are recorded once and reused by
every capability that traverses them.

Import as:

import operant.domain.models.graph as graph
"""

from __future__ import annotations

from typing import Annotated, Final, List, Literal, Optional, Union

import pydantic

import operant.domain.models.results as results
import operant.domain.models.targets as targets

SCHEMA_VERSION: Final = "2.3"
# 2.0 -> 2.1: extraction moved from Edge.extract (shared, leaked across
# capabilities) to CapabilityArtifact.extract. Old files load fine; the
# removed edge key is ignored by validation.
# 2.1 -> 2.2: io fields carry a data_class (sensitivity); additive,
# defaults to "none" on load.
# 2.2 -> 2.3: nodes carry a value-free content fingerprint for
# content-addressed localization; additive, defaults to [] on load.
ACCEPTED_SCHEMA_VERSIONS = Literal["2.0", "2.1", "2.2", "2.3"]


# #############################################################################
# TitleMatches
# #############################################################################


class TitleMatches(pydantic.BaseModel):
    """
    Hold when the window title matches a regex.

    :ivar kind: Discriminator, always ``titleMatches``.
    :ivar pattern: Regex searched in the window title.
    """

    kind: Literal["titleMatches"] = "titleMatches"
    pattern: str
    negate: bool = False


# #############################################################################
# TextMatches
# #############################################################################


class TextMatches(pydantic.BaseModel):
    """
    Hold when the visible text matches a regex.

    :ivar kind: Discriminator, always ``textMatches``.
    :ivar pattern: Regex searched in the digest text.
    """

    kind: Literal["textMatches"] = "textMatches"
    pattern: str
    negate: bool = False


# #############################################################################
# ElementVisible
# #############################################################################


class ElementVisible(pydantic.BaseModel):
    """
    Hold when a target stack resolves to a control.

    :ivar kind: Discriminator, always ``elementVisible``.
    :ivar target: Strategies tried in order against the digest.
    """

    kind: Literal["elementVisible"] = "elementVisible"
    target: List[targets.TargetStrategy]
    negate: bool = False


Condition = Annotated[
    Union[TitleMatches, TextMatches, ElementVisible],
    pydantic.Field(discriminator="kind"),
]


# #############################################################################
# BusinessOutcomeHandle
# #############################################################################


class BusinessOutcomeHandle(pydantic.BaseModel):
    """
    End the run with an outcome the application reported.

    :ivar type: Discriminator, always ``business_outcome``.
    :ivar outcome: Outcome name surfaced in the replay result.
    :ivar detail: Human-readable detail.
    """

    type: Literal["business_outcome"] = "business_outcome"
    outcome: str
    detail: str = ""


# #############################################################################
# GraphRef
# #############################################################################


class GraphRef(pydantic.BaseModel):
    """
    A cross-domain reference to another application graph.

    :ivar graph_id: Vendor id of the referenced graph.
    :ivar version: Graph version to use; ``None`` means latest at run
        time.
    :ivar target_node: Node to reach inside the referenced graph
        (default: its goal).
    """

    graph_id: str
    version: Optional[int] = None
    target_node: Optional[str] = None


# #############################################################################
# RecoverHandle
# #############################################################################


class RecoverHandle(pydantic.BaseModel):
    """
    Run a built-in recovery and retry.

    :ivar type: Discriminator, always ``recover``.
    :ivar recovery: Which recovery to run.
    :ivar max_attempts: How many times to try, 1..3.
    """

    type: Literal["recover"] = "recover"
    recovery: Literal["dismissDialog", "retryEdge", "reLogin"]
    max_attempts: int = pydantic.Field(default=1, ge=1, le=3)


# #############################################################################
# InvokeGraphHandle
# #############################################################################


class InvokeGraphHandle(pydantic.BaseModel):
    """
    Conditional (interrupt) composition.

    When the trigger holds, run another application graph, then resume
    the caller. This is the binding-edge handler.

    :ivar type: Discriminator, always ``invoke``.
    :ivar ref: The graph to run.
    :ivar reason: Why the composition exists.
    """

    type: Literal["invoke"] = "invoke"
    ref: GraphRef
    reason: str = ""


# #############################################################################
# EscalateHandle
# #############################################################################


class EscalateHandle(pydantic.BaseModel):
    """
    Hand control to a human.

    :ivar type: Discriminator, always ``escalate``.
    :ivar reason: Why a human is needed.
    """

    type: Literal["escalate"] = "escalate"
    reason: str


# #############################################################################
# FailHandle
# #############################################################################


class FailHandle(pydantic.BaseModel):
    """
    Stop the run with a classified failure.

    :ivar type: Discriminator, always ``fail``.
    :ivar failure_class: Closed failure vocabulary entry.
    :ivar message: Human-readable detail.
    """

    type: Literal["fail"] = "fail"
    failure_class: results.FailureClass
    message: str = ""


DetectorHandle = Annotated[
    Union[
        BusinessOutcomeHandle,
        RecoverHandle,
        EscalateHandle,
        FailHandle,
        InvokeGraphHandle,
    ],
    pydantic.Field(discriminator="type"),
]


# #############################################################################
# Node
# #############################################################################


class Node(pydantic.BaseModel):
    """
    A screen state.

    :ivar id: Stable node id, unique within the graph.
    :ivar description: What the screen is.
    :ivar checks: What must hold to consider us "here"; at least one.
    :ivar fingerprint: Value-free content signatures of the screen used
        for content-addressed localization; empty on pre-2.3 graphs.
    """

    id: str
    description: str
    checks: List[Condition] = pydantic.Field(min_length=1)
    fingerprint: List[str] = pydantic.Field(default_factory=list)


# #############################################################################
# Action
# #############################################################################


class Action(pydantic.BaseModel):
    """
    What an edge does on the surface.

    :ivar kind: The action kind.
    :ivar app: Application to launch (launch).
    :ivar url: Path joined to the tenant base URL (launch).
    :ivar key: Key chord (press).
    :ivar value: Text to type (fill).
    :ivar option: The option to choose, parameterisable (select).
    :ivar direction: Scroll direction (scroll).
    :ivar amount: Scroll notches (scroll).
    :ivar graph_ref: Cross-domain composition target (invoke).
    """

    kind: Literal[
        "launch", "click", "fill", "press", "select", "scroll", "invoke"
    ]
    app: Optional[str] = None
    url: Optional[str] = None
    key: Optional[str] = None
    value: Optional[targets.Value] = None
    option: Optional[targets.Value] = None
    direction: Optional[Literal["up", "down"]] = None
    amount: Optional[int] = None
    graph_ref: Optional[GraphRef] = None


# #############################################################################
# Wait
# #############################################################################


class Wait(pydantic.BaseModel):
    """
    What to wait for after an edge's action.

    :ivar kind:``settle`` (idle), ``element`` (target), or ``window``
        (title).
    :ivar timeout_ms: How long to wait before giving up.
    :ivar target: Strategies for the element to appear (element).
    :ivar title_pattern: Regex the window title must match (window).
    """

    kind: Literal["settle", "element", "window"] = "settle"
    timeout_ms: int = 3000
    target: Optional[List[targets.TargetStrategy]] = None
    title_pattern: Optional[str] = None


# #############################################################################
# Edge
# #############################################################################


class Edge(pydantic.BaseModel):
    """
    One recorded action: from one screen node to another.

    :ivar id: Stable edge id, unique within the graph.
    :ivar from_node: Source node id; serialised as ``from``.
    :ivar to_node: Destination node id; serialised as ``to``.
    :ivar description: What the action does.
    :ivar action: The surface action.
    :ivar target: Ranked strategies naming the control, when one is
        needed.
    :ivar wait: What to wait for after acting.
    :ivar risk:``safe`` or ``mutating``; drives policy and approval.
    """

    model_config = pydantic.ConfigDict(populate_by_name=True)

    id: str
    from_node: str = pydantic.Field(alias="from")
    to_node: str = pydantic.Field(alias="to")
    description: str
    action: Action
    target: Optional[targets.Target] = None
    wait: Wait = Wait()
    risk: Literal["safe", "mutating"] = "safe"


# #############################################################################
# OutcomeEdge
# #############################################################################


class OutcomeEdge(pydantic.BaseModel):
    """
    Conditional edge: when ``when`` holds at node ``at``, handle it.

    :ivar id: Stable outcome edge id.
    :ivar at: Node id, or ``*`` for capability-global.
    :ivar when: Condition that triggers the handler.
    :ivar handle: What to do when it triggers.
    """

    id: str
    at: str
    when: Condition
    handle: DetectorHandle


# #############################################################################
# AppGraph
# #############################################################################


class AppGraph(pydantic.BaseModel):
    """
    One application's graph, versioned.

    ``from``/``to`` on edges make this a real graph; it may contain
    cycles.

    :ivar schema_version: On-disk schema version this document uses.
    :ivar vendor_id: Application identifier the graph belongs to.
    :ivar graph_version: Monotonic version of this graph document.
    :ivar app_name: OS application this graph drives (the surface
        binding). A web app graph drives the browser; a system graph
        drives e.g. System Settings. Cross-domain invoke retargets the
        live session to the callee's binding.
    :ivar window_title_pattern: Regex the driven window's title matches.
    :ivar nodes: Screen states; at least one.
    :ivar edges: Actions between nodes.
    :ivar outcome_edges: Detectors encoding the error taxonomy.
    :ivar created_at: ISO timestamp of first save.
    :ivar updated_at: ISO timestamp of last save.
    """

    schema_version: ACCEPTED_SCHEMA_VERSIONS = SCHEMA_VERSION
    vendor_id: str
    graph_version: int = 1
    app_name: str = ""
    window_title_pattern: str = ""
    nodes: List[Node] = pydantic.Field(min_length=1)
    edges: List[Edge] = []
    outcome_edges: List[OutcomeEdge] = []
    created_at: str = ""
    updated_at: str = ""

    def node(self, node_id: str) -> Node:
        """
        Return the node with the given id.

        :param node_id: Id of the node to find.
        :return: The matching node.
        :raises KeyError: If no node has that id.
        """
        for n in self.nodes:
            if n.id == node_id:
                return n
        raise KeyError(f"unknown node {node_id!r}")

    def edge(self, edge_id: str) -> Edge:
        """
        Return the edge with the given id.

        :param edge_id: Id of the edge to find.
        :return: The matching edge.
        :raises KeyError: If no edge has that id.
        """
        for e in self.edges:
            if e.id == edge_id:
                return e
        raise KeyError(f"unknown edge {edge_id!r}")

    def edges_from(self, node_id: str) -> List[Edge]:
        """
        Return every edge leaving the given node.

        :param node_id: Id of the source node.
        :return: Edges whose ``from_node`` is ``node_id``, in graph
            order.
        """
        leaving = [e for e in self.edges if e.from_node == node_id]
        return leaving
