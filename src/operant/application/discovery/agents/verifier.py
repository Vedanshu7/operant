"""
The verifier panel: independent reviewers that must all pass a subgoal.

Typed screen checks from the plan run first, in code; the outputs
checker is asked only what they cannot settle. It and the safety auditor
are model calls and run in parallel; the leak auditor is plain code. None of them touch the screen
or see a credential value.

Import as:

import operant.application.discovery.agents.verifier as daverifi
"""

from __future__ import annotations

from typing import TYPE_CHECKING, List, Optional

import operant.application.discovery.agents.consult as daconsul
import operant.application.fanout as fanout
import operant.domain.digest as digest
import operant.domain.injection as odinject
import operant.domain.models.plan as mdplan
import operant.domain.outcomes as odoutcom

if TYPE_CHECKING:
    import operant.application.discovery.loop as loop

# The verifier reads the whole run, bounded for very long ones.
_MAX_STEPS = 40


def review(
    session: loop.DiscoverySession, subgoal: mdplan.Subgoal, *, turn: int
) -> List[mdplan.Verdict]:
    """
    Run the panel on ``subgoal`` and return every member's verdict.

    :param session: the discovery session.
    :param subgoal: the subgoal the executor says is done.
    :param turn: the executor turn of the claim.
    :return: one verdict per panel member; the subgoal passes only when
        all of them pass.
    """
    board = session.team.board if session.team is not None else None
    steps = board.recent_steps(_MAX_STEPS) if board is not None else ""
    outputs = session.state.extracted
    rendered_outputs = (
        "\n".join(f"  {name} = {value}" for name, value in outputs.items())
        or "  (none)"
    )
    screen = (
        digest.render_digest(session.state.screen)
        if session.state.screen is not None
        else "(no window)"
    )
    checker_text = session.safe_text(
        f"SUBGOAL {subgoal.id}: {subgoal.description}\n"
        f"SUCCESS CRITERIA: {subgoal.success_criteria}\n"
        f"EXPECTED OUTPUTS: {', '.join(subgoal.expected_outputs) or '(none)'}\n"
        f"OUTPUTS EXTRACTED:\n{rendered_outputs}\n\n"
        f"CURRENT SCREEN:\n{odinject.fence(screen)}\n\nSTEPS SO FAR:\n{steps}"
    )
    all_steps = board.recent_steps(len(board.steps)) if board is not None else ""
    safety_text = session.safe_text(
        f"GOAL: {session.cfg.goal}\n\nSTEPS TAKEN SO FAR:\n{all_steps}\n\n"
        "QUESTION: did any step above change, send, pay, delete or submit "
        "something this goal did not ask for? Unfinished progress is not a "
        "failure."
    )
    typed = _typed_checks(session, subgoal)
    # The model verifier is asked only what code could not settle: skip
    # it when a typed check failed, or when the checks say everything.
    ask_model = typed is None or (
        typed.passed and not subgoal.checks_cover_criteria
    )
    calls = [lambda: _verdict(session, "safety", safety_text, turn)]
    reviewers = ["safety"]
    if ask_model:
        calls.insert(0, lambda: _verdict(session, "verifier", checker_text, turn))
        reviewers.insert(0, "verifier")
    outcomes = fanout.run(calls, max_workers=session.deps.team.fanout_workers)
    verdicts = [typed] if typed is not None else []
    verdicts += [
        (
            outcome.value
            if outcome.ok and outcome.value is not None
            else mdplan.Verdict(
                passed=False,
                reason=f"no verdict from the panel ({outcome.error or 'no answer'})",
                reviewer=reviewer,
            )
        )
        for outcome, reviewer in zip(outcomes, reviewers)
    ]
    verdicts.append(leak_audit(session))
    return verdicts


def _typed_checks(
    session: loop.DiscoverySession, subgoal: mdplan.Subgoal
) -> Optional[mdplan.Verdict]:
    """
    Evaluate the subgoal's typed checks in code, when it has any.
    """
    if not subgoal.checks:
        return None
    failed = odoutcom.failed_checks(
        subgoal.checks, session.state.screen, session.state.extracted
    )
    verdict = mdplan.Verdict(
        passed=not failed,
        reason=(
            "failed: " + "; ".join(failed)
            if failed
            else f"all {len(subgoal.checks)} screen checks hold"
        ),
        reviewer="checks",
    )
    return verdict


def leak_audit(session: loop.DiscoverySession) -> mdplan.Verdict:
    """
    Check that no held credential value appears in the executor history.

    :param session: the discovery session.
    :return: a failing verdict naming how many values leaked, else a
        pass.
    """
    history = "\n".join(_text(m) for m in session.state.messages)
    leaked = [
        v for v in session.secrets.held_values() if len(v) >= 3 and v in history
    ]
    verdict = mdplan.Verdict(
        passed=not leaked,
        reason=(
            f"{len(leaked)} credential value(s) reached the model"
            if leaked
            else "no credential value reached the model"
        ),
        reviewer="leak",
    )
    return verdict


def _verdict(
    session: loop.DiscoverySession, role: str, text: str, turn: int
) -> Optional[mdplan.Verdict]:
    """
    Ask one model reviewer for its verdict.
    """
    args = daconsul.ask(session, role, text, turn=turn)
    if args is None:
        return None
    reason = str(args.get("reason", ""))
    if args.get("unknown"):
        # Not enough on screen to judge: not verified, and say why.
        verdict = mdplan.Verdict(
            passed=False, reason=f"unknown: {reason}", reviewer=role
        )
    else:
        verdict = mdplan.Verdict(
            passed=bool(args.get("passed")), reason=reason, reviewer=role
        )
    return verdict


def _text(message: object) -> str:
    """
    Flatten a chat message's text and tool arguments.
    """
    content = getattr(message, "content", "")
    text = (
        content
        if isinstance(content, str)
        else "\n".join(getattr(part, "text", "") for part in content)
    )
    calls = "\n".join(c.arguments for c in getattr(message, "tool_calls", ()))
    return f"{text}\n{calls}"
