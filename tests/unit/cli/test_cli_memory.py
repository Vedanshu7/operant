"""
``operant memory``: list what runs taught the agents, and forget one app.
"""

import pathlib

import typer.testing as testing

import operant.application.gateway.learner as gllearne
import operant.application.memory as apmemory
import operant.cli.main as main
import operant.domain.models.memory as mdmemory
import operant.domain.models.plan as mdplan
import operant.infra.db.engine as engine
import operant.infra.db.migrate as migrate
import operant.infra.repositories.learned_tools as learned_
import operant.infra.repositories.memory as rmmemory

runner = testing.CliRunner()


def _seed(root: pathlib.Path) -> None:
    database = engine.Database.open(root / "state" / "operant.sqlite3")
    migrate.upgrade(database)
    memory = apmemory.AgentMemory(rmmemory.SqlMemoryStore(database))
    plan = mdplan.Plan(
        subgoals=[
            mdplan.Subgoal(id="s1", description="log in", success_criteria="ok")
        ]
    )
    for vendor in ("bank", "crm"):
        memory.record_plan(vendor, "read the balance", plan, safe=str)
    memory.record_rejection(
        "bank",
        "read the balance",
        mdmemory.Rejection("open the account", "not_done"),
        worked="",
        safe=str,
    )
    database.close()
    learner = gllearne.ToolLearner(
        learned_.LearnedToolsStore(root / "state" / "learned-tools.json")
    )
    learner.record("bank::home::click::link:#", "ax-action")


def _invoke(root: pathlib.Path, *args: str):
    return runner.invoke(main.app, ["--root", str(root), "memory", *args])


def test_list_shows_every_kind(tmp_path: pathlib.Path) -> None:
    _seed(tmp_path)
    result = _invoke(tmp_path, "list", "--app", "bank")
    assert result.exit_code == 0, result.output
    assert "Plans (1)" in result.stdout
    assert "[verifier, not_done, x1]" in result.stdout
    assert "bank::home::click::link:#: ax-action 1/1" in result.stdout


def test_forget_removes_only_that_app(tmp_path: pathlib.Path) -> None:
    _seed(tmp_path)
    result = _invoke(tmp_path, "forget", "--app", "bank")
    assert result.exit_code == 0, result.output
    assert (
        "removed 1 plan(s), 1 lesson(s), 1 learned tool key(s)" in result.stdout
    )
    listed = _invoke(tmp_path, "list").stdout
    assert "Plans (1)" in listed and "crm:" in listed
    assert "Lessons (0)" in listed
