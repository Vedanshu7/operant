"""
``operant replay`` - deterministic replay of a saved capability.
"""

from __future__ import annotations

from typing import Annotated, Dict, List, Optional

import typer

import operant.adapters.hitl.tty as tty
import operant.application.approval as approval
import operant.application.usecases.replay as urreplay
import operant.cli.deps as cddeps
import operant.ports.hitl as hitl

_TERMINAL_FAILURE = 1
_TERMINAL_ESCALATED = 2


def register(app: typer.Typer) -> None:
    """
    Register the ``replay`` command.
    """

    @app.command()
    def replay(
        ctx: typer.Context,
        capability_id: str,
        tenant: Annotated[str, typer.Option("--tenant")] = "",
        input: Annotated[
            List[str], typer.Option("--input", help="key=value")
        ] = [],
        times: Annotated[int, typer.Option("--times")] = 1,
        fresh_session: Annotated[bool, typer.Option("--fresh-session")] = False,
        inject: Annotated[
            str, typer.Option("--inject", help="session-expired:<edge-id>")
        ] = "",
    ) -> None:
        """
        Replay a capability, optionally several times for stability.
        """
        deps: cddeps.CliDeps = ctx.obj
        if inject and not inject.startswith("session-expired:"):
            raise typer.BadParameter("--inject must be session-expired:<edge>")
        _run(
            deps,
            capability_id,
            tenant=tenant,
            inputs=_parse(input),
            times=times,
            fresh_session=fresh_session,
            inject=inject.removeprefix("session-expired:") or None,
        )


def _run(
    deps: cddeps.CliDeps,
    capability_id: str,
    *,
    tenant: str,
    inputs: Dict[str, str],
    times: int,
    fresh_session: bool,
    inject: Optional[str],
) -> None:
    """
    Replay a capability ``times`` over and record its stability.
    """
    database, run_repo = deps.open_runs()
    approver = _cli_approver(deps)
    successes = 0
    last_status = "failure"
    try:
        for i in range(times):
            if times > 1:
                typer.echo(f"\n--- replay {i + 1}/{times} ---")
            if fresh_session:
                _fresh_session(deps)
            request = urreplay.ReplayRequest(
                capability_id=capability_id,
                tenant=tenant,
                inputs=inputs,
                inject_session_expiry_before=inject,
            )
            result = urreplay.execute_replay(
                request,
                factory=deps.run_factory(),
                artifacts=deps.artifacts,
                graphs=deps.graphs,
                profiles=deps.profiles,
                approver=approver,
            )
            ok = urreplay.is_success(result)
            successes += ok
            last_status = result.status
            run_repo.record_stability(capability_id, "cli", succeeded=ok)
            typer.echo("\n=== REPLAY RESULT ===")
            typer.echo(result.model_dump_json(indent=2))
        if times > 1:
            rate = 100 * successes // times
            typer.echo(f"\nStability: {successes}/{times} ({rate}%)")
    finally:
        database.close()
    raise typer.Exit(_exit_code(last_status))


def _cli_approver(deps: cddeps.CliDeps) -> hitl.Approver:
    """
    Build the approver, remembering answers across a replay run.
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


def _fresh_session(deps: cddeps.CliDeps) -> None:
    """
    Quit the automation browser and wipe its dedicated profile.
    """
    import operant.adapters.macos.tools.launcher as launcher

    # Reset the dedicated automation browser and wipe its profile.
    found = launcher.AppLauncher.reset_dedicated_chrome(
        deps.settings.paths.chrome_profile_dir
    )
    state = "quit" if found else "not running"
    typer.echo(f"  fresh session: automation browser {state}, profile wiped")


def _parse(pairs: List[str]) -> Dict[str, str]:
    """
    Parse ``key=value`` pairs, raising a typer error on bad input.
    """
    import operant.application.context as context

    # Parse the pairs, surfacing bad input as a CLI error.
    try:
        parsed = context.parse_inputs(pairs)
    except ValueError as err:
        raise typer.BadParameter(str(err)) from err
    return parsed


def _exit_code(status: str) -> int:
    """
    Map a terminal run status to a process exit code.
    """
    if status == "escalated":
        # Handed to a human: its own exit code.
        code = _TERMINAL_ESCALATED
    elif status == "failure":
        # Replay failed outright.
        code = _TERMINAL_FAILURE
    else:
        # Anything else counts as success.
        code = 0
    return code
