"""
The in-memory fakes structurally satisfy every runtime port.
"""

from __future__ import annotations

import pathlib

import operant.domain.models.llm as llm
import operant.domain.models.runs as runs
import operant.ports.evidence as evidence
import operant.ports.hitl as hitl
import operant.ports.learning as learning
import operant.ports.llm as plllm
import operant.ports.repositories as repos
import operant.ports.surface as surface
import operant.ports.tool as tool
import tests.support.ports as ports


def test_surface_fake_satisfies_protocol() -> None:
    assert isinstance(ports.FakeSurface(), surface.Surface)


def test_tool_fake_satisfies_protocol() -> None:
    assert isinstance(ports.FakeTool(), tool.Tool)


def test_repository_fakes_satisfy_protocols(tmp_path: pathlib.Path) -> None:
    assert isinstance(ports.FakeArtifactRepository(), repos.ArtifactRepository)
    assert isinstance(ports.FakeGraphRepository(), repos.GraphRepository)
    assert isinstance(
        ports.FakeProfileRepository(tmp_path), repos.ProfileRepository
    )
    assert isinstance(ports.FakeRunRepository(), repos.RunRepository)
    assert isinstance(ports.FakeSecretRefRepository(), repos.SecretRefRepository)


def test_run_repository_fake_tracks_stability() -> None:
    repo = ports.FakeRunRepository()
    repo.record_stability("cap", "run-1", succeeded=True)
    track = repo.record_stability("cap", "run-2", succeeded=False)
    assert (track.runs, track.successes) == (2, 1)
    assert repo.stability("other").runs == 0


def test_evidence_fake_satisfies_protocol(tmp_path: pathlib.Path) -> None:
    sink = ports.FakeEvidenceSink(tmp_path)
    assert isinstance(sink, evidence.EvidenceSink)
    sink.event("run_status", status="running")
    assert sink.emitted[0].type == "run_status"


def test_hitl_fakes_satisfy_protocols() -> None:
    assert isinstance(ports.FakeApprover(decision=None), hitl.Approver)
    assert isinstance(ports.FakeClarifier(), hitl.Clarifier)


def test_llm_fake_satisfies_protocol() -> None:
    turn = llm.LlmTurn(
        tool_calls=(llm.ToolCall(id="c1", name="act", arguments="{}"),)
    )
    client = ports.FakeLlmClient([turn])
    assert isinstance(client, plllm.LlmClient)
    answer = client.complete(
        [llm.ChatMessage(role="user", content="go")], tools=[]
    )
    assert answer.tool_calls[0].name == "act"


def test_preference_store_fake_satisfies_protocol() -> None:
    assert isinstance(ports.FakePreferenceStore(), learning.PreferenceStore)


def test_run_filter_defaults_mean_any() -> None:
    criteria = runs.RunFilter()
    assert criteria.status is None
    assert criteria.limit == 50
