"""
Behavioral evals for agent memory, in each mode from OPERANT_EVAL_MODES (a
single agent reads memory when the memory mode is ``all``): a recalled plan
should not cost turns, stale memory must lose to the live screen, and memory
must keep no values.

Skipped unless OPERANT_RUN_LLM_EVALS=1; see tests/evals/conftest.py.
"""

from __future__ import annotations

import dataclasses
import pathlib
import statistics

import pytest

import operant.application.memory as apmemory
import operant.domain.models.plan as mdplan
import operant.infra.db.engine as engine
import operant.infra.repositories.memory as rmmemory
import tests.evals.catalog as catalog
import tests.evals.harness as harness
import tests.evals.scenes as scenes

_TRIALS = 3


def _store() -> rmmemory.SqlMemoryStore:
    database = engine.Database.open(None)
    database.create_all()
    return rmmemory.SqlMemoryStore(database)


def _in(mode: str, family: str, name: str, skin: scenes.Skin) -> harness.Scenario:
    found = next(s for s in catalog.FAMILIES[family](skin) if s.name == name)
    return dataclasses.replace(found, mode=mode)


_MODES = pytest.mark.parametrize("mode", catalog.modes())


def _with(env: harness.EvalEnv, memory: apmemory.AgentMemory) -> harness.EvalEnv:
    return dataclasses.replace(env, memory=memory)


@_MODES
@pytest.mark.parametrize("skin", scenes.SKINS, ids=[s.name for s in scenes.SKINS])
def test_recalled_plan_does_not_cost_turns(
    tmp_path: pathlib.Path,
    eval_env: harness.EvalEnv,
    skin: scenes.Skin,
    mode: str,
) -> None:
    scenario = _in(mode, "multistep", "transfer_flow", skin)
    seeded = apmemory.AgentMemory(_store())
    seeded.record_plan(
        "evalapp",
        scenario.goal,
        mdplan.Plan(
            subgoals=[
                mdplan.Subgoal(
                    id="s1", description="sign in", success_criteria="home"
                ),
                mdplan.Subgoal(
                    id="s2",
                    description=f"open {skin.mutate}, fill and submit the form",
                    success_criteria="confirmation number shown",
                    expected_outputs=["confirmation"],
                ),
            ],
            credential_names=["username", "password"],
        ),
        safe=lambda s: s,
    )
    turns = {}
    for label, memory in (
        ("without", apmemory.AgentMemory(_store())),
        ("with", seeded),
    ):
        runs = [
            harness.run_scenario(
                tmp_path / f"{label}-{trial}", _with(eval_env, memory), scenario
            )
            for trial in range(_TRIALS)
        ]
        turns[label] = statistics.mean(len(run.llm.turns) for run in runs)
        passed = sum(1 for run in runs if run.succeeded)
        print(
            f"\nMEMORY {mode} {skin.name} {label}: "
            f"{turns[label]:.1f} turns, {passed}/{_TRIALS} completed"
        )
    assert turns["with"] <= turns["without"], turns


@_MODES
@pytest.mark.parametrize("skin", scenes.SKINS, ids=[s.name for s in scenes.SKINS])
def test_stale_memory_loses_to_the_screen(
    tmp_path: pathlib.Path,
    eval_env: harness.EvalEnv,
    skin: scenes.Skin,
    mode: str,
) -> None:
    scenario = _in(mode, "auth", "already_logged_in", skin)
    memory = apmemory.AgentMemory(_store())
    memory.record_plan(
        "evalapp",
        scenario.goal,
        mdplan.Plan(
            subgoals=[
                mdplan.Subgoal(
                    id="s1", description="log in first", success_criteria="home"
                ),
                mdplan.Subgoal(
                    id="s2", description="read the value", success_criteria="read"
                ),
            ],
            credential_names=["username", "password"],
        ),
        safe=lambda s: s,
    )
    harness.run_trials(tmp_path, _with(eval_env, memory), scenario)


@pytest.mark.parametrize("skin", scenes.SKINS, ids=[s.name for s in scenes.SKINS])
def test_memory_keeps_no_values(
    tmp_path: pathlib.Path, eval_env: harness.EvalEnv, skin: scenes.Skin
) -> None:
    store = _store()
    scenario = _in("multi", "multistep", "transfer_flow", skin)
    harness.run_scenario(
        tmp_path, _with(eval_env, apmemory.AgentMemory(store)), scenario
    )
    stored = " ".join(store.all_text())
    assert scenes.SECRET_VALUE not in stored
    assert skin.record_id not in stored
