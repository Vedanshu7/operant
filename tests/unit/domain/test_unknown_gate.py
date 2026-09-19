"""
The unknown level: what no policy pattern names is neither safe nor mutating.

Discovery has to explore controls nobody listed, so the ``commit`` mode
runs ordinary navigation and stops only where an action looks like a
commit.
"""

from __future__ import annotations

from typing import List, Optional

import pytest

import operant.domain.approval as approval
import operant.domain.models.actions as actions
import operant.domain.models.digest as digest
import operant.domain.policy as policy
import tests.support.screens as screens


def _policy(mode: approval.UnknownMode) -> policy.Policy:
    return policy.Policy(
        id="p",
        allowed_apps=["App"],
        allowed_url_patterns=[".*"],
        allowed_action_kinds=["click", "press", "fill"],
        mutating_control_patterns=["transfer"],
        safe_control_patterns=["log ?in"],
        approval=approval.ApprovalPolicy(unknown=mode),
    )


def _click(
    mode: approval.UnknownMode,
    control: Optional[digest.Control],
    controls: Optional[List[digest.Control]] = None,
    **kwargs: object,
) -> approval.PolicyDecision:
    text = f"{control.name} | {control.label}" if control else "the green button"
    action = actions.SurfaceAction(
        kind="click", ref=control.ref if control else None, target_text=text
    )
    if kwargs.get("gate"):
        action = actions.SurfaceAction(
            kind="click", ref="c0", target_text=text, gate_unknown=True
        )
    screen = screens.digest(controls or ([control] if control else []))
    return policy.evaluate_action(
        _policy(mode), action, digest=screen, control=control, app="App"
    )


FIELD = screens.control(ref="f", role="text_field", name="Amount", value="10")
LINK = screens.control(role="link", name="Reports")
BUTTON = screens.control(role="button", name="Proceed")


def test_allow_keeps_today_s_behaviour() -> None:
    decision = _click("allow", BUTTON, [FIELD, BUTTON])
    assert (decision.verdict, decision.risk) == ("allow", "safe")


def test_commit_lets_discovery_explore_navigation() -> None:
    decision = _click("commit", LINK)
    assert (decision.verdict, decision.risk) == ("allow", "unknown")


def test_commit_lets_an_unlisted_button_run_when_nothing_was_entered() -> None:
    assert _click("commit", BUTTON).verdict == "allow"


def test_commit_asks_about_a_button_after_a_field_holds_a_value() -> None:
    decision = _click("commit", BUTTON, [FIELD, BUTTON])
    assert decision.verdict == "needs_approval"
    assert decision.approval is not None
    assert decision.approval.kind == "unknown"


def test_commit_asks_about_a_click_with_no_control() -> None:
    assert _click("commit", None).verdict == "needs_approval"


def test_a_click_with_no_control_cannot_talk_its_way_past_the_gate() -> None:
    click = actions.SurfaceAction(
        kind="click", x=0.5, y=0.5, target_text="Log in"
    )
    decision = policy.evaluate_action(
        _policy("commit"), click, digest=screens.digest()
    )
    assert decision.verdict == "needs_approval"


def test_commit_asks_about_enter_with_an_unlisted_button_and_a_filled_field() -> (
    None
):
    enter = actions.SurfaceAction(kind="press", key="Return")
    screen = screens.digest([FIELD, BUTTON])
    decision = policy.evaluate_action(_policy("commit"), enter, digest=screen)
    assert decision.verdict == "needs_approval"


def test_a_listed_safe_control_is_safe_even_after_a_filled_field() -> None:
    login = screens.control(role="button", name="Log In")
    decision = _click("commit", login, [FIELD, login])
    assert (decision.verdict, decision.risk) == ("allow", "safe")


def test_a_mutating_pattern_still_wins() -> None:
    move = screens.control(role="link", name="Transfer Funds")
    decision = _click("commit", move)
    assert decision.approval is not None
    assert decision.approval.kind == "mutating"


def test_a_field_is_never_unknown() -> None:
    assert _click("commit", FIELD).risk == "safe"


def test_ask_stops_at_every_unknown_control() -> None:
    assert _click("ask", LINK).verdict == "needs_approval"


def test_deny_refuses_unknown_controls() -> None:
    assert _click("deny", LINK).verdict == "deny"


def test_a_caller_can_tighten_but_not_loosen() -> None:
    assert _click("commit", LINK, gate=True).verdict == "needs_approval"
    assert _click("allow", LINK, gate=True).verdict == "allow"


def test_the_question_keys_on_the_control_not_its_label() -> None:
    first = screens.control(role="link", name="Reports", label="Menu")
    second = screens.control(role="link", name="Reports", label="Sidebar")
    asks = [_click("ask", control).approval for control in (first, second)]
    assert asks[0] is not None and asks[1] is not None
    assert asks[0].fingerprint == asks[1].fingerprint


@pytest.mark.parametrize(
    "control, expected",
    [(LINK, True), (BUTTON, True), (FIELD, False)],
)
def test_the_judge_sees_only_what_would_otherwise_run(
    control: digest.Control, expected: bool
) -> None:
    click = actions.SurfaceAction(
        kind="click", ref=control.ref, target_text=f"{control.name} | "
    )
    screen = screens.digest([control])
    assert (
        policy.needs_judgement(_policy("commit"), click, screen, control)
        is expected
    )


def test_the_judge_is_skipped_for_commit_shaped_steps() -> None:
    click = actions.SurfaceAction(
        kind="click", ref="c0", target_text="Proceed | "
    )
    screen = screens.digest([FIELD, BUTTON])
    assert not policy.needs_judgement(_policy("commit"), click, screen, BUTTON)
