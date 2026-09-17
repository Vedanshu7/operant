"""
Typed evidence events.

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

import collections.abc
from typing import Annotated, Any, Dict, Final, List, Literal, Optional, Union

import pydantic

# #############################################################################
# BaseEvent
# #############################################################################


class BaseEvent(pydantic.BaseModel):
    """
    Fields every event carries.

    :ivar type: event name; the discriminator.
    :ivar summary: one-line human summary.
    :ivar seq: stamped by the run log at write time; present when re-
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

    :ivar type: always ``run_meta``.
    :ivar run_id: id of the run.
    :ivar schema_version: event schema version the log was written with.
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

    :ivar type: always ``run_status``.
    :ivar status: the new status.
    """

    type: Literal["run_status"] = "run_status"
    status: str


# #############################################################################
# GatewayAction
# #############################################################################


class GatewayAction(BaseEvent):
    """
    The gateway dispatched an action to a tool.

    :ivar type: always ``gateway_action``.
    :ivar action: action kind.
    :ivar tool: tool that served it.
    :ivar status: dispatch outcome.
    :ivar reason: why the outcome was chosen.
    :ivar verified: whether the effect was verified on screen.
    :ivar target: text describing the target.
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

    :ivar type: always ``gateway_skip``.
    :ivar action: action kind.
    :ivar tool: tool that was skipped.
    :ivar reason: why it was skipped.
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

    :ivar type: always ``gateway_learned``.
    :ivar action: action kind.
    :ivar tool: tool now preferred.
    :ivar signature: action signature the preference keys on.
    :ivar reason: why it was learned.
    """

    type: Literal["gateway_learned"] = "gateway_learned"
    action: str
    tool: str
    signature: str
    reason: str = ""


# What the gateway journals while it dispatches an action.
GatewayEvent = Union[GatewayAction, GatewaySkip, GatewayLearned]
OnGatewayEvent = collections.abc.Callable[[GatewayEvent], None]


# #############################################################################
# PolicyCheck
# #############################################################################


class PolicyCheck(BaseEvent):
    """
    The policy evaluated an action.

    :ivar type: always ``policy_check``.
    :ivar allowed: whether the action may proceed.
    :ivar risk: risk level assigned.
    :ivar reason: why the verdict was reached.
    :ivar action: action kind.
    :ivar target: text describing the target.
    :ivar verdict: verdict name.
    :ivar approval_kind: approval needed, if any.
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

    :ivar type: always ``policy_blocked``.
    :ivar reason: why it was denied.
    """

    type: Literal["policy_blocked"] = "policy_blocked"
    reason: str


# #############################################################################
# ScopeGranted
# #############################################################################


class ScopeGranted(BaseEvent):
    """
    A human widened the policy scope for this run.

    :ivar type: always ``scope_granted``.
    :ivar kind: scope kind (app, domain, ...).
    :ivar pattern: pattern that was granted.
    :ivar value: value that triggered the grant.
    :ivar reason: why it was granted.
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

    :ivar type: always ``scope_denied``.
    :ivar kind: scope kind.
    :ivar value: value that was denied.
    :ivar reason: why it was denied.
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

    :ivar type: always ``approval_requested``.
    :ivar kind: approval kind.
    :ivar question: what the human was asked.
    :ivar fingerprint: stable hash used to remember the answer.
    :ivar step: edge id the request belongs to.
    :ivar details: extra context shown to the human.
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

    :ivar type: always ``approval_resolved``.
    :ivar kind: approval kind.
    :ivar approved: the answer.
    :ivar by: channel that answered.
    :ivar remembered: whether the answer was cached for the run.
    :ivar fingerprint: stable hash of the request.
    :ivar note: free-text note from the answerer.
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

    :ivar type: always ``sensitive_value_classified``.
    :ivar name: input or output name.
    :ivar data_class: assigned class.
    :ivar source: ``declared``, ``detector``, or ``secret_ref``.
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

    :ivar type: always ``sensitive_literal_promoted``.
    :ivar edge: edge whose literal was promoted.
    :ivar param: parameter name it became.
    :ivar data_class: sensitivity class that triggered promotion.
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

    :ivar type: always ``control_transition``.
    :ivar from_state: previous state; serialised as ``from``.
    :ivar to_state: new state; serialised as ``to``.
    :ivar detail: why control moved.
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

    :ivar type: always ``escalation_raised``.
    :ivar edge: edge at which it happened.
    :ivar reason: why a human is needed.
    :ivar screenshot: screenshot file captured at escalation.
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

    :ivar type: always ``escalation_resolved``.
    :ivar resolution: how it was resolved.
    :ivar note: free-text note from the human.
    :ivar human_actions: actions the human reported taking.
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

    :ivar type: always ``surface_error``.
    :ivar error: error text.
    """

    type: Literal["surface_error"] = "surface_error"
    error: str


# #############################################################################
# DiscoveryStarted
# #############################################################################


class DiscoveryStarted(BaseEvent):
    """
    A discovery run began.

    :ivar type: always ``discovery_started``.
    :ivar goal: natural-language goal.
    :ivar inputs: task inputs supplied up front.
    :ivar model: model driving discovery.
    :ivar trace_id: the run's trace in the observability backend.
    """

    type: Literal["discovery_started"] = "discovery_started"
    goal: str
    inputs: Dict[str, str] = {}
    model: str
    trace_id: str = ""


# #############################################################################
# AgentAction
# #############################################################################


class AgentAction(BaseEvent):
    """
    The discovery agent chose an action.

    :ivar type: always ``agent_action``.
    :ivar turn: turn number.
    :ivar action: action kind.
    :ivar intent: the agent's stated intent.
    :ivar target: text describing the target.
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

    :ivar type: always ``input_declared``.
    :ivar name: input name.
    :ivar value: value used during discovery.
    :ivar value_type: declared value type.
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

    :ivar type: always ``clarify``.
    :ivar question: the question asked.
    :ivar answered: whether an answer arrived.
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

    :ivar type: always ``clarification_answered``.
    :ivar question: the question that was asked.
    :ivar answered: whether an answer was given (vs. dismissed).
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

    :ivar type: always ``extraction_recorded``.
    :ivar name: output name.
    :ivar pattern: regex recorded for replay.
    :ivar value: value it matched during discovery.
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

    :ivar type: always ``goal_complete``.
    :ivar outputs: outputs extracted.
    :ivar inputs: inputs declared.
    :ivar turns: turns taken.
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

    :ivar type: always ``agent_gave_up``.
    :ivar reason: why it stopped.
    """

    type: Literal["agent_gave_up"] = "agent_gave_up"
    reason: str


# #############################################################################
# ArtifactSaved
# #############################################################################


class ArtifactSaved(BaseEvent):
    """
    A capability artifact was written.

    :ivar type: always ``artifact_saved``.
    :ivar id: capability id.
    :ivar version: artifact version.
    :ivar graph_version: graph version it pins.
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

    :ivar type: always ``replay_started``.
    :ivar capability: capability id.
    :ivar version: artifact version.
    :ivar graph_version: graph version in use.
    :ivar tenant: tenant name.
    :ivar params: input values (redacted where sensitive).
    :ivar path: compiled edge path, if any.
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

    :ivar type: always ``replay_finished``.
    :ivar status: result status.
    :ivar outputs: outputs extracted, on success.
    """

    type: Literal["replay_finished"] = "replay_finished"
    status: str
    outputs: Optional[Dict[str, str]] = None


# #############################################################################
# NodeArrived
# #############################################################################


class NodeArrived(BaseEvent):
    """
    A replay verifiably reached a node; raw material for ``graph learn``.

    :ivar type: always ``node_arrived``.
    :ivar node: the node reached.
    :ivar vendor_id: the app.
    :ivar graph_version: the graph version the run used.
    :ivar fingerprint: the screen's value-free signatures.
    :ivar url_path: the normalised address, when known.
    """

    type: Literal["node_arrived"] = "node_arrived"
    node: str
    vendor_id: str
    graph_version: int
    fingerprint: List[str]
    url_path: str = ""


# #############################################################################
# ScreenDrifted
# #############################################################################


class ScreenDrifted(BaseEvent):
    """
    A verified arrival no longer looks the way the node was recorded.

    :ivar type: always ``screen_drifted``.
    :ivar node: the node reached.
    :ivar views_lost: ``text`` and/or ``structure``.
    :ivar url_disagrees: the address is not one recorded for the node.
    """

    type: Literal["screen_drifted"] = "screen_drifted"
    node: str
    views_lost: List[str]
    url_disagrees: bool = False


# #############################################################################
# ControlJudged
# #############################################################################


class ControlJudged(BaseEvent):
    """
    The model judge classified a control no policy pattern names.

    :ivar type: always ``control_judged``.
    :ivar role: the control's role.
    :ivar name: the control's name.
    :ivar verdict: ``navigation``, ``commit`` or ``unsure``.
    """

    type: Literal["control_judged"] = "control_judged"
    role: str
    name: str
    verdict: str


# #############################################################################
# Localized
# #############################################################################


class Localized(BaseEvent):
    """
    Located the current screen in the graph.

    Emitted by replay when it localizes after a launch, and by discovery
    when the live screen matches a state already mapped for the app.

    :ivar type: always ``localized``.
    :ivar node: node id matched, if any.
    :ivar window: window title observed.
    :ivar kind: how sure the match is; see ``localize.Localization``.
    """

    type: Literal["localized"] = "localized"
    node: Optional[str] = None
    window: str = ""
    kind: str = ""


# #############################################################################
# ContextCompacted
# #############################################################################


class ContextCompacted(BaseEvent):
    """
    A model call had to send less history than usual to fit its budget.

    :ivar type: always ``context_compacted``.
    :ivar turn: discovery turn the call belongs to.
    :ivar tokens: tokens of the window that was sent.
    :ivar limit: the token budget it had to fit.
    :ivar kept_full_turns: turns sent with their full screen digest.
    :ivar dropped_images: older screenshots left out.
    """

    type: Literal["context_compacted"] = "context_compacted"
    turn: int
    tokens: int
    limit: int
    kept_full_turns: int
    dropped_images: int = 0


# #############################################################################
# PlanProposed
# #############################################################################


class PlanProposed(BaseEvent):
    """
    The planner split the goal into subgoals (multi-agent discovery).

    :ivar type: always ``plan_proposed``.
    :ivar subgoals: ``{id, description, success_criteria}`` per subgoal.
    :ivar credential_names: credentials the plan expects, by name.
    :ivar attempt: 0 for the first plan, then one per replan.
    """

    type: Literal["plan_proposed"] = "plan_proposed"
    subgoals: List[Dict[str, Any]] = []
    credential_names: List[str] = []
    attempt: int = 0


# #############################################################################
# SubgoalStarted
# #############################################################################


class SubgoalStarted(BaseEvent):
    """
    The executor moved on to a subgoal.

    :ivar type: always ``subgoal_started``.
    :ivar subgoal: the subgoal id.
    :ivar description: what the subgoal asks for.
    """

    type: Literal["subgoal_started"] = "subgoal_started"
    subgoal: str
    description: str = ""


# #############################################################################
# VerifierVerdict
# #############################################################################


class VerifierVerdict(BaseEvent):
    """
    A verifier-panel member judged a subgoal.

    :ivar type: always ``verifier_verdict``.
    :ivar subgoal: the subgoal id.
    :ivar passed: whether it judged the subgoal achieved.
    :ivar reason: its one-sentence reason.
    :ivar reviewer: which panel member decided.
    :ivar claim: ``subgoal`` (``subgoal_done``) or ``goal``
        (``goal_complete``).
    :ivar window: the window title the verdict was made on.
    """

    type: Literal["verifier_verdict"] = "verifier_verdict"
    subgoal: str
    passed: bool
    reason: str = ""
    reviewer: str = "verifier"
    claim: str = "subgoal"
    window: str = ""


# #############################################################################
# Replanned
# #############################################################################


class Replanned(BaseEvent):
    """
    The coordinator asked the planner for a new plan.

    :ivar type: always ``replanned``.
    :ivar reason: what triggered it (rejections, give-up, stall).
    :ivar attempt: which replan this is, from 1.
    """

    type: Literal["replanned"] = "replanned"
    reason: str
    attempt: int


# #############################################################################
# CompileReview
# #############################################################################


class CompileReview(BaseEvent):
    """
    An advisory review of the saved recording (never blocks the save).

    :ivar type: always ``compile_review``.
    :ivar target: the edge id, or ``schema`` for the input/output
        review.
    :ivar verdict: ``ok`` or ``concern``.
    :ivar note: the reviewer's note.
    """

    type: Literal["compile_review"] = "compile_review"
    target: str
    verdict: str
    note: str = ""


# #############################################################################
# InjectionSuspected
# #############################################################################


class InjectionSuspected(BaseEvent):
    """
    Screen content addressed the agent or gave it instructions.

    :ivar type: always ``injection_suspected``.
    :ivar snippets: the suspicious text, shortened.
    :ivar window: the window it appeared in.
    """

    type: Literal["injection_suspected"] = "injection_suspected"
    snippets: List[str] = []
    window: str = ""


# #############################################################################
# MemoryRecalled
# #############################################################################


class MemoryRecalled(BaseEvent):
    """
    Cross-run memory was offered to the agents as advisory hints.

    :ivar type: always ``memory_recalled``.
    :ivar plans: past plans recalled for the planner.
    :ivar lessons: lessons recalled for the planner and executor.
    """

    type: Literal["memory_recalled"] = "memory_recalled"
    plans: int = 0
    lessons: int = 0


# #############################################################################
# PathPlanned
# #############################################################################


class PathPlanned(BaseEvent):
    """
    Replay planned a path at run time.

    :ivar type: always ``path_planned``.
    :ivar path: ordered edge ids.
    :ivar start: start node id.
    :ivar goal: goal node id.
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

    :ivar type: always ``path_compiled_cache``.
    :ivar path: ordered edge ids.
    """

    type: Literal["path_compiled_cache"] = "path_compiled_cache"
    path: List[str]


# #############################################################################
# TargetResolved
# #############################################################################


class TargetResolved(BaseEvent):
    """
    A target stack resolved to a control.

    :ivar type: always ``target_resolved``.
    :ivar edge: edge id.
    :ivar strategy: strategy kind that matched.
    :ivar index: position of the strategy in the stack.
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

    :ivar type: always ``action_performed``.
    :ivar edge: edge id.
    :ivar kind: action kind.
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

    :ivar type: always ``outputs_extracted``.
    :ivar node: node they were read at.
    :ivar outputs: values found.
    :ivar missing: output names no pattern matched.
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

    :ivar type: always ``locator_failed``.
    :ivar edge: edge id.
    :ivar tried: strategies attempted.
    :ivar screenshot: screenshot file captured on failure.
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

    :ivar type: always ``node_assert_failed``.
    :ivar edge: edge id.
    :ivar node: node whose checks failed.
    :ivar screenshot: screenshot file captured on failure.
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

    :ivar type: always ``outcome_edge_matched``.
    :ivar edge: edge being replayed.
    :ivar outcome_edge: outcome edge that matched.
    :ivar handle: handler type.
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

    :ivar type: always ``interrupt_fired``.
    :ivar binding: outcome edge id.
    :ivar graph: graph invoked.
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

    :ivar type: always ``invoke_graph``.
    :ivar edge: invoking edge id.
    :ivar graph: graph invoked.
    :ivar binding: app name the session was retargeted to.
    :ivar version: graph version used.
    :ivar target: target node inside the callee.
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

    :ivar type: always ``retarget``.
    :ivar to: application name.
    """

    type: Literal["retarget"] = "retarget"
    to: str


# #############################################################################
# RetargetBack
# #############################################################################


class RetargetBack(BaseEvent):
    """
    The live session returned to the calling application.

    :ivar type: always ``retarget_back``.
    :ivar to: application name.
    """

    type: Literal["retarget_back"] = "retarget_back"
    to: str


# #############################################################################
# RecoveryRelogin
# #############################################################################


class RecoveryRelogin(BaseEvent):
    """
    The reLogin recovery ran.

    :ivar type: always ``recovery_relogin``.
    :ivar edge: edge that triggered it.
    """

    type: Literal["recovery_relogin"] = "recovery_relogin"
    edge: str


# #############################################################################
# FaultInjected
# #############################################################################


class FaultInjected(BaseEvent):
    """
    A test fault was injected into replay.

    :ivar type: always ``fault_injected``.
    :ivar edge: edge the fault applies to.
    :ivar fault: fault name.
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

    :ivar type: always ``screenshot_saved``.
    :ivar file: file name inside the evidence directory.
    :ivar label: what the screenshot shows.
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

    :ivar type: always ``screenshot_failed``.
    :ivar label: what the screenshot would have shown.
    :ivar error: error text.
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

    :ivar type: always ``capture_started``.
    :ivar dir: capture directory.
    :ivar ok: whether capture started.
    :ivar video: whether screen video is recorded.
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

    :ivar type: always ``capture_saved``.
    :ivar dir: capture directory.
    :ivar actions: input actions captured.
    :ivar video: video file, or whether one was produced.
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
    ContextCompacted,
    PlanProposed,
    SubgoalStarted,
    VerifierVerdict,
    Replanned,
    CompileReview,
    MemoryRecalled,
    InjectionSuspected,
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
        ControlJudged,
        NodeArrived,
        ScreenDrifted,
        ContextCompacted,
        PlanProposed,
        SubgoalStarted,
        VerifierVerdict,
        Replanned,
        CompileReview,
        MemoryRecalled,
        InjectionSuspected,
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
