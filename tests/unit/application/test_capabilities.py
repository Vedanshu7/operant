"""
commit_recording: the recording -> shared graph + path-query capability seam,
including id remapping through the merge and shared-subgraph reuse.
"""

import pathlib
from typing import Optional, Tuple

import operant.application.capabilities
import operant.application.recorder.recording
import operant.domain.models.digest as digest
import operant.domain.models.graph as graph
import operant.domain.models.targets as targets
import operant.infra.repositories.artifacts as artifact
import operant.infra.repositories.graphs as rggraphs
import tests.support.recording


def _stores(tmp_path: pathlib.Path):
    return (
        rggraphs.FileGraphRepository(tmp_path / "graphs"),
        artifact.FileArtifactRepository(tmp_path / "artifacts"),
    )


def _login_then(
    extra_click: str, extract: Optional[Tuple[str, str]] = None
) -> operant.application.recorder.recording.Recorder:
    recorder = operant.application.recorder.recording.Recorder()
    recorder.start("Login - Acme")
    tests.support.recording.record(
        recorder,
        action=graph.Action(
            kind="fill", value=targets.Value(secret_ref="username")
        ),
        control=digest.Control(
            ref="c1",
            role="text_field",
            name="Username",
            label="",
            path="w>tf",
            box=digest.Box(0.1, 0.1, 0.2, 0.05),
        ),
        description="enter username",
        pre="Login - Acme",
        post="Login - Acme",
    )
    tests.support.recording.record(
        recorder,
        action=graph.Action(kind="click"),
        control=tests.support.recording.control("Log In", "button"),
        description="log in",
        pre="Login - Acme",
        post="Overview - Acme",
    )
    tests.support.recording.record(
        recorder,
        action=graph.Action(kind="click"),
        control=tests.support.recording.control(extra_click),
        description=f"open {extra_click}",
        pre="Overview - Acme",
        post=f"{extra_click} - Acme",
    )
    if extract:
        recorder.record_extraction(*extract)
    return recorder


def test_commit_remaps_and_carries_capability_extract(
    tmp_path: pathlib.Path,
) -> None:
    graphs, artifacts = _stores(tmp_path)
    rec = tests.support.recording.build_recording(
        _login_then("Details", extract=("balance", r"\$([0-9.]+)")),
        {},
        {"balance": "42"},
        capability_id="read-balance",
        goal="read balance",
        run_id="r1",
    )
    cap, merged = operant.application.capabilities.commit_recording(
        rec, graph_store=graphs, artifact_store=artifacts
    )
    node_ids = {n.id for n in merged.nodes}
    edge_ids = {e.id for e in merged.edges}
    assert cap.start_node in node_ids and cap.goal_node in node_ids
    assert cap.extract_at_node in node_ids
    assert set(cap.compiled_path) <= edge_ids
    assert [s.output for s in cap.extract] == ["balance"]
    assert merged.graph_version == 1


def test_second_recording_reuses_shared_login_edges(
    tmp_path: pathlib.Path,
) -> None:
    graphs, artifacts = _stores(tmp_path)
    first = tests.support.recording.build_recording(
        _login_then("Details"), {}, {}, capability_id="a", run_id="r1"
    )
    _, g1 = operant.application.capabilities.commit_recording(
        first, graph_store=graphs, artifact_store=artifacts
    )
    second = tests.support.recording.build_recording(
        _login_then("Reports"), {}, {}, capability_id="b", run_id="r2"
    )
    cap_b, g2 = operant.application.capabilities.commit_recording(
        second, graph_store=graphs, artifact_store=artifacts
    )
    assert len(g2.nodes) == len(g1.nodes) + 1
    assert len(g2.edges) == len(g1.edges) + 1
    shared = [e for e in g2.edges if e.description == "log in"]
    assert len(shared) == 1
    assert shared[0].id in cap_b.compiled_path


def test_extraction_leak_is_structurally_impossible(
    tmp_path: pathlib.Path,
) -> None:
    graphs, artifacts = _stores(tmp_path)
    with_extract = tests.support.recording.build_recording(
        _login_then("Details", extract=("balance", r"\$([0-9.]+)")),
        {},
        {"balance": "42"},
        capability_id="with",
        run_id="r1",
    )
    operant.application.capabilities.commit_recording(
        with_extract, graph_store=graphs, artifact_store=artifacts
    )
    without = tests.support.recording.build_recording(
        _login_then("Details"), {}, {}, capability_id="without", run_id="r2"
    )
    cap, merged = operant.application.capabilities.commit_recording(
        without, graph_store=graphs, artifact_store=artifacts
    )
    assert cap.extract == []
    raw = (
        tmp_path / "graphs" / "acme" / f"v{merged.graph_version}.json"
    ).read_text()
    assert '"extract"' not in raw
