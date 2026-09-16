"""
``operant memory`` - see and forget what runs taught the agents.
"""

from __future__ import annotations

import datetime
from typing import Annotated, Any, Dict, List, Literal, Optional

import typer

import operant.application.gateway.learner as gllearne
import operant.application.memory as apmemory
import operant.application.remediation as remem
import operant.cli.deps as cddeps
import operant.infra.repositories.learned_tools as learned_
import operant.infra.repositories.memory as rmmemory
import operant.infra.repositories.remediations as rgremed

AppOption = Annotated[
    Optional[str],
    typer.Option("--app", help="A vendor id (plans, lessons) or OS app name."),
]


def register(app: typer.Typer) -> None:
    """
    Register the ``memory`` command group.
    """
    memory = typer.Typer(help="See and forget what runs taught the agents.")
    app.add_typer(memory, name="memory")

    @memory.command("list")
    def list_(ctx: typer.Context, app_name: AppOption = None) -> None:
        """
        Show plans, lessons, learned tools, and remedies.
        """
        deps: cddeps.CliDeps = ctx.obj
        database, _ = deps.open_runs()
        try:
            view = apmemory.summary(
                apmemory.AgentMemory(rmmemory.SqlMemoryStore(database)),
                learned=_learner(deps).entries(),
                remedies=_remedies(deps).entries(),
                app=app_name,
            )
        finally:
            database.close()
        _print(view)

    @memory.command("forget")
    def forget(
        ctx: typer.Context,
        app_name: Annotated[str, typer.Option("--app")],
        plans: Annotated[bool, typer.Option("--plans")] = False,
        lessons: Annotated[bool, typer.Option("--lessons")] = False,
        tools: Annotated[bool, typer.Option("--tools")] = False,
        remedies: Annotated[bool, typer.Option("--remedies")] = False,
    ) -> None:
        """
        Delete one app's memory; every kind unless some are named.
        """
        deps: cddeps.CliDeps = ctx.obj
        every = not (plans or lessons or tools or remedies)
        removed = (0, 0)
        if every or plans or lessons:
            database, _ = deps.open_runs()
            try:
                removed = apmemory.AgentMemory(
                    rmmemory.SqlMemoryStore(database)
                ).forget(app_name, _kinds(every, plans, lessons))
            finally:
                database.close()
        tools_removed = _learner(deps).forget(app_name) if every or tools else 0
        remedies_removed = (
            _remedies(deps).forget(app_name) if every or remedies else 0
        )
        typer.echo(
            f"  removed {removed[0]} plan(s), {removed[1]} lesson(s), "
            f"{tools_removed} learned tool key(s), {remedies_removed} remedy(ies)"
        )

    @memory.command("prune")
    def prune(ctx: typer.Context) -> None:
        """
        Delete failing or stale plans and long-unreinforced lessons.
        """
        deps: cddeps.CliDeps = ctx.obj
        database, _ = deps.open_runs()
        try:
            agent_memory = apmemory.AgentMemory(rmmemory.SqlMemoryStore(database))
            for vendor in agent_memory.vendors():
                plans, lessons = agent_memory.prune(vendor)
                typer.echo(
                    f"  {vendor}: removed {plans} plan(s), {lessons} lesson(s)"
                )
        finally:
            database.close()


def _learner(deps: cddeps.CliDeps) -> gllearne.ToolLearner:
    """
    Open the tool learner over its file.
    """
    return gllearne.ToolLearner(
        learned_.LearnedToolsStore(deps.settings.paths.learned_tools)
    )


def _remedies(deps: cddeps.CliDeps) -> remem.RemediationMemory:
    """
    Open the remediation memory over its file.
    """
    return remem.RemediationMemory(
        rgremed.RemediationsStore(deps.settings.paths.remediations)
    )


def _print(view: Dict[str, List[Dict[str, Any]]]) -> None:
    """
    Print the memory summary, one section per kind.
    """
    typer.echo(f"Plans ({len(view['plans'])})")
    for plan in view["plans"]:
        typer.echo(
            f"  {plan['vendor_id']}: '{plan['goal_text']}' - "
            f"{plan['successes']} ok / {plan['failures']} failed, "
            f"graph v{plan['graph_version']}, last worked "
            f"{_days(plan['last_used_at'])}"
        )
    typer.echo(f"Lessons ({len(view['lessons'])})")
    for lesson in view["lessons"]:
        typer.echo(
            f"  {lesson['vendor_id']} [{lesson['source']}"
            f"{', ' + lesson['failure_kind'] if lesson['failure_kind'] else ''}"
            f", x{lesson['reinforcements']}]: {lesson['lesson']}"
        )
    typer.echo(f"Learned tools ({len(view['tools'])})")
    for entry in view["tools"]:
        counts = ", ".join(
            f"{tool} {ok}/{ok + failed}"
            for tool, (ok, failed) in entry["tools"].items()
        )
        typer.echo(f"  {entry['signature']}: {counts}")
    typer.echo(f"Remedies ({len(view['remedies'])})")
    for remedy in view["remedies"]:
        typer.echo(
            f"  {remedy['key']}: {remedy['hint']} "
            f"({remedy['success']}/{remedy['applied']} worked)"
        )


def _days(iso: str) -> str:
    """
    Render an ISO time as "N days ago".
    """
    try:
        then = datetime.datetime.fromisoformat(iso)
    except ValueError:
        return "unknown"
    if then.tzinfo is None:
        then = then.replace(tzinfo=datetime.timezone.utc)
    days = (datetime.datetime.now(datetime.timezone.utc) - then).days
    return f"{days} day(s) ago"


def _kinds(
    every: bool, plans: bool, lessons: bool
) -> Literal["plans", "lessons", "all"]:
    """
    Name the agent-memory kinds a ``forget`` covers.
    """
    if every or (plans and lessons):
        kinds: Literal["plans", "lessons", "all"] = "all"
    elif plans:
        kinds = "plans"
    else:
        kinds = "lessons"
    return kinds
