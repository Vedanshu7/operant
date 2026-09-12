"""
The one act-then-record step shared by discovery and the drive REPL.

Both must gate, snapshot, classify risk, and record identically, or
replay of a demonstrated capability diverges from replay of a discovered
one.

Import as:

import operant.application.acting as acting
"""

from __future__ import annotations

import collections.abc
import dataclasses
import time
from typing import Optional, Tuple

import operant.application.approval as approval
import operant.application.recorder.recording as recdng
import operant.domain.approval as daapprov
import operant.domain.models.actions as actions
import operant.domain.models.digest as digest
import operant.domain.models.graph as graph
import operant.domain.policy as policy
import operant.ports.evidence as evidence
import operant.ports.hitl as hitl
import operant.ports.surface as pssurfac

# Actions that can load a new page; the screen is read only once it settles.
_NAVIGATING = frozenset({"click", "press", "launch"})


# #############################################################################
# SettlePolicy
# #############################################################################


@dataclasses.dataclass(frozen=True)
class SettlePolicy:
    """
    How long to wait for the screen after an action that may navigate.

    :ivar poll_s: Time between screen reads.
    :ivar change_window_s: With no change by then, the action did not
        navigate; stop waiting.
    :ivar max_s: Hard bound on the wait.
    """

    poll_s: float = 0.25
    change_window_s: float = 1.5
    max_s: float = 6.0


def _screen_key(screen: Optional[digest.ScreenDigest]) -> Tuple[str, str]:
    """
    Reduce a screen to what tells one page from another.
    """
    key = (screen.window_title, screen.text) if screen is not None else ("", "")
    return key


def settled_snapshot(
    surface: pssurfac.Surface,
    before: Optional[digest.ScreenDigest],
    timing: SettlePolicy,
) -> digest.ScreenDigest:
    """
    Read the screen once it has changed and then held still.

    A page that is still loading reads as the old page, so the first
    read after a click can be stale. This polls until the screen differs
    from ``before`` and two reads agree, or until nothing changed within
    the change window (the action did not navigate), or the hard bound.

    :param surface: The surface to read.
    :param before: The screen before the action.
    :param timing: Timing bounds.
    :return: The settled screen (the last read on timeout).
    """
    start = time.monotonic()
    before_key = _screen_key(before)
    last = surface.snapshot()
    changed = _screen_key(last) != before_key
    while time.monotonic() - start < timing.max_s:
        if not changed and time.monotonic() - start >= timing.change_window_s:
            # Nothing moved: the action did not load a new page.
            break
        time.sleep(timing.poll_s)
        current = surface.snapshot()
        if changed and _screen_key(current) == _screen_key(last):
            # Changed and now steady: the new page has loaded.
            last = current
            break
        changed = changed or _screen_key(current) != before_key
        last = current
    return last


def perform_and_record(
    surface: pssurfac.Surface,
    app_policy: policy.Policy,
    action: actions.SurfaceAction,
    *,
    approver: hitl.Approver,
    log: Optional[evidence.EvidenceSink],
    recorder: Optional[recdng.Recorder],
    recorded: Optional[graph.Action],
    description: str,
    pre_digest: Optional[digest.ScreenDigest],
    click_point: Optional[Tuple[float, float]] = None,
    on_grant: Optional[
        collections.abc.Callable[[daapprov.ScopeGrant], None]
    ] = None,
    settle: Optional[SettlePolicy] = None,
) -> digest.ScreenDigest:
    """
    Perform the action through the approval gate, then records the edge.

    ``ApprovalDeniedError`` and ``PolicyViolationError`` propagate -
    callers own the blocked-action experience.

    :param surface: The actuation surface.
    :param app_policy: Policy used to classify the recorded edge's risk.
    :param action: The action to perform.
    :param approver: Who answers approval questions.
    :param log: Evidence sink for approval events.
    :param recorder: Recorder to append the edge to; ``None`` skips
        recording.
    :param recorded: The edge action to record; ``None`` skips
        recording.
    :param description: What the action accomplishes.
    :param pre_digest: The screen before the action, when known.
    :param click_point: Window-normalised point for vision clicks.
    :param on_grant: Called with each scope grant made during the round-
        trip.
    :param settle: When set, a navigating action's screen is read only
        once it settles; ``None`` reads it at once (tests, fakes).
    :return: The screen digest after the action.
    """
    pre_title = pre_digest.window_title if pre_digest else ""
    control: Optional[digest.Control] = None
    if action.ref and pre_digest:
        control = next(
            (c for c in pre_digest.controls if c.ref == action.ref), None
        )
    outcome = approval.perform_gated(
        surface,
        action,
        approver=approver,
        log=log,
        run_id=log.run_id if log else "",
    )
    if on_grant is not None:
        for grant in outcome.grants:
            on_grant(grant)
    after = (
        settled_snapshot(surface, pre_digest, settle)
        if settle is not None and action.kind in _NAVIGATING
        else surface.snapshot()
    )
    if recorder is not None and recorded is not None:
        _record(
            recorder,
            app_policy,
            action,
            recorded,
            control,
            description=description,
            pre_title=pre_title,
            after=after,
            pre_digest=pre_digest,
            click_point=click_point,
        )
    return after


def _record(
    recorder: recdng.Recorder,
    app_policy: policy.Policy,
    action: actions.SurfaceAction,
    recorded: graph.Action,
    control: Optional[digest.Control],
    *,
    description: str,
    pre_title: str,
    after: digest.ScreenDigest,
    pre_digest: Optional[digest.ScreenDigest],
    click_point: Optional[Tuple[float, float]],
) -> None:
    """
    Record the performed edge with its classified risk.
    """
    if not pre_title:
        recorder.start(after.window_title, after)
    # Risk is judged on what the control SAYS, not on the wire action -
    # an empty target_text would classify every recorded edge as safe.
    probe = dataclasses.replace(
        actions.SurfaceAction(kind=action.kind, key=action.key),
        target_text=(
            f"{control.name} | {control.label}" if control else action.target_text
        ),
    )
    risk = policy.classify_risk(app_policy, probe, pre_digest, control)
    recorder.record(
        action=recorded,
        target_control=control,
        description=description,
        risk=risk,
        pre_title=pre_title or after.window_title,
        post_title=after.window_title,
        click_point=click_point,
        screen=after,
    )
