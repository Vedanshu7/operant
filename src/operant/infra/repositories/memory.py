"""
SQLite-backed agent memory (plans and lessons).

Implements ``operant.ports.memory.MemoryStore``. Called synchronously
from the discovery worker thread; SQLite serialises writers.

Import as:

import operant.infra.repositories.memory as rmmemory
"""

from __future__ import annotations

from typing import List

import sqlalchemy

import operant.domain.models.memory as mdmemory
import operant.helpers.time as time
import operant.infra.db.engine as engine
import operant.infra.db.models as models

# #############################################################################
# SqlMemoryStore
# #############################################################################


class SqlMemoryStore:
    """
    Plans and lessons in the run database.
    """

    def __init__(self, database: engine.Database) -> None:
        self._db = database

    def plans(self, vendor_id: str) -> List[mdmemory.PlanMemory]:
        """
        Return every stored plan for ``vendor_id``.
        """
        statement = sqlalchemy.select(models.PlanMemoryRow).where(
            models.PlanMemoryRow.vendor_id == vendor_id
        )
        with self._db.session() as session:
            found = [
                mdmemory.PlanMemory(
                    id=row.id,
                    vendor_id=row.vendor_id,
                    goal_key=row.goal_key,
                    goal_text=row.goal_text,
                    plan_json=row.plan_json,
                    successes=row.successes,
                    failures=row.failures,
                    last_used_at=row.last_used_at,
                )
                for row in session.scalars(statement)
            ]
        return found

    def lessons(self, vendor_id: str) -> List[mdmemory.Lesson]:
        """
        Return every stored lesson for ``vendor_id``.
        """
        statement = sqlalchemy.select(models.LessonRow).where(
            models.LessonRow.vendor_id == vendor_id
        )
        with self._db.session() as session:
            found = [
                mdmemory.Lesson(
                    id=row.id,
                    vendor_id=row.vendor_id,
                    goal_key=row.goal_key,
                    lesson=row.lesson,
                    source=row.source,
                    reinforcements=row.reinforcements,
                    last_used_at=row.last_used_at,
                )
                for row in session.scalars(statement)
            ]
        return found

    def save_plan(
        self, vendor_id: str, goal_key: str, goal_text: str, plan_json: str
    ) -> None:
        """
        Add a plan, or count one more success for the same goal key.
        """
        statement = sqlalchemy.select(models.PlanMemoryRow).where(
            models.PlanMemoryRow.vendor_id == vendor_id,
            models.PlanMemoryRow.goal_key == goal_key,
        )
        with self._db.session() as session:
            row = session.scalars(statement).first()
            if row is None:
                # First success for this goal on this app.
                session.add(
                    models.PlanMemoryRow(
                        vendor_id=vendor_id,
                        goal_key=goal_key,
                        goal_text=goal_text,
                        plan_json=plan_json,
                        successes=1,
                        failures=0,
                        last_used_at=time.iso_now(),
                    )
                )
            else:
                # Keep the latest plan that worked, and count the success.
                row.plan_json = plan_json
                row.successes += 1
                row.last_used_at = time.iso_now()

    def mark_plan_failed(self, plan_id: int) -> None:
        """
        Count a run that used the plan and still escalated.
        """
        with self._db.session() as session:
            row = session.get(models.PlanMemoryRow, plan_id)
            if row is not None:
                row.failures += 1

    def save_lesson(
        self, vendor_id: str, goal_key: str, lesson: str, source: str
    ) -> None:
        """
        Add a lesson, or reinforce the same one.
        """
        statement = sqlalchemy.select(models.LessonRow).where(
            models.LessonRow.vendor_id == vendor_id,
            models.LessonRow.lesson == lesson,
        )
        with self._db.session() as session:
            row = session.scalars(statement).first()
            if row is None:
                # A new mistake on this app.
                session.add(
                    models.LessonRow(
                        vendor_id=vendor_id,
                        goal_key=goal_key,
                        lesson=lesson,
                        source=source,
                        reinforcements=1,
                        last_used_at=time.iso_now(),
                    )
                )
            else:
                # The same mistake again: it matters more.
                row.reinforcements += 1
                row.last_used_at = time.iso_now()

    def touch(self, plan_ids: List[int], lesson_ids: List[int]) -> None:
        """
        Mark plans and lessons as just recalled.
        """
        now = time.iso_now()
        with self._db.session() as session:
            for plan_id in plan_ids:
                plan = session.get(models.PlanMemoryRow, plan_id)
                if plan is not None:
                    plan.last_used_at = now
            for lesson_id in lesson_ids:
                lesson = session.get(models.LessonRow, lesson_id)
                if lesson is not None:
                    lesson.last_used_at = now

    def all_text(self) -> List[str]:
        """
        Return every stored text field, for the audit.
        """
        with self._db.session() as session:
            texts = [
                text
                for row in session.scalars(
                    sqlalchemy.select(models.PlanMemoryRow)
                )
                for text in (row.goal_text, row.plan_json)
            ]
            texts += [
                row.lesson
                for row in session.scalars(sqlalchemy.select(models.LessonRow))
            ]
        return texts
