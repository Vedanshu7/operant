"""
``operant discover`` - an LLM-driven discovery run.
"""

from __future__ import annotations

from typing import Annotated, List, Optional, Union

import typer

import operant.adapters.hitl.tty as tty
import operant.adapters.llm.litellm_client as litecli
import operant.application.approval as approval
import operant.application.context as context
import operant.application.discovery.config as config
import operant.application.usecases.discover as uddiscov
import operant.cli.deps as cddeps
import operant.domain.errors as errors
import operant.ports.hitl as hitl


def register(app: typer.Typer) -> None:
    """
    Register the ``discover`` command.
    """

    @app.command()
    def discover(
        ctx: typer.Context,
        goal: Annotated[str, typer.Option("--goal")],
        capability: Annotated[str, typer.Option("--capability")],
        name: Annotated[str, typer.Option("--name")] = "",
        profile: Annotated[
            str, typer.Option("--profile", help="omit to bootstrap a vendor")
        ] = "",
        tenant: Annotated[str, typer.Option("--tenant")] = "",
        input: Annotated[
            List[str], typer.Option("--input", help="key=value pre-seed")
        ] = [],
        no_screenshots: Annotated[bool, typer.Option("--no-screenshots")] = False,
        max_turns: Annotated[
            Optional[int],
            typer.Option("--max-turns", help="override the turn budget"),
        ] = None,
    ) -> None:
        """
        Discover a capability for ``goal`` and commit it.
        """
        deps: cddeps.CliDeps = ctx.obj
        try:
            llm = litecli.LiteLlmClient(deps.settings.discovery)
        except errors.ConfigError as err:
            typer.echo(f"  {err}", err=True)
            raise typer.Exit(1) from err
        request = uddiscov.DiscoverRequest(
            goal=goal,
            capability_id=capability,
            name=name,
            profile_id=profile or None,
            tenant=tenant,
            inputs=context.parse_inputs(input),
            screenshots=not no_screenshots,
            max_turns=max_turns,
        )
        outcome = uddiscov.execute_discovery(
            request,
            factory=deps.run_factory(),
            artifacts=deps.artifacts,
            graphs=deps.graphs,
            profiles=deps.profiles,
            llm=llm,
            secret_store=deps.secret_store,
            model_name=deps.settings.discovery.model or "",
            clarifier=tty.TtyClarifier(),
            approver=_approver(deps),
            credential_requester=tty.TtyCredentialRequester(),
        )
        _report(outcome)


def _approver(deps: cddeps.CliDeps) -> hitl.Approver:
    """
    Build the approver, remembering answers across a discovery run.
    """
    import sys

    # Approve on the terminal when attended, deny every request when not.
    timeout = deps.settings.approval.timeout_s
    inner: hitl.Approver = (
        tty.TtyApprover(timeout)
        if sys.stdin.isatty()
        else approval.DenyAllApprover()
    )
    approver = approval.RememberingApprover(inner, cache={})
    return approver


def _report(
    outcome: Union[uddiscov.DiscoverOutcome, config.DiscoveryFailure],
) -> None:
    """
    Print the discovery outcome; exit non-zero on failure.
    """
    if isinstance(outcome, config.DiscoveryFailure):
        typer.echo(f"  discovery failed: {outcome.reason}", err=True)
        raise typer.Exit(1)
    cap = outcome.capability
    typer.echo(
        f"  committed {cap.id} v{cap.version} on graph "
        f"{cap.vendor_id} v{cap.graph_version}"
    )
    typer.echo(f"  profile: {outcome.profile_path}")
    typer.echo(f"  replay: operant replay {cap.id}")
