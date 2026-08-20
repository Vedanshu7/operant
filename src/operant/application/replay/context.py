"""
The per-run replay context and its control-flow exception.

``ReplayContext`` carries everything the per-edge loop reads and the few
things it accumulates (extracted outputs, the deadline, which interrupt
bindings have fired). ``Finished`` unwinds the edge loop the moment a
terminal ``ReplayResult`` is decided, so recovery and escalation paths
can end the run from deep in the call stack without threading a return
value back up.

Import as:

import operant.application.replay.context as context
"""

from __future__ import annotations

import collections.abc
import dataclasses
from typing import Dict, List, Literal, Optional, Set

import operant.application.escalation as escal
import operant.application.replay.options as options
import operant.domain.models.artifact as artifact
import operant.domain.models.digest as digest
import operant.domain.models.graph as mggraph
import operant.domain.models.results as results
import operant.domain.redaction as redact
import operant.ports.evidence as evidence
import operant.ports.hitl as hitl
import operant.ports.surface as pssurfac

InvokeGraph = collections.abc.Callable[
    [mggraph.GraphRef, "ReplayContext"], Optional[results.ReplayResult]
]

EscalationResolution = Literal["completed_by_human", "resumed_and_completed"]


# #############################################################################
# ReplayContext
# #############################################################################


@dataclasses.dataclass
class ReplayContext:
    """
    State shared across one capability's per-edge execution.

    :ivar capability: The capability being replayed.
    :ivar graph: The application graph it traverses.
    :ivar surface: The actuation surface bound to the app window.
    :ivar broker: Control broker for human hand-offs.
    :ivar log: Evidence sink for events and screenshots.
    :ivar opts: Timing knobs, inputs, and tenant for this run.
    :ivar base_url: Tenant base URL, trailing slash stripped.
    :ivar secrets: Resolved secret reference values keyed by ref name.
    :ivar approver: Who answers approval questions at the choke point.
    :ivar redactor: Masks sensitive values before they are logged.
    :ivar path: The edges being executed this run.
    :ivar outputs: Outputs extracted so far, keyed by name.
    :ivar output_origins: Where each output came from and how sensitive.
    :ivar extract_digest: Screen captured at ``extract_at_node``, if
        seen.
    :ivar deadline: Monotonic time the run must finish by; pushed
        forward by human wait time so thinking never times a run out.
    :ivar invoke_graph: Cross-domain composition hook injected by the
        traversal layer; returns ``None`` on success or a terminal
        ``ReplayResult`` to bubble.
    :ivar depth: Cross-graph composition depth of this run.
    :ivar fired_bindings: Interrupt binding ids already handled this
        run.
    :ivar intervention_id: Broker id of a resumed intervention, once one
        has been handed back; drives the escalated result.
    :ivar escalation_resolution: How the resumed intervention completed.
    """

    capability: artifact.CapabilityArtifact
    graph: mggraph.AppGraph
    surface: pssurfac.Surface
    broker: escal.ControlBroker
    log: evidence.EvidenceSink
    opts: options.ReplayOptions
    base_url: str
    secrets: Dict[str, str]
    approver: hitl.Approver
    redactor: redact.Redactor
    path: List[mggraph.Edge] = dataclasses.field(default_factory=list)
    outputs: Dict[str, str] = dataclasses.field(default_factory=dict)
    output_origins: Dict[str, options.OutputOrigin] = dataclasses.field(
        default_factory=dict
    )
    extract_digest: Optional[digest.ScreenDigest] = None
    deadline: float = 0.0
    invoke_graph: Optional[InvokeGraph] = None
    depth: int = 0
    fired_bindings: Set[str] = dataclasses.field(default_factory=set)
    intervention_id: Optional[str] = None
    escalation_resolution: Optional[EscalationResolution] = None


# #############################################################################
# Finished
# #############################################################################


class Finished(Exception):  # noqa: N818 - control flow, not an error
    """
    Unwinds the edge loop with a decided terminal result.

    :ivar result: The terminal replay result to return to the caller.
    """

    def __init__(self, result: results.ReplayResult) -> None:
        super().__init__("replay finished")
        self.result = result
