"""
The ``operant`` command.

Commands live in ``operant.cli.commands``; each module exposes
``register(app)`` so this file stays a table of contents. Settings are
loaded once in the callback and handed down through ``typer.Context.obj``.

Typical usage example:

  operant doctor
  operant replay goalnative --tenant tenant-b --input accountId=12456

Import as:

import operant.cli.main as main
"""

from __future__ import annotations

import importlib
import pathlib
from typing import Annotated, Final, Optional, Tuple

import typer

import operant
import operant.cli.deps as deps
import operant.helpers.logging as logging
import operant.infra.settings as issettin

_COMMAND_MODULES: Final[Tuple[str, ...]] = (
    "doctor",
    "serve",
    "serve_driver",
    "discover",
    "replay",
    "catalog",
    "audit",
    "graph",
    "drive",
    "capture",
    "migrate",
    "up",
)

app = typer.Typer(
    name="operant",
    help="Discover a UI task once with an LLM, replay it deterministically.",
    no_args_is_help=True,
    pretty_exceptions_show_locals=False,
)


@app.callback()
def _root(
    ctx: typer.Context,
    root: Annotated[
        Optional[pathlib.Path],
        typer.Option("--root", help="Data root (default: current directory)."),
    ] = None,
    log_level: Annotated[
        Optional[str], typer.Option("--log-level", help="Logging level.")
    ] = None,
) -> None:
    """
    Load settings and logging for every subcommand.
    """
    settings = issettin.OperantSettings.load(root=root)
    logging.configure(log_level or settings.log_level, settings.server.log_format)
    ctx.obj = deps.CliDeps.build(settings)


@app.command()
def version() -> None:
    """
    Print the Operant version.
    """
    typer.echo(operant.__version__)


def _register_commands() -> None:
    """
    Import each available command module and register it on ``app``.
    """
    for name in _COMMAND_MODULES:
        try:
            module = importlib.import_module(f"operant.cli.commands.{name}")
        except ModuleNotFoundError as missing:
            if missing.name != f"operant.cli.commands.{name}":
                raise
            continue
        module.register(app)


def main() -> None:
    """
    Console-script entry point.
    """
    _register_commands()
    app()


_register_commands()
