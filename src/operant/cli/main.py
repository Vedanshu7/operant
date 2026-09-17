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
    # Check the environment, permissions and tools.
    "doctor",
    # Start the operator web server (API and UI).
    "serve",
    # Start the macOS driver daemon that performs the actions.
    "serve_driver",
    # Run the LLM on a goal and save a capability.
    "discover",
    # Replay a saved capability with no LLM.
    "replay",
    # List, approve, invoke and canary capabilities.
    "catalog",
    # Check invariants over artifacts, graphs and evidence.
    "audit",
    # Inspect the versioned app graphs.
    "graph",
    # Prune stored run evidence.
    "evidence",
    # List or forget what runs taught the agents.
    "memory",
    # Bring data and the database up to the current layout.
    "migrate",
    # Start or stop the Docker containers.
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
    Import each command module and register it on ``app``.
    """
    for name in _COMMAND_MODULES:
        module = importlib.import_module(f"operant.cli.commands.{name}")
        module.register(app)


def main() -> None:
    """
    Console-script entry point.
    """
    app()


_register_commands()
