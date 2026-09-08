"""
Fan-out helpers around the executor: regex candidates for a failed extract, and
advisory reviews of the saved recording.

Neither touches the screen. Extract candidates are checked by code
against the visible text; reviews are evidence only and never block or
change the save.

Import as:

import operant.application.discovery.agents.reviewers as darevie
"""

from __future__ import annotations

import functools
import json
import re
from typing import TYPE_CHECKING, List, Optional

import operant.application.discovery.agents.consult as daconsul
import operant.application.fanout as fanout
import operant.application.recorder.recording as recdng
import operant.domain.events as events
import operant.domain.outcomes as outcomes

if TYPE_CHECKING:
    import operant.application.discovery.loop as loop

_MAX_REVIEWED_EDGES = 20
_TEXT_LIMIT = 2500


def extract_candidates(
    session: loop.DiscoverySession, name: str, failed: str, *, turn: int
) -> Optional[str]:
    """
    Propose regexes in parallel and keep the best one that matches.

    :param session: The discovery session.
    :param name: The output being extracted.
    :param failed: The executor's pattern that did not match.
    :param turn: The executor turn.
    :return: A one-group pattern that matches the visible text, or
        ``None`` when no candidate does.
    """
    screen = session.state.screen
    count = session.deps.team.extract_candidates
    chosen: Optional[str] = None
    if screen is not None and count > 0:
        text = (
            f"OUTPUT NAME: {name}\nPATTERN THAT DID NOT MATCH: {failed}\n\n"
            f"VISIBLE TEXT:\n{screen.text[:_TEXT_LIMIT]}"
        )
        results = fanout.run(
            [
                lambda: daconsul.ask(
                    session,
                    "extract",
                    text,
                    turn=turn,
                    traced_text=session.safe_text(text),
                )
            ]
            * count,
            max_workers=session.deps.team.fanout_workers,
        )
        patterns = [
            str(r.value.get("pattern", ""))
            for r in results
            if r.ok and r.value is not None
        ]
        chosen = best_pattern(patterns, screen.text)
    return chosen


def best_pattern(patterns: List[str], text: str) -> Optional[str]:
    """
    Pick the candidate to keep: it must compile, have one group, and match; one
    that does not spell out the captured value wins.

    :param patterns: Candidate regexes, in proposal order.
    :param text: The visible text they must match.
    :return: The chosen pattern, or ``None`` when none qualifies.
    """
    valid: List[str] = []
    anchored: List[str] = []
    for pattern in patterns:
        try:
            groups = re.compile(pattern).groups
            value = outcomes.extract_one(pattern, text) if groups == 1 else None
        except re.error:
            value = None
        if value:
            valid.append(pattern)
            if value not in pattern:
                # Anchored on labels, not on today's value: survives change.
                anchored.append(pattern)
    preferred = anchored or valid
    chosen = preferred[0] if preferred else None
    return chosen


def review_recording(
    session: loop.DiscoverySession, recording: recdng.Recording, *, turn: int
) -> None:
    """
    Review each recorded step's locator and the typed contract, in parallel,
    and log the findings as ``compile_review`` events.

    :param session: The discovery session.
    :param recording: The recording about to be returned.
    :param turn: The executor turn of ``goal_complete``.
    """
    edges = [e for e in recording.edges if e.target is not None]
    edges = edges[:_MAX_REVIEWED_EDGES]
    tasks = [
        (
            edge.id,
            session.safe_text(
                f"STEP: {edge.description}\nACTION: {edge.action.kind}\n"
                f"LOCATOR: {edge.target.model_dump_json() if edge.target else ''}"
            ),
            "critic",
        )
        for edge in edges
    ]
    contract = {
        "goal": session.cfg.goal,
        "inputs": {
            name: {"type": spec.type, "description": spec.description}
            for name, spec in recording.inputs.items()
        },
        "outputs": sorted(recording.outputs),
    }
    tasks.append(("schema", session.safe_text(json.dumps(contract)), "schema"))
    results = fanout.run(
        [
            functools.partial(daconsul.ask, session, role, text, turn=turn)
            for _, text, role in tasks
        ],
        max_workers=session.deps.team.fanout_workers,
    )
    for (target, _, _), result in zip(tasks, results):
        if result.ok and result.value is not None:
            session.log.emit(
                events.CompileReview(
                    target=target,
                    verdict=str(result.value.get("verdict", "ok")),
                    note=str(result.value.get("note", "")),
                    summary=f"review {target}: {result.value.get('verdict')}",
                )
            )
