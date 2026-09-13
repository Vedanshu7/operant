"""
Recording replays and revoking the approval of a capability that keeps failing.

A capability is approved on its track record; when the application's UI
changes under it, replays start failing. Each recorded replay checks the
recent record, and an approved capability that failed too many times in
a row is degraded: it stops replaying unattended until a person looks at
it and approves it again.

Import as:

import operant.application.stability as apstabil
"""

from __future__ import annotations

import operant.domain.governance as govern
import operant.domain.models.artifact as artifact
import operant.domain.models.runs as runs
import operant.helpers.time as time
import operant.ports.repositories as repos


def record_replay(
    capability_id: str,
    run_id: str,
    *,
    succeeded: bool,
    run_repo: repos.RunRepository,
    artifact_repo: repos.ArtifactRepository,
    gate: govern.StabilityGate,
) -> artifact.Stability:
    """
    Record one replay and degrade the capability when the gate says so.

    :param capability_id: The capability that was replayed.
    :param run_id: The replay's run id.
    :param succeeded: Whether the replay succeeded.
    :param run_repo: Where the track record and the audit trail live.
    :param artifact_repo: Where the capability's versions live.
    :param gate: The governance thresholds.
    :return: The recent track record, after this replay.
    """
    run_repo.record_stability(capability_id, run_id, succeeded=succeeded)
    stability = run_repo.stability(capability_id, window=gate.window)
    capability = artifact_repo.get(capability_id)
    if capability.status == "approved" and gate.degrades(stability):
        # Too many failures in a row: revoke the unattended approval.
        degraded = artifact_repo.save_new_version(
            capability.model_copy(update={"status": "degraded"})
        )
        run_repo.audit(
            runs.AuditEntry(
                at=time.iso_now(),
                actor="system",
                action="degrade_artifact",
                subject=capability_id,
                run_id=run_id,
                detail={
                    "version": str(degraded.version),
                    "consecutive_failures": str(stability.consecutive_failures),
                },
            )
        )
    return stability
