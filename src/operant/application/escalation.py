"""
Control-transfer model: exactly one party controls the session at a time.

agent --(intervention raised)--> paused --(operator takes over)--> human
human --(hand back)--> resuming --(state re-verified by engine)--> agent
human --(mark unrecoverable)--> agent (run ends as escalated/abandoned)

While the state is not ``agent`` the automation is blocked on the
resolution event, so it is structurally incapable of acting. A separate,
non-transferring slot carries approve/deny questions: the agent keeps
control and only waits on permission.

Capture start/stop is invoked outside the lock, so a slow capture never
blocks a concurrent approval.

Import as:

import operant.application.escalation as escal
"""

from __future__ import annotations

import collections.abc
import dataclasses
import threading
from typing import List, Literal, Optional

import operant.domain.approval as approval
import operant.domain.errors as errors
import operant.helpers.time as time

ControlState = Literal["agent", "paused", "human", "resuming"]


# #############################################################################
# InterventionRequest
# #############################################################################


@dataclasses.dataclass
class InterventionRequest:
    """
    A request for a human to take over the live session.

    :ivar run_id: Run that raised the request.
    :ivar kind:``discovery`` or ``replay``.
    :ivar capability: Capability id or goal name.
    :ivar goal: What the run is trying to achieve.
    :ivar reason: Why a human is needed.
    :ivar page_title: Window title when raised.
    :ivar edge_id: Edge the run was on, when replaying.
    :ivar screenshot_file: Evidence screenshot at escalation.
    :ivar id: Broker-assigned id (``iv-<n>``); empty until raised.
    :ivar raised_at: ISO timestamp the request was raised.
    """

    run_id: str
    kind: str
    capability: str
    goal: str
    reason: str
    page_title: str = ""
    edge_id: Optional[str] = None
    screenshot_file: Optional[str] = None
    id: str = ""
    raised_at: str = ""


# #############################################################################
# InterventionResolution
# #############################################################################


@dataclasses.dataclass
class InterventionResolution:
    """
    How an intervention ended.

    :ivar resolution:``resumed`` (hand back) or ``abandoned``.
    :ivar note: Operator remark.
    :ivar human_actions: Actions the human took while in control.
    """

    resolution: Literal["resumed", "abandoned"]
    note: str
    human_actions: List[str] = dataclasses.field(default_factory=list)


# #############################################################################
# PendingApproval
# #############################################################################


@dataclasses.dataclass
class PendingApproval:
    """
    An approve/deny question with no control transfer.

    :ivar id: Broker-assigned id (``approval-<n>``).
    :ivar run_id: Run that raised the question.
    :ivar request: The question put to the human.
    :ivar raised_at: ISO timestamp the question was raised.
    """

    id: str
    run_id: str
    request: approval.ApprovalRequest
    raised_at: str = ""


# #############################################################################
# ControlBroker
# #############################################################################


class ControlBroker:
    """
    Serialise control between the automation and a human operator.
    """

    def __init__(
        self,
        *,
        start_human_capture: collections.abc.Callable[
            [collections.abc.Callable[[str], None]], None
        ],
        stop_human_capture: collections.abc.Callable[[], None],
        on_transition: collections.abc.Callable[
            [ControlState, ControlState, str], None
        ],
    ) -> None:
        self._start_capture = start_human_capture
        self._stop_capture = stop_human_capture
        self._on_transition = on_transition
        self._state: ControlState = "agent"
        self._seq = 0
        self._pending: Optional[InterventionRequest] = None
        self._resolution: Optional[InterventionResolution] = None
        self._human_actions: List[str] = []
        self._resolved = threading.Event()
        self._lock = threading.Lock()
        self.listeners: List[collections.abc.Callable[[], None]] = []
        self._approval: Optional[PendingApproval] = None
        self._approval_decision: Optional[approval.ApprovalDecision] = None
        self._approval_done = threading.Event()

    @property
    def state(self) -> ControlState:
        """
        The current control state.
        """
        return self._state

    @property
    def pending(self) -> Optional[InterventionRequest]:
        """
        The pending intervention, if any.
        """
        return self._pending

    @property
    def pending_approval(self) -> Optional[PendingApproval]:
        """
        The pending approval question, if any.
        """
        return self._approval

    @property
    def human_actions_so_far(self) -> List[str]:
        """
        A copy of the actions the human has taken this intervention.
        """
        actions = list(self._human_actions)
        return actions

    def raise_intervention(
        self, request: InterventionRequest
    ) -> InterventionResolution:
        """
        Pause the automation and blocks until an operator resolves it.
        """
        with self._lock:
            if self._state != "agent":
                raise errors.InvalidTransitionError(
                    f'cannot raise intervention in state "{self._state}"'
                )
            self._seq += 1
            request.id = f"iv-{self._seq}"
            request.raised_at = time.iso_now()
            self._pending = request
            self._human_actions = []
            self._resolution = None
            self._resolved.clear()
            self._transition(
                "paused", f"intervention {request.id} raised: {request.reason}"
            )
        self._resolved.wait()
        resolution: Optional[InterventionResolution] = self._resolution
        if resolution is None:
            raise errors.InvalidTransitionError(
                "intervention resolved without a resolution"
            )
        return resolution

    def take_control(self, intervention_id: str) -> None:
        """
        Transfer control to the operator and starts action capture.
        """
        with self._lock:
            self._require_pending(intervention_id, "paused")
            self._transition(
                "human", f"operator took control for {intervention_id}"
            )
        self._start_capture(self._human_actions.append)

    def hand_back(self, intervention_id: str, note: str) -> None:
        """
        Return control to the automation, keeping the captured actions.
        """
        with self._lock:
            self._require_pending(intervention_id, "human")
        self._stop_capture()
        with self._lock:
            self._pending = None
            self._resolution = InterventionResolution(
                "resumed", note, list(self._human_actions)
            )
            self._transition(
                "resuming",
                f"operator handed control back for {intervention_id}",
            )
            self._resolved.set()

    def abandon(self, intervention_id: str, note: str) -> None:
        """
        End the run: control returns to the agent as ``abandoned``.
        """
        with self._lock:
            self._require_pending(intervention_id, None)
            was_human = self._state == "human"
        if was_human:
            self._stop_capture()
        with self._lock:
            self._pending = None
            self._resolution = InterventionResolution(
                "abandoned", note, list(self._human_actions)
            )
            self._transition("agent", f"operator abandoned {intervention_id}")
            self._resolved.set()

    def resume_automation(self, detail: str) -> None:
        """
        Completes a hand-back once the engine re-verified the state.
        """
        with self._lock:
            if self._state == "resuming":
                self._transition("agent", detail)

    def request_approval(
        self,
        run_id: str,
        request: approval.ApprovalRequest,
        timeout_s: Optional[float] = None,
    ) -> Optional[approval.ApprovalDecision]:
        """
        Block until an operator answers, or the timeout lapses (``None``).

        The agent keeps control of the session throughout; it is only
        waiting on permission.
        """
        with self._lock:
            self._seq += 1
            self._approval = PendingApproval(
                id=f"approval-{self._seq}",
                run_id=run_id,
                request=request,
                raised_at=time.iso_now(),
            )
            self._approval_decision = None
            self._approval_done.clear()
        self._notify()
        answered = self._approval_done.wait(timeout_s)
        with self._lock:
            decision = self._approval_decision if answered else None
            self._approval = None
        self._notify()
        return decision

    def resolve_approval(
        self,
        approval_id: str,
        approved: bool,
        remember: str = "once",
        note: str = "",
    ) -> None:
        """
        Record the operator's answer to the pending approval.
        """
        with self._lock:
            if self._approval is None or self._approval.id != approval_id:
                raise errors.UnknownApprovalError(approval_id)
            self._approval_decision = approval.ApprovalDecision(
                approved=approved,
                remember="process" if remember == "process" else "once",
                by="console",
                note=note,
            )
            self._approval_done.set()

    def _require_pending(
        self, intervention_id: str, expected: Optional[ControlState]
    ) -> None:
        """
        Assert the pending intervention matches the id and state.
        """
        if self._pending is None or self._pending.id != intervention_id:
            raise errors.UnknownInterventionError(intervention_id)
        if expected is not None and self._state != expected:
            raise errors.InvalidTransitionError(
                f'intervention "{intervention_id}" is not in state '
                f'"{expected}" (state is "{self._state}")'
            )

    def _transition(self, to: ControlState, detail: str) -> None:
        """
        Move to a new control state and notify listeners.
        """
        old = self._state
        self._state = to
        self._on_transition(old, to, detail)
        self._notify()

    def _notify(self) -> None:
        """
        Notify every registered listener.
        """
        for listener in list(self.listeners):
            listener()
