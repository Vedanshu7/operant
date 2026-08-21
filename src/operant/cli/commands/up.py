"""
``operant up`` / ``operant down`` - the one-command docker entry point.

``up`` starts the containers (server, UI, ParaBank), waits for the
server to report healthy, and prints the UI URL and bearer token. The
driver daemon is the only host-side process and is started separately
with ``operant serve-driver`` - macOS grants it the OS permissions the
container cannot hold.
"""

from __future__ import annotations

import subprocess
import time
import urllib.error
import urllib.request
from typing import List

import typer

import operant.adapters.http.common as common
import operant.cli.deps as cddeps
import operant.helpers.logging as logging

_LOG = logging.get_logger(__name__)


def register(app: typer.Typer) -> None:
    """
    Register the ``up`` and ``down`` commands.
    """

    @app.command()
    def up(ctx: typer.Context) -> None:
        """
        Start the stack with docker compose and prints the UI URL.
        """
        deps: cddeps.CliDeps = ctx.obj
        _compose(["up", "-d", "--build"])
        settings = deps.settings
        url = f"http://localhost:{settings.server.port}"
        if _wait_healthy(f"{url}/healthz", timeout_s=90.0):
            # Healthy: print the UI URL and bearer token.
            token = common.ensure_token(
                settings.paths.state_dir / "server-token",
                (
                    settings.server.auth_token.get_secret_value()
                    if settings.server.auth_token
                    else None
                ),
            )
            typer.echo(f"  UI:    {url}")
            typer.echo(f"  token: {token}")
            typer.echo("  driver: run `operant serve-driver --profile <id>`")
        else:
            # Never became healthy: report and exit non-zero.
            typer.echo(f"  server did not become healthy at {url}", err=True)
            raise typer.Exit(1)

    @app.command()
    def down(ctx: typer.Context) -> None:
        """
        Stop the stack.
        """
        _compose(["down"])


def _compose(args: List[str]) -> None:
    """
    Run ``docker compose`` with the given arguments.
    """
    subprocess.run(["docker", "compose", *args], check=True)


def _wait_healthy(url: str, *, timeout_s: float) -> bool:
    """
    Poll ``url`` until it returns 200 or the timeout elapses.
    """
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2.0) as response:
                if response.status == 200:
                    return True
        except (urllib.error.URLError, TimeoutError):
            pass
        time.sleep(1.0)
    return False
