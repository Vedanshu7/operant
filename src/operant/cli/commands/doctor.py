"""
``operant doctor`` - environment, permission, and tool health checks.
"""

from __future__ import annotations

import collections.abc
from typing import Annotated

import typer

import operant.cli.deps as cddeps
import operant.domain.errors as errors


def register(app: typer.Typer) -> None:
    """
    Register the ``doctor`` command.
    """

    @app.command()
    def doctor(
        ctx: typer.Context,
        profile: Annotated[str, typer.Option("--profile")] = "",
    ) -> None:
        """
        Report config, permissions, and (with a profile) tool health.
        """
        deps: cddeps.CliDeps = ctx.obj
        _report_config(deps)
        if deps.settings.legacy_sources:
            typer.echo(
                "  deprecated env names in use: "
                + ", ".join(deps.settings.legacy_sources)
            )
        if profile:
            _report_profile(deps, profile)


def _check(name: str, probe: collections.abc.Callable[[], str]) -> None:
    """
    Print ``name`` with the probe result, reporting failures inline.
    """
    try:
        typer.echo(f"  {name}: {probe()}")
    # Doctor reports, never crashes.
    except Exception as err:
        typer.echo(f"  {name}: FAILED - {err}")


def _report_config(deps: cddeps.CliDeps) -> None:
    """
    Report model, driver, secrets, and database configuration.
    """
    discovery = deps.settings.discovery
    _check("discovery model", lambda: discovery.model or "NOT SET")
    _check(
        "driver",
        lambda: deps.settings.driver.url or "in-process (macOS)",
    )
    _check("secrets backend", lambda: deps.settings.secrets.backend)
    _check(
        "database",
        lambda: str(deps.settings.paths.db_path),
    )


def _report_profile(deps: cddeps.CliDeps, profile_id: str) -> None:
    """
    Report the presence of each secret referenced by a profile.
    """
    try:
        profile = deps.profiles.get(profile_id)
    except errors.NotFoundError as err:
        typer.echo(f"  profile: FAILED - {err}")
        return
    names = sorted(
        {ref for tenant in profile.tenants.values() for ref in tenant.secret_refs}
    )
    for name in names:
        _check(f"secret ref {name}", _presence_probe(deps, profile, name))


def _presence_probe(
    deps: cddeps.CliDeps, profile: object, name: str
) -> collections.abc.Callable[[], str]:
    """
    Build a zero-arg probe that reports whether a secret resolves.
    """
    probe = lambda: _secret_present(deps, profile, name)
    return probe


def _secret_present(deps: cddeps.CliDeps, profile: object, name: str) -> str:
    """
    Report ``present``, ``NOT SET``, or ``unknown`` for a secret ref.
    """
    import operant.application.secrets as secrets
    import operant.domain.redaction as redact

    # Resolve the ref through its owning tenant and report presence.
    status = "unknown"
    for tenant in profile.tenants.values():  # type: ignore[attr-defined]
        if name in tenant.secret_refs:
            resolver = secrets.SecretResolver(
                tenant, deps.secret_store, redact.Redactor()
            )
            try:
                resolver.resolve(name)
                status = "present"
            except errors.SecretNotFoundError:
                status = "NOT SET"
            break
    return status
