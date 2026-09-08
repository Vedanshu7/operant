"""
Agent-memory tests over an in-memory SQLite store: recall is scoped per app,
ranked, keeps no values, and skips stale plans.
"""

from __future__ import annotations

import operant.application.memory as apmemory
import operant.domain.models.memory as mdmemory
import operant.domain.models.plan as mdplan
import operant.infra.db.engine as engine
import operant.infra.repositories.memory as rmmemory


def _memory() -> apmemory.AgentMemory:
    database = engine.Database.open(None)
    database.create_all()
    return apmemory.AgentMemory(rmmemory.SqlMemoryStore(database))


def _plan(description: str) -> mdplan.Plan:
    return mdplan.Plan(
        subgoals=[
            mdplan.Subgoal(
                id="s1", description=description, success_criteria="ok"
            )
        ]
    )


def _same(text: str) -> str:
    return text


def test_a_similar_goal_recalls_the_plan_on_the_same_app_only() -> None:
    memory = _memory()
    memory.record_plan(
        "bank", "Transfer $25 to account 13344", _plan("transfer"), safe=_same
    )
    hit = memory.recall("bank", "Transfer $90 to account 55555")
    miss = memory.recall("crm", "Transfer $90 to account 55555")
    assert len(hit.plans) == 1
    assert miss.plans == ()
    assert "MEMORY (advisory" in hit.render()


def test_stored_text_keeps_no_numbers_or_amounts() -> None:
    database = engine.Database.open(None)
    database.create_all()
    store = rmmemory.SqlMemoryStore(database)
    memory = apmemory.AgentMemory(store)
    memory.record_plan(
        "bank",
        "Transfer $25 to account 13344",
        _plan("send $25 to 13344"),
        safe=_same,
    )
    memory.record_lesson(
        "bank",
        "x",
        "typed 13344 into the wrong field",
        source="verifier",
        safe=_same,
    )
    stored = " ".join(store.all_text())
    assert "13344" not in stored and "$25" not in stored
    assert "<n>" in stored


def test_the_safe_function_runs_before_storage() -> None:
    memory = _memory()
    memory.record_lesson(
        "bank",
        "goal",
        "Jordan Lee was shown",
        source="human",
        safe=lambda s: s.replace("Jordan Lee", "<PERSON>"),
    )
    lessons = memory.recall("bank", "goal").lessons
    assert lessons[0].lesson == "<PERSON> was shown"


def test_repeated_lessons_are_reinforced_not_duplicated() -> None:
    memory = _memory()
    for _ in range(3):
        memory.record_lesson(
            "bank", "g", "same mistake", source="verifier", safe=_same
        )
    lessons = memory.recall("bank", "g").lessons
    assert len(lessons) == 1 and lessons[0].reinforcements == 3


def test_failures_are_counted_on_recalled_plans() -> None:
    memory = _memory()
    memory.record_plan("bank", "read balance", _plan("read"), safe=_same)
    recalled = memory.recall("bank", "read balance")
    memory.record_failure(recalled.plans)
    again = memory.recall("bank", "read balance").plans[0]
    assert (again.successes, again.failures) == (1, 1)


def test_goal_keys_ignore_numbers_and_stop_words() -> None:
    assert mdmemory.goal_key("Send $25 to account 13344") == mdmemory.goal_key(
        "send $90 to the account 777"
    )
    assert mdmemory.similarity("a b c", "a b d") == 0.5
