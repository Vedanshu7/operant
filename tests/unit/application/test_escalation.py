import threading
import time
from typing import List, Optional

import pytest

import operant.application.escalation as escal
import operant.domain.approval as approval
import operant.domain.errors as errors


def _broker(*, captures: Optional[List[str]] = None) -> escal.ControlBroker:
    started: List[str] = captures if captures is not None else []

    def start(on_action):
        on_action("human clicked Transfer")
        started.append("started")

    return escal.ControlBroker(
        start_human_capture=start,
        stop_human_capture=lambda: started.append("stopped"),
        on_transition=lambda a, b, d: None,
    )


def _request() -> escal.InterventionRequest:
    return escal.InterventionRequest(
        run_id="replay-1",
        kind="replay",
        capability="goalnative",
        goal="read the balance",
        reason="locator failed",
    )


def test_intervention_take_hand_back_resume() -> None:
    log: List[str] = []
    broker = _broker(captures=log)
    resolutions: List[escal.InterventionResolution] = []

    def run() -> None:
        resolutions.append(broker.raise_intervention(_request()))

    worker = threading.Thread(target=run)
    worker.start()
    while broker.pending is None:
        time.sleep(0.005)
    assert broker.state == "paused"
    iv_id = broker.pending.id
    broker.take_control(iv_id)
    assert broker.state == "human"
    assert broker.human_actions_so_far == ["human clicked Transfer"]
    broker.hand_back(iv_id, "done")
    worker.join(timeout=1)
    assert broker.state == "resuming"
    assert resolutions[0].resolution == "resumed"
    assert resolutions[0].human_actions == ["human clicked Transfer"]
    broker.resume_automation("state re-verified")
    assert broker.state == "agent"
    assert log[-1] == "stopped"


def test_abandon_ends_the_run() -> None:
    broker = _broker()
    resolutions: List[escal.InterventionResolution] = []
    worker = threading.Thread(
        target=lambda: resolutions.append(broker.raise_intervention(_request()))
    )
    worker.start()
    while broker.pending is None:
        time.sleep(0.005)
    broker.abandon(broker.pending.id, "unrecoverable")
    worker.join(timeout=1)
    assert broker.state == "agent"
    assert resolutions[0].resolution == "abandoned"


def test_unknown_intervention_id_raises() -> None:
    broker = _broker()
    with pytest.raises(errors.UnknownInterventionError):
        broker.take_control("iv-99")


def test_second_intervention_while_paused_is_rejected() -> None:
    broker = _broker()
    threading.Thread(
        target=lambda: broker.raise_intervention(_request()), daemon=True
    ).start()
    while broker.pending is None:
        time.sleep(0.005)
    with pytest.raises(errors.InvalidTransitionError):
        broker.raise_intervention(_request())


def test_approval_round_trip_and_timeout() -> None:
    broker = _broker()
    request = approval.ApprovalRequest(
        kind="mutating", summary="click Transfer", action_kind="click"
    )

    def console() -> None:
        while broker.pending_approval is None:
            time.sleep(0.005)
        broker.resolve_approval(broker.pending_approval.id, True, "once")

    threading.Thread(target=console).start()
    decision = broker.request_approval("replay-1", request, timeout_s=5)
    assert decision is not None and decision.approved and decision.by == "console"
    assert broker.request_approval("replay-1", request, timeout_s=0.05) is None
