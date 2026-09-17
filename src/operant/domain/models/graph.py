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

import operant.domain.errors as errors
import operant.domain.models.results as results
import operant.domain.models.targets as targets

SCHEMA_VERSION: Final = "2.4"
# 2.0 -> 2.1: extraction moved from Edge.extract (shared, leaked across
# capabilities) to CapabilityArtifact.extract. Old files load fine; the
# removed edge key is ignored by validation.
# 2.1 -> 2.2: io fields carry a `data_class` (sensitivity); additive,
# defaults to "none" on load.
# 2.2 -> 2.3: nodes carry a value-free content fingerprint for
# content-addressed localization; additive, defaults to [] on load.
# 2.3 -> 2.4: nodes carry `url_paths`, edges `retired_in`, an `unknown` risk
# and the judge's verdict. Before
# this, `safe` on a click or key press only meant no pattern matched, so
# those edges load as `unknown`.
ACCEPTED_SCHEMA_VERSIONS = Literal["2.0", "2.1", "2.2", "2.3", "2.4"]


# #############################################################################
# TitleMatches
# #############################################################################


class TitleMatches(pydantic.BaseModel):
    """
    Hold when the window title matches a regex.

    :ivar kind: discriminator, always ``titleMatches``.
    :ivar pattern: regex searched in the window title.
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

    :ivar kind: discriminator, always ``textMatches``.
    :ivar pattern: regex searched in the digest text.
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

    :ivar kind: discriminator, always ``elementVisible``.
    :ivar target: strategies tried in order against the digest.
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

    :ivar type: discriminator, always ``business_outcome``.
    :ivar outcome: outcome name surfaced in the replay result.
    :ivar detail: human-readable detail.
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

    :ivar graph_id: vendor id of the referenced graph.
    :ivar version: graph version to use; ``None`` means latest at run
        time.
    :ivar target_node: node to reach inside the referenced graph
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

    :ivar type: discriminator, always ``recover``.
    :ivar recovery: which recovery to run.
    :ivar max_attempts: how many times to try, 1..3.
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

    :ivar type: discriminator, always ``invoke``.
    :ivar ref: the graph to run.
    :ivar reason: why the composition exists.
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

    :ivar type: discriminator, always ``escalate``.
    :ivar reason: why a human is needed.
    """

    type: Literal["escalate"] = "escalate"
    reason: str


# #############################################################################
# FailHandle
# #############################################################################


class FailHandle(pydantic.BaseModel):
    """
    Stop the run with a classified failure.

    :ivar type: discriminator, always ``fail``.
    :ivar failure_class: closed failure vocabulary entry.
    :ivar message: human-readable detail.
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

    :ivar id: stable node id, unique within the graph.
    :ivar description: what the screen is.
    :ivar checks: what must hold to consider us "here"; at least one.
    :ivar fingerprint: value-free content signatures of the screen used
        for content-addressed localization; empty on pre-2.3 graphs.
    :ivar url_paths: normalised page addresses seen for this screen;
        they can only veto a match, because index pages repeat across
        states.
    """

    id: str
    description: str
    checks: List[Condition] = pydantic.Field(min_length=1)
    fingerprint: List[str] = pydantic.Field(default_factory=list)
    url_paths: List[str] = pydantic.Field(default_factory=list)


# #############################################################################
# Action
# #############################################################################


class Action(pydantic.BaseModel):
    """
    What an edge does on the surface.

    :ivar kind: the action kind.
    :ivar app: application to launch (launch).
    :ivar url: path joined to the tenant base URL (launch).
    :ivar key: key chord (press).
    :ivar value: text to type (fill).
    :ivar option: the option to choose, parameterisable (select).
    :ivar direction: scroll direction (scroll).
    :ivar amount: scroll notches (scroll).
    :ivar graph_ref: cross-domain composition target (invoke).
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

    :ivar kind: ``settle`` (idle), ``element`` (target), or ``window``
        (title).
    :ivar timeout_ms: how long to wait before giving up.
    :ivar target: strategies for the element to appear (element).
    :ivar title_pattern: regex the window title must match (window).
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

    :ivar id: stable edge id, unique within the graph.
    :ivar from_node: source node id; serialised as ``from``.
    :ivar to_node: destination node id; serialised as ``to``.
    :ivar description: what the action does.
    :ivar action: the surface action.
    :ivar target: ranked strategies naming the control, when one is
        needed.
    :ivar wait: what to wait for after acting.
    :ivar risk: ``safe``, ``mutating`` or ``unknown``.
    :ivar judged: the model judge's verdict on an unknown step, when it
        was asked. Advisory, shown when a person reviews the step.
    :ivar retired_in: graph version that retired this edge; routes skip
        it from then on, and older versions keep it.
    """

    model_config = pydantic.ConfigDict(populate_by_name=True)

    id: str
    from_node: str = pydantic.Field(alias="from")
    to_node: str = pydantic.Field(alias="to")
    description: str
    action: Action
    target: Optional[targets.Target] = None
    wait: Wait = Wait()
    risk: Literal["safe", "mutating", "unknown"] = "safe"
    judged: Optional[str] = None
    retired_in: Optional[int] = None


# #############################################################################
# OutcomeEdge
# #############################################################################


class OutcomeEdge(pydantic.BaseModel):
    """
    Conditional edge: when ``when`` holds at node ``at``, handle it.

    :ivar id: stable outcome edge id.
    :ivar at: node id, or ``*`` for capability-global.
    :ivar when: condition that triggers the handler.
    :ivar handle: what to do when it triggers.
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

    :ivar schema_version: on-disk schema version this document uses.
    :ivar vendor_id: application identifier the graph belongs to.
    :ivar graph_version: monotonic version of this graph document.
    :ivar app_name: OS application this graph drives (the surface
        binding). A web app graph drives the browser; a system graph
        drives e.g. System Settings. Cross-domain invoke retargets the
        live session to the callee's binding.
    :ivar window_title_pattern: regex the driven window's title matches.
    :ivar nodes: screen states; at least one.
    :ivar edges: actions between nodes.
    :ivar outcome_edges: detectors encoding the error taxonomy.
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

        :param node_id: id of the node to find.
        :return: the matching node.
        :raises errors.NotFoundError: if no node has that id.
        """
        for n in self.nodes:
            if n.id == node_id:
                return n
        raise errors.NotFoundError(f"Unknown node '{node_id}'")

    def edge(self, edge_id: str) -> Edge:
        """
        Return the edge with the given id.

        :param edge_id: id of the edge to find.
        :return: the matching edge.
        :raises errors.NotFoundError: if no edge has that id.
        """
        for e in self.edges:
            if e.id == edge_id:
                return e
        raise errors.NotFoundError(f"Unknown edge '{edge_id}'")

    def edges_from(self, node_id: str) -> List[Edge]:
        """
        Return every live edge leaving the given node.

        :param node_id: id of the source node.
        :return: edges whose ``from_node`` is ``node_id``, in graph
            order.
        """
        leaving = [
            e
            for e in self.edges
            if e.from_node == node_id and e.retired_in is None
        ]
        return leaving

    @pydantic.model_validator(mode="after")
    def _upgrade_edges(self) -> AppGraph:
        """
        Load pre-2.4 click and key edges as ``unknown``.
        """
        if self.schema_version < "2.4":
            self.edges = [
                (
                    edge.model_copy(update={"risk": "unknown"})
                    if edge.risk == "safe"
                    and edge.action.kind in {"click", "press"}
                    else edge
                )
                for edge in self.edges
            ]
            self.schema_version = SCHEMA_VERSION
        return self
