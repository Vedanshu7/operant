import pytest

import operant.domain.approval as approval
import operant.domain.errors as errors
import operant.domain.events as events
import operant.domain.models.results as results
import operant.domain.models.runs as runs
import operant.infra.db.engine as engine
import operant.infra.repositories.runs as rrruns
import operant.ports.repositories as repos


@pytest.fixture
def repo() -> rrruns.SqlRunRepository:
    database = engine.Database.open(None)
    database.create_all()
    return rrruns.SqlRunRepository(database)


def _run(run_id: str = "replay-1") -> runs.RunRecord:
    return runs.RunRecord(
        id=run_id,
        kind="replay",
        status="queued",
        vendor_id="parabank",
        capability_id="goalnative",
        tenant="tenant-b",
    )


def test_satisfies_the_port(repo: rrruns.SqlRunRepository) -> None:
    assert isinstance(repo, repos.RunRepository)


def test_create_get_and_status_round_trip(
    repo: rrruns.SqlRunRepository,
) -> None:
    repo.create(_run())
    with pytest.raises(errors.VersionConflictError):
        repo.create(_run())
    result = results.SuccessResult(
        outputs={"currentBalance": "10.45"}, evidence_dir="evidence/replay-1"
    )
    repo.update_status("replay-1", "succeeded", result=result)
    loaded = repo.get("replay-1")
    assert loaded.status == "succeeded"
    assert isinstance(loaded.result, results.SuccessResult)
    assert loaded.result.outputs == {"currentBalance": "10.45"}
    with pytest.raises(errors.NotFoundError):
        repo.get("nope")


def test_list_filters_and_orders_newest_first(
    repo: rrruns.SqlRunRepository,
) -> None:
    repo.create(
        runs.RunRecord(
            id="a",
            kind="replay",
            status="queued",
            vendor_id="parabank",
            created_at="2026-08-23T00:00:00Z",
        )
    )
    repo.create(
        runs.RunRecord(
            id="b",
            kind="discovery",
            status="running",
            vendor_id="notes",
            created_at="2026-08-23T01:00:00Z",
        )
    )
    everything = repo.list(runs.RunFilter())
    assert [r.id for r in everything] == ["b", "a"]
    only_replay = repo.list(runs.RunFilter(kind="replay"))
    assert [r.id for r in only_replay] == ["a"]


def test_approval_intervention_and_clarification_lifecycle(
    repo: rrruns.SqlRunRepository,
) -> None:
    repo.create(_run())
    request = approval.ApprovalRequest(
        kind="mutating", summary="click Transfer", action_kind="click"
    )
    approval_id = repo.open_approval("replay-1", request)
    repo.decide_approval(
        approval_id,
        approval.ApprovalDecision(approved=True, by="console"),
    )
    with pytest.raises(errors.UnknownApprovalError):
        repo.decide_approval("missing", approval.ApprovalDecision(approved=False))
    iv = repo.open_intervention(
        "replay-1",
        runs.InterventionRequest(
            kind="replay", capability="goalnative", goal="g", reason="stuck"
        ),
    )
    repo.update_intervention(iv, "human")
    repo.update_intervention(iv, "resumed", note="fixed", human_actions=["click"])
    with pytest.raises(errors.UnknownInterventionError):
        repo.update_intervention("missing", "abandoned")
    clar = repo.open_clarification("replay-1", "which account?")
    repo.answer_clarification(clar, "12456")
    with pytest.raises(errors.NotFoundError):
        repo.answer_clarification("missing", "x")


def test_stability_accumulates_and_reports(
    repo: rrruns.SqlRunRepository,
) -> None:
    assert repo.stability("cap").runs == 0
    repo.record_stability("cap", "replay-1", succeeded=True)
    updated = repo.record_stability("cap", "replay-2", succeeded=False)
    assert (updated.runs, updated.successes) == (2, 1)
    assert repo.stability("cap").successes == 1


def test_index_event_keeps_hitl_payload_only(
    repo: rrruns.SqlRunRepository,
) -> None:
    repo.create(_run())
    repo.index_event(
        "replay-1",
        events.ReplayStarted(
            summary="started",
            capability="c",
            version=1,
            graph_version=1,
            tenant="tenant-b",
        ),
    )
    repo.index_event(
        "replay-1",
        events.ApprovalRequested(
            kind="mutating", question="click Transfer", summary="approval"
        ),
    )


def test_secret_ref_repository(
    repo: rrruns.SqlRunRepository,
) -> None:
    database = engine.Database.open(None)
    database.create_all()
    refs = rrruns.SqlSecretRefRepository(database)
    assert isinstance(refs, repos.SecretRefRepository)
    refs.upsert(
        runs.SecretRefMeta(
            name="password", backend="env", locator="PARABANK_PASSWORD"
        )
    )
    refs.upsert(
        runs.SecretRefMeta(
            name="password", backend="env", locator="PB_PW", description="pw"
        )
    )
    refs.mark_presence("password", True)
    listed = refs.list()
    assert [m.name for m in listed] == ["password"]
    assert listed[0].locator == "PB_PW" and listed[0].description == "pw"
    refs.delete("password")
    assert refs.list() == []
    with pytest.raises(errors.NotFoundError):
        refs.delete("password")
