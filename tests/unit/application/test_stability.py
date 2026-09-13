"""
Recording replays: an approved capability that keeps failing is degraded and
audited; a draft, or a failure streak a success breaks, is not.
"""

import operant.application.stability as apstabil
import operant.domain.governance as govern
import tests.support.capabilities as capab
import tests.support.ports as ports

GATE = govern.StabilityGate(max_consecutive_failures=3)


def _record(run_repo, artifact_repo, outcomes) -> None:
    for index, succeeded in enumerate(outcomes):
        apstabil.record_replay(
            "c",
            f"replay-{index}",
            succeeded=succeeded,
            run_repo=run_repo,
            artifact_repo=artifact_repo,
            gate=GATE,
        )


def _repos(status: str):
    run_repo = ports.FakeRunRepository()
    artifact_repo = ports.FakeArtifactRepository()
    artifact_repo.save_new_version(capab.capability(status=status))
    return run_repo, artifact_repo


def test_an_approved_capability_that_keeps_failing_is_degraded() -> None:
    run_repo, artifact_repo = _repos("approved")
    _record(run_repo, artifact_repo, [True] * 10 + [False, False])
    assert artifact_repo.get("c").status == "approved"
    _record(run_repo, artifact_repo, [False])
    assert artifact_repo.get("c").status == "degraded"
    assert len(run_repo.audit_trail) == 1
    entry = run_repo.audit_trail[0]
    assert entry.action == "degrade_artifact" and entry.subject == "c"
    assert entry.detail["consecutive_failures"] == "3"


def test_a_success_breaks_the_failure_streak() -> None:
    run_repo, artifact_repo = _repos("approved")
    _record(run_repo, artifact_repo, [False, False, True, False, False])
    assert artifact_repo.get("c").status == "approved"
    assert run_repo.audit_trail == []


def test_a_draft_is_never_degraded() -> None:
    run_repo, artifact_repo = _repos("draft")
    _record(run_repo, artifact_repo, [False] * 5)
    assert artifact_repo.get("c").status == "draft"
