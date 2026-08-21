"""
``operant catalog`` - list, describe, approve, and invoke capabilities.
"""

from __future__ import annotations

from typing import Annotated, List

import typer

import operant.application.usecases.replay as replay
import operant.cli.deps as cddeps
import operant.domain.governance as govern


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
            for cap in deps.artifacts.list():
                stability = runs.stability(cap.id)
                inputs = ", ".join(
                    f"{k}: {v.type}" for k, v in cap.inputs.items()
                )
                outputs = ", ".join(
                    f"{k}: {v.type}" for k, v in cap.outputs.items()
                )
                typer.echo(
                    f"  {cap.id} v{cap.version} [{cap.status}] | stability "
                    f"{stability.successes}/{stability.runs}"
                )
                typer.echo(f"    {cap.description}")
                typer.echo(
                    f"    inputs: ({inputs or 'none'}) -> "
                    f"outputs: ({outputs or 'none'})"
                )
        finally:
            database.close()

    @catalog.command("approve")
    def approve(
        ctx: typer.Context,
        capability_id: str,
        force: Annotated[bool, typer.Option("--force")] = False,
    ) -> None:
        """
        Approve a capability if the stability gate passes (or forced).
        """
        deps: cddeps.CliDeps = ctx.obj
        database, runs = deps.open_runs()
        try:
            stability = runs.stability(capability_id)
            gate = govern.StabilityGate(
                min_runs=deps.settings.governance.min_runs,
                min_success_rate=deps.settings.governance.min_success_rate,
            )
            if not force and not gate.passes(stability.runs, stability.successes):
                typer.echo(
                    f"  refusing to approve {capability_id!r}: "
                    f"{gate.describe(stability.runs, stability.successes)} "
                    "- prove it first or pass --force",
                    err=True,
                )
                raise typer.Exit(1)
            approved = deps.artifacts.approve(capability_id)
        finally:
            database.close()
        typer.echo(f"{approved.id} v{approved.version} is now: {approved.status}")

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
        )
        typer.echo(result.model_dump_json(indent=2))
        raise typer.Exit(0 if result.status != "failure" else 1)
