"""
Agent memory: recall plans and lessons for a goal, and record new ones.

Advisory only, like remediation memory: what is recalled is offered as a
hint, and the live screen always wins. Everything stored passes the
run's redactor and PII scrubber first, and plans keep names, never
values: numbers and amounts are masked before anything is written.
Memory is scoped per app; nothing is recalled across apps.

Import as:

import operant.application.memory as apmemory
"""

from __future__ import annotations

import collections.abc
import dataclasses
import datetime
from typing import Final, List, Tuple

import operant.domain.models.memory as mdmemory
import operant.domain.models.plan as mdplan
import operant.ports.memory as pmmemory

_MIN_SIMILARITY: Final = 0.5
_MAX_PLANS: Final = 2
_MAX_LESSONS: Final = 3
_STALE_DAYS: Final = 90


# #############################################################################
# Recalled
# #############################################################################


@dataclasses.dataclass(frozen=True)
class Recalled:
    """
    What memory offers the agents for one goal.

    :ivar plans: Up to two past plans for similar goals.
    :ivar lessons: Up to three lessons from this app.
    """

    plans: Tuple[mdmemory.PlanMemory, ...] = ()
    lessons: Tuple[mdmemory.Lesson, ...] = ()

    def render(self) -> str:
        """
        Render the recall as advisory text for the planner.
        """
        lines: List[str] = []
        for plan in self.plans:
            lines.append(
                f"  past plan for '{plan.goal_text}' "
                f"({plan.successes} ok / {plan.failures} failed): {plan.plan_json}"
            )
        for lesson in self.lessons:
            lines.append(f"  lesson ({lesson.source}): {lesson.lesson}")
        text = (
            "MEMORY (advisory - the live screen always wins):\n"
            + "\n".join(lines)
            if lines
            else ""
        )
        return text


# #############################################################################
# AgentMemory
# #############################################################################


class AgentMemory:
    """
    Recall and record plans and lessons through a store.
    """

    def __init__(self, store: pmmemory.MemoryStore) -> None:
        self._store = store

    def recall(self, vendor_id: str, goal: str) -> Recalled:
        """
        Return the best plans and lessons for ``goal`` on ``vendor_id``.

        :param vendor_id: The app; recall never crosses apps.
        :param goal: The goal being planned.
        :return: Ranked, non-stale plans and lessons.
        """
        key = mdmemory.goal_key(goal)
        plans = [
            p
            for p in self._store.plans(vendor_id)
            if not _stale(p.last_used_at, p.successes, p.failures)
            and (
                p.goal_key == key
                or mdmemory.similarity(p.goal_key, key) >= _MIN_SIMILARITY
            )
        ]
        plans.sort(
            key=lambda p: (
                p.goal_key != key,
                -(p.successes - p.failures),
                _age(p.last_used_at),
            )
        )
        lessons = sorted(
            self._store.lessons(vendor_id),
            key=lambda lsn: (
                -mdmemory.similarity(lsn.goal_key, key),
                -lsn.reinforcements,
                _age(lsn.last_used_at),
            ),
        )
        recalled = Recalled(
            plans=tuple(plans[:_MAX_PLANS]), lessons=tuple(lessons[:_MAX_LESSONS])
        )
        self._store.touch(
            [p.id for p in recalled.plans], [lsn.id for lsn in recalled.lessons]
        )
        return recalled

    def record_plan(
        self,
        vendor_id: str,
        goal: str,
        plan: mdplan.Plan,
        *,
        safe: collections.abc.Callable[[str], str],
    ) -> None:
        """
        Remember a plan whose run finished verified.

        :param vendor_id: The app.
        :param goal: The goal it achieved.
        :param plan: The plan (names only by construction).
        :param safe: The run's redact-then-scrub function.
        """
        self._store.save_plan(
            vendor_id,
            mdmemory.goal_key(goal),
            mdmemory.mask_numbers(safe(goal)),
            mdmemory.mask_numbers(safe(plan.model_dump_json())),
        )

    def record_failure(
        self, plans: collections.abc.Sequence[mdmemory.PlanMemory]
    ) -> None:
        """
        Count a failure for each recalled plan the run still escalated with.
        """
        for plan in plans:
            self._store.mark_plan_failed(plan.id)

    def record_lesson(
        self,
        vendor_id: str,
        goal: str,
        lesson: str,
        *,
        source: str,
        safe: collections.abc.Callable[[str], str],
    ) -> None:
        """
        Remember a mistake to avoid on this app.

        :param vendor_id: The app.
        :param goal: The goal it happened on.
        :param lesson: What went wrong.
        :param source:``verifier`` or ``human``.
        :param safe: The run's redact-then-scrub function.
        """
        self._store.save_lesson(
            vendor_id,
            mdmemory.goal_key(goal),
            mdmemory.mask_numbers(safe(lesson)),
            source,
        )


def _age(iso: str) -> float:
    """
    Seconds since ``iso``; unparseable times count as very old.
    """
    try:
        then = datetime.datetime.fromisoformat(iso)
        if then.tzinfo is None:
            then = then.replace(tzinfo=datetime.timezone.utc)
        age = (
            datetime.datetime.now(datetime.timezone.utc) - then
        ).total_seconds()
    except ValueError:
        age = float("inf")
    return age


def _stale(iso: str, successes: int, failures: int) -> bool:
    """
    Report whether a plan is stale: unused for a long time and failing more
    often than it succeeds.
    """
    unused = _age(iso) > _STALE_DAYS * 86_400
    stale = unused and failures > successes
    return stale
