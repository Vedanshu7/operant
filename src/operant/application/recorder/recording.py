"""
The recorder: node synthesis and edge accumulation during a run.

Each distinct window title becomes a screen node whose check is a title
assertion; actions that do not change the screen are self-edges. The
recorder is pure state - turning it into a ``Recording`` is the
builder's job, and nothing here touches disk.

Import as:

import operant.application.recorder.recording as recdng
"""

from __future__ import annotations

import dataclasses
import re
from typing import Dict, List, Optional, Tuple

import operant.domain.fingerprint as odfinger
import operant.domain.models.artifact as artifact
import operant.domain.models.digest as digest
import operant.domain.models.graph as graph
import operant.domain.models.targets as targets
import operant.helpers.text as text

_DEDUP_COVERAGE = 0.6

NodeBinding = tuple[str, str, str]
"""
A node's surface binding: (vendor_id, app_name, window_title_pattern).
"""


# #############################################################################
# Recording
# #############################################################################


@dataclasses.dataclass
class Recording:
    """
    A pure, IO-free result of a discovery or demonstration run.

    Merged into the app graph and turned into a path-query capability by
    ``operant.application.capabilities.commit_recording``.

    :ivar capability_id: Id the capability will be saved under.
    :ivar capability_name: Human-readable capability name.
    :ivar goal: The natural-language goal that produced the run.
    :ivar vendor_id: Application graph the recording belongs to.
    :ivar app_name: OS application hosting the target.
    :ivar window_title_pattern: Pattern binding the session to the window.
    :ivar tenants: Tenant bindings carried onto the capability.
    :ivar default_tenant: Tenant used when none is given.
    :ivar inputs: Typed task inputs, including promoted sensitive literals.
    :ivar outputs: Typed outputs the capability extracts.
    :ivar nodes: Screen nodes synthesised from window titles.
    :ivar edges: Recorded edges in execution order.
    :ivar outcome_edges: Detectors for exceptional states.
    :ivar entry_node: Node the run started on.
    :ivar goal_node: Node the run ended on.
    :ivar extract_at_node: Node whose screen extraction reads.
    :ivar extract: Capability-scoped extraction specs.
    :ivar policy_scope: Policy id and the action kinds the path needs.
    :ivar provenance: Where the recording came from.
    :ivar node_bindings: Which app each node belongs to; only populated when
        the run crossed apps - segmentation splits on it.
    :ivar promoted: ``(edge id, input name, data class)`` for every sensitive
        literal turned into an input instead of persisted in the graph.
    """

    capability_id: str
    capability_name: str
    goal: str
    vendor_id: str
    app_name: str
    window_title_pattern: str
    tenants: Dict[str, artifact.TenantBinding]
    default_tenant: str
    inputs: Dict[str, artifact.IoField]
    outputs: Dict[str, artifact.OutField]
    nodes: List[graph.Node]
    edges: List[graph.Edge]
    outcome_edges: List[graph.OutcomeEdge]
    entry_node: str
    goal_node: str
    extract_at_node: str
    extract: List[artifact.ExtractSpec]
    policy_scope: artifact.PolicyScope
    provenance: artifact.Provenance
    node_bindings: Dict[str, NodeBinding] = dataclasses.field(
        default_factory=dict
    )
    promoted: List[Tuple[str, str, str]] = dataclasses.field(default_factory=list)


def page_title_pattern(window_title: str) -> str:
    """
    Build a title assertion from the page part of a window title.

    Window titles look like ``<page title> - <browser/app name>``; asserting
    on the page part lets the same artifact work in any host app.
    """
    page = window_title.rsplit(" - ", 1)[0].strip() or window_title
    pattern = re.escape(page)
    return pattern


def region_target(x: float, y: float, description: str) -> targets.Target:
    """
    Build the target for a vision-grounded coordinate click.

    The synthetic ``region`` role matches no digest control, so replay
    falls through to the engine's coordinate fallback instead of ever
    resolving a wrong element.
    """
    target = targets.Target(
        strategies=[
            targets.RegionStrategy(
                role="region",
                x=x - 0.02,
                y=y - 0.02,
                w=0.04,
                h=0.04,
                tolerance=0.05,
            )
        ],
        reasoning=(
            f"vision-grounded click point for {description!r}; the "
            "accessibility inventory lacked the element"
        ),
    )
    return target


def strategies_for(control: digest.Control) -> targets.Target:
    """
    Build the ranked strategy stack for a resolved control.
    """
    strategies: List[targets.TargetStrategy] = []
    why: List[str] = []
    if control.name:
        strategies.append(
            targets.RoleStrategy(role=control.role, name=control.name)
        )
        why.append(
            f'accessible name "{control.name}" is user-facing and survives '
            "restyling"
        )
    if control.label and control.label != control.name:
        strategies.append(
            targets.LabelProximityStrategy(
                anchor_text=control.label, role=control.role
            )
        )
        why.append(
            f'anchored to adjacent text "{control.label}" (legacy layouts)'
        )
    strategies.append(targets.StructuralStrategy(path=control.path))
    why.append("a11y tree path as fallback when semantics are absent")
    strategies.append(
        targets.RegionStrategy(
            role=control.role,
            x=control.box.x,
            y=control.box.y,
            w=control.box.w,
            h=control.box.h,
        )
    )
    why.append("window-relative geometry as last resort")
    target = targets.Target(strategies=strategies, reasoning="; ".join(why))
    return target


# #############################################################################
# RecordedStep
# #############################################################################


@dataclasses.dataclass
class RecordedStep:
    """
    One recorded edge with the context the builder needs.

    :ivar edge: The edge as recorded.
    :ivar from_title: Raw window title before the action.
    :ivar control: The control the action targeted, when resolved.
    """

    edge: graph.Edge
    from_title: str
    control: Optional[digest.Control] = None


# #############################################################################
# Recorder
# #############################################################################


class Recorder:
    """
    Accumulates nodes and edges as a run performs actions.
    """

    def __init__(self) -> None:
        self.recorded: List[RecordedStep] = []
        self.nodes: Dict[str, graph.Node] = {}
        self.extractions: List[artifact.ExtractSpec] = []
        self.extract_node = ""
        self.node_bindings: Dict[str, NodeBinding] = {}
        self._counter = 0
        self._current_node = ""
        self._binding: Optional[NodeBinding] = None

    @property
    def current_node(self) -> str:
        """
        The node the recording currently stands on.
        """
        return self._current_node

    def set_binding(
        self, vendor_id: str, app_name: str, window_title_pattern: str
    ) -> None:
        """
        Set the surface binding for nodes recorded from here on.

        Called by the loop when a launch switches apps - segmentation
        splits on it.
        """
        self._binding = (vendor_id, app_name, window_title_pattern)

    def start(
        self, window_title: str, screen: Optional[digest.ScreenDigest] = None
    ) -> None:
        """
        Mark the entry screen.
        """
        self._current_node = self._node_for(window_title, "entry screen", screen)

    def record(
        self,
        *,
        action: graph.Action,
        target_control: Optional[digest.Control],
        description: str,
        risk: str,
        pre_title: str,
        post_title: str,
        click_point: Optional[Tuple[float, float]] = None,
        screen: Optional[digest.ScreenDigest] = None,
    ) -> None:
        """
        Append one performed action as an edge.

        :param action: The recorded edge action.
        :param target_control: The control it targeted, when resolved.
        :param description: What the action did.
        :param risk:``safe`` or ``mutating``.
        :param pre_title: Window title before the action.
        :param post_title: Window title after the action.
        :param click_point: Window-normalised point for vision clicks.
        :param screen: The post-action digest; its control inventory
            becomes the destination node's content fingerprint.
        """
        self._counter += 1
        same_screen = page_title_pattern(post_title) == page_title_pattern(
            pre_title
        ) and self._same_content(screen)
        to_node = (
            self._current_node
            if same_screen
            else self._node_for(post_title, description, screen)
        )
        if target_control is not None:
            # A resolved control: build its ranked strategy stack.
            target = strategies_for(target_control).model_dump()
        elif click_point is not None:
            # Only a vision click point: target the coordinate region.
            target = region_target(*click_point, description).model_dump()
        else:
            # Neither available: no target; replay falls back to coords.
            target = None
        edge = graph.Edge.model_validate(
            {
                "id": f"edge-{self._counter}",
                "from": self._current_node,
                "to": to_node,
                "description": description,
                "action": action.model_dump(),
                "target": target,
                "wait": graph.Wait(kind="settle", timeout_ms=4000).model_dump(),
                "risk": risk,
            }
        )
        self.recorded.append(
            RecordedStep(edge=edge, from_title=pre_title, control=target_control)
        )
        self._current_node = to_node

    def record_extraction(self, output: str, pattern: str) -> None:
        """
        Add a capability-scoped extraction read on the current screen.

        Extractions belong to this run's goal, not to the edge:
        attaching them to the edge would leak them onto every other
        capability that shares that edge in the app graph (login and
        navigation are shared subgraphs).
        """
        self.extractions.append(
            artifact.ExtractSpec(output=output, pattern=pattern)
        )
        self.extract_node = self._current_node

    def _same_content(self, screen: Optional[digest.ScreenDigest]) -> bool:
        """
        Report whether a screen is the same content as the current node.
        """
        # No digest (or no current fingerprint) -> trust the title alone.
        if screen is None:
            same = True
        else:
            current = self.nodes.get(self._current_node)
            if current is None or not current.fingerprint:
                same = True
            else:
                cover = odfinger.coverage(
                    current.fingerprint, set(odfinger.of(screen))
                )
                same = cover >= _DEDUP_COVERAGE
        return same

    def _node_for(
        self,
        window_title: str,
        description: str,
        screen: Optional[digest.ScreenDigest] = None,
    ) -> str:
        """
        Return the node for a window title, creating it when new.
        """
        pattern = page_title_pattern(window_title)
        fingerprint = odfinger.of(screen) if screen is not None else []
        for node in self.nodes.values():
            check = node.checks[0]
            if not (
                isinstance(check, graph.TitleMatches) and check.pattern == pattern
            ):
                continue
            # Same title: reuse only when the content matches too, so two
            # states that share a title (a logged-out vs logged-in index
            # page) become distinct nodes.
            if (
                not fingerprint
                or not node.fingerprint
                or odfinger.coverage(node.fingerprint, set(fingerprint))
                >= _DEDUP_COVERAGE
            ):
                return node.id
        slug = text.slugify(window_title.rsplit(" - ", 1)[0]) or "screen"
        node_id = slug if slug not in self.nodes else f"{slug}-{len(self.nodes)}"
        self.nodes[node_id] = graph.Node(
            id=node_id,
            description=description,
            checks=[graph.TitleMatches(pattern=pattern)],
            fingerprint=fingerprint,
        )
        if self._binding is not None:
            self.node_bindings[node_id] = self._binding
        return node_id
