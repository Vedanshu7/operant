"""
``operant evidence`` - manage stored run evidence.
"""

from __future__ import annotations

import time
from typing import Annotated, Optional

import typer

import operant.application.retention as apretent
import operant.cli.deps as cddeps


def register(app: typer.Typer) -> None:
    """
    Register the ``evidence`` command group.
    """
    evidence = typer.Typer(help="Manage stored run evidence.")
    app.add_typer(evidence, name="evidence")

    @evidence.command("prune")
    def prune(
        ctx: typer.Context,
        days: Annotated[
            Optional[float],
            typer.Option("--days", help="Override the retention setting."),
        ] = None,
        dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    ) -> None:
        """
        Delete evidence runs older than the retention period.
        """
        deps: cddeps.CliDeps = ctx.obj
        max_age = (
            days
            if days is not None
            else deps.settings.privacy.evidence_retention_days
        )
        if max_age is None:
            typer.echo(
                "  no retention period: set "
                "OPERANT_PRIVACY__EVIDENCE_RETENTION_DAYS or pass --days",
                err=True,
            )
            raise typer.Exit(1)
        evidence_dir = deps.settings.paths.evidence_dir
        expired = (
            apretent.expired_runs(
                evidence_dir, max_age_days=max_age, now=time.time()
            )
            if evidence_dir.exists()
            else []
        )
        for run_dir in expired:
            typer.echo(
                f"  {'would delete' if dry_run else 'deleting'} {run_dir.name}"
            )
        if not dry_run:
            apretent.delete_runs(expired)
        typer.echo(f"  {len(expired)} run(s) older than {max_age:g} days")
