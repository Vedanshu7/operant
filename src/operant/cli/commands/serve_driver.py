"""
``operant serve-driver`` - the macOS driver daemon (run from Terminal).
"""

from __future__ import annotations

from typing import Annotated

import typer

import operant.cli.deps as cddeps
import operant.domain.errors as errors
import operant.helpers.logging as logging


def register(app: typer.Typer) -> None:
    """
    Register the ``serve-driver`` command.
    """

    @app.command(name="serve-driver")
    def serve_driver(
        ctx: typer.Context,
        profile: Annotated[str, typer.Option("--profile")],
        host: Annotated[str, typer.Option("--host")] = "",
        port: Annotated[int, typer.Option("--port")] = 0,
    ) -> None:
        """
        Run the driver daemon; this process owns the OS permissions.
        """
        deps: cddeps.CliDeps = ctx.obj
        logging.configure(deps.settings.log_level)
        settings = deps.settings
        if host:
            settings.driver.host = host
        if port:
            settings.driver.port = port
        try:
            app_profile = deps.profiles.get(profile)
        except errors.NotFoundError as err:
            raise typer.BadParameter(str(err)) from err
        import operant.adapters.http.driver.app as daapp

        # Start the driver daemon for this profile.
        daapp.serve_driver(app_profile, settings)
