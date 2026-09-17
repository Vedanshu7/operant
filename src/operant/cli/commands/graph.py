"""
``operant graph`` - inspect versioned app graphs.
"""

from __future__ import annotations

from typing import Annotated, List

import typer

import operant.application.drift as apdrift
import operant.cli.deps as cddeps
import operant.domain.errors as errors
import operant.domain.graph.drift as ogdrift


def register(app: typer.Typer) -> None:
    """
    Register the ``graph`` command group.
    """
    graph = typer.Typer(help="Inspect versioned app graphs.")
    app.add_typer(graph, name="graph")

    @graph.command("list")
    def list_graphs(ctx: typer.Context) -> None:
        """
        List every vendor graph and its current version.
        """
        deps: cddeps.CliDeps = ctx.obj
        for vendor in deps.graphs.vendors():
            versions = deps.graphs.versions(vendor)
            head = deps.graphs.head(vendor)
            typer.echo(f"  {vendor}: v{head} (versions {versions})")

    @graph.command("learn")
    def learn(ctx: typer.Context, vendor: str) -> None:
        """
        Save a new version with stable cores from verified replays.
        """
        deps: cddeps.CliDeps = ctx.obj
        try:
            learned = apdrift.learn(
                vendor, deps.settings.paths.evidence_dir, deps.graphs
            )
        except errors.NotFoundError as err:
            raise typer.BadParameter(str(err)) from err
        if learned is None:
            typer.echo(f"  {vendor}: nothing to learn yet")
        else:
            typer.echo(
                f"  {vendor}: saved v{learned.graph_version}; capabilities stay "
                "pinned until you run `operant catalog repin`"
            )

    @graph.command("retire")
    def retire(ctx: typer.Context, vendor: str, edges: List[str]) -> None:
        """
        Save a new version with edges that no longer belong retired.
        """
        deps: cddeps.CliDeps = ctx.obj
        try:
            updated = ogdrift.retire(deps.graphs.get(vendor), set(edges))
        except errors.NotFoundError as err:
            raise typer.BadParameter(str(err)) from err
        saved = deps.graphs.save_new_version(updated)
        typer.echo(f"  {vendor}: saved v{saved.graph_version}")

    @graph.command("show")
    def show(
        ctx: typer.Context,
        vendor: str,
        version: Annotated[int, typer.Option("--version")] = 0,
    ) -> None:
        """
        Print a graph version's nodes and edges.
        """
        deps: cddeps.CliDeps = ctx.obj
        try:
            model = deps.graphs.get(vendor, version or None)
        except errors.NotFoundError as err:
            raise typer.BadParameter(str(err)) from err
        typer.echo(f"# {model.vendor_id} v{model.graph_version}")
        typer.echo(f"  app: {model.app_name!r}")
        typer.echo(f"  nodes ({len(model.nodes)}):")
        for node in model.nodes:
            typer.echo(f"    {node.id}: {node.description}")
        typer.echo(f"  edges ({len(model.edges)}):")
        for edge in model.edges:
            typer.echo(
                f"    {edge.id} [{edge.risk}] {edge.from_node} -> "
                f"{edge.to_node}: {edge.action.kind}"
            )
