"""
``operant catalog`` - list, approve, invoke, and canary capabilities.
"""

from __future__ import annotations

import sys
from typing import Annotated, List, Optional

import typer

import operant.application.canary as apcanary
import operant.application.capabilities as apcapab
import operant.application.stability as apstabil
import operant.application.usecases.replay as replay
import operant.cli.deps as cddeps
import operant.domain.errors as errors
import operant.domain.models.artifact as artifact
import operant.domain.models.graph as graph
import operant.helpers.ids as ids

# Below this share of named targets, approval warns that it is brittle.
_BRITTLE_BELOW = 0.7


def _confirm_steps(steps: List[graph.Edge], *, yes: bool) -> None:
    """
    Show the unknown steps and require a person to accept them.
    """
    for step in steps:
        verdict = f" (judge: {step.judged})" if step.judged else ""
        typer.echo(f"  unknown step: {step.description}{verdict}")
    if steps and not yes:
        if not sys.stdin.isatty():
            typer.echo("  pass --yes to accept these steps", err=True)
            raise typer.Exit(1)
        typer.confirm("  Have you reviewed these steps?", abort=True)


def register(app: typer.Typer) -> None:
    """
    Register the ``catalog`` command group.
    """
    catalog = typer.Typer(help="Agent-facing capability catalog.")
    app.add_typer(catalog, name="catalog")

    @catalog.command("list")
    def list_capabilities(ctx: typer.Context) -> None:
        """
        List every saved capability with its stability and contract.
        """
        deps: cddeps.CliDeps = ctx.obj
        database, runs = deps.open_runs()
        try:
            for capability in deps.artifacts.list():
                stability = runs.stability(
                    capability.id, window=deps.settings.governance.window
                )
                inputs = ", ".join(
                    f"{k}: {v.type}" for k, v in capability.inputs.items()
                )
                outputs = ", ".join(
                    f"{k}: {v.type}" for k, v in capability.outputs.items()
                )
                typer.echo(
                    f"  {capability.id} v{capability.version} [{capability.status}] | stability "
                    f"{stability.successes}/{stability.runs}"
                )
                typer.echo(f"    {capability.description}")
                typer.echo(
                    f"    inputs: ({inputs or 'none'}) -> "
                    f"outputs: ({outputs or 'none'})"
                )
                if (
                    capability.accessibility is not None
                    and capability.accessibility.steps
                ):
                    typer.echo(f"    {_accessibility(capability.accessibility)}")
        finally:
            database.close()

    @catalog.command("approve")
    def approve(
        ctx: typer.Context,
        capability_id: str,
        force: Annotated[bool, typer.Option("--force")] = False,
        yes: Annotated[
            bool, typer.Option("--yes", help="accept the listed unknown steps")
        ] = False,
    ) -> None:
        """
        Approve a capability if the stability gate passes (or forced).

        The unknown steps are listed first: approving is their review.
        """
        deps: cddeps.CliDeps = ctx.obj
        database, runs = deps.open_runs()
        try:
            gate = deps.settings.governance.gate()
            stability = runs.stability(capability_id, window=gate.window)
            if not force and not gate.passes(stability.runs, stability.successes):
                typer.echo(
                    f"  refusing to approve {capability_id!r}: "
                    f"{gate.describe(stability.runs, stability.successes)} "
                    "- prove it first or pass --force",
                    err=True,
                )
                raise typer.Exit(1)
            outstanding = apcapab.outstanding_steps(
                deps.artifacts.get(capability_id), deps.graphs, runs.edge_records
            )
            _confirm_steps(outstanding, yes=yes)
            approved = deps.artifacts.approve(capability_id)
            apcapab.review_unknown_steps(
                approved, deps.graphs, runs.edge_records, by="catalog approve"
            )
        finally:
            database.close()
        found = approved.accessibility
        score = found.score if found is not None else None
        if found is not None and score is not None and score < _BRITTLE_BELOW:
            typer.echo(
                f"  warning: {_accessibility(found)} - it depends on screen "
                "positions and will break when the layout changes",
                err=True,
            )
        typer.echo(f"{approved.id} v{approved.version} is now: {approved.status}")

    @catalog.command("repin")
    def repin(
        ctx: typer.Context,
        capability_id: str,
        version: Annotated[
            Optional[int],
            typer.Option("--version", help="graph version; default newest"),
        ] = None,
    ) -> None:
        """
        Move a capability to another graph version, as a draft.
        """
        deps: cddeps.CliDeps = ctx.obj
        database, runs = deps.open_runs()
        try:
            moved = apcapab.repin(
                deps.artifacts.get(capability_id),
                graph_store=deps.graphs,
                artifact_store=deps.artifacts,
                run_repo=runs,
                by="catalog repin",
                version=version,
            )
        except errors.RepinRefusedError as err:
            typer.echo(f"  {err}", err=True)
            raise typer.Exit(1) from err
        finally:
            database.close()
        typer.echo(
            f"{moved.id} v{moved.version} is on graph v{moved.graph_version} "
            f"({moved.status}); replay and approve it to run unattended"
        )

    @catalog.command("invoke")
    def invoke(
        ctx: typer.Context,
        capability_id: str,
        tenant: Annotated[str, typer.Option("--tenant")] = "",
        input: Annotated[
            List[str], typer.Option("--input", help="key=value")
        ] = [],
        force_draft: Annotated[bool, typer.Option("--force-draft")] = False,
    ) -> None:
        """
        Invoke an approved capability (a replay by another name).
        """
        deps: cddeps.CliDeps = ctx.obj
        capability = deps.artifacts.get(capability_id)
        if capability.status != "approved" and not force_draft:
            typer.echo(
                f'Refusing to invoke draft capability "{capability_id}" '
                "unattended. Approve it or pass --force-draft.",
                err=True,
            )
            raise typer.Exit(1)
        import operant.application.context as context

        # Replay the capability and report its outcome.
        database, runs = deps.open_runs()
        try:
            result = replay.execute_replay(
                replay.ReplayRequest(
                    capability_id=capability_id,
                    tenant=tenant,
                    inputs=context.parse_inputs(input),
                ),
                factory=deps.run_factory(),
                artifacts=deps.artifacts,
                graphs=deps.graphs,
                profiles=deps.profiles,
                edge_records=runs.edge_records,
            )
        finally:
            database.close()
        typer.echo(result.model_dump_json(indent=2))
        raise typer.Exit(0 if result.status != "failure" else 1)

    @catalog.command("canary")
    def canary(ctx: typer.Context) -> None:
        """
        Replay every approved read-only capability once, for a schedule.

        Each result counts toward the stability gate, so a capability
        whose application changed is degraded before anyone needs it.
        Exits non-zero when any canary failed.
        """
        deps: cddeps.CliDeps = ctx.obj
        database, runs = deps.open_runs()
        failed = 0
        try:
            for planned in apcanary.plan_canaries(deps.artifacts, runs):
                if planned.inputs is None:
                    # Nothing safe to replay it with: report why.
                    typer.echo(
                        f"  {planned.capability_id}: skipped ({planned.skipped})"
                    )
                    continue
                result = replay.execute_replay(
                    replay.ReplayRequest(
                        capability_id=planned.capability_id,
                        tenant="",
                        inputs=planned.inputs,
                    ),
                    factory=deps.run_factory(),
                    artifacts=deps.artifacts,
                    graphs=deps.graphs,
                    profiles=deps.profiles,
                    edge_records=runs.edge_records,
                )
                ok = replay.is_success(result)
                gate = deps.settings.governance.gate()
                stability = (
                    apstabil.record_replay(
                        planned.capability_id,
                        ids.run_id("canary"),
                        succeeded=replay.is_stable(result),
                        run_repo=runs,
                        artifact_repo=deps.artifacts,
                        gate=gate,
                    )
                    if replay.counts_toward_stability(result)
                    else runs.stability(planned.capability_id, window=gate.window)
                )
                failed += not ok
                status = deps.artifacts.get(planned.capability_id).status
                typer.echo(
                    f"  {planned.capability_id}: {result.status} "
                    f"(recent {stability.successes}/{stability.runs}, {status})"
                )
        finally:
            database.close()
        raise typer.Exit(1 if failed else 0)


def _accessibility(found: artifact.Accessibility) -> str:
    """
    Describe how a capability's steps locate their targets.
    """
    return (
        f"accessibility {100 * (found.score or 0):.0f}%: "
        f"{found.coordinate_steps} of {found.steps} steps by screen position, "
        f"{found.unnamed_steps} on unnamed controls"
    )
