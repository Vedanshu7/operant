"""
``operant migrate`` - bring data and the database up to the current layout.

Runs the database migrations to HEAD, moves any flat
``artifacts/<id>.json`` into the versioned ``artifacts/<id>/`` layout,
and canonicalises profile secret references to the
``<backend>:<locator>`` grammar. Idempotent; ``--dry-run`` reports
without writing.
"""

from __future__ import annotations

from typing import Annotated, Dict, Optional

import typer

import operant.cli.deps as cddeps
import operant.domain.models.artifact as maartifa
import operant.domain.profile as profile
import operant.domain.secrets as secrets
import operant.helpers.files as files


def register(app: typer.Typer) -> None:
    """
    Register the ``migrate`` command.
    """

    @app.command()
    def migrate(
        ctx: typer.Context,
        dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    ) -> None:
        """
        Apply DB migrations and moves flat artifacts to the new layout.
        """
        deps: cddeps.CliDeps = ctx.obj
        if not dry_run:
            # Live run: apply the database migrations to head.
            database, _ = deps.open_runs()
            database.close()
            typer.echo("  database migrated to head")
        else:
            # Dry run: report the database step, write nothing.
            typer.echo("  [dry-run] would migrate the database to head")
        _migrate_artifacts(deps, dry_run=dry_run)
        _migrate_profiles(deps, dry_run=dry_run)


def _migrate_profiles(deps: cddeps.CliDeps, *, dry_run: bool) -> None:
    """
    Canonicalise the secret references in every stored profile.
    """
    for profile_id in deps.profiles.ids():
        document = deps.profiles.get(profile_id)
        migrated = _canonicalise_secret_refs(document)
        if migrated is None:
            continue
        if dry_run:
            typer.echo(f"  [dry-run] would canonicalise secrets: {profile_id}")
            continue
        deps.profiles.save(migrated)
        typer.echo(f"  canonicalised secret refs in {profile_id}")


def _canonicalise_secret_refs(
    document: profile.AppProfile,
) -> Optional[profile.AppProfile]:
    """
    Rewrite a profile's secret refs to canonical form, if changed.
    """
    changed = False
    tenants: Dict[str, maartifa.TenantBinding] = {}
    for name, binding in document.tenants.items():
        refs = {
            ref: str(secrets.SecretRef.parse(locator))
            for ref, locator in binding.secret_refs.items()
        }
        if refs != binding.secret_refs:
            changed = True
        tenants[name] = binding.model_copy(update={"secret_refs": refs})
    migrated = (
        document.model_copy(update={"tenants": tenants}) if changed else None
    )
    return migrated


def _migrate_artifacts(deps: cddeps.CliDeps, *, dry_run: bool) -> None:
    """
    Move flat ``artifacts/<id>.json`` files to the versioned layout.
    """
    root = deps.settings.paths.artifacts_dir
    if not root.exists():
        return
    for path in sorted(root.glob("*.json")):
        artifact = files.read_model(path, maartifa.CapabilityArtifact)
        if (root / artifact.id / "HEAD").exists():
            continue
        if dry_run:
            typer.echo(f"  [dry-run] would version {path.name}")
            continue
        deps.artifacts.save_new_version(artifact)
        path.rename(path.with_suffix(".json.migrated"))
        typer.echo(f"  versioned {artifact.id} (was {path.name})")
