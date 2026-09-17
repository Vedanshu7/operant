"""
Canary planning.

Only approved, read-only capabilities with known, non-sensitive inputs
are replayed.
"""

from typing import Optional

import operant.application.canary as apcanary
import operant.domain.models.artifact as artifact
import operant.domain.models.runs as runs
import tests.support.capabilities as capab
import tests.support.ports as ports

INPUTS = {"accountId": artifact.IoField(description="account")}


def _scope(mutating: bool) -> artifact.PolicyScope:
    return artifact.PolicyScope(
        policy_id="p", required_action_kinds=[], touches_mutating_edges=mutating
    )


def _plan(**over) -> Optional[apcanary.Canary]:
    over.setdefault("status", "approved")
    over.setdefault("inputs", INPUTS)
    over.setdefault("policy_scope", _scope(False))
    artifact_repo = ports.FakeArtifactRepository()
    artifact_repo.save_new_version(capab.capability(**over))
    run_repo = ports.FakeRunRepository()
    run_repo.create(
        runs.RunRecord(
            id="r",
            kind="discovery",
            status="succeeded",
            vendor_id="app",
            inputs={"accountId": "12345"},
        )
    )
    planned = apcanary.plan_canaries(artifact_repo, run_repo)
    return planned[0] if planned else None


def test_a_read_only_capability_replays_with_its_discovery_inputs() -> None:
    planned = _plan()
    assert planned is not None
    assert planned.inputs == {"accountId": "12345"}


def test_a_capability_that_changes_data_is_never_a_canary() -> None:
    planned = _plan(policy_scope=_scope(True))
    assert planned is not None
    assert planned.inputs is None and "changes data" in planned.skipped


def test_sensitive_inputs_are_skipped() -> None:
    secret = {"pin": artifact.IoField(description="pin", sensitive=True)}
    planned = _plan(inputs=secret)
    assert planned is not None
    assert planned.inputs is None and "sensitive" in planned.skipped


def test_unknown_inputs_are_skipped() -> None:
    other = {"customerId": artifact.IoField(description="customer")}
    planned = _plan(inputs=other)
    assert planned is not None
    assert planned.inputs is None and "earlier run" in planned.skipped


def test_drafts_are_not_planned() -> None:
    assert _plan(status="draft") is None
