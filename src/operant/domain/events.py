"""Typed evidence events.

Untyped event dicts let a ``type=`` kwarg silently overwrite the event
name (every ``input_declared`` event in every run was unreadable) and
gave the audit nothing to validate against. One model per event, extras
forbidden, so schema drift fails in tests and the audit can verify old
run logs.

``EVENT_REGISTRY`` maps each ``type`` string to its model;
``event_adapter`` validates a logged line into the right model::

    event = event_adapter.validate_python(json.loads(line))

Import as:

import operant.domain.events as events
"""

from __future__ import annotations

from typing import Annotated, Any, Dict, Final, List, Literal, Optional, Union

import pydantic

# #############################################################################
# BaseEvent
# #############################################################################


class BaseEvent(pydantic.BaseModel):
    """
    Fields every event carries.

    :ivar type: Event name; the discriminator.
    :ivar summary: One-line human summary.
    :ivar seq: Stamped by the run log at write time; present when re-
        validating logged lines.
    :ivar at: ISO timestamp stamped by the run log at write time.
    """

    model_config = pydantic.ConfigDict(extra="forbid", populate_by_name=True)
    type: str
    summary: str = ""
    seq: Optional[int] = None
    at: Optional[str] = None


# #############################################################################
# RunMeta
# #############################################################################


class RunMeta(BaseEvent):
    """
    First line of every run log.

    Its presence tells the audit this log was written through the typed
    schema; logs without it are legacy and are reported, not validated.

    :ivar type: Always ``run_meta``.
    :ivar run_id: Id of the run.
    :ivar schema_version: Event schema version the log was written with.
    """

    type: Literal["run_meta"] = "run_meta"
    run_id: str
    schema_version: str


# #############################################################################
# RunStatusChanged
# #############################################################################


class RunStatusChanged(BaseEvent):
    """
    The run moved to a new lifecycle status.

    :ivar type: Always ``run_status``.
    :ivar status: The new status.
    """

    type: Literal["run_status"] = "run_status"
    status: str


# #############################################################################
# GatewayAction
# #############################################################################


class GatewayAction(BaseEvent):
    """
    The gateway dispatched an action to a tool.

    :ivar type: Always ``gateway_action``.
    :ivar action: Action kind.
    :ivar tool: Tool that served it.
    :ivar status: Dispatch outcome.
    :ivar reason: Why the outcome was chosen.
    :ivar verified: Whether the effect was verified on screen.
    :ivar target: Text describing the target.
    """

    type: Literal["gateway_action"] = "gateway_action"
    action: str
    tool: Optional[str] = None
    status: str = ""
    reason: Optional[str] = None
    verified: bool = False
    target: str = ""


# #############################################################################
# GatewaySkip
# #############################################################################


class GatewaySkip(BaseEvent):
    """
    The gateway skipped a tool for an action.

    :ivar type: Always ``gateway_skip``.
    :ivar action: Action kind.
    :ivar tool: Tool that was skipped.
    :ivar reason: Why it was skipped.
    """

    type: Literal["gateway_skip"] = "gateway_skip"
    action: str
    tool: str
    reason: Optional[str] = None


# #############################################################################
# GatewayLearned
# #############################################################################


class GatewayLearned(BaseEvent):
    """
    The gateway learned a tool preference for an action signature.

    :ivar type: Always ``gateway_learned``.
    :ivar action: Action kind.
    :ivar tool: Tool now preferred.
    :ivar signature: Action signature the preference keys on.
    :ivar reason: Why it was learned.
    """

    type: Literal["gateway_learned"] = "gateway_learned"
    action: str
    tool: str
    signature: str
    reason: str = ""


# #############################################################################
# PolicyCheck
# #############################################################################


class PolicyCheck(BaseEvent):
    """
    The policy evaluated an action.

    :ivar type: Always ``policy_check``.
    :ivar allowed: Whether the action may proceed.
    :ivar risk: Risk level assigned.
    :ivar reason: Why the verdict was reached.
    :ivar action: Action kind.
    :ivar target: Text describing the target.
    :ivar verdict: Verdict name.
    :ivar approval_kind: Approval needed, if any.
    """

    type: Literal["policy_check"] = "policy_check"
    allowed: bool
    risk: str
    reason: str
    action: str
    target: str = ""
    verdict: str = ""
    approval_kind: Optional[str] = None


# #############################################################################
# PolicyBlocked
# #############################################################################


class PolicyBlocked(BaseEvent):
    """
    The policy denied an action outright.

    :ivar type: Always ``policy_blocked``.
    :ivar reason: Why it was denied.
    """

    type: Literal["policy_blocked"] = "policy_blocked"
    reason: str


# #############################################################################
# ScopeGranted
# #############################################################################


class ScopeGranted(BaseEvent):
    """
    A human widened the policy scope for this run.

    :ivar type: Always ``scope_granted``.
    :ivar kind: Scope kind (app, domain, ...).
    :ivar pattern: Pattern that was granted.
    :ivar value: Value that triggered the grant.
    :ivar reason: Why it was granted.
    """

    type: Literal["scope_granted"] = "scope_granted"
    kind: str
    pattern: str
    value: str
    reason: str = ""


# #############################################################################
# ScopeDenied
# #############################################################################


class ScopeDenied(BaseEvent):
    """
    A scope widening was denied.

    No longer emitted (denials are ``approval_resolved`` events);
    registered so logs written before the unified approval channel still
    validate.

    :ivar type: Always ``scope_denied``.
    :ivar kind: Scope kind.
    :ivar value: Value that was denied.
    :ivar reason: Why it was denied.
    """

    type: Literal["scope_denied"] = "scope_denied"
    kind: str
    value: str
    reason: str = ""


# #############################################################################
# ApprovalRequested
# #############################################################################


class ApprovalRequested(BaseEvent):
    """
    A human was asked to approve something.

    :ivar type: Always ``approval_requested``.
    :ivar kind: Approval kind.
    :ivar question: What the human was asked.
    :ivar fingerprint: Stable hash used to remember the answer.
    :ivar step: Edge id the request belongs to.
    :ivar details: Extra context shown to the human.
    """

    type: Literal["approval_requested"] = "approval_requested"
    kind: str
    question: str
    fingerprint: str = ""
    step: Optional[str] = None
    details: Dict[str, str] = {}


# #############################################################################
# ApprovalResolved
# #############################################################################


class ApprovalResolved(BaseEvent):
    """
    An approval request was answered.

    :ivar type: Always ``approval_resolved``.
    :ivar kind: Approval kind.
    :ivar approved: The answer.
    :ivar by: Channel that answered.
    :ivar remembered: Whether the answer was cached for the run.
    :ivar fingerprint: Stable hash of the request.
    :ivar note: Free-text note from the answerer.
    """

    type: Literal["approval_resolved"] = "approval_resolved"
    kind: str
    approved: bool
    by: Literal[
        "tty", "console", "scripted", "cache", "timeout", "denied-by-default"
    ]
    remembered: bool = False
    fingerprint: str = ""
    note: str = ""


# #############################################################################
# SensitiveValueClassified
# #############################################################################


class SensitiveValueClassified(BaseEvent):
    """
    A value was assigned a sensitivity class.

    :ivar type: Always ``sensitive_value_classified``.
    :ivar name: Input or output name.
    :ivar data_class: Assigned class.
    :ivar source:``declared``, ``detector``, or ``secret_ref``.
    """

    type: Literal["sensitive_value_classified"] = "sensitive_value_classified"
    name: str
    data_class: str
    source: str


# #############################################################################
# SensitiveLiteralPromoted
# #############################################################################


class SensitiveLiteralPromoted(BaseEvent):
    """
    A sensitive literal was promoted to a parameter.

    :ivar type: Always ``sensitive_literal_promoted``.
    :ivar edge: Edge whose literal was promoted.
    :ivar param: Parameter name it became.
    :ivar data_class: Sensitivity class that triggered promotion.
    """

    type: Literal["sensitive_literal_promoted"] = "sensitive_literal_promoted"
    edge: str
    param: str
    data_class: str


# #############################################################################
# ControlTransition
# #############################################################################


class ControlTransition(BaseEvent):
    """
    Control moved between the system and a human.

    :ivar type: Always ``control_transition``.
    :ivar from_state: Previous state; serialised as ``from``.
    :ivar to_state: New state; serialised as ``to``.
    :ivar detail: Why control moved.
    """

    type: Literal["control_transition"] = "control_transition"
    from_state: str = pydantic.Field(alias="from")
    to_state: str = pydantic.Field(alias="to")
    detail: str = ""


# #############################################################################
# EscalationRaised
# #############################################################################


class EscalationRaised(BaseEvent):
    """
    The run asked for a human.

    :ivar type: Always ``escalation_raised``.
    :ivar edge: Edge at which it happened.
    :ivar reason: Why a human is needed.
    :ivar screenshot: Screenshot file captured at escalation.
    """

    type: Literal["escalation_raised"] = "escalation_raised"
    edge: Optional[str] = None
    reason: str
    screenshot: str = ""


# #############################################################################
# EscalationResolved
# #############################################################################


class EscalationResolved(BaseEvent):
    """
    A human resolved an escalation.

    :ivar type: Always ``escalation_resolved``.
    :ivar resolution: How it was resolved.
    :ivar note: Free-text note from the human.
    :ivar human_actions: Actions the human reported taking.
    """

    type: Literal["escalation_resolved"] = "escalation_resolved"
    resolution: str
    note: str = ""
    human_actions: List[str] = []


# #############################################################################
# SurfaceError
# #############################################################################


class SurfaceError(BaseEvent):
    """
    The surface failed to observe or act.

    :ivar type: Always ``surface_error``.
    :ivar error: Error text.
    """

    type: Literal["surface_error"] = "surface_error"
    error: str


# #############################################################################
# DiscoveryStarted
# #############################################################################


class DiscoveryStarted(BaseEvent):
    """
    A discovery run began.

    :ivar type: Always ``discovery_started``.
    :ivar goal: Natural-language goal.
    :ivar inputs: Task inputs supplied up front.
    :ivar model: Model driving discovery.
    """

    type: Literal["discovery_started"] = "discovery_started"
    goal: str
    inputs: Dict[str, str] = {}
    model: str


# #############################################################################
# AgentAction
# #############################################################################


class AgentAction(BaseEvent):
    """
    The discovery agent chose an action.

    :ivar type: Always ``agent_action``.
    :ivar turn: Turn number.
    :ivar action: Action kind.
    :ivar intent: The agent's stated intent.
    :ivar target: Text describing the target.
    """

    type: Literal["agent_action"] = "agent_action"
    turn: int
    action: str
    intent: str
    target: Optional[str] = None


# #############################################################################
# InputDeclared
# #############################################################################


class InputDeclared(BaseEvent):
    """
    The agent declared a task input.

    :ivar type: Always ``input_declared``.
    :ivar name: Input name.
    :ivar value: Value used during discovery.
    :ivar value_type: Declared value type.
    """

    type: Literal["input_declared"] = "input_declared"
    name: str
    value: str
    value_type: str = "string"


# #############################################################################
# Clarify
# #############################################################################


class Clarify(BaseEvent):
    """
    The agent asked the operator a question.

    :ivar type: Always ``clarify``.
    :ivar question: The question asked.
    :ivar answered: Whether an answer arrived.
    """

    type: Literal["clarify"] = "clarify"
    question: str
    answered: bool


# #############################################################################
# ClarificationAnswered
# #############################################################################


class ClarificationAnswered(BaseEvent):
    """
    The operator responded to a clarifying question.

    :ivar type: Always ``clarification_answered``.
    :ivar question: The question that was asked.
    :ivar answered: Whether an answer was given (vs. dismissed).
    """

    type: Literal["clarification_answered"] = "clarification_answered"
    question: str
    answered: bool


# #############################################################################
# ExtractionRecorded
# #############################################################################


class ExtractionRecorded(BaseEvent):
    """
    The agent recorded an output extraction.

    :ivar type: Always ``extraction_recorded``.
    :ivar name: Output name.
    :ivar pattern: Regex recorded for replay.
    :ivar value: Value it matched during discovery.
    """

    type: Literal["extraction_recorded"] = "extraction_recorded"
    name: str
    pattern: str
    value: str


# #############################################################################
# GoalComplete
# #############################################################################


class GoalComplete(BaseEvent):
    """
    The agent declared the goal reached.

    :ivar type: Always ``goal_complete``.
    :ivar outputs: Outputs extracted.
    :ivar inputs: Inputs declared.
    :ivar turns: Turns taken.
    """

    type: Literal["goal_complete"] = "goal_complete"
    outputs: Dict[str, str] = {}
    inputs: Dict[str, str] = {}
    turns: int


# #############################################################################
# AgentGaveUp
# #############################################################################


class AgentGaveUp(BaseEvent):
    """
    The agent stopped without reaching the goal.

    :ivar type: Always ``agent_gave_up``.
    :ivar reason: Why it stopped.
    """

    type: Literal["agent_gave_up"] = "agent_gave_up"
    reason: str


# #############################################################################
# ArtifactSaved
# #############################################################################


class ArtifactSaved(BaseEvent):
    """
    A capability artifact was written.

    :ivar type: Always ``artifact_saved``.
    :ivar id: Capability id.
    :ivar version: Artifact version.
    :ivar graph_version: Graph version it pins.
    """

    type: Literal["artifact_saved"] = "artifact_saved"
    id: str
    version: int
    graph_version: int


# #############################################################################
# ReplayStarted
# #############################################################################


class ReplayStarted(BaseEvent):
    """
    A replay began.

    :ivar type: Always ``replay_started``.
    :ivar capability: Capability id.
    :ivar version: Artifact version.
    :ivar graph_version: Graph version in use.
    :ivar tenant: Tenant name.
    :ivar params: Input values (redacted where sensitive).
    :ivar path: Compiled edge path, if any.
    """

    type: Literal["replay_started"] = "replay_started"
    capability: str
    version: int
    graph_version: int
    tenant: str
    params: Dict[str, str] = {}
    path: List[str] = []


# #############################################################################
# ReplayFinished
# #############################################################################


class ReplayFinished(BaseEvent):
    """
    A replay ended.

    :ivar type: Always ``replay_finished``.
    :ivar status: Result status.
    :ivar outputs: Outputs extracted, on success.
    """

    type: Literal["replay_finished"] = "replay_finished"
    status: str
    outputs: Optional[Dict[str, str]] = None


# #############################################################################
# Localized
# #############################################################################


class Localized(BaseEvent):
    """
    Located the current screen in the graph.

    Emitted by replay when it localizes after a launch, and by discovery
    when the live screen matches a state already mapped for the app.

    :ivar type: Always ``localized``.
    :ivar node: Node id matched, if any.
    :ivar window: Window title observed.
    """

    type: Literal["localized"] = "localized"
    node: Optional[str] = None
    window: str = ""


# #############################################################################
# PathPlanned
# #############################################################################


class PathPlanned(BaseEvent):
    """
    Replay planned a path at run time.

    :ivar type: Always ``path_planned``.
    :ivar path: Ordered edge ids.
    :ivar start: Start node id.
    :ivar goal: Goal node id.
    """

    type: Literal["path_planned"] = "path_planned"
    path: List[str]
    start: str
    goal: str


# #############################################################################
# PathCompiledCache
# #############################################################################


class PathCompiledCache(BaseEvent):
    """
    Replay used the compiled path from the artifact.

    :ivar type: Always ``path_compiled_cache``.
    :ivar path: Ordered edge ids.
    """

    type: Literal["path_compiled_cache"] = "path_compiled_cache"
    path: List[str]


# #############################################################################
# TargetResolved
# #############################################################################


class TargetResolved(BaseEvent):
    """
    A target stack resolved to a control.

    :ivar type: Always ``target_resolved``.
    :ivar edge: Edge id.
    :ivar strategy: Strategy kind that matched.
    :ivar index: Position of the strategy in the stack.
    """

    type: Literal["target_resolved"] = "target_resolved"
    edge: str
    strategy: str
    index: int


# #############################################################################
# ActionPerformed
# #############################################################################


class ActionPerformed(BaseEvent):
    """
    An edge's action ran on the surface.

    :ivar type: Always ``action_performed``.
    :ivar edge: Edge id.
    :ivar kind: Action kind.
    """

    type: Literal["action_performed"] = "action_performed"
    edge: str
    kind: str


# #############################################################################
# OutputsExtracted
# #############################################################################


class OutputsExtracted(BaseEvent):
    """
    Declared outputs were read from the screen.

    :ivar type: Always ``outputs_extracted``.
    :ivar node: Node they were read at.
    :ivar outputs: Values found.
    :ivar missing: Output names no pattern matched.
    """

    type: Literal["outputs_extracted"] = "outputs_extracted"
    node: str
    outputs: Dict[str, str] = {}
    missing: List[str] = []


# #############################################################################
# LocatorFailed
# #############################################################################


class LocatorFailed(BaseEvent):
    """
    No strategy in a target stack resolved.

    :ivar type: Always ``locator_failed``.
    :ivar edge: Edge id.
    :ivar tried: Strategies attempted.
    :ivar screenshot: Screenshot file captured on failure.
    """

    type: Literal["locator_failed"] = "locator_failed"
    edge: str
    tried: List[Any] = []
    screenshot: str = ""


# #############################################################################
# NodeAssertFailed
# #############################################################################


class NodeAssertFailed(BaseEvent):
    """
    The destination node's checks did not hold after an edge.

    :ivar type: Always ``node_assert_failed``.
    :ivar edge: Edge id.
    :ivar node: Node whose checks failed.
    :ivar screenshot: Screenshot file captured on failure.
    """

    type: Literal["node_assert_failed"] = "node_assert_failed"
    edge: str
    node: str
    screenshot: str = ""


# #############################################################################
# OutcomeEdgeMatched
# #############################################################################


class OutcomeEdgeMatched(BaseEvent):
    """
    An outcome edge's condition held.

    :ivar type: Always ``outcome_edge_matched``.
    :ivar edge: Edge being replayed.
    :ivar outcome_edge: Outcome edge that matched.
    :ivar handle: Handler type.
    """

    type: Literal["outcome_edge_matched"] = "outcome_edge_matched"
    edge: str
    outcome_edge: str
    handle: str


# #############################################################################
# InterruptFired
# #############################################################################


class InterruptFired(BaseEvent):
    """
    A binding edge triggered cross-graph composition.

    :ivar type: Always ``interrupt_fired``.
    :ivar binding: Outcome edge id.
    :ivar graph: Graph invoked.
    """

    type: Literal["interrupt_fired"] = "interrupt_fired"
    binding: str
    graph: str


# #############################################################################
# InvokeGraph
# #############################################################################


class InvokeGraph(BaseEvent):
    """
    Replay invoked another application graph.

    :ivar type: Always ``invoke_graph``.
    :ivar edge: Invoking edge id.
    :ivar graph: Graph invoked.
    :ivar binding: App name the session was retargeted to.
    :ivar version: Graph version used.
    :ivar target: Target node inside the callee.
    """

    type: Literal["invoke_graph"] = "invoke_graph"
    edge: str
    graph: str
    binding: Optional[str] = None
    version: Optional[int] = None
    target: Optional[str] = None


# #############################################################################
# Retarget
# #############################################################################


class Retarget(BaseEvent):
    """
    The live session was retargeted to another application.

    :ivar type: Always ``retarget``.
    :ivar to: Application name.
    """

    type: Literal["retarget"] = "retarget"
    to: str


# #############################################################################
# RetargetBack
# #############################################################################


class RetargetBack(BaseEvent):
    """
    The live session returned to the calling application.

    :ivar type: Always ``retarget_back``.
    :ivar to: Application name.
    """

    type: Literal["retarget_back"] = "retarget_back"
    to: str


# #############################################################################
# RecoveryRelogin
# #############################################################################


class RecoveryRelogin(BaseEvent):
    """
    The reLogin recovery ran.

    :ivar type: Always ``recovery_relogin``.
    :ivar edge: Edge that triggered it.
    """

    type: Literal["recovery_relogin"] = "recovery_relogin"
    edge: str


# #############################################################################
# FaultInjected
# #############################################################################


class FaultInjected(BaseEvent):
    """
    A test fault was injected into replay.

    :ivar type: Always ``fault_injected``.
    :ivar edge: Edge the fault applies to.
    :ivar fault: Fault name.
    """

    type: Literal["fault_injected"] = "fault_injected"
    edge: str
    fault: str


# #############################################################################
# ScreenshotSaved
# #############################################################################


class ScreenshotSaved(BaseEvent):
    """
    A screenshot was written to evidence.

    :ivar type: Always ``screenshot_saved``.
    :ivar file: File name inside the evidence directory.
    :ivar label: What the screenshot shows.
    """

    type: Literal["screenshot_saved"] = "screenshot_saved"
    file: str
    label: str


# #############################################################################
# ScreenshotFailed
# #############################################################################


class ScreenshotFailed(BaseEvent):
    """
    A screenshot could not be taken.

    :ivar type: Always ``screenshot_failed``.
    :ivar label: What the screenshot would have shown.
    :ivar error: Error text.
    """

    type: Literal["screenshot_failed"] = "screenshot_failed"
    label: str
    error: str


# #############################################################################
# CaptureStarted
# #############################################################################


class CaptureStarted(BaseEvent):
    """
    Full UI-activity capture started.

    :ivar type: Always ``capture_started``.
    :ivar dir: Capture directory.
    :ivar ok: Whether capture started.
    :ivar video: Whether screen video is recorded.
    """

    type: Literal["capture_started"] = "capture_started"
    dir: str
    ok: bool
    video: bool = True


# #############################################################################
# CaptureSaved
# #############################################################################


class CaptureSaved(BaseEvent):
    """
    Full UI-activity capture finished.

    :ivar type: Always ``capture_saved``.
    :ivar dir: Capture directory.
    :ivar actions: Input actions captured.
    :ivar video: Video file, or whether one was produced.
    """

    type: Literal["capture_saved"] = "capture_saved"
    dir: Optional[str] = None
    actions: Optional[int] = None
    video: Optional[Union[str, bool]] = None


_EVENT_MODELS: Final[List[type[BaseEvent]]] = [
    RunMeta,
    RunStatusChanged,
    GatewayAction,
    GatewaySkip,
    GatewayLearned,
    PolicyCheck,
    PolicyBlocked,
    ScopeGranted,
    ScopeDenied,
    ApprovalRequested,
    ApprovalResolved,
    SensitiveValueClassified,
    SensitiveLiteralPromoted,
    ControlTransition,
    EscalationRaised,
    EscalationResolved,
    SurfaceError,
    DiscoveryStarted,
    AgentAction,
    InputDeclared,
    Clarify,
    ClarificationAnswered,
    ExtractionRecorded,
    GoalComplete,
    AgentGaveUp,
    ArtifactSaved,
    ReplayStarted,
    ReplayFinished,
    Localized,
    PathPlanned,
    PathCompiledCache,
    TargetResolved,
    ActionPerformed,
    OutputsExtracted,
    LocatorFailed,
    NodeAssertFailed,
    OutcomeEdgeMatched,
    InterruptFired,
    InvokeGraph,
    Retarget,
    RetargetBack,
    RecoveryRelogin,
    FaultInjected,
    ScreenshotSaved,
    ScreenshotFailed,
    CaptureStarted,
    CaptureSaved,
]

EVENT_REGISTRY: Final[Dict[str, type[BaseEvent]]] = {
    m.model_fields["type"].default: m for m in _EVENT_MODELS
}

EventUnion = Annotated[
    Union[
        RunMeta,
        RunStatusChanged,
        GatewayAction,
        GatewaySkip,
        GatewayLearned,
        PolicyCheck,
        PolicyBlocked,
        ScopeGranted,
        ScopeDenied,
        ApprovalRequested,
        ApprovalResolved,
        SensitiveValueClassified,
        SensitiveLiteralPromoted,
        ControlTransition,
        EscalationRaised,
        EscalationResolved,
        SurfaceError,
        DiscoveryStarted,
        AgentAction,
        InputDeclared,
        Clarify,
        ClarificationAnswered,
        ExtractionRecorded,
        GoalComplete,
        AgentGaveUp,
        ArtifactSaved,
        ReplayStarted,
        ReplayFinished,
        Localized,
        PathPlanned,
        PathCompiledCache,
        TargetResolved,
        ActionPerformed,
        OutputsExtracted,
        LocatorFailed,
        NodeAssertFailed,
        OutcomeEdgeMatched,
        InterruptFired,
        InvokeGraph,
        Retarget,
        RetargetBack,
        RecoveryRelogin,
        FaultInjected,
        ScreenshotSaved,
        ScreenshotFailed,
        CaptureStarted,
        CaptureSaved,
    ],
    pydantic.Field(discriminator="type"),
]

event_adapter: Final[pydantic.TypeAdapter[BaseEvent]] = pydantic.TypeAdapter(
    EventUnion
)
