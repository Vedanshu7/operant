"""
The coordinator's per-run blackboard for multi-agent discovery.

It holds the plan and the run's progress. Each role gets its own view of
it - never another role's conversation.

Import as:

import operant.application.discovery.blackboard as dsblackb
"""

from __future__ import annotations

import dataclasses
from typing import Dict, List, Optional, Tuple

import operant.domain.models.memory as mdmemory
import operant.domain.models.plan as mdplan

# #############################################################################
# StepNote
# #############################################################################


@dataclasses.dataclass(frozen=True)
class StepNote:
    """
    One executor step, as the reviewers see it.

    :ivar turn: the executor turn.
    :ivar tool: the tool the executor called.
    :ivar intent: what the step was for (or its main argument).
    :ivar result: the first line of the tool's reply.
    """

    turn: int
    tool: str
    intent: str
    result: str


# #############################################################################
# Blackboard
# #############################################################################


@dataclasses.dataclass
class Blackboard:
    """
    Plan and progress for one multi-agent run.

    :ivar plan: the current plan.
    :ivar active: index of the subgoal being worked on.
    :ivar done: ``(subgoal description, summary)`` of verified subgoals.
    :ivar rejections: verifier rejections per subgoal id.
    :ivar replans: replans made so far.
    :ivar steps: every executor step, in order.
    :ivar progress_turn: last turn a subgoal was verified (or planned).
    :ivar subgoal_start: index in the executor history where the active
        subgoal's turns begin.
    :ivar pending_compaction: history range of a just-verified subgoal,
        folded away at the start of the next turn.
    :ivar open_rejections: rejected subgoals not yet verified, keyed by
        their normalised description so they survive a replan; memory
        decides at the end what they teach.
    """

    plan: mdplan.Plan
    active: int = 0
    done: List[Tuple[str, str]] = dataclasses.field(default_factory=list)
    rejections: Dict[str, int] = dataclasses.field(default_factory=dict)
    replans: int = 0
    steps: List[StepNote] = dataclasses.field(default_factory=list)
    progress_turn: int = 0
    subgoal_start: int = 0
    pending_compaction: Optional[int] = None
    open_rejections: Dict[str, mdmemory.Rejection] = dataclasses.field(
        default_factory=dict
    )

    @property
    def current(self) -> Optional[mdplan.Subgoal]:
        """
        Return the active subgoal, or ``None`` when all are done.
        """
        subgoals = self.plan.subgoals
        found = subgoals[self.active] if self.active < len(subgoals) else None
        return found

    @property
    def is_last(self) -> bool:
        """
        Whether the active subgoal is the plan's last one.
        """
        return self.active >= len(self.plan.subgoals) - 1

    def remaining(self) -> List[mdplan.Subgoal]:
        """
        Return the subgoals after the active one.
        """
        return list(self.plan.subgoals[self.active + 1 :])

    def executor_block(self) -> str:
        """
        Render the plan context added to each executor turn.
        """
        lines: List[str] = []
        for description, summary in self.done:
            lines.append(f"  [done] {description}: {summary}")
        current = self.current
        if current is not None:
            lines.append(
                f"ACTIVE SUBGOAL {current.id}: {current.description} "
                f"(done when: {current.success_criteria})"
            )
            if current.expected_outputs:
                lines.append(
                    "  extract before finishing it: "
                    + ", ".join(current.expected_outputs)
                )
        for later in self.remaining():
            lines.append(f"  later: {later.id} {later.description}")
        lines.append(
            "Call subgoal_done(summary) when the ACTIVE subgoal is achieved; "
            "a reviewer checks the screen. Call goal_complete only when the "
            "last subgoal is achieved."
        )
        block = "PLAN:\n" + "\n".join(lines)
        return block

    def recent_steps(self, count: int) -> str:
        """
        Render the last ``count`` executor steps for a reviewer.
        """
        shown = [
            f"  turn {s.turn}: {s.tool} {s.intent} -> {s.result}"
            for s in self.steps[-count:]
        ]
        rendered = "\n".join(shown) or "  (no steps yet)"
        return rendered
