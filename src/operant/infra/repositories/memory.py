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

    def vendors(self) -> List[str]:
        """
        Return every app that has stored plans or lessons.
        """
        with self._db.session() as session:
            found = set(
                session.scalars(sqlalchemy.select(models.PlanMemoryRow.vendor_id))
            ) | set(
                session.scalars(sqlalchemy.select(models.LessonRow.vendor_id))
            )
        return sorted(found)

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
                    graph_version=row.graph_version,
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
                    subgoal_key=row.subgoal_key,
                    failure_kind=row.failure_kind,
                    graph_version=row.graph_version,
                )
                for row in session.scalars(statement)
            ]
        return found

    def save_plan(
        self,
        vendor_id: str,
        goal_key: str,
        goal_text: str,
        plan_json: str,
        *,
        graph_version: int = 0,
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
                        graph_version=graph_version,
                    )
                )
            else:
                # Keep the latest plan that worked, and count the success.
                row.plan_json = plan_json
                row.successes += 1
                row.last_used_at = time.iso_now()
                row.graph_version = graph_version

    def mark_plan_failed(self, plan_id: int) -> None:
        """
        Count a run that recalled the plan and still failed.
        """
        with self._db.session() as session:
            row = session.get(models.PlanMemoryRow, plan_id)
            if row is not None:
                row.failures += 1

    def save_lesson(
        self,
        vendor_id: str,
        goal_key: str,
        lesson: str,
        source: str,
        *,
        subgoal_key: str = "",
        failure_kind: str = "",
        graph_version: int = 0,
    ) -> None:
        """
        Add a lesson, or reinforce the one it repeats.

        A lesson about a subgoal repeats one with the same subgoal and
        failure kind, and replaces its text (the latest "what worked"
        wins); a person's note repeats one with the same text.
        """
        same = (
            (
                models.LessonRow.subgoal_key == subgoal_key,
                models.LessonRow.failure_kind == failure_kind,
            )
            if subgoal_key
            else (models.LessonRow.lesson == lesson,)
        )
        statement = sqlalchemy.select(models.LessonRow).where(
            models.LessonRow.vendor_id == vendor_id, *same
        )
        with self._db.session() as session:
            row = session.scalars(statement).first()
            if row is None:
                # A new lesson on this app.
                session.add(
                    models.LessonRow(
                        vendor_id=vendor_id,
                        goal_key=goal_key,
                        lesson=lesson,
                        source=source,
                        reinforcements=1,
                        last_used_at=time.iso_now(),
                        subgoal_key=subgoal_key,
                        failure_kind=failure_kind,
                        graph_version=graph_version,
                    )
                )
            else:
                # The same lesson again: it matters more.
                row.lesson = lesson
                row.reinforcements += 1
                row.last_used_at = time.iso_now()
                row.graph_version = graph_version

    def delete(self, plan_ids: List[int], lesson_ids: List[int]) -> None:
        """
        Remove plans and lessons by id.
        """
        with self._db.session() as session:
            if plan_ids:
                session.execute(
                    sqlalchemy.delete(models.PlanMemoryRow).where(
                        models.PlanMemoryRow.id.in_(plan_ids)
                    )
                )
            if lesson_ids:
                session.execute(
                    sqlalchemy.delete(models.LessonRow).where(
                        models.LessonRow.id.in_(lesson_ids)
                    )
                )

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
