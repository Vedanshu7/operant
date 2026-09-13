"""
``operant audit`` - invariant checks over artifacts, graphs, evidence.
"""

from __future__ import annotations

from typing import Annotated

import typer

import operant.application.audit as aaaudit
import operant.cli.deps as cddeps
import operant.infra.repositories.memory as rmmemory


def register(app: typer.Typer) -> None:
    """
    Register the ``audit`` command.
    """

    @app.command()
    def audit(
        ctx: typer.Context,
        strict: Annotated[bool, typer.Option("--strict")] = False,
        evidence: Annotated[bool, typer.Option("--evidence")] = False,
    ) -> None:
        """
        Report findings; exits non-zero on an error under ``--strict``.
        """
        deps: cddeps.CliDeps = ctx.obj
        database, runs = deps.open_runs()
        try:
            findings = aaaudit.audit_all(
                deps.artifacts,
                deps.graphs,
                deps.settings.paths.evidence_dir if evidence else None,
                stability_of=lambda capability_id: runs.stability(
                    capability_id, window=deps.settings.governance.window
                ),
                gate=deps.settings.governance.gate(),
                memory_text=rmmemory.SqlMemoryStore(database).all_text(),
            )
        finally:
            database.close()
        errors = 0
        for finding in findings:
            typer.echo(
                f"  {finding.severity.upper():7} [{finding.code}] "
                f"{finding.subject}: {finding.message}"
            )
            errors += finding.severity == "error"
        typer.echo(f"\n  {errors} error(s), {len(findings) - errors} warning(s)")
        if strict and errors:
            raise typer.Exit(1)
