"""
The agent-memory port: plans and lessons that outlive one run.

Import as:

import operant.ports.memory as pmmemory
"""

from __future__ import annotations

from typing import List, Protocol, runtime_checkable

import operant.domain.models.memory as mdmemory

# #############################################################################
# MemoryStore
# #############################################################################


@runtime_checkable
class MemoryStore(Protocol):
    """
    Persist plans and lessons, scoped per app.
    """

    def plans(self, vendor_id: str) -> List[mdmemory.PlanMemory]:
        """
        Return every stored plan for ``vendor_id``.
        """
        ...

    def lessons(self, vendor_id: str) -> List[mdmemory.Lesson]:
        """
        Return every stored lesson for ``vendor_id``.
        """
        ...

    def save_plan(
        self, vendor_id: str, goal_key: str, goal_text: str, plan_json: str
    ) -> None:
        """
        Add a plan, or count one more success for the same goal key.
        """
        ...

    def mark_plan_failed(self, plan_id: int) -> None:
        """
        Count a run that used the plan and still escalated.
        """
        ...

    def save_lesson(
        self, vendor_id: str, goal_key: str, lesson: str, source: str
    ) -> None:
        """
        Add a lesson, or reinforce the same one.
        """
        ...

    def touch(self, plan_ids: List[int], lesson_ids: List[int]) -> None:
        """
        Mark plans and lessons as just recalled.
        """
        ...

    def all_text(self) -> List[str]:
        """
        Return every stored text field, for the audit.
        """
        ...
