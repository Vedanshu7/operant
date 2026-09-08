"""
The planner role: split the goal into checkable subgoals.

It sees a redacted, PII-scrubbed view - the goal, the current screen,
the app map, and recalled memory - and never acts.

Import as:

import operant.application.discovery.agents.planner as daplanne
"""

from __future__ import annotations

import collections.abc
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

import pydantic

import operant.application.discovery.agents.consult as daconsul
import operant.application.fanout as fanout
import operant.domain.digest as digest
import operant.domain.models.plan as mdplan

if TYPE_CHECKING:
    import operant.application.discovery.loop as loop

_MAP_EDGES = 12


def propose(
    session: loop.DiscoverySession,
    *,
    turn: int,
    reason: str = "",
    memory: str = "",
) -> Tuple[mdplan.Plan, bool]:
    """
    Ask the planner for a plan; fall back to the goal as one subgoal.

    :param session: The discovery session.
    :param turn: The executor turn the planning happens at.
    :param reason: Why a replan was asked for, when replanning.
    :param memory: Recalled plans and lessons, already rendered.
    :return: The chosen plan, and whether it came from the model.
    """
    text = session.safe_text(_planner_input(session, reason, memory))
    samples = max(1, session.deps.team.planner_samples)
    outcomes = fanout.run(
        [lambda: _one_plan(session, text, turn)] * samples,
        max_workers=session.deps.team.fanout_workers,
    )
    plans = [o.value for o in outcomes if o.ok and o.value is not None]
    chosen = pick(plans)
    plan = chosen if chosen is not None else mdplan.single_step(session.cfg.goal)
    return plan, chosen is not None


def pick(plans: collections.abc.Sequence[mdplan.Plan]) -> Optional[mdplan.Plan]:
    """
    Choose among plan candidates deterministically: fewest subgoals wins, ties
    go to the earliest candidate.

    :param plans: Valid candidate plans, in sample order.
    :return: The chosen plan, or ``None`` when there are none.
    """
    ranked = sorted(
        enumerate(plans), key=lambda item: (len(item[1].subgoals), item[0])
    )
    chosen = ranked[0][1] if ranked else None
    return chosen


def _one_plan(
    session: loop.DiscoverySession, text: str, turn: int
) -> Optional[mdplan.Plan]:
    """
    Get one validated plan, retrying once with the validation error.
    """
    plan: Optional[mdplan.Plan] = None
    prompt = text
    for _ in range(2):
        args = daconsul.ask(session, "planner", prompt, turn=turn)
        if args is None:
            # No usable answer: retrying the same prompt rarely helps.
            break
        try:
            plan = mdplan.Plan.model_validate(_normalize(args))
            break
        except pydantic.ValidationError as err:
            # Show the planner what was wrong and ask once more.
            prompt = (
                f"{text}\n\nYour previous plan was rejected: "
                f"{err.errors()[0]['msg']}. Submit a corrected plan."
            )
    return plan


def _normalize(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Give subgoals missing ids a positional id.
    """
    subgoals = args.get("subgoals")
    if isinstance(subgoals, list):
        for index, subgoal in enumerate(subgoals, start=1):
            if isinstance(subgoal, dict) and not subgoal.get("id"):
                subgoal["id"] = f"s{index}"
    return args


def _planner_input(
    session: loop.DiscoverySession, reason: str, memory: str
) -> str:
    """
    Render what the planner sees.
    """
    state = session.state
    screen = (
        digest.render_digest(state.screen)
        if state.screen is not None
        else "(no window yet - the executor's first action will be a launch)"
    )
    parts: List[str] = [f"GOAL: {session.cfg.goal}", f"CURRENT SCREEN:\n{screen}"]
    known = session.cfg.known_graph
    if known is not None:
        moves = [edge.description for edge in known.edges if edge.description]
        nodes = [node.description for node in known.nodes]
        parts.append(
            "APP MAP (already mapped for this app):\n"
            f"  screens: {', '.join(nodes[:_MAP_EDGES])}\n"
            f"  moves: {'; '.join(moves[:_MAP_EDGES])}"
        )
    board = session.team.board if session.team is not None else None
    if board is not None and board.done:
        finished = "; ".join(f"{d} ({s})" for d, s in board.done)
        parts.append(f"ALREADY DONE (do not plan these again): {finished}")
    if reason:
        parts.append(f"REPLANNING BECAUSE: {reason}")
    if memory:
        parts.append(memory)
    text = "\n\n".join(parts)
    return text
