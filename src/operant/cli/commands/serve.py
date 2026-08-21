"""
``operant serve`` - the operator web server (API + UI).
"""

from __future__ import annotations

from typing import Annotated

import typer

import operant.cli.deps as cddeps


def register(app: typer.Typer) -> None:
    """
    Register the ``serve`` command.
    """

    @app.command()
    def serve(
        ctx: typer.Context,
        host: Annotated[str, typer.Option("--host")] = "",
        port: Annotated[int, typer.Option("--port")] = 0,
    ) -> None:
        """
        Run the FastAPI server that drives runs and answers approvals.
        """
        deps: cddeps.CliDeps = ctx.obj
        settings = deps.settings
        if host:
            settings.server.host = host
        if port:
            settings.server.port = port
        import operant.server.runner as runner

        # Hand off to the web server runner.
        runner.run(settings)
